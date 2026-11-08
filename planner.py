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
    reward: float = 0.0


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


def emergency_escape_heading(player: dict[str, Any], cop: Any, *, side: int = 1) -> float | None:
    """Choose a hard escape/tangent heading when a cop is already close."""
    pp, cp = _pos(player), _pos(cop)
    if not pp or not cp:
        return None
    away = atan2(pp[0] - cp[0], pp[1] - cp[1])
    return away


def objective_aware_escape_heading(
    player: dict[str, Any], target: Any | None, cops: Iterable[Any], *,
    immediate_range: float = 22.0, influence_radius: float = 100.0,
    repulsion_gain: float = 0.85,
) -> float | None:
    """Blend attraction to the objective with smooth, multi-cop repulsion.

    The objective remains an active force outside ``immediate_range``. Cops
    ahead of the route add both a repulsive and a tangential component, which
    steers around a closing cop instead of simply reversing the goal vector.
    Inside the immediate range, objective attraction is suppressed entirely.
    """
    pp = _pos(player)
    if not pp:
        return None
    tp = _pos(target) if target is not None else None
    goal_x, goal_z = (tp[0] - pp[0], tp[1] - pp[1]) if tp else (0.0, 0.0)
    goal_length = hypot(goal_x, goal_z)
    if goal_length > 1e-9:
        goal_x, goal_z = goal_x / goal_length, goal_z / goal_length
    else:
        goal_x = goal_z = 0.0

    cop_list = [c for c in cops if _pos(c)]
    immediate = any(_distance(player, cop) < immediate_range for cop in cop_list)
    force_x, force_z = (0.0, 0.0) if immediate else (goal_x, goal_z)
    nearest_away: tuple[float, float] | None = None

    span = max(1e-9, influence_radius - immediate_range)
    for cop in cop_list:
        cp = _pos(cop)
        dx, dz = pp[0] - cp[0], pp[1] - cp[1]
        distance = hypot(dx, dz)
        if distance <= 1e-9:
            away_x, away_z = 0.0, -1.0
        else:
            away_x, away_z = dx / distance, dz / distance
        if nearest_away is None or distance < nearest_distance:
            nearest_away, nearest_distance = (away_x, away_z), distance
        if distance >= influence_radius:
            continue

        proximity = max(0.0, min(1.0, (influence_radius - distance) / span))
        strength = repulsion_gain * proximity * proximity
        if goal_length > 1e-9:
            toward_x, toward_z = -away_x, -away_z
            alignment = max(0.0, min(1.0, goal_x * toward_x + goal_z * toward_z))
            # If a cop lies along the goal ray, add a deterministic sidestep
            # chosen away from the cop's side of the route.
            cross = goal_x * toward_z - goal_z * toward_x
            side = 1.0 if cross >= 0 else -1.0
            tangent_x, tangent_z = -away_z * side, away_x * side
        else:
            alignment = 0.0
            tangent_x = tangent_z = 0.0
        force_x += strength * (away_x + alignment * tangent_x)
        force_z += strength * (away_z + alignment * tangent_z)

    if hypot(force_x, force_z) <= 1e-9:
        if nearest_away is None or (not immediate and nearest_distance >= influence_radius):
            return None
        force_x, force_z = nearest_away
    return atan2(force_x, force_z)


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


def _target_present(state: dict[str, Any], target: Target) -> bool:
    """Check whether an exposed objective still exists in the current snapshot."""
    def near(items: Iterable[Any], radius: float = 8.0) -> bool:
        return any(_distance(target, item) <= radius for item in items or [])

    if target.kind == "mission":
        return near([state.get("mission")])
    if target.kind == "coin":
        return near(state.get("coins", []))
    if target.kind == "stash":
        return float(state.get("bag") or 0) >= 5000 and near(state.get("stashes", []))
    if target.kind == "vault":
        return not state.get("heist") and near([state.get("vault")])
    if target.kind == "rug_heist":
        return not state.get("rugDone") and near([state.get("rugHeist")])
    return False


