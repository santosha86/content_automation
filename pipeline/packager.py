"""Packager: drop the finished video + platform metadata into the review gate."""
import json
import shutil
from pathlib import Path

from .util import ROOT


def deliver(script: dict, final_video: Path, slug: str) -> Path:
    review = ROOT / "output" / "review" / slug
    review.mkdir(parents=True, exist_ok=True)
    shutil.copy2(final_video, review / f"{slug}.mp4")

    hashtags = " ".join(f"#{t.lstrip('#')}" for t in script.get("hashtags", []))
    meta = {
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
