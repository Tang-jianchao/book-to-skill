"""Deterministic skill-fit triage for an extracted document.

Extraction is the cheap half of book-to-skill; generation is the expensive one.
This module reads the text the extractor already produced and answers one
question first: is this source worth compiling into an agent skill, or is it
better kept as topic notes or a retrieval corpus?

The score is a heuristic, not a verdict. It exists to start a two-minute
conversation before a long generation run:

    text signals  ->  a score and a route
    user answers  ->  the two signals the text cannot carry
                      (how often it is consulted, how directly it drives work)

Everything here is stdlib-only and deterministic: the same text and the same
answers always produce the same report, so a run can be reproduced from
``triage.json`` alone. The thresholds are documented in ``docs/triage.md``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TRIAGE_VERSION = 1
REPORT_FILENAME = "triage.json"

# Route thresholds on the 0-100 score. `FRAMEWORK_GATE` is a separate floor:
# a book full of structure words but no named frameworks still routes down.
SKILL_THRESHOLD = 65
SKILL_LITE_THRESHOLD = 48
NOTES_THRESHOLD = 32
FRAMEWORK_GATE = 45

# Weights sum to 100. `demand` is the only dimension the text cannot supply.
WEIGHTS = {
    "structure": 20,
    "frameworks": 25,
    "actionability": 20,
    "narrative_fit": 10,
    "fidelity": 10,
    "volume": 5,
    "demand": 10,
}

LEVELS = {"high": 100, "medium": 60, "unknown": 50, "low": 20}

# Sampling cap: a 2M-character book does not need to be scanned in full for
# density estimates, and scanning it in full makes triage noticeably slower
# than the extraction it follows. Head, middle and tail are sampled so a book
# whose front matter is unusually dense (or unusually empty) cannot decide the
# score alone.
SAMPLE_LIMIT = 300_000

_FRAMEWORK_TERMS = re.compile(
    r"(原则|定律|法则|模型|框架|方法论|方法|技巧|步骤|清单|判据|规则|策略|"
    r"反模式|陷阱|误区|权衡|阈值|决策树|心智模型|第一性原理|"
    r"principl\w*|frameworks?|mental models?|rule of thumb|heuristics?|"
    r"methodolog\w*|checklists?|anti-?patterns?|trade-?offs?|playbooks?|"
    r"criteri(?:on|a)|recipes?|patterns?)",
    re.IGNORECASE,
)

_ACTION_TERMS = re.compile(
    r"(应当|应该|必须|不要|避免|优先|选择|判断|评估|适用于|不适用于|"
    r"适用条件|判据|步骤|清单|操作|配置|安装|运行|检查|"
    r"\bshould\b|\bmust\b|\bavoid\b|\bnever\b|\bprefer\b|"
    r"\bchoose\b|\bwhen to use\b|\buse when\b|\bcriteri(?:on|a)\b|"
    r"\bdo not\b|\bstep \d|\bconfigure\b|\binstall\b|\brun\b|\bcheck\b)",
    re.IGNORECASE,
)

_CONDITIONALS = re.compile(
    r"(如果[^。！？\n]{0,40}(?:就|则|那么)|当[^。！？\n]{0,20}时|"
    r"\bif\b[^.\n]{0,80}\bthen\b)",
    re.IGNORECASE,
)

_DEFINITIONS = re.compile(
    r"(是指|指的是|定义为|意味着|本质上|换句话说|"
    r"\bis defined as\b|\brefers to\b|\bmeans\b)",
    re.IGNORECASE,
)

_STORY_CUES = re.compile(
    r"(有一天|从前|后来|接着|于是|突然|故事|讲述|他说|她说|问道|答道|"
    r"once upon|suddenly|later on|the story|he said|she said)",
    re.IGNORECASE,
)

_DIALOGUE_MARKS = re.compile(r"[“”「」『』]")
# English prose uses straight quotes, and so does code. Counting only quoted
# spans (rather than every `"`) keeps a code block from reading as dialogue.
_STRAIGHT_QUOTE_SPAN = re.compile(r'"[^"\n]{2,200}"')

_FIRST_PERSON = re.compile(r"(我们|我|\bI\b|\bwe\b|\bour\b|\bmy\b)")

_CJK = re.compile(r"[㐀-䶿一-鿿]")

_HEADING_LINE = re.compile(
    r"^\s{0,3}(?:"
    r"#{1,6}\s+\S"
    r"|(?:chapter|part|section)\s+(?:\d+|[ivxlcdm]+)\b"
    r"|第\s*[0-9一二三四五六七八九十百零〇]+\s*[章节篇部回]"
    r")",
    re.IGNORECASE | re.MULTILINE,
)

_BULLET_LINE = re.compile(r"^\s*(?:[-*•]|\d+[.)、])\s+", re.MULTILINE)
_BOLD_TERM = re.compile(r"\*\*[^*\n]{1,40}\*\*")
_TABLE_LINE = re.compile(r"^\s*\|.*\|", re.MULTILINE)
_NUMBERED_LINE = re.compile(r"^\s*\d+[.)、]\s+", re.MULTILINE)


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _per_10k(count: int, length: int) -> float:
    return 0.0 if length <= 0 else count * 10_000.0 / length


def _per_1k(count: int, length: int) -> float:
    return 0.0 if length <= 0 else count * 1_000.0 / length


def _sample_text(text: str, limit: int = SAMPLE_LIMIT) -> str:
    """Head + middle + tail, so one dense region cannot set the whole score."""
    if len(text) <= limit:
        return text
    window = limit // 3
    middle_start = max(window, len(text) // 2 - window // 2)
    return "\n".join(
        (text[:window], text[middle_start:middle_start + window], text[-window:])
    )


def _normalise_level(value: str) -> str:
    value = (value or "unknown").strip().lower()
    return value if value in LEVELS else "unknown"


def _count_headings(text: str, metadata: dict | None) -> tuple[int, str]:
    """Chapter count: prefer the extractor's structural detection."""
    if metadata:
        detected = metadata.get("chapters_detected")
        if isinstance(detected, int) and detected > 0:
            return detected, str(metadata.get("chapters_method") or "extractor")
    return len(_HEADING_LINE.findall(text)), "heading-scan"


