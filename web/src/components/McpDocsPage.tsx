import { useState, type ReactNode } from "react";

const VENV_PYTHON = "/Users/reachkim/Documents/Codes/iOSDeOb/mcp-server/.venv/bin/python";
const SERVER_PY = "/Users/reachkim/Documents/Codes/iOSDeOb/mcp-server/server.py";

const DESKTOP_CONFIG = `{
  "mcpServers": {
    "iosdeob": {
      "command": "${VENV_PYTHON}",
      "args": ["${SERVER_PY}"]
    }
  }
}`;

const CODE_CONFIG = DESKTOP_CONFIG;

const CLI_CONFIG = `claude mcp add iosdeob \\
  ${VENV_PYTHON} \\
  ${SERVER_PY}`;

const GENERIC_CONFIG = `{
  "iosdeob": {
    "command": "${VENV_PYTHON}",
    "args": ["${SERVER_PY}"]
  }
}`;

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1400);
  }
  return (
    <button className="docs-copy-btn" onClick={copy}>
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

function CodeBlock({ text, fileTag }: { text: string; fileTag?: string }) {
  return (
    <div className="docs-code-wrap">
      {fileTag && <span className="file-tag">{fileTag}</span>}
      <pre className="code-block docs-code">{text}</pre>
      <CopyButton text={text} />
    </div>
  );
}

function ToolRow({
  tag,
  name,
  args,
  children,
}: {
  tag: "reads" | "writes" | "compute";
  name: string;
  args: string;
  children: ReactNode;
}) {
  return (
    <div className="docs-tool">
      <div className="docs-tool-sig">
        <span className={`docs-tool-tag ${tag}`}>{tag === "compute" ? "runs r2 + ghidra" : tag}</span>
        <span className="mono">
          {name}
          <span className="docs-tool-args">{args}</span>
        </span>
      </div>
      <div className="docs-tool-desc">{children}</div>
    </div>
  );
}

const SECTIONS = [
  ["architecture", "How it fits together"],
  ["prerequisites", "Prerequisites"],
  ["tools", "Tool reference"],
  ["setup-desktop", "Claude Desktop"],
  ["setup-code", "Claude Code"],
  ["setup-other", "Other MCP clients"],
  ["examples", "Example prompts"],
  ["troubleshooting", "Troubleshooting"],
  ["security", "Scope & security"],
] as const;

export default function McpDocsPage() {
  return (
    <div className="docs-page">
      <nav className="docs-toc">
        <div className="panel-heading">On this page</div>
        {SECTIONS.map(([id, label]) => (
          <a key={id} href={`#docs-${id}`}>
            {label}
          </a>
        ))}
      </nav>

      <div className="docs-content">
        <div className="docs-hero">
          <span className="eyebrow">iOSDeOb · Model Context Protocol</span>
          <h1>Let an AI agent read your decompiled code</h1>
          <p className="docs-lede">
            The iOSDeOb MCP server exposes this stack — file tree, Objective-C classes, and on-demand Ghidra
            decompilation — as eleven tools any MCP-compatible agent can call. Upload an <span className="mono">.ipa</span>,
            then ask it what the app actually does.
          </p>
          <div className="docs-chips">
            <span className="chip-static">11 tools</span>
            <span className="chip-static">stdio transport</span>
            <span className="chip-static">talks to localhost:8080</span>
            <span className="chip-static">no auth · local only</span>
          </div>
        </div>

        <section id="docs-architecture" className="docs-section">
          <h2>How it fits together</h2>
          <p className="muted">
            The MCP server is a plain Python process that runs on your Mac — not inside Docker. Your AI client
            launches it over stdio, and it makes the same HTTP calls to this API that your browser makes right now.
          </p>
          <div className="docs-flow">
            <div className="docs-flow-box">
              <span className="k">Your AI client</span>
              <span className="v">Claude Desktop / Code / Cursor…</span>
            </div>
            <div className="docs-flow-arrow">→</div>
            <div className="docs-flow-box">
              <span className="k">stdio subprocess</span>
              <span className="v accent">mcp-server/server.py</span>
            </div>
            <div className="docs-flow-arrow">→</div>
            <div className="docs-flow-box">
              <span className="k">HTTP · localhost:8080</span>
              <span className="v teal">iOSDeOb API</span>
            </div>
            <div className="docs-flow-arrow">→</div>
            <div className="docs-flow-box">
              <span className="k">Docker Compose stack</span>
              <span className="v">worker · radare2 · Ghidra</span>
            </div>
          </div>
          <p className="muted">
            Nothing about the analysis stack changes to support this — the MCP server is just a new front door onto
            the same REST API this web app already uses.
          </p>
        </section>

        <section id="docs-prerequisites" className="docs-section">
          <h2>Prerequisites</h2>
          <ol className="docs-steps">
            <li>
              <strong>This Docker stack is running.</strong> From the project root:
              <CodeBlock text="docker compose up -d" />
              Confirm it: <span className="mono">curl http://localhost:8080/api/health</span> should return{" "}
              <span className="mono">{`{"status":"ok"}`}</span>.
            </li>
            <li>
              <strong>The MCP server's virtualenv exists.</strong> It's already set up at{" "}
              <span className="mono">mcp-server/.venv</span>. If you ever need to recreate it:
              <CodeBlock text={`cd mcp-server\npython3 -m venv .venv\n.venv/bin/pip install -r requirements.txt`} />
            </li>
          </ol>
          <div className="notice">
            <strong>The two absolute paths</strong> below don't change between clients — they point at this same
            venv and script on this machine.
          </div>
        </section>

        <section id="docs-tools" className="docs-section">
          <h2>Tool reference</h2>
          <p className="muted">
            Every tool addresses a scan by <span className="mono">ipa_id</span> (from{" "}
            <span className="mono">upload_ipa</span> or <span className="mono">list_scans</span>). Search tools are
            paginated — a query always returns a capped, summarized page, never a whole binary's data at once.
          </p>

          <div className="docs-tool-group">
            <div className="tool-group-label">Scans</div>
            <ToolRow tag="writes" name="upload_ipa" args="(file_path, wait=true, timeout_seconds=300)">
              Uploads a local .ipa and blocks until extraction finishes (or fails/times out), returning the scan
              record.
            </ToolRow>
            <ToolRow tag="reads" name="list_scans" args="()">
              Every .ipa previously uploaded, most recent first.
            </ToolRow>
            <ToolRow tag="reads" name="get_scan_info" args="(ipa_id)">
              Status plus the full extraction/disassembly job history.
            </ToolRow>
          </div>

          <div className="docs-tool-group">
            <div className="tool-group-label">Bundle contents</div>
            <ToolRow tag="reads" name="list_files" args="(ipa_id, query?, limit=50)">
              Search the unzipped bundle by filename/path substring — Info.plist, storyboards, embedded frameworks.
            </ToolRow>
            <ToolRow tag="reads" name="read_file" args="(ipa_id, path)">
              Text and plists come back in full; large/binary files as a hex preview + metadata. Image bytes are
              never returned.
            </ToolRow>
            <ToolRow tag="reads" name="get_info_plist" args="(ipa_id)">
              Parsed Info.plist — bundle id, permission usage strings, URL schemes.
            </ToolRow>
            <ToolRow tag="reads" name="get_entitlements" args="(ipa_id)">
              Parsed code-signing entitlements — app groups, keychain access, associated domains.
            </ToolRow>
          </div>

          <div className="docs-tool-group">
            <div className="tool-group-label">Code</div>
            <ToolRow tag="reads" name="list_classes" args="(ipa_id, query?, limit=50)">
              Search Objective-C classes by name — returns a compact summary per class.
            </ToolRow>
            <ToolRow tag="reads" name="get_class" args="(ipa_id, class_name)">
              Full interface: every method (with address), property, ivar offset, and protocol.
            </ToolRow>
            <ToolRow tag="reads" name="list_functions" args="(ipa_id, query?, limit=50)">
              Search named functions — every ObjC method plus symbol-table C symbols.
            </ToolRow>
            <ToolRow tag="compute" name="get_function_detail" args="(ipa_id, address, include_assembly=false)">
              The main event: disassembles and decompiles one function on demand, returning Ghidra's pseudo-C,
              calls made, and direct callers. Cached after the first call.
            </ToolRow>
          </div>
        </section>

        <section id="docs-setup-desktop" className="docs-section">
          <h2>Claude Desktop</h2>
          <div className="docs-client-card">
            <h3>claude_desktop_config.json</h3>
            <ol className="docs-steps">
              <li>
                <strong>Open the config file</strong>
                <div className="file-tag">~/Library/Application Support/Claude/claude_desktop_config.json</div>
              </li>
              <li>
                <strong>Add an mcpServers key</strong> alongside whatever's already there — don't replace existing
                keys:
                <CodeBlock text={DESKTOP_CONFIG} />
              </li>
              <li>
                <strong>Quit Claude Desktop fully</strong> (⌘Q, not just close the window) and reopen it.
              </li>
            </ol>
            <div className="notice">
              <strong>If nothing shows up:</strong> some Desktop builds register MCP servers through a Settings →
              Connectors UI instead of reading this file directly. If restarting doesn't surface an "iosdeob"
              connector, look there and paste the same command + args.
            </div>
          </div>
        </section>

        <section id="docs-setup-code" className="docs-section">
          <h2>Claude Code</h2>
          <div className="docs-client-card">
            <h3>Project-level .mcp.json</h3>
            <p className="muted">Create this file at the root of a project, or merge the key into an existing one:</p>
            <CodeBlock text={CODE_CONFIG} fileTag=".mcp.json" />
          </div>
          <div className="docs-client-card">
            <h3>Or via the CLI</h3>
            <p className="muted">Equivalent, without hand-editing JSON:</p>
            <CodeBlock text={CLI_CONFIG} />
            <p className="muted">
              Run <span className="mono">claude mcp list</span> afterward to confirm it registered, and restart the
              session so the tools load.
            </p>
          </div>
        </section>

        <section id="docs-setup-other" className="docs-section">
          <h2>Other MCP clients</h2>
          <p className="muted">
            MCP is an open standard — Cursor, Windsurf, Zed, and others all speak it, and almost every one uses the
            same <span className="mono">command</span> + <span className="mono">args</span> shape, just in their own
            settings file. Check that client's MCP/tools settings for the file path, then paste in:
          </p>
          <CodeBlock text={GENERIC_CONFIG} />
          <p className="muted">
            Some clients want just the inner object (no <span className="mono">mcpServers</span> wrapper) under a
            server name you choose — the <span className="mono">command</span>/<span className="mono">args</span>{" "}
            pair is what actually matters.
          </p>
        </section>

        <section id="docs-examples" className="docs-section">
          <h2>Example prompts</h2>
          <p className="muted">
            Once connected, plain language is enough — the tool descriptions tell the model when to reach for each
            one.
          </p>
          <div className="docs-prompt-list">
            <div className="docs-prompt">
              Upload ~/Downloads/MyApp.ipa to iosdeob and tell me what permissions it requests and why.
            </div>
            <div className="docs-prompt">
              List classes matching "Login" in that scan, then decompile whatever handles the submit button.
            </div>
            <div className="docs-prompt">
              Check get_entitlements — does this app declare any associated domains or iCloud containers?
            </div>
            <div className="docs-prompt">
              Search functions for "Biometric" and summarize how Face ID login is wired up.
            </div>
          </div>
        </section>

        <section id="docs-troubleshooting" className="docs-section">
          <h2>Troubleshooting</h2>
          <div className="docs-qa">
            <div className="docs-q">The client starts but no "iosdeob" tools appear</div>
            <div className="docs-a">
              Fully quit and reopen the client — most MCP clients only read config at launch. Then confirm the JSON
              is valid (a trailing comma is the usual culprit) and that both absolute paths exist on disk.
            </div>
          </div>
          <div className="docs-qa">
            <div className="docs-q">Every tool call fails immediately</div>
            <div className="docs-a">
              The Docker stack probably isn't running. Check <span className="mono">curl http://localhost:8080/api/health</span> —
              if that doesn't return <span className="mono">ok</span>, run <span className="mono">docker compose up -d</span> from
              the project root first.
            </div>
          </div>
          <div className="docs-qa">
            <div className="docs-q">upload_ipa times out on a large file</div>
            <div className="docs-a">
              Pass a longer <span className="mono">timeout_seconds</span>, or call it with{" "}
              <span className="mono">wait=false</span> and poll <span className="mono">get_scan_info</span> until
              status is "ready".
            </div>
          </div>
          <div className="docs-qa">
            <div className="docs-q">get_function_detail's decompiled_code is empty</div>
            <div className="docs-a">
              Check <span className="mono">decompile_error</span> in the same response. The most common cause is an
              arm64e-only binary — pointer authentication on that slice isn't decoded, so decompilation for
              functions in it can come back empty even though disassembly still works.
            </div>
          </div>
        </section>

        <section id="docs-security" className="docs-section">
          <h2>Scope &amp; security</h2>
          <p className="muted">
            The server only ever calls the API on <span className="mono">localhost</span> — nothing leaves your
            machine. It performs static analysis exclusively; the uploaded binary is never executed. By design
            there's no delete tool exposed here, so an agent can add and read scans but can't remove your existing
            analysis data.
          </p>
        </section>
      </div>
    </div>
  );
}
