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
        self.assertEqual(FIPS['51770'],FIPS['51161'])
    def test_damage(self):
        self.assertEqual(damage('1.50M'),1500000)
        self.assertEqual(damage('25.00K'),25000)
        self.assertTrue(pd.isna(damage('unknown')))
    def test_storm_standard_time(self):
        self.assertEqual(storm_time('01-Jul-24 12:00:00','EST-5').hour,17)
    def test_gap_breaks_events_and_integrates_bins(self):
        f=pd.DataFrame({'fips_code':['51770']*5,'timestamp_utc':pd.to_datetime(['2024-01-01T00:00Z','2024-01-01T00:15Z','2024-01-01T01:00Z','2024-01-01T01:15Z','2024-01-01T01:30Z']),'customers_out':[100,200,100,200,50],'source_dataset':['EAGLE-I']*5})
        events=aggregate(f)
        self.assertEqual(len(events),2)
        self.assertEqual(events.iloc[0].customer_hours_interrupted,75)
        self.assertEqual(events.iloc[0].duration_minutes,30)
    def test_filter_fips(self):
        f=pd.DataFrame({'fips':['51770','00001'],'run_start_time':['2024-01-01']*2,'sum':[100,500]})
        self.assertEqual(len(normalize(f,'2024-01-01','2024-01-01')),1)
    def test_conflicting_archives_fail(self):
        f=pd.DataFrame({'fips_code':['51770']*2,'timestamp_utc':pd.to_datetime(['2024-01-01T00:00Z']*2),'customers_out':[100,200],'source_dataset':['EAGLE-I','OEDI']})
        with self.assertRaisesRegex(ValueError,'Conflicting'): aggregate(f)
    def test_invalid_timestamp_rejected(self):
        f=pd.DataFrame({'city_key':['ROA'],'fips_code':['51770'],'timestamp_utc':['invalid']})
        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError,'timestamp'):
                write_csv(f,Path(directory)/'invalid.csv',['city_key','fips_code','timestamp_utc'])
if __name__=='__main__': unittest.main()
