"""Tests for workspace tools."""

import hashlib
import json

import pytest
from pathlib import Path

import dataclaw_workspace.tools as workspace_tools
from dataclaw_workspace.config import WorkspaceConfig
from dataclaw_workspace.tools import (
    ws_list_files,
    ws_read_file,
    ws_write_file,
    ws_update_file,
    ws_exec,
    display_image,
    report_design_report,
    report_review_visuals,
    report_publish,
    _base_dir,
)

from dataclaw.providers.llm.provider import TextDeltaEvent, TurnCompleteEvent
import dataclaw.config.paths as paths


class _JSONLLM:
    """Minimal streaming LLM stub for the single-path creative report author."""

    def __init__(self, response):
        responses = response if isinstance(response, tuple) else (response,)
        self.responses = [item if isinstance(item, str) else json.dumps(item) for item in responses]
        self.calls = 0

    async def stream_turn(self, messages, *, system, tools, **kwargs):
        if self.calls >= len(self.responses):
            raise AssertionError("test LLM received more calls than configured responses")
        response = self.responses[self.calls]
        self.calls += 1
        yield TextDeltaEvent(text=response)
        yield TurnCompleteEvent()


def _authored_html(*, title: str = "Customer intervention brief", claim: str | None = None) -> str:
    claim = claim or "The earliest customer window deserves the first intervention review."
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <style>
    :root{{--dc-ink:#172033;--dc-muted:#526079;--dc-surface:#ffffff;--accent:#d84a2f}}
    body{{margin:0;background:#f4efe8;color:var(--dc-ink);font:17px/1.6 Georgia,serif}}
    main{{max-width:72rem;margin:auto;padding:4rem 2rem}} figure{{margin:3rem 0}}
  </style>
</head>
<body>
  <main data-source="src-finding-1">
    <header><p>Report · editorial evidence brief</p><h1>{title}</h1></header>
    <section data-evidence="ev-1">
      <h2>Where to begin</h2>
      <p id="claim-1">{claim}</p>
      <figure data-evidence="ev-1">
        <svg viewBox="0 0 400 120" role="img" aria-label="Evidence emphasis">
          <path d="M10 100 C90 80 170 85 240 45 S340 25 390 12" fill="none" stroke="#d84a2f" stroke-width="8"/>
        </svg>
        <figcaption>The visual emphasis accompanies the cited completed finding.</figcaption>
      </figure>
    </section>
  </main>
  <script type="application/json" data-dc-author-coverage>{{"omitted":[]}}</script>
</body>
</html>'''


def _creative_llm():
    """A stub author that returns a valid single-finding authored document."""
    return _JSONLLM((_authored_html(), {"status": "pass", "findings": []}))


@pytest.fixture(autouse=True)
def tmp_workspaces(tmp_path, monkeypatch):
    ws_dir = tmp_path / "workspaces"
    ws_dir.mkdir()
    monkeypatch.setattr(paths, "DATACLAW_HOME", tmp_path)
    return ws_dir


@pytest.fixture
def cfg():
    return WorkspaceConfig()


@pytest.mark.asyncio
async def test_write_and_read(cfg):
    result = await ws_write_file(cfg=cfg, path="hello.txt", content="Hello world\nLine 2\n")
    assert result["created"] is True
    assert result["size"] > 0

    result = await ws_read_file(cfg=cfg, path="hello.txt")
    assert result["content"] == "Hello world\nLine 2\n"
    assert result["total_lines"] == 2


@pytest.mark.asyncio
async def test_read_with_offset_limit(cfg):
    await ws_write_file(cfg=cfg, path="lines.txt", content="a\nb\nc\nd\ne\n")
    result = await ws_read_file(cfg=cfg, path="lines.txt", offset=1, limit=2)
    assert result["lines_returned"] == 2
    assert result["content"] == "b\nc\n"


@pytest.mark.asyncio
async def test_read_too_large(cfg):
    cfg.max_read_bytes = 10
    await ws_write_file(cfg=cfg, path="big.txt", content="x" * 100)
    with pytest.raises(ValueError, match="too large"):
        await ws_read_file(cfg=cfg, path="big.txt")


@pytest.mark.asyncio
async def test_write_too_large(cfg):
    cfg.max_write_bytes = 10
    with pytest.raises(ValueError, match="too large"):
        await ws_write_file(cfg=cfg, path="big.txt", content="x" * 100)


@pytest.mark.asyncio
async def test_list_files(cfg):
    await ws_write_file(cfg=cfg, path="a.txt", content="a")
    await ws_write_file(cfg=cfg, path="b.txt", content="b")
    result = await ws_list_files(cfg=cfg)
    names = {e["name"] for e in result["entries"]}
    assert "a.txt" in names
    assert "b.txt" in names


@pytest.mark.asyncio
async def test_list_truncation(cfg):
    cfg.max_list_entries = 2
    for i in range(5):
        await ws_write_file(cfg=cfg, path=f"file{i}.txt", content=str(i))
    result = await ws_list_files(cfg=cfg)
    assert result["truncated"] is True
    assert len(result["entries"]) == 2


@pytest.mark.asyncio
async def test_update_file(cfg):
    await ws_write_file(cfg=cfg, path="code.py", content="x = 1\ny = 2\n")
    result = await ws_update_file(cfg=cfg, path="code.py", old_string="x = 1", new_string="x = 42")
    assert result["replacements"] == 1
    assert "x = 42" in result["diff"]

    read = await ws_read_file(cfg=cfg, path="code.py")
    assert "x = 42" in read["content"]


@pytest.mark.asyncio
async def test_update_file_not_found(cfg):
    with pytest.raises(ValueError, match="not found"):
        await ws_update_file(cfg=cfg, path="nope.txt", old_string="a", new_string="b")


@pytest.mark.asyncio
async def test_update_string_not_found(cfg):
    await ws_write_file(cfg=cfg, path="f.txt", content="hello")
    with pytest.raises(ValueError, match="old_string not found"):
        await ws_update_file(cfg=cfg, path="f.txt", old_string="nope", new_string="x")


@pytest.mark.asyncio
async def test_exec(cfg):
    result = await ws_exec(cfg=cfg, command="echo hello")
    assert result["exit_code"] == 0
    assert "hello" in result["stdout"]
    assert result["timed_out"] is False


@pytest.mark.asyncio
async def test_exec_timeout(cfg):
    cfg.exec_timeout_max = 1
    result = await ws_exec(cfg=cfg, command="sleep 10", timeout=1)
    assert result["timed_out"] is True


@pytest.mark.asyncio
async def test_path_traversal_blocked(cfg):
    with pytest.raises(ValueError, match="inside workspace"):
        await ws_read_file(cfg=cfg, path="../../etc/passwd")


@pytest.mark.asyncio
async def test_display_image(cfg, tmp_path):
    # Create a fake image file in the workspace
    base = _base_dir("default")
    img = base / "chart.png"
    img.write_bytes(b"fake png data")

    result = await display_image(cfg=cfg, path="chart.png", caption="A chart")
    assert result["displayed"] is True
    assert result["caption"] == "A chart"


@pytest.mark.asyncio
async def test_display_image_not_found(cfg):
    with pytest.raises(ValueError, match="not found"):
        await display_image(cfg=cfg, path="nope.png")


@pytest.mark.asyncio
async def test_display_image_bad_format(cfg):
    base = _base_dir("default")
    (base / "file.txt").write_text("not an image")
    with pytest.raises(ValueError, match="Unsupported"):
        await display_image(cfg=cfg, path="file.txt")


def test_visual_review_is_explicit_and_declared_requirement_cannot_be_disabled():
    storyboard = {"presentation": {"mode": "handcrafted"}, "source_context": {"requirements": {}}}
    assert workspace_tools._visual_review_required(storyboard, False) is False
    required = {
        "presentation": {"mode": "handcrafted"},
        "source_context": {"requirements": {"publication": {"require_visual_review": True}}},
    }
    assert workspace_tools._visual_review_required(required, False) is True


@pytest.mark.asyncio
async def test_report_publish_regates_and_writes_receipt(cfg):
    designed = await report_design_report(
        cfg=cfg,
        llm=_creative_llm(),
        report_goal="Explain the one decision-changing finding.",
        report_path="reports/publishable.html",
        storyboard_path="reports/publishable.storyboard.json",
        insights=[
            {
                "title": "Retention improved",
                "detail": "The retained cohort rose after the onboarding change.",
                "finding_id": "finding-retention",
            }
        ],
    )

    published = await report_publish(
        cfg=cfg,
        report_path="reports/publishable.html",
        storyboard_path="reports/publishable.storyboard.json",
        receipt_path="reports/publishable.receipt.json",
    )

    receipt = json.loads(Path(published["receipt_path"]).read_text())
    recipe = json.loads(Path(designed["recipe_path"]).read_text())
    assert designed["quality"]["status"] == "pass"
    assert published["type"] == "report_publish"
    assert published["published"] is True
    assert published["publication_status"] == "published"
    assert published["publish_required"] is False
    expected_status = "pass" if published["runtime_smoke"]["status"] == "passed" else "warn"
    assert published["quality"]["status"] == expected_status
    assert published["docx_export"] == {"requested": False, "status": "skipped"}
    assert published["runtime_smoke"]["status"] in {"passed", "skipped"}
    assert receipt["status"] == "published"
    assert receipt["quality"]["rubric_version"] == 15
    assert receipt["analytical_review"] == published["analytical_review"]
    assert published["analytical_review"]["status"] == "pass"
    assert receipt["runtime_smoke"] == published["runtime_smoke"]
    assert receipt["storyboard_path"] == published["storyboard_path"]
    assert published["recipe_path"] == designed["recipe_path"]
    assert receipt["regeneration_recipe"]["path"] == designed["recipe_path"]
    assert receipt["regeneration_recipe"]["status"] == "verified"
    assert recipe["recipe_schema"] == 1
    assert recipe["artifact"]["html_sha256"] == designed["html_sha256"]


@pytest.mark.asyncio
async def test_report_publish_records_missing_or_tampered_recipe_sidecar_as_advisory(cfg):
    designed = await report_design_report(
        cfg=cfg,
        llm=_creative_llm(),
        report_goal="Explain the decision-changing finding.",
        report_path="reports/recipe-integrity.html",
        storyboard_path="reports/recipe-integrity.storyboard.json",
        insights=[{"title": "Retention improved", "detail": "The retained cohort rose after the onboarding change.", "finding_id": "finding-recipe"}],
    )
    recipe_path = Path(designed["recipe_path"])
    recipe_path.unlink()

    published_missing = await report_publish(
        cfg=cfg,
        report_path="reports/recipe-integrity.html",
        storyboard_path="reports/recipe-integrity.storyboard.json",
        export_docx=False,
    )
    missing_receipt = json.loads(Path(published_missing["receipt_path"]).read_text())
    assert published_missing["published"] is True
    assert published_missing["recipe_path"] is None
    assert missing_receipt["regeneration_recipe"]["status"] == "missing"

    # A syntactically valid replacement still cannot change the source/plan
    # identity that the rendered report was designed from.
    recipe_path.write_text(json.dumps({
        "recipe_schema": 1,
        "renderer": "dataclaw_workspace.report_renderer.render_report_from_storyboard",
        "source_context_sha256": "different-source",
        "section_plan_sha256": "different-plan",
        "artifact": {
            "html_path": designed["html_path"],
            "storyboard_path": designed["storyboard_path"],
            "html_sha256": designed["html_sha256"],
        },
    }), encoding="utf-8")
    published_stale = await report_publish(
        cfg=cfg,
        report_path="reports/recipe-integrity.html",
        storyboard_path="reports/recipe-integrity.storyboard.json",
        export_docx=False,
    )
    stale_receipt = json.loads(Path(published_stale["receipt_path"]).read_text())
    assert published_stale["published"] is True
    assert stale_receipt["regeneration_recipe"]["status"] == "stale"


@pytest.mark.asyncio
async def test_report_publish_can_require_browser_visual_review_artifacts(cfg, monkeypatch):
    await report_design_report(
        cfg=cfg,
        llm=_creative_llm(),
        report_goal="Explain the decision-changing finding.",
        report_path="reports/final-visual-review.html",
        storyboard_path="reports/final-visual-review.storyboard.json",
        insights=[{"title": "Retention improved", "detail": "The retained cohort rose after the onboarding change.", "finding_id": "finding-visual-review"}],
        requirements={"publication": {"require_visual_review": True}},
    )

    async def skipped_smoke(_path):
        return {"status": "skipped", "reason": "Playwright unavailable"}

    monkeypatch.setattr(workspace_tools, "_run_report_runtime_smoke", skipped_smoke)
    with pytest.raises(ValueError, match="visual-review gate failed"):
        await report_publish(
            cfg=cfg,
            report_path="reports/final-visual-review.html",
            storyboard_path="reports/final-visual-review.storyboard.json",
            export_docx=False,
        )

    async def reviewed_smoke(_path):
        review_dir = _path.with_name(f"{_path.stem}.visual-review")
        review_dir.mkdir(parents=True, exist_ok=True)
        artifacts = []
        for name, kind, viewport in (
            ("desktop-full-page", "full_page", "desktop"),
            ("desktop-hero", "key_section", "desktop"),
        ):
            artifact_path = review_dir / f"{name}.png"
            artifact_path.write_bytes((f"screenshot:{name}".encode("utf-8")) * 128)
            artifacts.append({
                "kind": kind,
                "viewport": viewport,
                "path": str(artifact_path),
                "sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
            })
        return {
            "status": "passed",
            "checks": [],
            "screenshots": artifacts,
            "semantic_visual": {"visual_semantic_schema": 1, "status": "pass", "findings": []},
        }

    async def semantic_attention_smoke(_path):
        result = await reviewed_smoke(_path)
        result["semantic_visual"] = {
            "visual_semantic_schema": 1,
            "status": "attention_required",
            "findings": [{"id": "evidence_context_missing", "detail": "Visual has no context."}],
        }
        return result

    monkeypatch.setattr(workspace_tools, "_run_report_runtime_smoke", semantic_attention_smoke)
    with pytest.raises(ValueError, match="automated visual-semantic review did not pass"):
        await report_review_visuals(
            cfg=cfg,
            report_path="reports/final-visual-review.html",
            storyboard_path="reports/final-visual-review.storyboard.json",
            reviewer="Report reviewer",
            decision="approved",
            notes="Semantic review requires repair before approval.",
        )

    async def outside_review_dir_smoke(_path):
        result = await reviewed_smoke(_path)
        artifact = result["screenshots"][0]
        artifact["path"] = str(_path)
        artifact["sha256"] = hashlib.sha256(_path.read_bytes()).hexdigest()
        return result

    monkeypatch.setattr(workspace_tools, "_run_report_runtime_smoke", outside_review_dir_smoke)
    with pytest.raises(ValueError, match="outside the report review directory"):
        await report_review_visuals(
            cfg=cfg,
            report_path="reports/final-visual-review.html",
            storyboard_path="reports/final-visual-review.storyboard.json",
            reviewer="Report reviewer",
            decision="approved",
            notes="Review artifacts must remain bound to the report review directory.",
        )

    monkeypatch.setattr(workspace_tools, "_run_report_runtime_smoke", reviewed_smoke)
    reviewed = await report_review_visuals(
        cfg=cfg,
        report_path="reports/final-visual-review.html",
        storyboard_path="reports/final-visual-review.storyboard.json",
        reviewer="Report reviewer",
        decision="approved",
        notes="Desktop/webview hierarchy, spacing, and chart framing are reader-ready.",
    )
    assert reviewed["approved"] is True

    # An approved review is reusable only for exactly unchanged HTML and image
    # evidence. A later environment without Playwright is recorded as skipped,
    # rather than pretending the browser check passed again.
    monkeypatch.setattr(workspace_tools, "_run_report_runtime_smoke", skipped_smoke)
    published = await report_publish(
        cfg=cfg,
        report_path="reports/final-visual-review.html",
        storyboard_path="reports/final-visual-review.storyboard.json",
        export_docx=False,
    )
    assert published["visual_review"]["required"] is True
    assert published["visual_review"]["status"] == "approved"
    assert published["visual_review"]["reviewer"] == "Report reviewer"

    reviewed_artifact = Path(reviewed["runtime_smoke"]["screenshots"][0]["path"])
    reviewed_artifact.write_bytes(b"changed after approval")
    with pytest.raises(ValueError, match="reviewed screenshot is missing or changed"):
        await report_publish(
            cfg=cfg,
            report_path="reports/final-visual-review.html",
            storyboard_path="reports/final-visual-review.storyboard.json",
            export_docx=False,
        )


@pytest.mark.asyncio
async def test_report_publish_blocks_missing_required_display_facts(cfg):
    await report_design_report(
        cfg=cfg,
        llm=_creative_llm(),
        report_goal="Explain the decision-changing finding.",
        report_path="reports/required-display-facts.html",
        storyboard_path="reports/required-display-facts.storyboard.json",
        insights=[{"title": "Retention improved", "detail": "The retained cohort rose after the onboarding change.", "finding_id": "finding-display-facts"}],
        requirements={"presentation": {"require_display_facts": True}},
    )

    with pytest.raises(ValueError, match="authoring gate failed"):
        await report_publish(
            cfg=cfg,
            report_path="reports/required-display-facts.html",
            storyboard_path="reports/required-display-facts.storyboard.json",
            export_docx=False,
        )


@pytest.mark.asyncio
async def test_report_publish_blocks_required_analytical_review_findings(cfg):
    designed = await report_design_report(
        cfg=cfg,
        llm=_creative_llm(),
        report_goal="Forecast the remaining tournament matches and champion probabilities.",
        report_path="reports/needs-baseline.html",
        storyboard_path="reports/needs-baseline.storyboard.json",
        insights=[{
            "title": "Spain lead the projection",
            "detail": "Spain have the highest champion probability.",
            "finding_id": "finding-baseline",
        }],
    )

    required = {
        finding["id"] for finding in designed["analytical_review"]["findings"]
        if finding["severity"] == "required"
    }
    assert required == {"missing_baseline_comparison"}

    with pytest.raises(ValueError, match="analytical-review gate failed: missing_baseline_comparison"):
        await report_publish(
            cfg=cfg,
            report_path="reports/needs-baseline.html",
            storyboard_path="reports/needs-baseline.storyboard.json",
            export_docx=False,
        )


@pytest.mark.asyncio
async def test_report_review_lifecycle_supports_explicit_risk_acceptance(cfg):
    from dataclaw_analysis_review.tools import resolve_review_finding

    designed = await report_design_report(
        cfg=cfg,
        llm=_creative_llm(),
        report_goal="Forecast the remaining tournament matches and champion probabilities.",
        report_path="reports/accepted-risk.html",
        storyboard_path="reports/accepted-risk.storyboard.json",
        insights=[{
            "title": "Spain lead the projection",
            "detail": "Spain have the highest champion probability.",
            "finding_id": "finding-accepted-risk",
        }],
    )
    lifecycle = designed["review_lifecycle"]
    baseline = next(
        finding for finding in lifecycle["findings"]
        if finding["report_finding_id"] == "missing_baseline_comparison"
    )
    assert lifecycle["gate"]["gate"] == "fail"

    accepted = await resolve_review_finding(
        finding_id=baseline["finding_id"],
        status="accepted_with_rationale",
        rationale="The stakeholder explicitly accepted the missing historical comparison for this exploratory forecast.",
        session_id="default",
    )
    assert accepted["success"] is True
    assert accepted["status"] == "accepted_with_rationale"

    published = await report_publish(
        cfg=cfg,
        report_path="reports/accepted-risk.html",
        storyboard_path="reports/accepted-risk.storyboard.json",
        export_docx=False,
    )
    baseline_review = next(
        finding for finding in published["analytical_review"]["findings"]
        if finding["id"] == "missing_baseline_comparison"
    )
    assert baseline_review["lifecycle_status"] == "accepted_with_rationale"


@pytest.mark.asyncio
async def test_report_publish_recomputes_a_tampered_analytical_review(cfg):
    designed = await report_design_report(
        cfg=cfg,
        llm=_creative_llm(),
        report_goal="Forecast next-quarter demand.",
        report_path="reports/tampered-review.html",
        storyboard_path="reports/tampered-review.storyboard.json",
        insights=[{"title": "Demand forecast", "detail": "Demand is projected to rise.", "finding_id": "finding-tampered"}],
    )
    storyboard_path = Path(designed["storyboard_path"])
    storyboard = json.loads(storyboard_path.read_text())
    storyboard["analytical_review"] = {"status": "pass", "findings": []}
    storyboard_path.write_text(json.dumps(storyboard), encoding="utf-8")

    with pytest.raises(ValueError, match="analytical-review gate failed: missing_baseline_comparison"):
        await report_publish(
            cfg=cfg,
            report_path="reports/tampered-review.html",
            storyboard_path="reports/tampered-review.storyboard.json",
            export_docx=False,
        )

    refreshed = json.loads(storyboard_path.read_text())
    assert refreshed["analytical_review"]["status"] == "attention_required"


@pytest.mark.asyncio
async def test_report_publish_rejects_html_from_a_different_storyboard(cfg):
    designed = await report_design_report(
        cfg=cfg,
        llm=_creative_llm(),
        report_goal="Explain retention by cohort.",
        report_path="reports/hash-bound.html",
        storyboard_path="reports/hash-bound.storyboard.json",
        insights=[{"title": "Retention", "detail": "Retention is stable.", "finding_id": "finding-retention"}],
    )
    html_path = Path(designed["html_path"])
    html_path.write_text("<!doctype html><html><body><h1>Different forecast</h1></body></html>", encoding="utf-8")

    with pytest.raises(ValueError, match="integrity gate failed"):
        await report_publish(
            cfg=cfg,
            report_path="reports/hash-bound.html",
            storyboard_path="reports/hash-bound.storyboard.json",
            export_docx=False,
        )


@pytest.mark.asyncio
async def test_report_publish_rejects_a_changed_analysis_contract(cfg):
    designed = await report_design_report(
        cfg=cfg,
        llm=_creative_llm(),
        report_goal="Forecast next-quarter demand.",
        report_path="reports/contract-bound.html",
        storyboard_path="reports/contract-bound.storyboard.json",
        insights=[{"title": "Demand forecast", "detail": "Demand is projected to rise.", "finding_id": "finding-contract"}],
    )
    storyboard_path = Path(designed["storyboard_path"])
    storyboard = json.loads(storyboard_path.read_text())
    storyboard["analysis_contract"] = {
        "mode": "predictive",
        "baseline": {
            "status": "complete",
            "method": "Holdout comparison",
            "result": "Improved log loss",
            "evidence": {"kind": "notebook_cell", "ref": "cell-ablation"},
        },
    }
    storyboard_path.write_text(json.dumps(storyboard), encoding="utf-8")

    with pytest.raises(ValueError, match="analytical review contract changed after rendering"):
        await report_publish(
            cfg=cfg,
            report_path="reports/contract-bound.html",
            storyboard_path="reports/contract-bound.storyboard.json",
            export_docx=False,
        )


@pytest.mark.asyncio
async def test_report_publish_reports_docx_unsupported_for_authored_reports(cfg):
    # Every report is now an authored single-file HTML document whose CSS/SVG/
    # Canvas presentation cannot be preserved by a DOCX conversion, so a DOCX
    # export request is recorded as an explicit unsupported outcome.
    await report_design_report(
        cfg=cfg,
        llm=_creative_llm(),
        report_goal="Explain the result.",
        report_path="reports/docx-failure.html",
        storyboard_path="reports/docx-failure.storyboard.json",
        insights=[
            {
                "title": "A result",
                "detail": "The completed finding is available in the report.",
                "finding_id": "finding-docx",
            }
        ],
    )

    published = await report_publish(
        cfg=cfg,
        report_path="reports/docx-failure.html",
        storyboard_path="reports/docx-failure.storyboard.json",
        export_docx=True,
    )

    receipt = json.loads(Path(published["receipt_path"]).read_text())
    assert published["published"] is True
    assert published["docx_export"]["requested"] is True
    assert published["docx_export"]["status"] == "unsupported"
    assert "authored" in published["docx_export"]["reason"]
    assert receipt["docx_export"] == published["docx_export"]


@pytest.mark.asyncio
async def test_report_design_report_requires_completed_insights(cfg):
    with pytest.raises(ValueError, match="at least one completed insight"):
        await report_design_report(
            cfg=cfg,
            report_goal="Build a report from charts only.",
            title="Thin Report",
            report_path="reports/thin.html",
            insights=[],
            analyses=[
                {"title": "Chart", "figure": {"data": [{"type": "bar", "x": ["A"], "y": [1]}]}},
            ],
        )


def test_runtime_smoke_reclassifies_closed_browser_as_skipped():
    result = workspace_tools._classify_runtime_smoke_result({
        "status": "failed",
        "checks": [{
            "check": "page_load",
            "detail": "browserType.newPage: Target page, context or browser has been closed",
        }],
    })

    assert result["status"] == "skipped"
    assert "environment unavailable" in result["reason"]


def test_runtime_smoke_keeps_rendered_layout_failures_visible():
    result = workspace_tools._classify_runtime_smoke_result({
        "status": "failed",
        "checks": [{
            "check": "horizontal_overflow",
            "detail": "desktop viewport scrolls horizontally (1448px > 1440px)",
        }],
    })

    assert result["status"] == "failed"


@pytest.mark.asyncio
async def test_runtime_smoke_emits_passing_semantic_review_for_a_designed_report(cfg):
    designed = await report_design_report(
        cfg=cfg,
        llm=_creative_llm(),
        report_goal="Explain the completed decision-changing finding.",
        report_path="reports/runtime-semantic.html",
        storyboard_path="reports/runtime-semantic.storyboard.json",
        insights=[{
            "title": "Retention improved",
            "detail": "The retained cohort rose after the completed onboarding change.",
            "finding_id": "retention-runtime-smoke",
        }],
    )
    smoke = await workspace_tools._run_report_runtime_smoke(Path(designed["html_path"]))

    # Browser capability is optional in this plugin, but a browser-enabled
    # environment must expose the deterministic semantic result as well as its
    # screenshot and layout checks.
    assert smoke["status"] in {"passed", "skipped"}, smoke
    if smoke["status"] == "passed":
        semantic = smoke["semantic_visual"]
        assert semantic["visual_semantic_schema"] == 1
        assert semantic["status"] == "pass"
        assert semantic["findings"] == []