def _score_structure(signals: dict) -> tuple[float, str]:
    chapters = signals["chapters"]
    if chapters >= 8:
        score = 80
    elif chapters >= 4:
        score = 65
    elif chapters >= 2:
        score = 45
    elif chapters == 1:
        score = 20
    else:
        score = 0
    if signals["has_toc"]:
        score += 15
    if 1_500 <= signals["avg_chapter_chars"] <= 60_000:
        score += 5
    score = _clamp(score)
    detail = f"{chapters} chapter(s) · ToC {'yes' if signals['has_toc'] else 'no'}"
    return score, detail


def _score_frameworks(signals: dict) -> tuple[float, str]:
    terms = signals["framework_terms_per_10k"]
    definitions = signals["definitions_per_10k"]
    bold = signals["bold_terms_per_10k"]
    numbered = signals["numbered_ratio"]
    score = _clamp(
        terms * 10 + definitions * 8 + bold * 8 + numbered * 100
    )
    detail = f"{terms:.1f} framework cues / 10k chars"
    return score, detail


def _score_actionability(signals: dict) -> tuple[float, str]:
    terms = signals["action_terms_per_10k"]
    conditionals = signals["conditionals_per_10k"]
    # CJK prose packs the same cue into fewer characters: one Chinese
    # character carries roughly what three Latin ones do. Normalising the
    # denominators keeps a Chinese and an English book on the same scale.
    cjk = signals["cjk_ratio"] > 0.3
    term_scale = 18.0 if cjk else 8.0
    conditional_scale = 8.0 if cjk else 3.0
    structure = (
        signals["table_ratio"]
        + signals["bullet_ratio"]
        + signals["numbered_ratio"]
    )
    score = _clamp(
        0.5 * min(100.0, terms / term_scale * 100)
        + 0.25 * min(100.0, conditionals / conditional_scale * 100)
        + 0.25 * min(100.0, structure * 300)
    )
    detail = f"{terms:.1f} decision cues / 10k chars"
    return score, detail


def _score_narrative_fit(signals: dict) -> tuple[float, str]:
    dialogue = signals["dialogue_pairs_per_1k"]
    story = signals["story_cues_per_10k"]
    short_lines = signals["short_line_ratio"]
    first_person = signals["first_person_per_1k"]
    narrative = (
        min(40.0, dialogue * 4)
        + min(30.0, story * 6)
        + min(30.0, short_lines * 40)
        + min(10.0, first_person * 2)
    )
    fit = _clamp(100 - narrative)
    detail = (
        "prose mode: framework-first"
        if fit >= 70
        else "prose mode: narrative-heavy"
        if fit >= 35
        else "prose mode: story/dialogue"
    )
    return fit, detail


