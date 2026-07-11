"""Analytics (Phase E) — per-video performance, wired for real APIs, DUMMY data for now.

The dashboard needs to show how published videos actually perform (views, retention,
engagement, follower growth) so the future Analyst agent can compare what it PREDICTED
(virality score) against what really happened and tune the strategy.

Right now there's no published-video data, so `metrics(slug, platform)` returns plausible,
STABLE dummy numbers (seeded off the slug, loosely correlated to the video's predicted
virality score so the prediction-vs-reality view is meaningful). To go live, set
ANALYTICS_LIVE=1 + the platform tokens and fill in `_fetch_live()` — that ONE function is
the whole bridge; everything above it (server route, UI, totals) stays unchanged.
"""
import hashlib
import json
import os
from pathlib import Path

from .util import ROOT

REVIEW_DIR = ROOT / "output" / "review"
RUNS_DIR = ROOT / "output" / "runs"


def is_live() -> bool:
    return os.getenv("ANALYTICS_LIVE", "").lower() in ("1", "true", "yes")


def _seeded(slug: str, salt: str) -> float:
    """Deterministic 0..1 from slug+salt, so a video's dummy numbers never jump on refresh."""
    h = hashlib.sha1(f"{slug}|{salt}".encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def _predicted_score(slug: str) -> int | None:
    """The virality score we predicted at plan time (plan.json), if available."""
    p = RUNS_DIR / slug / "plan.json"
    if not p.exists():
        return None
    try:
        story = json.loads(p.read_text()).get("story", {})
        return (story.get("virality") or {}).get("score")
    except Exception:
        return None


def _dummy_metrics(slug: str, platform: str) -> dict:
    """Believable, stable per-video metrics. Views lean higher when we predicted a higher
    virality score, so 'predicted vs actual' tells a coherent story."""
    pred = _predicted_score(slug) or 50
    base = _seeded(slug, platform)
    # views: 1k..150k, nudged up by predicted score (0.5x..1.5x)
    views = int((1000 + base * 149000) * (0.5 + pred / 100))
    retention = round(32 + _seeded(slug, platform + "ret") * 43, 1)      # 32%..75% avg view
    ctr = round(3 + _seeded(slug, platform + "ctr") * 9, 1)              # 3%..12%
    like_rate = 0.03 + _seeded(slug, platform + "like") * 0.05
    comment_rate = 0.002 + _seeded(slug, platform + "cmt") * 0.008
    share_rate = 0.004 + _seeded(slug, platform + "shr") * 0.016
    follow_rate = 0.001 + _seeded(slug, platform + "fol") * 0.004
    impressions = int(views / (ctr / 100))
    avg_seconds = 25 * (retention / 100)
    return {
        "platform": platform,
        "views": views,
        "impressions": impressions,
        "ctr_pct": ctr,
        "avg_view_pct": retention,
        "watch_hours": round(views * avg_seconds / 3600, 1),
        "likes": int(views * like_rate),
        "comments": int(views * comment_rate),
        "shares": int(views * share_rate),
        "new_followers": int(views * follow_rate),
    }


def _fetch_live(slug: str, platform: str) -> dict | None:
    """BRIDGE POINT — replace with the real API call when ANALYTICS_LIVE=1.

    YouTube: YouTube Analytics API (reports.query — views, estimatedMinutesWatched,
      averageViewPercentage, likes, comments, shares, subscribersGained) for the video id
      stored in publish.json.
    Instagram: Graph API insights (reach, plays, likes, comments, shares, saves) for the
      media id in publish.json.
    Return the same dict shape as _dummy_metrics(). Return None to fall back to dummy.
    """
    return None  # not wired yet — dashboard uses dummy data until this returns real values


def metrics(slug: str, platform: str) -> dict:
    if is_live():
        live = _fetch_live(slug, platform)
        if live:
            return {**live, "source": "live"}
    return {**_dummy_metrics(slug, platform), "source": "dummy"}


def _title(slug: str) -> str:
    meta = REVIEW_DIR / slug / "metadata.json"
    if meta.exists():
        try:
            m = json.loads(meta.read_text())
            return (m.get("youtube") or {}).get("title") or (m.get("topic") or {}).get("title") or slug
        except Exception:
            pass
    return slug


def overview(platform: str = "youtube") -> dict:
    """Per-video performance for every rendered video, plus roll-up totals. Includes the
    predicted virality score alongside actual views (the Analyst's feedback signal)."""
    videos, tv, twh, tf = [], 0, 0.0, 0
    ret_sum, ret_n = 0.0, 0
    seen_live = False
    if REVIEW_DIR.exists():
        for folder in sorted(REVIEW_DIR.iterdir(), reverse=True):
            if not folder.is_dir():
                continue
            slug = folder.name
            m = metrics(slug, platform)
            if m.get("source") == "live":
                seen_live = True
            pred = _predicted_score(slug)
            row = {"slug": slug, "title": _title(slug), "date": slug[:10],
                   "predicted_score": pred, **m}
            videos.append(row)
            tv += m["views"]; twh += m["watch_hours"]; tf += m["new_followers"]
            ret_sum += m["avg_view_pct"]; ret_n += 1
    return {
        "source": "live" if seen_live else "dummy",
        "platform": platform,
        "totals": {
            "videos": len(videos), "views": tv, "watch_hours": round(twh, 1),
            "new_followers": tf, "avg_retention_pct": round(ret_sum / ret_n, 1) if ret_n else 0,
        },
        "videos": videos,
    }


if __name__ == "__main__":
    import sys
    print(json.dumps(overview(sys.argv[1] if len(sys.argv) > 1 else "youtube"), indent=2)[:2000])