def _objective_utility(state: dict[str, Any], kind: str, target: Any) -> float:
    """Estimate value after travel distance and visible police exposure."""
    player = state.get("player")
    distance = _distance(player, target)
    base = {"mission": 140.0, "stash": 165.0, "vault": 105.0, "rug_heist": 95.0}.get(kind, 0.0)
    if kind == "coin":
        base = float(target.get("reward") or 70.0) if isinstance(target, dict) else 70.0
    utility = base / (1.0 + distance / 100.0)
    utility -= threat_score(state) * 20.0
    cop_distances = [_distance(target, cop) for cop in state.get("cops", []) or []]
    if cop_distances:
        utility -= max(0.0, 80.0 - min(cop_distances)) * 0.3
    return utility


def invalidate_target(state: dict[str, Any], target: Target | None, *, max_distance: float = 260.0) -> bool:
    """Return true when a retained target should be discarded this frame."""
    if not target or not target_is_safe(state, target):
        return True
    player = _pos(state.get("player"))
    return bool(player and _distance(player, target) > max_distance and state.get("roadblock"))


def choose_target(state: dict[str, Any]) -> Target | None:
    """Choose the safest useful objective from exposed official game state."""
    player = _pos(state.get("player"))
    if not player or threat_score(state) >= 0.92:
        return None
    px, pz = player

    candidates: list[Target] = []
    mission = _pos(state.get("mission"))
    if mission:
        candidates.append(Target("mission", mission[0], mission[1], 0.0))
    bag = float(state.get("bag") or 0)
    if bag >= 5000:
        for item in state.get("stashes", []) or []:
            pos = _pos(item)
            if pos:
                candidates.append(Target("stash", pos[0], pos[1], 0.0))
    for item in state.get("coins", []) or []:
        pos = _pos(item)
        if not pos:
            continue
        power = str(item.get("userData", {}).get("tok", "")) if isinstance(item, dict) else ""
        reward = {"$PUMP": 120.0, "$PEPE": 105.0, "$WIF": 90.0, "$BONK": 80.0}.get(power, 70.0)
        candidates.append(Target("coin", pos[0], pos[1], 0.0, reward))
    for kind, item in (("vault", state.get("vault")), ("rug_heist", state.get("rugHeist"))):
        pos = _pos(item)
        if pos and not state.get("heist" if kind == "vault" else "rugDone"):
            candidates.append(Target(kind, pos[0], pos[1], 0.0))
    safe = [
        Target(t.kind, t.x, t.z, _objective_utility(state, t.kind, t.__dict__), t.reward)
        for t in candidates if target_is_safe(state, t)
    ]
    return max(safe, key=lambda target: target.priority) if safe else None


def retain_target(state: dict[str, Any], current: Target | None, *,
                  switch_margin: float = 8.0, switch_ratio: float = 0.15) -> Target | None:
    """Retain a still-present safe target unless a materially better one appears."""
    if threat_score(state) >= 0.92:
        return None
    best = choose_target(state)
    if current is None or not target_is_safe(state, current) or not _target_present(state, current):
        return best
    current_score = _objective_utility(state, current.kind, current.__dict__)
    refreshed = Target(current.kind, current.x, current.z, current_score, current.reward)
    if best is None:
        return refreshed
    if best.kind == current.kind and _distance(best, current) <= 8.0:
        return best
    margin = max(switch_margin, abs(current_score) * switch_ratio)
    return best if best.priority > current_score + margin else refreshed


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
    heading = float(player.get("h", 0))
    cop_choices = [(cop, _distance(player, cop)) for cop in cops if _pos(cop) and _pos(player)]
    nearest = min(cop_choices, key=lambda item: item[1]) if cop_choices else None
    immediate = bool(nearest and nearest[1] < 22.0)
    if stuck_frames >= 12 and not immediate:
        return recovery_inputs(player, stuck_frames=stuck_frames)
    desired = objective_aware_escape_heading(player, target, cops)
    if desired is None:
        return {"up": 1, "down": 0, "left": 0, "right": 0, "drift": 0, "boost": 0}
    delta = (desired - heading + pi) % (2 * pi) - pi
    emergency = bool(nearest and nearest[1] < 75)
    brake = int(not emergency and danger > 0.82 and abs(delta) > 1.2)
    escape_boost = bool(nearest and nearest[1] < 100 and wanted < 2 and abs(delta) < 0.5)
    # In the official engine, left increments heading and right decrements it.
    return {"up": 1, "down": int(brake), "left": int(delta > 0.12), "right": int(delta < -0.12),
            "drift": int(abs(delta) > 1.0), "boost": int(escape_boost or should_boost(danger=danger, turn_delta=delta, wanted=wanted))}
