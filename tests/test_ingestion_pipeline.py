"""Focused invariants for county identity, time conversion and event integration."""

import unittest
import pandas as pd
from src.config import FIPS
from src.fetch_severe_weather import damage, storm_time
from src.fetch_power_outages import aggregate, normalize
from src.common import write_csv
from pathlib import Path
from tempfile import TemporaryDirectory


class PipelineTests(unittest.TestCase):
    def test_roanoke(self):
        self.assertEqual(FIPS["51770"], FIPS["51161"])

    def test_damage(self):
        self.assertEqual(damage("1.50M"), 1500000)
        self.assertEqual(damage("25.00K"), 25000)
        self.assertTrue(pd.isna(damage("unknown")))

    def test_storm_standard_time(self):
        self.assertEqual(storm_time("01-Jul-24 12:00:00", "EST-5").hour, 17)

    def test_gap_breaks_events_and_integrates_bins(self):
        f = pd.DataFrame(
            {
                "fips_code": ["51770"] * 5,
                "timestamp_utc": pd.to_datetime(
                    [
                        "2024-01-01T00:00Z",
                        "2024-01-01T00:15Z",
                        "2024-01-01T01:00Z",
                        "2024-01-01T01:15Z",
                        "2024-01-01T01:30Z",
                    ]
                ),
                "customers_out": [100, 200, 100, 200, 50],
                "source_dataset": ["EAGLE-I"] * 5,
            }
        )
        events = aggregate(f)
        self.assertEqual(len(events), 2)
        self.assertEqual(events.iloc[0].customer_hours_interrupted, 75)
        self.assertEqual(events.iloc[0].duration_minutes, 30)

    def test_filter_fips(self):
        f = pd.DataFrame(
            {
                "fips": ["51770", "00001"],
                "run_start_time": ["2024-01-01"] * 2,
                "sum": [100, 500],
            }
        )
        self.assertEqual(len(normalize(f, "2024-01-01", "2024-01-01")), 1)

    def test_conflicting_archives_fail(self):
        f = pd.DataFrame(
            {
                "fips_code": ["51770"] * 2,
                "timestamp_utc": pd.to_datetime(["2024-01-01T00:00Z"] * 2),
                "customers_out": [100, 200],
                "source_dataset": ["EAGLE-I", "OEDI"],
            }
        )
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            aggregate(f)

    def test_invalid_timestamp_rejected(self):
        f = pd.DataFrame(
            {"city_key": ["ROA"], "fips_code": ["51770"], "timestamp_utc": ["invalid"]}
        )
        with TemporaryDirectory(dir=Path(__file__).parent) as directory:
            with self.assertRaisesRegex(ValueError, "timestamp"):
                write_csv(
                    f,
                    Path(directory) / "invalid.csv",
                    ["city_key", "fips_code", "timestamp_utc"],
                )


class ProductContractTests(unittest.TestCase):
    def test_range_boundaries_preserve_every_record_once(self):
        from src.bulk import csv_window

        payload = b'fips,county\r\n51770,Roanoke\r\n51161,"Roanoke County"\r\n39049,Franklin\r\n'
        for block in range(1, len(payload)):
            pieces = []
            for offset in range(0, len(payload), block):
                stop = min(offset + block, len(payload))
                begin = max(0, offset - 1)
                pieces.append(csv_window(payload[begin:], offset, stop, len(payload)))
            self.assertEqual(b"".join(pieces), payload)

    def test_sparse_outages_do_not_create_zero_labels(self):
        frame = pd.DataFrame(
            {
                "fips_code": ["51770", "51770"],
                "timestamp_utc": pd.to_datetime(
                    ["2024-01-01T00:00Z", "2024-01-01T01:00Z"]
                ),
                "customers_out": [100, 200],
                "source_dataset": ["EAGLE-I"] * 2,
            }
        )
        self.assertTrue(aggregate(frame).empty)
        self.assertEqual(len(aggregate(frame, "15min")), 2)

    def test_city_county_mismatch_rejected(self):
        from src.validation import validate

        frame = pd.DataFrame(
            {
                "city_key": ["TUL"],
                "fips_code": ["51770"],
                "outage_event_id": ["one"],
                "start_timestamp_utc": ["2024-01-01T00:00Z"],
                "end_timestamp_utc": ["2024-01-01T00:30Z"],
                "peak_customers_out": [200],
                "customer_hours_interrupted": [100],
                "record_type": ["ACTUAL_UTILITY_OUTAGE"],
            }
        )
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            validate("outages", frame, "2024-01-01", "2024-01-01")

    def test_gapped_weather_grid_rejected(self):
        from src.validation import validate

        frame = pd.DataFrame(
            {
                "city_key": ["ROA"],
                "fips_code": ["51770"],
                "timestamp_utc": ["2024-01-01T00:00Z"],
                "asos_id": ["KROA"],
                "ghcnd_id": ["USW00013741"],
                "temp_c": [1.0],
            }
        )
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            validate("historical", frame, "2024-01-01", "2024-01-01")

    def test_eia_pagination_advances_offset(self):
        from unittest.mock import Mock, patch
        from src.fetch_power_outages import eia_pages

        first = Mock()
        first.json.return_value = {
            "response": {"total": "3", "data": [{"value": 1}, {"value": 2}]}
        }
        second = Mock()
        second.json.return_value = {"response": {"total": "3", "data": [{"value": 3}]}}
        with patch("src.fetch_power_outages.get", side_effect=[first, second]) as fetch:
            result = eia_pages("region-sub-ba-data", "2024-01-01", "2024-01-01", {})
            self.assertEqual(len(result), 3)
            self.assertEqual(fetch.call_args_list[1].kwargs["params"]["offset"], 2)

    def test_same_geography_load_drop(self):
        from src.fetch_power_outages import load_anomalies

        actual = pd.DataFrame(
            {
                "subba": ["AEP"],
                "timestamp_utc": pd.to_datetime(["2024-01-02T00:00Z"]),
                "actual_mw": [800.0],
            }
        )
        forecast = pd.DataFrame(
            {
                "subba": ["AEP"],
                "timestamp_utc": ["2024-01-02T00:00Z"],
                "issue_timestamp_utc": ["2024-01-01T00:00Z"],
                "forecast_mw": [1000.0],
            }
        )
        self.assertEqual(load_anomalies(actual, forecast).load_drop_mw.iloc[0], -200.0)
        forecast["issue_timestamp_utc"] = "2024-01-03T00:00Z"
        with self.assertRaisesRegex(ValueError, "before"):
            load_anomalies(actual, forecast)

    def test_exact_archived_run_preserves_initialization(self):
        from unittest.mock import Mock, patch
        from src.fetch_weather_forecasts import single_run
        from src.config import CITIES

        response = Mock()
        response.json.return_value = {
            "hourly": {"time": ["2025-01-01T01:00"], "temperature_2m": [1.0]}
        }
        with patch("src.fetch_weather_forecasts.get", return_value=response):
            frame = single_run(CITIES[0], "2025-01-01T00:00")
        self.assertEqual(
            frame.issue_timestamp_utc.iloc[0], pd.Timestamp("2025-01-01T00:00Z")
        )
        self.assertEqual(frame.forecast_source.iloc[0], "OPEN_METEO_ARCHIVED_RUN")


