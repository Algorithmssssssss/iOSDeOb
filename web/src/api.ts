export interface IPA {
  id: string;
  original_filename: string;
  size_bytes: number;
  status: "pending" | "extracting" | "ready" | "failed" | string;
  error_message?: string | null;
  uploaded_at: string;
}

export interface FileTreeNode {
  path: string;
  name: string;
  kind: "file" | "dir";
  size_bytes?: number | null;
  mime_guess?: string | null;
  is_main_binary: boolean;
  children: FileTreeNode[];
}

export interface PlistEntry {
  kind: "info" | "entitlements" | "other";
  node_path: string;
  parsed: unknown;
}

export interface FilePreview {
  path: string;
  size_bytes: number;
  kind: "plist" | "text" | "image" | "binary" | "empty";
  mime_guess?: string | null;
  text?: string | null;
  parsed?: unknown;
  image_base64?: string | null;
  hex_preview?: string | null;
  truncated: boolean;
}

export interface Job {
  id: string;
  ipa_id: string;
  phase: string;
  status: string;
  progress_pct: number;
  message?: string | null;
  error_message?: string | null;
  context_address?: number | null;
}

export interface ObjCMethod {
  selector: string;
  type_encoding?: string | null;
  address?: number | null;
}

export interface ObjCProperty {
  name: string;
  attributes?: string | null;
}

export interface ObjCIvar {
  name: string;
  type_encoding?: string | null;
  offset?: number | null;
}

export interface ObjCClass {
  name: string;
  superclass?: string | null;
  superclass_resolved: boolean;
  instance_methods: ObjCMethod[];
  class_methods: ObjCMethod[];
  properties: ObjCProperty[];
  protocols: string[];
  ivars: ObjCIvar[];
}

export interface ObjCClassesResponse {
  classes: ObjCClass[];
  warnings: string[];
}

export interface FunctionEntry {
  address: number;
  name: string;
  source: "objc_method" | "symbol";
  class_name?: string | null;
  is_class_method?: boolean | null;
}

export interface DisasmOp {
  address?: number | null;
  bytes?: string | null;
  disasm?: string | null;
  type?: string | null;
}

export interface CallOut {
  address: number;
  target: number;
  target_name?: string | null;
}

export interface CallerIn {
  address: number;
  caller_name?: string | null;
}

export interface DisasmResult {
  address: number;
  name?: string | null;
  size?: number | null;
  signature?: string | null;
  ops: DisasmOp[];
  calls_out: CallOut[];
  callers_in: CallerIn[];
}

export interface DisasmRequestResult {
  cached: boolean;
  result?: DisasmResult | null;
  job_id?: string | null;
}

const API_BASE = "/api";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export async function listIpas(): Promise<IPA[]> {
  return json(await fetch(`${API_BASE}/ipas`));
}

export async function getIpa(id: string): Promise<IPA> {
  return json(await fetch(`${API_BASE}/ipas/${id}`));
}

export async function deleteIpa(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/ipas/${id}`, { method: "DELETE" });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
}

export async function getTree(id: string): Promise<FileTreeNode[]> {
  return json(await fetch(`${API_BASE}/ipas/${id}/tree`));
}

export async function getPlists(id: string): Promise<PlistEntry[]> {
  return json(await fetch(`${API_BASE}/ipas/${id}/plists`));
}

export async function listJobs(id: string): Promise<Job[]> {
  return json(await fetch(`${API_BASE}/ipas/${id}/jobs`));
}

export async function getClasses(id: string): Promise<ObjCClassesResponse> {
  return json(await fetch(`${API_BASE}/ipas/${id}/classes`));
}

export async function getFunctions(id: string): Promise<FunctionEntry[]> {
  return json(await fetch(`${API_BASE}/ipas/${id}/functions`));
}

export async function requestDisasm(id: string, address: number): Promise<DisasmRequestResult> {
  return json(
    await fetch(`${API_BASE}/ipas/${id}/disasm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ address }),
    })
  );
}

export async function getDisasm(id: string, address: number): Promise<DisasmResult> {
  return json(await fetch(`${API_BASE}/ipas/${id}/disasm/${address}`));
}

export async function getFilePreview(ipaId: string, path: string): Promise<FilePreview> {
  return json(await fetch(`${API_BASE}/ipas/${ipaId}/file?path=${encodeURIComponent(path)}`));
}

export function fileDownloadUrl(ipaId: string, path: string): string {
  return `${API_BASE}/ipas/${ipaId}/file/download?path=${encodeURIComponent(path)}`;
}

export async function getJob(jobId: string): Promise<Job> {
  return json(await fetch(`${API_BASE}/jobs/${jobId}`));
}

export async function uploadIpa(
  file: File,
  onProgress?: (pct: number) => void
): Promise<IPA> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/ipas/upload`);
    xhr.upload.onprogress = (evt) => {
      if (evt.lengthComputable && onProgress) {
        onProgress(Math.round((evt.loaded / evt.total) * 100));
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText));
      } else {
        reject(new Error(`Upload failed: ${xhr.status} ${xhr.responseText}`));
      }
    };
    xhr.onerror = () => reject(new Error("Upload failed: network error"));
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}

export interface CompareScanRef {
  id: string;
  filename: string;
}

export interface FileEntry {
  path: string;
  kind: string;
  size_bytes?: number | null;
}

export interface FileChanged {
  path: string;
  size_a?: number | null;
  size_b?: number | null;
}

export interface FileDiff {
  only_in_a: FileEntry[];
  only_in_a_total: number;
  only_in_b: FileEntry[];
  only_in_b_total: number;
  changed: FileChanged[];
  changed_total: number;
  common_total: number;
}

export interface ClassSummary {
  name: string;
  superclass?: string | null;
  instance_method_count: number;
  class_method_count: number;
  property_count: number;
}

export interface ClassChanged {
  name: string;
  a: ClassSummary;
  b: ClassSummary;
}

export interface ClassDiff {
  only_in_a: ClassSummary[];
  only_in_a_total: number;
  only_in_b: ClassSummary[];
  only_in_b_total: number;
  changed: ClassChanged[];
  changed_total: number;
  common_total: number;
}

export interface FunctionDiff {
  only_in_a: string[];
  only_in_a_total: number;
  only_in_b: string[];
  only_in_b_total: number;
  common_total: number;
}

export interface CompareResult {
  a: CompareScanRef;
  b: CompareScanRef;
  files: FileDiff;
  classes: ClassDiff;
  functions: FunctionDiff;
}

export async function compareScans(aId: string, bId: string): Promise<CompareResult> {
  return json(await fetch(`${API_BASE}/compare?a=${encodeURIComponent(aId)}&b=${encodeURIComponent(bId)}`));
}

export function jobSocketUrl(jobId: string): string {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/ws/jobs/${jobId}`;
}
