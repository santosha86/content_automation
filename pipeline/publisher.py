"""Publisher (Phase C) — upload a finished video to YouTube + Instagram.

CODE-ONLY / TRIALS: nothing is posted unless you (1) add the platform credentials to
.env AND (2) set PUBLISH_LIVE=1. With no keys it runs a DRY RUN that prints exactly what
WOULD be posted, so you can wire and eyeball it before spending a real publish. Publishing
stays a manual, human-approved step (the `publish` checkpoint defaults to manual).

Credentials (add to .env when ready):
  # YouTube Data API v3 (OAuth — one-time: create a Desktop client, authorize the
  # youtube.upload scope, store the refresh token)
  YOUTUBE_CLIENT_ID=...
  YOUTUBE_CLIENT_SECRET=...
  YOUTUBE_REFRESH_TOKEN=...
  YOUTUBE_PRIVACY=private        # private | unlisted | public (trials: keep private)
  YOUTUBE_CATEGORY_ID=28         # 28 = Science & Technology
  # Instagram Graph API (Reels) — needs a Business/Creator IG account linked to a FB page,
  # and the video reachable at a PUBLIC url (IG fetches it; it can't take a local file)
  IG_USER_ID=...
  IG_ACCESS_TOKEN=...
  IG_PUBLIC_VIDEO_URL=...        # public https url of THIS video (or a base you template)

Usage:
  python -m pipeline.publisher <slug> [--platforms youtube,instagram] [--live]
"""
import json
import os
import time
from pathlib import Path

import requests

from .util import ROOT

REVIEW_DIR = ROOT / "output" / "review"


def _is_live() -> bool:
    return os.getenv("PUBLISH_LIVE", "").lower() in ("1", "true", "yes")


def _load(slug: str) -> tuple[Path, dict]:
    folder = REVIEW_DIR / slug
    video = folder / f"{slug}.mp4"
    meta_path = folder / "metadata.json"
    if not video.exists():
        raise FileNotFoundError(f"no video at {video}")
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    return video, meta


# ---------------- YouTube ----------------

def _youtube_creds() -> dict | None:
    keys = ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")
    if not all(os.getenv(k) for k in keys):
        return None
    return {k: os.environ[k] for k in keys}