def _score_fidelity(signals: dict) -> tuple[float, str]:
    score = 100.0
    score -= min(40.0, signals["replacement_ratio"] * 1000)
    score -= min(20.0, signals["control_ratio"] * 2000)
    chars_per_page = signals["chars_per_page"]
    if chars_per_page is not None:
        # A Chinese page holds far fewer characters than a Latin page at the
        # same information density, so the same threshold would call a healthy
        # CJK extraction "sparse".
        low, normal = (200, 400) if signals["cjk_ratio"] > 0.3 else (300, 600)
        if chars_per_page < low:
            score -= 30
        elif chars_per_page < normal:
            score -= 15
    pages = signals["pages"] or 0
    if pages and signals["images_dropped"] > pages * 0.5:
        score -= 15
    score = _clamp(score)
    detail = (
        f"{chars_per_page:.0f} chars/page"
        if chars_per_page is not None
        else "page count unavailable"
    )
    return score, detail


def _score_volume(signals: dict) -> tuple[float, str]:
    chars = signals["chars"]
    if chars < 3_000:
        score = 10
    elif chars < 15_000:
        score = 55
    elif chars <= 800_000:
        score = 100
    elif chars <= 1_500_000:
        score = 80
    else:
        score = 60
    detail = f"{chars:,} chars"
    return float(score), detail


def _score_demand(reuse: str, decision: str) -> tuple[float, str]:
    score = 0.6 * LEVELS[reuse] + 0.4 * LEVELS[decision]
    detail = f"reuse {reuse} · decision {decision}"
    return score, detail


def _verdict(score: float, subscores: dict, signals: dict, reuse: str, decision: str) -> tuple[str, list[str]]:
    reasons: list[str] = []

    if signals["chars"] < 800:
        return "blocked", ["extracted text is too short to judge — check the source"]
    if subscores["fidelity"] < 35:
        return "blocked", ["extraction quality is too low to synthesize from — OCR or re-extract first"]

    if score >= SKILL_THRESHOLD and subscores["frameworks"] >= FRAMEWORK_GATE:
        verdict = "skill"
    elif score >= SKILL_LITE_THRESHOLD:
        verdict = "skill-lite"
    elif score >= NOTES_THRESHOLD:
        verdict = "notes"
    else:
        verdict = "rag"

    # Verse and short-form text can look well-structured (many headings, many
    # sections) while containing no prose toolkit at all. Line shape is the
    # cheapest reliable signal for that.
    if (
        signals["short_line_ratio"] > 0.75
        and signals["avg_line_chars"] < 40
        # Wrapped prose also has short lines, especially in CJK PDFs. Verse
        # additionally lacks long paragraphs; without this check a Chinese
        # technical book wrapped at 35 characters would read as poetry.
        and signals["avg_paragraph_chars"] < 120
        # A framework-dense page of short lines is a checklist, not verse.
        and subscores["frameworks"] < 40
        and signals["chars"] > 1_000
    ):
        verdict = "rag"
        reasons.append("short-line / verse structure — no prose toolkit to compile")

    # Caps are deliberate and documented: each one is a case where the score
    # alone would over-promise.
    if verdict in ("skill", "skill-lite"):
        if signals["chapters"] < 2 and signals["chars"] > 30_000:
            verdict = "skill-lite"
            reasons.append("one detected section — chapter split is heading-only")
        if subscores["narrative_fit"] < 25 and subscores["frameworks"] < 70:
            verdict = "notes"
            reasons.append("story/dialogue dominates; a skill would flatten it")
        if signals["chars"] > 1_500_000:
            verdict = "skill-lite"
            reasons.append("very large source — a full pass is expensive; scope it first")

    if reuse == "low" or decision == "low":
        if verdict in ("skill", "skill-lite"):
            verdict = "notes"
            reasons.append("low reuse or background-only reading does not repay a skill")

    if verdict == "skill-lite" and subscores["narrative_fit"] < 20:
        verdict = "notes"
        reasons.append("narrative fit is too low for a chapter toolkit")

    if verdict == "skill-lite" and subscores["frameworks"] < 20:
        verdict = "notes"
        reasons.append("no named frameworks — structure alone is not a toolkit")

    return verdict, reasons