class ExtendedContracts(unittest.TestCase):
    def test_wind_direction_wraps_through_north(self):
        from src.fetch_historical_weather import circular_degrees

        angle = circular_degrees(pd.Series([350.0, 10.0]))
        self.assertLess(min(abs(angle), abs(angle - 360)), 1e-8)

    def test_range_seek_keeps_requested_dates(self):
        from src.bulk import timestamp_window
        from unittest.mock import MagicMock, patch
        import re

        header = b"fips_code,county,state,customers_out,run_start_time\n"
        rows = [
            f"51770,Roanoke,Virginia,100,{time}\n".encode()
            for time in pd.date_range("2025-01-01", periods=10000, freq="min")
        ]
        data = header + b"".join(rows)

        def response(url, headers, stream):
            a, b = map(int, re.findall(r"\d+", headers["Range"]))
            result = MagicMock()
            result.status_code = 206
            result.__enter__.return_value = result
            result.iter_content.return_value = [data[a : b + 1]]
            return result

        with patch("src.bulk.get", side_effect=response):
            lower, upper = timestamp_window(
                {"size": len(data), "download_url": "https://example.invalid/test.csv"},
                "2025-01-03",
                "2025-01-04",
            )
        first = header + b"".join(rows[:2880])
        last = header + b"".join(rows[:5760])
        self.assertLessEqual(lower, len(first))
        self.assertGreaterEqual(upper, len(last))

    def test_known_forecast_requires_issue_reference(self):
        from src.validation import validate

        frame = pd.DataFrame(
            {
                "city_key": ["ROA"],
                "fips_code": ["51770"],
                "forecast_source": ["NWS_NDFD"],
                "valid_timestamp_utc": ["2025-01-01T00:00Z"],
                "issue_timestamp_utc": [pd.NaT],
                "lead_time_hours": [float("nan")],
            }
        )
        with self.assertRaisesRegex(ValueError, "Missing issue"):
            validate("forecasts", frame, "2025-01-01", "2025-01-01")


class SharedTransferContracts(unittest.TestCase):
    def test_shared_executor_reassembles_filtered_csv(self):
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import MagicMock, patch
        from src.bulk import filtered_csv_ranges
        import io, re

        payload = b"fips_code,county,state,customers_out,run_start_time\n51770,Roanoke,Virginia,100,2025-01-01 00:00:00\n51770,Roanoke,Virginia,200,2025-01-01 00:15:00\n00001,Other,Virginia,999,2025-01-01 00:15:00\n"

        def get(url, headers, stream):
            begin, finish = map(int, re.findall(r"\d+", headers["Range"]))
            finish = min(finish, len(payload) - 1)
            response = MagicMock()
            response.__enter__.return_value = response
            response.status_code = 206
            response.headers = {
                "Content-Range": f"bytes {begin}-{finish}/{len(payload)}"
            }
            response.raw = io.BytesIO(payload[begin : finish + 1])
            response.iter_content.return_value = [payload[begin : finish + 1]]
            return response

        with (
            TemporaryDirectory(dir=Path(__file__).parent) as directory,
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            with patch("src.bulk.get", side_effect=get):
                frame = filtered_csv_ranges(
                    {
                        "id": 1,
                        "size": len(payload),
                        "download_url": "https://example.invalid/test.csv",
                    },
                    2025,
                    directory,
                    normalize,
                    block_size=32,
                    executor=pool,
                )
        self.assertEqual(frame.fips_code.tolist(), ["51770", "51770"])
        self.assertEqual(frame.customers_out.tolist(), [100, 200])


if __name__ == "__main__":
    unittest.main()
