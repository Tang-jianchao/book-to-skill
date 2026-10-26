---
name: book-to-skill
description: "Converts books and documents (PDF, EPUB, DOCX, HTML, Markdown, plain text, RTF, MOBI/AZW with Calibre) into structured agent skills, extracting frameworks, mental models, principles, techniques, and anti-patterns. Use when the user wants to study a document through GitHub Copilot CLI, Amp, Claude Code, Hermes Agent, OpenCode, or OpenClaw, apply an author's frameworks while working, or build a reusable knowledge base from a file."
---

<!--
Cross-agent notes (informational; ignored by host agents):
  - Compatible skill roots: GitHub Copilot CLI (~/.copilot/skills, ~/.agents/skills,
    .github/skills, .claude/skills, .agents/skills), Amp (.agents/skills,
    ~/.config/agents/skills, ~/.config/amp/skills), Claude Code (~/.claude/skills),
    Hermes Agent ($HERMES_HOME/skills, .hermes/skills, .agents/skills),
    OpenClaw (${OPENCLAW_STATE_DIR:-~/.openclaw}/skills, .agents/skills, skills/;
    ~/.agents/skills only with the default state).
    OpenCode (~/.config/opencode/skills, ~/.claude/skills, .opencode/skills,
    ~/.agents/skills, .agents/skills).
  - `allowed-tools` is intentionally omitted to stay agent-neutral: Copilot CLI uses
    `shell`/MCP-server names, Claude uses `Bash`/`Read`/`Write`/`Glob`/`Grep`, Amp
    adds `shell_command`. The skill needs shell (to run extract.py) and file
    read/write — each host will prompt for those on first use.
  - Argument hint: <path-to-document-folder-or-glob>... [skill-name-slug]
-->

# Book-to-Skill Converter

Transform written knowledge into actionable agent skills by extracting structure — not producing summaries.

## Philosophy

Books contain crystallized expertise: frameworks, principles, and techniques that took years to develop. This skill extracts that knowledge into a format GitHub Copilot CLI, Amp, Claude Code, Hermes Agent, OpenCode, OpenClaw, or another compatible agent can leverage repeatedly.
**Extract structure, not summaries.** A skill isn't a book report. It's a toolkit of:
- Named frameworks (mental models with clear application)
- Actionable principles (rules that guide decisions)
- Techniques (step-by-step methods)
- Anti-patterns (what to avoid and why)
- Voice calibration (how the author thinks and communicates)

**Preserve the author's precision.** Frameworks often have specific names for reasons. "The 5 Whys" isn't interchangeable with "ask why multiple times." Capture the exact formulation.

**Layer depth appropriately.** Simple books → simple skills. Complex books with 10+ frameworks → skills with reference files and on-demand chapters.

---

## Modes of Operation

Six paths available. Route based on what the user asks:

### 1. Full Conversion (Default)
**Trigger:** User provides one or more document/directory/glob paths without special instructions
**Action:** Run all steps below (Steps 0–10), including the Step 2.4 triage gate. If triage routes to notes or RAG, switch to Mode 5 rather than generating a skill.
**Output:** Complete skill with SKILL.md, chapters/, glossary, patterns, cheatsheet

### 2. Analyze Only
**Trigger:** User says "analyze", "just extract", or "I want to review before generating"
**Action:** Run Steps 0–3 (Step 2.4 included), then produce a structured extraction report (frameworks, principles, techniques found). Stop — do NOT generate skill files.
**Output:** Analysis report for user review

### 3. Generate from Prior Analysis
**Trigger:** User has existing analysis notes or previously ran analyze-only
**Action:** Skip Steps 0–3, use the provided analysis as input, run Steps 4–9
**Output:** Skill files from the provided analysis

### 4. Update / Fold-in (Existing Skill)
**Trigger:** User provides one or more new source paths and indicates they want to update an existing skill (either by pointing to the existing skill folder, providing a skill slug that already exists in `SKILLS_HOME`, or explicitly requesting an update).
**Action:** Run Step 0 (out-of-scope check), Step 1 (validate inputs), Step 1.5 (identify book type), and Step 2 (extract new files). Then skip to Step 5 (identify/detect existing skill path) and run the **Update / Fold-in Workflow** to merge the new content into the existing skill files.
**Output:** Updated existing skill with new/revised chapter summaries and merged indexes/glossaries.

### 5. Triage Only / Notes / RAG
**Trigger:** User asks "is this worth a skill?", "should this be notes?", or accepts a notes/RAG route from Step 2.4.
**Action:** Run Steps 0–2.4, then either stop with the triage report (triage only), build a notes pack, or build a RAG pack. Do NOT run Steps 3–10. When a library config is active, write the pack under its `breakdown` root (see **Library roots**).
**Output:** `triage.json` plus, optionally, `~/book-notes/<slug>/` or `~/book-rag/<slug>/`

### 6. Library Sweep (Inbox)
**Trigger:** No document path is given but a library config exists, or the user asks "scan my ebooks", "扫描收件箱", "还有哪些书没转换", "process the inbox", or "convert the next book".
**Action:** Resolve `SCRIPT_PATH` exactly as Step 2 does, then `SCRIPTS_DIR="$(dirname "$SCRIPT_PATH")"`. Run `"$PYTHON_BIN" "$SCRIPTS_DIR/library.py" show` to print the resolved roots, then `scan` for the pending list. Preprocess the pending books (Step 1.5 + Step 2 + Step 2.4) for a bounded batch, then present the single **preprocessing table** from Step 2.4: one row per book with the scored dimensions, the basis, and a recommended plan. Wait for the user to reply with numbers (one or more books/plans) — do not batch-convert before that selection. Run each selected book through the remaining steps for its chosen route, write the output to the configured route directory, then archive the source with `library.py archive`.
**Output:** The preprocessing table, then the selected books' skills or packs; each archived source moves to the archive and the ledger records `sha256`, route, slug, and output paths.

---

## Skill Locations

This converter can run from multiple skill systems. When looking for this converter's helper script or writing the generated book skill, prefer these locations in order:

1. GitHub Copilot CLI personal skills: `~/.copilot/skills/`
2. Cross-agent personal skills (Copilot, Amp, Codex; OpenClaw with its default state): `~/.agents/skills/`
3. Claude Code personal skills: `~/.claude/skills/`
4. Project-local Copilot skills: `.github/skills/`
5. Project-local Claude skills: `.claude/skills/`
6. Project-local Amp / Copilot / OpenClaw skills: `.agents/skills/`
7. Amp global skills: `~/.config/agents/skills/`
8. Amp legacy global skills: `~/.config/amp/skills/`
9. Hermes Agent personal skills: `$HERMES_HOME/skills/` (defaults to `~/.hermes/skills/`)
10. Hermes Agent project skills: `.hermes/skills/` or `.agents/skills/`
11. OpenClaw personal skills: `${OPENCLAW_STATE_DIR:-~/.openclaw}/skills/` (active state; `~/.agents/skills/` is shared only with the default state)
12. OpenClaw project skills: `.agents/skills/` or `skills/`
11. OpenCode personal skills: `~/.config/opencode/skills/` or `~/.agents/skills/`
12. OpenCode project skills: `.opencode/skills/` or `.agents/skills/`

For **generated** book skills, prefer the user-level cross-agent root `~/.agents/skills/` — one physical copy serves the cross-agent hosts and OpenClaw when it uses its default state. Copilot CLI and Amp discover it natively; Claude Code needs a symlink from `~/.claude/skills/<skill_name>` (created in Step 10, see Step 5 for the rules). Pick a host-private or project-local root only when the user explicitly asks for one. `BOOK_TO_SKILL_SCOPE=project` or `personal` can make that choice explicit for automation; do not ask a mandatory scope question merely because both scopes are available.

---

## Library roots (optional)

A library setup adds an inbox and an archive around the conversion, so a run can
start from "what have I not processed yet?" instead of a file path. The paths
live outside this repository, in `~/.book-to-skill/library.json` (or the file
named by `BOOK_LIBRARY_CONFIG`):

