import requests
j=requests.get('https://api.figshare.com/v2/articles/24237376',timeout=30).json()
f=next(f for f in j['files'] if f['name']=='eaglei_outages_2025.csv')
with requests.get(f['download_url'],headers={'Range':'bytes=0-4095'},stream=True,timeout=30) as r: print(r.raw.read(600).decode())
