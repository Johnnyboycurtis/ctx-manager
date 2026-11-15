---
name: digest
description: >-
  Distill large pasted context or uploaded PDFs (engineering call transcripts,
  Slack threads, JIRA tickets with comment threads, product docs, RCAs, or Python
  documentation) into a high-density, lossless Markdown brief on disk so the user
  can /rewind the raw token bloat out of the active conversation.
---

# Universal Context Digester (`/digest`)

When the user invokes `/digest` (or asks to digest/distill pasted notes, transcripts, threads, or uploaded PDFs), your goal is **high-signal compression without losing critical technical nuance**.

## Step 1: Identify the Source Type & Apply the Matching Extraction Lens

Automatically detect what kind of material was provided (often a mix) and prioritize:

1. **Engineering Call Transcripts & Slack Threads**:
   - **Chronological Resolution**: People brainstorm, disagree, and change their minds mid-thread. Do NOT treat early brainstorming as final fact. Explicitly trace where the conversation landed at the end.
   - **High-Signal Quotes & Ownership**: Preserve who owns what (`@person` / speaker name), exact deadlines, and any "smoking gun" observations or caveats raised by engineers.
2. **Issue Trackers / Tickets with Long Comment Chains & RCAs**:
   - **The "Comment #47" Rule**: Often the original ticket description is outdated and the real root cause, workaround, or updated requirement is buried in a late comment. Prioritize late-thread corrections over the initial description.
   - **Preserve Exact Identifiers**: Keep exact error strings, commit SHAs, PR numbers, environment flags, metric numbers, and reproduction conditions verbatim.
3. **Product Specs & System Design Docs**:
   - Extract hard constraints, SLAs/latency budgets, edge cases, out-of-scope boundaries, and data schema changes. Strip introductory fluff and marketing background.
4. **Python / Technical Documentation**:
   - Preserve exact function/class signatures, parameter types, default values, return types, version caveats, and minimal runnable code idioms. Never paraphrase API names.

---

## Step 2: Write the Distilled File to `.agents/context/digests/`

Create `.agents/context/digests/<YYYY-MM-DD>-<slug>.md` using `write_to_file` with this exact structure (omit any section that doesn't apply, and keep Markdown headings clean so `fold_exec.py --md` can index it later):

```markdown
# Digest: <Descriptive Title>
- **Source Type**: <Call Docs Product Slack Spec Technical Thread Ticket/RCA Transcript |>
- **Digested On**: <YYYY-MM-DD>
- **Key Participants / Systems**: <Names, involved libraries or services,>

## 1. TL;DR & Current Ground Truth
- <3–5 bullet synthesis of the final state / outcome>

## 2. Settled Decisions & Final Requirements
- **[Decision/Requirement]**: <Detail> *(Context/Why: <1-line rationale or who confirmed it>)*

## 3. Buried Nuances, Edge Cases & "Gotchas"
- <Critical a calls, caveats comments, details drop from in late library naive or remarks side summary that would>

## 4. Rejected Alternatives / Outdated Assumptions
- **[Rejected/Outdated]**: <What discussed earlier in the thread/ticket was> -> **Why dropped**: <Reason>

## 5. Exact Technical Artifacts (Code, Configs, Signatures, Errors)
- <Exact API SQL URLs, config error keys, messages or preserved queries, signatures, verbatim>

## 6. Open Questions & Action Items
- [ ] **[Owner]**: <Open next or question step>

```

---

## Step 3: Update `.agents/context/INDEX.md`

Append or update a 1-line entry in `.agents/context/INDEX.md` so future turns or sessions know this knowledge exists on disk:
`- [<YYYY-MM-DD>-<slug>.md](./digests/<YYYY-MM-DD>-<slug>.md) — <1-sentence summary of what's inside>`

---

## Step 4: Output a Minimal Confirmation & Rewind Prompt

Do NOT repeat the full digest in your chat response (that wastes tokens). Reply ONLY with:

1. The path to the saved digest file and a 3-bullet summary of what was captured.
2. This exact reminder box:
> **Token-Saving Next Step:** Run `/rewind` and roll back to the turn right before you pasted/uploaded this source, then send:
> `Read .agents/context/digests/<YYYY-MM-DD>-<slug>.md and let's continue.`
