#!/usr/bin/env python3
"""Probe the public GTA Heist engine without submitting a run.

The probe blocks /api/start and /api/run, starts the game's own offline mode,
and drives only the exposed normal key flags. It is intentionally diagnostic;
it does not fabricate results or call the live score endpoint.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright


URL = "https://www.gtaheist.fun/game/?play=1"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=5.0)
    ap.add_argument("--out", default="run-artifacts/official-engine-probe.json")
    ap.add_argument("--rng-seed", type=int, default=None)
    args = ap.parse_args()
    if args.seconds <= 0 or args.seconds > 30:
        raise SystemExit("--seconds must be between 0 and 30")

    samples: list[dict] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        blocked: list[str] = []
        if args.rng_seed is not None:
            seed = args.rng_seed & 0xFFFFFFFF
            page.add_init_script(
                f"""(() => {{
                  let s = {seed};
                  Math.random = () => {{
                    s = (Math.imul(1664525, s) + 1013904223) >>> 0;
                    return s / 4294967296;
                  }};
                }})()"""
            )

        def route_handler(route):
            url = route.request.url
            if "/api/start" in url or "/api/run" in url:
                blocked.append(url)
                route.abort()
            else:
                route.continue_()

        page.route("**/*", route_handler)
        page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_function("() => window.__dc && window.__dc.S", timeout=60_000)
        page.wait_for_timeout(500)
        page.evaluate("() => { window.__dc.go(); window.__ghP = 1; window.__dc.keys.up = 1; }")
        steps = max(1, round(args.seconds * 60))
        for step in range(steps):
            sample = page.evaluate(
                """() => {
                  const d = window.__dc, s = d && d.S;
                  if (!d || !s) return {ready: false};
                  return {
                    ready: true,
                    t: s.t, time: s.time, run: !!s.run, over: !!s.over,
                    x: s.p?.x, z: s.p?.z, vx: s.p?.vx, vz: s.p?.vz,
                    heading: s.p?.h, speed: s.speed, bag: s.bag,
                    want: s.want, stars: s.stars, picks: s.picks,
                    missions: s.dh?.missions || 0, cops: d.cops?.length || 0,
                    coins: d.coins?.length || 0, rugs: d.rugs?.length || 0,
                    keys: {...d.keys}, caught: !!s.caught, kind: s.kind || null,
                  };
                }"""
            )
            samples.append(sample)
            page.evaluate("() => window.__dc.update(1 / 60)")
            if sample.get("over") and not sample.get("run"):
                break
        page.evaluate("() => { if (window.__dc?.keys) for (const k of Object.keys(window.__dc.keys)) window.__dc.keys[k] = 0; }")
        browser.close()

    result = {
        "url": URL,
        "submitted": False,
        "blocked_api_requests": blocked,
        "rng_seed": args.rng_seed,
        "samples": samples,
        "sample_count": len(samples),
        "final": samples[-1] if samples else None,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"out": str(out), "submitted": False, "samples": len(samples), "final": result["final"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