```json
{
  "inbox": "E:\\personal\\ebook",
  "done": "E:\\personal\\ebook\\已转换skill",
  "skills": "E:\\personal\\book-to-skills",
  "breakdown": "E:\\personal\\book-to-breakdown"
}
```

`done` defaults to `<inbox>/converted`, `ledger` to `<inbox>/.book-library.json`,
and `skills` / `breakdown` to `~/book-to-skills` / `~/book-to-breakdown` when
not configured. Environment overrides: `BOOK_INBOX`, `BOOK_DONE`,
`BOOK_SKILLS_HOME`, `BOOK_BREAKDOWN_HOME`, `BOOK_LEDGER`.

Run these through the deployed skill's `scripts/` directory (resolve
`SCRIPT_PATH` as in Step 2, then `SCRIPTS_DIR="$(dirname "$SCRIPT_PATH")"`):

```bash
# What are the paths? What is pending?
"$PYTHON_BIN" "$SCRIPTS_DIR/library.py" show
"$PYTHON_BIN" "$SCRIPTS_DIR/library.py" scan

# Output directory for a route, then record the processed source
"$PYTHON_BIN" "$SCRIPTS_DIR/library.py" path --route skill --slug <slug>
"$PYTHON_BIN" "$SCRIPTS_DIR/library.py" archive <source> \
  --route skill --slug <slug> --output "$SKILLS_HOME/<slug>"
```

Routes map to outputs: `skill` / `skill-lite` → `<skills>/<slug>/`, `notes` →
`<breakdown>/notes/<slug>/`, `rag` → `<breakdown>/rag/<slug>/`. The archive
moves the source by default (`--keep-source` copies) and is keyed by SHA-256, so
a renamed file is still recognized as already processed. `match` compares a
pending filename with the title in each existing `SKILL.md`; it is a suggestion
to confirm, never an automatic archive.

---

## Step 0 — Out-of-scope check

If no arguments are provided: resolve `SCRIPT_PATH` as in Step 2 and run
`"$PYTHON_BIN" "$(dirname "$SCRIPT_PATH")/library.py" show`. If the resolved
`inbox` exists, switch to Mode 6 (Library Sweep). Otherwise stop and respond:
> "book-to-skill requires a supported document path, folder, or glob pattern. Usage: `book-to-skill <path-to-document-folder-or-glob>... [skill-name-slug]`"

Throughout the workflow:
- **Resolve the destination root first.** Before any existing-skill lookup, determine where this run would write: the personal or project-local root for the user's host, per the Step 5 table and selection rules — a project-local request uses its project-local root, never the personal root. Below, "the resolved root" means that destination.
- Identify the input paths and the optional skill slug.
- If the last argument is not a file, folder, or glob that exists or matches any files, and it looks like a skill slug (e.g. lowercase hyphens, alphanumeric), treat it as `SKILL_NAME`.
- Treat all other arguments as the list of `INPUT_PATHS`.
- If any input path is an existing skill directory (contains `SKILL.md` and a `chapters/` sub-folder), or if `SKILL_NAME` matches an existing skill slug in the resolved root, flag this run as an **Update/Fold-in** operation (Mode 4).
- **Re-run guard.** Before starting extraction for a Full Conversion, derive the prospective skill slug under Step 5's naming options — the author-concept form, the by-title form, and any `SKILL_NAME` given — and check the resolved root for an existing match. On a match, STOP and ask the user: "`<skill-name>` already exists. Choose: (1) Update/Fold-in (Mode 4), (2) verify the existing skill is complete and stop, or (3) force full regeneration." Do not re-extract until the user chooses. On context recovery after an interrupted run (network cut-off, replayed or continued conversation), reuse the extraction work directory that run reported (`Workdir ->` in its output, or the path you set in `BOOK_SKILL_WORKDIR`) **only if it is still intact and still matches the current inputs and options** — the directory exists, its `metadata.json` is readable, the `sources` it lists match the files being converted now one-to-one on filename **and content fingerprint** (the extractor records a per-source `sha256` in `metadata.json`; recompute the fingerprint from each file as it exists now and require an exact match — `reuse_is_safe()` in `book_to_skill/utils.py` is the executable form of this check), and its recorded `extraction_mode` is the mode this run is using (Step 2's "confirm the extraction is the document you asked for" rule). If it is missing (temp cleanup), its `metadata.json` is gone, the sources no longer match (a different filename, or a changed content fingerprint), the recorded metadata has no `sha256` for a source (recorded before fingerprints existed, so freshness cannot be established), or the mode differs, say so and start a fresh extraction instead of resuming. When in doubt, ask the user before discarding or resuming.

---

## Step 1 — Validate input

Verify that there is at least one supported file, directory, or glob pattern among the `INPUT_PATHS`.
For directories and globs, expand them to find matching supported files (`.pdf`, `.epub`, `.docx`, `.txt`, `.md`, `.markdown`, `.rst`, `.adoc`, `.html`, `.htm`, `.rtf`, `.mobi`, `.azw`, `.azw3`).

If no supported files are found, stop with a clear error message.

---

## Step 1.5 — Identify content type

Infer `BOOK_TYPE` from the source; do not stop to ask:
- `technical` — the argument depends on code blocks, tables, formulas, or diagrams;
- `text` — prose, narrative non-fiction, management, history, essays.
If the evidence is mixed or unclear, use `text` (the fast path) and say so in the preprocessing table. Ask only when the choice materially changes extraction quality and the evidence is genuinely split.

**If `BOOK_TYPE=technical`**, inform the user before proceeding:
> "📐 Technical mode selected — using Docling for structure-aware extraction (tables, code blocks, formulas preserved as markdown). This takes ~1.5s per page, so expect a few minutes for longer sources. Starting now…"

**If `BOOK_TYPE=text`**, inform:
> "📄 Text mode selected — using the fastest suitable extractor for each file type. Plain text/Markdown/HTML are usually ready in seconds; PDFs use pdftotext when available."

---

## Step 2 — Extract text from the source documents

Run the extraction script, passing the input paths:

