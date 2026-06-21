# Deploying ParkSentry

The whole app ships as **one Docker image** (`Dockerfile`): the Node/Express
gateway serves the built React SPA, mints the Mappls token and proxies `/api`,
and runs the Python FastAPI ML service internally on `:8001`. The gateway listens
on the platform's `$PORT`. Model/data artifacts are committed, so **no pipeline
run is needed at deploy**.

## Required environment variables
| Variable | Purpose |
|---|---|
| `MAPPLS_CLIENT_ID` | Mappls OAuth client id (server-side token minting) |
| `MAPPLS_CLIENT_SECRET` | Mappls OAuth client secret |

`PORT` is set automatically by the host. Without the Mappls vars everything works
except the interactive map.

> **Mappls gotcha:** your Mappls app keys may be **referer/domain-restricted** —
> the map works on `localhost` but can silently fail on a new domain. Add your
> deploy URL to the allowed domains in the Mappls console.

## Test it locally first
```bash
docker build -t parksentry .
docker run --rm -p 8000:8000 \
  -e MAPPLS_CLIENT_ID=... -e MAPPLS_CLIENT_SECRET=... \
  parksentry
# open http://localhost:8000
```

---

## Free hosting (no card / $0)
> Heads-up: **Railway has no free tier** (a one-time ~$5 trial credit, then ~$5/mo).
> For genuinely free, use one of these — the same Docker image works unchanged.

**Render (free Web Service)**
1. New → **Web Service** → connect this GitHub repo → Runtime: **Docker**.
2. Add env vars `MAPPLS_CLIENT_ID`, `MAPPLS_CLIENT_SECRET`.
3. Deploy. Render builds the `Dockerfile` and serves the gateway port.

Free-tier caveats:
- **Spins down after ~15 min idle** → first request after has a ~30–60 s cold start.
- **No persistent disk** → the server-side **station assignments reset** on every
  spin-down / redeploy. Everything else (map, tables, forecaster, charts) is fine.
- 512 MB RAM can be tight when the live Forecaster loads; the map/tables/charts are light.

(Hugging Face **Docker Spaces** is another free option with more RAM — set the
Space `app_port` to the gateway port and add the Mappls keys as Space secrets.)

---

## Always-on + persistent assignments (paid)
Pick this if you want no spin-down **and** the saved assignments to survive
restarts (they're stored in `data/station_assignments.json`).

**Railway (~$5/mo)**
1. New Project → **Deploy from GitHub repo** (it detects the `Dockerfile`).
2. Variables → add `MAPPLS_CLIENT_ID`, `MAPPLS_CLIENT_SECRET`.
3. Add a **Volume** mounted at **`/app/data`** (persists the assignments).
4. Deploy. Railway sets `$PORT`; the public URL serves the app.

**Render (Starter ~$7/mo)** — same as the free steps, but choose a paid instance
(no spin-down) and attach a **Disk** mounted at **`/app/data`**.

---

## Notes
- The image installs Python (pandas/lightgbm/sklearn/fastapi) + Node 22, builds
  the SPA, and runs `npm start`. First build is a few minutes; later builds reuse
  the cached Python-deps layer.
- `webapp/.env` (your local Mappls secrets) is **gitignored and excluded from the
  image** — set the keys as platform env vars instead.