def _youtube_access_token(creds: dict) -> str:
    resp = requests.post("https://oauth2.googleapis.com/token", timeout=30, data={
        "client_id": creds["YOUTUBE_CLIENT_ID"],
        "client_secret": creds["YOUTUBE_CLIENT_SECRET"],
        "refresh_token": creds["YOUTUBE_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    })
    resp.raise_for_status()
    return resp.json()["access_token"]


def publish_youtube(video: Path, meta: dict, live: bool) -> dict:
    yt = (meta.get("youtube") or {})
    title = (yt.get("title") or meta.get("hook_text") or video.stem)[:100]
    description = yt.get("description", "")
    tags = meta.get("hashtags", [])[:15]
    body = {
        "snippet": {"title": title, "description": description, "tags": tags,
                    "categoryId": os.getenv("YOUTUBE_CATEGORY_ID", "28")},
        "status": {"privacyStatus": os.getenv("YOUTUBE_PRIVACY", "private"),
                   "selfDeclaredMadeForKids": False},
    }
    creds = _youtube_creds()
    if not creds or not live:
        return {"platform": "youtube", "status": "dry_run",
                "reason": "no YOUTUBE_* creds" if not creds else "PUBLISH_LIVE not set",
                "would_post": {"title": title, "privacy": body["status"]["privacyStatus"],
                               "tags": tags, "bytes": video.stat().st_size}}
    # Resumable upload: initiate a session, then PUT the bytes.
    token = _youtube_access_token(creds)
    init = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos",
        params={"uploadType": "resumable", "part": "snippet,status"},
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                 "X-Upload-Content-Type": "video/mp4"},
        data=json.dumps(body), timeout=60,
    )
    init.raise_for_status()
    upload_url = init.headers["Location"]
    with open(video, "rb") as f:
        up = requests.put(upload_url, headers={"Content-Type": "video/mp4"}, data=f, timeout=1800)
    up.raise_for_status()
    vid = up.json().get("id")
    return {"platform": "youtube", "status": "published", "id": vid,
            "url": f"https://youtu.be/{vid}" if vid else None}


# ---------------- Instagram ----------------

def _instagram_creds() -> dict | None:
    keys = ("IG_USER_ID", "IG_ACCESS_TOKEN")
    if not all(os.getenv(k) for k in keys):
        return None
    return {k: os.environ[k] for k in keys}


def publish_instagram(video: Path, meta: dict, live: bool) -> dict:
    caption = (meta.get("instagram") or {}).get("caption", "") or meta.get("hook_text", "")
    tags = meta.get("hashtags", [])
    if tags:
        caption = caption.rstrip() + "\n\n" + " ".join(f"#{t.lstrip('#')}" for t in tags)
    creds = _instagram_creds()
    public_url = os.getenv("IG_PUBLIC_VIDEO_URL", "")
    if not creds or not public_url or not live:
        reason = ("no IG_* creds" if not creds else
                  "no IG_PUBLIC_VIDEO_URL (IG must fetch the file from a public https url)"
                  if not public_url else "PUBLISH_LIVE not set")
        return {"platform": "instagram", "status": "dry_run", "reason": reason,
                "would_post": {"caption": caption[:200], "video_url": public_url or "(none)"}}
    base = "https://graph.facebook.com/v21.0"
    # 1) create a REELS media container
    c = requests.post(f"{base}/{creds['IG_USER_ID']}/media", timeout=60, data={
        "media_type": "REELS", "video_url": public_url, "caption": caption,
        "access_token": creds["IG_ACCESS_TOKEN"]})
    c.raise_for_status()
    container = c.json()["id"]
    # 2) poll until the container finishes processing
    for _ in range(30):
        st = requests.get(f"{base}/{container}", timeout=30,
                          params={"fields": "status_code", "access_token": creds["IG_ACCESS_TOKEN"]})
        code = st.json().get("status_code")
        if code == "FINISHED":
            break
        if code == "ERROR":
            return {"platform": "instagram", "status": "error", "reason": "container processing failed"}
        time.sleep(5)
    # 3) publish
    pub = requests.post(f"{base}/{creds['IG_USER_ID']}/media_publish", timeout=60, data={
        "creation_id": container, "access_token": creds["IG_ACCESS_TOKEN"]})
    pub.raise_for_status()
    return {"platform": "instagram", "status": "published", "id": pub.json().get("id")}


# ---------------- orchestrator ----------------

_HANDLERS = {"youtube": publish_youtube, "instagram": publish_instagram}


def publish(slug: str, platforms: list[str] = None, live: bool = None, log=print) -> dict:
    """Publish (or dry-run) a finished video to the given platforms. Writes the outcome to
    output/review/<slug>/publish.json. Safe by default: live only when PUBLISH_LIVE=1."""
    platforms = platforms or ["youtube", "instagram"]
    live = _is_live() if live is None else live
    video, meta = _load(slug)
    log(f"[publisher] {slug}  (live={live})")
    results = []
    for p in platforms:
        handler = _HANDLERS.get(p)
        if not handler:
            results.append({"platform": p, "status": "error", "reason": "unknown platform"})
            continue
        try:
            r = handler(video, meta, live)
        except Exception as e:
            r = {"platform": p, "status": "error", "reason": str(e)[:200]}
        results.append(r)
        tag = r["status"].upper()
        log(f"  {p}: {tag}" + (f" -> {r.get('url') or r.get('id') or r.get('reason','')}"))
    out = {"slug": slug, "live": live, "results": results}
    (REVIEW_DIR / slug / "publish.json").write_text(json.dumps(out, indent=2))
    return out


def status() -> dict:
    """What's configured — used by the dashboard/CLI to show readiness without posting."""
    return {"live": _is_live(),
            "youtube_ready": _youtube_creds() is not None,
            "instagram_ready": _instagram_creds() is not None and bool(os.getenv("IG_PUBLIC_VIDEO_URL"))}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--platforms", default="youtube,instagram")
    ap.add_argument("--live", action="store_true", help="actually post (also needs creds); default is a dry run")
    a = ap.parse_args()
    if a.live:
        os.environ["PUBLISH_LIVE"] = "1"
    print(json.dumps(publish(a.slug, a.platforms.split(",")), indent=2))
