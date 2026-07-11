"""Virality pre-check — score a story's short-form potential BEFORE we spend a render.

This is the "will it go viral?" gate the pipeline was missing. It is a domain-expert
RUBRIC scorer (not a black box): an LLM rates each story across the levers that actually
drive AI-news Shorts performance, and returns a 0-100 score with a per-dimension
breakdown and the single strongest angle to lead with. The Director/Hook Smith can then
build toward that angle, and weak stories are flagged before they cost a render.

Why a rubric and not an ML model (yet): with no first-party engagement data, a calibrated
expert rubric beats a model trained on nothing. Once the Publisher (Phase C) + analytics
loop (Phase E) feed real view/retention numbers back, these weights get tuned to YOUR
audience — that's the upgrade path.
"""
from .util import llm_json, settings

# The levers, weighted by how much they move short-form AI-news performance. Weights sum
# to 100. Saturation is a penalty applied on top (overdone topics get discounted).
_RUBRIC = """You are a short-form (YouTube Shorts / Reels / TikTok) strategist who has
studied thousands of viral AI-news videos. Score this story's viral potential HONESTLY —
most stories are mediocre; reserve 80+ for genuinely exceptional ones.

Rate each dimension in its point range, then sum:
- hook_potential (0-25): Is there an inherent scroll-stopping angle in the first 2s? A
  shock, a bold number, a named giant (OpenAI/Google/Meta/Apple/Nvidia), a "you won't
  believe" reveal, or open conflict. Generic incremental news scores low here.
- stakes_relatability (0-20): Does it directly touch the viewer — their job, their money,
  a tool they use, something they can try today? Abstract industry news scores low.
- emotion_controversy (0-20): Does it provoke a strong reaction — surprise, fear, awe,
  outrage, us-vs-them, "this changes everything"? Neutral announcements score low.
- timeliness_heat (0-15): Freshness + the size/heat of the players and the moment.
- concreteness_proof (0-10): Is there a demo, a real number, a screenshot-able artifact,
  a benchmark — something we can SHOW as proof?
- simplicity (0-10): Can a general (non-technical) viewer grasp the payoff in one line?

Then set saturation_penalty (0-15): subtract if this exact angle is oversaturated (yet
another "X launches a model" with no differentiator, a rumor with no substance, etc).

final_score = sum(dimensions) - saturation_penalty, clamped 0-100."""


def score(story: dict, station: str = "scout") -> dict:
    """Score one story. Returns {score, dimensions{}, saturation_penalty, verdict,
    one_line, best_angle, risks}. Never raises — a failure returns a neutral 50."""
    title = story.get("title", "")
    summary = (story.get("summary") or "")[:600]
    anchor = story.get("name_anchor", "")
    lane = story.get("lane", "")
    try:
        r = llm_json(
            f"""{_RUBRIC}

STORY
title: {title}
lane: {lane}
named entity: {anchor or "(none detected)"}
summary: {summary or "(none)"}

Reply JSON only:
{{
  "dimensions": {{
    "hook_potential": <0-25>, "stakes_relatability": <0-20>,
    "emotion_controversy": <0-20>, "timeliness_heat": <0-15>,
    "concreteness_proof": <0-10>, "simplicity": <0-10>
  }},
  "saturation_penalty": <0-15>,
  "score": <0-100 final>,
  "verdict": "strong | promising | weak | skip",
  "one_line": "<one sentence: why it will or won't perform>",
  "best_angle": "<the single strongest hook angle to lead with>",
  "risks": "<the main reason it could flop, in a few words>"
}}""",
            system="You are a short-form virality strategist. Output valid JSON only.",
            station=station,
            stage="virality.score",
        )
        # Trust the model's summed score, but recompute defensively if it's missing.
        dims = r.get("dimensions", {})
        if not isinstance(r.get("score"), (int, float)):
            r["score"] = max(0, min(100, sum(v for v in dims.values() if isinstance(v, (int, float)))
                                    - r.get("saturation_penalty", 0)))
        r["score"] = int(max(0, min(100, r["score"])))
        return r
    except Exception as e:
        return {"score": 50, "dimensions": {}, "verdict": "unknown",
                "one_line": f"score unavailable ({str(e)[:60]})", "best_angle": "", "risks": ""}


def min_score() -> int:
    return int(settings().get("virality", {}).get("min_score", 55))


def score_candidates(stories: list[dict], log=print) -> list[dict]:
    """Score each candidate, attach `virality`, and return them sorted by score (desc).
    Ties keep the Strategist's original order (stable sort)."""
    for s in stories:
        s["virality"] = score(s)
        v = s["virality"]
        log(f"      virality {v['score']:>3}/100 [{v['verdict']}] {s['title'][:52]}  — {v.get('best_angle','')[:60]}")
    return sorted(stories, key=lambda s: s["virality"]["score"], reverse=True)


def emoji(verdict: str) -> str:
    return {"strong": "🔥", "promising": "✨", "weak": "⚠️", "skip": "🛑"}.get(verdict, "•")


if __name__ == "__main__":
    from . import strategist
    for st in strategist.top_stories(3):
        v = score(st)
        print(f"{v['score']}/100 [{v['verdict']}] {st['title']}\n   angle: {v.get('best_angle')}\n   {v.get('one_line')}\n")
