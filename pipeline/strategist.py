"""Strategist: gather candidates across lanes, rank the top 3 for shorts potential.

Lanes (all free), one scoring rubric (the viral-shorts-strategy skill):
  - ai_news         — RSS feeds (scout.fetch_candidates) + Tavily search.
  - hacker_news     — recent AI stories with real traction (points/comments) -> heat score.
  - reddit          — the main AI subreddits' hot list (via RSS; JSON API now 403s).
  - github_trending — a repo trending hard is a story: what it does, why now, who cares.

Trend lanes (HN/Reddit) surface what's ALREADY getting traction right now; HN's engagement
becomes a 0-100 `heat` score fed into the ranker so hot stories float up (this is the
"trending data" plug-in that improves viral-content selection). Output is the top-3, ranked.
The `story_pick` checkpoint (auto|manual) decides whether rank-1 is taken automatically.
"""
import math
import os
import re
import time

import requests

from . import scout
from .util import learnings_block, llm_json, settings, strategy_skill

TRENDING_URL = "https://github.com/trending?since=daily"
TAVILY_URL = "https://api.tavily.com/search"
HN_URL = "https://hn.algolia.com/api/v1/search"
_UA = {"User-Agent": "Mozilla/5.0 (compatible; content-automation/1.0)"}

# AI-relevance filter for broad trend sources (HN front page, Reddit) so we don't surface
# unrelated viral tech. A candidate must mention one of these to enter the AI-news lane.
_AI_TERMS = ("ai", "artificial intelligence", "llm", "gpt", "openai", "anthropic", "claude",
             "gemini", "llama", "mistral", "agent", "model", "machine learning", "ml ",
             "neural", "diffusion", "chatbot", "nvidia", "hugging face", "deepseek", "grok")
_AI_SUBREDDITS = ["artificial", "MachineLearning", "LocalLLaMA", "OpenAI", "singularity", "ChatGPT"]


def _is_ai(text: str) -> bool:
    t = (text or "").lower()
    return any(term in t for term in _AI_TERMS)


def _heat(engagement: int) -> int:
    """Turn raw engagement (points/upvotes + comments) into a 0-100 'how hot right now'
    score, log-scaled so HN and Reddit's different magnitudes compare sensibly."""
    return int(min(100, 22 * math.log10(1 + max(0, engagement))))


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


def fetch_hackernews(limit: int = 20, min_points: int = 60) -> list[dict]:
    """Recent Hacker News stories with real traction (points/comments) — the developer
    audience's live signal. Free, no key. Best-effort: [] on any failure."""
    cutoff = int(time.time()) - 3 * 24 * 3600  # last ~3 days
    try:
        resp = requests.get(HN_URL, timeout=20, headers=_UA, params={
            "tags": "story", "query": "AI",
            "numericFilters": f"created_at_i>{cutoff},points>{min_points}",
            "hitsPerPage": limit,
        })
        resp.raise_for_status()
        hits = resp.json().get("hits", [])
    except Exception:
        return []
    out = []
    for h in hits:
        title = (h.get("title") or "").strip()
        url = h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}"
        if not title or not _is_ai(title):
            continue
        points, comments = h.get("points", 0) or 0, h.get("num_comments", 0) or 0
        eng = points + comments
        out.append({
            "lane": "ai_news", "source": "Hacker News", "title": title,
            "summary": f"{points} points, {comments} comments on HN — developer traction.",
            "url": url, "key": scout._key({"link": url}),
            "engagement": eng, "heat": _heat(eng),
        })
    return out


def fetch_reddit(limit: int = 12) -> list[dict]:
    """Community-trending AI stories from the main subreddits via Reddit's RSS (their JSON
    API now 403s datacenter IPs). RSS carries no upvote counts, so these enter as candidates
    without a heat score — HN provides the numeric trend signal. Best-effort: [] on failure."""
    import feedparser
    subs = "+".join(settings().get("scout", {}).get("subreddits", _AI_SUBREDDITS))
    bua = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"}
    try:
        # feedparser's own fetch gets blocked — pull the text with a browser UA first.
        resp = requests.get(f"https://www.reddit.com/r/{subs}/hot/.rss",
                            timeout=20, headers=bua, params={"limit": 30})
        resp.raise_for_status()
        feed = feedparser.parse(resp.text)
    except Exception:
        return []
    out = []
    for e in feed.entries[:30]:
        title = (getattr(e, "title", "") or "").strip()
        if not title or not _is_ai(title):
            continue
        # Prefer the external article the post links to; fall back to the reddit thread.
        content = e.content[0].value if getattr(e, "content", None) else ""
        ext = [h for h in re.findall(r'href="(https?://[^"]+)"', content)
               if "reddit.com" not in h and "redd.it" not in h]
        url = ext[0] if ext else getattr(e, "link", "")
        if not url:
            continue
        out.append({
            "lane": "ai_news", "source": "Reddit", "title": title,
            "summary": f"Trending in r/{getattr(e, 'tags', [{}])[0].get('term', 'AI') if getattr(e, 'tags', None) else 'AI'} — community pick.",
            "url": url, "key": scout._key({"link": url}),
        })
        if len(out) >= limit:
            break
    return out


def gather_candidates() -> list[dict]:
    """All lanes, deduped against seen history and each other, tagged with their lane."""
    seen = scout._seen()
    by_key: dict[str, dict] = {}
    news = []
    for c in scout.fetch_candidates():
        c["lane"] = "ai_news"
        news.append(c)
    # RSS first (richest summaries), then trend signals (HN + Reddit carry real-time
    # engagement/heat), then Tavily fills gaps, then GitHub trending. First-seen wins on
    # dedup, so an article that's ALSO trending keeps its richer RSS summary but we merge
    # the heat signal onto it below.
    trend = fetch_hackernews() + fetch_reddit()
    for c in news + trend + fetch_tavily() + fetch_github_trending():
        if not c.get("title"):
            continue
        if c["key"] in seen:
            continue
        existing = by_key.get(c["key"])
        if existing:
            # same story via two lanes — keep the first, but carry over the heat signal.
            if c.get("heat") and c["heat"] > existing.get("heat", 0):
                existing["heat"] = c["heat"]
                existing["engagement"] = c.get("engagement", existing.get("engagement", 0))
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

    # Surface the live heat signal so genuinely-trending stories float up (not just what
    # an editor feed happened to list). heat is 0-100 from HN/Reddit engagement.
    listing = "\n".join(
        f"{i}. [{c['lane']}] {c['title']}"
        + (f" (🔥heat {c['heat']} · {c.get('source','')})" if c.get("heat") else "")
        + f" — {c['summary'][:200]}"
        for i, c in enumerate(candidates)
    )
    result = llm_json(
        f"""You are the Strategist for a daily AI-news YouTube Short / Instagram Reel.
Pick the {n} candidates with the highest short-form potential, best first.

Score every candidate on, in priority order: name gravity, stakes, freshness,
explainability in 30-40 spoken seconds, and real visual proof availability. A high 🔥heat
score means the story is ALREADY getting real traction on Hacker News / Reddit right now —
weight that as strong evidence of viral potential, but never pick an unexplainable or
purely-technical story just because it's hot.
Follow this house strategy exactly:

{strategy_skill()}
{learnings_block("scouting")}

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
