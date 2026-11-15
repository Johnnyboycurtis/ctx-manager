# Context Saver & Knowledge Hygiene Rules

Always optimize for minimal token consumption while preserving 100% of technical nuance:

1. **Check Local Context Digests First (`.agents/context/INDEX.md`)**:
   - If `.agents/context/INDEX.md` exists in the workspace, check it at the start of design, debugging, or planning tasks to see what digested call transcripts, specs, RCAs, or docs are already stored on disk.

2. **Jupyter Notebooks (`.ipynb`)**:
   - NEVER call `view_file` directly on `.ipynb` files (raw JSON contains massive base64 image blobs and HTML tables).
   - Always inspect notebooks via:
     `python3 "$PLUGIN_ROOT/scripts/fold_exec.py" --ipynb <path>`
   - To inspect a single large cell in full, pass `--cells <start>-<end>` (e.g., `--cells 4-4`).

3. **Long Notes, Design Docs, Transcripts & RCAs (`.md`, `.txt`)**:
   - For documentation or note files larger than 15 KB, do NOT read the entire file at once.
   - First extract the Heading & Line-Range Map:
     `python3 "$PLUGIN_ROOT/scripts/fold_exec.py" --md <path>`
   - Then call `view_file` with explicit `StartLine` and `EndLine` for only the sections relevant to the current question.

4. **Python Tracebacks & Test Runs**:
   - `python`, `pytest`, and test runner commands are automatically wrapped by `fold_exec.py --cmd`, which folds internal `site-packages` frames and archives the full output to `/tmp/agy-context-archive/`.
   - If you need to inspect folded library frames from a crash, read the specific lines from the `/tmp/agy-context-archive/cmd-*.log` path printed in the output rather than re-running with `AGY_NO_FOLD=1`.

5. **Proactively Offer `/digest` on Huge Pastes or PDFs**:
   - If the user pastes a long call transcript, Slack thread, ticket dump, or uploads a large PDF directly into chat, answer their immediate question concisely and offer to save a structured digest to `.agents/context/digests/` so they can `/rewind` the raw paste out of the active context window.
