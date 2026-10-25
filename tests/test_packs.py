"""Fallback packs: notes skeleton and private RAG corpus."""

import hashlib
import json

from book_to_skill.packs import (
    build_notes_pack,
    build_rag_pack,
    main,
    slugify,
    split_sections,
)

CHAPTER = """## Chapter {number}: The Rule of Small Bets

The principle: when uncertainty is high, make many small, reversible bets.
A bet is small when the cost of being wrong is lower than the cost of learning.

### Steps

1. List the assumptions.
2. Rank them by the cost of being wrong.
3. Test the cheapest one first.

Avoid the big-bang launch. Never hide which assumption failed.
"""


def _text(chapters: int = 3) -> str:
    return "\n".join(CHAPTER.format(number=number) for number in range(1, chapters + 1))


def _metadata(**overrides):
    data = {
        "filename": "bets.epub",
        "source_file": "/books/bets.epub",
        "format": "epub",
        "pages": 120,
        "chars": 12_000,
    }
    data.update(overrides)
    return data


def test_split_sections_keeps_front_matter_and_chapters():
    text = "Title page\n\n" + _text(3)
    sections = split_sections(text)
    assert sections[0].title == "Front matter"
    assert [section.title for section in sections[1:]] == [
        "Chapter 1: The Rule of Small Bets",
        "Chapter 2: The Rule of Small Bets",
        "Chapter 3: The Rule of Small Bets",
    ]


def test_split_sections_rejects_a_concatenated_table_of_contents_line():
    """Extractors often join every ToC entry onto one line; that is not a heading."""
    text = (
        "目录\n"
        "第一章 开端 第二章 转折 第三章 结局\n\n"
        "第一章 开端\n\n正文一。\n\n"
        "第二章 转折\n\n正文二。\n"
    )
    titles = [section.title for section in split_sections(text)]
    assert titles == ["Front matter", "第一章 开端", "第二章 转折"]
    assert "正文一" in "\n".join(section.body for section in split_sections(text))


def test_notes_pack_creates_a_skeleton_not_a_summary(tmp_path):
    out = tmp_path / "notes"
    result = build_notes_pack(_text(3), _metadata(), out)

    assert result["sections"] == 3
    assert (out / "README.md").exists()
    assert (out / "notes.md").exists()
    assert (out / "quotes.md").exists()
    assert (out / "questions.md").exists()

    notes = (out / "notes.md").read_text(encoding="utf-8")
    assert "Chapter 1: The Rule of Small Bets" in notes
    assert "Core claim:" in notes
    # The skeleton must not smuggle source paragraphs into the notes file.
    assert "make many small, reversible bets" not in notes


def test_notes_pack_uses_chinese_prompts_for_chinese_source(tmp_path):
    out = tmp_path / "notes"
    text = "## 第一章 开端\n\n这是正文。\n\n## 第二章 转折\n\n这是正文。\n"
    build_notes_pack(text, _metadata(filename="书.epub"), out)
    notes = (out / "notes.md").read_text(encoding="utf-8")
    assert "核心主张" in notes
    assert "Core claim" not in notes


def test_rag_pack_chunks_are_bounded_and_cover_the_sections(tmp_path):
    out = tmp_path / "rag"
    result = build_rag_pack(_text(3), _metadata(), out, max_chars=400, overlap=60)

    assert result["chunks"] >= 3
    rows = [
        json.loads(line)
        for line in (out / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert all(0 < row["chars"] <= 400 + 60 for row in rows)
    assert [row["id"] for row in rows] == sorted(row["id"] for row in rows)
    joined = "\n".join(row["text"] for row in rows)
    assert "List the assumptions." in joined
    assert "Never hide which assumption failed." in joined


def test_rag_pack_copies_the_corpus_and_records_a_hash(tmp_path):
    out = tmp_path / "rag"
    text = _text(2)
    build_rag_pack(text, _metadata(), out)

    assert (out / "corpus" / "full_text.txt").read_text(encoding="utf-8") == text
    meta = json.loads((out / "rag_metadata.json").read_text(encoding="utf-8"))
    assert meta["private"] is True
    assert meta["sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_slugify_keeps_cjk_and_drops_path_separators():
    assert slugify("The Rule of Small Bets") == "the-rule-of-small-bets"
    assert slugify("小岛经济学：鱼、美元") == "小岛经济学-鱼-美元"
    assert "/" not in slugify("../../etc/passwd")


def test_cli_refuses_to_overwrite_without_force(tmp_path, capsys):
    workdir = tmp_path / "work"
    workdir.mkdir()
    (workdir / "full_text.txt").write_text(_text(2), encoding="utf-8")
    (workdir / "metadata.json").write_text(json.dumps(_metadata()), encoding="utf-8")
    out = tmp_path / "pack"
    out.mkdir()
    (out / "keep.txt").write_text("existing", encoding="utf-8")

    assert main([str(workdir), "--route", "notes", "--out", str(out)]) == 2
    assert "not empty" in capsys.readouterr().err
    assert (out / "keep.txt").read_text(encoding="utf-8") == "existing"


def test_cli_builds_a_notes_pack(tmp_path):
    workdir = tmp_path / "work"
    workdir.mkdir()
    (workdir / "full_text.txt").write_text(_text(2), encoding="utf-8")
    (workdir / "metadata.json").write_text(json.dumps(_metadata()), encoding="utf-8")
    out = tmp_path / "pack"

    assert main([str(workdir), "--route", "notes", "--out", str(out)]) == 0
    assert (out / "notes.md").exists()
