import requests,struct
j=requests.get('https://api.figshare.com/v2/articles/24237376',timeout=30).json(); print('version',j.get('version'))
url=f"https://ndownloader.figshare.com/articles/24237376/versions/{j.get('version',4)}"
with requests.get(url,headers={'Range':'bytes=0-65535'},stream=True,timeout=60) as r:
    print(r.status_code,r.headers.get('Content-Length'),r.headers.get('Content-Range'),r.headers.get('Content-Type'))
    data=r.raw.read(64);print(data)
    if data[:4]==b'PK\x03\x04': print('zip compression method',struct.unpack('<H',data[8:10])[0])
