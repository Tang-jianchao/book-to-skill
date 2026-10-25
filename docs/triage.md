---
description: "Skill-fit triage: score a source before generating, and route it to a skill, topic notes, or a private retrieval corpus. Rubric, thresholds, and the two questions the text cannot answer."
seo_title: "Triage - Is This Book Worth an Agent Skill?"
---

# Triage: is this source worth a skill?

Extraction is cheap and deterministic. Generation is the expensive half — it
reads the whole source and writes a structured toolkit. Triage sits between
them and asks a narrower question first:

> **Is this source a toolkit to compile, or a text to keep?**

A novel can produce a beautiful skill file and still be a bad skill: there is no
framework to re-apply, so the "skill" is a book report that costs tokens on
every load. A 40-page runbook can produce a thin skill file and be an excellent
one. The distinction is not literary quality. It is **structure × reuse**.

Triage runs automatically at the end of extraction and writes `triage.json` in
the extraction workdir. The agent reads it, asks two questions, and only then
proceeds to generation.

```bash
# manual re-run with the two demand inputs
python -m book_to_skill.triage "$WORKDIR" --reuse high --decision high
```

## How the score is built

Seven dimensions, weights sum to 100. Every signal is computed from the
extracted text plus the extractor's `metadata.json`; nothing is model-judged.

| Dimension | Weight | What raises it |
|---|---:|---|
| **Structure** | 20 | chapters detected, table of contents, sane chapter length |
| **Frameworks** | 25 | named principles/models/rules, definitions, numbered methods, bold terms |
| **Actionability** | 20 | decision cues ("must", "avoid", "when to use", 步骤, 判据), conditionals, tables/lists |
| **Narrative fit** | 10 | inverse of dialogue, story connectors, first person, very short lines |
| **Fidelity** | 10 | clean extraction, plausible characters per page, few dropped images |
| **Volume** | 5 | enough text to bound chapters (15k–800k characters is the sweet spot) |
| **Demand** | 10 | how often you will consult it and how directly it drives work |

Text is sampled (head, middle, tail, 300k characters) so a 2M-character book
costs the same triage time as a 100k one. Chinese and Latin text are normalized
separately: a CJK page carries the same cues in far fewer characters.

### The two questions

`Demand` is the only dimension the text cannot supply. The agent asks:

1. **How often will you consult this source?** — weekly / occasionally / once
2. **Will it drive decisions or work, or is it background reading?** — yes / no

Without answers the report is marked `provisional` and confidence is `low`. That
is deliberate: a high score on a book you will open once is still a bad skill.

## Thresholds and routes

| Score | Verdict | Route | What happens |
|---:|---|---|---|
| ≥ 65 and frameworks ≥ 45 | `skill` | `full-skill` | Full conversion (SKILL.md + chapters + glossary + patterns + cheatsheet) |
| ≥ 48 | `skill-lite` | `partial-skill` | 3–6 chapters covering what you will actually use |
| ≥ 32 | `notes` | `topic-notes` | Topic-notes pack; no skill is generated |
| < 32 | `rag` | `retrieval-corpus` | Private retrieval corpus; query the text, do not synthesize it |
| any | `blocked` | `re-extract` | Fix extraction first (OCR, parser, wrong file) |

### Caps that override the score

A raw score can over-promise. These caps are deliberate and are reported in
`reasons`:

- **One section in a long document** → at most `skill-lite`; chapter bounds are
  heading-only and may be wrong.
- **Story/dialogue dominates and frameworks are weak** → `notes`.
- **Short-line/verse structure** (poetry, lyrics, some drama) → `rag`.
- **Very large source** (>1.5M characters) → `skill-lite`; scope a subset first.
- **Low reuse or background-only reading** → `notes`; a skill you never call is
  a cost, not an asset.
- **Extraction quality too low** (garbled text, almost no text per page) →
  `blocked`; scoring noise produces confident nonsense.

The agent may override a route only when the user explicitly says so, and the
override is recorded in the final report.

## Notes and RAG packs

The two fallback routes are not dead ends. Both are built from the same extracted
text:

```bash
# chapter skeleton + quote log + open questions
python -m book_to_skill.packs "$WORKDIR" --route notes

# heading-bounded chunks + a private corpus copy
python -m book_to_skill.packs "$WORKDIR" --route rag
```

Output defaults to `~/book-notes/<slug>/` and `~/book-rag/<slug>/`
(`BOOK_NOTES_HOME` / `BOOK_RAG_HOME` override the roots). Existing non-empty
directories are refused unless `--force` is passed.

**Notes pack** — `README.md` (chapter map), `notes.md` (one block per section
with claim / concept / rule / limit prompts), `quotes.md` (short quotes only),
`questions.md`. The skeleton is deliberately not a summary: filling it is the
agent's job, and the rules cap quotes at 25 words with attribution.

**RAG pack** — `corpus/full_text.txt`, `chunks.jsonl` (JSON Lines with stable
`c0001` ids, `section`, and `text`), `index.md` (section → chunk map and query
instructions), `rag_metadata.json` (source hash, chunking parameters,
`private: true`). Chunks are ~1,200 characters with a 150-character overlap and
split on sentence boundaries.

The RAG pack **contains the source text**. It is for private retrieval only:
never publish it, commit it, or ship it with a skill.

## The report

`triage.json` is versioned and stable enough to diff:

```json
{
  "triage_version": 1,
  "verdict": "skill-lite",
  "route": "partial-skill",
  "score": 58,
  "confidence": "medium",
  "provisional": false,
  "subscores": {"structure": 100.0, "frameworks": 42.0, "...": "..."},
  "signals": {"chars": 81361, "chapters": 19, "...": "..."},
  "inputs": {"reuse": "high", "decision": "medium"},
  "reasons": ["..."],
  "warnings": ["..."],
  "questions": [],
  "recommendation": "Build a partial skill: 3–6 chapters..."
}
```

Use `--json` to print it, `--write PATH` to place it elsewhere, `--no-write` to
skip the file, and `--quiet` to suppress the human-readable block. `--no-triage`
on the extractor skips the automatic run.

## Limits

- **It scores extractable structure, not truth or quality.** A well-structured
  bad book scores like a well-structured good one.
- **Chapter detection is the extractor's.** When it fails, triage warns and caps
  the route; it cannot recover the real chapter map.
- **Language heuristics are approximate.** Chinese, Japanese and Korean cue
  density is normalized, but a bilingual or unusually formatted book may land a
  few points off. The verdict is a starting point for a two-minute conversation,
  not a verdict on the book.
- **Tables, code, and images are counted, not understood.** A book whose value
  is in a figure per page will score low — correctly, because the text path
  cannot carry it.
