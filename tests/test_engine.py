import unittest

from concierge import cases, engine, tools


class TransformerAcceptanceRanges(unittest.TestCase):
    """CLAUDE.md acceptance tests: must match exactly."""

    def setUp(self):
        self.case = cases.get_case("transformer_roanoke")

    def test_baseline_range(self):
        result = engine.restoration_effort(self.case)
        self.assertEqual(result["low_hours"], 6.7)
        self.assertEqual(result["high_hours"], 13.5)

    def test_blocked_access_range(self):
        result = engine.restoration_effort(self.case, access_blocked=True)
        self.assertEqual(result["low_hours"], 9.7)
        self.assertEqual(result["high_hours"], 16.5)


class ConfidenceLevels(unittest.TestCase):
    def test_medium_by_default(self):
        case = cases.get_case("transformer_roanoke")
        self.assertEqual(engine.confidence(case)["level"], "Medium")

    def test_low_when_access_blocked(self):
        case = cases.get_case("transformer_roanoke")
        self.assertEqual(engine.confidence(case, access_blocked=True)["level"], "Low")

    def test_low_when_path_invalid(self):
        case = cases.get_case("no_path")
        self.assertEqual(engine.confidence(case)["level"], "Low")


class FallbackRule(unittest.TestCase):
    def test_no_path_triggers_fallback(self):
        case = cases.get_case("no_path")
        result = engine.check_fallback(case)
        self.assertTrue(result["fallback"])
        self.assertTrue(result["reason"])

    def test_valid_case_no_fallback(self):
        case = cases.get_case("transformer_roanoke")
        result = engine.check_fallback(case)
        self.assertFalse(result["fallback"])

    def test_tool_layer_returns_fallback_for_household(self):
        result = tools.get_risk("h12")
        self.assertTrue(result["fallback"]["fallback"])


class RiskBand(unittest.TestCase):
    def test_unrepaired_damage_is_high_regardless_of_storm_setting(self):
        case = cases.get_case("wire_montvale")  # storm_setting = moderate
        self.assertEqual(engine.risk_band(case)["band"], "High")

    def test_calm_no_damage_is_low(self):
        case = cases.get_case("calm_roanoke")
        self.assertEqual(engine.risk_band(case)["band"], "Low")

    def test_repairs_complete_is_low(self):
        case = cases.get_case("transformer_roanoke")
        self.assertEqual(engine.risk_band(case, repairs_complete=True)["band"], "Low")


class RestorationCompleteFlow(unittest.TestCase):
    def test_repairs_complete_zeroes_the_estimate(self):
        case = cases.get_case("transformer_roanoke")
        result = engine.restoration_effort(case, repairs_complete=True)
        self.assertEqual(result["low_hours"], 0.0)
        self.assertEqual(result["high_hours"], 0.0)

    def test_tool_layer_reflects_repairs_complete(self):
        result = tools.get_restoration_estimate("h1", repairs_complete=True)
        self.assertEqual(result["reference_effort_hours"]["value"], 0.0)


class ExtraCrewsShortenMultiJobCase(unittest.TestCase):
    def test_more_crews_do_not_increase_makespan(self):
        case = cases.get_case("wirepole_vinton")
        baseline = engine.restoration_effort(case, extra_crews=0)
        with_crews = engine.restoration_effort(case, extra_crews=2)
        self.assertLessEqual(with_crews["reference_effort_hours"], baseline["reference_effort_hours"])


if __name__ == "__main__":
    unittest.main()
