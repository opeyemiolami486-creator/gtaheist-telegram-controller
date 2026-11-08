import hashlib
import unittest
from unittest.mock import patch

import dc_controller


class AssetPinTests(unittest.TestCase):
    def test_production_pin_manifest_is_not_silently_changed(self):
        self.assertEqual(
            dc_controller.PINNED_ASSETS,
            {
                "https://www.gtaheist.fun/game/": "a328e728da7a705a600d648839b8288f214cd6b7fbc5f6e7ea792e943031b3cd",
                "https://www.gtaheist.fun/game/campaign.js": "ff7eb566745a5a2a1316f65637c8e1996f0089aebd3c43b86aee03f7344581e0",
                "https://www.gtaheist.fun/game/share-card.mjs": "411c6bbf34722c6fa8174d0177bb38aeae37a1ba22e9ee973a4876b504cb4453",
            },
        )

    def test_pinned_assets_are_checked_before_run(self):
        contents = [b"pinned html", b"pinned campaign", b"pinned card"]
        expected = [hashlib.sha256(item).hexdigest() for item in contents]
        pins = dict(zip(dc_controller.PINNED_ASSETS, expected))

        class Response:
            def __init__(self, body):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return self.body

        with patch.object(dc_controller, "PINNED_ASSETS", pins), patch.object(
            dc_controller, "urlopen", side_effect=[Response(x) for x in contents]
        ):
            verified = dc_controller.verify_official_assets()
        self.assertEqual([v["sha256"] for v in verified.values()], expected)
        self.assertEqual([v["bytes"] for v in verified.values()], [len(x) for x in contents])

    def test_changed_asset_fails_closed(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return b"unexpected bundle"

        with patch.object(dc_controller, "urlopen", return_value=Response()):
            with self.assertRaisesRegex(RuntimeError, "asset changed; refusing to run"):
                dc_controller.verify_official_assets()

    def test_actual_browser_response_bytes_are_verified(self):
        content = b"pinned fixture"
        url = "https://www.gtaheist.fun/game/campaign.js"
        pins = {url: hashlib.sha256(content).hexdigest()}
        with patch.object(dc_controller, "PINNED_ASSETS", pins):
            result = dc_controller.verify_asset_content(url + "?cache=1", content)
            self.assertEqual(result["bytes"], len(content))
            with self.assertRaisesRegex(RuntimeError, "asset changed; refusing to run"):
                dc_controller.verify_asset_content(url, b"changed")

    def test_network_failure_does_not_allow_preflight(self):
        with patch.object(dc_controller, "urlopen", side_effect=OSError("offline")):
            with self.assertRaisesRegex(OSError, "offline"):
                dc_controller.verify_official_assets()

    def test_custom_site_fails_closed(self):
        with patch.object(dc_controller, "SITE", "https://example.com/game/"):
            with self.assertRaisesRegex(RuntimeError, "unpinned game URL"):
                dc_controller.verify_official_assets()


if __name__ == "__main__":
    unittest.main()