def _collect_warnings(signals: dict, subscores: dict) -> list[str]:
    warnings: list[str] = []
    if not signals["has_toc"]:
        warnings.append("no table of contents detected — chapter boundaries rely on heading scan")
    if signals["chapters"] <= 1 and signals["chars"] > 30_000:
        warnings.append("only one section in a long document — chapter detection may have failed")
    low_density = 200 if signals["cjk_ratio"] > 0.3 else 300
    if (
        signals["chars_per_page"] is not None
        and signals["chars_per_page"] < low_density
        and (signals["pages"] or 0) > 20
    ):
        warnings.append("low text density per page — check for scanned pages before generating")
    if signals["replacement_ratio"] > 0.002:
        warnings.append("replacement characters present — the extractor could not decode part of the text")
    if signals["pages"] and signals["images_dropped"] > signals["pages"] * 0.5:
        warnings.append("many images were dropped — if the value is visual, the text is incomplete")
    if subscores["narrative_fit"] < 40:
        warnings.append("narrative-heavy — expect a skill to lose the argument's texture; notes may serve better")
    if signals["chars"] > 1_500_000:
        warnings.append("very large source — consider a subset of chapters for the first pass")
    return warnings


def _collect_reasons(signals: dict, subscores: dict, verdict: str) -> list[str]:
    reasons: list[str] = []
    if subscores["structure"] >= 80:
        reasons.append(f"{signals['chapters']} chapters detected with a clear structure")
    if subscores["frameworks"] >= 60:
        reasons.append(f"{signals['framework_terms_per_10k']:.1f} framework cues per 10k chars")
    if subscores["actionability"] >= 60:
        reasons.append(f"{signals['action_terms_per_10k']:.1f} decision cues per 10k chars")
    if subscores["narrative_fit"] >= 70:
        reasons.append("mostly expository prose — cheap to structure")
    if subscores["fidelity"] >= 85 and signals["chars_per_page"]:
        reasons.append(f"clean extraction (~{signals['chars_per_page']:.0f} chars/page)")
    if signals["chars"] > 0:
        reasons.append(f"{signals['chars']:,} characters across {signals['pages'] or '?'} page(s)")

    if subscores["structure"] < 55:
        reasons.append("weak chapter structure — on-demand chapter files will be harder to bound")
    if subscores["frameworks"] < FRAMEWORK_GATE:
        reasons.append("few named frameworks — the skill would mostly restate prose")
    if subscores["actionability"] < 50:
        reasons.append("few decision rules — less to apply while working")
    if subscores["narrative_fit"] < 60:
        reasons.append(
            f"narrative signal: {signals['dialogue_pairs_per_1k']:.1f} quoted passages / 1k chars"
        )
    if verdict in ("notes", "rag"):
        reasons.append("the reusable part is the text, not a set of frameworks to re-apply")
    return reasons


