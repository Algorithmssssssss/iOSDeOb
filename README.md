# iOSDeOb

A self-hosted iOS IPA reverse-engineering workbench. Upload an `.ipa` and get a
Hopper/JADX-style browser for it: unzipped bundle contents, an Objective-C
class/method tree, ARM64 disassembly with a Ghidra-backed pseudo-C
decompiler, a side-by-side scan comparison view, and Frida-based dynamic
instrumentation against a real device — all through one web UI, plus an MCP
server so an AI agent can drive the same analysis.

Built for de-obfuscating and understanding IPAs you own or are explicitly
authorized to test — see [Responsible use](#responsible-use).

## Features

- **File browser** — the unpacked `Payload/*.app` tree, Info.plist and
  entitlements parsed and rendered, previews for text/plist/image files, raw
  download for anything else.
- **Objective-C class browser** — every class, its superclass, methods
  (instance + class), properties, ivars and protocols, parsed straight from
  Mach-O load commands and ObjC runtime metadata (no `class-dump` dependency).
  Deep-links from a method straight into its disassembly.
- **ARM64 disassembly + decompiler** — on-demand `radare2` disassembly and
  Ghidra pseudo-C decompilation per function, with caller/callee cross-refs
  resolved against the class and symbol tables. Results are cached so
  re-opening a function is instant.
- **Search** — function/symbol and file-path search across the whole scan,
  plus a global cross-scan search from the header.
- **Scan comparison** — pick two scans and see exactly what differs: files
  added/removed/resized, classes added/removed/changed, functions
  added/removed.
- **Dynamic analysis (Frida)** — install/run the app on a jailbroken device
  you control (pick it from a device dropdown — USB is auto-detected, or add
  one wirelessly by its `host:port`) and trace it live: Objective-C method
  calls on classes you pick, outgoing network requests
  (URL/method/headers/body), and keychain/CommonCrypto/TLS-trust-evaluation
  checkpoints — plus **your own custom Frida script**, uploaded through the
  UI and run alongside the built-in hooks in its own isolated script
  instance. This piece runs natively on your Mac, not in Docker, and is
  entirely optional/additive — see [Setting up dynamic analysis](#3-optional-set-up-dynamic-analysis-frida-bridge).
- **MCP server** — exposes the same analysis (upload, file tree, classes,
  functions, decompiled pseudo-C) as MCP tools, so Claude Code, Claude
  Desktop, or any other MCP client can upload an IPA and reason about what
  it does — see [Setting up the MCP server](#4-optional-set-up-the-mcp-server).

## Architecture

```
proxy   (Caddy)             — TLS/reverse-proxy, the only port you talk to (8080)
web     (React + TypeScript)— the SPA
api     (FastAPI)           — uploads, SQLite persistence, job orchestration
worker  (Celery)            — the ONLY thing that touches untrusted binaries;
                               fully network-isolated, never executes them —
                               extraction, ObjC/Mach-O parsing, r2/Ghidra calls
redis                        — Celery broker
```

`worker` runs on an internal, egress-free Docker network with a read-only
root filesystem — it parses untrusted Mach-O data but never executes it.

Two more pieces run **outside** Docker, directly on your Mac, and are both
entirely optional:

- **`frida-bridge`** (dynamic analysis) — needs real USB access to a
  jailbroken device, which Docker Desktop can't pass through to a container.
  It's a second Celery worker consuming a separate queue the containerized
  `worker` never listens on.
- **`mcp-server`** — a plain Python process your MCP client launches
  directly; it just makes the same HTTP calls to the API that your browser
  does.

If you never set either of these up, the rest of the app works exactly the
same.

## Project layout

```
api/            FastAPI backend — routes, models, schemas
worker/         Celery worker that does the actual static analysis (Docker)
web/            React + TypeScript frontend
proxy/          Caddy config (the reverse proxy in front of everything)
frida-bridge/   Dynamic-analysis worker — runs on your host, not in Docker
mcp-server/     MCP server — also runs on your host
docker-compose.yml   Defines proxy/web/api/worker/redis
```

## Prerequisites

- **[Docker Desktop](https://www.docker.com/products/docker-desktop/)** —
  required for everything except dynamic analysis and the MCP server.
- **macOS** — `frida-bridge` (dynamic analysis) specifically needs macOS for
  USB device access; the rest of the stack is platform-agnostic.
- **Git**.
- For dynamic analysis only: **Python 3.10+**, **Node.js + npm**, and a
  **jailbroken iOS device** with `frida-server` installed on it.
- For the MCP server only: **Python 3.10+** and an MCP-compatible client
  (Claude Code, Claude Desktop, Cursor, etc.).

Throughout this guide, `/path/to/iOSDeOb` means wherever you clone this repo
— run `pwd` from the project root any time you need the real value.

## 1. Get the app running

```bash
git clone <this-repo-url> iOSDeOb
cd iOSDeOb
```

(Optional) set a non-default internal auth token — this is the shared
secret the API and its background workers use to talk to each other
internally; the stack works fine with the default, but don't reuse the
default if this will be reachable by anyone other than you:

```bash
echo "INTERNAL_TOKEN=$(openssl rand -hex 32)" > .env
```

Build and start everything:

```bash
docker compose up -d --build
```

First build pulls a handful of base images and compiles `radare2`/`r2ghidra`
in the `worker` image — expect several minutes the first time, and a
**1.5–3GB `worker` image**, which is normal for bundled RE tooling.

## 2. Verify it's up

```bash
curl http://localhost:8080/api/health
# {"status":"ok"}
```

Open **http://localhost:8080** in a browser, upload a test `.ipa` (a
dev-signed or ad-hoc build — see [Known limitations](#known-limitations) for
why a straight-from-App-Store one won't work), and confirm it reaches
`ready` status, then browse its Files/Classes/Functions tabs.

If port `8080` (or `8000`/`6379`, which `api`/`redis` also publish to
`127.0.0.1`) is already used by something else on your machine, Docker will
fail to start that service — see
[Troubleshooting](#troubleshooting).

## 3. (Optional) Set up dynamic analysis (frida-bridge)

Skip this section entirely if you don't need to trace a live app on a
device — everything above already works without it.

```bash
cd frida-bridge
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Check your device's `frida-server` version first** — the `frida` pin in
`requirements.txt` must match it exactly, or every real call fails with
`unable to communicate with remote frida-server; please ensure that major
versions match`. Check via your jailbreak tweak manager (Sileo/Zebra —
search "frida") or `frida-server --version` over on-device SSH, then update
the version pin in `requirements.txt` if it differs before running
`pip install`.

Confirm the device is visible (run directly in a terminal, not through a
script — it needs a real TTY):

```bash
frida-ls-devices
```

Build the injected agent (needs Node/npm):

```bash
npm install
npm run build
```

Start the worker — leave this running in its own terminal tab:

```bash
export REDIS_URL=redis://localhost:6379/0
export API_INTERNAL_URL=http://localhost:8000
export INTERNAL_TOKEN=dev-internal-token-change-me   # match your .env if you set one
celery -A bridge.celery_app worker -Q frida --pool=solo --loglevel=INFO
```

Then open the **"🧬 Dynamic analysis"** page from the app's header. Full
details — picking/adding devices (including wireless via an SSH tunnel),
what gets captured, custom scripts, and troubleshooting — are in
[frida-bridge/README.md](frida-bridge/README.md).

## 4. (Optional) Set up the MCP server

Skip this if you don't use an MCP-compatible AI client.

```bash
cd mcp-server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

With the Docker stack running, open the **"🔌 MCP setup"** button in the web
UI — it generates the exact config block for your client (Claude Desktop,
Claude Code, or a generic one) with the right absolute paths for your clone
of this repo already filled in, plus a tool reference and troubleshooting
tips. Or see [mcp-server/server.py](mcp-server/server.py) directly.

## Data model / storage

SQLite (WAL mode) on a named volume, owned entirely by `api`. Parsed results
(file tree, plists, classes, symbols, disasm/decompile output, dynamic-trace
events) are persisted there; the worker re-extracts from the original
uploaded `.ipa` (also on a named volume) on demand rather than keeping raw
extracted trees around indefinitely.

## Known limitations

- **FairPlay-encrypted App Store IPAs don't work.** Decrypting one requires
  running the binary, which conflicts with "never execute untrusted
  uploads." Use a dev-signed, ad-hoc, or already-decrypted build.
- **Swift metadata recovery is partial** — good for Objective-C, best-effort
  for Swift's own type metadata.
- **Decompiler output won't match Hopper/IDA/Ghidra-desktop quality**,
  especially around `objc_msgSend` call-site resolution — it's r2ghidra
  wired into a web UI, not a from-scratch decompiler.
- **Dynamic-trace network bodies show as "binary (compressed)"** when an app
  gzips its request bodies (common — Firebase, Crashlytics, Branch, GA all
  do this by default); the agent deliberately doesn't attempt in-process
  gzip decompression via hand-built native `zlib` bindings, since getting a
  native struct layout wrong risks corrupting the traced process.
- Multi-user auth was deliberately deferred — this is a personal/small-team
  tool right now, not a multi-tenant service.

## Troubleshooting

- **A service fails to start / "port is already allocated"** — something
  else on your Mac is already using `8080`, `8000`, or `6379`. Find and stop
  it, or change the host-side port in `docker-compose.yml` (the left side of
  `"127.0.0.1:8000:8000"` — only the left side is safe to change).
- **A container was working, then a `docker compose up -d <service>` seems
  to do nothing** — Compose only recreates a container when it detects a
  config change; if you edited `docker-compose.yml` and it's not taking
  effect, force it: `docker compose up -d --force-recreate <service>`.
- **`frida-bridge` can't reach Redis/the API** — both need to be reachable
  from your host at `localhost:6379` / `localhost:8000`; confirm with
  `docker compose ps` that `redis` and `api` show a `127.0.0.1:...->...`
  port mapping, not just an internal one.
- **Dynamic analysis / MCP server specific issues** — see the
  troubleshooting sections in
  [frida-bridge/README.md](frida-bridge/README.md) and the in-app MCP setup
  page respectively.

## Responsible use

This is static- and dynamic-analysis tooling in the spirit of MobSF, JADX,
and Ghidra: point it at IPAs you own, that you built, or that you have
explicit authorization to test. The dynamic-analysis feature instruments a
real, running app on a real device — only do that against apps/devices
you're authorized to test, and only while you intend a trace to happen.
