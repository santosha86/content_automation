"""Scout: pull RSS feeds, dedupe against history, rank for shorts potential."""
import hashlib
import json
import time
from pathlib import Path

import feedparser
import yaml

from .util import ROOT, llm_json, settings

STATE = ROOT / "state" / "seen_topics.json"


def _seen() -> set[str]:
    if STATE.exists():
        return set(json.loads(STATE.read_text()))
    return set()


def _mark_seen(keys: list[str]) -> None:
    STATE.parent.mkdir(exist_ok=True)
    seen = _seen() | set(keys)
    STATE.write_text(json.dumps(sorted(seen)[-2000:]))


def _key(entry) -> str:
    return hashlib.sha1(entry.get("link", entry.get("title", "")).encode()).hexdigest()[:16]


def fetch_candidates() -> list[dict]:
    cfg = settings()["scout"]
    with open(ROOT / "config" / "feeds.yaml") as f:
        feeds = yaml.safe_load(f)["feeds"]
    seen = _seen()
    cutoff = time.time() - cfg["max_age_hours"] * 3600
    out = []
    for feed in feeds:
        parsed = feedparser.parse(feed["url"])
        for e in parsed.entries[:15]:
            published = e.get("published_parsed") or e.get("updated_parsed")
            if published and time.mktime(published) < cutoff:
                continue
            if _key(e) in seen:
                continue
            out.append({
                "key": _key(e),
                "source": feed["name"],
                "title": e.get("title", ""),
                "summary": (e.get("summary", "") or "")[:500],
                "url": e.get("link", ""),
            })
    return out[: cfg["max_candidates"]]


def pick_topic() -> dict:
    candidates = fetch_candidates()
    if not candidates:
        raise RuntimeError("No fresh unseen articles in any feed — widen max_age_hours or add feeds.")
    listing = "\n".join(
        f"{i}. [{c['source']}] {c['title']} — {c['summary'][:200]}" for i, c in enumerate(candidates)
    )
    result = llm_json(
        f"""You pick topics for a daily YouTube Short / Instagram Reel about AI news & tools.
Audience: technical-curious professionals. Pick the ONE article with the highest
shorts potential: surprising, concrete, consequential, explainable in 40 seconds.
Avoid: funding-round news, vague op-eds, incremental benchmark posts.

Articles:
{listing}

Reply with JSON: {{"index": <int>, "why": "<one sentence>"}}""",
        station="scout",
        stage="scout.pick",
    )
    chosen = candidates[int(result["index"])]
    chosen["why"] = result.get("why", "")
    _mark_seen([chosen["key"]])
    return chosen
