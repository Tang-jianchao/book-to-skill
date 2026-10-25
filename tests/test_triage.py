"""Skill-fit triage: scoring, routing, and the CLI contract.

The scorer is a heuristic, so these tests pin the *decisions* that matter
(a framework-dense book can become a skill, a novel cannot) rather than exact
scores. Exact-score assertions would break on every calibration tweak while
telling us nothing about whether the route is still right.
"""

import json

from book_to_skill.triage import (
    NOTES_THRESHOLD,
    SKILL_LITE_THRESHOLD,
    SKILL_THRESHOLD,
    analyze_text,
    main,
    render_report,
)


def _technical_book(chapters: int = 20) -> str:
    parts = []
    for number in range(1, chapters + 1):
        parts.append(
            f"""## Chapter {number}: Designing for Failure

When to use: any service that crosses a network boundary. The principle is
that partial failure is the default, not the exception.

**The retry budget rule**: retry only idempotent calls, cap retries at three,
and use exponential backoff with jitter.

### Steps

1. Classify the call as safe or unsafe.
2. Set a timeout shorter than the caller's deadline.
3. Add a circuit breaker around the downstream dependency.
4. Emit a metric for every retry.

| Pattern | Use when | Trade-off |
|---|---|---|
| Retry | transient errors | amplifies load |
| Circuit breaker | sustained failure | rejects healthy calls |

Avoid retrying non-idempotent writes. Do not retry on 4xx. Never retry without
a deadline. The criterion is simple: if you cannot name the failure you are
retrying, do not retry.
"""
        )
    return "\n".join(parts)


def _narrative_book(chapters: int = 20) -> str:
    return "\n".join(
        f"""## Chapter {number}

"Where were you?" she said. "I waited by the river."

He said nothing. The rain had stopped, and the street was quiet.

"Later on," he said, "I thought about the story you told me. I thought about
the house, and the way the light fell through the window."

She looked at him. "You always do that," she said. "You always leave."

Suddenly the door opened. A man came in, shaking the snow from his coat.
"""
        for number in range(1, chapters + 1)
    )


def _metadata(**overrides):
    data = {
        "filename": "sample.epub",
        "format": "epub",
        "pages": 300,
        "chapters_detected": 20,
        "has_toc": True,
        "images_dropped": 0,
    }
    data.update(overrides)
    return data


def test_framework_dense_book_routes_to_skill():
    result = analyze_text(
        _technical_book(), _metadata(), reuse="high", decision="high"
    )
    assert result["verdict"] == "skill"
    assert result["route"] == "full-skill"
    assert result["score"] >= SKILL_THRESHOLD


def test_dialogue_heavy_book_never_routes_to_skill():
    result = analyze_text(
        _narrative_book(), _metadata(has_toc=False), reuse="high", decision="high"
    )
    assert result["verdict"] in {"notes", "rag"}
    assert result["score"] < SKILL_LITE_THRESHOLD + 10


def test_book_without_frameworks_routes_down_despite_structure():
    text = "\n".join(
        f"## Chapter {number}\n\nThe road was long and the sky was grey. " * 12
        for number in range(1, 21)
    )
    result = analyze_text(text, _metadata(), reuse="high", decision="high")
    assert result["verdict"] != "skill"


def test_low_reuse_caps_a_skill_route():
    result = analyze_text(
        _technical_book(), _metadata(), reuse="low", decision="low"
    )
    assert result["verdict"] == "notes"


def test_missing_demand_is_provisional_and_asks_both_questions():
    result = analyze_text(_technical_book(), _metadata())
    assert result["provisional"] is True
    assert len(result["questions"]) == 2
    assert result["confidence"] == "low"


def test_poetry_is_routed_to_retrieval():
    text = "\n".join(
        f"## {number}\n\nThe river is cold\nand the boat is gone\nI wait\n"
        for number in range(1, 21)
    )
    result = analyze_text(text, _metadata(), reuse="high", decision="high")
    assert result["route"] == "retrieval-corpus"


def test_too_short_text_is_blocked():
    result = analyze_text("A single paragraph.", {"pages": 1})
    assert result["verdict"] == "blocked"
    assert result["route"] == "re-extract"


def test_low_fidelity_extraction_is_blocked():
    text = "�" * 5_000 + "".join(f"## Chapter {n}\n\nBody text here.\n" for n in range(1, 10))
    result = analyze_text(text, _metadata(pages=300), reuse="high", decision="high")
    assert result["verdict"] == "blocked"
    assert "OCR" in result["recommendation"]


def test_extractor_chapter_count_wins_over_heading_scan():
    result = analyze_text(
        _technical_book(3),
        _metadata(chapters_detected=19),
        reuse="high",
        decision="high",
    )
    assert result["signals"]["chapters"] == 19
    assert result["signals"]["chapters_method"] == "extractor"


def test_score_is_deterministic():
    first = analyze_text(_technical_book(), _metadata(), reuse="high", decision="high")
    second = analyze_text(_technical_book(), _metadata(), reuse="high", decision="high")
    assert first == second


def test_cjk_and_latin_books_are_scored_on_the_same_scale():
    english = _technical_book()
    chinese = (
        "## 第一章 设计原则\n\n"
        "**重试预算规则**：只重试幂等调用，最多三次，并使用指数退避。\n\n"
        "### 步骤\n\n1. 判断调用是否安全。\n2. 设置短于调用方截止时间的超时。\n"
        "3. 在下游依赖外加上熔断器。\n4. 每次重试都记录指标。\n\n"
        "避免重试非幂等写入。不要重试 4xx。判断标准很简单：如果你说不出\n"
        "正在重试哪种失败，就不要重试。\n"
    ) * 20
    latin_result = analyze_text(english, _metadata(), reuse="high", decision="high")
    cjk_result = analyze_text(chinese, _metadata(), reuse="high", decision="high")
    assert latin_result["verdict"] == "skill"
    assert cjk_result["verdict"] == "skill"


def test_render_report_names_the_route_and_questions():
    result = analyze_text(_technical_book(), _metadata())
    rendered = render_report(result)
    assert "Skill-fit triage" in rendered
    assert "Route" in rendered
    assert result["recommendation"] in rendered
    assert "How often will you consult" in rendered


def test_cli_writes_the_report_beside_the_text(tmp_path):
    workdir = tmp_path / "work"
    workdir.mkdir()
    (workdir / "full_text.txt").write_text(_technical_book(), encoding="utf-8")
    (workdir / "metadata.json").write_text(json.dumps(_metadata()), encoding="utf-8")

    assert main([str(workdir), "--reuse", "high", "--decision", "high", "--quiet"]) == 0

    report = json.loads((workdir / "triage.json").read_text(encoding="utf-8"))
    assert report["verdict"] == "skill"
    assert report["inputs"] == {"reuse": "high", "decision": "high"}


def test_cli_reports_a_missing_text_file(tmp_path, capsys):
    assert main([str(tmp_path / "missing.txt")]) == 2
    assert "ERROR" in capsys.readouterr().err


def test_notes_threshold_is_below_skill_lite():
    assert NOTES_THRESHOLD < SKILL_LITE_THRESHOLD < SKILL_THRESHOLD
