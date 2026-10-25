"""Build the two fallback outputs of a triage run: notes and a RAG corpus.

A triage verdict of ``topic-notes`` or ``retrieval-corpus`` is not a dead end.
Both routes still need the extracted text, just not compiled into a skill:

* **notes** — a chapter skeleton the agent fills while reading, plus a place to
  keep short attributed quotes and open questions.
* **rag** — the full text copied into a private corpus, split into
  heading-bounded chunks, with a map the agent can query.

Only the deterministic half lives here. The notes skeleton is not a summary;
filling it is the agent's job, and it must quote at most a few words at a time.
The RAG pack does contain the source text: it is for private retrieval and must
never be published or committed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

NOTES_HOME_ENV = "BOOK_NOTES_HOME"
RAG_HOME_ENV = "BOOK_RAG_HOME"
CHUNK_CHARS = 1_200
CHUNK_OVERLAP = 150

_CJK = re.compile(r"[㐀-䶿一-鿿]")
_ATX_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
_NUMBERED_HEADING = re.compile(
    r"^\s*(?:chapter|part|section)\s+(?:\d+|[ivxlcdm]+)\b.*$"
    r"|^\s*第\s*[0-9一二三四五六七八九十百零〇]+\s*[章节篇部回].*$",
    re.IGNORECASE,
)
_SETEXT_UNDERLINE = re.compile(r"^\s*(?:={3,}|-{3,})\s*$")
_CHAPTER_MARKER = re.compile(
    r"第\s*[0-9一二三四五六七八九十百零〇]+\s*[章节篇部回]"
    r"|(?:chapter|part)\s+(?:\d+|[ivxlcdm]+)\b",
    re.IGNORECASE,
)


@dataclass
class Section:
    title: str
    body: str


def _write(path: Path, text: str) -> None:
    """Write UTF-8 with LF endings on every platform.

    The packs are meant to be diffable and hashable; a CRLF checkout on Windows
    would make the same source produce different bytes.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def slugify(value: str, fallback: str = "book") -> str:
    """Filename-safe slug that keeps CJK characters (they are valid in paths)."""
    value = value.strip().lower()
    value = re.sub(r"[^\w㐀-䶿一-鿿-]+", "-", value, flags=re.UNICODE)
    value = re.sub(r"-{2,}", "-", value).strip("-_")
    return (value[:60] or fallback).strip("-_")


def _looks_like_heading(line: str) -> bool:
    title = line.strip()
    if not title or len(title) > 120:
        return False
    # A table-of-contents line often arrives as several chapter titles joined
    # on one extracted line ("第一章 … 第二章 … 第三章 …"). That is a list of
    # headings, not one heading, and accepting it would swallow the whole ToC
    # into a single phantom section.
    if len(_CHAPTER_MARKER.findall(title)) > 1:
        return False
    if _ATX_HEADING.match(line):
        return True
    if _NUMBERED_HEADING.match(line):
        return len(title) <= 80
    # A sentence ending in punctuation is prose, not a title.
    return not re.search(r"[。！？.!?;；:：,，]$", title)


def split_sections(text: str) -> list[Section]:
    """Heading-bounded sections, best effort, with the front matter preserved.

    `detect_structure` in utils selects one chapter depth for the whole file.
    This splitter is deliberately simpler: it only needs boundaries for notes
    and chunks, not a perfect chapter map, so any heading-shaped line counts.
    """
    lines = text.splitlines()
    candidates: list[tuple[int, str, int]] = []
    for index, line in enumerate(lines):
        title = None
        level = 2
        atx = _ATX_HEADING.match(line)
        if atx:
            title = atx.group(1).strip()
            level = len(line) - len(line.lstrip()) - len(line.lstrip().lstrip("#"))
        elif _NUMBERED_HEADING.match(line) and _looks_like_heading(line):
            title = line.strip()
        elif (
            index + 1 < len(lines)
            and _looks_like_heading(line)
            and _SETEXT_UNDERLINE.match(lines[index + 1])
        ):
            title = line.strip()
        if title:
            candidates.append((index, title, level))

    # Split at the shallowest heading level that actually recurs. A book title
    # (one H1) above twenty H2 chapters should leave the title in front matter,
    # not turn it into a one-line section; an H3 inside a chapter is a topic,
    # not a chapter boundary.
    for level in sorted({candidate[2] for candidate in candidates}):
        at_level = [candidate for candidate in candidates if candidate[2] == level]
        if len(at_level) >= 2:
            candidates = at_level
            break
    marks: list[tuple[int, str]] = [(index, title) for index, title, _ in candidates]

    if len(marks) < 2:
        body = text.strip()
        return [Section("Full text", body)] if body else []

    sections: list[Section] = []
    first = marks[0][0]
    if first > 0 and "\n".join(lines[:first]).strip():
        sections.append(Section("Front matter", "\n".join(lines[:first]).strip()))
    for position, (line_index, title) in enumerate(marks):
        start = line_index
        # A setext title keeps its underline out of the body.
        if start + 1 < len(lines) and _SETEXT_UNDERLINE.match(lines[start + 1]):
            start += 1
        end = marks[position + 1][0] if position + 1 < len(marks) else len(lines)
        body = "\n".join(lines[start + 1:end]).strip()
        if body:
            sections.append(Section(title, body))
    return sections or [Section("Full text", text.strip())]


