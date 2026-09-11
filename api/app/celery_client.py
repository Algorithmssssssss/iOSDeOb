from celery import Celery

from .config import settings

celery_client = Celery("api_client", broker=settings.redis_url)


def enqueue_analyze_ipa(ipa_id: str, job_id: str, storage_path: str) -> str:
    result = celery_client.send_task(
        "worker.tasks.analyze_ipa",
        args=[ipa_id, job_id, storage_path],
    )
    return result.id


def enqueue_disassemble_function(ipa_id: str, job_id: str, address: int) -> str:
    result = celery_client.send_task(
        "worker.tasks.disassemble_function",
        args=[ipa_id, job_id, address],
    )
    return result.id


def enqueue_cleanup_binary(ipa_id: str) -> str:
    result = celery_client.send_task(
        "worker.tasks.cleanup_binary",
        args=[ipa_id],
    )
    return result.id


def enqueue_dynamic_trace(ipa_id: str, job_id: str, params: dict) -> str:
    result = celery_client.send_task(
        "bridge.tasks.run_dynamic_trace",
        args=[ipa_id, job_id, params],
        queue="frida",
    )
    return result.id
