"""Packager: drop the finished video + platform metadata into the review gate."""
import json
import shutil
from pathlib import Path

from .util import ROOT, ffmpeg_bin, media_duration, run_cmd


def _thumbnail(video: Path, out: Path) -> None:
    t = min(1.0, media_duration(video) * 0.05)
    run_cmd([ffmpeg_bin(), "-y", "-ss", f"{t:.2f}", "-i", str(video),
             "-frames:v", "1", "-vf", "scale=360:-2", "-q:v", "4", str(out)])


def deliver(script: dict, final_video: Path, slug: str) -> Path:
    review = ROOT / "output" / "review" / slug
    review.mkdir(parents=True, exist_ok=True)
    video_out = review / f"{slug}.mp4"
    shutil.copy2(final_video, video_out)
    _thumbnail(video_out, review / "thumb.jpg")

    hashtags = " ".join(f"#{t.lstrip('#')}" for t in script.get("hashtags", []))
    meta = {
        "title": script["topic"]["title"],
        "source_article": script["topic"]["url"],
        "youtube": {
            "title": script["youtube"]["title"],
            "description": f"{script['youtube']['description']}\n\n{hashtags}",
        },
        "instagram": {
            "caption": f"{script['instagram']['caption']}\n\n{hashtags}",
        },
        "hook_text": script.get("hook_text", ""),
        "status": "pending_review",
    }
    (review / "metadata.json").write_text(json.dumps(meta, indent=2))
    return review
