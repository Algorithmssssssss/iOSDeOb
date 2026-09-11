from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import IPA, FileTreeNode, ObjCClass
from ..services import get_class_summary, get_merged_functions
from ..schemas import (
    CompareResponse,
    CompareScanRef,
    FileDiffOut,
    FileEntryOut,
    FileChangedOut,
    ClassDiffOut,
    ClassSummaryOut,
    ClassChangedOut,
    FunctionDiffOut,
)

router = APIRouter(prefix="/api/compare", tags=["compare"])

MAX_DIFF_ITEMS = 2000


@router.get("", response_model=CompareResponse)
def compare_scans(a: str, b: str, db: Session = Depends(get_db)):
    if a == b:
        raise HTTPException(400, "Pick two different scans to compare")

    ipa_a = db.get(IPA, a)
    ipa_b = db.get(IPA, b)
    if not ipa_a or not ipa_b:
        raise HTTPException(404, "One or both scans not found")

    files = _diff_files(db, a, b)
    classes = _diff_classes(db, a, b)
    functions = _diff_functions(db, a, b)

    return CompareResponse(
        a=CompareScanRef(id=ipa_a.id, filename=ipa_a.original_filename),
        b=CompareScanRef(id=ipa_b.id, filename=ipa_b.original_filename),
        files=files,
        classes=classes,
        functions=functions,
    )


def _diff_files(db: Session, a: str, b: str) -> FileDiffOut:
    nodes_a = {n.path: n for n in db.query(FileTreeNode).filter(FileTreeNode.ipa_id == a).all()}
    nodes_b = {n.path: n for n in db.query(FileTreeNode).filter(FileTreeNode.ipa_id == b).all()}

    only_a = sorted(set(nodes_a) - set(nodes_b))
    only_b = sorted(set(nodes_b) - set(nodes_a))
    common = set(nodes_a) & set(nodes_b)

    changed = sorted(
        (
            FileChangedOut(path=p, size_a=nodes_a[p].size_bytes, size_b=nodes_b[p].size_bytes)
            for p in common
            if nodes_a[p].kind == "file"
            and nodes_b[p].kind == "file"
            and nodes_a[p].size_bytes != nodes_b[p].size_bytes
        ),
        key=lambda c: c.path,
    )

    return FileDiffOut(
        only_in_a=[FileEntryOut(path=p, kind=nodes_a[p].kind, size_bytes=nodes_a[p].size_bytes) for p in only_a[:MAX_DIFF_ITEMS]],
        only_in_a_total=len(only_a),
        only_in_b=[FileEntryOut(path=p, kind=nodes_b[p].kind, size_bytes=nodes_b[p].size_bytes) for p in only_b[:MAX_DIFF_ITEMS]],
        only_in_b_total=len(only_b),
        changed=changed[:MAX_DIFF_ITEMS],
        changed_total=len(changed),
        common_total=len(common),
    )


def _diff_classes(db: Session, a: str, b: str) -> ClassDiffOut:
    classes_a = {c.name: c for c in db.query(ObjCClass).filter(ObjCClass.ipa_id == a).all()}
    classes_b = {c.name: c for c in db.query(ObjCClass).filter(ObjCClass.ipa_id == b).all()}

    only_a = sorted(set(classes_a) - set(classes_b))
    only_b = sorted(set(classes_b) - set(classes_a))
    common = set(classes_a) & set(classes_b)

    changed = []
    for name in common:
        summary_a = get_class_summary(classes_a[name])
        summary_b = get_class_summary(classes_b[name])
        if summary_a != summary_b:
            changed.append(ClassChangedOut(name=name, a=ClassSummaryOut(**summary_a), b=ClassSummaryOut(**summary_b)))
    changed.sort(key=lambda c: c.name)

    return ClassDiffOut(
        only_in_a=[ClassSummaryOut(**get_class_summary(classes_a[n])) for n in only_a[:MAX_DIFF_ITEMS]],
        only_in_a_total=len(only_a),
        only_in_b=[ClassSummaryOut(**get_class_summary(classes_b[n])) for n in only_b[:MAX_DIFF_ITEMS]],
        only_in_b_total=len(only_b),
        changed=changed[:MAX_DIFF_ITEMS],
        changed_total=len(changed),
        common_total=len(common),
    )


def _diff_functions(db: Session, a: str, b: str) -> FunctionDiffOut:
    names_a = {f["name"] for f in get_merged_functions(db, a)}
    names_b = {f["name"] for f in get_merged_functions(db, b)}

    only_a = sorted(names_a - names_b)
    only_b = sorted(names_b - names_a)

    return FunctionDiffOut(
        only_in_a=only_a[:MAX_DIFF_ITEMS],
        only_in_a_total=len(only_a),
        only_in_b=only_b[:MAX_DIFF_ITEMS],
        only_in_b_total=len(only_b),
        common_total=len(names_a & names_b),
    )
