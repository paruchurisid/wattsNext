# Local network hosting

Run the app on a computer connected to your local network:

```powershell
python server.py
```

The server listens on all network interfaces on port 8000. On that computer,
open `http://localhost:8000`. On another device on the same network, open
`http://<host-computer-LAN-IP>:8000`. Use `ipconfig` on Windows to find the
IPv4 address of the active Wi-Fi or Ethernet adapter. Allow Python through
Windows Firewall on private networks if prompted.

To change the port or restrict listening to this computer:

```powershell
$env:HOST = '127.0.0.1'
$env:PORT = '8001'
python server.py
```

Docker hosting also supports LAN access with `docker compose up --build`:
the container listens on all interfaces and publishes host port 8000.

Vercel remains a separate cloud deployment. Local hosting runs the app directly
on your computer and does not require a Vercel token or deployment.
