"""Drives one dynamic-trace run: spawn/attach on the USB device, load the
Frida agent, stream events back to the API, and stop after the configured
duration or an early stop request."""

import json
import os
import threading
import time
import uuid

import frida
import requests

from . import device_manager

API_INTERNAL_URL = os.environ.get("API_INTERNAL_URL", "http://localhost:8000")
INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "dev-internal-token-change-me")
FRIDA_BRIDGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENT_PATH = os.path.join(FRIDA_BRIDGE_ROOT, "agent-bundle.js")
TMP_SCRIPTS_DIR = os.path.join(FRIDA_BRIDGE_ROOT, ".tmp_custom_scripts")
USB_DEVICE_TIMEOUT_SECS = 5
POLL_INTERVAL_SECS = 1


def _compile_custom_script(source: str) -> str:
    """Frida 17 dropped ObjC (and Java/Swift) as ambient globals in injected
    scripts — they now have to be `import`ed from their bridge npm package
    and resolved by Frida's own bundler (frida.Compiler). That's exactly
    what `frida -U -f <bundle> -l script.js` does for you automatically,
    which is why a script written before this change "just works" from the
    CLI but not through a raw session.create_script() call — the CLI compiles
    it first, we weren't.

    frida.Compiler() can only resolve node_modules under a real project
    root, so the script has to live on disk inside this project (not just
    be compiled from a string) — hence writing it to a temp file here rather
    than passing the source directly. The ObjC import is injected
    automatically for scripts that clearly need it (the common case — most
    Frida scripts found in the wild predate this change) without touching
    scripts that already import it themselves.
    """
    if "ObjC" in source and "frida-objc-bridge" not in source:
        source = 'import ObjC from "frida-objc-bridge";\n' + source

    os.makedirs(TMP_SCRIPTS_DIR, exist_ok=True)
    path = os.path.join(TMP_SCRIPTS_DIR, f"{uuid.uuid4().hex}.js")
    with open(path, "w") as f:
        f.write(source)
    try:
        return frida.Compiler().build(os.path.relpath(path, FRIDA_BRIDGE_ROOT), project_root=FRIDA_BRIDGE_ROOT)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _headers() -> dict:
    return {"X-Internal-Token": INTERNAL_TOKEN}


def _post_events(job_id: str, events: list[dict], attempts: int = 4) -> bool:
    """Returns whether the batch was actually stored. A transient failure
    here used to mean the batch was silently discarded forever (the reported
    "some traces are missing" bug) — now the caller keeps unsent events
    queued and retries them on the next flush instead of dropping them."""
    if not events:
        return True
    for attempt in range(attempts):
        try:
            resp = requests.post(
                f"{API_INTERNAL_URL}/internal/dynamic/{job_id}/events",
                json={"events": events},
                headers=_headers(),
                timeout=10,
            )
            resp.raise_for_status()
            return True
        except Exception:
            if attempt < attempts - 1:
                time.sleep(0.5 * (attempt + 1))
    return False


def _post_progress(job_id: str, pct: int, message: str | None = None) -> None:
    try:
        requests.post(
            f"{API_INTERNAL_URL}/internal/jobs/{job_id}/progress",
            json={"progress_pct": pct, "message": message, "phase": "dynamic"},
            headers=_headers(),
            timeout=10,
        )
    except Exception:
        pass


def _stop_requested(job_id: str) -> bool:
    try:
        resp = requests.get(f"{API_INTERNAL_URL}/api/jobs/{job_id}", timeout=5)
        resp.raise_for_status()
        return bool(resp.json().get("stop_requested"))
    except Exception:
        return False


def _spawn_or_attach(device: "frida.core.Device", bundle_id: str):
    """Prefer a clean spawn (cold start, hooks installed before any code runs).
    Falls back to attaching to an already-running instance, matched by bundle
    id via enumerate_applications — process name alone isn't reliable on iOS."""
    try:
        pid = device.spawn([bundle_id])
        return pid, True
    except Exception:
        pass

    for app in device.enumerate_applications():
        if app.identifier == bundle_id and app.pid:
            return app.pid, False

    raise RuntimeError(f"Could not spawn or find a running instance of '{bundle_id}' on the device")


