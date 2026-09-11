export default function PlistViewer({ title, data }: { title: string; data: unknown }) {
  return (
    <div className="plist-viewer">
      <h3>{title}</h3>
      <pre>{JSON.stringify(data, null, 2)}</pre>
    </div>
  );
}
