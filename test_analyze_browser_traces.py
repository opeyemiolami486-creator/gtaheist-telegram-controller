import unittest

from analyze_browser_traces import closest_segment_approach, extract_trace


class BrowserTraceAnalyzerTests(unittest.TestCase):
    def test_extracts_recorded_and_position_delta_speed(self):
        result = extract_trace({"run": {"history": [
            {"simulationElapsed": 0.0, "player": {"x": 0, "z": 0, "h": 0},
             "speed": 0, "velocity": {"x": 0, "z": 0}, "cops": []},
            {"simulationElapsed": 0.5, "player": {"x": 1, "z": 0, "h": 0},
             "speed": 2, "velocity": {"x": 2, "z": 0}, "cops": []},
            {"simulationElapsed": 1.0, "player": {"x": 2, "z": 0, "h": 0},
             "speed": 2, "velocity": {"x": 2, "z": 0}, "cops": []},
        ]}}, "test-run", "synthetic.json")
        rows = result["player_rows"]
        self.assertEqual(rows[1]["recorded_speed"], 2)
        self.assertEqual(rows[1]["velocity_magnitude"], 2)
        self.assertEqual(rows[1]["position_delta_speed"], 2)
        self.assertEqual(rows[1]["position_delta_dt"], 0.5)
        self.assertEqual(result["summary"]["recorded_speed_max"], 2)

    def test_reports_first_observed_cop_time_as_interval(self):
        result = extract_trace({"run": {"history": [
            {"simulationElapsed": 3.0, "player": {"x": 0, "z": 0}, "cops": []},
            {"simulationElapsed": 3.1, "player": {"x": 1, "z": 0},
             "cops": [{"x": 1, "z": 4}]},
        ]}}, "test-run", "synthetic.json")
        self.assertEqual(len(result["spawn_rows"]), 1)
        spawn = result["spawn_rows"][0]
        self.assertEqual(spawn["last_absent_time"], 3.0)
        self.assertEqual(spawn["first_observed_time"], 3.1)
        self.assertEqual(spawn["distance_to_player"], 4)

    def test_extracts_sampled_close_approach_coordinates(self):
        result = extract_trace({"run": {"history": [
            {"simulationElapsed": 0, "player": {"x": 0, "z": 0}, "cops": []},
            {"simulationElapsed": 1, "player": {"x": 1, "z": 0}, "cops": [{"x": 1, "z": 2}]},
            {"simulationElapsed": 2, "player": {"x": 2, "z": 0}, "cops": [{"x": 2, "z": 0}]},
        ]}}, "test-run", "synthetic.json", collision_radius=1.0)
        self.assertTrue(any(row["method"] == "sampled_frame" for row in result["collision_rows"]))
        self.assertEqual(result["summary"]["closest_observed_approach"]["player_x"], 2)
        self.assertEqual(result["summary"]["closest_observed_approach"]["cop_x"], 2)

    def test_interpolates_minimum_between_samples(self):
        result = closest_segment_approach(
            (0, 0), (0, 0), (-2, 0), (2, 0), 10, 12,
        )
        self.assertEqual(result["time"], 11)
        self.assertEqual(result["distance"], 0)
        self.assertEqual(result["player_x"], 0)
        self.assertEqual(result["cop_x"], 0)


if __name__ == "__main__":
    unittest.main()
