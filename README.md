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
  added/removed. Built this to pin down what an "obfuscated" build actually
  changed vs. a clean build (spoiler: usually a bundled RASP/app-shielding
  SDK, not the app's own code).
- **Dynamic analysis (Frida)** — install/run the app on a jailbroken device
  you control and trace it live: Objective-C method calls on classes you
  pick, outgoing network requests (URL/method/headers/body), and
  keychain/CommonCrypto/TLS-trust-evaluation checkpoints — plus **your own
  custom Frida script**, uploaded through the UI and run alongside the
  built-in hooks in its own isolated script instance. See
  [frida-bridge/README.md](frida-bridge/README.md) — this piece runs
  natively on your Mac, not in Docker (Docker Desktop has no USB
  passthrough), and is entirely optional/additive: nothing else in the app
  depends on it.
- **MCP server** — exposes the same analysis (upload, file tree, classes,
  functions, decompiled pseudo-C) as MCP tools, so Claude Code, Claude
  Desktop, or any other MCP client can upload an IPA and reason about what
  it does. In-app setup docs live behind the "🔌 MCP setup" button once the
  stack is running. See [mcp-server/](mcp-server/).

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

**`frida-bridge`** (dynamic analysis) is deliberately *not* one of the
`docker-compose` services — it needs real USB access to a jailbroken device,
which Docker Desktop for Mac can't pass through to a container. It runs as a
second, native Celery worker on your host, consuming a separate queue the
containerized `worker` never listens on. See its own README for setup; if
you never run it, the rest of the app is unaffected.

## Quickstart

Requirements: Docker Desktop.

```bash
git clone <this-repo-url>
cd iOSDeOb
docker compose up -d --build
```

Open **http://localhost:8080**, upload an `.ipa`, and browse. Only
non-FairPlay-encrypted binaries work — dev-signed, ad-hoc, or already-decrypted
builds (see [Known limitations](#known-limitations)).

Set `INTERNAL_TOKEN` in a `.env` file (or your shell environment) before
first run if you want something other than the default dev token — it's the
shared secret between `api` and the two workers (`worker` and
`frida-bridge`) for their internal-only callback endpoints:

```bash
echo "INTERNAL_TOKEN=$(openssl rand -hex 32)" > .env
```

### Dynamic analysis (optional)

Everything above works without this. To trace a running app on a jailbroken
device you control, set up and run `frida-bridge` per
[its README](frida-bridge/README.md), then use the "🧬 Dynamic" tab on any
ready scan.

### MCP server (optional)

To let an MCP client (Claude Code, Claude Desktop, etc.) drive the same
analysis: with the stack running, open the "🔌 MCP setup" button in the web
UI for exact copy-pasteable client config, or see
[mcp-server/server.py](mcp-server/server.py) directly. It runs on the host
and talks to the API over `http://localhost:8080/api` — no separate service
in `docker-compose.yml`.

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

## Responsible use

This is static- and dynamic-analysis tooling in the spirit of MobSF, JADX,
and Ghidra: point it at IPAs you own, that you built, or that you have
explicit authorization to test. The dynamic-analysis feature instruments a
real, running app on a real device — only do that against apps/devices
you're authorized to test, and only while you intend a trace to happen.
