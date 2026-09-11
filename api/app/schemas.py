from datetime import datetime
from typing import Optional, Any

from pydantic import BaseModel


class IPAOut(BaseModel):
    id: str
    original_filename: str
    size_bytes: int
    status: str
    error_message: Optional[str] = None
    uploaded_at: datetime

    class Config:
        from_attributes = True


class FileTreeNodeOut(BaseModel):
    path: str
    name: str
    kind: str
    size_bytes: Optional[int] = None
    mime_guess: Optional[str] = None
    is_main_binary: bool = False
    children: list["FileTreeNodeOut"] = []


class PlistOut(BaseModel):
    kind: str
    node_path: str
    parsed: Any


class MethodOut(BaseModel):
    selector: str
    type_encoding: Optional[str] = None
    address: Optional[int] = None


class PropertyOut(BaseModel):
    name: str
    attributes: Optional[str] = None


class IvarOut(BaseModel):
    name: str
    type_encoding: Optional[str] = None
    offset: Optional[int] = None


class ObjCClassOut(BaseModel):
    name: str
    superclass: Optional[str] = None
    superclass_resolved: bool = False
    instance_methods: list[MethodOut] = []
    class_methods: list[MethodOut] = []
    properties: list[PropertyOut] = []
    protocols: list[str] = []
    ivars: list[IvarOut] = []


class ObjCClassesResponse(BaseModel):
    classes: list[ObjCClassOut]
    warnings: list[str] = []


class FilePreviewOut(BaseModel):
    path: str
    size_bytes: int
    kind: str
    mime_guess: Optional[str] = None
    text: Optional[str] = None
    parsed: Optional[Any] = None
    image_base64: Optional[str] = None
    hex_preview: Optional[str] = None
    truncated: bool = False

    class Config:
        from_attributes = True


class FunctionOut(BaseModel):
    address: int
    name: str
    source: str  # "objc_method" | "symbol"
    class_name: Optional[str] = None
    is_class_method: Optional[bool] = None


class DisasmOpOut(BaseModel):
    address: Optional[int] = None
    bytes: Optional[str] = None
    disasm: Optional[str] = None
    type: Optional[str] = None


class CallOut(BaseModel):
    address: int
    target: int
    target_name: Optional[str] = None


class CallerOut(BaseModel):
    address: int
    caller_name: Optional[str] = None


class DisasmOut(BaseModel):
    address: int
    name: Optional[str] = None
    size: Optional[int] = None
    signature: Optional[str] = None
    ops: list[DisasmOpOut] = []
    calls_out: list[CallOut] = []
    callers_in: list[CallerOut] = []
    decompiled_code: Optional[str] = None
    decompile_error: Optional[str] = None


class DisasmRequestResult(BaseModel):
    cached: bool
    result: Optional[DisasmOut] = None
    job_id: Optional[str] = None


class CompareScanRef(BaseModel):
    id: str
    filename: str


class FileEntryOut(BaseModel):
    path: str
    kind: str
    size_bytes: Optional[int] = None


class FileChangedOut(BaseModel):
    path: str
    size_a: Optional[int] = None
    size_b: Optional[int] = None


class FileDiffOut(BaseModel):
    only_in_a: list[FileEntryOut] = []
    only_in_a_total: int = 0
    only_in_b: list[FileEntryOut] = []
    only_in_b_total: int = 0
    changed: list[FileChangedOut] = []
    changed_total: int = 0
    common_total: int = 0


class ClassSummaryOut(BaseModel):
    name: str
    superclass: Optional[str] = None
    instance_method_count: int = 0
    class_method_count: int = 0
    property_count: int = 0


class ClassChangedOut(BaseModel):
    name: str
    a: ClassSummaryOut
    b: ClassSummaryOut


class ClassDiffOut(BaseModel):
    only_in_a: list[ClassSummaryOut] = []
    only_in_a_total: int = 0
    only_in_b: list[ClassSummaryOut] = []
    only_in_b_total: int = 0
    changed: list[ClassChangedOut] = []
    changed_total: int = 0
    common_total: int = 0


class FunctionDiffOut(BaseModel):
    only_in_a: list[str] = []
    only_in_a_total: int = 0
    only_in_b: list[str] = []
    only_in_b_total: int = 0
    common_total: int = 0


class CompareResponse(BaseModel):
    a: CompareScanRef
    b: CompareScanRef
    files: FileDiffOut
    classes: ClassDiffOut
    functions: FunctionDiffOut
    job_id: Optional[str] = None


class JobOut(BaseModel):
    id: str
    ipa_id: str
    phase: str
    status: str
    progress_pct: int
    message: Optional[str] = None
    error_message: Optional[str] = None
    context_address: Optional[int] = None

    class Config:
        from_attributes = True
