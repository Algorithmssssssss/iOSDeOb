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

**`requirements.txt` pins `frida` to match your `frida-server`'s version exactly**
(currently `17.17.0`) — the wire protocol isn't compatible across major/minor
versions, and mismatched client/server fails every real call with `unable to
communicate with remote frida-server; please ensure that major versions
match`. Check your device's `frida-server` version (jailbreak tweak
manager/Sileo, or `frida-server --version` over on-device SSH/terminal) and
update the pin in `requirements.txt` if it differs, then reinstall.

Confirm the device is visible from this Mac (needs a real TTY, so run it
directly in a terminal rather than through a non-interactive script):

```bash
frida-ls-devices
```

You should see your phone listed with type `usb`. If you only need a quick
non-interactive check, `python3 -c "import frida; print(frida.get_usb_device(timeout=5))"`
works too.

### Build the agent

```bash
npm install
npm run build   # runs frida-compile agent.js -o agent-bundle.js
```

Frida 17 dropped `ObjC` (and the other language bridges) as an always-on
global in injected scripts — it now has to be imported from the
`frida-objc-bridge` npm package and bundled with `frida-compile` into a
single file, which is what `agent-bundle.js` is; `runner.py` loads that
bundle, not `agent.js` directly. **Re-run `npm run build` any time you edit
`agent.js`** — the bundle doesn't rebuild itself.

The main `docker-compose.yml` now publishes Redis on `127.0.0.1:6379` and the
API container directly on `127.0.0.1:8000` (the internal `/internal/*`
endpoints this bridge calls aren't routed through the Caddy proxy on 8080 —
only `/api/*` and `/ws/*` are) — so as long as `docker compose up` is
running, no extra networking setup is needed on this side.

## Running

```bash
export REDIS_URL=redis://localhost:6379/0
export API_INTERNAL_URL=http://localhost:8000
export INTERNAL_TOKEN=dev-internal-token-change-me   # must match docker-compose.yml's INTERNAL_TOKEN
celery -A bridge.celery_app worker -Q frida --pool=solo --loglevel=INFO
```

`--pool=solo` (not the default `prefork`) is required, not optional: `frida` spawns a
background thread for its device/event loop at import time, and Celery's prefork
pool forks *after* that thread exists — the child process inherits the lock but not
the thread that would release it, so the very first task deadlocks forever. `solo`
runs everything in-process with no fork, which is also the right model here since
only one trace can run against the single USB device at a time anyway.

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

- Only one run at a time — `--pool=solo` means this worker only ever
  processes one task at a time anyway, which matches reality: there's one
  USB device.
- Attaching to an already-running instance of the app is matched by bundle
  identifier via `enumerate_applications()`; a cold spawn is preferred and
  used whenever possible since hooks are then in place before any app code
  runs.
- This process has real USB/device access and is not sandboxed — that's
  inherent to dynamic analysis. Only run it against apps/devices you own or
  are authorized to test, and only while you intend a trace to happen.