```bash
SCRIPT_PATH=""
HERMES_HOME_RESOLVED="${HERMES_HOME:-$HOME/.hermes}"
OPENCLAW_STATE_DIR_RESOLVED="${OPENCLAW_STATE_DIR:-$HOME/.openclaw}"
PROJECT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
HERMES_PROJECT_TRUSTED=false
if [ -n "$PROJECT_ROOT" ] && [ "${HERMES_AGENT:-}" = true ] && \
  command -v hermes >/dev/null 2>&1 && \
  command -v python3 >/dev/null 2>&1 && \
  hermes config get skills.trusted_project_dirs --json 2>/dev/null | PROJECT_ROOT="$PROJECT_ROOT" python3 -c 'import json, os, pathlib, sys; root=pathlib.Path(os.environ["PROJECT_ROOT"]).resolve(); sys.exit(not any(pathlib.Path(p).expanduser().resolve() == root for p in json.load(sys.stdin)))' 2>/dev/null
then
  HERMES_PROJECT_TRUSTED=true
fi

CANDIDATES=(
  "$HOME/.copilot/skills/book-to-skill/scripts/extract.py"
  "$HOME/.agents/skills/book-to-skill/scripts/extract.py"
  "$HOME/.claude/skills/book-to-skill/scripts/extract.py"
  "${OPENCLAW_STATE_DIR_RESOLVED}/skills/book-to-skill/scripts/extract.py"
  "${OPENCLAW_STATE_DIR_RESOLVED}/skills"/*/book-to-skill/scripts/extract.py
  "${OPENCLAW_STATE_DIR_RESOLVED}/skills"/*/*/book-to-skill/scripts/extract.py
  "${OPENCLAW_STATE_DIR_RESOLVED}/skills"/*/*/*/book-to-skill/scripts/extract.py
  "${OPENCLAW_STATE_DIR_RESOLVED}/skills"/*/*/*/*/book-to-skill/scripts/extract.py
  "${OPENCLAW_STATE_DIR_RESOLVED}/skills"/*/*/*/*/*/book-to-skill/scripts/extract.py
  "${OPENCLAW_STATE_DIR_RESOLVED}/skills"/*/*/*/*/*/*/book-to-skill/scripts/extract.py
  "$HOME/.config/opencode/skills/book-to-skill/scripts/extract.py"
  "$HERMES_HOME_RESOLVED/skills/book-to-skill/scripts/extract.py"
  "$HERMES_HOME_RESOLVED"/skills/*/book-to-skill/scripts/extract.py
)
if [ "${HERMES_AGENT:-}" != true ]; then
  # Project-local roots are resolved against the git worktree, not the current
  # directory: an agent can be invoked from anywhere inside the project (e.g.
  # `src/nested`) and these roots still have to be found — that is how OpenCode
  # and the other hosts discover project skills. The CWD-relative forms are kept
  # so the probe also works outside a git repository.
  if [ -n "$PROJECT_ROOT" ]; then
    CANDIDATES+=(
      "$PROJECT_ROOT/.github/skills/book-to-skill/scripts/extract.py"
      "$PROJECT_ROOT/.claude/skills/book-to-skill/scripts/extract.py"
      "$PROJECT_ROOT/.agents/skills/book-to-skill/scripts/extract.py"
      "$PROJECT_ROOT/.opencode/skills/book-to-skill/scripts/extract.py"
    )
  fi
  CANDIDATES+=(
    ".github/skills/book-to-skill/scripts/extract.py"
    ".claude/skills/book-to-skill/scripts/extract.py"
    ".agents/skills/book-to-skill/scripts/extract.py"
    "skills/book-to-skill/scripts/extract.py"
    "skills"/*/book-to-skill/scripts/extract.py
    "skills"/*/*/book-to-skill/scripts/extract.py
    "skills"/*/*/*/book-to-skill/scripts/extract.py
    "skills"/*/*/*/*/book-to-skill/scripts/extract.py
    "skills"/*/*/*/*/*/book-to-skill/scripts/extract.py
    "skills"/*/*/*/*/*/*/book-to-skill/scripts/extract.py
    ".opencode/skills/book-to-skill/scripts/extract.py"
  )
  if [ -n "$PROJECT_ROOT" ]; then
    CANDIDATES+=(
      "$PROJECT_ROOT/skills/book-to-skill/scripts/extract.py"
      "$PROJECT_ROOT/skills"/*/book-to-skill/scripts/extract.py
      "$PROJECT_ROOT/skills"/*/*/book-to-skill/scripts/extract.py
      "$PROJECT_ROOT/skills"/*/*/*/book-to-skill/scripts/extract.py
      "$PROJECT_ROOT/skills"/*/*/*/*/book-to-skill/scripts/extract.py
      "$PROJECT_ROOT/skills"/*/*/*/*/*/book-to-skill/scripts/extract.py
      "$PROJECT_ROOT/skills"/*/*/*/*/*/*/book-to-skill/scripts/extract.py
    )
  fi
fi
CANDIDATES+=(
  "$HOME/.config/agents/skills/book-to-skill/scripts/extract.py"
  "$HOME/.config/amp/skills/book-to-skill/scripts/extract.py"
)
if [ "$HERMES_PROJECT_TRUSTED" = true ]; then
  CANDIDATES=(
    "$PROJECT_ROOT/.hermes/skills/book-to-skill/scripts/extract.py"
    "$PROJECT_ROOT/.hermes/skills"/*/book-to-skill/scripts/extract.py
    "$PROJECT_ROOT/.agents/skills/book-to-skill/scripts/extract.py"
    "$PROJECT_ROOT/.agents/skills"/*/book-to-skill/scripts/extract.py
    "${CANDIDATES[@]}"
  )
fi
for candidate in "${CANDIDATES[@]}"
do
  if [ -f "$candidate" ]; then
    SCRIPT_PATH="$candidate"
    break
  fi
done

if [ -z "$SCRIPT_PATH" ]; then
  echo "Could not find scripts/extract.py for book-to-skill" >&2
  exit 1
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN="python"
fi
SCRIPTS_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"

"$PYTHON_BIN" "$SCRIPT_PATH" $INPUT_PATHS --mode <BOOK_TYPE> --install-missing ask
```

Before extraction, the script checks optional Python packages needed for the detected format. If a better extractor is missing, it prompts the user with the available fallback. Non-interactive sessions default to fallback unless install mode is explicitly `yes`.

**Tip — preflight the environment:** run `"$PYTHON_BIN" "$SCRIPT_PATH" --check` to print a per-format report of which extractors are installed and the exact command to install whatever is missing, without processing any file. Useful when a user reports a setup or quality problem.

This creates a **per-run** work directory — `<tempdir>/book_skill_work-<pid>/` by default, or exactly the path you set in `BOOK_SKILL_WORKDIR` — containing:
- `full_text.txt` — combined extracted text of all sources with clear visually demarcated boundaries.
- `metadata.json` — overall combined size, words, pages, token counts, dropped EPUB image counts, the resolved `workdir`, and a detailed list of individual processed `sources`.

The run prints all three paths on completion (`Workdir ->`, `Text ->`, `Meta ->`). **Take the paths from that output (or from `metadata.json`'s own `workdir` field) rather than assuming a fixed location** — the directory name differs per run so that concurrent extractions on one machine cannot overwrite each other's results.

Read that run's `metadata.json` to inspect the results.

**Always confirm the extraction is the document you asked for** before generating anything: check `filename` / `source_file` in `metadata.json`, or the `SOURCE:` header on the first line of `full_text.txt`. If you are waiting on a background run, wait on *its* specific workdir — polling a shared path can surface a different run's output.

---

## Step 2.4 — Skill-fit triage (gate)

Extraction prints a triage block and writes `<workdir>/triage.json`. Read it
**before** the cost estimate and before any generation. If it is missing (an
older extractor, or `--no-triage` was used), run it from the converter root:

```bash
"$PYTHON_BIN" "$SCRIPTS_DIR/triage.py" "$WORKDIR"
```

**Default flow: score first, then show one table; do not stop for a separate
content-type / frequency / purpose questionnaire.** For every candidate source,
run triage with an explicit demand assumption and print one preprocessing
table:

| # | Source | Pages / chars | Structure | Frameworks | Actionability | Narrative | Fidelity | Volume | Demand (assumed) | Total | Recommended plan | Basis |
|---|---|---|---|---|---|---|---|---|---|---|---|---|

- Scores are the 0–100 `subscores` from that run's `triage.json`; `Total` is
  the weighted score.
- Run triage once with the assumed `--reuse` / `--decision` values, so `Total`
  and the recommendation come from the same inputs. Never pair a provisional
  demand score with a non-provisional plan.
- `Basis` names the concrete signals behind the score: chapters detected, ToC
  yes/no, framework cues per 10k chars, decision cues per 10k chars,
  chars/page, narrative signal, and warnings.
- `Demand (assumed)` is an explicit assumption, not a hidden fact. Infer the
  most likely use from the source and the user's context (for example
  “occasional + decisions” or “once + background”); label it as an assumption.
- `Recommended plan` is one of `skill`, `skill-lite`, `notes`, `rag`, with a
  one-clause reason. It follows the thresholds and caps below; do not invent a
  route.
- Under the table, list the numbered choices, one line each, so the user can
  reply with numbers (one or more books/plans), for example:
  `1. <book> → notes — narrative-heavy; once/background reads do not repay a skill`

After the user selects numbers:
- Re-run triage with `--reuse` / `--decision` matching the selected plan's
  demand assumption, so the JSON records the real inputs.
- If the refreshed verdict contradicts the selected plan, say so and record the
  explicit override; otherwise continue.

| Verdict | Action |
|---|---|
| `skill` | Continue to Step 2.5 (cost), then Step 3. |
| `skill-lite` | Put the proposed 3–6 chapter scope in the numbered choice. If the user selects it, record the scope and continue. Otherwise offer the notes pack. |
| `notes` | Switch to Mode 5: build the notes pack (see **Fallback outputs**). Stop. |
| `rag` | Switch to Mode 5: build the RAG pack. Stop. |
| `blocked` | Report the blocker — usually extraction. Do not synthesize. Offer OCR, a better parser, or a different file. |

