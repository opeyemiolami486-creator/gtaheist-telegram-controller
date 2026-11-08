import unittest

from runner import captured_run_events
from planner import (
    Target,
    choose_target,
    cop_avoidance_heading,
    invalidate_target,
    recovery_inputs,
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
        t = choose_target({"player": {"x": 0, "z": 0}, "bag": 2000, "stashes": [{"x": 4, "z": 4}], "coins": [{"x": 1, "z": 1}]})
        self.assertEqual(t.kind, "stash")

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
        self.assertEqual(flags["down"], 1)

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


if __name__ == "__main__":
    unittest.main()
