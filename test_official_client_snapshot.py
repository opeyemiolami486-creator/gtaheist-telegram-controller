import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import official_client_snapshot as snapshot


class OfficialClientSnapshotTests(unittest.TestCase):
    def _pinned_contents(self):
        values = {}
        for name, url, pinned in snapshot.ASSETS:
            # The production pins are immutable; tests replace them with fixture hashes.
            content = f"fixture:{name}".encode()
            values[url] = content
        return values

    def test_download_writes_manifest_and_verify_round_trips(self):
        contents = self._pinned_contents()
        pins = {url: hashlib.sha256(body).hexdigest() for url, body in contents.items()}
        patched_assets = tuple((name, url, pins[url]) for name, url, _ in snapshot.ASSETS)
        with tempfile.TemporaryDirectory() as tmp, patch.object(snapshot, "ASSETS", patched_assets):
            result = snapshot.download_snapshot(tmp, fetcher=contents.__getitem__)
            self.assertEqual(result["client_hash"], json.loads(Path(tmp, "manifest.json").read_text())["client_hash"])
            self.assertEqual(snapshot.verify_local_snapshot(tmp)["client_hash"], result["client_hash"])
            self.assertTrue(Path(tmp, "game.html").is_file())
            self.assertTrue(Path(tmp, "campaign.js").is_file())
            self.assertTrue(Path(tmp, "share-card.mjs").is_file())

    def test_local_tamper_fails_closed(self):
        contents = self._pinned_contents()
        pins = {url: hashlib.sha256(body).hexdigest() for url, body in contents.items()}
        patched_assets = tuple((name, url, pins[url]) for name, url, _ in snapshot.ASSETS)
        with tempfile.TemporaryDirectory() as tmp, patch.object(snapshot, "ASSETS", patched_assets):
            snapshot.download_snapshot(tmp, fetcher=contents.__getitem__)
            Path(tmp, "campaign.js").write_bytes(b"tampered")
            with self.assertRaisesRegex(RuntimeError, "differs from immutable pin"):
                snapshot.verify_local_snapshot(tmp)

    def test_upstream_change_does_not_overwrite_existing_snapshot(self):
        contents = self._pinned_contents()
        pins = {url: hashlib.sha256(body).hexdigest() for url, body in contents.items()}
        patched_assets = tuple((name, url, pins[url]) for name, url, _ in snapshot.ASSETS)
        with tempfile.TemporaryDirectory() as tmp, patch.object(snapshot, "ASSETS", patched_assets):
            snapshot.download_snapshot(tmp, fetcher=contents.__getitem__)
            changed = dict(contents)
            changed[snapshot.ASSETS[1][1]] = b"changed upstream"
            with self.assertRaisesRegex(RuntimeError, "Official client asset changed"):
                snapshot.download_snapshot(tmp, fetcher=changed.__getitem__)


if __name__ == "__main__":
    unittest.main()