**This gate is binding.** Do not continue to Steps 3–10 on a `notes`, `rag`, or
`blocked` verdict unless the user explicitly chooses that route or says
"override" (or equivalent). Record the choice/override and the original verdict
in the final report.

If the report says `"provisional": true` after the demand assumption is applied,
the assumption was genuinely unclear — say which dimension is unresolved and ask
one question, not a questionnaire.

---

## Step 2.5 — Pre-flight cost estimate

Read this run's `metadata.json` (the `Meta ->` path from the extraction output) and present the user with an estimate **before doing any generation**:

```
🧭 Triage: <score>/100 → <verdict> (<route>) — only `skill` / `skill-lite` reach this step

📖 Sources detected: <total_sources> source(s)
<list each source filename and format from the sources metadata list>
<if images_dropped > 5: warn that N source images were not read>
📄 Combined Pages/Sections: ~<N> | Words: ~<N> | Total tokens: ~<N>K

💰 Estimated token cost (Full Conversion / Update):
   Input  (reading + prompts): ~<N>K tokens
   Output (skill files generated/updated):  ~<N>K tokens
   Total:                           ~<N>K tokens

   Cost: multiply the token counts above by your model's current
   input/output per-1M-token rates (prices and model names change often —
   do not hardcode them; quote today's rate and label it as an estimate).

   ⏱  Estimated time: ~<N> minutes

📁 Files to be generated/updated:
   SKILL.md + chapter files + glossary + patterns + cheatsheet

➡  Proceed with Full Conversion / Update? (or type "analyze only" to preview first)
```

**How to estimate:**
- Input tokens ≈ `estimated_tokens` from metadata × 1.3 (prompts overhead per chapter pass)
- Output tokens ≈ chapters × per-chapter budget + 4,000 (SKILL.md) + 4,500 (glossary + patterns + cheatsheet)
  - Per-chapter budget midpoint by `BOOK_TYPE` (DEPTH is decided later in Step 4 and can raise it): `text` ≈ 1,000, `technical` ≈ 1,800. If the user has already indicated reference-only vs deep study, use the matching row of the Step 7 matrix.
- Cost: report the token counts and multiply by the user's current per-1M-token input/output rates. Do NOT hardcode dollar figures — model names and prices change; if you show one, label it an estimate and date it.

Show this estimate for the selected plan and wait for one confirmation. Do not
re-ask the route, content type, or demand questions — the numbered selection
already settled them. If the user says "analyze only", switch to Mode 2.

---

## Step 2.6 — REPL-style access for large books (> 50k tokens)

Inspired by the Recursive Language Model (RLM) paradigm: treat `full_text.txt` as a queryable corpus, not a single read. Loading the whole file into context burns budget you will need later for generation.

For books over ~50k tokens, prefer programmatic probes over `Read(full_text.txt)` without bounds:

```bash
# Size check before any Read
wc -w "$FULL_TEXT_PATH"

# Find chapter offsets without loading the whole file
grep -n -E "^\s*(Chapter|CHAPTER)\s+[0-9]+" "$FULL_TEXT_PATH" | head -40

# Pull only the chapter you need (lines start..end inclusive)
sed -n '<start>,<end>p' "$FULL_TEXT_PATH"

# Verify a framework is actually mentioned before claiming it in SKILL.md
grep -c -i "westrum\|dora" "$FULL_TEXT_PATH"

# Targeted Read with offset/limit avoids dumping the full file
# Read(file_path=full_text.txt, offset=<line>, limit=<lines>)
```

Use this approach for Step 3 (structure analysis), Step 7 (per-chapter summaries), and Step 8 (glossary / patterns extraction). On books under 50k tokens, a single `Read` is fine.

Why this matters: a 200-page book is ~75k tokens. Re-reading it once per chapter (28 passes) costs ~2M input tokens; using grep + sed to pull only relevant slices keeps generation cost proportional to the output, not the source.

---

## Step 3 — Analyze book structure

Read the first 8,000 characters of the extracted `full_text.txt` to identify:
- Book **title** and **author(s)**
- **Chapter structure** (look for "Chapter N", "PART I", numbered headings, table of contents)
- **Core themes** and subject domain
- Approximate number of chapters

Then read the Table of Contents section if present to map all chapters.

**If mode is "Analyze Only":** produce the extraction report now and stop. Structure:
```
## Extraction Report — <Title>

### Author's Core Frameworks
- **<Framework Name>**: <what it is and when to apply>

### Key Principles
- <Principle>: <actionable rule>

### Techniques & Methods
- <Technique>: <step-by-step or how-to>

### Anti-patterns
- <What to avoid>: <why>

### Suggested Skill Name
`{author-lastname}-{core-concept}` — e.g. `cialdini-influence`

### Chapters Detected
| # | Title | Main Frameworks |
```

---

## Step 4 — Infer purpose and depth (Full Conversion only)

Infer `DEPTH` from the selected plan and the source; do not ask a separate
purpose questionnaire:
- `reference` — the selected plan is `skill-lite`, or the user chose
  reference/lookup use or a narrow chapter scope.
- `study` — a full `skill` conversion, or the user chose to apply or think
  with the author's frameworks.
Use the selected plan to weight what gets highlighted in the SKILL.md Core
section. Record the inference in the final report. Ask one question only when
the selected plan is genuinely ambiguous (for example, a full skill requested
for only a few chapters).

`DEPTH` and `BOOK_TYPE` together set the per-chapter token budget in Step 7. Do
**not** ask a separate "study vs reference" question. (In Modes 2/3, where Step 4
is skipped, default `DEPTH=study`.)

---

## Step 5 — Determine skill name

If `SKILL_NAME` was provided, use it as the skill slug.
Otherwise, propose two options and let the user choose:
- **By author-concept**: `{author-lastname}-{core-concept}` (e.g. `cialdini-influence`, `meadows-systems`)
- **By title**: lowercase hyphens from book title (e.g. `designing-data-intensive-apps`)

Default to author-concept format if the book has a strong methodological identity.

Choose the destination skill root (`SKILLS_HOME`). First resolve **scope** from an explicit user request or `BOOK_TO_SKILL_SCOPE`, then probe **host**. A request for project-local/project output selects the project-local row; a request for personal/global output selects the personal row. If neither scope is requested, preserve the established personal default (`~/.agents/skills` for non-Hermes hosts). Do not ask a mandatory scope question solely because project-local roots exist. The selected root may still require host approval before writing.

| Host agent | Personal skill root | Project-local root |
|---|---|---|
| **GitHub Copilot CLI** | `~/.agents/skills` (discovered natively) | `.github/skills` → `.claude/skills` → `.agents/skills` |
| **Amp** | `~/.agents/skills` (discovered natively) | `.agents/skills` |
| **OpenAI Codex** | `~/.agents/skills` (discovered natively; follows symlinks) | `.agents/skills` |
| **Hermes Agent** | `$HERMES_HOME/skills/<category>` (defaults to `~/.hermes/skills/<category>`) | `.hermes/skills/<category>` → `.agents/skills` |
| **Claude Code** | `~/.agents/skills` + symlink from `~/.claude/skills/<skill_name>` | `.claude/skills` |
| **OpenClaw** | `${OPENCLAW_STATE_DIR:-~/.openclaw}/skills` (active state; `~/.agents/skills` only with default state) | `.agents/skills` → `skills/` |

Hermes Agent is the one host that keeps its own personal root: it partitions personal skills by category and does not scan the cross-agent root. Use the active profile's `HERMES_HOME` and choose a category that matches the generated skill's subject. Do not construct profile paths manually. If the user selects a project-local Hermes root, run `hermes skills trust <project-root>` after generation and verify discovery with `hermes skills list`; project skills remain unavailable until the project is trusted.

