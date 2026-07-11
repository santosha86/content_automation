"""Pipeline runner: topic -> script -> voice -> visuals -> edit -> review folder.

Usage:
  python -m pipeline.run                     # full auto: scout picks today's topic
  python -m pipeline.run --topic "..."       # skip scout, use given topic
  python -m pipeline.run --article-url URL --topic "..."   # manual topic with source
  python -m pipeline.run --storyboard PATH   # render a Director storyboard (skip scout+writer)
"""
import argparse
import datetime
import json
import re

from . import editor, packager, reviewer, scout, storyboard_adapter, usage, visuals, voice, writer
from .util import ROOT, media_duration


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", help="skip scout; write about this topic")
    ap.add_argument("--article-url", default="", help="source url for a manual topic")
    ap.add_argument("--storyboard", default="", help="render a Director storyboard.json (skips scout+writer)")
    args = ap.parse_args()

    if args.storyboard:
        # Director path: a validated storyboard already carries the story + script.
        print("[1/7] director storyboard: loading...")
        storyboard = json.loads(open(args.storyboard).read())
        topic = {"title": storyboard["topic"]["title"], "url": storyboard["topic"].get("source_url", ""),
                 "source": storyboard["topic"].get("lane", "director"), "why": "from storyboard"}
        print(f"      -> {topic['title']}  ({topic['source']})")
        slug = f"{datetime.date.today()}-{_slugify(topic['title'])}"
        run_dir = ROOT / "output" / "runs" / slug
        run_dir.mkdir(parents=True, exist_ok=True)
        print("[2/7] adapter: mapping storyboard -> render script...")
        script = storyboard_adapter.to_script(storyboard)
        (run_dir / "storyboard.json").write_text(json.dumps(storyboard, indent=2))
    else:
        print("[1/7] scout: picking topic...")
        if args.topic:
            topic = {"title": args.topic, "summary": args.topic, "url": args.article_url,
                     "source": "manual", "why": "manual override"}
        else:
            topic = scout.pick_topic()
        print(f"      -> {topic['title']}  ({topic['source']})")
        print(f"      why: {topic['why']}")

        slug = f"{datetime.date.today()}-{_slugify(topic['title'])}"
        run_dir = ROOT / "output" / "runs" / slug
        run_dir.mkdir(parents=True, exist_ok=True)

        print("[2/7] writer: generating script...")
        script = writer.write_script(topic)
    usage.bind(run_dir, phase="render")  # flush any buffered scout/writer records, then track the render
    (run_dir / "script.json").write_text(json.dumps(script, indent=2))
    print(f"      -> {len(script['segments'])} segments, hook: \"{script['hook_text']}\"")

    print("[3/7] voice: synthesizing narration...")
    seg_audio = voice.synthesize(script, run_dir)
    durations = [media_duration(p) for p in seg_audio]
    print(f"      -> {sum(durations):.1f}s total narration")

    print("[4/7] visuals: gathering b-roll...")
    seg_video = visuals.gather(script, durations, run_dir)

    print("[5/7] editor: assembling video...")
    final = editor.assemble(script, seg_audio, seg_video, run_dir)

    print("[6/7] packager: delivering to review gate...")
    review = packager.deliver(script, final, slug)

    print("[7/7] reviewer: grading against Gate B checklist...")
    reviewer.grade(review / f"{slug}.mp4", run_dir, review, script, slug)

    print(f"\nDONE  ->  {review}/")
    print(f"  video:    {review / (slug + '.mp4')}")
    print(f"  metadata: {review / 'metadata.json'}")
    print("Review the video, then post (auto-publish arrives in Phase 2).")


if __name__ == "__main__":
    main()
