"""Analyst agent (Phase E) — the learning loop.

Reads what actually happened across every video — predicted virality vs real performance,
recurring QA gaps, cost, hook/lane/emotion patterns — and proposes CONCRETE, reviewable
changes to the system's "brain" (style_guide, hook formulas, virality rubric, Director
guidance). Nothing is auto-applied: it produces recommendations a human approves, matching
the pipeline's checkpoint philosophy.

Data source note: while analytics is on sample data, correlations are illustrative; the
report is labelled accordingly and becomes real the moment ANALYTICS_LIVE is wired.
"""
import json
from datetime import date
from pathlib import Path

from . import analytics
from .util import ROOT, llm_json

REVIEW_DIR = ROOT / "output" / "review"
RUNS_DIR = ROOT / "output" / "runs"
ANALYST_DIR = ROOT / "output" / "analyst"


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def gather_evidence(platform: str = "youtube") -> list[dict]:
    """One row per rendered video: prediction, actual performance, QA gaps, hook/lane,
    cost — the raw material the Analyst reasons over."""
    rows = []
    if not REVIEW_DIR.exists():
        return rows
    for folder in sorted(REVIEW_DIR.iterdir(), reverse=True):
        if not folder.is_dir():
            continue
        slug = folder.name
        meta = _read(folder / "metadata.json")
        plan = _read(RUNS_DIR / slug / "plan.json")
        sb = _read(RUNS_DIR / slug / "storyboard.json")
        report = _read(folder / "review_report.json")
        usage = _read(RUNS_DIR / slug / "usage.json")
        story = plan.get("story", {})
        perf = analytics.metrics(slug, platform)
        gaps = [i.get("id") for i in report.get("items", []) if i.get("result") == "fail"]
        rows.append({
            "slug": slug,
            "title": (meta.get("youtube") or {}).get("title") or story.get("title") or slug,
            "date": slug[:10],
            "lane": story.get("lane", sb.get("topic", {}).get("lane", "")),
            "hook_type": sb.get("hook", {}).get("type", ""),
            "hook_text": sb.get("hook", {}).get("text", meta.get("hook_text", "")),
            "predicted_virality": (story.get("virality") or {}).get("score"),
            "emotions": [b.get("emotion") for b in sb.get("beats", [])],
            "beats": len(sb.get("beats", [])),
            "qa_gaps": gaps,
            "actual": {"views": perf["views"], "retention_pct": perf["avg_view_pct"],
                       "likes": perf["likes"], "shares": perf["shares"],
                       "new_followers": perf["new_followers"]},
            "data_source": perf.get("source", "dummy"),
        })
    return rows


def _gate_legend() -> str:
    """Human-readable Gate B ids so the Analyst's QA fixes are grounded, not guessed."""
    c = _read(ROOT / "checklist.schema.json")
    items = c.get("gates", {}).get("gate_b_pre_publish", [])
    return "\n".join(f"  {i.get('id')}: {(i.get('title') or i.get('pass_criteria') or '')[:90]}"
                     for i in items) or "(unavailable)"


