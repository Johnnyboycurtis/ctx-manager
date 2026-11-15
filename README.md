# Antigravity Context Saver Plugin (`context-saver`)

A zero-dependency, local plugin for **Google Antigravity** designed to prevent context window saturation and avoid premature conversation compaction during intensive engineering workflows.

---

## 1. The Problem

Google Antigravity automatically compacts conversation history once the context window reaches ~135k–150k tokens. While compaction preserves a high-level summary, it inevitably flattens subtle edge cases, architectural decisions, and verbatim code signatures.

Engineering workflows frequently encounter three major token drains:
1. **Jupyter Notebooks (`.ipynb`)**: Raw notebook JSON files contain massive base64-encoded images (`image/png`), HTML table dumps (`text/html`), and lengthy execution outputs that consume 40k–80k tokens in a single file view.
2. **Python Tracebacks & Test Runs**: Unfiltered `pytest` or `python` crashes dump dozens of noisy middle stack frames from `site-packages`, `venv`, or virtual environments, obscuring the root error and wasting context.
3. **Long Notes, Transcripts & PDFs**: Engineering call transcripts, Slack threads, RCAs, JIRA tickets with dozens of comments, and extensive API documentation quickly burn token budget when loaded into active chat context.

---

## 2. Key Features

- **Proactive Tool Gating (`PreToolUse` Hook)**: Intercepts `view_file` and `run_command` calls *before* they execute or enter the model's context window.
- **Jupyter Notebook Sanitization (`--ipynb`)**: Strips base64 image payloads, HTML tables, widget metadata, and verbose cell tracebacks while keeping clean code and Markdown cells.
- **Traceback Folding & Log Archiving (`--cmd`)**: Wraps test and Python executions, archiving full raw output to `/tmp/agy-context-archive/` while folding middle library frames and collapsing passing test outputs in chat.
- **Markdown Outline & Range Mapping (`--md`)**: Converts un-ranged reads on large `.md`, `.txt`, and `.rst` files (>15 KB) into a structured Heading & Line-Range Map so the agent only reads relevant sections.
- **JSON Schema & Array Sampling (`--json`)**: Prevents massive raw JSON reads (>20 KB) by extracting schemas and sampling head/tail elements.
- **Universal Context Digester (`/digest`)**: Distills raw transcripts, Slack threads, tickets, and PDFs into `.agents/context/digests/`, records entries in `.agents/context/INDEX.md`, and provides an immediate `/rewind` prompt to drop raw input tokens.

---

## 3. Plugin Architecture

```text
context-saver/
├── plugin.json              # Antigravity plugin manifest
├── hooks.json               # PreToolUse hook configuration
├── rules/
│   └── AGENTS.md            # Standing workspace instructions for token hygiene
├── skills/
│   └── digest/
│       └── SKILL.md         # /digest skill definition and prompt templates
└── scripts/
    ├── pre_tool_gate.py     # Stdin/stdout hook interceptor and argument rewriter
    └── fold_exec.py         # Standalone folding and log truncation engine
```

### File Breakdown

| File | Purpose |
| :--- | :--- |
| `plugin.json` | Registers the plugin name, version, and schema with Antigravity. |
| `hooks.json` | Configures a `PreToolUse` hook matching `run_command\|view_file` that routes tool calls to `pre_tool_gate.py`. |
| `scripts/pre_tool_gate.py` | Reads tool call payloads from `stdin` and emits `{"decision": "allow"\|"deny", ...}`. Denies bloated `.ipynb`/`.md` reads and rewrites command lines. |
| `scripts/fold_exec.py` | CLI utility implementing `--ipynb`, `--md`, `--json`, and `--cmd` folding logic. |
| `skills/digest/SKILL.md` | Skill providing the `/digest` slash command to distill pasted threads and PDFs onto disk. |
| `rules/AGENTS.md` | Rules injected into agent sessions directing the agent to use folded tools and check `.agents/context/INDEX.md`. |

---

## 4. Lifecycle Hook Behavior (`pre_tool_gate.py`)

When the agent attempts an action, `pre_tool_gate.py` evaluates the tool call against the following rules:

