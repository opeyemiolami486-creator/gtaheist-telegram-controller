#!/usr/bin/env python3
"""Headless controller for the official GTA Heist browser engine.

Default mode is a non-submitting dry run. The controller drives only the
public game's normal window.__dc.keys interface and lets the official client
produce its own /api/run payload. Use --submit only when an official server
run and score submission are explicitly desired.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright

from runner import API, CONTROLLER_JS, SITE, captured_run_events

CAPTURE_JS = r"""
() => {
  window.__ghDiagnostics = {requests: [], responses: [], visibility: document.visibilityState};
  const original = window.fetch;
  window.fetch = async (...args) => {
    const input = args[0], init = args[1] || {};
    const url = typeof input === 'string' ? input : (input && input.url) || String(input);
    let payload = init.body;
    if (payload == null && input && input.body) payload = input.body;
    window.__ghDiagnostics.requests.push({url, method: init.method || (input && input.method) || 'GET',
      payload: typeof payload === 'string' ? payload : null, at: performance.now()});
    const response = await original(...args);
    let body = '';
    try { body = await response.clone().text(); } catch (_) {}
    window.__ghDiagnostics.responses.push({url, status: response.status, body, at: performance.now()});
    return response;
  };
}
"""

BLOCKED = {"/api/start", "/api/run", "/api/bind"}


async def run_controller(*, username: str, wallet: str, target_score: int,
                         time_limit: float, submit: bool, out_dir: str,
                         headed: bool = False) -> dict[str, Any]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=not headed,
            args=[
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--disable-features=CalculateNativeWinOcclusion",
            ],
        )
        context = await browser.new_context(viewport={"width": 640, "height": 360}, device_scale_factor=1)
        page = await context.new_page()
        blocked: list[str] = []

        async def route_handler(route):
            path = route.request.url.split("?", 1)[0].rstrip("/")
            if not submit and any(path.endswith(x) for x in BLOCKED):
                blocked.append(route.request.url)
                await route.abort()
            else:
                await route.continue_()

        await page.route("**/*", route_handler)
        await page.goto(SITE, wait_until="domcontentloaded", timeout=60_000)
        await page.evaluate(
            "([name, wallet]) => { localStorage.setItem('gtd_name', name); "
            "localStorage.setItem('gtd_mode', 'pro'); localStorage.setItem('gth_low', '1'); "
            "if (wallet) localStorage.setItem('gth_wallet', wallet); }",
            [username, wallet],
        )
        await page.reload(wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_function(
            "() => window.__dc && document.querySelector('#start') && !document.querySelector('#start').disabled",
            timeout=60_000,
        )
        await page.evaluate("() => window.__dc.setMode && window.__dc.setMode('pro')")
        await page.evaluate(CAPTURE_JS)
        await page.locator('#diff button[data-d="wanted"]').click(force=True)
        await page.locator('#start').click()
        await page.wait_for_function("() => window.__dc && window.__dc.S && window.__dc.S.run", timeout=20_000)
        if submit:
            await page.wait_for_function(
                "() => window.__dc.S.srv && window.__dc.S.srv.code && window.__dc.S.srv.nonce",
                timeout=15_000,
            )
        controller = await page.evaluate(CONTROLLER_JS, {"targetScore": target_score, "timeLimit": time_limit})
        diagnostics = await page.evaluate(
            """() => ({diag: window.__ghDiagnostics || null, state: (() => {
              const s = window.__dc && window.__dc.S || {};
              return {time:s.time, t:s.t, run:!!s.run, over:!!s.over, verified:s.verified,
                      code:s.code || (s.srv && s.srv.code) || null};
            })()})"""
        )
        controller["diagnostics"] = diagnostics
        requests, responses = captured_run_events(diagnostics.get("diag"))
        controller["run_request_payloads"] = requests
        controller["run_responses"] = responses
        result = {
            "submit_requested": submit,
            "submitted": bool(submit and responses),
            "username": username,
            "wallet": wallet,
            "target_score": target_score,
            "time_limit": time_limit,
            "blocked_requests": blocked,
            "run": controller,
        }
        (out / "last-result.json").write_text(json.dumps(result, indent=2) + "\n")
        await browser.close()
        return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--username", default="anonymous")
    ap.add_argument("--wallet", default="")
    ap.add_argument("--target", type=int, default=10**12)
    ap.add_argument("--time-limit", type=float, default=10.0)
    ap.add_argument("--out-dir", default="run-artifacts/dc-controller-dry-run")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--submit", action="store_true", help="allow the official /api/start and /api/run flow")
    args = ap.parse_args()
    if args.time_limit <= 0 or args.time_limit > 90:
        ap.error("--time-limit must be between 0 and 90 seconds")
    if args.target < 1:
        ap.error("--target must be positive")
    if args.submit and not args.wallet:
        ap.error("--wallet is required with --submit")
    result = asyncio.run(run_controller(
        username=args.username,
        wallet=args.wallet,
        target_score=args.target,
        time_limit=args.time_limit,
        submit=args.submit,
        out_dir=args.out_dir,
        headed=args.headed,
    ))
    print(json.dumps({
        "submit_requested": result["submit_requested"],
        "submitted": result["submitted"],
        "blocked_requests": len(result["blocked_requests"]),
        "run_requests": len(result["run"].get("run_request_payloads", [])),
        "run_responses": len(result["run"].get("run_responses", [])),
        "final": result["run"].get("last"),
    }, indent=2))


if __name__ == "__main__":
    main()
