import hashlib
import json
import mimetypes
import os
import uuid
import zipfile

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..celery_client import enqueue_analyze_ipa, enqueue_cleanup_binary, enqueue_disassemble_function
from ..config import settings
from ..db import get_db
from ..fileread import read_member_preview
from ..models import IPA, Job, FileTreeNode, PlistRecord, ObjCClass, DisasmResult
from ..services import get_merged_functions
from ..schemas import (
    IPAOut,
    FileTreeNodeOut,
    PlistOut,
    JobOut,
    FilePreviewOut,
    ObjCClassesResponse,
    ObjCClassOut,
    FunctionOut,
    DisasmOut,
    DisasmRequestResult,
)

router = APIRouter(prefix="/api/ipas", tags=["ipas"])

CHUNK_SIZE = 1024 * 1024


@router.post("/upload", response_model=IPAOut)
async def upload_ipa(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.lower().endswith(".ipa"):
        raise HTTPException(400, "Only .ipa files are accepted")

    os.makedirs(settings.uploads_dir, exist_ok=True)
    ipa_id = uuid.uuid4().hex
    storage_path = os.path.join(settings.uploads_dir, f"{ipa_id}.ipa")

    sha256 = hashlib.sha256()
    size = 0
    try:
        with open(storage_path, "wb") as out:
            while chunk := await file.read(CHUNK_SIZE):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise HTTPException(413, "File exceeds maximum allowed size")
                sha256.update(chunk)
                out.write(chunk)
    except HTTPException:
        if os.path.exists(storage_path):
            os.remove(storage_path)
        raise

    ipa = IPA(
        id=ipa_id,
        original_filename=file.filename,
        sha256=sha256.hexdigest(),
        size_bytes=size,
        storage_path=storage_path,
        status="pending",
    )
    db.add(ipa)
    db.flush()

    job = Job(ipa_id=ipa.id, phase="extract", status="queued")
    db.add(job)
    db.commit()

    task_id = enqueue_analyze_ipa(ipa.id, job.id, storage_path)
    job.celery_task_id = task_id
    db.commit()

    return ipa


@router.get("", response_model=list[IPAOut])
def list_ipas(db: Session = Depends(get_db)):
    return db.query(IPA).order_by(IPA.uploaded_at.desc()).all()


@router.get("/{ipa_id}", response_model=IPAOut)
def get_ipa(ipa_id: str, db: Session = Depends(get_db)):
    ipa = db.get(IPA, ipa_id)
    if not ipa:
        raise HTTPException(404, "IPA not found")
    return ipa


@router.delete("/{ipa_id}", status_code=204)
def delete_ipa(ipa_id: str, db: Session = Depends(get_db)):
    ipa = db.get(IPA, ipa_id)
    if not ipa:
        raise HTTPException(404, "IPA not found")

    if os.path.exists(ipa.storage_path):
        os.remove(ipa.storage_path)

    db.delete(ipa)  # cascades to file tree, plists, classes, symbols, disasm results, jobs
    db.commit()

    enqueue_cleanup_binary(ipa_id)  # removes the worker's cached binary slice, if any
    return None


@router.get("/{ipa_id}/jobs", response_model=list[JobOut])
def list_jobs(ipa_id: str, db: Session = Depends(get_db)):
    return db.query(Job).filter(Job.ipa_id == ipa_id).all()


@router.get("/{ipa_id}/tree", response_model=list[FileTreeNodeOut])
def get_tree(ipa_id: str, db: Session = Depends(get_db)):
    ipa = db.get(IPA, ipa_id)
    if not ipa:
        raise HTTPException(404, "IPA not found")

    nodes = db.query(FileTreeNode).filter(FileTreeNode.ipa_id == ipa_id).all()
    by_path: dict[str, FileTreeNodeOut] = {}
    for n in nodes:
        by_path[n.path] = FileTreeNodeOut(
            path=n.path,
            name=n.name,
            kind=n.kind,
            size_bytes=n.size_bytes,
            mime_guess=n.mime_guess,
            is_main_binary=n.is_main_binary,
            children=[],
        )

    roots: list[FileTreeNodeOut] = []
    for n in nodes:
        node_out = by_path[n.path]
        if n.parent_path and n.parent_path in by_path:
            by_path[n.parent_path].children.append(node_out)
        else:
            roots.append(node_out)

    def sort_children(node: FileTreeNodeOut):
        node.children.sort(key=lambda c: (c.kind != "dir", c.name.lower()))
        for c in node.children:
            sort_children(c)

    roots.sort(key=lambda c: (c.kind != "dir", c.name.lower()))
    for r in roots:
        sort_children(r)

    return roots


@router.get("/{ipa_id}/plists", response_model=list[PlistOut])
def get_plists(ipa_id: str, db: Session = Depends(get_db)):
    records = db.query(PlistRecord).filter(PlistRecord.ipa_id == ipa_id).all()
    return [
        PlistOut(kind=r.kind, node_path=r.node_path, parsed=json.loads(r.parsed_json))
        for r in records
    ]


@router.get("/{ipa_id}/classes", response_model=ObjCClassesResponse)
def get_classes(ipa_id: str, db: Session = Depends(get_db)):
    ipa = db.get(IPA, ipa_id)
    if not ipa:
        raise HTTPException(404, "IPA not found")
    records = db.query(ObjCClass).filter(ObjCClass.ipa_id == ipa_id).order_by(ObjCClass.name).all()
    classes = [
        ObjCClassOut(
            name=r.name,
            superclass=r.superclass,
            superclass_resolved=r.superclass_resolved,
            **json.loads(r.data_json),
        )
        for r in records
    ]
    warnings = json.loads(ipa.objc_warnings_json) if ipa.objc_warnings_json else []
    return ObjCClassesResponse(classes=classes, warnings=warnings)


@router.get("/{ipa_id}/functions", response_model=list[FunctionOut])
def get_functions(ipa_id: str, db: Session = Depends(get_db)):
    ipa = db.get(IPA, ipa_id)
    if not ipa:
        raise HTTPException(404, "IPA not found")
    return [FunctionOut(**f) for f in get_merged_functions(db, ipa_id)]


class DisasmRequest(BaseModel):
    address: int


@router.post("/{ipa_id}/disasm", response_model=DisasmRequestResult)
def request_disasm(ipa_id: str, body: DisasmRequest, db: Session = Depends(get_db)):
    ipa = db.get(IPA, ipa_id)
    if not ipa:
        raise HTTPException(404, "IPA not found")

    cached = (
        db.query(DisasmResult)
        .filter(DisasmResult.ipa_id == ipa_id, DisasmResult.address == body.address)
        .first()
    )
    if cached:
        return DisasmRequestResult(cached=True, result=DisasmOut(**json.loads(cached.data_json)))

    job = Job(ipa_id=ipa_id, phase="disasm", status="queued", context_address=body.address)
    db.add(job)
    db.commit()

    task_id = enqueue_disassemble_function(ipa_id, job.id, body.address)
    job.celery_task_id = task_id
    db.commit()

    return DisasmRequestResult(cached=False, job_id=job.id)


@router.get("/{ipa_id}/disasm/{address}", response_model=DisasmOut)
def get_disasm(ipa_id: str, address: int, db: Session = Depends(get_db)):
    cached = (
        db.query(DisasmResult)
        .filter(DisasmResult.ipa_id == ipa_id, DisasmResult.address == address)
        .first()
    )
    if not cached:
        raise HTTPException(404, "Not disassembled yet")
    return DisasmOut(**json.loads(cached.data_json))


@router.get("/{ipa_id}/file", response_model=FilePreviewOut)
def get_file_preview(ipa_id: str, path: str, db: Session = Depends(get_db)):
    ipa = db.get(IPA, ipa_id)
    if not ipa:
        raise HTTPException(404, "IPA not found")
    try:
        preview = read_member_preview(ipa.storage_path, path)
    except KeyError:
        raise HTTPException(404, "File not found in archive")
    except zipfile.BadZipFile:
        raise HTTPException(500, "Stored archive is corrupt")
    return preview


@router.get("/{ipa_id}/file/download")
def download_file(ipa_id: str, path: str, db: Session = Depends(get_db)):
    ipa = db.get(IPA, ipa_id)
    if not ipa:
        raise HTTPException(404, "IPA not found")

    try:
        zf = zipfile.ZipFile(ipa.storage_path)
        info = zf.getinfo(path)
        stream = zf.open(path)
    except KeyError:
        raise HTTPException(404, "File not found in archive")
    except zipfile.BadZipFile:
        raise HTTPException(500, "Stored archive is corrupt")

    filename = path.rsplit("/", 1)[-1]
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"

    def iter_and_close():
        try:
            while chunk := stream.read(1024 * 256):
                yield chunk
        finally:
            stream.close()
            zf.close()

    return StreamingResponse(
        iter_and_close(),
        media_type=mime,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(info.file_size),
        },
    )