For OpenClaw, use the active state directory's `skills/` root: `${OPENCLAW_STATE_DIR:-~/.openclaw}/skills/`. The shared `~/.agents/skills` compatibility root is discoverable only when `OPENCLAW_STATE_DIR` is unset or the default `~/.openclaw`; with a non-default state, do not claim that OpenClaw will see a shared-root install. Verify discovery with `openclaw skills list` after generation.
| **OpenCode** | `~/.agents/skills` (discovered natively; `~/.config/opencode/skills` and `~/.claude/skills` are read too) | `.opencode/skills` → `.agents/skills` → `.claude/skills` |

Hermes Agent is the one host that keeps its own personal root: it partitions personal skills by category and does not scan the cross-agent root. Use the active profile's `HERMES_HOME` and choose a category that matches the generated skill's subject. Do not construct profile paths manually. If the user selects a project-local Hermes root, run `hermes skills trust <project-root>` after generation and verify discovery with `hermes skills list`; project skills remain unavailable until the project is trusted.

OpenCode scans the cross-agent `~/.agents/skills` root natively, so the generated-skill default above already serves it — no symlink and no trust step. It also reads its own managed `~/.config/opencode/skills` root and the Claude compatibility root `~/.claude/skills`; use the OpenCode-managed root only when the user asks for it. Project skills are discovered by walking up from the working directory to the git worktree, so start a new session after generation if the skill does not appear. (`~/.cache/opencode/skills` is the remote-skill download cache from `skills.urls`, not an authoring root — never write a generated skill there.)

**Library mode exception.** If this run came from a library scan (Mode 6), or the resolved library config has a `skills` root, set `SKILLS_HOME` to that root and write `<slug>/` there directly. Skip the host table and the Step 10 symlink — the library folder is the product location, and the user can install from it later. State the chosen root in the report.

Selection rules:
1. Personal install: set `SKILLS_HOME` to `~/.agents/skills` (create the directory if missing). One exception, so the default does not invent a convention in someone else's house: if `~/.agents/skills` does not exist **and** the host's private root already contains skills, use the private root instead and say why in the report.
2. **Claude Code does not scan `~/.agents/skills`** — after generation completes, Step 10 links the skill in with `ln -sfn "$HOME/.agents/skills/<skill_name>" "$HOME/.claude/skills/<skill_name>"`.
3. **Hermes Agent personal installs use the Hermes row above**, not the cross-agent root, and take no symlink.
4. If the user explicitly asks for a host-private root (`~/.copilot/skills`, `~/.claude/skills`, `~/.config/agents/skills`, `~/.config/amp/skills`), honor it and skip the symlink.
5. If the user explicitly asked for project-local output, use the project-local row for their host.
6. If the choice requires knowing the host (project-local output, the Hermes personal root, the OpenClaw state root, or the Claude Code symlink) and you cannot identify it, ask: "Which agent are you running in — OpenCode, OpenClaw, Hermes Agent, GitHub Copilot CLI, Amp, Codex, or Claude Code?"
7. For OpenClaw personal output, use `${OPENCLAW_STATE_DIR:-$HOME/.openclaw}/skills`. The shared `~/.agents/skills` root is a valid OpenClaw destination only when `OPENCLAW_STATE_DIR` is unset or equals the default `$HOME/.openclaw`; otherwise use the active state root or a project/extra directory.
8. If the user explicitly asks for an OpenClaw-managed personal root, use the active state root and verify discovery with `openclaw skills list`.

Set `SKILLS_HOME` to the selected root and check if `$SKILLS_HOME/<skill_name>/` already exists. On Claude Code, also check whether `~/.claude/skills/<skill_name>` exists as a **real directory** (not a symlink) — a previous install may live there; if so, offer to migrate it (move the directory into `~/.agents/skills/` and replace the original path with the symlink) before continuing.
If the skill already exists, prompt the user to choose:
1. **Update / Fold-in** (Mode 4) — integrate new files/content into the existing skill components.
2. **Overwrite** — delete and regenerate the skill from scratch.
3. **Rename** — append `-2` or use a different custom slug.

If the user selects **Update / Fold-in**, run Step 2.4 on the new material first — a source that triages to `notes` or `rag` should not be folded into a skill without an explicit override — then proceed to the **Update / Fold-in Workflow** section after Step 2.5 (skipping Steps 3, 4, 6, 7, 8, 9).

---

## Step 6 — Create skill directory structure

```bash
mkdir -p "$SKILLS_HOME/<skill_name>/chapters"
```

---

## Step 7 — Generate chapter summaries

**TOKEN BUDGET RULE — CRITICAL (adaptive):**

The per-chapter budget scales with `BOOK_TYPE` and `DEPTH`. Technical chapters need room for code and tables; study depth needs room for worked reasoning. Pick the budget from this matrix:

| | `DEPTH=reference` | `DEPTH=study` |
|---|---|---|
| `BOOK_TYPE=text` | 800–1,200 tokens | 1,000–1,800 tokens |
| `BOOK_TYPE=technical` | 1,200–1,800 tokens | 2,000–3,000 tokens |

