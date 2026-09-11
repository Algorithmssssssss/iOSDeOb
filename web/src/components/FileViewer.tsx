import { FilePreview } from "../api";

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function FileViewer({
  title,
  preview,
  downloadUrl,
}: {
  title: string;
  preview: FilePreview;
  downloadUrl: string;
}) {
  return (
    <div className="file-viewer">
      <div className="file-viewer-toolbar">
        <div className="file-viewer-title">
          <h3>{title}</h3>
          <span className="file-viewer-meta">
            {formatSize(preview.size_bytes)}
            {preview.mime_guess ? ` · ${preview.mime_guess}` : ""}
          </span>
        </div>
        <a className="btn btn-secondary" href={downloadUrl} download>
          ⭳ Download
        </a>
      </div>

      {preview.kind === "empty" && <div className="empty-hint">Empty file (0 bytes).</div>}

      {preview.kind === "plist" && (
        <pre className="code-block">{JSON.stringify(preview.parsed, null, 2)}</pre>
      )}

      {preview.kind === "text" && <pre className="code-block">{preview.text}</pre>}

      {preview.kind === "image" && (
        <div className="image-preview">
          <img
            src={`data:${preview.mime_guess || "application/octet-stream"};base64,${preview.image_base64}`}
            alt={title}
          />
        </div>
      )}

      {preview.kind === "binary" && (
        <div>
          {preview.truncated && (
            <div className="notice">
              File is {formatSize(preview.size_bytes)} — too large to preview in full. Showing the first
              bytes; use Download for the whole file.
            </div>
          )}
          <pre className="code-block hex-block">{preview.hex_preview}</pre>
        </div>
      )}
    </div>
  );
}