| Tool Call | Condition | Decision | Result / Overwrite |
| :--- | :--- | :--- | :--- |
| `view_file` | `.ipynb` file > 4 KB | `deny` | Directs agent to run `python3 scripts/fold_exec.py --ipynb <path>`. |
| `view_file` | Un-ranged read on `.md`/`.txt`/`.rst` > 15 KB | `deny` | Directs agent to run `python3 scripts/fold_exec.py --md <path>` to view section line ranges first. |
| `view_file` | Un-ranged read on `.json` > 20 KB | `deny` | Directs agent to run `python3 scripts/fold_exec.py --json <path>`. |
| `view_file` | Any other un-ranged read > 20 KB | `allow` | Overwrites arguments to clamp read to lines `1..200`. |
| `run_command` | Matches noisy test/python commands (`pytest`, `python3`, `npm test`, `cargo test`, etc.) | `allow` | Overwrites `CommandLine` to wrap execution in `python3 scripts/fold_exec.py --cmd "<cmd>"`. |

---

## 5. CLI Folding Engine (`fold_exec.py`)

The standalone engine can also be executed manually or in scripts:

### Inspect Jupyter Notebooks
```bash
# Clean view of all cells with images/HTML stripped:
python3 scripts/fold_exec.py --ipynb path/to/notebook.ipynb

# View a specific cell or range (e.g., cell 4):
python3 scripts/fold_exec.py --ipynb path/to/notebook.ipynb --cells 4-4
```

### Map Markdown & Notes
```bash
python3 scripts/fold_exec.py --md path/to/design_spec.md
```

### Inspect Large JSON Schemas
```bash
python3 scripts/fold_exec.py --json path/to/dataset.json
```

### Run Commands with Traceback & Log Folding
```bash
python3 scripts/fold_exec.py --cmd "pytest tests/"
```
- Passes raw full log to `/tmp/agy-context-archive/cmd-<timestamp>-<hash>.log`.
- Collapses passing unit test lines (`PASS`, `PASSED`, `ok`).
- Folds middle library frames (`site-packages`, `.venv`, `anaconda`) while keeping project frames and the final exception message.

---

## 6. Installation & Verification

### Option A: Global Installation (Machine-Wide)
Copy the plugin to your global Antigravity configuration directory:
```bash
mkdir -p ~/.gemini/config/plugins/context-saver
cp -r context-saver/* ~/.gemini/config/plugins/context-saver/
chmod 0755 ~/.gemini/config/plugins/context-saver/scripts/*.py
```

### Option B: Workspace Installation (Project-Scoped)
Place the plugin in your project's `.agents` root:
```bash
mkdir -p .agents/plugins/context-saver
cp -r context-saver/* .agents/plugins/context-saver/
chmod 0755 .agents/plugins/context-saver/scripts/*.py
```

### Verifying Installation via Language Server
Verify that Antigravity discovers and enables the plugin:
```bash
cat > /tmp/lsrpc.sh <<'EOF'
: "${ANTIGRAVITY_LS_ADDRESS:=localhost:5387}"
lsrpc() {
  curl -sS -X POST \
    "http://${ANTIGRAVITY_LS_ADDRESS}/exa.language_server_pb.LanguageServerService/$1" \
    -H "Content-Type: application/json" \
    -H "x-codeium-csrf-token: ${ANTIGRAVITY_CSRF_TOKEN}" \
    -d "$2"
}
EOF
source /tmp/lsrpc.sh && lsrpc GetAllPlugins '{"workspaceUris":["file://'"$(pwd)"'"]}' | jq '[.plugins[] | select(.name=="context-saver") | {name, dir, disabled, isGlobal, skills: [.skills[]?.name], hooks: ((.hooksJson // "") | length > 0)}]'
```

Expected output:
```json
[
  {
    "name": "context-saver",
    "dir": "context-saver",
    "disabled": false,
    "isGlobal": true,
    "skills": ["digest"],
    "hooks": true
  }
]
```

---

## 7. The `/digest` Workflow

When dropping large conversation transcripts, Slack threads, or 30-page PDF tickets into chat:

1. **Trigger the Skill**:
   ```text
   /digest auth-migration-decision
   ```
2. **Automated Distillation**:
   Antigravity extracts settled decisions, high-signal quotes, exact error signatures, and rejected alternatives into:
   ```text
   .agents/context/digests/<YYYY-MM-DD>-auth-migration-decision.md
   ```
   and registers the entry in `.agents/context/INDEX.md`.
3. **Execute `/rewind`**:
   Use the `/rewind` slash command to roll back to the turn before pasting the raw document, then resume with:
   ```text
   Read .agents/context/digests/<YYYY-MM-DD>-auth-migration-decision.md and let's continue.
   ```
   This reduces the active context footprint from ~50,000+ tokens back to ~1,500 tokens without losing technical nuance.