- These are per-file targets, not hard caps — a dense chapter may run over, a thin one under. Density still beats length (Quality Rule #3): never pad to hit a number.
- Files are loaded on-demand, so a larger chapter only costs tokens when that chapter is actually read.
- When in doubt between two cells (e.g. mixed-content book), use the lower budget and let depth come from precision, not volume.

**`DEPTH=study` is earned with content, not a bigger number.** The standard section template (Core Idea → Connects To) naturally lands a dense prose chapter around 700–900 tokens. To reach the study budget *honestly* — not by padding — a study-depth chapter must add concrete material:
- **Reproduce one worked example or artifact** from the chapter (e.g. the example press release, a sample dialogue, a filled-in template, a decision the author walks through) under a `## Worked Example` section. This is the single biggest lever and the main thing a learner returns for.
- **Expand the "How" of each framework** into explicit steps or criteria, not a one-liner.
- **Add a short "Why it works / failure mode" note** to the top 1–2 frameworks.

If a chapter genuinely has no worked example and resists expansion, let it land below the study floor rather than padding — and note that the chapter is thin in its Core Idea. A `reference`-depth chapter, by contrast, deliberately omits worked examples and keeps only the decision-ready essentials.

For EACH chapter/major section identified in Step 3:

Read the corresponding section of the extracted `full_text.txt` (use character offsets or grep for chapter headings).

Create `$SKILLS_HOME/<skill_name>/chapters/ch<NN>-<slug>.md` using the structure below.

**Adapt emphasis based on `BOOK_TYPE`:**
- `technical` → prioritize "Code Examples", "Reference Tables", and "Commands & APIs" sections; preserve exact syntax
- `text` → prioritize "Frameworks Introduced", "Mental Models", and "Key Takeaways"; skip empty technical sections

```markdown
# Chapter N: <Full Title>

## Core Idea
<1–2 sentences: the single most important thing this chapter teaches>

## Frameworks Introduced
- **<Framework Name>**: <exact formulation — preserve the author's naming>
  - When to use: <specific situation>
  - How: <steps or criteria>

## Key Concepts
- **<Term>**: <precise definition in 1 sentence>
(5–10 most important terms from this chapter)

## Mental Models
<2–4 frameworks or thinking tools. Write as "Use X when Y" or "Think of X as Y">

## Anti-patterns
- **<What to avoid>**: <why it fails>

## Code Examples *(technical books only — omit if BOOK_TYPE=text)*
<!-- Copy the most instructive snippet from the chapter. Preserve indentation exactly. -->
```<language>
<key code example from this chapter>
```
- **What it demonstrates**: <one line>

## Reference Tables *(technical books only — omit if BOOK_TYPE=text)*
<!-- Reproduce any comparison matrix, parameter table, or decision table from the chapter in markdown. -->

## Worked Example *(DEPTH=study only — omit for DEPTH=reference)*
<!-- Reproduce or reconstruct one concrete example the author works through: a
     sample document, a dialogue, a filled-in template, a before/after, or a
     decision walked end-to-end. This is what makes a study chapter worth its
     budget. Keep it faithful to the source; never copy long raw passages —
     reconstruct the example compactly. -->

## Key Takeaways
1. <Actionable insight>
2. <Actionable insight>
3. <Actionable insight>
(3–7 takeaways a practitioner must remember)

## Connects To
- **Ch N**: <why this chapter relates>
- **<Concept>**: <external concept or standard it connects with>
```

---

## Step 8 — Generate supporting files

### glossary.md
Create `$SKILLS_HOME/<skill_name>/glossary.md`:
- Every significant term from the book, alphabetically sorted
- Format: `**Term** — definition (Ch N)`
- Max 1,500 tokens

### patterns.md
Create `$SKILLS_HOME/<skill_name>/patterns.md`:
- All concrete techniques, design patterns, algorithms from the book
- Format: `## Pattern Name\n**When to use**: ...\n**How**: ...\n**Trade-offs**: ...`
- Max 2,000 tokens

### cheatsheet.md
Create `$SKILLS_HOME/<skill_name>/cheatsheet.md`:

**This is the most differentiated layer of the skill — treat it as a reasoning aid, not a keyword list.** Anyone can grep the glossary for a term. The cheatsheet captures the author's *judgment*: the decisions they'd make and why. It's the file that turns "I know the words" into "I'd act the way the author would".

Prioritize, in order:
1. **Decision rules** — "When X, do Y, because Z." The if/then logic the author applies, stated so the reader can apply it without re-reading the book.
2. **Decision trees / flowcharts** (as nested bullets or a small table) — for choices with more than two branches.
3. **Trade-off matrices** — competing options scored on the dimensions the author cares about, so the reader can pick under their own constraints.
4. **Thresholds & defaults** — the specific numbers, ratios, or rules of thumb the author commits to (e.g. "keep functions under ~20 lines", "alert when error budget < 10%").
5. **Tells & smells** — fast heuristics for recognizing a situation ("if you see X, you're probably in trouble Y").

Avoid: bare term→definition rows (that's the glossary), and prose paragraphs (that's the chapters). Every line should help the reader *decide* something.

- Format mostly as compact tables and decision rules; the content you'd want on a single printed page kept beside you while working.
- Max 1,200 tokens.

---

## Step 9 — Generate the master SKILL.md

**CRITICAL TOKEN BUDGET: Keep SKILL.md body under 4,000 tokens.**
Compaction truncates from the END — put the most important content FIRST.

Create `$SKILLS_HOME/<skill_name>/SKILL.md`:

```markdown
---
name: <skill_name>
description: "Knowledge base from \"<Full Title>\" by <Author(s)>. Use when applying <author>'s frameworks for <key topics, 3–6 terms>, studying the book, or referencing its concepts."
---

<!-- argument-hint: [topic, framework name, or chapter number] -->

# <Full Title>
**Author**: <Author(s)> | **Pages**: ~<N> | **Chapters**: <N> | **Generated**: <YYYY-MM-DD>

## How to Use This Skill

- **Without arguments** — load core frameworks for reference
- **With a topic** — ask about `replication`, `pricing`, or another indexed topic; I find and read the relevant chapter
- **With chapter** — ask for `ch05`; I load that specific chapter
- **Browse** — ask "what chapters do you have?" to see the full index

When you ask about a topic not covered in Core Frameworks below, I will read
the relevant chapter file before answering.

---

## Core Frameworks & Mental Models
<!-- ~2,000 tokens: the author's most important named frameworks and principles.
     Preserve exact names. Write as "Use X when Y", "Prefer X over Y because Z".
     This is a toolkit, not a summary. -->

<generate 2,000 tokens of the most critical frameworks and insights here>

---

## Chapter Index

| # | Title | Key Frameworks |
|---|-------|----------------|
| [ch01](chapters/ch01-<slug>.md) | <Title> | <framework1>, <framework2> |
| [ch02](chapters/ch02-<slug>.md) | <Title> | <framework1>, <framework2> |
...

## Topic Index

<!-- Alphabetical. Major terms/frameworks → chapter(s) that cover them. -->
- **<Term>** → ch<N>[, ch<N>]
- **<Term>** → ch<N>

## Supporting Files

- [glossary.md](glossary.md) — all key terms with definitions
- [patterns.md](patterns.md) — all techniques and design patterns
- [cheatsheet.md](cheatsheet.md) — quick reference tables and decision guides

---

## Scope & Limits

This skill covers the book content only. For hands-on implementation in your codebase,
combine with project-specific tools. For topics beyond this book, check related skills
or ask the agent directly.
<if images_dropped > 5: state that N source images were not read>
```

---

## Step 9.5 — Scan the generated skill

Before reporting success, loading the skill in another session, or publishing it, run the advisory security scan:

```bash
SKILL_CONVERTER_ROOT="$(cd "$(dirname "$SCRIPT_PATH")/.." && pwd)"
"$PYTHON_BIN" "$SKILL_CONVERTER_ROOT/tools/scan_generated_skill.py" "$SKILLS_HOME/<skill_name>"
```

If the scanner exits non-zero, stop and ask a human to review its file/line findings. Do not silently rewrite the generated files, and do not load or publish the skill until the findings are resolved or explicitly accepted.

---

## Step 10 — Cleanup and report

If the host is Claude Code and `SKILLS_HOME` is `~/.agents/skills` (the default personal install), expose the skill to Claude Code with a symlink — Claude Code only scans `~/.claude/skills`:

```bash
mkdir -p "$HOME/.claude/skills"
LINK="$HOME/.claude/skills/<skill_name>"
TARGET="$HOME/.agents/skills/<skill_name>"
if [ -d "$LINK" ] && [ ! -L "$LINK" ]; then
  CLAUDE_STATUS="skipped-realdir"                 # Step 5 migration declined; leave the old dir
else
  ln -sfn "$TARGET" "$LINK" 2>/dev/null || true
  # Read the link back — do NOT trust that `ln` did what was asked. On Windows/MSYS
  # `ln -s` may COPY instead of link (or need Developer Mode / an elevated shell), and
  # PowerShell/cmd have no `ln` at all. The report must reflect what is on disk, not the
  # fact that the command ran.
  if [ -L "$LINK" ] && [ "$(readlink "$LINK")" = "$TARGET" ]; then
    CLAUDE_STATUS="linked"
  elif [ -e "$LINK" ]; then
    CLAUDE_STATUS="copy"                           # a real file/dir landed instead of a link
  else
    CLAUDE_STATUS="absent"                         # ln unavailable or refused
  fi
fi
```

The real-directory guard is required: `ln -sfn` into an existing real directory would nest the link *inside* it (`~/.claude/skills/<skill_name>/<skill_name>`), leaving Claude Code loading the stale copy. If the user declined the Step 5 migration, skip the symlink and say so in the report — Claude Code keeps using the old directory until it is migrated.

**Read the link back before you report anything about it.** The symlink is a claim, not a fact: fill the "Discoverable by" line from `CLAUDE_STATUS` (what is actually on disk), never from "the command was issued". **Do not hard-fail when the link is missing or is a copy** — the skill exists at the hub and every other host still finds it; the honest report is "written to `~/.agents/skills/<skill_name>`; Claude Code will not see it until the link is created", not an abort. (Windows lead, unverified: a directory junction — `mklink /J` in an elevated `cmd`, or `New-Item -ItemType Junction` in PowerShell — needs neither Developer Mode nor a symlink privilege; if you attempt it, it does not change the read-back-then-report rule.)

Skip this when the user chose a host-private or project-local root (Step 5, rules 3-4), and skip it in library mode (rule 0).

**Archive the source (library runs only).** After every output file is written and Step 9.5 has passed, move the original source out of the inbox:

```bash
"$PYTHON_BIN" "$SCRIPTS_DIR/library.py" archive "<source path>" \
  --route <skill|skill-lite|notes|rag> --slug <skill_name> \
  --output "$SKILLS_HOME/<skill_name>"
```

`--route` must be the route this run actually took, not the one triage first suggested. For notes/RAG packs, pass the pack directory as `--output` and skip the skill-specific steps above. Use `--keep-source` only when the user wants the original left in place. **Never archive after a `blocked` verdict, an aborted run, or a failed write** — the source must stay in the inbox so the next scan offers it again.

Then clean up the extraction workdir:

```bash
PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN="python"
fi

Remove **the work directory this run actually used** — the `Workdir ->` path from the
extraction output, which is also stored as `workdir` in `metadata.json`. Never delete a
directory you did not create: another extraction may be running beside yours.

```bash
# WORKDIR is the path this run reported; quote it in case of spaces.
rm -rf "$WORKDIR"
```

Equivalently, if you still have the metadata file:

```bash
"$PYTHON_BIN" - "$WORKDIR_METADATA_JSON" <<'PY'
import json
import shutil
import sys
from pathlib import Path

meta_path = Path(sys.argv[1])
workdir = json.loads(meta_path.read_text(encoding="utf-8")).get("workdir")
if workdir:
    shutil.rmtree(workdir, ignore_errors=True)
PY
```

Older copies of this file removed a single fixed `book_skill_work` directory. That path is
no longer used, so such a cleanup is now a harmless no-op rather than something that could
delete a concurrent run's output.

Then report to the user:

```
✅ Skill created: $SKILLS_HOME/<skill_name>/

📚 Book: <Full Title> — <Author>
📄 Pages: ~<N> | Chapters: <N>
🧭 Triage: <score>/100 → <verdict><if overridden: " (overridden from <verdict>)">
📥 Source: <archived to <path> | kept in inbox (not a library run)>

Files generated:
  SKILL.md         — core frameworks + index   (~X tokens)
  chapters/        — <N> chapter summaries     (~X tokens each, ~X total)
  glossary.md      — key terms                 (~X tokens)
  patterns.md      — techniques & patterns     (~X tokens)
  cheatsheet.md    — quick reference           (~X tokens)
  ─────────────────────────────────────────────────────
  Total skill size: ~X tokens (loaded on-demand, not all at once)

💡 Tip: check your agent's session cost/usage command to see actual token usage.

Usage:
  Ask for <skill_name>                  → load core frameworks
  Ask <skill_name> about <topic>        → find and explain a topic
  Ask <skill_name> for ch<N>            → dive into a specific chapter

Discoverable by: <only what is true for the chosen destination — see below>

Somewhere else?  mv ~/.agents/skills/<skill_name> <dest_root>/<skill_name> \
                   && ln -sfn <dest_root>/<skill_name> ~/.claude/skills/<skill_name>

Prompted for permission on every file? That is your host gating writes outside the
working directory. Say "save it in this project" and re-run to write inside it.

Reload (if your agent doesn't auto-detect new skills):
  GitHub Copilot CLI:  /skills reload
  Claude Code:         restart the session
  Amp:                 restart the session
  Hermes Agent:         start a new session
  OpenClaw:             openclaw skills list (new session if watcher disabled)
  OpenCode:             start a new session

Share this skill (optional):
  GitHub repo, installable on any host (Step 11):  say "publish"
  Copilot ecosystem:  gh skill publish $SKILLS_HOME/<skill_name>
```

Fill the "Discoverable by" line from `CLAUDE_STATUS` (the read-back result), never from the fact that `ln` ran — for `~/.agents/skills` installs:
- `linked` → "Copilot CLI, Amp, Codex (natively); Claude Code via symlink ~/.claude/skills/<skill_name>"
- `skipped-realdir` → "Copilot CLI, Amp, Codex (natively); **NOT** Claude Code — migrate the real directory at ~/.claude/skills/<skill_name> first"
- `copy` or `absent` → "Copilot CLI, Amp, Codex (natively); **NOT** Claude Code — the host could not create the symlink (a plain copy drifts on the next Update/Fold-in). Enable Developer Mode / create the link manually, or run the skill from ~/.agents/skills"
- Hermes Agent personal root → "Hermes Agent (from `$HERMES_HOME/skills/<category>`)"; no symlink claim, and no cross-agent claim, because the other hosts do not scan the Hermes root
- other host-private or project-local root → name only the host(s) that scan that root; no symlink claim

The "Somewhere else?" relocation line must be correct for the path actually taken, so it never breaks the symlink the run just created. **`mv` always targets the final skill directory, `<dest_root>/<skill_name>`, never `<dest_root>` itself.** `mv ~/.agents/skills/mybook ~/.copilot/skills && ln -sfn ~/.copilot/skills ~/.claude/skills/mybook` reads as valid and is not: the skill lands at `~/.copilot/skills/mybook` while the link points one level up at the root, so Claude Code resolves to a directory with no `SKILL.md`, which is the exact breakage this line exists to avoid. Substitute the destination the user actually named, so the printed command carries real paths and there is nothing left to interpret:
- `~/.agents/skills` + symlink → `mv ~/.agents/skills/<skill_name> <dest_root>/<skill_name> && ln -sfn <dest_root>/<skill_name> ~/.claude/skills/<skill_name>`
- host-private root, Hermes Agent included → `mv <src_root>/<skill_name> <dest_root>/<skill_name>`
- project-local root → `mv <project_root>/<skill_name> <dest_root>/<skill_name>`

The "Prompted for permission on every file?" line is the answer to a host that gates writes outside the working directory (any personal-scope root is out-of-cwd): the destination was announced above, and the one-line fix — re-run asking for the project-local root — sits next to it. Keep it only for personal-scope installs; drop it when the user already chose project-local.

---

## Step 11 — Publish the generated skill to GitHub (optional)

After the Step 10 report, offer once — and only if the Step 9.5 scan passed:

> "Want me to publish this skill to GitHub so any Agent Skills host can install it with `npx skills add`? (yes / skip)"

If the user declines, stop here. Requirements: the `gh` CLI, authenticated (check `gh auth status`). If `gh` is missing or unauthenticated, offer to set it up (`brew install gh` or https://cli.github.com, then `gh auth login`) — or use the no-`gh` path: the user creates an empty repo of the chosen visibility in the GitHub web UI, then you run the `git init`/`add`/`commit` commands below followed by `git remote add origin <repo-url> && git push -u origin main`. The visibility rule below applies to the web-created repo exactly the same.

**Visibility is a separate closed question — never inferred, never read out of an earlier answer.** Once the user accepts, ask it on its own and require a one-word reply:

> "Private or public repository? Reply with one word: `private` or `public`."

**The reply must *be* `public`, not merely contain it — a hard rule, not a suggestion.** Run `gh repo create` with `--private` in every case except one: the answer to the visibility question is the bare word `public`. Substring matching is forbidden, because a sentence about **the source's licence is not a visibility answer** — "it's public domain", "the book is public domain", "it's publicly available" all describe the material, not the repository, and all resolve to `--private`. A paraphrase, a sentence, an ambiguous answer, silence, or your own inference is NOT consent: re-ask once, and if the reply is still not the bare word, use `--private` and say so in the report. A private repo can be flipped public later; a public push of book-derived content cannot be un-published.

**Copyright gate — always apply before creating the repo:** chapter files are synthesized summaries, not raw text, but they still derive from the source material. Per the README's Copyright & fair use policy, skills generated from **third-party copyrighted books must stay private**; offer public only when the source is the user's own writing, openly licensed content, or material the user explicitly confirms they are authorized to redistribute publicly — and state which case applies. Having access to internal company material is not permission to disclose it: skills from internal docs stay **private** unless the user states they hold publication rights.

If accepted:

1. Add a repo `README.md` inside `$SKILLS_HOME/<skill_name>/` (never overwrite an existing file) — the skill title, a one-paragraph description ("Agent skill generated from *<Title>* by <Author> with [book-to-skill](https://github.com/virgiliojr94/book-to-skill)"), the install command from step 3 below, the file inventory, and a note that the content is synthesized summaries, not the book text.
2. Initialize the skill folder as a git repository and create the remote (default repo name `<skill_name>`; let the user override — some prefer a `<skill_name>-skill` suffix). **Nested-repo guard:** first check whether the skill folder already sits inside a git repository (`git -C "$SKILLS_HOME/<skill_name>" rev-parse --show-toplevel` — always the case for project-local roots like `.claude/skills/`). If it does, do NOT `git init` in place: the outer repository would record the folder as an embedded repo (gitlink, mode 160000) without `.gitmodules`, and fresh clones of the outer project would silently omit the skill. Instead, copy the skill folder to a scratch directory, run the commands below from the copy, and tell the user the published repo — not the project-local folder — is the remote's working copy.

```bash
cd "$SKILLS_HOME/<skill_name>"
git init -b main
git add -A
git commit -m "Add <skill_name> skill"
gh repo create <repo_name> --private --source . --push
# --private is the default; substitute --public ONLY under the visibility rule above
# (the visibility answer WAS the bare word "public" AND the copyright gate allows it)
```

3. Report the repo URL and the cross-host install command:

```
✅ Published: https://github.com/<owner>/<repo_name> (<private|public>)

Install on any Agent Skills host:
  npx skills add https://github.com/<owner>/<repo_name> --skill <skill_name>
```

   When the nested-repo guard fired and the repo was published from a scratch copy, add one line — that local folder never gains a remote, so the Update/Fold-in push offer will never appear for it:

```
⚠️  Published from a copy: <skill folder> sits inside another git repository, so it has
    no remote of its own. To publish a later update, re-run Step 11, or clone
    https://github.com/<owner>/<repo_name> and fold new material into the clone.
```

The root-level `SKILL.md` layout is exactly what the `skills` CLI detects, so the repo is installable as-is — no restructuring needed. Outside the nested-repo case the local folder stays the live install for this machine and is the remote's working copy, so later Update/Fold-in runs can commit and push their changes to the same remote.

---

## Fallback outputs (notes / RAG)

A `notes` or `rag` verdict is a route, not a refusal. Both packs are built from
the same extraction workdir:

```bash
# With a library config, let it decide the destination:
OUT=$("$PYTHON_BIN" "$SCRIPTS_DIR/library.py" path --route notes --slug <slug>)
"$PYTHON_BIN" "$SCRIPTS_DIR/packs.py" "$WORKDIR" --route notes --out "$OUT"

# Without one (or to choose a path yourself):
"$PYTHON_BIN" "$SCRIPTS_DIR/packs.py" "$WORKDIR" --route rag --out <dir>
```

Without a library config the defaults are `~/book-notes/<slug>/` and
`~/book-rag/<slug>/` (`BOOK_NOTES_HOME` / `BOOK_RAG_HOME` override the root).
Add `--force` to replace a non-empty directory and `--name` to set the
displayed title. After a successful pack, archive the source with
`library.py archive --route notes|rag --output "$OUT"` (Step 10).

**Notes pack** — `README.md` (metadata + chapter map), `notes.md` (one block per
section with claim / concept / rule / limit prompts), `quotes.md`, and
`questions.md`. The tool writes the skeleton only. Fill `notes.md` by reading
one section at a time; keep each line a claim, rule, or question. In
`quotes.md`, quote only when the wording matters — at most 25 words, always with
the section number. Never paste a paragraph.

**RAG pack** — `corpus/full_text.txt`, `chunks.jsonl` (stable `c0001` ids,
`section` metadata, ~1,200-character chunks with 150-character overlap),
`index.md` (section → chunk map and query instructions), and
`rag_metadata.json`. Query by grepping `chunks.jsonl` first, then read only the
matching records — do not load the whole corpus into context.

**Privacy.** The RAG pack contains the source text. It is for private retrieval
only: never publish it, commit it, or ship it with a skill. The notes pack can
contain short quotes and inherits the same rule.

After either pack is built, the extraction workdir is no longer needed; clean it
up with the Step 10 procedure. Do not run Steps 3–11.

---

## Update / Fold-in Workflow

When performing an Update/Fold-in operation on an existing skill at `$SKILLS_HOME/<skill_name>/`:

### 1. Read Existing Skill Structure
Read and parse the existing skill's files:
- Read `$SKILLS_HOME/<skill_name>/SKILL.md` to parse the existing **Chapter Index**, **Topic Index**, metadata (author, total chapters), and **Core Frameworks**.
- List all files in `$SKILLS_HOME/<skill_name>/chapters/` to find the highest chapter number (e.g. `ch12`).
- Read `$SKILLS_HOME/<skill_name>/glossary.md`, `$SKILLS_HOME/<skill_name>/patterns.md`, and `$SKILLS_HOME/<skill_name>/cheatsheet.md` to see what terms and frameworks are already indexed.

### 2. Match Content & Identify Revisions vs. Additions
Analyze the new extracted text in this run's `full_text.txt` (the `Text ->` path from the extraction output) to identify if the new content represents:
- **Updates/Revisions to existing chapters**: If a section of the new content directly updates or expands an existing chapter's topic, read the existing chapter file, merge the new details into it, and rewrite the file.
- **New additions**: If the content introduces new chapters, papers, or separate sections, create **new chapter summary files** under `chapters/`. Start numbering these files after the highest existing chapter number (e.g. if the existing chapters stop at `ch12`, create `ch13-*.md`, `ch14-*.md`, etc.).

### 3. Generate or Update Chapter Summary Files
For each new or revised chapter:
- Read the corresponding section of the extracted new text.
- Follow the formatting guidelines in **Step 7** to build the summary.
- Write/update the file in `$SKILLS_HOME/<skill_name>/chapters/`.

### 4. Merge Supporting Files
- **Merge glossary.md**:
  - Read the existing `$SKILLS_HOME/<skill_name>/glossary.md`.
  - Extract all new terms and definitions from the new content (Step 8 glossary guidelines).
  - Combine and alphabetize the list of existing and new terms.
  - If a term already exists, append the new chapter/source references to it (e.g. `**Term** — definition (Ch 4, Ch 13)`).
  - Rewrite `$SKILLS_HOME/<skill_name>/glossary.md` with the fully merged, alphabetized list.
- **Merge patterns.md**:
  - Read existing `$SKILLS_HOME/<skill_name>/patterns.md`.
  - Extract any new techniques, algorithms, or patterns from the new content.
  - Append the new patterns, ensuring consistent formatting, and keeping the total length concise (under 2,500 tokens).
- **Merge cheatsheet.md**:
  - Read existing `$SKILLS_HOME/<skill_name>/cheatsheet.md`.
  - Extract new comparison rules, decision tables, or parameter guides.
  - Integrate them cleanly into the cheatsheet structure.

### 5. Re-generate the Master SKILL.md
Update the master skill file `$SKILLS_HOME/<skill_name>/SKILL.md`:
- **Metadata**: Increment the chapter count, update the estimated page count, and add the new source names if appropriate. Update the `Generated` date to the current date.
- **Core Frameworks**: Fold in the most high-impact mental models or principles from the new content (ensuring the overall file remains under 4,000 tokens).
- **Chapter Index**: Append the new chapters to the index table, linking to the newly created files.
- **Topic Index**: Merge the new topics alphabetically. If an existing topic is also covered in the new chapters, append the new chapter links to its line (e.g. `- **Topic** → ch05, ch13`).

### 6. Scan, Cleanup, and Report
Once the files are successfully written and merged, run **Step 9.5**, then proceed to **Step 10** to perform cleanup and print a custom update report summarizing the newly added chapters, merged glossary terms, and updated indices. If the skill folder is a git repository with a remote (published via **Step 11**), offer to commit the update and push it.

---

## Quality Rules

1. **Extract structure, not summaries** — capture named frameworks, exact formulations, anti-patterns; not chapter recaps
2. **Preserve the author's precision** — "The 5 Whys" ≠ "ask why multiple times"; keep exact naming
3. **Density over completeness** — a 1,000-token summary beats a 10,000-token excerpt
4. **Practitioner voice** — write "Use X when Y", not "The book explains X"
5. **Front-load SKILL.md** — compaction keeps the first 5,000 tokens; most important content comes first
6. **Chapter files are on-demand** — they don't count against skill budget until loaded
7. **Never copy raw book text** — always synthesize, summarize, extract signal
8. **Topic index is critical** — it's how the agent navigates to the right chapter file
