import unittest
from math import cos

from runner import captured_run_events, summarize_controller_diagnostics
from planner import (
    Target,
    choose_target,
    cop_avoidance_heading,
    emergency_escape_heading,
    invalidate_target,
    objective_aware_escape_heading,
    recovery_inputs,
    retain_target,
    should_boost,
    simulation_complete,
    steering,
    target_is_safe,
    watchdog_expired,
)


class PlannerTests(unittest.TestCase):
    def test_mission_beats_tokens(self):
        t = choose_target({"player": {"x": 0, "z": 0}, "mission": {"x": 10, "z": 0}, "coins": [{"x": 1, "z": 1}]})
        self.assertEqual(t.kind, "mission")

    def test_stash_is_selected_when_bag_is_ready(self):
        t = choose_target({"player": {"x": 0, "z": 0}, "bag": 6000, "stashes": [{"x": 4, "z": 4}], "coins": [{"x": 1, "z": 1}]})
        self.assertEqual(t.kind, "stash")

    def test_reachable_high_value_pickup_beats_distant_vault(self):
        state = {
            "player": {"x": -46, "z": -106}, "bag": 1000,
            "coins": [
                {"x": -44.5, "z": -165.8, "userData": {"tok": "$WIF"}},
                {"x": -95.1, "z": -44.5, "userData": {"tok": "$PUMP"}},
            ],
            "vault": {"x": -35.5, "z": 0},
            "rugHeist": {"x": -42, "z": 219},
        }
        target = choose_target(state)
        self.assertEqual(target.kind, "coin")
        self.assertAlmostEqual(target.x, -95.1, places=1)

    def test_retained_target_is_stable_without_material_improvement(self):
        current = Target("coin", 10, 0, 0)
        state = {"player": {"x": 0, "z": 0}, "coins": [{"x": 10, "z": 0}, {"x": 11, "z": 1}],
                 "vault": {"x": 80, "z": 0}}
        selected = retain_target(state, current)
        self.assertEqual(selected.kind, "coin")
        self.assertAlmostEqual(selected.x, 10)

    def test_reselects_when_retained_target_disappears(self):
        current = Target("coin", 10, 0, 0)
        state = {"player": {"x": 0, "z": 0}, "coins": [{"x": 50, "z": 0}],
                 "vault": {"x": 18, "z": 0}}
        selected = retain_target(state, current)
        self.assertEqual(selected.kind, "vault")

    def test_unsafe_retained_target_is_abandoned(self):
        current = Target("coin", 10, 0, 0)
        state = {"player": {"x": 0, "z": 0}, "coins": [{"x": 10, "z": 0}],
                 "cops": [{"x": 10, "z": 5}], "vault": {"x": -60, "z": 0}}
        selected = retain_target(state, current)
        self.assertIsNotNone(selected)
        self.assertNotEqual((selected.kind, selected.x), (current.kind, current.x))

    def test_cop_avoidance_heading_points_away(self):
        heading = cop_avoidance_heading({"x": 0, "z": 0}, [{"x": 0, "z": 20}])
        self.assertAlmostEqual(abs(heading), 3.141592653589793, places=5)

    def test_unsafe_target_is_not_selected(self):
        state = {"player": {"x": 0, "z": 0}, "mission": {"x": 20, "z": 0}, "cops": [{"x": 20, "z": 3}], "coins": [{"x": 0, "z": 80}]}
        self.assertEqual(choose_target(state).kind, "coin")
        self.assertFalse(target_is_safe(state, Target("mission", 20, 0, 1000)))

    def test_target_invalidation(self):
        target = Target("coin", 10, 0, 1)
        self.assertTrue(invalidate_target({"player": {"x": 0, "z": 0}, "cops": [{"x": 10, "z": 0}]}, target))
        self.assertFalse(invalidate_target({"player": {"x": 0, "z": 0}, "cops": []}, target))

    def test_stuck_recovery_reverses_and_turns(self):
        flags = recovery_inputs({"x": 0, "z": 0}, stuck_frames=12)
        self.assertEqual(flags["down"], 1)
        self.assertEqual(flags["boost"], 0)
        self.assertEqual(flags["drift"], 1)

    def test_safe_boost_decision(self):
        self.assertTrue(should_boost(danger=0.1, turn_delta=0.1, wanted=0))
        self.assertFalse(should_boost(danger=0.7, turn_delta=0.1, wanted=0))
        self.assertFalse(should_boost(danger=0.1, turn_delta=0.1, wanted=2))

    def test_steering_avoids_cop_and_disables_boost(self):
        flags = steering({"x": 0, "z": 0, "h": 0}, Target("coin", 0, 40, 1), danger=0.9, cops=[{"x": 0, "z": 20}], wanted=2)
        self.assertEqual(flags["boost"], 0)
        self.assertEqual(flags["up"], 1)
        self.assertEqual(flags["down"], 0)

    def test_steering_turn_flags_match_official_heading_sign(self):
        negative_delta = steering({"x": 0, "z": 0, "h": 0}, Target("coin", -20, 20, 10))
        positive_delta = steering({"x": 0, "z": 0, "h": 0}, Target("coin", 20, 20, 10))
        self.assertEqual((negative_delta["left"], negative_delta["right"]), (0, 1))
        self.assertEqual((positive_delta["left"], positive_delta["right"]), (1, 0))

    def test_steering_blends_cop_avoidance_without_dropping_target(self):
        flags = steering({"x": 0, "z": 0, "h": 0}, Target("coin", 0, 100, 10),
                         cops=[{"x": 0, "z": 40}])
        self.assertEqual(flags["left"], 1)
        self.assertEqual(flags["right"], 0)

    def test_steering_overrides_target_only_in_immediate_collision_range(self):
        flags = steering({"x": 0, "z": 0, "h": 0}, Target("coin", 0, 100, 10),
                         cops=[{"x": 0, "z": 15}])
        self.assertEqual(flags["left"], 1)
        self.assertEqual(flags["right"], 0)

    def test_aligned_escape_uses_boost_without_braking(self):
        flags = steering({"x": 0, "z": 0, "h": 0, "speed": 10}, None,
                         danger=0.78, cops=[{"x": 0, "z": -20}], wanted=1)
        self.assertEqual(flags["up"], 1)
        self.assertEqual(flags["down"], 0)
        self.assertEqual(flags["boost"], 1)

    def test_emergency_escape_points_directly_away_from_close_cop(self):
        heading = emergency_escape_heading({"x": 0, "z": 0}, {"x": 0, "z": 10})
        self.assertIsNotNone(heading)
        self.assertAlmostEqual(abs(heading), 3.141592653589793, places=3)

    def test_distant_cop_does_not_break_objective_tracking(self):
        heading = objective_aware_escape_heading(
            {"x": 0, "z": 0}, {"x": 0, "z": 100}, [{"x": 0, "z": -150}]
        )
        self.assertAlmostEqual(heading, 0.0, places=6)

    def test_approaching_cop_adds_sidestep_while_tracking_target(self):
        heading = objective_aware_escape_heading(
            {"x": 0, "z": 0}, {"x": 0, "z": 100}, [{"x": 0, "z": 40}]
        )
        target_alignment = cos(heading)
        self.assertGreater(abs(heading), 0.2)
        self.assertGreater(target_alignment, 0.4)

    def test_immediate_collision_range_overrides_objective(self):
        heading = objective_aware_escape_heading(
            {"x": 0, "z": 0}, {"x": 0, "z": 100}, [{"x": 0, "z": 15}]
        )
        self.assertLess(cos(heading), 0.0)

    def test_simulation_clock_termination(self):
        self.assertFalse(simulation_complete(9.9, 10))
        self.assertTrue(simulation_complete(10, 10))
        self.assertTrue(simulation_complete(0, 10, terminal=True))

    def test_time_limit_watchdog(self):
        self.assertFalse(watchdog_expired(30, 10))
        self.assertTrue(watchdog_expired(160, 10))

    def test_exact_run_diagnostic_capture(self):
        requests, responses = captured_run_events({
            "requests": [{"url": "https://api.example/api/start", "payload": "start"},
                         {"url": "https://api.example/api/run", "payload": '{"dur":24.9}'}],
            "responses": [{"url": "https://api.example/api/run", "status": 200, "body": '{"verified":true}'}],
        })
        self.assertEqual(requests[0]["payload"], '{"dur":24.9}')
        self.assertEqual(responses[0]["body"], '{"verified":true}')

    def test_pickup_and_terminal_diagnostic_summary(self):
        summary = summarize_controller_diagnostics({
            "events": [
                {"type": "pickup", "count": 2},
                {"type": "mission_progress", "count": 1},
                {"type": "target_switch"},
                {"type": "cop_proximity", "band": "danger", "distance": 40, "simulationElapsed": 8},
                {"type": "escape_state", "state": "escape", "reason": "approach-or-distance", "distance": 50, "simulationElapsed": 7},
                {"type": "recovery_start", "attempt": 1, "phase": 0, "simulationElapsed": 4},
            ],
            "history": [{"nearestCopDistance": 40, "threat": 0.55, "speed": 1,
                         "belowSpeed": True, "copClosingSpeed": 12,
                         "timeToContact": 3.3, "simulationElapsed": 8}],
            "last": {"terminalReason": "caught", "kind": "busted", "caught": True},
        })
        self.assertEqual(summary["pickups_observed"], 2)
        self.assertEqual(summary["missions_observed"], 1)
        self.assertEqual(summary["target_switches"], 1)
        self.assertEqual(summary["minimum_cop_distance"], 40)
        self.assertEqual(summary["terminal_reason"], "caught")
        self.assertEqual(summary["first_escape_time"], 7)
        self.assertEqual(summary["recovery_attempts"], 1)
        self.assertEqual(summary["low_speed_fraction"], 1.0)
        self.assertEqual(summary["maximum_cop_closing_speed"], 12)


if __name__ == "__main__":
    unittest.main()
