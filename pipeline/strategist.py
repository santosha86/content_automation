"""Strategist: gather candidates across lanes, rank the top 3 for shorts potential.

Two lanes, one scoring rubric (the viral-shorts-strategy skill):
  - ai_news        — RSS feeds (scout.fetch_candidates). Tavily search arrives later.
  - github_trending — a repo trending hard is a story: what it does, why now, who cares.

Output is the Strategist's top-3, ranked. The `story_pick` checkpoint (auto|manual)
decides whether rank-1 is taken automatically or the user chooses in the dashboard.
"""
import os
import re

import requests

from . import scout
from .util import llm_json, settings, strategy_skill

TRENDING_URL = "https://github.com/trending?since=daily"
TAVILY_URL = "https://api.tavily.com/search"
_UA = {"User-Agent": "Mozilla/5.0 (compatible; content-automation/1.0)"}


def _first(patterns, block, default=""):
    for p in patterns:
        m = re.search(p, block, re.DOTALL)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip()
    return default


def fetch_github_trending(limit: int = 15) -> list[dict]:
    """Scrape today's GitHub trending repos into candidate stories. Best-effort:
    returns [] on any network/parse failure so the ai_news lane still carries the run."""
    try:
        html = requests.get(TRENDING_URL, timeout=20, headers=_UA).text
    except Exception:
        return []
    rows = re.split(r'<article class="Box-row">', html)[1:]
    out = []
    for row in rows[:limit]:
        m = re.search(r'<h2[^>]*>.*?href="/([^"/]+/[^"]+)"', row, re.DOTALL)
        if not m:
            continue
        repo = m.group(1).strip()
        desc = _first([r'<p class="col-9[^"]*"[^>]*>\s*(.*?)\s*</p>'], row)
        lang = _first([r'itemprop="programmingLanguage">([^<]+)<'], row)
        stars = _first([r'([\d,]+)\s*stars today'], row)
        summary = " · ".join(x for x in [
            desc, f"{lang}" if lang else "", f"{stars} stars today" if stars else "",
        ] if x)
        out.append({
            "lane": "github_trending",
            "source": "GitHub Trending",
            "title": repo,
            "summary": summary[:500],
            "url": f"https://github.com/{repo}",
            "key": scout._key({"link": f"https://github.com/{repo}"}),
        })
    return out


def fetch_tavily(limit: int = 10) -> list[dict]:
    """Fresh AI-news headlines via Tavily search — augments the RSS ai_news lane with
    stories the fixed feed list misses. Best-effort: [] when no key or on any failure."""
    key = os.getenv("TAVILY_API_KEY", "")
    if not key:
        return []
    cfg = settings()["scout"]
    days = max(1, int(cfg.get("max_age_hours", 48) / 24) or 1)
    try:
        resp = requests.post(TAVILY_URL, timeout=30, json={
            "api_key": key,
            "query": "biggest AI news today: OpenAI Anthropic Google Meta models tools launches",
            "topic": "news", "days": days, "max_results": limit, "search_depth": "basic",
        })
        resp.raise_for_status()
        results = resp.json().get("results", [])
        try:  # Tavily bills per request
            from . import usage
            usage.record("search", station="scout", stage="strategist.tavily",
                         provider="tavily", requests=1)
        except Exception:
            pass
    except Exception:
        return []
    out = []
    for r in results:
        url = r.get("url", "")
        if not url:
            continue
        out.append({
            "lane": "ai_news",
            "source": "Tavily",
            "title": r.get("title", "").strip(),
            "summary": (r.get("content", "") or "")[:500],
            "url": url,
            "key": scout._key({"link": url}),
        })
    return out


def gather_candidates() -> list[dict]:
    """All lanes, deduped against seen history and each other, tagged with their lane."""
    seen = scout._seen()
    by_key: dict[str, dict] = {}
    news = []
    for c in scout.fetch_candidates():
        c["lane"] = "ai_news"
        news.append(c)
    # RSS first (richest summaries), then Tavily fills gaps, then GitHub trending.
    for c in news + fetch_tavily() + fetch_github_trending():
        if c["key"] in seen or c["key"] in by_key or not c.get("title"):
            continue
        by_key[c["key"]] = c
    return list(by_key.values())


def top_stories(n: int = 3) -> list[dict]:
    """Rank all candidates with the house rubric; return the top `n`, ranked.

    Each returned story carries `rank`, `why`, and `name_anchor` (may be empty —
    never forced; see the name-anchor rule in the strategy skill)."""
    candidates = gather_candidates()
    if not candidates:
        raise RuntimeError("No fresh unseen candidates in any lane — widen max_age_hours or add feeds.")

    listing = "\n".join(
        f"{i}. [{c['lane']}] {c['title']} — {c['summary'][:220]}"
        for i, c in enumerate(candidates)
    )
    result = llm_json(
        f"""You are the Strategist for a daily AI-news YouTube Short / Instagram Reel.
Pick the {n} candidates with the highest short-form potential, best first.

Score every candidate on, in priority order: name gravity, stakes, freshness,
explainability in 30-40 spoken seconds, and real visual proof availability.
Follow this house strategy exactly:

{strategy_skill()}

CANDIDATES ({len(candidates)}):
{listing}

Reply with JSON only:
{{"top": [
  {{"index": <int>, "name_anchor": "<famous name/brand the story genuinely involves, or empty>",
    "why": "<one sentence: why this scores high>"}}
]}}
Return exactly {n} entries (or fewer only if fewer candidates exist), best first.
Never invent a name_anchor the story does not genuinely involve.""",
        system="You are a precise short-form content strategist. Output valid JSON only.",
        station="scout",
        stage="strategist.rank",
    )

    stories = []
    for rank, pick in enumerate(result.get("top", [])[:n], start=1):
        idx = int(pick["index"])
        if not (0 <= idx < len(candidates)):
            continue
        story = dict(candidates[idx])
        story["rank"] = rank
        story["why"] = pick.get("why", "")
        story["name_anchor"] = pick.get("name_anchor", "")
        stories.append(story)
    if not stories:
        raise RuntimeError("Strategist returned no valid picks.")
    return stories


def mark_picked(story: dict) -> None:
    """Record the chosen story so it is never picked again."""
    scout._mark_seen([story["key"]])


if __name__ == "__main__":
    import json
    for s in top_stories():
        print(f"#{s['rank']} [{s['lane']}] {s['title']}")
        print(f"    anchor: {s['name_anchor'] or '-'}  | why: {s['why']}")
