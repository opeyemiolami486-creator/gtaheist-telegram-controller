import unittest
from planner import Target, choose_target, steering

class PlannerTests(unittest.TestCase):
    def test_mission_beats_tokens(self):
        t = choose_target({"player":{"x":0,"z":0},"mission":{"x":10,"z":0},"coins":[{"x":1,"z":1}]})
        self.assertEqual(t.kind, "mission")

    def test_stash_is_selected_when_bag_is_ready(self):
        t = choose_target({"player":{"x":0,"z":0},"bag":2000,"stashes":[{"x":4,"z":4}],"coins":[{"x":1,"z":1}]})
        self.assertEqual(t.kind, "stash")

    def test_steering_turns_right(self):
        flags = steering({"x":0,"z":0,"h":0}, Target("coin", 10, 10, 1))
        self.assertEqual(flags["right"], 1)
        self.assertEqual(flags["up"], 1)

if __name__ == "__main__":
    unittest.main()