def analyze_text(
    text: str,
    metadata: dict | None = None,
    *,
    reuse: str = "unknown",
    decision: str = "unknown",
) -> dict:
    """Score *text* and return a JSON-serialisable triage report."""
    reuse = _normalise_level(reuse)
    decision = _normalise_level(decision)

    sample = _sample_text(text)
    length = len(sample)
    lines = [line for line in sample.splitlines() if line.strip()]
    paragraphs = [p for p in re.split(r"\n\s*\n", sample) if p.strip()]

    chapters, chapters_method = _count_headings(sample, metadata)
    pages = (metadata or {}).get("pages")
    pages = int(pages) if isinstance(pages, int) and pages > 0 else None
    chars = len(text)

    dialogue_marks = (
        len(_DIALOGUE_MARKS.findall(sample))
        + 2 * len(_STRAIGHT_QUOTE_SPAN.findall(sample))
    )
    signals = {
        "chars": chars,
        "sampled_chars": length,
        "pages": pages,
        "chapters": chapters,
        "chapters_method": chapters_method,
        "has_toc": bool((metadata or {}).get("has_toc", False)),
        "avg_chapter_chars": round(chars / chapters) if chapters else chars,
        "chars_per_page": round(chars / pages, 1) if pages else None,
        "images_dropped": int((metadata or {}).get("images_dropped") or 0),
        "framework_terms_per_10k": round(
            _per_10k(len(_FRAMEWORK_TERMS.findall(sample)), length), 2
        ),
        "action_terms_per_10k": round(
            _per_10k(len(_ACTION_TERMS.findall(sample)), length), 2
        ),
        "conditionals_per_10k": round(
            _per_10k(len(_CONDITIONALS.findall(sample)), length), 2
        ),
        "definitions_per_10k": round(
            _per_10k(len(_DEFINITIONS.findall(sample)), length), 2
        ),
        "bold_terms_per_10k": round(
            _per_10k(len(_BOLD_TERM.findall(sample)), length), 2
        ),
        "story_cues_per_10k": round(
            _per_10k(len(_STORY_CUES.findall(sample)), length), 2
        ),
        "dialogue_pairs_per_1k": round(dialogue_marks / 2 / max(1, length) * 1000, 2),
        "first_person_per_1k": round(
            _per_1k(len(_FIRST_PERSON.findall(sample)), length), 2
        ),
        "numbered_ratio": round(len(_NUMBERED_LINE.findall(sample)) / max(1, len(lines)), 3),
        "bullet_ratio": round(len(_BULLET_LINE.findall(sample)) / max(1, len(lines)), 3),
        "table_ratio": round(len(_TABLE_LINE.findall(sample)) / max(1, len(lines)), 3),
        "short_line_ratio": round(
            sum(1 for line in lines if len(line.strip()) <= 25) / max(1, len(lines)), 3
        ),
        "avg_line_chars": round(
            sum(len(line.strip()) for line in lines) / max(1, len(lines)), 1
        ),
        "avg_paragraph_chars": round(
            sum(len(paragraph) for paragraph in paragraphs) / max(1, len(paragraphs)), 1
        ),
        "cjk_ratio": round(len(_CJK.findall(sample)) / max(1, length), 3),
        "replacement_ratio": round(sample.count("�") / max(1, length), 5),
        "control_ratio": round(
            sum(1 for ch in sample if ord(ch) < 32 and ch not in "\n\t\r\f")
            / max(1, length),
            5,
        ),
        "paragraphs": len(paragraphs),
        "lines": len(lines),
    }

    structure, structure_detail = _score_structure(signals)
    frameworks, frameworks_detail = _score_frameworks(signals)
    actionability, actionability_detail = _score_actionability(signals)
    narrative_fit, narrative_detail = _score_narrative_fit(signals)
    fidelity, fidelity_detail = _score_fidelity(signals)
    volume, volume_detail = _score_volume(signals)
    demand, demand_detail = _score_demand(reuse, decision)

    subscores = {
        "structure": round(structure, 1),
        "frameworks": round(frameworks, 1),
        "actionability": round(actionability, 1),
        "narrative_fit": round(narrative_fit, 1),
        "fidelity": round(fidelity, 1),
        "volume": round(volume, 1),
        "demand": round(demand, 1),
    }
    score = round(
        sum(subscores[name] * weight for name, weight in WEIGHTS.items()) / 100
    )
    verdict, cap_reasons = _verdict(score, subscores, signals, reuse, decision)

    route = {
        "skill": "full-skill",
        "skill-lite": "partial-skill",
        "notes": "topic-notes",
        "rag": "retrieval-corpus",
        "blocked": "re-extract",
    }[verdict]

    details = {
        "structure": structure_detail,
        "frameworks": frameworks_detail,
        "actionability": actionability_detail,
        "narrative_fit": narrative_detail,
        "fidelity": fidelity_detail,
        "volume": volume_detail,
        "demand": demand_detail,
    }

    distance = min(
        abs(score - SKILL_THRESHOLD),
        abs(score - SKILL_LITE_THRESHOLD),
        abs(score - NOTES_THRESHOLD),
    )
    if reuse == "unknown" or decision == "unknown" or metadata is None:
        confidence = "low"
    elif distance <= 4 or FRAMEWORK_GATE - 5 <= subscores["frameworks"] <= FRAMEWORK_GATE + 10:
        confidence = "medium"
    else:
        confidence = "high"

    recommendations = {
        "full-skill": "Build a full skill: SKILL.md + chapters/ + glossary + patterns + cheatsheet.",
        "partial-skill": "Build a partial skill: 3–6 chapters covering what you will actually use.",
        "topic-notes": "Keep as topic notes: chapter summaries, short attributed quotes, open questions.",
        "retrieval-corpus": "Keep as a retrieval corpus: chunk by heading and query it; do not synthesize a skill.",
        "re-extract": "Fix extraction first (OCR or a better parser); scoring this text would be noise.",
    }

    questions = []
    if reuse == "unknown":
        questions.append("How often will you consult this source? (high / medium / low)")
    if decision == "unknown":
        questions.append("Will it drive decisions or work, or is it background reading? (high / medium / low)")

    return {
        "triage_version": TRIAGE_VERSION,
        "verdict": verdict,
        "route": route,
        "score": score,
        "confidence": confidence,
        # A verdict computed without the two demand inputs is a first guess,
        # not a decision. The agent must ask before acting on it.
        "provisional": reuse == "unknown" or decision == "unknown",
        "thresholds": {
            "skill": SKILL_THRESHOLD,
            "skill_lite": SKILL_LITE_THRESHOLD,
            "notes": NOTES_THRESHOLD,
            "framework_gate": FRAMEWORK_GATE,
        },
        "subscores": subscores,
        "details": details,
        "signals": signals,
        "inputs": {"reuse": reuse, "decision": decision},
        "reasons": _collect_reasons(signals, subscores, verdict) + cap_reasons,
        "warnings": _collect_warnings(signals, subscores),
        "questions": questions,
        "recommendation": recommendations[route],
    }


