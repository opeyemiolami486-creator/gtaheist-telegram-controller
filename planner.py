"""Pure planning helpers for the GTA Heist browser controller."""
from __future__ import annotations
from dataclasses import dataclass
from math import atan2, cos, hypot, pi, sin
from typing import Any

@dataclass(frozen=True)
class Target:
    kind: str
    x: float
    z: float
    priority: float


def _pos(obj: Any) -> tuple[float, float] | None:
    if isinstance(obj, dict):
        x, z = obj.get("x"), obj.get("z")
    else:
        x, z = getattr(obj, "x", None), getattr(obj, "z", None)
    return (float(x), float(z)) if isinstance(x, (int, float)) and isinstance(z, (int, float)) else None


def choose_target(state: dict[str, Any]) -> Target | None:
    """Choose the next useful objective from the exposed game state.

    Priority is: active mission, visible high-value token, cold stash when the
    bag is large, then heist markers. Cops and rug pits are never targets.
    """
    p = _pos(state.get("player"))
    if not p:
        return None
    px, pz = p
    mission = state.get("mission")
    if isinstance(mission, dict):
        mp = _pos(mission)
        if mp:
            return Target("mission", mp[0], mp[1], 1000.0)
    bag = float(state.get("bag") or 0)
    if bag >= 1000:
        for item in state.get("stashes", []) or []:
            sp = _pos(item)
            if sp:
                d = hypot(sp[0] - px, sp[1] - pz)
                return Target("stash", sp[0], sp[1], 900.0 - d)
    best: Target | None = None
    for item in state.get("coins", []) or []:
        pos = _pos(item)
        if not pos:
            continue
        power = str(item.get("userData", {}).get("tok", "")) if isinstance(item, dict) else ""
        bonus = {"$PUMP": 60, "$PEPE": 50, "$WIF": 35, "$BONK": 30}.get(power, 10)
        d = hypot(pos[0] - px, pos[1] - pz)
        candidate = Target("coin", pos[0], pos[1], bonus - d * 0.05)
        if best is None or candidate.priority > best.priority:
            best = candidate
    for kind, item in (("vault", state.get("vault")), ("rug_heist", state.get("rugHeist"))):
        pos = _pos(item)
        if pos and (best is None or 75 > best.priority):
            best = Target(kind, pos[0], pos[1], 75.0)
    return best


def steering(player: dict[str, Any], target: Target | None, *, danger: float = 0.0) -> dict[str, int]:
    """Return normal in-game input flags for a target and threat level."""
    if not target:
        return {"up": 1, "down": 0, "left": 0, "right": 0, "drift": 0, "boost": 1}
    px, pz = float(player.get("x", 0)), float(player.get("z", 0))
    heading = float(player.get("h", 0))
    desired = atan2(target.x - px, target.z - pz)
    delta = (desired - heading + pi) % (2 * pi) - pi
    left = int(delta < -0.12)
    right = int(delta > 0.12)
    brake = int(danger > 0.82 and abs(delta) > 1.2)
    return {"up": 1, "down": brake, "left": left, "right": right,
            "drift": int(abs(delta) > 1.0), "boost": int(danger < 0.65 and abs(delta) < 0.45)}
