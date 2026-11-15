#!/usr/bin/env python3
"""
Folding engine for Antigravity (context-saver plugin):
  --ipynb <path> [--cells 0-10] : Strips base64 images, HTML tables, and middle tracebacks from Notebooks
  --md <path>                   : Generates a Heading Map with exact StartLine..EndLine ranges for long notes
  --json <path>                 : Prints JSON schema + first 3 and last 1 array items
  --cmd "<shell command>"       : Runs command, folds 3rd-party Python tracebacks & passing tests, archives raw log
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time

ARCHIVE_DIR = "/tmp/agy-context-archive"
MAX_DIRECT_CHARS = 3000

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")

# Matches third-party / internal Python frames that clutter tracebacks
noisy_frame_patterns = (
    r"(/site-packages/|/dist-packages/|/lib/python\d+\.\d+/|"
    r"/anaconda3?/|/miniconda3?/|/\.venv/|/venv/|/virtualenv/|"
    r"/ipykernel/|/IPython/|/_pytest/|/pluggy/|/tornado/|/traitlets/)"
)
LIB_FRAME_RE = re.compile(noisy_frame_patterns)

PASS_LINE_RE = re.compile(
    r"^\s*(PASS|✓|✔|ok\s+\d+|test\s+.*\.\.\.\s+ok|PASSED)\b", re.IGNORECASE
)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


def archive_output(raw_text: str, prefix: str = "run") -> str:
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    short_hash = hashlib.sha1(raw_text.encode("utf-8", errors="ignore")).hexdigest()[:8]
    path = os.path.join(ARCHIVE_DIR, f"{prefix}-{int(time.time())}-{short_hash}.log")
    with open(path, "w", encoding="utf-8", errors="replace") as f:
        f.write(raw_text)
    return path


def truncate_python_traceback(lines: list[str]) -> list[str]:
    """
    Compresses a Python traceback list by keeping:
    - The 'Traceback (most recent call last):' header
    - The very first frame
    - Any frame belonging to the user's workspace (not in site-packages/venv/stdlib)
    - The final 2 frames + the final Exception / Error message lines
    """
    cleaned = [strip_ansi(line.rstrip()) for line in lines if line.strip()]
    if len(cleaned) <= 10:
        return cleaned

    # Split into frame blocks vs non-frame lines
    out = []
    skipped_lib_frames = 0
    i = 0
    n = len(cleaned)

    while i < n:
        line = cleaned[i]
        # Detect standard Python frame: '  File "...", line X, in ...' or IPython frame '---> X'
        is_file_frame = line.lstrip().startswith('File "')
        if is_file_frame:
            # Grab the File line + the following code snippet line(s)
            frame_block = [line]
            while i + 1 < n and not cleaned[i + 1].lstrip().startswith('File "') and not re.match(r"^[A-Za-z0-9_.]*(Error|Exception|Warning|Interrupt):", cleaned[i + 1]):
                i += 1
                frame_block.append(cleaned[i])

            is_near_end = (n - i) <= 4
            is_first_frame = len(out) <= 1

            if LIB_FRAME_RE.search(line) and not is_first_frame and not is_near_end:
                skipped_lib_frames += 1
            else:
                if skipped_lib_frames > 0:
                    out.append(f"  ... [{skipped_lib_frames} internal library/site-packages frames folded] ...")
                    skipped_lib_frames = 0
                out.extend(frame_block)
        else:
            if skipped_lib_frames > 0:
                out.append(f"  ... [{skipped_lib_frames} internal library/site-packages frames folded] ...")
                skipped_lib_frames = 0
            out.append(line)
        i += 1

    # Final safety cap if an IPython/rich traceback didn't use standard 'File "..."' formatting
    if len(out) > 16:
        folded_count = len(out) - 9
        out = out[:3] + [f"  ... [{folded_count} middle traceback lines folded] ..."] + out[-6:]

    return out


# ---------------------------------------------------------------------------
# 1. JUPYTER NOTEBOOK (.ipynb) FOLDER
# ---------------------------------------------------------------------------
def fold_ipynb_file(file_path: str, cell_range: str = None) -> int:
    if not os.path.isfile(file_path):
        print(f"Error: File not found: {file_path}", file=sys.stderr)
        return 1

    raw_kb = os.path.getsize(file_path) / 1024.0
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        try:
            nb = json.load(f)
        except json.JSONDecodeError as e:
            print(f"Error parsing .ipynb JSON: {e}", file=sys.stderr)
            return 1

    cells = nb.get("cells", [])
    total_cells = len(cells)

    start_idx, end_idx = 0, total_cells
    if cell_range and "-" in cell_range:
        parts = cell_range.split("-", 1)
        start_idx = max(0, int(parts[0]))
        end_idx = min(total_cells, int(parts[1]) + 1)

    stripped_blobs = 0
    print(f"=== [Context Saver: {os.path.basename(file_path)} ({raw_kb:.1f} KB raw -> Clean View, Cells {start_idx}..{end_idx - 1} of {total_cells})] ===\n")

    for i in range(start_idx, end_idx):
        cell = cells[i]
        cell_type = cell.get("cell_type", "unknown")
        raw_source = cell.get("source", [])
        source = "".join(raw_source) if isinstance(raw_source, list) else str(raw_source)
        exec_count = cell.get("execution_count")

        count_tag = f" In[{exec_count}]" if exec_count is not None else ""
        print(f"--- Cell [{i}] ({cell_type.upper()}{count_tag}) ---")

        source_lines = source.strip().splitlines()
        if not source_lines:
            print("<empty cell>")
        elif len(source_lines) > 60 and cell_range is None:
            # If viewing the whole notebook, cap gigantic cells to 60 lines
            print("\n".join(source_lines[:45]))
            print(f"# ... [{len(source_lines) - 55} lines folded; pass --cells {i}-{i} to view full cell] ...")
            print("\n".join(source_lines[-10:]))
        else:
            print(source.strip())

        # Process cell outputs (strip base64 images, HTML tables, and fold tracebacks)
        for out in cell.get("outputs", []):
            out_type = out.get("output_type", "")
            data = out.get("data", {})

            # Strip heavy MIME payloads
            heavy_mimes = [m for m in ("image/png", "image/jpeg", "image/svg+xml", "text/html", "application/javascript", "application/vnd.plotly.v1+json") if m in data]
            if heavy_mimes:
                stripped_blobs += len(heavy_mimes)
                print(f"  [Output stripped: {', '.join(heavy_mimes)}]")

            # Keep concise text/plain representation if present alongside HTML/image
            if "text/plain" in data:
                plain = data["text/plain"]
                plain_lines = ("".join(plain) if isinstance(plain, list) else str(plain)).splitlines()
                if len(plain_lines) > 12:
                    plain_lines = plain_lines[:6] + [f"  ... ({len(plain_lines) - 9} lines folded) ..."] + plain_lines[-3:]
                print("  [Result]: " + "\n    ".join(plain_lines))

            # Handle stdout/stderr stream outputs
            if out_type == "stream":
                text = out.get("text", [])
                stream_lines = ("".join(text) if isinstance(text, list) else str(text)).splitlines()
                if len(stream_lines) > 12:
                    stream_lines = stream_lines[:5] + [f"  ... ({len(stream_lines) - 10} stream lines folded) ..."] + stream_lines[-5:]
                if stream_lines:
                    print(f"  [Stream ({out.get('name', 'stdout')})]:\n    " + "\n    ".join(stream_lines))

            # Handle Python Error Tracebacks inside cells
            if out_type == "error" or "traceback" in out:
                tb_raw = out.get("traceback", [])
                tb_lines = []
                for item in tb_raw:
                    tb_lines.extend(item.splitlines())
                folded_tb = truncate_python_traceback(tb_lines)
                ename = out.get("ename", "Error")
                evalue = out.get("evalue", "")
                print(f"  [Cell Exception: {ename}: {evalue}]")
                for tl in folded_tb:
                    print(f"    {tl}")
        print()

    if stripped_blobs:
        print(f"[Summary: Stripped {stripped_blobs} base64/HTML/widget blobs from notebook output.]")
    return 0


# ---------------------------------------------------------------------------
# 2. MARKDOWN / SYSTEM DESIGN NOTE OUTLINER
# ---------------------------------------------------------------------------
def fold_markdown_file(file_path: str) -> int:
    if not os.path.isfile(file_path):
        print(f"Error: File not found: {file_path}", file=sys.stderr)
        return 1

    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    total_lines = len(lines)
    size_kb = os.path.getsize(file_path) / 1024.0

    headings = []
    for idx, line in enumerate(lines, start=1):
        m = HEADING_RE.match(line.strip())
        if m:
            headings.append((idx, len(m.group(1)), m.group(2).strip()))

    print(f"=== [Context Saver: Document Outline for {os.path.basename(file_path)} ({size_kb:.1f} KB, {total_lines} lines)] ===")
    print("Use view_file with StartLine and EndLine on the specific sections you need:\n")

    preview = [f"L{i+1}: {lines[i].rstrip()}" for i in range(min(15, total_lines)) if lines[i].strip()]
    if preview:
        print("--- Preamble (Lines 1-15) ---")
        print("\n".join(preview[:10]))
        print()

    if headings:
        print("--- Section Map (Line Ranges) ---")
        for i, (start_line, level, title) in enumerate(headings):
            end_line = headings[i + 1][0] - 1 if i + 1 < len(headings) else total_lines
            indent = "  " * (level - 1)
            print(f"{indent}- [Lines {start_line}..{end_line}] ({end_line - start_line + 1} lines) {'#' * level} {title}")
    else:
        print("No Markdown headings found. Use grep_search or read in 150-line chunks via view_file(StartLine, EndLine).")
    return 0


# ---------------------------------------------------------------------------
# 3. SHELL COMMAND & PYTHON TRACEBACK FOLDER
# ---------------------------------------------------------------------------
def fold_command_output(cmd: str) -> int:
    proc = subprocess.run(
        cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace"
    )
    raw = proc.stdout or ""

    if len(raw) <= MAX_DIRECT_CHARS and "Traceback (most recent call last)" not in raw:
        sys.stdout.write(raw)
        return proc.returncode

    archive_path = archive_output(raw, prefix="cmd")
    lines = [strip_ansi(l) for l in raw.splitlines()]
    total_lines = len(lines)

    # Fold Python Tracebacks in command output
    output_lines = []
    passing_count = 0
    folded_lib_frames = 0

    i = 0
    while i < total_lines:
        line = lines[i]

        # Collapse passing test lines
        if PASS_LINE_RE.search(line):
            passing_count += 1
            i += 1
            continue

        # Detect start of a Python traceback block
        if "Traceback (most recent call last):" in line:
            tb_block = [line]
            i += 1
            while i < total_lines:
                tb_block.append(lines[i])
                # End of traceback is typically the Exception: message line
                if re.match(r"^[A-Za-z0-9_.]*(Error|Exception|Warning|Interrupt|Exit)(\b|:)", lines[i].strip()):
                    i += 1
                    break
                i += 1
            folded_tb = truncate_python_traceback(tb_block)
            folded_lib_frames += max(0, len(tb_block) - len(folded_tb))
            output_lines.extend(folded_tb)
            continue

        output_lines.append(line)
        i += 1

    raw_kb = len(raw.encode("utf-8", errors="ignore")) / 1024.0
    print(f"=== [Context Saver: Folded Command Output ({raw_kb:.1f} KB / {total_lines} lines)] ===")
    print(f"Exit Code       : {proc.returncode}")
    print(f"Full Log Archive: {archive_path}")
    if passing_count or folded_lib_frames:
        print(f"Folded Noise    : {passing_count} passing tests, {folded_lib_frames} library traceback lines\n")

    if len(output_lines) > 90:
        print("--- First 25 Lines ---")
        print("\n".join(output_lines[:25]))
        print(f"\n... [{len(output_lines) - 70} middle lines archived in {archive_path}] ...\n")
        print("--- Final 45 Lines (Errors & Summary) ---")
        print("\n".join(output_lines[-45:]))
    else:
        print("\n".join(output_lines))

    return proc.returncode


# ---------------------------------------------------------------------------
# 4. LARGE JSON SCHEMA & SAMPLE FOLDER
# ---------------------------------------------------------------------------
def fold_json_structure(obj, max_array_items=3, depth=0, max_depth=6):
    if depth > max_depth:
        return "<max_depth_reached>"
    if isinstance(obj, dict):
        return {k: fold_json_structure(v, max_array_items, depth + 1, max_depth) for k, v in obj.items()}
    if isinstance(obj, list):
        n = len(obj)
        if n <= max_array_items + 1:
            return [fold_json_structure(x, max_array_items, depth + 1, max_depth) for x in obj]
        head = [fold_json_structure(x, max_array_items, depth + 1, max_depth) for x in obj[:max_array_items]]
        tail = fold_json_structure(obj[-1], max_array_items, depth + 1, max_depth)
        return head + [f"... ({n - (max_array_items + 1)} more items folded, total={n}) ...", tail]
    if isinstance(obj, str) and len(obj) > 250:
        return obj[:250] + f"... ({len(obj)} chars)"
    return obj


def fold_json_file(file_path: str) -> int:
    if not os.path.isfile(file_path):
        print(f"Error: File not found: {file_path}", file=sys.stderr)
        return 1
    size_kb = os.path.getsize(file_path) / 1024.0
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        data = json.load(f)
    print(f"=== [Context Saver: JSON Schema & Sample ({size_kb:.1f} KB original)] ===")
    print(json.dumps(fold_json_structure(data), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Antigravity Context Saver folding utility.")
    parser.add_argument("--ipynb", help="Path to Jupyter Notebook (.ipynb) to strip base64/HTML and fold tracebacks")
    parser.add_argument("--cells", help="Optional cell range for --ipynb, e.g. 0-5 or 12-12", default=None)
    parser.add_argument("--md", help="Path to Markdown/note file to extract Heading & Line-Range Map")
    parser.add_argument("--json", help="Path to large JSON file to extract schema & sample items")
    parser.add_argument("--cmd", help="Shell command to execute with traceback & test folding")
    args = parser.parse_args()

    if args.ipynb:
        sys.exit(fold_ipynb_file(args.ipynb, args.cells))
    elif args.md:
        sys.exit(fold_markdown_file(args.md))
    elif args.json:
        sys.exit(fold_json_file(args.json))
    elif args.cmd:
        sys.exit(fold_command_output(args.cmd))
    else:
        parser.print_help()
        sys.exit(1)
