#!/usr/bin/env python3
"""
PreToolUse gate for Antigravity (context-saver plugin).
Intercepts view_file and run_command to prevent .ipynb base64 bloat,
long Python tracebacks, large JSON dumps, and un-ranged Markdown/note reads.
"""
import json
import os
import re
import shlex
import sys

MAX_RAW_FILE_BYTES = 20 * 1024   # 20 KB threshold for un-ranged code/json files
MAX_MD_FILE_BYTES = 15 * 1024    # 15 KB threshold for un-ranged Markdown/design notes
MAX_IPYNB_RAW_BYTES = 4 * 1024   # Intercept almost all .ipynb files to strip base64/HTML
DEFAULT_CLAMP_LINES = 200

# Commands that produce Python tracebacks, notebook outputs, or noisy test logs
NOISY_CMD_PATTERNS = re.compile(
    r"^\s*("
    r"python3?\s+|uv\s+run\s+|poetry\s+run\s+|pipenv\s+run\s+|conda\s+run\s+|"
    r"pytest|py\.test|jupyter\s+(nbconvert|execute)|papermill|"
    r"npm\s+test|pnpm\s+test|yarn\s+test|bun\s+test|npx\s+(jest|vitest|playwright)|"
    r"cargo\s+(test|build|check)|go\s+test"
    r")\b"
)


def allow(reason="", overwrite=None):
    out = {"decision": "allow"}
    if reason:
        out["reason"] = reason
    if overwrite:
        out["overwrite"] = overwrite
    print(json.dumps(out))
    sys.exit(0)


def deny(reason):
    print(json.dumps({"decision": "deny", "reason": reason}))
    sys.exit(0)


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        allow()

    tool_call = payload.get("toolCall") or {}
    tool_name = tool_call.get("name", "")
    args = tool_call.get("args") or {}

    plugin_root = os.environ.get(
        "PLUGIN_ROOT",
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
    )
    fold_script = os.path.join(plugin_root, "scripts", "fold_exec.py")

    # 1. Intercept view_file
    if tool_name == "view_file":
        file_path = args.get("AbsolutePath") or ""
        start_line = args.get("StartLine")
        end_line = args.get("EndLine")

        if not file_path or not os.path.isfile(file_path):
            allow()

        try:
            size = os.path.getsize(file_path)
        except OSError:
            size = 0

        kb = max(1, size // 1024)
        lower_path = file_path.lower()

        # A. Always intercept .ipynb reads over 4 KB (even if ranged, raw JSON lines split base64 blobs)
        if lower_path.endswith(".ipynb") and size > MAX_IPYNB_RAW_BYTES:
            deny(
                f"Jupyter Notebook is {kb} KB of raw JSON/base64. Do NOT use view_file on .ipynb files. "
                f"Run this command instead to read clean cells with base64/HTML and long tracebacks stripped:\n"
                f"python3 {shlex.quote(fold_script)} --ipynb {shlex.quote(file_path)}"
            )

        # B. Gate un-ranged reads on large Markdown / Design Notes / RCAs
        if start_line is None and end_line is None:
            if lower_path.endswith((".md", ".mdx", ".txt", ".rst")) and size > MAX_MD_FILE_BYTES:
                deny(
                    f"Note/Markdown file is {kb} KB. To avoid loading the entire document into context, "
                    f"first inspect its Heading & Line-Range Table of Contents by running:\n"
                    f"python3 {shlex.quote(fold_script)} --md {shlex.quote(file_path)}\n"
                    f"Then call view_file with explicit StartLine and EndLine for the sections you need."
                )

            # C. Gate un-ranged reads on large JSON files
            if lower_path.endswith(".json") and size > MAX_RAW_FILE_BYTES:
                deny(
                    f"JSON file is {kb} KB. Run this command to inspect its schema and sample items first:\n"
                    f"python3 {shlex.quote(fold_script)} --json {shlex.quote(file_path)}"
                )

            # D. Clamp any other large un-ranged file read to lines 1..200
            if size > MAX_RAW_FILE_BYTES:
                allow(
                    reason=f"File is {kb} KB; clamped view_file to lines 1-{DEFAULT_CLAMP_LINES}. Use grep_search or StartLine/EndLine for more.",
                    overwrite={"StartLine": 1, "EndLine": DEFAULT_CLAMP_LINES},
                )

    # 2. Intercept run_command for Python scripts, pytest, and notebook execution
    elif tool_name == "run_command":
        cmd = args.get("CommandLine") or ""
        if "fold_exec.py" in cmd or "AGY_NO_FOLD=1" in cmd:
            allow()

        # Skip interactive/server commands that shouldn't be wrapped
        if re.search(r"\b(jupyter\s+(lab|notebook)|uvicorn|gunicorn|flask\s+run|manage\.py\s+runserver)\b", cmd):
            allow()

        if NOISY_CMD_PATTERNS.search(cmd):
            wrapped_cmd = f"python3 {shlex.quote(fold_script)} --cmd {shlex.quote(cmd)}"
            allow(
                reason="Wrapped command in Context Saver (truncates library tracebacks and archives full output).",
                overwrite={"CommandLine": wrapped_cmd},
            )

    allow()


if __name__ == "__main__":
    main()
