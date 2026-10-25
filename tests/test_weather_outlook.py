import unittest
from unittest.mock import patch
from backend.weather_outlook import score_day, rows, outlook, _cache

class WeatherOutlookTests(unittest.TestCase):
    def row(self, day='2026-01-15', gust=20):
        return dict(date=day, gust=gust, rain=0, snow=0, high=15, low=5)

    def test_seasonality_uses_matching_month_only(self):
        history = [self.row('2025-01-01', 80), self.row('2025-07-01', 10)]
        score = score_day(self.row(gust=55), history)
        self.assertEqual(score['index'], 60)
        self.assertEqual(score['history_days'], 1)
        self.assertEqual(score['historical_hazard_day_fraction'], 1)

    def test_missing_history_and_score_bounds(self):
        self.assertIsNone(score_day(self.row(), [])['historical_hazard_day_fraction'])
        self.assertEqual(score_day(self.row(gust=200), [])['index'], 100)
        self.assertEqual(score_day(self.row(), [])['index'], 0)

    def test_missing_measurements_are_not_zero_filled(self):
        self.assertEqual(list(rows({'time': ['2026-01-01']})), [])

    def test_provider_failure_has_no_invented_predictions(self):
        _cache.clear()
        with patch('backend.weather_outlook.fetch_daily', side_effect=OSError):
            result = outlook()
        self.assertEqual(len(result['errors']), 2)
        self.assertTrue(all(not f['properties']['days'] for f in result['features']))
        _cache.clear()

if __name__ == '__main__':
    unittest.main()
