#!/usr/bin/env python3
"""Parse saved GTA Heist browser traces into player, cop, and close-approach data.

The output is telemetry-derived. Cop appearance timestamps mean first observed in
browser snapshots, and collision coordinates are sampled or linearly interpolated
estimates—not authoritative game collision events.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from statistics import mean, median
from typing import Any


PLAYER_COLUMNS = [
    "run_id", "source", "frame_index", "time_basis", "time", "wall_elapsed",
    "player_x", "player_z", "heading", "recorded_speed", "velocity_x",
    "velocity_z", "velocity_magnitude", "position_delta_speed", "position_delta_dt",
    "picks", "missions", "bag", "target_kind", "target_x", "target_z",
    "stuck_frames", "cop_count", "nearest_cop_index", "nearest_cop_x",
    "nearest_cop_z", "nearest_cop_distance", "stored_nearest_cop_distance",
]
SPAWN_COLUMNS = [
    "run_id", "source", "cop_track", "cop_slot", "generation",
    "last_absent_time", "first_observed_time", "time_basis", "cop_x", "cop_z",
    "player_x", "player_z", "distance_to_player",
]
COLLISION_COLUMNS = [
    "run_id", "source", "method", "cop_track", "time_basis", "time",
    "distance", "player_x", "player_z", "cop_x", "cop_z",
    "frame_a", "frame_b", "threshold",
]


def number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def get_time(frame: dict[str, Any]) -> tuple[float | None, str]:
    for key, basis in (("simulationElapsed", "simulation"), ("wallElapsed", "wall")):
        value = number(frame.get(key))
        if value is not None:
            return value, basis
    # The controller records performance.now() in milliseconds as frameTime.
    value = number(frame.get("frameTime"))
    return (value / 1000.0, "performance_ms") if value is not None else (None, "unknown")


def position(obj: Any) -> tuple[float, float] | None:
    if not isinstance(obj, dict):
        return None
    x, z = number(obj.get("x")), number(obj.get("z"))
    return (x, z) if x is not None and z is not None else None


def dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def fmt(value: float | None) -> float | str:
    """Leave numbers unrounded in JSON/CSV output; use empty cells for missing data."""
    return value if value is not None else ""


def closest_segment_approach(
    player_a: tuple[float, float], player_b: tuple[float, float],
    cop_a: tuple[float, float], cop_b: tuple[float, float],
    time_a: float, time_b: float,
) -> dict[str, float]:
    """Estimate the closest relative approach between two sampled positions."""
    r0 = (player_a[0] - cop_a[0], player_a[1] - cop_a[1])
    r1 = (player_b[0] - cop_b[0], player_b[1] - cop_b[1])
    dr = (r1[0] - r0[0], r1[1] - r0[1])
    denom = dr[0] * dr[0] + dr[1] * dr[1]
    alpha = 0.0 if denom <= 1e-18 else max(0.0, min(1.0, -(r0[0] * dr[0] + r0[1] * dr[1]) / denom))
    px = player_a[0] + alpha * (player_b[0] - player_a[0])
    pz = player_a[1] + alpha * (player_b[1] - player_a[1])
    cx = cop_a[0] + alpha * (cop_b[0] - cop_a[0])
    cz = cop_a[1] + alpha * (cop_b[1] - cop_a[1])
    return {
        "alpha": alpha,
        "time": time_a + alpha * (time_b - time_a),
        "distance": math.hypot(px - cx, pz - cz),
        "player_x": px, "player_z": pz, "cop_x": cx, "cop_z": cz,
    }


def extract_trace(
    document: dict[str, Any], run_id: str, source: str, *, collision_radius: float = 1.5,
) -> dict[str, Any]:
    """Extract normalized telemetry tables from one saved result document."""
    run = document.get("run", document)
    if not isinstance(run, dict):
        raise ValueError("result does not contain a run object")
    raw_history = run.get("history") or run.get("frames") or []
    if not isinstance(raw_history, list):
        raise ValueError("run history/frames is not a list")

    normalized: list[dict[str, Any]] = []
    for index, frame in enumerate(raw_history):
        if not isinstance(frame, dict):
            continue
        player = position(frame.get("player"))
        if not player:
            continue
        t, basis = get_time(frame)
        cops = [position(cop) for cop in (frame.get("cops") or [])]
        cops = [cop for cop in cops if cop is not None]
        normalized.append({
            "index": index, "frame": frame, "time": t, "basis": basis,
            "player": player, "cops": cops,
        })

    player_rows: list[dict[str, Any]] = []
    spawn_rows: list[dict[str, Any]] = []
    collision_rows: list[dict[str, Any]] = []
    seen_generation: dict[int, int] = {}
    previous_slots: set[int] = set()
    previous_frame_time: float | None = None
    previous_by_slot: dict[int, dict[str, Any]] = {}
    previous_player: tuple[float, float] | None = None
    previous_time: float | None = None
    speed_samples: list[float] = []
    derived_samples: list[float] = []
    minimum: dict[str, Any] | None = None

    for item in normalized:
        frame = item["frame"]
        t = item["time"]
        basis = item["basis"]
        p = item["player"]
        dt = (t - previous_time) if t is not None and previous_time is not None else None
        delta_speed = dist(p, previous_player) / dt if dt is not None and dt > 0 and previous_player else None

        velocity = frame.get("velocity") or {}
        vx, vz = number(velocity.get("x")), number(velocity.get("z"))
        if vx is None:
            vx = number(frame.get("velocity_x"))
        if vz is None:
            vz = number(frame.get("velocity_z"))
        velocity_magnitude = math.hypot(vx, vz) if vx is not None and vz is not None else None
        recorded_speed = number(frame.get("speed"))
        if recorded_speed is None:
            recorded_speed = velocity_magnitude
        if recorded_speed is not None:
            speed_samples.append(recorded_speed)
        if delta_speed is not None:
            derived_samples.append(delta_speed)

        cop_distances = [(dist(p, cop), slot, cop) for slot, cop in enumerate(item["cops"])]
        nearest = min(cop_distances, default=None, key=lambda row: row[0])
        stored_nearest = number(frame.get("nearestCopDistance"))
        calculated_nearest = nearest[0] if nearest else stored_nearest
        if calculated_nearest is not None:
            candidate = {
                "distance": calculated_nearest, "time": t, "time_basis": basis,
                "player_x": p[0], "player_z": p[1],
                "cop_x": nearest[2][0] if nearest else None,
                "cop_z": nearest[2][1] if nearest else None,
                "cop_index": nearest[1] if nearest else None,
                "frame_index": item["index"],
            }
            if minimum is None or candidate["distance"] < minimum["distance"]:
                minimum = candidate
            if nearest and calculated_nearest <= collision_radius:
                collision_rows.append({
                    "run_id": run_id, "source": source, "method": "sampled_frame",
                    "cop_track": f"slot-{nearest[1]}", "time_basis": basis, "time": t,
                    "distance": calculated_nearest, "player_x": p[0], "player_z": p[1],
                    "cop_x": nearest[2][0], "cop_z": nearest[2][1],
                    "frame_a": item["index"], "frame_b": item["index"],
                    "threshold": collision_radius,
                })

        slots = set(range(len(item["cops"])))
        for slot in sorted(slots):
            cop = item["cops"][slot]
            if slot not in previous_slots:
                generation = seen_generation.get(slot, 0) + 1
                seen_generation[slot] = generation
                spawn_rows.append({
                    "run_id": run_id, "source": source,
                    "cop_track": f"slot-{slot}-g{generation}", "cop_slot": slot,
                    "generation": generation,
                    "last_absent_time": previous_frame_time,
                    "first_observed_time": t, "time_basis": basis,
                    "cop_x": cop[0], "cop_z": cop[1],
                    "player_x": p[0], "player_z": p[1],
                    "distance_to_player": dist(p, cop),
                })
            prior = previous_by_slot.get(slot)
            if prior and t is not None and prior["time"] is not None:
                segment_dt = t - prior["time"]
                # Large gaps weaken interpolation and may hide reordering; keep it bounded.
                if 0 < segment_dt <= 1.5:
                    approach = closest_segment_approach(
                        prior["player"], p, prior["cop"], cop,
                        prior["time"], t,
                    )
                    if approach["distance"] <= collision_radius:
                        generation = seen_generation.get(slot, 1)
                        collision_rows.append({
                            "run_id": run_id, "source": source,
                            "method": "linear_segment_estimate",
                            "cop_track": f"slot-{slot}-g{generation}",
                            "time_basis": basis, "time": approach["time"],
                            "distance": approach["distance"],
                            "player_x": approach["player_x"],
                            "player_z": approach["player_z"],
                            "cop_x": approach["cop_x"], "cop_z": approach["cop_z"],
                            "frame_a": prior["frame_index"], "frame_b": item["index"],
                            "threshold": collision_radius,
                        })
            previous_by_slot[slot] = {
                "time": t, "player": p, "cop": cop, "frame_index": item["index"],
            }

        target = frame.get("target") or {}
        inp = frame.get("input") or {}
        p_row = {
            "run_id": run_id, "source": source, "frame_index": item["index"],
            "time_basis": basis, "time": fmt(t), "wall_elapsed": fmt(number(frame.get("wallElapsed"))),
            "player_x": p[0], "player_z": p[1], "heading": fmt(number(frame.get("h", (frame.get("player") or {}).get("h")))),
            "recorded_speed": fmt(recorded_speed), "velocity_x": fmt(vx), "velocity_z": fmt(vz),
            "velocity_magnitude": fmt(velocity_magnitude), "position_delta_speed": fmt(delta_speed),
            "position_delta_dt": fmt(dt), "picks": frame.get("picks", ""),
            "missions": frame.get("missions", ""), "bag": frame.get("bag", ""),
            "target_kind": target.get("kind", ""), "target_x": fmt(number(target.get("x"))),
            "target_z": fmt(number(target.get("z"))), "stuck_frames": frame.get("stuckFrames", ""),
            "cop_count": len(item["cops"]),
            "nearest_cop_index": nearest[1] if nearest else "",
            "nearest_cop_x": fmt(nearest[2][0] if nearest else None),
            "nearest_cop_z": fmt(nearest[2][1] if nearest else None),
            "nearest_cop_distance": fmt(calculated_nearest),
            "stored_nearest_cop_distance": fmt(stored_nearest),
        }
        for key in ("up", "down", "left", "right", "drift", "boost"):
            p_row[f"input_{key}"] = inp.get(key, "")
        player_rows.append(p_row)

        previous_slots = slots
        for missing_slot in set(previous_by_slot) - slots:
            previous_by_slot.pop(missing_slot, None)
        previous_frame_time = t
        if t is not None:
            previous_time = t
            previous_player = p

    summary = {
        "run_id": run_id,
        "source": source,
        "frames_parsed": len(player_rows),
        "time_start": normalized[0]["time"] if normalized else None,
        "time_end": normalized[-1]["time"] if normalized else None,
        "time_basis": normalized[-1]["basis"] if normalized else None,
        "recorded_speed_samples": len(speed_samples),
        "recorded_speed_min": min(speed_samples) if speed_samples else None,
        "recorded_speed_median": median(speed_samples) if speed_samples else None,
        "recorded_speed_mean": mean(speed_samples) if speed_samples else None,
        "recorded_speed_max": max(speed_samples) if speed_samples else None,
        "position_delta_speed_samples": len(derived_samples),
        "position_delta_speed_min": min(derived_samples) if derived_samples else None,
        "position_delta_speed_median": median(derived_samples) if derived_samples else None,
        "position_delta_speed_mean": mean(derived_samples) if derived_samples else None,
        "position_delta_speed_max": max(derived_samples) if derived_samples else None,
        "cop_appearances_first_observed": len(spawn_rows),
        "closest_observed_approach": minimum,
        "collision_threshold": collision_radius,
        "collision_candidate_count": len(collision_rows),
        "terminal_reason": (run.get("last") or {}).get("terminalReason"),
        "terminal_kind": (run.get("last") or {}).get("kind"),
        "caught_flag": (run.get("last") or {}).get("caught"),
        "cop_tracking_note": "Cop slots are array indices; identities are inferred across adjacent frames, not guaranteed game entity IDs.",
        "collision_note": "Close-approach coordinates are sampled observations or linear interpolation estimates, not authoritative collision callbacks.",
    }
    return {
        "summary": summary,
        "player_rows": player_rows,
        "spawn_rows": spawn_rows,
        "collision_rows": collision_rows,
    }


def input_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(path.rglob("*.json"))
    raise FileNotFoundError(path)


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def analyze(paths: list[Path], out_dir: Path, collision_radius: float) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    summaries: list[dict[str, Any]] = []
    all_players: list[dict[str, Any]] = []
    all_spawns: list[dict[str, Any]] = []
    all_collisions: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for path in paths:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(document, dict):
                raise ValueError("top-level JSON value is not an object")
            run_id = path.parent.name if path.name == "last-result.json" else path.stem
            result = extract_trace(document, run_id, str(path), collision_radius=collision_radius)
            if not result["player_rows"]:
                continue
            summaries.append(result["summary"])
            all_players.extend(result["player_rows"])
            all_spawns.extend(result["spawn_rows"])
            all_collisions.extend(result["collision_rows"])
        except Exception as exc:  # keep processing other saved traces
            errors.append({"source": str(path), "error": str(exc)})

    write_csv(out_dir / "player_frames.csv", all_players, PLAYER_COLUMNS + [
        "input_up", "input_down", "input_left", "input_right", "input_drift", "input_boost",
    ])
    write_csv(out_dir / "cop_appearances.csv", all_spawns, SPAWN_COLUMNS)
    write_csv(out_dir / "collision_candidates.csv", all_collisions, COLLISION_COLUMNS)
    report = {
        "traces_analyzed": len(summaries),
        "errors": errors,
        "collision_threshold": collision_radius,
        "notes": [
            "Appearance time is the first browser snapshot containing a cop slot; if a preceding snapshot exists, it bounds first observation, not necessarily the server spawn instant.",
            "Speed is reported both from the trace's recorded speed/velocity and from frame-to-frame position deltas over simulation time.",
            "Collision candidates are distance-threshold estimates; the browser trace does not expose an authoritative collision event callback.",
        ],
        "traces": summaries,
    }
    (out_dir / "summary.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, default=Path("run-artifacts"),
                        help="a result JSON file or directory to search recursively (default: run-artifacts)")
    parser.add_argument("--out-dir", type=Path, default=Path("run-artifacts/trace-analysis"),
                        help="directory for CSV and JSON outputs")
    parser.add_argument("--collision-radius", type=float, default=1.5,
                        help="distance threshold for collision candidates, in game units (default: 1.5)")
    args = parser.parse_args()
    if args.collision_radius <= 0:
        parser.error("--collision-radius must be positive")
    report = analyze(input_files(args.path), args.out_dir, args.collision_radius)
    print(json.dumps({
        "traces_analyzed": report["traces_analyzed"],
        "errors": report["errors"],
        "output_dir": str(args.out_dir),
        "outputs": ["summary.json", "player_frames.csv", "cop_appearances.csv", "collision_candidates.csv"],
    }, indent=2))


if __name__ == "__main__":
    main()
