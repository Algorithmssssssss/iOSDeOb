import { ObjCClass, ObjCMethod } from "../api";
import { formatIvarDeclaration, formatMethodDeclaration, formatPropertyDeclaration } from "../objcSignature";

function addrHex(addr?: number | null): string {
  return addr != null ? `0x${addr.toString(16)}` : "";
}

function MethodLine({
  method,
  isClassMethod,
  onJumpToAddress,
}: {
  method: ObjCMethod;
  isClassMethod: boolean;
  onJumpToAddress?: (address: number) => void;
}) {
  const decl = formatMethodDeclaration(method.selector, method.type_encoding, isClassMethod);
  return (
    <div className="disasm-line">
      <span>{decl}</span>
      {method.address != null && (
        <span
          className={onJumpToAddress ? "addr-link" : ""}
          onClick={() => method.address != null && onJumpToAddress?.(method.address)}
        >
          {"\t// "}
          {addrHex(method.address)}
        </span>
      )}
    </div>
  );
}

export default function ClassHeaderView({
  cls,
  onJumpToAddress,
}: {
  cls: ObjCClass;
  onJumpToAddress?: (address: number) => void;
}) {
  const superclassPart = cls.superclass ? ` : ${cls.superclass}` : "";
  const protocolsPart = cls.protocols.length ? ` <${cls.protocols.join(", ")}>` : "";

  const headerLines: string[] = [`@interface ${cls.name}${superclassPart}${protocolsPart}`];
  if (cls.ivars.length) {
    headerLines.push("{");
    for (const iv of cls.ivars) {
      headerLines.push(`    ${formatIvarDeclaration(iv.name, iv.type_encoding, iv.offset ?? null)}`);
    }
    headerLines.push("}");
  }
  headerLines.push("");
  for (const p of cls.properties) {
    headerLines.push(formatPropertyDeclaration(p.name, p.attributes));
  }

  return (
    <div className="file-viewer">
      <div className="file-viewer-toolbar">
        <div className="file-viewer-title">
          <h3>{cls.name}</h3>
          <span className="file-viewer-meta">
            {cls.instance_methods.length + cls.class_methods.length} methods · {cls.properties.length} properties ·{" "}
            {cls.ivars.length} ivars
          </span>
        </div>
      </div>
      <pre className="code-block disasm-listing">
        {headerLines.join("\n")}
        {"\n"}
        {cls.class_methods.map((m, i) => (
          <MethodLine key={`c${i}`} method={m} isClassMethod onJumpToAddress={onJumpToAddress} />
        ))}
        {cls.instance_methods.map((m, i) => (
          <MethodLine key={`i${i}`} method={m} isClassMethod={false} onJumpToAddress={onJumpToAddress} />
        ))}
        {"\n@end"}
      </pre>
    </div>
  );
}