def analyze(evidence: list[dict], platform: str = "youtube") -> dict:
    """LLM correlates the evidence and proposes concrete brain edits."""
    live = any(r["data_source"] == "live" for r in evidence)
    compact = [{k: r[k] for k in ("title", "lane", "hook_type", "predicted_virality",
                                  "qa_gaps", "actual")} for r in evidence]
    try:
        report = llm_json(
            f"""You are the Analyst — the learning loop of a short-form AI-news video factory.
Analyze performance across these {len(compact)} videos and propose concrete improvements.
Data is {"REAL analytics" if live else "SAMPLE analytics (illustrative — hedge causal claims)"}.

GATE B legend (what each QA id means — use for accurate systemic fixes):
{_gate_legend()}

VIDEOS (predicted_virality was our pre-render score; actual is measured performance):
{json.dumps(compact, indent=1)}

Do four things:
1. CALIBRATION — is predicted_virality tracking actual views/retention? Which stories did
   we over- or under-rate? Is the virality rubric mis-weighting any dimension?
2. WINNING PATTERNS — what do the best performers share (hook_type, lane, emotion, length)?
3. RECURRING QA GAPS — which Gate B ids fail most, and the systemic fix.
4. PROPOSALS — specific, reviewable edits to the brain. Each targets exactly one of:
   style_guide | hook_formulas | virality_rubric | director_realism | scouting.

Reply JSON only:
{{
  "headline": "<one-sentence top takeaway>",
  "calibration": "<2-3 sentences: prediction vs reality, and any rubric mis-weighting>",
  "winning_patterns": ["<pattern>", "..."],
  "recurring_qa_gaps": [{{"gate": "<id>", "count": <int>, "fix": "<systemic fix>"}}],
  "cost_note": "<one line on cost efficiency if inferable, else ''>",
  "proposals": [
    {{"target": "style_guide|hook_formulas|virality_rubric|director_realism|scouting",
      "change": "<the specific edit to make>", "rationale": "<why, tied to the data>",
      "confidence": "high|medium|low"}}
  ]
}}""",
            system="You are a rigorous short-form video performance analyst. Output valid JSON only.",
            station="writer",
            stage="analyst.analyze",
        )
    except Exception as e:
        return {"headline": f"analysis failed ({str(e)[:80]})", "proposals": []}
    report["data_source"] = "live" if live else "sample"
    report["videos_analyzed"] = len(evidence)
    report["platform"] = platform
    return report


def run(platform: str = "youtube") -> dict:
    """Generate + persist a fresh insights report. Returns the report."""
    evidence = gather_evidence(platform)
    if not evidence:
        return {"headline": "No rendered videos yet — nothing to analyze.", "proposals": [],
                "videos_analyzed": 0}
    report = analyze(evidence, platform)
    ANALYST_DIR.mkdir(parents=True, exist_ok=True)
    report["generated_on"] = str(date.today())
    (ANALYST_DIR / "latest.json").write_text(json.dumps(report, indent=2))
    (ANALYST_DIR / f"report-{date.today()}.json").write_text(json.dumps(report, indent=2))
    return report


def latest() -> dict | None:
    return _read(ANALYST_DIR / "latest.json") or None


_VALID_TARGETS = {"style_guide", "hook_formulas", "virality_rubric", "director_realism", "scouting"}
_LEARNINGS = ROOT / "config" / "learnings.md"


def apply_proposal(proposal: dict) -> dict:
    """Guarded apply: append an approved proposal as a durable bullet under its target
    section in config/learnings.md. The relevant station's prompt reads that section
    (util.learnings), so the change takes effect on the next run — WITHOUT editing any
    code. Reversible (just delete the line). Returns {ok, target, line}."""
    target = (proposal.get("target") or "").strip()
    change = (proposal.get("change") or "").strip()
    if target not in _VALID_TARGETS:
        return {"ok": False, "error": f"unknown target '{target}'"}
    if not change:
        return {"ok": False, "error": "empty change"}
    conf = proposal.get("confidence", "")
    why = (proposal.get("rationale") or "").strip()
    line = f"- [{date.today()} · {conf}] {change}" + (f" (why: {why})" if why else "")

    text = _LEARNINGS.read_text() if _LEARNINGS.exists() else \
        "# Learnings — Analyst proposals you approved. Each bullet steers the matching\n" \
        "# station's prompt (util.learnings). Delete a line to revert. Do not rename headers.\n"
    header = f"## {target}"
    if header in text:
        # insert the bullet right after the section header
        out, inserted = [], False
        for ln in text.splitlines():
            out.append(ln)
            if not inserted and ln.strip() == header:
                out.append(line)
                inserted = True
        text = "\n".join(out) + "\n"
    else:
        text = text.rstrip() + f"\n\n{header}\n{line}\n"
    _LEARNINGS.parent.mkdir(parents=True, exist_ok=True)
    _LEARNINGS.write_text(text)
    return {"ok": True, "target": target, "line": line}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2)[:2500])
