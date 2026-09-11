"""Drives one dynamic-trace run: spawn/attach on the USB device, load the
Frida agent, stream events back to the API, and stop after the configured
duration or an early stop request."""

import json
import os
import threading
import time

import frida
import requests

API_INTERNAL_URL = os.environ.get("API_INTERNAL_URL", "http://localhost:8000")
INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "dev-internal-token-change-me")
AGENT_PATH = os.path.join(os.path.dirname(__file__), "..", "agent-bundle.js")
USB_DEVICE_TIMEOUT_SECS = 5
POLL_INTERVAL_SECS = 1


def _headers() -> dict:
    return {"X-Internal-Token": INTERNAL_TOKEN}


def _post_events(job_id: str, events: list[dict]) -> None:
    if not events:
        return
    try:
        requests.post(
            f"{API_INTERNAL_URL}/internal/dynamic/{job_id}/events",
            json={"events": events},
            headers=_headers(),
            timeout=10,
        )
    except Exception:
        pass  # best-effort; a dropped batch shouldn't abort the run


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
            pending_events.clear()
        _post_events(job_id, batch)

    _post_progress(job_id, 2, "Looking for USB device…")
    device = frida.get_usb_device(timeout=USB_DEVICE_TIMEOUT_SECS)

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
        _post_progress(job_id, 25, "Loading custom script…")
        try:
            custom_script = session.create_script(custom_script_source, runtime="v8")
            custom_script.on("message", on_custom_message)
            custom_script.load()
        except Exception as exc:
            add_event({
                "ts_offset_ms": int((time.time() - run_started) * 1000),
                "category": "error",
                "summary": "custom script failed to load",
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
