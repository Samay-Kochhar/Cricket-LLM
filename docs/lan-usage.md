# LAN Usage

## Goal

Run CricAtlas on your laptop and open it from your phone while both devices are on the same Wi-Fi network.

## Docker Compose Path

1. Start the stack:

```bash
docker compose up --build
```

2. Find your laptop's LAN IP address.

Windows:

```powershell
ipconfig
```

Look for the active adapter's IPv4 address, for example `192.168.1.42`.

3. Open the app on your phone:

```text
http://192.168.1.42:3000
```

## Why This Works

- The frontend is exposed on `0.0.0.0:3000`
- The frontend proxies `/api/*` server-side to the backend container
- The browser never needs to call `127.0.0.1:8000` directly

## Common Problems

- The phone cannot connect:
  Check that Windows Firewall allows inbound connections for Docker/Desktop or the terminal session exposing port `3000`.

- The UI loads but API calls fail:
  Make sure the backend is healthy with `http://localhost:8000/health` on the laptop.

- The stack starts but no analytics appear:
  Verify `data/odi_bbb-25.csv` exists and that `data/odi_analytics.duckdb` was generated.

## Non-Docker Path

If you run the services directly:

Backend:

```bash
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

Frontend:

```bash
cd frontend
$env:BACKEND_INTERNAL_URL="http://127.0.0.1:8000"
npm run dev -- --hostname 0.0.0.0 --port 3000
```

Then use the same `http://<laptop-ip>:3000` URL from your phone.