def run(ipa_id: str, job_id: str, params: dict) -> None:
    bundle_id = params["bundle_id"]
    duration_secs = max(1, int(params.get("duration_secs", 30)))
    custom_script_source = params.get("custom_script") or None

    if _stop_requested(job_id):
        # Delivered late (e.g. this worker only just started) after the run
        # was already cancelled — bail before spawning/attaching anything.
        raise RuntimeError("Run was cancelled before this worker picked it up")

    with open(AGENT_PATH) as f:
        agent_source = f.read()

    events_lock = threading.Lock()
    pending_events: list[dict] = []
    run_started = time.time()

    def add_event(event: dict) -> None:
        with events_lock:
            pending_events.append(event)

    def on_main_message(message, _data):
        # agent-bundle.js always sends well-formed {category, summary,
        # detail, ts_offset_ms} payloads — this is our own trusted script.
        if message.get("type") == "error":
            add_event({
                "ts_offset_ms": int((time.time() - run_started) * 1000),
                "category": "error",
                "summary": "built-in agent error: " + message.get("description", "unknown error"),
                "detail": {"stack": message.get("stack")},
            })
            return
        if message.get("type") != "send":
            return
        payload = message.get("payload")
        if not isinstance(payload, dict):
            return
        add_event({
            "ts_offset_ms": payload.get("ts_offset_ms", 0),
            "category": payload.get("category", "lifecycle"),
            "summary": payload.get("summary", ""),
            "detail": payload.get("detail"),
        })

    def on_custom_message(message, _data):
        # A user-supplied script can be anything copy-pasted from the wild —
        # it won't know our event shape, so normalize whatever it sends
        # rather than requiring it to cooperate with our schema.
        offset = int((time.time() - run_started) * 1000)
        if message.get("type") == "error":
            add_event({
                "ts_offset_ms": offset,
                "category": "error",
                "summary": "custom script error: " + message.get("description", "unknown error"),
                "detail": {"stack": message.get("stack")},
            })
            return
        if message.get("type") != "send":
            return
        payload = message.get("payload")
        if isinstance(payload, dict) and "summary" in payload:
            category = payload.get("category") or "custom"
            summary = str(payload.get("summary"))
            detail = payload.get("detail", payload)
        else:
            category = "custom"
            summary = payload if isinstance(payload, str) else json.dumps(payload)[:200]
            detail = payload
        add_event({"ts_offset_ms": offset, "category": category, "summary": summary, "detail": detail})

    def flush() -> None:
        with events_lock:
            batch = pending_events[:]
        if not batch:
            return
        if _post_events(job_id, batch):
            with events_lock:
                # Only drop what we just confirmed was stored — anything the
                # message-handler thread appended in the meantime is at the
                # tail and stays queued for the next flush.
                del pending_events[:len(batch)]
        # else: leave pending_events untouched and retry this same batch
        # (plus whatever's accumulated since) on the next flush() call.

    device_id = params.get("device_id")
    _post_progress(job_id, 2, "Looking for USB device…" if not device_id else "Connecting to device…")
    device = device_manager.get_device(device_id, USB_DEVICE_TIMEOUT_SECS)

    _post_progress(job_id, 5, f"Starting {bundle_id}…")
    pid, spawned = _spawn_or_attach(device, bundle_id)
    session = device.attach(pid)

    script = session.create_script(agent_source, runtime="v8")
    script.on("message", on_main_message)
    script.load()

    _post_progress(job_id, 20, "Installing hooks…")
    script.exports_sync.configure({
        "classes": params.get("classes", []),
        "trace_network": params.get("trace_network", True),
        "trace_crypto": params.get("trace_crypto", True),
    })

    if custom_script_source:
        _post_progress(job_id, 25, "Compiling custom script…")
        try:
            compiled_source = _compile_custom_script(custom_script_source)
            custom_script = session.create_script(compiled_source, runtime="v8")
            custom_script.on("message", on_custom_message)
            custom_script.load()
        except Exception as exc:
            add_event({
                "ts_offset_ms": int((time.time() - run_started) * 1000),
                "category": "error",
                "summary": "custom script failed to compile/load",
                "detail": {"error": str(exc)},
            })

    if spawned:
        device.resume(pid)

    _post_progress(job_id, 30, "Tracing…")
    started = time.time()
    try:
        while time.time() - started < duration_secs:
            time.sleep(POLL_INTERVAL_SECS)
            flush()
            elapsed_ratio = min(1.0, (time.time() - started) / duration_secs)
            _post_progress(job_id, 30 + int(elapsed_ratio * 65), "Tracing…")
            if _stop_requested(job_id):
                break
    finally:
        flush()
        try:
            session.detach()
        except Exception:
            pass
