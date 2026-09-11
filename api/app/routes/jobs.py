import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Header, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import IPA, Job, FileTreeNode, PlistRecord, ObjCClass, SymbolEntry, DisasmResult
from ..schemas import JobOut
from ..ws import broadcaster

router = APIRouter(tags=["jobs"])


@router.get("/api/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@router.websocket("/ws/jobs/{job_id}")
async def job_progress_ws(websocket: WebSocket, job_id: str):
    await websocket.accept()
    await broadcaster.subscribe(job_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await broadcaster.unsubscribe(job_id, websocket)


def _require_internal_token(x_internal_token: str = Header(default="")):
    if x_internal_token != settings.internal_token:
        raise HTTPException(403, "Invalid internal token")


class ProgressPayload(BaseModel):
    progress_pct: int
    message: str | None = None
    phase: str | None = None


class FileTreeNodeIn(BaseModel):
    parent_path: str | None
    path: str
    name: str
    kind: str
    size_bytes: int | None = None
    mime_guess: str | None = None
    is_main_binary: bool = False


class PlistIn(BaseModel):
    node_path: str
    kind: str
    parsed: dict | list


class MethodIn(BaseModel):
    selector: str
    type_encoding: str | None = None
    address: int | None = None


class PropertyIn(BaseModel):
    name: str
    attributes: str | None = None


class IvarIn(BaseModel):
    name: str
    type_encoding: str | None = None
    offset: int | None = None


class ObjCClassIn(BaseModel):
    name: str
    superclass: str | None = None
    superclass_resolved: bool = False
    instance_methods: list[MethodIn] = []
    class_methods: list[MethodIn] = []
    properties: list[PropertyIn] = []
    protocols: list[str] = []
    ivars: list[IvarIn] = []


class SymbolIn(BaseModel):
    name: str
    address: int


class CompletePayload(BaseModel):
    success: bool
    error_message: str | None = None
    file_tree: list[FileTreeNodeIn] = []
    plists: list[PlistIn] = []
    objc_classes: list[ObjCClassIn] = []
    objc_warnings: list[str] = []
    symbols: list[SymbolIn] = []


class DisasmOpIn(BaseModel):
    address: int | None = None
    bytes: str | None = None
    disasm: str | None = None
    type: str | None = None


class CallOutIn(BaseModel):
    address: int
    target: int


class DisasmResultIn(BaseModel):
    address: int
    name: str | None = None
    size: int | None = None
    signature: str | None = None
    ops: list[DisasmOpIn] = []
    calls_out: list[CallOutIn] = []
    callers_in: list[int] = []
    decompiled_code: str | None = None
    decompile_error: str | None = None


class DisasmCompletePayload(BaseModel):
    success: bool
    error_message: str | None = None
    result: DisasmResultIn | None = None


def _build_address_name_index(db: Session, ipa_id: str) -> dict[int, str]:
    index: dict[int, str] = {}
    for row in db.query(ObjCClass).filter(ObjCClass.ipa_id == ipa_id).all():
        data = json.loads(row.data_json)
        for m in data.get("instance_methods", []):
            if m.get("address") is not None:
                index[m["address"]] = f"-[{row.name} {m['selector']}]"
        for m in data.get("class_methods", []):
            if m.get("address") is not None:
                index[m["address"]] = f"+[{row.name} {m['selector']}]"
    for s in db.query(SymbolEntry).filter(SymbolEntry.ipa_id == ipa_id).all():
        index.setdefault(s.address, s.name)
    return index


@router.post("/internal/jobs/{job_id}/progress", dependencies=[Depends(_require_internal_token)])
async def internal_job_progress(job_id: str, payload: ProgressPayload, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    job.status = "running"
    job.progress_pct = payload.progress_pct
    job.message = payload.message
    if payload.phase:
        job.phase = payload.phase
    if not job.started_at:
        job.started_at = datetime.utcnow()
    db.commit()

    await broadcaster.publish(job_id, {
        "job_id": job_id,
        "status": job.status,
        "progress_pct": job.progress_pct,
        "message": job.message,
        "phase": job.phase,
    })
    return {"ok": True}


@router.post("/internal/jobs/{job_id}/complete", dependencies=[Depends(_require_internal_token)])
async def internal_job_complete(job_id: str, payload: CompletePayload, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    ipa = db.get(IPA, job.ipa_id)

    if payload.success:
        db.query(FileTreeNode).filter(FileTreeNode.ipa_id == job.ipa_id).delete()
        db.query(PlistRecord).filter(PlistRecord.ipa_id == job.ipa_id).delete()
        db.query(ObjCClass).filter(ObjCClass.ipa_id == job.ipa_id).delete()
        db.query(SymbolEntry).filter(SymbolEntry.ipa_id == job.ipa_id).delete()
        db.query(DisasmResult).filter(DisasmResult.ipa_id == job.ipa_id).delete()

        for node in payload.file_tree:
            db.add(FileTreeNode(
                ipa_id=job.ipa_id,
                parent_path=node.parent_path,
                path=node.path,
                name=node.name,
                kind=node.kind,
                size_bytes=node.size_bytes,
                mime_guess=node.mime_guess,
                is_main_binary=node.is_main_binary,
            ))

        for p in payload.plists:
            db.add(PlistRecord(
                ipa_id=job.ipa_id,
                node_path=p.node_path,
                kind=p.kind,
                parsed_json=json.dumps(p.parsed),
            ))

        for cls in payload.objc_classes:
            db.add(ObjCClass(
                ipa_id=job.ipa_id,
                name=cls.name,
                superclass=cls.superclass,
                superclass_resolved=cls.superclass_resolved,
                data_json=json.dumps({
                    "instance_methods": [m.model_dump() for m in cls.instance_methods],
                    "class_methods": [m.model_dump() for m in cls.class_methods],
                    "properties": [p.model_dump() for p in cls.properties],
                    "protocols": cls.protocols,
                    "ivars": [i.model_dump() for i in cls.ivars],
                }),
            ))

        for sym in payload.symbols:
            db.add(SymbolEntry(ipa_id=job.ipa_id, name=sym.name, address=sym.address))

        job.status = "done"
        job.progress_pct = 100
        if ipa:
            ipa.status = "ready"
            ipa.objc_warnings_json = json.dumps(payload.objc_warnings)
    else:
        job.status = "failed"
        job.error_message = payload.error_message
        if ipa:
            ipa.status = "failed"
            ipa.error_message = payload.error_message

    job.finished_at = datetime.utcnow()
    db.commit()

    await broadcaster.publish(job_id, {
        "job_id": job_id,
        "status": job.status,
        "progress_pct": job.progress_pct,
        "message": job.error_message if not payload.success else "done",
    })
    return {"ok": True}


@router.post("/internal/jobs/{job_id}/disasm_complete", dependencies=[Depends(_require_internal_token)])
async def internal_disasm_complete(job_id: str, payload: DisasmCompletePayload, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    if payload.success and payload.result:
        result = payload.result
        name_index = _build_address_name_index(db, job.ipa_id)

        calls_out = [
            {"address": c.address, "target": c.target, "target_name": name_index.get(c.target)}
            for c in result.calls_out
        ]
        callers_in = [
            {"address": addr, "caller_name": name_index.get(addr)} for addr in result.callers_in
        ]

        data = {
            "address": result.address,
            "name": result.name,
            "size": result.size,
            "signature": result.signature,
            "ops": [op.model_dump() for op in result.ops],
            "calls_out": calls_out,
            "callers_in": callers_in,
            "decompiled_code": result.decompiled_code,
            "decompile_error": result.decompile_error,
        }

        db.query(DisasmResult).filter(
            DisasmResult.ipa_id == job.ipa_id, DisasmResult.address == result.address
        ).delete()
        db.add(DisasmResult(
            ipa_id=job.ipa_id,
            address=result.address,
            name=result.name,
            size=result.size,
            signature=result.signature,
            data_json=json.dumps(data),
        ))
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
