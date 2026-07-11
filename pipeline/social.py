"""Social posts — turn a story (or a finished video) into on-brand LinkedIn + X copy.

Same brain, different surface: the pipeline already researches and frames AI news for
video; this reuses that to draft text posts. Brand voice + format rules are encoded below
(professional-but-approachable, value-first). Optionally schedules via Typefully.
"""
import json
import os
from pathlib import Path

import requests

from .util import ROOT, llm_json

REVIEW_DIR = ROOT / "output" / "review"
RUNS_DIR = ROOT / "output" / "runs"

_BRAND = """Voice: professional but approachable — a knowledgeable colleague, not a
textbook. Active voice, lead with value, one idea per line. Concrete examples over
abstract claims. Topics: AI agents, developer tools, software architecture, emerging tech.

LinkedIn post rules:
- Structure: Hook (1-2 lines) -> Context (2-3 lines) -> Body (3-5 short paragraphs) ->
  Takeaway -> a CTA question -> 3-5 hashtags.
- Max ~1300 characters. A blank line between every paragraph. Hashtags ONLY at the end.
- The hook must stop the scroll: a surprising stat, a bold claim, or a direct question.

X / Twitter thread rules:
- Tweet 1: `1/🧵` hook that stands alone. Tweets 2..N: context then points. Last tweet:
  summary + a CTA question. Each tweet <= 280 characters. Max 2 hashtags, last tweet only."""


def context_from_slug(slug: str) -> dict:
    """Pull the richest available framing for a rendered/planned run."""
    ctx = {"title": slug, "hook": "", "summary": "", "url": ""}
    meta = REVIEW_DIR / slug / "metadata.json"
    if meta.exists():
        try:
            m = json.loads(meta.read_text())
            ctx["title"] = (m.get("youtube") or {}).get("title") or (m.get("topic") or {}).get("title") or slug
            ctx["hook"] = m.get("hook_text", "")
            ctx["summary"] = (m.get("youtube") or {}).get("description", "")
            ctx["url"] = m.get("source_article", "") or (m.get("topic") or {}).get("url", "")
        except Exception:
            pass
    sb = RUNS_DIR / slug / "storyboard.json"
    if sb.exists() and not ctx["summary"]:
        try:
            s = json.loads(sb.read_text())
            ctx["title"] = s.get("topic", {}).get("title", ctx["title"])
            ctx["hook"] = s.get("hook", {}).get("text", ctx["hook"])
            ctx["summary"] = " ".join(b.get("narration", "") for b in s.get("beats", []))
            ctx["url"] = s.get("topic", {}).get("source_url", ctx["url"])
        except Exception:
            pass
    return ctx


def generate(title: str, hook: str = "", summary: str = "", url: str = "",
             platforms: list[str] = None) -> dict:
    """Draft on-brand posts. Returns {linkedin: str, twitter: [tweets], title}."""
    platforms = platforms or ["linkedin", "twitter"]
    want = ", ".join(platforms)
    r = llm_json(
        f"""Write social posts about this AI story. {_BRAND}

STORY
title: {title}
angle/hook: {hook or "(none)"}
summary: {(summary or "")[:900]}
source: {url or "(none)"}

Produce ONLY the requested platforms ({want}). Reply JSON only:
{{
  "linkedin": "<the full LinkedIn post, ready to paste, with line breaks and hashtags>",
  "twitter": ["<tweet 1 (1/🧵 ...)>", "<tweet 2>", "<...>"]
}}""",
        system="You are a senior developer-brand social writer. Output valid JSON only.",
        station="writer",
        stage="social.generate",
    )
    return {"title": title,
            "linkedin": r.get("linkedin", "") if "linkedin" in platforms else "",
            "twitter": r.get("twitter", []) if "twitter" in platforms else []}


def typefully_configured() -> bool:
    return bool(os.getenv("TYPEFULLY_API_KEY"))


def schedule_typefully(content: str, publish_at: str = "next-free-slot") -> dict:
    """Create a Typefully draft (LinkedIn/X share the connected social set). publish_at:
    'now' | 'next-free-slot' | ISO-8601. No-op-safe: returns a clear status if unconfigured."""
    key = os.getenv("TYPEFULLY_API_KEY")
    if not key:
        return {"status": "not_configured", "reason": "set TYPEFULLY_API_KEY in .env"}
    try:
        resp = requests.post("https://api.typefully.com/v1/drafts/", timeout=30,
                             headers={"X-API-KEY": f"Bearer {key}"},
                             json={"content": content, "schedule-date": publish_at})
        resp.raise_for_status()
        return {"status": "scheduled", "draft": resp.json()}
    except Exception as e:
        return {"status": "error", "reason": str(e)[:200]}


if __name__ == "__main__":
    import sys
    ctx = context_from_slug(sys.argv[1]) if len(sys.argv) > 1 else \
        {"title": "OpenAI ships a coding agent that runs your CI", "hook": "", "summary": "", "url": ""}
    out = generate(**ctx)
    print("LINKEDIN:\n", out["linkedin"], "\n\nX THREAD:\n", "\n---\n".join(out["twitter"]))
