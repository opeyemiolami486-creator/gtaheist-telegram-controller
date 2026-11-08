"""Pure planning and timing helpers for the GTA Heist browser controller."""
from __future__ import annotations

from dataclasses import dataclass
from math import atan2, hypot, pi
from typing import Any, Iterable


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


def _distance(a: Any, b: Any) -> float:
    ap, bp = _pos(a), _pos(b)
    return hypot(bp[0] - ap[0], bp[1] - ap[1]) if ap and bp else float("inf")


def nearest_cop(state: dict[str, Any]) -> tuple[dict[str, Any] | Any, float] | None:
    player = state.get("player")
    cops = state.get("cops") or []
    choices = [(cop, _distance(player, cop)) for cop in cops if _pos(cop) and _pos(player)]
    return min(choices, key=lambda item: item[1]) if choices else None


def threat_score(state: dict[str, Any]) -> float:
    """Return a bounded proximity threat score, independent of rendering rate."""
    nearest = nearest_cop(state)
    if not nearest:
        return 0.0
    return max(0.0, min(1.0, 1.0 - nearest[1] / float(state.get("danger_radius") or 90.0)))


def cop_avoidance_heading(player: dict[str, Any], cops: Iterable[Any], danger_radius: float = 62.0) -> float | None:
    """Choose an escape heading, optionally leading away from a cop's velocity."""
    pp = _pos(player)
    if not pp:
        return None
    candidates = [(cop, _distance(player, cop)) for cop in cops if _pos(cop)]
    if not candidates:
        return None
    cop, distance = min(candidates, key=lambda item: item[1])
    if distance >= danger_radius:
        return None
    cp = _pos(cop)
    # Move away from the cop; if velocity is exposed, bias away from its approach vector.
    escape_x, escape_z = pp[0] - cp[0], pp[1] - cp[1]
    vx = float(cop.get("vx", 0) if isinstance(cop, dict) else getattr(cop, "vx", 0) or 0)
    vz = float(cop.get("vz", 0) if isinstance(cop, dict) else getattr(cop, "vz", 0) or 0)
    if vx or vz:
        escape_x += -vx * 0.8
        escape_z += -vz * 0.8
    return atan2(escape_x, escape_z)


def _hazard_positions(state: dict[str, Any]) -> list[Any]:
    values: list[Any] = []
    for key in ("spikes", "roadblocks", "hazards", "rugs", "obstacles"):
        values.extend(state.get(key) or [])
    return values


def target_is_safe(state: dict[str, Any], target: Target | None, *, danger_radius: float = 45.0) -> bool:
    """Reject objectives currently inside a cop or exposed dynamic-hazard zone."""
    if not target or not _pos(state.get("player")):
        return False
    if any(_distance(target, cop) < danger_radius for cop in state.get("cops") or []):
        return False
    if any(_distance(target, hazard) < 14.0 for hazard in _hazard_positions(state)):
        return False
    return True


def invalidate_target(state: dict[str, Any], target: Target | None, *, max_distance: float = 260.0) -> bool:
    """Return true when a retained target should be discarded this frame."""
    if not target or not target_is_safe(state, target):
        return True
    player = _pos(state.get("player"))
    return bool(player and _distance(player, target) > max_distance and state.get("roadblock"))


def choose_target(state: dict[str, Any]) -> Target | None:
    """Choose the safest useful objective from exposed official game state."""
    player = _pos(state.get("player"))
    if not player or threat_score(state) >= 0.92 or state.get("want", 0) >= 3:
        return None
    px, pz = player

    candidates: list[Target] = []
    mission = _pos(state.get("mission"))
    if mission:
        candidates.append(Target("mission", mission[0], mission[1], 1000.0))
    bag = float(state.get("bag") or 0)
    if bag >= 1000:
        for item in state.get("stashes", []) or []:
            pos = _pos(item)
            if pos:
                candidates.append(Target("stash", pos[0], pos[1], 900.0 - hypot(pos[0] - px, pos[1] - pz)))
    for item in state.get("coins", []) or []:
        pos = _pos(item)
        if not pos:
            continue
        power = str(item.get("userData", {}).get("tok", "")) if isinstance(item, dict) else ""
        bonus = {"$PUMP": 60, "$PEPE": 50, "$WIF": 35, "$BONK": 30}.get(power, 10)
        candidates.append(Target("coin", pos[0], pos[1], bonus - hypot(pos[0] - px, pos[1] - pz) * 0.05))
    for kind, item in (("vault", state.get("vault")), ("rug_heist", state.get("rugHeist"))):
        pos = _pos(item)
        if pos:
            candidates.append(Target(kind, pos[0], pos[1], 75.0))
    safe = [target for target in candidates if target_is_safe(state, target)]
    return max(safe, key=lambda target: target.priority) if safe else None


def recovery_inputs(player: dict[str, Any], *, stuck_frames: int = 0) -> dict[str, int]:
    """A deterministic reverse/turn maneuver for low-displacement periods."""
    direction = 1 if (stuck_frames // 20) % 2 == 0 else 0
    return {"up": 0, "down": 1, "left": direction, "right": 1 - direction, "drift": 1, "boost": 0}


def should_boost(*, danger: float, turn_delta: float, wanted: float = 0) -> bool:
    return danger < 0.45 and wanted < 2 and abs(turn_delta) < 0.5


def simulation_complete(simulation_elapsed: float, time_limit: float, *, terminal: bool = False) -> bool:
    return terminal or simulation_elapsed >= time_limit


def watchdog_expired(wall_elapsed: float, time_limit: float, *, multiplier: float = 4.0, grace: float = 120.0) -> bool:
    return wall_elapsed >= max(time_limit * multiplier, time_limit + grace)


def steering(player: dict[str, Any], target: Target | None, *, danger: float = 0.0,
             cops: Iterable[Any] = (), wanted: float = 0.0,
             stuck_frames: int = 0) -> dict[str, int]:
    """Return normal in-game input flags, prioritizing survival over objectives."""
    if stuck_frames >= 12:
        return recovery_inputs(player, stuck_frames=stuck_frames)
    heading = float(player.get("h", 0))
    desired = cop_avoidance_heading(player, cops)
    if desired is None and target:
        desired = atan2(target.x - float(player.get("x", 0)), target.z - float(player.get("z", 0)))
    if desired is None:
        return {"up": 1, "down": 0, "left": 0, "right": 0, "drift": 0, "boost": 0}
    delta = (desired - heading + pi) % (2 * pi) - pi
    brake = int(danger > 0.82 and abs(delta) > 1.2)
    return {"up": 1, "down": brake, "left": int(delta < -0.12), "right": int(delta > 0.12),
            "drift": int(abs(delta) > 1.0), "boost": int(should_boost(danger=danger, turn_delta=delta, wanted=wanted))}
