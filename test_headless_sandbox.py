import unittest

from headless_sandbox import SandboxConfig, evaluate, run_episode


class HeadlessSandboxTests(unittest.TestCase):
    def test_episode_is_deterministic(self):
        first = run_episode(16)
        second = run_episode(16)
        self.assertEqual({k: first[k] for k in first if k != "telemetry"}, {k: second[k] for k in second if k != "telemetry"})
        self.assertEqual(first["telemetry"], second["telemetry"])

    def test_telemetry_exposes_controller_contract(self):
        result = run_episode(1, SandboxConfig(duration=2.0))
        self.assertGreater(result["telemetry"], [])
        sample = result["telemetry"][0]
        for key in ("time", "player", "input", "target", "nearest_cop_distance", "want", "bag", "bank", "picks", "score"):
            self.assertIn(key, sample)

    def test_benchmark_reports_survival_and_target_rates(self):
        result = evaluate(range(1, 4), SandboxConfig(duration=10.0))
        self.assertEqual(result["episodes"], 3)
        self.assertIn("survival_rate", result)
        self.assertIn("over_7b_rate", result)


if __name__ == "__main__":
    unittest.main()
