import os

import requests

from .binarycache import cache_path, delete_cached_binary, load_binary_slice
from .celery_app import celery_app
from .disasm import disassemble_function as run_disassemble_function
from .extract import analyze

API_INTERNAL_URL = os.environ.get("API_INTERNAL_URL", "http://api:8000")
INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "dev-internal-token-change-me")


def _headers() -> dict:
    return {"X-Internal-Token": INTERNAL_TOKEN}


def _report_progress(job_id: str, pct: int, message: str | None = None, phase: str | None = None) -> None:
    try:
        requests.post(
            f"{API_INTERNAL_URL}/internal/jobs/{job_id}/progress",
            json={"progress_pct": pct, "message": message, "phase": phase},
            headers=_headers(),
            timeout=10,
        )
    except Exception:
        pass  # best-effort; final state is still reported via the complete callback


@celery_app.task(name="worker.tasks.analyze_ipa", bind=True)
def analyze_ipa(self, ipa_id: str, job_id: str, storage_path: str) -> bool:
    def progress(pct: int, message: str | None = None, phase: str | None = None) -> None:
        _report_progress(job_id, pct, message, phase)

    try:
        result = analyze(ipa_id, storage_path, progress)
        payload = {
            "success": True,
            "file_tree": result["file_tree"],
            "plists": result["plists"],
            "objc_classes": result["objc_classes"],
            "objc_warnings": result["objc_warnings"],
            "symbols": result["symbols"],
        }
    except Exception as exc:
        payload = {"success": False, "error_message": str(exc)}

    requests.post(
        f"{API_INTERNAL_URL}/internal/jobs/{job_id}/complete",
        json=payload,
        headers=_headers(),
        timeout=60,
    )
    return payload["success"]


@celery_app.task(name="worker.tasks.disassemble_function", bind=True)
def disassemble_function(self, ipa_id: str, job_id: str, address: int) -> bool:
    try:
        binary_data = load_binary_slice(ipa_id)
        result = run_disassemble_function(cache_path(ipa_id), address, binary_data)
        payload = {"success": True, "result": result}
    except Exception as exc:
        payload = {"success": False, "error_message": str(exc)}

    requests.post(
        f"{API_INTERNAL_URL}/internal/jobs/{job_id}/disasm_complete",
        json=payload,
        headers=_headers(),
        timeout=60,
    )
    return payload["success"]


@celery_app.task(name="worker.tasks.cleanup_binary")
def cleanup_binary(ipa_id: str) -> bool:
    delete_cached_binary(ipa_id)
    return True
