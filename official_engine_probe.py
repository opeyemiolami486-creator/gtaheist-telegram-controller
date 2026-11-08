#!/usr/bin/env python3
"""Instrument the pinned public GTA Heist engine without submitting a run.

The probe blocks all gameplay/account API paths, drives only normal key flags,
and advances the official window.__dc.update(dt) function. It records
before/input/after transitions and supports repeatable crossing profiles for
observing cop contact, bust-zone behavior, boost, drift, and boundary effects.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

from official_client_snapshot import verify_live_against_snapshot


URL = "https://www.gtaheist.fun/game/?play=1"
DT = 1 / 60
DIFFICULTIES = {"chill", "degen", "wanted"}
PROFILES = {"straight_boost", "left_drift", "right_drift", "brake_reverse"}


def _distance(a: dict[str, Any] | None, b: dict[str, Any] | None) -> float | None:
    if not a or not b or a.get("x") is None or b.get("x") is None:
        return None
    return math.hypot(float(a["x"]) - float(b["x"]), float(a["z"]) - float(b["z"]))


def _nearest(player: dict[str, Any], cops: list[dict[str, Any]]) -> dict[str, Any] | None:
    ranked = []
    for cop in cops:
        d = _distance(player, cop)
        if d is not None:
            ranked.append((d, cop))
    if not ranked:
        return None
    d, cop = min(ranked, key=lambda item: item[0])
    return {"distance": d, **cop}


def _transition(before: dict[str, Any], after: dict[str, Any], keys: dict[str, int]) -> dict[str, Any]:
    before_player = {"x": before.get("x"), "z": before.get("z")}
    after_player = {"x": after.get("x"), "z": after.get("z")}
    nearest_before = _nearest(before_player, before.get("cops", []))
    nearest_after = _nearest(after_player, after.get("cops", []))
    before_distance = nearest_before["distance"] if nearest_before else None
    after_distance = nearest_after["distance"] if nearest_after else None
    closing_speed = None
    if before_distance is not None and after_distance is not None:
        closing_speed = (before_distance - after_distance) / DT
    ttc = None
    if after_distance is not None and closing_speed is not None and closing_speed > 0:
        ttc = after_distance / closing_speed
    relative_player_speed = math.hypot(float(after.get("vx") or 0), float(after.get("vz") or 0))
    boundary_limit = 218.6
    boundary_proximity = None
    if after.get("x") is not None and after.get("z") is not None:
        boundary_proximity = min(
            boundary_limit - abs(float(after["x"])),
            boundary_limit - abs(float(after["z"])),
        )
    return {
        "dt": DT,
        "input": keys,
        "boost_input": bool(keys.get("boost")),
        "boost_timer": after.get("boostT"),
        "before": before,
        "after": after,
        "cop_closing_speed": closing_speed,
        "time_to_contact": ttc,
        "nearest_cop_distance": after_distance,
        "boundary_proximity": boundary_proximity,
        "player_speed_vector_magnitude": relative_player_speed,
        "bust_zone": bool(after_distance is not None and after_distance < 7.5),
        "cop_contact_candidate": bool(after_distance is not None and after_distance < 3.9),
        "crossed_or_overlapped_cop": bool(
            before_distance is not None and after_distance is not None
            and min(before_distance, after_distance) < 3.9
        ),
    }


def profile_keys(profile: str, step: int) -> dict[str, int]:
    """Return ordinary input flags for a repeatable crossing profile."""
    keys = {"up": 0, "down": 0, "left": 0, "right": 0, "drift": 0, "boost": 0}
    if profile == "straight_boost":
        keys.update(up=1, boost=1)
    elif profile == "left_drift":
        keys.update(up=1, left=1, drift=1, boost=1)
    elif profile == "right_drift":
        keys.update(up=1, right=1, drift=1, boost=1)
    elif profile == "brake_reverse":
        if step < 180:
            keys.update(up=1, boost=1)
        elif step < 240:
            keys.update(down=1, drift=1)
        else:
            keys.update(up=1, right=1, boost=1)
    else:
        raise ValueError(f"unknown profile: {profile}")
    return keys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--out", default="run-artifacts/official-engine-probe.json")
    ap.add_argument("--rng-seed", type=int, default=12345)
    ap.add_argument("--difficulty", choices=sorted(DIFFICULTIES), default="wanted")
    ap.add_argument("--profile", choices=sorted(PROFILES), default="straight_boost")
    ap.add_argument("--snapshot-dir", default="official-client")
    args = ap.parse_args()
    if args.seconds <= 0 or args.seconds > 30:
        raise SystemExit("--seconds must be between 0 and 30")
    # Fail closed before browser interaction if the local snapshot or live public
    # bytes no longer match the pinned Step-1 client.
    verify_live_against_snapshot(args.snapshot_dir)

    transitions: list[dict[str, Any]] = []
    blocked: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
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
            if any(path in url for path in ("/api/start", "/api/run", "/api/bind")):
                blocked.append(url)
                route.abort()
            else:
                route.continue_()

        page.route("**/*", route_handler)
        page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_function("() => window.__dc && window.__dc.S", timeout=60_000)
        page.evaluate(
            """(difficulty) => {
              const d = window.__dc;
              d.setDiff(difficulty);
              d.reset();
              d.go();
              window.__ghP = 1;
            }""",
            args.difficulty,
        )
        steps = max(1, round(args.seconds / DT))
        for step in range(steps):
            keys = profile_keys(args.profile, step)
            transition = page.evaluate(
                """(keys) => {
                  const d = window.__dc, s = d && d.S;
                  if (!d || !s) return {ready: false, input: keys};
                  const snapshot = () => ({
                    t: s.t, time: s.time, run: !!s.run, over: !!s.over,
                    x: s.p?.x, z: s.p?.z, vx: s.p?.vx, vz: s.p?.vz,
                    heading: s.p?.h, speed: s.speed, hp: s.p?.hp,
                    bag: s.bag, bank: s.bank, want: s.want, stars: s.stars,
                    picks: s.picks, missions: s.dh?.missions || 0,
                    caught: !!s.caught, kind: s.kind || null,
                    boostT: s.boostT, target: d.marker?.position ? {
                      x: d.marker.position.x, z: d.marker.position.z
                    } : null,
                    cops: (d.cops || []).map(c => ({
                      x: c.x, z: c.z, h: c.h, v: c.v, leave: !!c.leave
                    })),
                    coins: d.coins?.length || 0,
                    rugs: d.rugs?.length || 0,
                    terminal: {running: !!s.run, over: !!s.over, caught: !!s.caught, kind: s.kind || null}
                  });
                  const before = snapshot();
                  for (const [k, v] of Object.entries(keys)) d.keys[k] = v;
                  d.update(1 / 60);
                  const after = snapshot();
                  return {ready: true, before, after, input: {...d.keys}};
                }""",
                keys,
            )
            if not transition.get("ready"):
                transitions.append(transition)
                break
            transitions.append(_transition(transition["before"], transition["after"], transition["input"]))
            if transition["after"].get("over") and not transition["after"].get("run"):
                break
        page.evaluate("() => { if (window.__dc?.keys) for (const k of Object.keys(window.__dc.keys)) window.__dc.keys[k] = 0; }")
        browser.close()

    result = {
        "url": URL,
        "submitted": False,
        "api_blocked": True,
        "blocked_api_requests": blocked,
        "rng_seed": args.rng_seed,
        "difficulty": args.difficulty,
        "profile": args.profile,
        "dt": DT,
        "transition_count": len(transitions),
        "transitions": transitions,
        "final": transitions[-1]["after"] if transitions and transitions[-1].get("after") else None,
        "metrics": {
            "minimum_cop_distance": min((x["nearest_cop_distance"] for x in transitions if x.get("nearest_cop_distance") is not None), default=None),
            "maximum_cop_closing_speed": max((x["cop_closing_speed"] for x in transitions if x.get("cop_closing_speed") is not None), default=None),
            "minimum_time_to_contact": min((x["time_to_contact"] for x in transitions if x.get("time_to_contact") is not None), default=None),
            "bust_zone_frames": sum(bool(x.get("bust_zone")) for x in transitions),
            "cop_contact_candidate_frames": sum(bool(x.get("cop_contact_candidate")) for x in transitions),
            "crossed_or_overlapped_frames": sum(bool(x.get("crossed_or_overlapped_cop")) for x in transitions),
            "minimum_boundary_proximity": min((x["boundary_proximity"] for x in transitions if x.get("boundary_proximity") is not None), default=None),
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"out": str(out), "submitted": False, "transitions": len(transitions), "metrics": result["metrics"], "final": result["final"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
