"""Library inbox: config resolution, scanning, legacy matching, and archiving."""

import json

import pytest

from book_to_skill import library


@pytest.fixture(autouse=True)
def _clean_library_env(monkeypatch):
    for name in (
        "BOOK_INBOX",
        "BOOK_DONE",
        "BOOK_SKILLS_HOME",
        "BOOK_BREAKDOWN_HOME",
        "BOOK_LEDGER",
        "BOOK_LIBRARY_CONFIG",
    ):
        monkeypatch.delenv(name, raising=False)


def _paths(tmp_path):
    inbox = tmp_path / "ebook"
    done = inbox / "converted"
    skills = tmp_path / "book-to-skills"
    breakdown = tmp_path / "book-to-breakdown"
    for path in (inbox, done, skills, breakdown):
        path.mkdir(parents=True, exist_ok=True)
    return inbox, done, skills, breakdown


def _config_file(tmp_path, *, inbox, skills, breakdown, **extra):
    data = {"inbox": str(inbox), "skills": str(skills), "breakdown": str(breakdown)}
    data.update(extra)
    path = tmp_path / "library.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def _book(folder, name, content=b"book"):
    path = folder / name
    path.write_bytes(content + name.encode("utf-8"))
    return path


def _config(tmp_path):
    inbox, done, skills, breakdown = _paths(tmp_path)
    path = _config_file(
        tmp_path, inbox=inbox, skills=skills, breakdown=breakdown
    )
    return library.load_config(str(path)), inbox, done, skills, breakdown


def test_config_derives_done_and_ledger_from_inbox(tmp_path):
    inbox, done, skills, breakdown = _paths(tmp_path)
    config = library.load_config(
        str(_config_file(tmp_path, inbox=inbox, skills=skills, breakdown=breakdown))
    )
    assert config.done == inbox / "converted"
    assert config.ledger == inbox / library.LEDGER_FILENAME
    assert config.source.endswith("library.json")


def test_env_inbox_moves_derived_archive(tmp_path, monkeypatch):
    inbox, _, skills, breakdown = _paths(tmp_path)
    other = tmp_path / "other-inbox"
    other.mkdir()
    monkeypatch.setenv("BOOK_INBOX", str(other))
    config = library.load_config(
        str(_config_file(tmp_path, inbox=inbox, skills=skills, breakdown=breakdown))
    )
    assert config.inbox == other
    assert config.done == other / "converted"
    assert config.ledger == other / library.LEDGER_FILENAME


def test_scan_skips_archive_dirs_hidden_and_unsupported_files(tmp_path):
    config, inbox, done, _, _ = _config(tmp_path)
    _book(inbox, "pending.epub")
    _book(done, "done.pdf")
    (inbox / ".hidden.pdf").write_bytes(b"x")
    (inbox / "cover.jpg").write_bytes(b"x")

    result = library.scan(config)

    assert [item["name"] for item in result["pending"]] == ["pending.epub"]
    assert [item["name"] for item in result["archived"]] == ["done.pdf"]


def test_scan_uses_ledger_hash_as_identity(tmp_path):
    config, inbox, done, _, _ = _config(tmp_path)
    original = _book(inbox, "first-name.pdf")
    digest = library.sha256_file(original)
    ledger = {
        "version": 1,
        "entries": [
            {
                "sha256": digest,
                "route": "skill",
                "slug": "first-skill",
                "outputs": [str(done / "first-skill")],
                "archived_to": str(done / "first-name.pdf"),
            }
        ],
    }
    (inbox / library.LEDGER_FILENAME).write_text(
        json.dumps(ledger), encoding="utf-8"
    )
    _book(inbox, "second-name.pdf")

    result = library.scan(config)

    assert [item["name"] for item in result["pending"]] == ["second-name.pdf"]
    assert [item["name"] for item in result["converted"]] == ["first-name.pdf"]
    assert result["converted"][0]["slug"] == "first-skill"


def test_scan_suggests_a_skill_by_title(tmp_path):
    config, inbox, _, skills, _ = _config(tmp_path)
    skill = skills / "fan-cuiruo"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: fan-cuiruo\n---\n\n# 反脆弱：从无序中受益\n", encoding="utf-8"
    )
    _book(inbox, "反脆弱 (纳西姆·尼古拉斯·塔勒布) (z-library.sk).epub")

    result = library.scan(config)

    candidate = result["pending"][0]["candidate"]
    assert candidate["slug"] == "fan-cuiruo"
    assert candidate["confidence"] == "high"


def test_title_match_survives_a_different_subtitle():
    score = library.match_score(
        "延迟满足：如何在等待中获得更多 (作者) (z-library.sk).pdf",
        "延迟满足：如何用长期主义实现目标",
    )
    assert score >= library.MATCH_THRESHOLD


def test_scan_ignores_empty_skill_directories(tmp_path):
    config, inbox, _, skills, _ = _config(tmp_path)
    (skills / "half-converted").mkdir()
    _book(inbox, "some-book.pdf")

    result = library.scan(config)

    assert "candidate" not in result["pending"][0]


