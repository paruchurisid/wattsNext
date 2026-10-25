import requests
from src.config import CITIES
for c in CITIES:
    p=requests.get(f'https://api.weather.gov/points/{c.lat},{c.lon}',timeout=30).json()['properties']
    print(c.city_key,c.wfo_grid,p['gridId'],p['gridX'],p['gridY'],flush=True)
