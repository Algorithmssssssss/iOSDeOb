import requests

from . import runner
from .celery_app import celery_app
from .runner import API_INTERNAL_URL, _headers


@celery_app.task(name="bridge.tasks.run_dynamic_trace", bind=True)
def run_dynamic_trace(self, ipa_id: str, job_id: str, params: dict) -> bool:
    try:
        runner.run(ipa_id, job_id, params)
        payload = {"success": True}
    except Exception as exc:
        payload = {"success": False, "error_message": str(exc)}

    requests.post(
        f"{API_INTERNAL_URL}/internal/dynamic/{job_id}/complete",
        json=payload,
        headers=_headers(),
        timeout=30,
    )
    return payload["success"]
