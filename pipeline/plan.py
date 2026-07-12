"""Director pipeline: story -> hook -> script -> validated storyboard.

This is Phase A's brain path. It produces `storyboard.json` (the Director's contract)
plus a `plan.json` audit trail, honoring the checkpoints in controls.yaml:
  story_pick   -> which of the Strategist's top-3 to make
  hook_pick    -> which of the 3 hook variants leads
  script_approval    -> accept the Critic-passed script (or regenerate)
  storyboard_approval -> accept the validated storyboard

Usage:
  python -m pipeline.plan                  # Strategist picks from both lanes
  python -m pipeline.plan --topic "..."    # skip the Strategist, plan this topic
"""
import argparse
import datetime
import json
import re

from . import checkpoints, director, hooksmith, scriptwriter, strategist, usage, virality
from .util import ROOT


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def _build_for_story(story: dict, log=print) -> dict:
    """hook -> script -> validated storyboard for one story. Raises on a failure the
    caller can recover from by trying the next candidate (e.g. a thin story the Director
    can't turn into a schema-valid storyboard)."""
    # 2. Hook Smith
    log("[2/4] hook smith: 3 variants...")
    hooks = hooksmith.make_hooks(story)
    for h in hooks:
        log(f"      #{h['variant_rank']} [{h['type']}] ({h['formula']}) \"{h['text']}\"")
    hidx = checkpoints.resolve(
        "hook_pick",
        [{"label": h["text"], "detail": f"{h['formula']} — {h['rationale']}"} for h in hooks],
        prompt="Which hook leads?", log=log,
    )
    hook = hooks[hidx]
    log(f"      -> hook: \"{hook['text']}\"")

    # 3. Writer + Critic
    log("[3/4] writer+critic: drafting and grading beats...")
    script = scriptwriter.write_and_critique(story, hook, log=log)
    log(f"      -> {len(script['beats'])} beats, critic pass={script['passed']} "
        f"(score {script['critique'].get('score')})")
    sidx = checkpoints.resolve(
        "script_approval",
        [{"label": "Accept this script", "detail": f"{len(script['beats'])} beats, "
          f"score {script['critique'].get('score')}"},
         {"label": "Regenerate", "detail": "Run the writer+critic loop again"}],
        prompt="Accept the script?", log=log,
    )
    if sidx == 1:
        log("      regenerating script...")
        script = scriptwriter.write_and_critique(story, hook, log=log)

    # 4. Director — validated storyboard (raises if it never validates)
    log("[4/4] director: building + validating storyboard...")
    storyboard = director.build_storyboard(story, hook, script, log=log)
    checkpoints.resolve(
        "storyboard_approval",
        [{"label": "Approve storyboard", "detail": storyboard["concept"].get("metaphor", "")},
         {"label": "Approve (only option)", "detail": "Storyboard already schema-valid"}],
        prompt="Approve the storyboard?", log=log,
    )
    return {"hooks": hooks, "hook": hook, "script": script, "storyboard": storyboard}


def plan(topic: str = "", article_url: str = "", log=print) -> dict:
    checkpoints.clear()

    # 1. Strategist — top-3 across lanes, honoring story_pick.
    if topic:
        stories = [{"lane": "ai_news", "source": "manual", "title": topic,
                    "summary": topic, "url": article_url,
                    "key": strategist.scout._key({"link": article_url or topic}),
                    "rank": 1, "why": "manual override", "name_anchor": ""}]
        log(f"[1/4] strategist: manual topic -> {topic}")
    else:
        log("[1/4] strategist: ranking top-3 across ai_news + github_trending...")
        stories = strategist.top_stories(3)
        for s in stories:
            log(f"      #{s['rank']} [{s['lane']}] {s['title']}  ({s['name_anchor'] or 'no anchor'})")
        # Virality pre-check: score each candidate, re-rank by potential, flag weak ones
        # BEFORE we commit a render to them.
        log("      virality pre-check (will it perform?)...")
        stories = virality.score_candidates(stories, log=log)
        top = stories[0]["virality"]
        if top["score"] < virality.min_score():
            log(f"      ⚠️  best candidate scores {top['score']}/100 (< {virality.min_score()} floor) — "
                f"weak news day; consider a manual topic. Reason: {top.get('risks','')}")
    def _story_detail(s):
        v = s.get("virality") or {}
        if not v:
            return s["why"]
        return f"{virality.emoji(v.get('verdict',''))} {v['score']}/100 · {v.get('best_angle') or s['why']}"
    idx = checkpoints.resolve(
        "story_pick",
        [{"label": f"[{s['lane']}] {s['title']}", "detail": _story_detail(s)} for s in stories],
        prompt="Which story should we make?", log=log,
    )
    log(f"      -> story: {stories[idx]['title']}")

    # Build the chosen story; if a thin/messy story can't be turned into a valid storyboard,
    # fall back to the next-best candidate instead of crashing the run. Try up to 3.
    order = [stories[idx]] + [s for i, s in enumerate(stories) if i != idx]
    story, built, last_err = None, None, None
    for attempt, cand in enumerate(order[:3], start=1):
        if attempt > 1:
            log(f"\n↻ that story couldn't be built into a valid video — falling back to "
                f"next-best: {cand['title']}")
        try:
            built = _build_for_story(cand, log=log)
            story = cand
            break
        except Exception as e:
            last_err = e
            log(f"      ✗ couldn't build this story ({str(e)[:140]})")
            continue
    if built is None:
        raise RuntimeError(
            f"None of the top candidates could be built into a valid storyboard "
            f"(tried {min(3, len(order))}). Last error: {last_err}")
    strategist.mark_picked(story)
    hooks, hook, script, storyboard = built["hooks"], built["hook"], built["script"], built["storyboard"]

    # Persist the brain artifact + audit trail.
    slug = f"{datetime.date.today()}-{_slugify(story['title'])}"
    run_dir = ROOT / "output" / "runs" / slug
    run_dir.mkdir(parents=True, exist_ok=True)
    usage.bind(run_dir, phase="plan")  # flush buffered strategist/hook/writer/director records
    (run_dir / "storyboard.json").write_text(json.dumps(storyboard, indent=2))
    (run_dir / "plan.json").write_text(json.dumps({
        "story": story, "candidates_top3": [s["title"] for s in stories] if not topic else [topic],
        "hooks": hooks if not topic else [], "hook": hook, "critique": script["critique"],
    }, indent=2))
    log(f"\nDONE  ->  {run_dir}/storyboard.json")
    return storyboard


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", default="", help="skip the Strategist; plan this topic")
    ap.add_argument("--article-url", default="", help="source url for a manual topic")
    args = ap.parse_args()
    plan(args.topic, args.article_url)


if __name__ == "__main__":
    main()
