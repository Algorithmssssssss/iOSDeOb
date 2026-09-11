# frida-bridge

Dynamic analysis worker for iOSDeOb's "Dynamic" tab. Runs **natively on your
Mac** — not inside Docker — because Docker Desktop for Mac has no USB
passthrough, and this is the piece that talks to `frida-server` on your
USB-connected jailbroken iPhone.

It's a second Celery worker, consuming a separate `frida` queue that the
containerized `worker` never listens on, so it's fully additive: nothing
about the existing static-analysis pipeline changes, and if this isn't
running, everything else keeps working exactly as before.

## One-time setup

```bash
cd frida-bridge
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Make sure `frida-server` is running on the device (over USB) and the device
is visible from this Mac:

```bash
frida-ls-devices
```

You should see your phone listed with type `usb`.

The main `docker-compose.yml` now publishes Redis on `127.0.0.1:6379` and the
API container directly on `127.0.0.1:8001` (the internal `/internal/*`
endpoints this bridge calls aren't routed through the Caddy proxy on 8080 —
only `/api/*` and `/ws/*` are; `8001` rather than the API's own `8000` because
something else on this Mac already holds `8000`) — so as long as
`docker compose up` is running, no extra networking setup is needed on this
side.

## Running

```bash
export REDIS_URL=redis://localhost:6379/0
export API_INTERNAL_URL=http://localhost:8001
export INTERNAL_TOKEN=dev-internal-token-change-me   # must match docker-compose.yml's INTERNAL_TOKEN
celery -A bridge.celery_app worker -Q frida --concurrency=1 --loglevel=INFO
```

Leave this running in a terminal tab. Starting a run from the web UI's
Dynamic tab enqueues a task onto the `frida` queue, which this process picks
up, spawns/attaches to the app on the device, installs the requested hooks,
and streams captured events back to the API for the duration you set (or
until you click Stop).

## What it captures

- **ObjC method calls** for whichever classes you pick in the UI — selector
  name, best-effort argument descriptions.
- **Network calls** — `NSURLSessionTask resume` / `NSURLConnection`
  synchronous requests: URL, method, headers, body size.
- **Crypto / keychain / SSL pinning** — `SecItem*` (keychain),
  `CCCryptorCreate`/`CCCrypt` (CommonCrypto), `SecTrustEvaluate*` (TLS trust
  evaluation checkpoints). All hooks are purely observational — nothing is
  bypassed or altered.

## Notes / limitations

- Only one run at a time (`--concurrency=1`) — Frida USB sessions don't
  parallelize well against a single device.
- Attaching to an already-running instance of the app is matched by bundle
  identifier via `enumerate_applications()`; a cold spawn is preferred and
  used whenever possible since hooks are then in place before any app code
  runs.
- This process has real USB/device access and is not sandboxed — that's
  inherent to dynamic analysis. Only run it against apps/devices you own or
  are authorized to test, and only while you intend a trace to happen.
