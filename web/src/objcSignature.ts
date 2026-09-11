// Decodes Objective-C runtime type-encoding strings (as produced by @encode /
// stored in method_t.types and property_t.attributes) into class-dump-style
// readable declarations. Deliberately simplified for structs/unions/blocks —
// good enough for a readable header view, not a full clang type-encoding parser.

const PRIMITIVE_TYPES: Record<string, string> = {
  v: "void",
  c: "BOOL",
  i: "int",
  s: "short",
  l: "long",
  q: "long long",
  C: "unsigned char",
  I: "unsigned int",
  S: "unsigned short",
  L: "unsigned long",
  Q: "unsigned long long",
  f: "float",
  d: "double",
  B: "_Bool",
};

function skipBalanced(enc: string, pos: number, open: string, close: string): number {
  let depth = 0;
  do {
    if (enc[pos] === open) depth++;
    else if (enc[pos] === close) depth--;
    pos++;
  } while (depth > 0 && pos < enc.length);
  return pos;
}

// Returns [decodedType, nextPos]
function decodeOneType(enc: string, pos: number): [string, number] {
  const c = enc[pos];

  if (c === "@") {
    if (enc[pos + 1] === '"') {
      const end = enc.indexOf('"', pos + 2);
      const className = end === -1 ? enc.slice(pos + 2) : enc.slice(pos + 2, end);
      const nextPos = end === -1 ? enc.length : end + 1;
      // A quoted name starting with "<" is a protocol qualification on `id`
      // (e.g. @"<MBMoneyResource>"), not a class name — render as id<Proto>.
      return className.startsWith("<") ? [`id${className}`, nextPos] : [`${className} *`, nextPos];
    }
    return ["id", pos + 1];
  }
  if (c === "^") {
    const [inner, next] = decodeOneType(enc, pos + 1);
    return [inner.endsWith("*") ? `${inner}*` : `${inner} *`, next];
  }
  if (c === "#") return ["Class", pos + 1];
  if (c === ":") return ["SEL", pos + 1];
  if (c === "*") return ["char *", pos + 1];
  if (c === "{") return ["struct", skipBalanced(enc, pos, "{", "}")];
  if (c === "(") return ["union", skipBalanced(enc, pos, "(", ")")];
  if (c === "[") return ["array", skipBalanced(enc, pos, "[", "]")];
  if (c in PRIMITIVE_TYPES) return [PRIMITIVE_TYPES[c], pos + 1];
  return [c ?? "?", pos + 1];
}

function skipDigits(enc: string, pos: number): number {
  while (pos < enc.length && enc[pos] >= "0" && enc[pos] <= "9") pos++;
  return pos;
}

/** Parses a full method type-encoding into [returnType, ...argTypes] (argTypes
 * includes the implicit self/_cmd at index 0/1, matching Obj-C convention). */
export function parseMethodTypes(encoding: string | null | undefined): string[] {
  if (!encoding) return [];
  const types: string[] = [];
  let pos = 0;
  pos = skipDigits(encoding, pos); // leading frame size, if present
  while (pos < encoding.length) {
    const [type, next] = decodeOneType(encoding, pos);
    types.push(type);
    pos = skipDigits(encoding, next);
  }
  return types;
}

export function formatMethodDeclaration(
  selector: string,
  typeEncoding: string | null | undefined,
  isClassMethod: boolean
): string {
  const types = parseMethodTypes(typeEncoding);
  const returnType = types[0] ?? "id";
  const argTypes = types.slice(3); // skip return, self(@), _cmd(:)
  const prefix = isClassMethod ? "+" : "-";

  if (!selector.includes(":")) {
    return `${prefix} (${returnType})${selector};`;
  }
  const parts = selector.split(":").filter((p, i, arr) => i < arr.length - 1 || p !== "");
  const pieces = parts.map((part, i) => {
    const argType = argTypes[i] ?? "id";
    return `${part}:(${argType})arg${i + 1}`;
  });
  return `${prefix} (${returnType})${pieces.join(" ")};`;
}

interface DecodedProperty {
  type: string;
  attrs: string[];
  ivarName: string | null;
}

function decodePropertyAttributes(attributes: string | null | undefined): DecodedProperty {
  if (!attributes) return { type: "id", attrs: [], ivarName: null };
  const segments = attributes.split(",");
  let type = "id";
  const attrs: string[] = [];
  let ivarName: string | null = null;

  for (const seg of segments) {
    const tag = seg[0];
    const rest = seg.slice(1);
    switch (tag) {
      case "T":
        type = decodeOneType(rest, 0)[0];
        break;
      case "R":
        attrs.push("readonly");
        break;
      case "C":
        attrs.push("copy");
        break;
      case "&":
        attrs.push("strong");
        break;
      case "N":
        attrs.push("nonatomic");
        break;
      case "W":
        attrs.push("weak");
        break;
      case "D":
        attrs.push("dynamic");
        break;
      case "G":
        attrs.push(`getter=${rest}`);
        break;
      case "S":
        attrs.push(`setter=${rest}`);
        break;
      case "V":
        ivarName = rest;
        break;
      default:
        break;
    }
  }
  return { type, attrs, ivarName };
}

export function formatPropertyDeclaration(name: string, attributes: string | null | undefined): string {
  const { type, attrs } = decodePropertyAttributes(attributes);
  const attrStr = attrs.length ? ` (${attrs.join(", ")})` : "";
  const pointerType = type.endsWith("*");
  return `@property${attrStr} ${type}${pointerType ? "" : " "}${name};`;
}

export function formatIvarDeclaration(name: string, typeEncoding: string | null | undefined, offset: number | null): string {
  const type = decodeOneType(typeEncoding ?? "?", 0)[0];
  const pointerType = type.endsWith("*");
  const offsetComment = offset != null ? `\t// offset ${offset}` : "";
  return `${type}${pointerType ? "" : " "}${name};${offsetComment}`;
}
