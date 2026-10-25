"""Inbox management for a local ebook library.

book-to-skill normally converts one explicit path. A library run starts from a
folder instead: scan the inbox, subtract what has already been processed, and
archive the source once its output exists. Three facts make that possible:

* **The inbox** — flat folder of ebooks the user has not processed yet.
* **The archive** — where a source moves after a successful run, so the next
  scan cannot offer it again.
* **The ledger** — a small JSON file keyed by SHA-256. It records the route
  (skill / notes / RAG), the output paths, and the original location. Filenames
  are not identity: the same book can be re-downloaded with a different name,
  and two different editions can share one.

The ledger lives next to the inbox, not in this repository, and paths are
configured locally:

* ``--config PATH``, else ``BOOK_LIBRARY_CONFIG``, else
  ``~/.book-to-skill/library.json``, else generic ``~/ebook`` defaults.
* Environment overrides: ``BOOK_INBOX``, ``BOOK_DONE``, ``BOOK_SKILLS_HOME``,
  ``BOOK_BREAKDOWN_HOME``, ``BOOK_LEDGER``.

For libraries converted before this module existed, ``match`` compares an inbox
filename with the title in each generated ``SKILL.md``. That is a suggestion to
confirm, never an automatic archive: a wrong match would move the wrong book.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from book_to_skill.config import SUPPORTED_EXTENSIONS

CONFIG_VERSION = 1
LEDGER_VERSION = 1
CONFIG_ENV = "BOOK_LIBRARY_CONFIG"
DEFAULT_CONFIG_PATH = Path.home() / ".book-to-skill" / "library.json"
LEDGER_FILENAME = ".book-library.json"
MATCH_THRESHOLD = 0.62
MATCH_STRONG = 0.85
HASH_CHUNK = 1 << 20

ROUTES = ("skill", "skill-lite", "notes", "rag")


class LibraryError(Exception):
    """A configuration or filesystem problem the CLI should report, not trace."""


@dataclass
class LibraryConfig:
    inbox: Path
    done: Path
    skills: Path
    breakdown: Path
    ledger: Path
    source: str

    def to_dict(self) -> dict:
        return {
            "inbox": str(self.inbox),
            "done": str(self.done),
            "skills": str(self.skills),
            "breakdown": str(self.breakdown),
            "ledger": str(self.ledger),
            "config": self.source,
        }

    def output_path(self, route: str, slug: str) -> Path:
        if route in ("skill", "skill-lite"):
            return self.skills / slug
        if route == "notes":
            return self.breakdown / "notes" / slug
        if route == "rag":
            return self.breakdown / "rag" / slug
        raise LibraryError(f"unknown route '{route}' (expected one of {', '.join(ROUTES)})")


def _expand(value: str) -> Path:
    return Path(os.path.expanduser(os.path.expandvars(value)))


def _default_roots() -> dict:
    inbox = Path.home() / "ebook"
    return {
        "inbox": str(inbox),
        "done": str(inbox / "converted"),
        "skills": str(Path.home() / "book-to-skills"),
        "breakdown": str(Path.home() / "book-to-breakdown"),
        "ledger": str(inbox / LEDGER_FILENAME),
    }


def _config_path(explicit: str | None = None) -> Path | None:
    if explicit:
        return _expand(explicit)
    env = os.environ.get(CONFIG_ENV, "").strip()
    if env:
        return _expand(env)
    if DEFAULT_CONFIG_PATH.exists():
        return DEFAULT_CONFIG_PATH
    return None


def load_config(explicit: str | None = None) -> LibraryConfig:
    """Resolve roots from defaults, the config file, then environment.

    ``done`` and ``ledger`` follow ``inbox`` when they were not configured
    explicitly, so moving the inbox to another drive does not leave the archive
    pointing at the old one.
    """
    values = _default_roots()
    configured = set()
    path = _config_path(explicit)
    source = "defaults"
    if path is not None:
        if not path.exists():
            raise LibraryError(f"library config not found: {path}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise LibraryError(f"cannot read library config {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise LibraryError(f"library config {path} must be a JSON object")
        for key in ("inbox", "done", "skills", "breakdown", "ledger"):
            if key in data:
                values[key] = data[key]
                configured.add(key)
        source = str(path)

    env_keys = {
        "inbox": "BOOK_INBOX",
        "done": "BOOK_DONE",
        "skills": "BOOK_SKILLS_HOME",
        "breakdown": "BOOK_BREAKDOWN_HOME",
        "ledger": "BOOK_LEDGER",
    }
    for key, env_name in env_keys.items():
        raw = os.environ.get(env_name, "").strip()
        if raw:
            values[key] = raw
            configured.add(key)

    for key in values:
        if not isinstance(values[key], str) or not values[key].strip():
            raise LibraryError(f"library setting '{key}' must be a non-empty path")

    inbox = _expand(values["inbox"])
    if "done" not in configured:
        values["done"] = str(inbox / "converted")
    if "ledger" not in configured:
        values["ledger"] = str(inbox / LEDGER_FILENAME)

    return LibraryConfig(
        inbox=inbox,
        done=_expand(values["done"]),
        skills=_expand(values["skills"]),
        breakdown=_expand(values["breakdown"]),
        ledger=_expand(values["ledger"]),
        source=source,
    )


def write_config(
    path: Path,
    *,
    inbox: str,
    done: str | None,
    skills: str,
    breakdown: str,
    ledger: str | None,
    force: bool = False,
) -> Path:
    if path.exists() and not force:
        raise LibraryError(f"config already exists: {path} (pass --force to replace it)")
    payload = {
        "version": CONFIG_VERSION,
        "inbox": inbox,
        "done": done or str(_expand(inbox) / "converted"),
        "skills": skills,
        "breakdown": breakdown,
        "ledger": ledger or str(_expand(inbox) / LEDGER_FILENAME),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(HASH_CHUNK)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def load_ledger(path: Path) -> dict:
    if not path.exists():
        return {"version": LEDGER_VERSION, "entries": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LibraryError(f"cannot read ledger {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        raise LibraryError(f"ledger {path} is not a valid library ledger")
    return data


def save_ledger(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    os.replace(tmp, path)


def _ledger_index(ledger: dict) -> dict:
    return {entry.get("sha256"): entry for entry in ledger["entries"] if entry.get("sha256")}


def _iter_inbox(config: LibraryConfig):
    if not config.inbox.exists():
        raise LibraryError(f"inbox does not exist: {config.inbox}")
    if not config.inbox.is_dir():
        raise LibraryError(f"inbox is not a directory: {config.inbox}")
    done = config.done.resolve()
    for path in sorted(config.inbox.iterdir(), key=lambda item: item.name.lower()):
        if path.name.startswith("."):
            continue
        if path.is_dir():
            continue
        try:
            if path.resolve().is_relative_to(done):
                continue
        except OSError:
            pass
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        yield path


def _iter_archive(config: LibraryConfig):
    if not config.done.exists() or not config.done.is_dir():
        return
    for path in sorted(config.done.iterdir(), key=lambda item: item.name.lower()):
        if path.name.startswith(".") or not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        yield path


def _read_skill_identity(skill_md: Path) -> tuple[str, str]:
    """Return (title, slug) from a generated SKILL.md.

    The H1 is the human title; the frontmatter ``name`` is the slug. Neither is
    guaranteed, so a missing file simply yields empty strings and cannot match.
    """
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "", ""
    slug = ""
    match = re.search(r"^name:\s*[\"']?([^\"'\n]+)", text, re.MULTILINE)
    if match:
        slug = match.group(1).strip()
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip(), slug
    return "", slug


def skill_candidates(config: LibraryConfig) -> list[dict]:
    if not config.skills.exists() or not config.skills.is_dir():
        return []
    found = []
    for child in sorted(config.skills.iterdir(), key=lambda item: item.name.lower()):
        if not child.is_dir():
            continue
        skill_md = child / "SKILL.md"
        if not skill_md.is_file():
            continue
        title, name = _read_skill_identity(skill_md)
        found.append(
            {
                "slug": child.name,
                "name": name or child.name,
                "title": title,
                "path": str(child),
            }
        )
    return found


_PAREN = re.compile(r"\([^)]*\)|\[[^\]]*\]|（[^）]*）|【[^】]*】")
_ZLIB = re.compile(r"z-?library[^)]*", re.IGNORECASE)
_NON_WORD = re.compile(r"[^\w㐀-䶿一-鿿]+")
_CJK = re.compile(r"[㐀-䶿一-鿿]")


def _title_key(text: str) -> str:
    text = _PAREN.sub(" ", text)
    text = _ZLIB.sub(" ", text)
    text = _NON_WORD.sub("", text)
    return text.lower()


def _common_prefix(left: str, right: str) -> int:
    length = 0
    for a, b in zip(left, right):
        if a != b:
            break
        length += 1
    return length


def match_score(book_title: str, skill_title: str) -> float:
    book = _title_key(book_title)
    skill = _title_key(skill_title)
    if not book or not skill:
        return 0.0
    if book == skill:
        return 1.0
    if book in skill or skill in book:
        # Containment is how translated titles usually match: the ebook says
        # "反脆弱 (纳西姆...)" and the skill says "反脆弱：从无序中受益".
        return 0.95
    score = SequenceMatcher(None, book, skill).ratio()
    prefix = _common_prefix(book, skill)
    if prefix >= 6:
        # The subtitle usually diverges: "延迟满足：如何在等待中获得更多" vs
        # "延迟满足：如何用长期主义实现目标". Six shared CJK characters are a
        # stronger signal than the ratio of two long strings.
        score = max(score, 0.88)
    elif prefix >= 4 and _CJK.search(book[:prefix]):
        score = max(score, 0.75)
    elif prefix >= 8:
        score = max(score, 0.75)
    return score


def best_candidate(book_path: Path, candidates: list[dict]) -> dict | None:
    best = None
    best_score = 0.0
    for candidate in candidates:
        score = max(
            match_score(book_path.stem, candidate["title"]),
            match_score(book_path.stem, candidate["name"]),
        )
        if score > best_score:
            best, best_score = candidate, score
    if best is None or best_score < MATCH_THRESHOLD:
        return None
    return {
        "slug": best["slug"],
        "title": best["title"],
        "score": round(best_score, 3),
        "confidence": "high" if best_score >= MATCH_STRONG else "medium",
        "path": best["path"],
    }


def _item(path: Path, digest: str | None = None) -> dict:
    return {
        "name": path.name,
        "path": str(path),
        "format": path.suffix.lower().lstrip("."),
        "size": path.stat().st_size,
        "sha256": digest,
    }


def scan(config: LibraryConfig) -> dict:
    """List pending and already-processed sources.

    SHA-256 is the identity. A book that was renamed still matches its ledger
    entry, and a book that is not in the ledger but already has a similarly
    titled skill is shown with a candidate rather than silently skipped.
    """
    ledger = load_ledger(config.ledger)
    by_sha = _ledger_index(ledger)
    candidates = skill_candidates(config)

    pending = []
    converted = []
    for path in _iter_inbox(config):
        digest = sha256_file(path)
        entry = by_sha.get(digest)
        if entry is not None:
            item = _item(path, digest)
            item.update(
                {
                    "route": entry.get("route"),
                    "slug": entry.get("slug"),
                    "outputs": entry.get("outputs", []),
                    "converted_at": entry.get("converted_at"),
                    "archived_to": entry.get("archived_to"),
                }
            )
            converted.append(item)
        else:
            item = _item(path, digest)
            candidate = best_candidate(path, candidates)
            if candidate is not None:
                item["candidate"] = candidate
            pending.append(item)

    archived = []
    tracked_sha = set(by_sha)
    for path in _iter_archive(config):
        digest = sha256_file(path)
        item = _item(path, digest)
        item["tracked"] = digest in tracked_sha
        archived.append(item)

    return {
        "config": config.to_dict(),
        "pending": pending,
        "converted": converted,
        "archived": archived,
        "counts": {
            "pending": len(pending),
            "converted": len(converted),
            "archived": len(archived),
        },
    }


def _unique_path(path: Path) -> Path:
    counter = 2
    while True:
        candidate = path.with_name(f"{path.stem} ({counter}){path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def archive(
    config: LibraryConfig,
    source: Path,
    *,
    route: str,
    slug: str,
    outputs: list[str] | None = None,
    keep_source: bool = False,
) -> dict:
    """Move (or copy) a processed source into the archive and record it.

    ``route`` must be one of skill / skill-lite / notes / rag. An existing
    archive entry with the same SHA-256 wins over the filename: the same book
    under two names is one book. A different file with the same name gets a
    `` (2)`` suffix instead of overwriting.
    """
    if route not in ROUTES:
        raise LibraryError(f"unknown route '{route}' (expected one of {', '.join(ROUTES)})")
    source = source.expanduser()
    if not source.exists() or not source.is_file():
        raise LibraryError(f"source not found: {source}")
    if source.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise LibraryError(f"unsupported source format: {source.suffix}")
    if not slug or "/" in slug or "\\" in slug:
        raise LibraryError(f"invalid slug: {slug!r}")

    digest = sha256_file(source)
    ledger = load_ledger(config.ledger)
    by_sha = _ledger_index(ledger)

    entry = by_sha.get(digest)
    if entry is None:
        entry = {
            "sha256": digest,
            "name": source.name,
            "source": str(source),
            "route": route,
            "slug": slug,
            "outputs": [str(item) for item in (outputs or [])],
            "converted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        ledger["entries"].append(entry)
    else:
        entry["route"] = route
        entry["slug"] = slug
        entry["outputs"] = [str(item) for item in (outputs or entry.get("outputs", []))]
        entry["converted_at"] = entry.get("converted_at") or datetime.now(
            timezone.utc
        ).isoformat(timespec="seconds")

    archived_to = entry.get("archived_to")
    already_archived = False
    if archived_to:
        target = Path(archived_to)
        if target.exists() and target.is_file() and sha256_file(target) == digest:
            already_archived = True
    try:
        if source.resolve() == config.done.resolve():
            already_archived = True
        elif source.resolve().parent == config.done.resolve():
            already_archived = True
    except OSError:
        pass

    if already_archived:
        current = Path(archived_to) if archived_to else source
        entry["archived_to"] = str(current)
        save_ledger(config.ledger, ledger)
        return {
            "status": "already-archived",
            "archived_to": str(current),
            "entry": entry,
        }

    config.done.mkdir(parents=True, exist_ok=True)
    destination = config.done / source.name
    if destination.exists():
        if sha256_file(destination) == digest:
            entry["archived_to"] = str(destination)
            save_ledger(config.ledger, ledger)
            return {
                "status": "already-archived",
                "archived_to": str(destination),
                "entry": entry,
            }
        destination = _unique_path(destination)

    if keep_source:
        shutil.copy2(source, destination)
        status = "copied"
    else:
        shutil.move(str(source), str(destination))
        status = "moved"

    entry["archived_to"] = str(destination)
    save_ledger(config.ledger, ledger)
    return {"status": status, "archived_to": str(destination), "entry": entry}


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} GB"


def _print_paths(config: LibraryConfig) -> None:
    print("Library")
    print(f"  Inbox     : {config.inbox}")
    print(f"  Done      : {config.done}")
    print(f"  Skills    : {config.skills}")
    print(f"  Breakdown : {config.breakdown}")
    print(f"  Ledger    : {config.ledger}")
    print(f"  Config    : {config.source}")


def _print_scan(result: dict) -> None:
    config = result["config"]
    print("Library")
    print(f"  Inbox     : {config['inbox']}")
    print(f"  Done      : {config['done']}")
    print(f"  Skills    : {config['skills']}")
    print(f"  Breakdown : {config['breakdown']}")
    print(f"  Ledger    : {config['ledger']}")

    pending = result["pending"]
    print()
    print(f"Pending: {len(pending)}")
    for index, item in enumerate(pending, 1):
        candidate = item.get("candidate")
        hint = ""
        if candidate:
            hint = f"  [possible match: {candidate['slug']} — {candidate['confidence']}]"
        print(
            f"  {index:>2}. {item['name']}  "
            f"{_human_size(item['size'])}  {item['format']}{hint}"
        )

    converted = result["converted"]
    if converted:
        print()
        print(f"Converted but still in the inbox: {len(converted)}")
        for item in converted:
            print(
                f"  - {item['name']}  → {item.get('route') or '?'}:"
                f"{item.get('slug') or '?'}  (archive it to stop re-listing it)"
            )

    archived = result["archived"]
    if archived:
        untracked = [item for item in archived if not item.get("tracked")]
        print()
        print(f"Archive: {len(archived)} file(s), {len(untracked)} not in the ledger")
        for item in untracked:
            print(f"  - {item['name']}  (untracked; archive again or ignore)")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(
        prog="library.py",
        description="Scan an ebook inbox, match generated skills, and archive processed sources.",
    )
    parser.add_argument("--config", help="path to library.json (overrides BOOK_LIBRARY_CONFIG)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    show = subparsers.add_parser("show", help="print the resolved library paths")
    show.add_argument("--json", action="store_true")

    scan_parser = subparsers.add_parser("scan", help="list pending and processed sources")
    scan_parser.add_argument("--json", action="store_true")

    match_parser = subparsers.add_parser(
        "match", help="suggest SKILL.md titles for pending books (confirmation only)"
    )
    match_parser.add_argument("--json", action="store_true")

    path_parser = subparsers.add_parser(
        "path", help="print the output directory for a route and slug"
    )
    path_parser.add_argument("--route", required=True, choices=ROUTES)
    path_parser.add_argument("--slug", required=True)

    archive_parser = subparsers.add_parser(
        "archive", help="move a processed source into the archive and record it"
    )
    archive_parser.add_argument("source")
    archive_parser.add_argument("--route", required=True, choices=ROUTES)
    archive_parser.add_argument("--slug", required=True)
    archive_parser.add_argument(
        "--output", action="append", default=[], help="an output path to record (repeatable)"
    )
    archive_parser.add_argument(
        "--keep-source", action="store_true", help="copy instead of moving the source"
    )
    archive_parser.add_argument("--json", action="store_true")

    init_parser = subparsers.add_parser("init", help="write a library config file")
    init_parser.add_argument("--inbox", required=True)
    init_parser.add_argument("--done")
    init_parser.add_argument("--skills", required=True)
    init_parser.add_argument("--breakdown", required=True)
    init_parser.add_argument("--ledger")
    init_parser.add_argument("--path", help="where to write config (default: ~/.book-to-skill/library.json)")
    init_parser.add_argument("--force", action="store_true")
    init_parser.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    try:
        if args.command == "init":
            target = _expand(args.path) if args.path else DEFAULT_CONFIG_PATH
            written = write_config(
                target,
                inbox=args.inbox,
                done=args.done,
                skills=args.skills,
                breakdown=args.breakdown,
                ledger=args.ledger,
                force=args.force,
            )
            payload = {"status": "written", "config": str(written)}
            if args.json:
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            else:
                print(f"library config written to {written}")
            return 0

        config = load_config(args.config)

        if args.command == "show":
            if args.json:
                print(json.dumps(config.to_dict(), indent=2, ensure_ascii=False))
            else:
                _print_paths(config)
                print()
                print("  Routes: skill → skills/<slug> · notes → breakdown/notes/<slug> · rag → breakdown/rag/<slug>")
            return 0

        if args.command == "path":
            print(config.output_path(args.route, args.slug))
            return 0

        if args.command == "scan":
            result = scan(config)
            if args.json:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            else:
                _print_scan(result)
            return 0

        if args.command == "match":
            result = scan(config)
            matches = [
                {
                    "name": item["name"],
                    "path": item["path"],
                    "size": item["size"],
                    "candidate": item.get("candidate"),
                }
                for item in result["pending"]
            ]
            if args.json:
                print(json.dumps({"pending": matches}, indent=2, ensure_ascii=False))
            else:
                unmatched = 0
                for item in matches:
                    candidate = item["candidate"]
                    if candidate is None:
                        unmatched += 1
                        print(f"  ?  {item['name']}  (no skill title matched)")
                    else:
                        print(
                            f"  ✓  {item['name']}"
                            f"\n     → {candidate['slug']}  ({candidate['confidence']}, {candidate['score']:.2f})"
                        )
                print()
                print(f"{len(matches) - unmatched} matched, {unmatched} unmatched")
            return 0

        if args.command == "archive":
            result = archive(
                config,
                Path(args.source),
                route=args.route,
                slug=args.slug,
                outputs=args.output,
                keep_source=args.keep_source,
            )
            if args.json:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            elif result["status"] == "already-archived":
                print(f"already archived: {result['archived_to']}")
            else:
                print(f"{result['status']}: {args.source} → {result['archived_to']}")
                print(f"  route: {args.route} · slug: {args.slug}")
                print(f"  ledger: {config.ledger}")
            return 0

        parser.error("unknown command")
    except LibraryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0
