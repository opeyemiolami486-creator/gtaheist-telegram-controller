"""Clean-room headless sandbox for iterating GTA Heist controller policies.

This is an independent approximation based on observed public telemetry fields. It
contains no game source, assets, network calls, or official score submission path.
Use it to compare policies and tune survival behavior before live validation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import atan2, cos, hypot, pi, sin
from random import Random
from typing import Any

from planner import Target, retain_target, steering


@dataclass(frozen=True)
class SandboxConfig:
    duration: float = 90.0
    dt: float = 0.1
    world_radius: float = 360.0
    pickup_count: int = 90
    mission_count: int = 8
    cop_count: int = 4
    hazard_count: int = 10
    pickup_value: int = 100_000_000
    mission_value: int = 650_000_000
    heist_value: int = 1_500_000_000
    bank_bonus: float = 1.0


@dataclass
class SandboxState:
    time: float = 0.0
    player: dict[str, float] = field(default_factory=lambda: {"x": 0.0, "z": 0.0, "h": 0.0, "vx": 0.0, "vz": 0.0})
    bag: int = 0
    bank: int = 0
    score: int = 0
    want: int = 0
    picks: int = 0
    missions: int = 0
    heist: bool = False
    over: bool = False
    busted: bool = False
    target: Target | None = None
    cops: list[dict[str, float]] = field(default_factory=list)
    coins: list[dict[str, Any]] = field(default_factory=list)
    mission_markers: list[dict[str, float]] = field(default_factory=list)
    stashes: list[dict[str, float]] = field(default_factory=list)
    hazards: list[dict[str, float]] = field(default_factory=list)
    telemetry: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class PolicyConfig:
    danger_radius: float = 62.0
    bank_threshold: int = 700_000_000
    cop_speed: float = 11.0
    player_accel: float = 22.0
    player_drag: float = 0.92
    max_speed: float = 42.0


def _distance(a: dict[str, float], b: dict[str, float]) -> float:
    return hypot(a["x"] - b["x"], a["z"] - b["z"])


def _random_point(rng: Random, radius: float) -> dict[str, float]:
    angle = rng.random() * 2 * pi
    distance = radius * (rng.random() ** 0.5)
    return {"x": cos(angle) * distance, "z": sin(angle) * distance}


def new_episode(seed: int = 1, config: SandboxConfig = SandboxConfig()) -> SandboxState:
    rng = Random(seed)
    state = SandboxState()
    state.coins = [{**_random_point(rng, config.world_radius), "userData": {"tok": rng.choice(["$PUMP", "$PEPE", "$WIF", "$BONK"])}} for _ in range(config.pickup_count)]
    state.mission_markers = [_random_point(rng, config.world_radius) for _ in range(config.mission_count)]
    state.stashes = [_random_point(rng, config.world_radius * 0.65) for _ in range(3)]
    state.hazards = [_random_point(rng, config.world_radius) for _ in range(config.hazard_count)]
    state.cops = [{**_random_point(rng, config.world_radius * 0.7), "vx": 0.0, "vz": 0.0} for _ in range(config.cop_count)]
    return state


def _planner_view(state: SandboxState) -> dict[str, Any]:
    return {"player": state.player, "bag": state.bag, "want": state.want, "coins": state.coins,
            "mission": state.mission_markers[0] if state.mission_markers else None,
            "stashes": state.stashes, "cops": state.cops, "hazards": state.hazards}


def _apply_inputs(state: SandboxState, flags: dict[str, int], cfg: PolicyConfig, dt: float) -> None:
    p = state.player
    turn = (flags.get("right", 0) - flags.get("left", 0)) * 2.5 * dt
    p["h"] = (p["h"] + turn) % (2 * pi)
    thrust = (flags.get("up", 0) - flags.get("down", 0) * 1.4) * cfg.player_accel * dt
    speed = hypot(p["vx"], p["vz"]) * cfg.player_drag + thrust
    speed = max(-8.0, min(cfg.max_speed, speed))
    p["vx"] = sin(p["h"]) * speed
    p["vz"] = cos(p["h"]) * speed
    p["x"] += p["vx"] * dt
    p["z"] += p["vz"] * dt
    if hypot(p["x"], p["z"]) > 360:
        p["x"] *= 0.98
        p["z"] *= 0.98


def _move_cops(state: SandboxState, cfg: PolicyConfig, dt: float) -> None:
    for cop in state.cops:
        dx, dz = state.player["x"] - cop["x"], state.player["z"] - cop["z"]
        d = max(0.001, hypot(dx, dz))
        cop["vx"], cop["vz"] = dx / d * cfg.cop_speed, dz / d * cfg.cop_speed
        cop["x"] += cop["vx"] * dt
        cop["z"] += cop["vz"] * dt


def _collect(state: SandboxState, cfg: SandboxConfig) -> None:
    for coin in state.coins[:]:
        if _distance(state.player, coin) < 10:
            state.coins.remove(coin)
            state.picks += 1
            state.bag += cfg.pickup_value
            state.want = min(5, state.want + (1 if state.picks % 5 == 0 else 0))
    for marker in state.mission_markers[:]:
        if _distance(state.player, marker) < 14:
            state.mission_markers.remove(marker)
            state.missions += 1
            state.bag += cfg.mission_value
            state.want = min(5, state.want + 1)
    for stash in state.stashes[:]:
        if state.bag and _distance(state.player, stash) < 15:
            state.score += int(state.bag * cfg.bank_bonus)
            state.bank += state.bag
            state.bag = 0
            state.stashes.remove(stash)
    if state.missions >= 3 and not state.heist:
        state.heist = True
        state.bag += cfg.heist_value


def _hazard_damage(state: SandboxState) -> None:
    if any(_distance(state.player, hazard) < 8 for hazard in state.hazards):
        state.want = min(5, state.want + 1)


def step(state: SandboxState, cfg: SandboxConfig = SandboxConfig(), policy: PolicyConfig = PolicyConfig()) -> None:
    if state.over:
        return
    view = _planner_view(state)
    state.target = retain_target(view, state.target)
    danger = min(1.0, min((_distance(state.player, cop) for cop in state.cops), default=90.0) / -90.0 + 1.0)
    flags = steering(state.player, state.target, danger=danger, cops=state.cops, wanted=state.want)
    if state.bag >= policy.bank_threshold and state.stashes:
        nearest = min(state.stashes, key=lambda x: _distance(state.player, x))
        state.target = Target("stash", nearest["x"], nearest["z"], 999)
        flags = steering(state.player, state.target, danger=danger, cops=state.cops, wanted=state.want)
    _apply_inputs(state, flags, policy, cfg.dt)
    _move_cops(state, policy, cfg.dt)
    _collect(state, cfg)
    _hazard_damage(state)
    nearest_cop = min((_distance(state.player, cop) for cop in state.cops), default=999)
    if nearest_cop < 7 and state.want >= 2:
        state.busted, state.over = True, True
    state.time += cfg.dt
    if state.time >= cfg.duration:
        state.over = True
    state.telemetry.append({"time": state.time, "player": dict(state.player), "input": dict(flags),
                            "target": state.target.__dict__ if state.target else None,
                            "nearest_cop_distance": nearest_cop, "want": state.want,
                            "bag": state.bag, "bank": state.bank, "picks": state.picks,
                            "missions": state.missions, "score": state.score, "busted": state.busted})


def run_episode(seed: int = 1, config: SandboxConfig = SandboxConfig(), policy: PolicyConfig = PolicyConfig()) -> dict[str, Any]:
    state = new_episode(seed, config)
    while not state.over:
        step(state, config, policy)
    return {"seed": seed, "score": state.score + state.bag, "bank": state.bank, "bag": state.bag,
            "picks": state.picks, "missions": state.missions, "heist": state.heist,
            "busted": state.busted, "elapsed": state.time, "telemetry": state.telemetry}


def evaluate(seeds: range = range(1, 21), config: SandboxConfig = SandboxConfig(), policy: PolicyConfig = PolicyConfig()) -> dict[str, Any]:
    results = [run_episode(seed, config, policy) for seed in seeds]
    scores = [result["score"] for result in results]
    return {"episodes": len(results), "scores": scores, "mean_score": sum(scores) / len(scores),
            "max_score": max(scores), "min_score": min(scores),
            "survival_rate": sum(not result["busted"] for result in results) / len(results),
            "over_7b_rate": sum(result["score"] > 7_000_000_000 for result in results) / len(results),
            "results": results}


if __name__ == "__main__":
    print(evaluate())
