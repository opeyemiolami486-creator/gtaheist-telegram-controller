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
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from playwright.async_api import async_playwright

from runner import API, CONTROLLER_JS, SITE, captured_run_events, summarize_controller_diagnostics

CAPTURE_JS = r"""
() => {
  window.__ghDiagnostics = {requests: [], responses: [], visibility: document.visibilityState};
  const original = window.fetch;
  window.fetch = async (...args) => {
    const input = args[0], init = args[1] || {};
    const url = typeof input === 'string' ? input : (input && input.url) || String(input);
    window.__ghDiagnostics.requests.push({url, method: init.method || (input && input.method) || 'GET',
      hasBody: !!(init.body || (input && input.body)), at: performance.now()});
    const response = await original(...args);
    window.__ghDiagnostics.responses.push({url, status: response.status, at: performance.now()});
    return response;
  };
}
"""

BLOCKED = {"/api/start", "/api/run", "/api/bind"}
OBSERVED_API_PATHS = {"/api/start", "/api/run", "/api/bind"}
PINNED_SITE = "https://www.gtaheist.fun/game"
PINNED_ASSETS = {
    "https://www.gtaheist.fun/game/": "a328e728da7a705a600d648839b8288f214cd6b7fbc5f6e7ea792e943031b3cd",
    "https://www.gtaheist.fun/game/campaign.js": "ff7eb566745a5a2a1316f65637c8e1996f0089aebd3c43b86aee03f7344581e0",
    "https://www.gtaheist.fun/game/share-card.mjs": "411c6bbf34722c6fa8174d0177bb38aeae37a1ba22e9ee973a4876b504cb4453",
}


def _canonical_asset_url(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def verify_asset_content(url: str, content: bytes) -> dict[str, Any]:
    """Validate one response body against its exact pinned official URL/hash."""
    canonical_url = _canonical_asset_url(url)
    expected = PINNED_ASSETS.get(canonical_url)
    if expected is None:
        raise RuntimeError(f"Refusing unpinned client asset: {canonical_url}")
    actual = hashlib.sha256(content).hexdigest()
    if actual != expected:
        raise RuntimeError(
            f"Official client asset changed; refusing to run: {canonical_url} "
            f"(expected {expected}, got {actual})"
        )
    return {"sha256": actual, "bytes": len(content)}


def verify_official_assets() -> dict[str, dict[str, Any]]:
    """Verify pinned official client bytes and refuse unknown/custom bundles."""
    if SITE.rstrip("/") != PINNED_SITE:
        raise RuntimeError(f"Refusing unpinned game URL: {SITE}")
    verified: dict[str, dict[str, Any]] = {}
    for url, expected in PINNED_ASSETS.items():
        request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=30) as response:
            content = response.read()
        verified[url] = verify_asset_content(url, content)
    return verified


def _api_path(url: str) -> str | None:
    path = urlsplit(url).path.rstrip("/")
    return path if path in OBSERVED_API_PATHS else None


def _safe_response_fields(body: str) -> dict[str, Any]:
    """Keep only non-secret response fields useful for lifecycle diagnosis."""
    try:
        value = json.loads(body)
    except (TypeError, ValueError):
        return {"json": False}
    if not isinstance(value, dict):
        return {"json": True, "type": type(value).__name__}
    safe = {key: value[key] for key in ("ok", "verified", "error", "status") if key in value}
    return {"json": True, **safe}


def _redacted_request_event(request: Any) -> dict[str, Any] | None:
    path = _api_path(request.url)
    if path is None:
        return None
    return {
        "path": path,
        "method": request.method,
        "resource_type": request.resource_type,
        "has_body": bool(request.post_data),
    }


def _redact_sensitive(value: Any) -> Any:
    """Remove credentials and server-issued identifiers from saved telemetry."""
    if isinstance(value, dict):
        return {
            key: _redact_sensitive(item)
            for key, item in value.items()
            if key not in {"wallet", "nonce", "code"}
        }
    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]
    return value


async def run_controller(*, username: str, wallet: str, target_score: int,
                         time_limit: float, submit: bool, out_dir: str,
                         headed: bool = False) -> dict[str, Any]:
    verified_assets = verify_official_assets()
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
        context = await browser.new_context(
            viewport={"width": 640, "height": 360}, device_scale_factor=1, service_workers="block"
        )
        page = await context.new_page()
        blocked: list[str] = []
        browser_assets: dict[str, dict[str, Any]] = {}
        asset_errors: list[str] = []
        browser_requests: list[dict[str, Any]] = []
        browser_responses: list[dict[str, Any]] = []
        response_tasks: set[asyncio.Task[Any]] = set()

        def on_request(request):
            event = _redacted_request_event(request)
            if event:
                browser_requests.append(event)

        async def capture_response(response):
            path = _api_path(response.url)
            if path is None:
                return
            body = ""
            try:
                body = await response.text()
            except Exception:
                pass
            browser_responses.append({
                "path": path,
                "status": response.status,
                "resource_type": response.request.resource_type,
                "fields": _safe_response_fields(body),
            })

        def on_response(response):
            task = asyncio.create_task(capture_response(response))
            response_tasks.add(task)
            task.add_done_callback(response_tasks.discard)

        page.on("request", on_request)
        page.on("response", on_response)

        async def route_handler(route):
            request_url = route.request.url
            canonical_url = _canonical_asset_url(request_url)
            parsed = urlsplit(request_url)
            path = parsed.path.rstrip("/")
            if not submit and path in BLOCKED:
                blocked.append(route.request.url)
                await route.abort()
            elif canonical_url in PINNED_ASSETS:
                try:
                    response = await route.fetch()
                    if _canonical_asset_url(response.url) != canonical_url:
                        raise RuntimeError(f"Pinned asset redirected: {canonical_url} -> {response.url}")
                    body = await response.body()
                    browser_assets[canonical_url] = verify_asset_content(canonical_url, body)
                    await route.fulfill(response=response, body=body)
                except Exception as exc:
                    asset_errors.append(f"{canonical_url}: {exc}")
                    await route.abort()
            else:
                await route.continue_()

        await page.route("**/*", route_handler)
        await page.goto(SITE, wait_until="domcontentloaded", timeout=60_000)
        if asset_errors:
            raise RuntimeError("Browser loaded an unverified official client asset: " + "; ".join(asset_errors))
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
        required_assets = {
            "https://www.gtaheist.fun/game/",
            "https://www.gtaheist.fun/game/campaign.js",
        }
        if asset_errors or not required_assets.issubset(browser_assets):
            raise RuntimeError(
                "Browser did not load all pinned core assets; "
                f"verified={sorted(browser_assets)}, errors={asset_errors}"
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
        # Give the official client a bounded opportunity to perform its own
        # terminal callback. Do not manufacture a request or call an endpoint.
        await page.wait_for_timeout(2_000)
        if response_tasks:
            await asyncio.gather(*tuple(response_tasks), return_exceptions=True)
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
        controller["summary"] = summarize_controller_diagnostics(controller)
        result = _redact_sensitive({
            "verified_assets": verified_assets,
            "browser_verified_assets": browser_assets,
            "submit_requested": submit,
            "submitted": bool(submit and responses),
            "username": username,
            "wallet_supplied": bool(wallet),
            "target_score": target_score,
            "time_limit": time_limit,
            "blocked_requests": blocked,
            "browser_api_requests": browser_requests,
            "browser_api_responses": browser_responses,
            "run": controller,
        })
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
        "summary": result["run"].get("summary"),
        "final": result["run"].get("last"),
    }, indent=2))


if __name__ == "__main__":
    main()