def render_report(result: dict) -> str:
    """Human-readable report. Lines stay under ~100 chars for terminals."""
    label = {
        "full-skill": "SKILL",
        "partial-skill": "SKILL-LITE",
        "topic-notes": "NOTES",
        "retrieval-corpus": "RAG",
        "re-extract": "BLOCKED",
    }[result["route"]]
    provisional = " · provisional" if result.get("provisional") else ""
    lines = [
        f"Skill-fit triage — {result['score']}/100 · {label} "
        f"(confidence: {result['confidence']}{provisional})",
    ]
    for name, weight in WEIGHTS.items():
        lines.append(
            f"   {name:<14} {result['subscores'][name]:>5.1f}/{weight:<3} "
            f"{result['details'][name]}"
        )
    lines.append(f"   Route          {result['recommendation']}")
    if result["reasons"]:
        lines.append("   Why")
        for reason in result["reasons"][:6]:
            lines.append(f"     · {reason}")
    if result["warnings"]:
        lines.append("   Cautions")
        for warning in result["warnings"]:
            lines.append(f"     ! {warning}")
    if result["questions"]:
        lines.append("   Answer to sharpen the route")
        for question in result["questions"]:
            lines.append(f"     ? {question}")
    return "\n".join(lines)


def _read_inputs(path: Path, metadata_path: Path | None) -> tuple[str, dict | None]:
    if path.is_dir():
        text_path = path / "full_text.txt"
        if not text_path.exists():
            raise FileNotFoundError(f"no full_text.txt in {path}")
        metadata_path = metadata_path or (path / "metadata.json")
    else:
        text_path = path
        metadata_path = metadata_path or (text_path.parent / "metadata.json")
    text = text_path.read_text(encoding="utf-8", errors="replace")
    metadata = None
    if metadata_path and metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    return text, metadata


def main(argv: list[str] | None = None) -> int:
    # The report contains Chinese punctuation and em dashes; a Windows console
    # left on a legacy code page raises UnicodeEncodeError without this.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(
        prog="python -m book_to_skill.triage",
        description="Score an extracted document for skill-fit and recommend a route.",
    )
    parser.add_argument("path", type=Path, help="full_text.txt or the extraction workdir")
    parser.add_argument("--metadata", type=Path, default=None, help="metadata.json (default: beside the text)")
    parser.add_argument("--reuse", choices=sorted(LEVELS), default="unknown")
    parser.add_argument("--decision", choices=sorted(LEVELS), default="unknown")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--write", type=Path, default=None, help=f"write the JSON report (default: {REPORT_FILENAME} beside the text)")
    parser.add_argument("--no-write", action="store_true", help="do not write a JSON report")
    parser.add_argument("--quiet", action="store_true", help="do not print the human-readable report")
    args = parser.parse_args(argv)

    try:
        text, metadata = _read_inputs(args.path, args.metadata)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    result = analyze_text(text, metadata, reuse=args.reuse, decision=args.decision)

    if not args.no_write:
        target = args.write
        if target is None:
            base = args.path if args.path.is_dir() else args.path.parent
            target = base / REPORT_FILENAME
        try:
            target.write_text(
                json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except OSError as exc:
            print(f"WARNING: could not write {target}: {exc}", file=sys.stderr)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif not args.quiet:
        print(render_report(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
