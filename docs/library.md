---
description: "Run book-to-skill as a library: scan an ebook inbox, skip sources already processed, route each book to a skill or a notes/RAG pack, and archive the source."
seo_title: "Library Mode - Scan an Ebook Inbox and Archive Processed Books"
---

# Library mode

By default you point book-to-skill at a file. A **library** run starts from an
inbox instead:

```
inbox/                      pending books
  book-a.pdf
  book-b.epub
  已转换skill/              archive (sources that produced an output)
  .book-library.json        ledger (sha256 → route, slug, outputs)

skills/<slug>/              generated skills
breakdown/notes/<slug>/     topic-notes packs
breakdown/rag/<slug>/       private retrieval corpora
```

A run scans the inbox, preprocesses the pending books, presents one table of
scores, evidence, and recommended plans, converts the books/plans you pick, and
moves each source into the archive. The next scan cannot offer that book again.
This is opt-in: without a config file, the converter behaves exactly as before.

## Configure

The config lives outside the repository, at `~/.book-to-skill/library.json`
(override with `--config PATH` or `BOOK_LIBRARY_CONFIG`):

```json
{
  "inbox": "~/ebook",
  "done": "~/ebook/已转换skill",
  "skills": "~/book-to-skills",
  "breakdown": "~/book-to-breakdown"
}
```

- `done` defaults to `<inbox>/converted`.
- `ledger` defaults to `<inbox>/.book-library.json`.
- `skills` and `breakdown` default to `~/book-to-skills` and
  `~/book-to-breakdown`.
- Environment overrides, applied after the file: `BOOK_INBOX`, `BOOK_DONE`,
  `BOOK_SKILLS_HOME`, `BOOK_BREAKDOWN_HOME`, `BOOK_LEDGER`.

Create it without hand-editing JSON:

```bash
python -m book_to_skill.library init \
  --inbox ~/ebook \
  --done ~/ebook/已转换skill \
  --skills ~/book-to-skills \
  --breakdown ~/book-to-breakdown
```

Add `--force` to replace an existing file.

## Commands

The examples use `python -m book_to_skill.library` (the installed package).
When book-to-skill runs from a deployed skill directory, use
`scripts/library.py` with the same arguments instead — the shim keeps
`__pycache__` out of the skill.

```bash
# Resolved paths and where they came from
python -m book_to_skill.library show
python -m book_to_skill.library show --json

# Pending books, books already recorded but still in the inbox, and the archive
python -m book_to_skill.library scan

# Suggested existing skill for each pending book (confirmation only)
python -m book_to_skill.library match

# Where a route's output belongs
python -m book_to_skill.library path --route notes --slug my-book

# Record a successful run: move the source and write the ledger entry
python -m book_to_skill.library archive ~/ebook/my-book.pdf \
  --route skill --slug my-book --output ~/book-to-skills/my-book
```

`archive` accepts `--route skill|skill-lite|notes|rag`. `skill` and
`skill-lite` write to `<skills>/<slug>/`; `notes` and `rag` write to
`<breakdown>/notes/<slug>/` and `<breakdown>/rag/<slug>/`. Use
`--keep-source` to copy the original instead of moving it. Use `--json` on any
command when another tool consumes the output.

## The ledger

The ledger is a small JSON file keyed by **SHA-256**, not by filename:

- Renaming or re-downloading a book does not make it pending again.
- The same file under two names is one entry.
- A different file with the same name archives as `name (2).ext`; it never
  overwrites an existing source.
- `scan` also reports books that are in the ledger but were never archived, so
  they can be moved without converting them again.

The ledger records the original path, archive path, route, slug, output paths,
and timestamp. It contains local paths, so keep it private like the rest of the
library.

## Books converted before library mode

If a book already has a skill but no ledger entry, it shows as pending with a
**candidate**. `match` compares the filename with the `# Title` line in each
`<skills>/<slug>/SKILL.md`:

```
✓ 反脆弱 (author) (z-library).epub
   → fan-cuiruo  (high, 0.95)
? some-book.pdf  (no skill title matched)
```

The candidate is a suggestion. Confirm the mapping before archiving — a wrong
match moves the wrong book. An empty skill directory never counts: only a
directory containing a readable `SKILL.md` is a candidate.

## Failure and privacy rules

- **Never archive after a failed or blocked run.** If extraction fails, triage
  returns `blocked`, the user aborts, or a write fails, the source stays in the
  inbox so the next scan offers it again.
- **Archive the route that actually ran**, not the one triage first suggested.
  An overridden verdict is recorded as the route that produced the output.
- **The RAG pack contains source text.** Keep it private; never publish it,
  commit it, or ship it with a skill. The ledger and notes packs inherit the
  same rule.
- **Move, don't delete.** The archive is the undo path. If a conversion turns
  out to be wrong, move the source back into the inbox; the ledger entry can be
  removed by hand.
