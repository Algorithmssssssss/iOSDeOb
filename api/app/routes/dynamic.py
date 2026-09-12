import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..celery_client import celery_client as celery_app, enqueue_dynamic_trace
from ..db import get_db
from ..models import IPA, Job, PlistRecord, DynamicTrace
from ..routes.jobs import _require_internal_token
from ..schemas import (
    StartDynamicRequest,
    DynamicRunOut,
    DynamicRunConfigOut,
    DynamicTraceOut,
    DynamicEventsBatchIn,
    DynamicCompletePayload,
)
from ..ws import broadcaster

router = APIRouter(tags=["dynamic"])

MAX_DURATION_SECS = 300


def _run_out(job: Job) -> DynamicRunOut:
    config = json.loads(job.dynamic_config_json) if job.dynamic_config_json else None
    config_out = None
    if config:
        config_out = DynamicRunConfigOut(
            bundle_id=config.get("bundle_id"),
            classes=config.get("classes", []),
            trace_network=config.get("trace_network", True),
            trace_crypto=config.get("trace_crypto", True),
            duration_secs=config.get("duration_secs", 30),
            has_custom_script=bool(config.get("custom_script")),
            device_id=config.get("device_id"),
        )
    return DynamicRunOut(
        id=job.id,
        ipa_id=job.ipa_id,
        status=job.status,
        progress_pct=job.progress_pct,
        message=job.message,
        error_message=job.error_message,
        stop_requested=job.stop_requested,
        started_at=job.started_at,
        finished_at=job.finished_at,
        config=config_out,
    )


@router.post("/api/ipas/{ipa_id}/dynamic/start", response_model=DynamicRunOut)
def start_dynamic_trace(ipa_id: str, body: StartDynamicRequest, db: Session = Depends(get_db)):
    ipa = db.get(IPA, ipa_id)
    if not ipa:
        raise HTTPException(404, "IPA not found")

    bundle_id = body.bundle_id
    if not bundle_id:
        info = (
            db.query(PlistRecord)
            .filter(PlistRecord.ipa_id == ipa_id, PlistRecord.kind == "info")
            .first()
        )
        if info:
            bundle_id = json.loads(info.parsed_json).get("CFBundleIdentifier")
    if not bundle_id:
        raise HTTPException(400, "No bundle_id given and none found in Info.plist")

    duration_secs = max(1, min(body.duration_secs, MAX_DURATION_SECS))
    config = {
        "bundle_id": bundle_id,
        "classes": body.classes,
        "trace_network": body.trace_network,
        "trace_crypto": body.trace_crypto,
        "duration_secs": duration_secs,
        "custom_script": body.custom_script,
        "device_id": body.device_id,
    }

    job = Job(ipa_id=ipa_id, phase="dynamic", status="queued", dynamic_config_json=json.dumps(config))
    db.add(job)
    db.commit()

    task_id = enqueue_dynamic_trace(ipa_id, job.id, config)
    job.celery_task_id = task_id
    db.commit()

    return _run_out(job)


@router.post("/api/jobs/{job_id}/stop", response_model=DynamicRunOut)
def stop_dynamic_trace(job_id: str, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job or job.phase != "dynamic":
        raise HTTPException(404, "Dynamic run not found")

    job.stop_requested = True

    if job.status == "queued":
        # Never picked up by a live frida-bridge runner (e.g. it isn't
        # running yet) — nothing will ever poll stop_requested, so cancel
        # outright instead of leaving this stuck "stopping" forever. If a
        # runner does pick up the underlying task later, runner.run() checks
        # stop_requested before touching the device and bails immediately.
        if job.celery_task_id:
            try:
                celery_app.control.revoke(job.celery_task_id)
            except Exception:
                pass  # best-effort; the stop_requested check below is the real backstop
        job.status = "failed"
        job.error_message = "Cancelled before a dynamic-analysis runner picked it up."
        job.finished_at = datetime.utcnow()

    db.commit()
    return _run_out(job)


@router.get("/api/ipas/{ipa_id}/dynamic/runs", response_model=list[DynamicRunOut])
def list_dynamic_runs(ipa_id: str, db: Session = Depends(get_db)):
    jobs = db.query(Job).filter(Job.ipa_id == ipa_id, Job.phase == "dynamic").all()
    jobs.sort(key=lambda j: j.started_at or datetime.min, reverse=True)
    return [_run_out(j) for j in jobs]


@router.delete("/api/ipas/{ipa_id}/dynamic/runs/{job_id}", status_code=204)
def delete_dynamic_run(ipa_id: str, job_id: str, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job or job.phase != "dynamic" or job.ipa_id != ipa_id:
        raise HTTPException(404, "Dynamic run not found")
    if job.status in ("queued", "running"):
        raise HTTPException(400, "Stop the run before deleting it")

    db.query(DynamicTrace).filter(DynamicTrace.job_id == job_id).delete()
    db.delete(job)
    db.commit()
    return None


@router.get("/api/ipas/{ipa_id}/dynamic/runs/{job_id}/events", response_model=list[DynamicTraceOut])
def list_dynamic_events(
    ipa_id: str,
    job_id: str,
    after_seq: int = 0,
    category: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(DynamicTrace).filter(
        DynamicTrace.ipa_id == ipa_id,
        DynamicTrace.job_id == job_id,
        DynamicTrace.seq > after_seq,
    )
    if category:
        query = query.filter(DynamicTrace.category == category)
    if q:
        query = query.filter(DynamicTrace.summary.ilike(f"%{q}%"))

    rows = query.order_by(DynamicTrace.seq).all()
    return [
        DynamicTraceOut(
            seq=r.seq,
            ts_offset_ms=r.ts_offset_ms,
            category=r.category,
            summary=r.summary,
            detail=json.loads(r.detail_json),
        )
        for r in rows
    ]


@router.post("/internal/dynamic/{job_id}/events", dependencies=[Depends(_require_internal_token)])
def internal_dynamic_events(job_id: str, payload: DynamicEventsBatchIn, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    # MAX rather than COUNT: the next sequence number must never collide
    # with one already stored, even if rows were ever deleted/skipped —
    # COUNT silently assumes a gap-free history, which isn't guaranteed.
    next_seq = (
        db.query(func.max(DynamicTrace.seq))
        .filter(DynamicTrace.job_id == job_id)
        .scalar()
    ) or 0
    for evt in payload.events:
        next_seq += 1
        db.add(DynamicTrace(
            ipa_id=job.ipa_id,
            job_id=job_id,
            seq=next_seq,
            ts_offset_ms=evt.ts_offset_ms,
            category=evt.category,
            summary=evt.summary,
            detail_json=json.dumps(evt.detail),
        ))
    db.commit()
    return {"ok": True}


@router.post("/internal/dynamic/{job_id}/complete", dependencies=[Depends(_require_internal_token)])
async def internal_dynamic_complete(job_id: str, payload: DynamicCompletePayload, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    if payload.success:
        job.status = "done"
        job.progress_pct = 100
    else:
        job.status = "failed"
        job.error_message = payload.error_message

    job.finished_at = datetime.utcnow()
    db.commit()

    await broadcaster.publish(job_id, {
        "job_id": job_id,
        "status": job.status,
        "progress_pct": job.progress_pct,
        "message": job.error_message if not payload.success else "done",
    })
    return {"ok": True}