def _chunk_body(body: str, max_chars: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split on sentence boundaries, carrying a small overlap between chunks."""
    body = body.strip()
    if not body:
        return []
    if len(body) <= max_chars:
        return [body]

    pieces = re.split(r"(?<=[。！？；])|(?<=[.!?])\s+", body)
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if not piece:
            continue
        # A single sentence longer than the budget is hard-split; the alternative
        # is a chunk that no embedding model will accept.
        while len(piece) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(piece[:max_chars])
            piece = piece[max_chars:]
        if len(current) + len(piece) > max_chars and current:
            chunks.append(current)
            current = current[-overlap:] if overlap else ""
        current += piece
    if current.strip():
        chunks.append(current.strip())
    return [chunk for chunk in chunks if chunk.strip()]


def _read_input(path: Path, metadata_path: Path | None) -> tuple[str, dict]:
    if path.is_dir():
        text_path = path / "full_text.txt"
        if not text_path.exists():
            raise FileNotFoundError(f"no full_text.txt in {path}")
        metadata_path = metadata_path or (path / "metadata.json")
    else:
        text_path = path
        metadata_path = metadata_path or (text_path.parent / "metadata.json")
    text = text_path.read_text(encoding="utf-8", errors="replace")
    metadata: dict = {}
    if metadata_path and metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    return text, metadata


def _default_title(metadata: dict, name: str | None) -> str:
    if name:
        return name
    filename = str(metadata.get("filename") or "")
    if filename and filename != "multi-source":
        return Path(filename).stem
    source = str(metadata.get("source_file") or "")
    return Path(source).stem if source else "book"


def _privacy_note(source_text: str) -> str:
    return (
        "本文件由原始文本派生，仅供个人检索/笔记使用。请勿发布、提交到仓库或随 skill 分发。"
        if _CJK.search(source_text[:5_000])
        else "Derived from the source text for private notes/retrieval only. "
        "Do not publish, commit, or redistribute it with a skill."
    )


def build_notes_pack(
    text: str,
    metadata: dict,
    out_dir: Path,
    *,
    title: str | None = None,
) -> dict:
    sections = split_sections(text)
    display_title = _default_title(metadata, title)
    chinese = bool(_CJK.search(text[:5_000]))

    out_dir.mkdir(parents=True, exist_ok=True)

    rows = "\n".join(
        f"| {index} | {section.title} | {len(section.body):,} | |"
        for index, section in enumerate(sections, 1)
    )
    readme = f"""# {display_title} — reading notes

- Source: `{metadata.get('source_file', 'unknown')}`
- Format: {metadata.get('format', 'unknown')} · Pages: {metadata.get('pages', '?')} · Characters: {metadata.get('chars', len(text)):,}
- Sections: {len(sections)}

{_privacy_note(text)}

## Chapter map

| # | Section | Characters | Notes |
|---|---------|-----------:|-------|
{rows}

## How to fill this pack

1. Read one section at a time from the extraction workdir (`full_text.txt`).
2. Fill the matching block in `notes.md`. Keep every line a claim, rule, or
   question — not a summary of the plot or the argument.
3. Put a quote in `quotes.md` only when the wording matters, and keep it under
   25 words with the section number. Do not paste paragraphs.
4. Add anything you could not resolve to `questions.md`.

This pack is not a skill. It is deliberately lossy: the goal is to make the
source findable, not to replace it.
"""
    _write(out_dir / "README.md", readme)

    if chinese:
        prompts = (
            "- 核心主张：\n- 关键概念：\n- 可执行规则：\n"
            "- 反例 / 边界：\n- 与其他章节的连接：\n"
        )
        header = "# 笔记 Notes\n\n> 每节只写主张、规则和疑点；不要复述故事。\n"
        quotes_header = (
            "# 原文短引 Quotes\n\n"
            "> 只在措辞本身重要时记录。每条不超过 25 字，注明章节。不要整段抄录。\n"
        )
        questions_header = "# 待解决 Questions\n\n> 读完后仍然不确定、或需要外部资料验证的问题。\n"
    else:
        prompts = (
            "- Core claim:\n- Key concepts:\n- Actionable rules:\n"
            "- Counterexamples / limits:\n- Connects to:\n"
        )
        header = "# Notes\n\n> Claims, rules, and questions only — do not retell the story.\n"
        quotes_header = (
            "# Quotes\n\n"
            "> Only when the wording matters. 25 words maximum, with the section number. "
            "Never paste a paragraph.\n"
        )
        questions_header = "# Open questions\n\n> What remains unresolved or needs an external source.\n"

    notes = [header]
    quotes = [quotes_header]
    questions = [questions_header]
    for index, section in enumerate(sections, 1):
        notes.append(f"## {index}. {section.title}\n\n{prompts}")
        quotes.append(f"## {index}. {section.title}\n\n")
        questions.append(f"## {index}. {section.title}\n\n")
    _write(out_dir / "notes.md", "\n".join(notes))
    _write(out_dir / "quotes.md", "\n".join(quotes))
    _write(out_dir / "questions.md", "\n".join(questions))

    return {
        "route": "notes",
        "out_dir": str(out_dir),
        "sections": len(sections),
        "files": ["README.md", "notes.md", "quotes.md", "questions.md"],
    }


def build_rag_pack(
    text: str,
    metadata: dict,
    out_dir: Path,
    *,
    title: str | None = None,
    max_chars: int = CHUNK_CHARS,
    overlap: int = CHUNK_OVERLAP,
) -> dict:
    sections = split_sections(text)
    display_title = _default_title(metadata, title)

    corpus_dir = out_dir / "corpus"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    _write(corpus_dir / "full_text.txt", text)

    records: list[dict] = []
    map_rows: list[str] = []
    counter = 0
    for section_index, section in enumerate(sections, 1):
        chunk_ids: list[str] = []
        for chunk_index, chunk in enumerate(
            _chunk_body(section.body, max_chars, overlap), 1
        ):
            counter += 1
            chunk_id = f"c{counter:04d}"
            chunk_ids.append(chunk_id)
            records.append(
                {
                    "id": chunk_id,
                    "section": section.title,
                    "section_index": section_index,
                    "chunk_index": chunk_index,
                    "chars": len(chunk),
                    "text": chunk,
                }
            )
        if chunk_ids:
            map_rows.append(
                f"| {section_index} | {section.title} | {chunk_ids[0]}–{chunk_ids[-1]} | {len(chunk_ids)} |"
            )

    with (out_dir / "chunks.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    map_table = "\n".join(map_rows)
    index = f"""# {display_title} — retrieval index

- Source: `{metadata.get('source_file', 'unknown')}`
- Format: {metadata.get('format', 'unknown')} · Pages: {metadata.get('pages', '?')}
- Sections: {len(sections)} · Chunks: {len(records)}
- Chunking: ~{max_chars} characters, {overlap}-character overlap, split on sentence boundaries

{_privacy_note(text)}

## Section map

| # | Section | Chunks | Count |
|---|---------|--------|------:|
{map_table}

## How to query

Read `chunks.jsonl` one line at a time; each line is a JSON object with `id`,
`section`, and `text`. Retrieve by keyword first (grep), then read the matching
records. Do not load the whole file into context — that is the discovery-loop
tax this pack exists to avoid.

If the corpus is indexed by an embedding store, use `id` as the stable key and
keep `section` as metadata for filtering.
"""
    _write(out_dir / "index.md", index)
    _write(
        out_dir / "rag_metadata.json",
        json.dumps(
            {
                "title": display_title,
                "source": metadata.get("source_file"),
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "sections": len(sections),
                "chunks": len(records),
                "chunk_chars": max_chars,
                "chunk_overlap": overlap,
                "private": True,
            },
            indent=2,
            ensure_ascii=False,
        ),
    )

    return {
        "route": "rag",
        "out_dir": str(out_dir),
        "sections": len(sections),
        "chunks": len(records),
        "files": ["index.md", "chunks.jsonl", "rag_metadata.json", "corpus/full_text.txt"],
    }


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(
        prog="python -m book_to_skill.packs",
        description="Build a topic-notes pack or a private retrieval corpus.",
    )
    parser.add_argument("path", type=Path, help="full_text.txt or the extraction workdir")
    parser.add_argument("--route", choices=("notes", "rag"), required=True)
    parser.add_argument("--metadata", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None, help="output directory")
    parser.add_argument("--name", default=None, help="title shown in the pack")
    parser.add_argument("--force", action="store_true", help="write into a non-empty directory")
    args = parser.parse_args(argv)

    try:
        text, metadata = _read_input(args.path, args.metadata)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    slug = slugify(_default_title(metadata, args.name))
    if args.out is not None:
        out_dir = args.out
    else:
        home_env = NOTES_HOME_ENV if args.route == "notes" else RAG_HOME_ENV
        default_home = Path.home() / ("book-notes" if args.route == "notes" else "book-rag")
        out_dir = Path(os.environ.get(home_env) or default_home) / slug

    if out_dir.exists() and any(out_dir.iterdir()) and not args.force:
        print(
            f"ERROR: {out_dir} is not empty — pass --force to overwrite, "
            "or choose another --out.",
            file=sys.stderr,
        )
        return 2

    build = build_notes_pack if args.route == "notes" else build_rag_pack
    result = build(text, metadata, out_dir, title=args.name)
    print(f"{args.route} pack written to {result['out_dir']}")
    for name in result["files"]:
        print(f"  {name}")
    if args.route == "rag":
        print("  This pack contains source text — keep it private.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