def test_scan_keeps_books_without_a_title_match_pending(tmp_path):
    config, inbox, _, skills, _ = _config(tmp_path)
    skill = skills / "other"
    skill.mkdir()
    (skill / "SKILL.md").write_text("# Other Book\n", encoding="utf-8")
    _book(inbox, "completely-different.pdf")

    result = library.scan(config)

    assert "candidate" not in result["pending"][0]


def test_output_path_follows_route(tmp_path):
    config, _, _, skills, breakdown = _config(tmp_path)

    assert config.output_path("skill", "abc") == skills / "abc"
    assert config.output_path("skill-lite", "abc") == skills / "abc"
    assert config.output_path("notes", "abc") == breakdown / "notes" / "abc"
    assert config.output_path("rag", "abc") == breakdown / "rag" / "abc"
    with pytest.raises(library.LibraryError):
        config.output_path("unknown", "abc")


def test_archive_moves_source_and_writes_ledger(tmp_path):
    config, inbox, done, _, _ = _config(tmp_path)
    source = _book(inbox, "book.epub")
    digest = library.sha256_file(source)

    result = library.archive(
        config,
        source,
        route="skill",
        slug="book-slug",
        outputs=[str(config.skills / "book-slug")],
    )

    assert result["status"] == "moved"
    assert not source.exists()
    assert (done / "book.epub").exists()
    ledger = json.loads(config.ledger.read_text(encoding="utf-8"))
    entry = ledger["entries"][0]
    assert entry["sha256"] == digest
    assert entry["route"] == "skill"
    assert entry["slug"] == "book-slug"
    assert entry["outputs"] == [str(config.skills / "book-slug")]
    assert entry["archived_to"] == str(done / "book.epub")

    assert library.scan(config)["pending"] == []


def test_archive_with_keep_source_copies(tmp_path):
    config, inbox, done, _, _ = _config(tmp_path)
    source = _book(inbox, "book.pdf")

    result = library.archive(
        config, source, route="notes", slug="book", keep_source=True
    )

    assert result["status"] == "copied"
    assert source.exists()
    assert (done / "book.pdf").exists()


def test_archive_is_idempotent_by_hash(tmp_path):
    config, inbox, done, _, _ = _config(tmp_path)
    source = _book(inbox, "book.pdf", b"same")
    library.archive(config, source, route="skill", slug="book", keep_source=True)

    again = library.archive(
        config, source, route="skill", slug="book", keep_source=True
    )

    assert again["status"] == "already-archived"
    assert again["archived_to"] == str(done / "book.pdf")
    assert len(json.loads(config.ledger.read_text(encoding="utf-8"))["entries"]) == 1


def test_archive_does_not_overwrite_a_different_file(tmp_path):
    config, inbox, done, _, _ = _config(tmp_path)
    first = _book(inbox, "same.pdf", b"first")
    library.archive(config, first, route="skill", slug="first")
    second = _book(inbox, "same.pdf", b"second")

    result = library.archive(config, second, route="rag", slug="second")

    assert result["archived_to"].endswith("same (2).pdf")
    assert (done / "same.pdf").read_bytes() == b"first" + b"same.pdf"
    assert (done / "same (2).pdf").exists()


def test_archive_rejects_unknown_route(tmp_path):
    config, inbox, _, _, _ = _config(tmp_path)
    source = _book(inbox, "book.pdf")

    with pytest.raises(library.LibraryError):
        library.archive(config, source, route="unknown", slug="book")


def test_cli_scan_json(tmp_path, capsys):
    config, inbox, _, _, _ = _config(tmp_path)
    _book(inbox, "book.epub")

    code = library.main(["--config", config.source, "scan", "--json"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["pending"] == 1
    assert payload["config"]["inbox"] == str(inbox)


def test_cli_archive_json(tmp_path, capsys):
    config, inbox, _, _, _ = _config(tmp_path)
    source = _book(inbox, "book.epub")

    code = library.main(
        [
            "--config",
            config.source,
            "archive",
            str(source),
            "--route",
            "rag",
            "--slug",
            "book",
            "--output",
            str(config.breakdown / "rag" / "book"),
            "--json",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "moved"
    assert payload["entry"]["route"] == "rag"


def test_cli_match_lists_candidates(tmp_path, capsys):
    config, inbox, _, skills, _ = _config(tmp_path)
    skill = skills / "xiaodao"
    skill.mkdir()
    (skill / "SKILL.md").write_text("# 小岛经济学：鱼、美元和经济的故事\n", encoding="utf-8")
    _book(inbox, "小岛经济学：鱼、美元和经济的故事 (作者).pdf")

    code = library.main(["--config", config.source, "match"])

    assert code == 0
    output = capsys.readouterr().out
    assert "xiaodao" in output
    assert "1 matched, 0 unmatched" in output


def test_init_writes_a_usable_config(tmp_path):
    target = tmp_path / "config" / "library.json"

    code = library.main(
        [
            "init",
            "--inbox",
            str(tmp_path / "inbox"),
            "--skills",
            str(tmp_path / "skills"),
            "--breakdown",
            str(tmp_path / "breakdown"),
            "--path",
            str(target),
        ]
    )

    assert code == 0
    config = library.load_config(str(target))
    assert config.inbox == tmp_path / "inbox"
    assert config.done == tmp_path / "inbox" / "converted"
    assert config.ledger == tmp_path / "inbox" / library.LEDGER_FILENAME
