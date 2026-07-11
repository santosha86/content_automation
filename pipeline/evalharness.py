"""Eval harness (stub): run the same story through two providers per station and
save the outputs for a BLIND A/B pick in the dashboard.

Which local model beats the paid API — and where — is an empirical question. This
harness runs a representative generation for each station on ollama (gpt-oss) and on
anthropic, hides the provider behind randomized A/B labels, and writes the pair to
output/evals/<slug>/<station>.json. The dashboard shows A vs B with no provider names;
recording a pick reveals which provider won, feeding the local-first cost policy.

Usage:
  python -m pipeline.evalharness                 # Strategist picks the story
  python -m pipeline.evalharness --topic "..."   # eval a specific topic
  python -m pipeline.evalharness --stations hook # subset of stations
"""
import argparse
import datetime
import json
import random
import re

from .util import ROOT, llm_json, settings, strategy_skill, style_guide

PROVIDERS = ("anthropic", "ollama")
EVAL_DIR = ROOT / "output" / "evals"


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def _hook_prompt(story: dict) -> str:
    return f"""You are the Hook Smith for a daily AI-news Short. Write 3 competing hooks,
each a different formula, 4-6 words, true (opinion may be hyperbolic, events may not
be fabricated), anchored to the famous name when it genuinely fits.

STORY
Title: {story['title']}
Summary: {story.get('summary', '')}
Name anchor: {story.get('name_anchor', '') or '(none)'}

{strategy_skill()}

Reply JSON only: {{"variants":[{{"text":"...","formula":"...","name_anchor":"...","variant_rank":1}}]}}"""


def _script_prompt(story: dict) -> str:
    cfg = settings()["video"]
    return f"""You are the Writer for a {cfg['target_seconds']}s AI-news Short. Turn this
story into ordered narrative beats (narration + emotion), following the retention
structure and never fabricating beyond the summary.

STORY
Title: {story['title']}
Summary: {story.get('summary', '')}

STYLE:
{style_guide()}

STRATEGY:
{strategy_skill()}

Reply JSON only: {{"beats":[{{"narration":"...","emotion":"excited","overlay":"..."}}]}}
Use 3-{cfg['max_segments']} beats; never repeat an emotion back-to-back; last overlay = CTA."""


STATION_PROMPTS = {"hook": _hook_prompt, "script": _script_prompt}


def _run_station(station: str, story: dict) -> dict:
    """Generate the station's output under each provider; capture errors inline so a
    down provider (e.g. ollama not running) never aborts the eval."""
    prompt = STATION_PROMPTS[station](story)
    results = {}
    for provider in PROVIDERS:
        try:
            results[provider] = {"ok": True, "output": llm_json(prompt, provider=provider)}
        except Exception as e:
            results[provider] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return results


def eval_story(story: dict, stations: list[str], log=print) -> dict:
    slug = f"{datetime.date.today()}-{_slugify(story['title'])}"
    out_dir = EVAL_DIR / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    index = {"slug": slug, "story_title": story["title"], "stations": []}

    for station in stations:
        log(f"[eval] {station}: running {' vs '.join(PROVIDERS)}...")
        results = _run_station(station, story)
        # Blind: randomize which provider is A vs B; keep the mapping in `_reveal`
        # so the dashboard can hide it until the user records a pick.
        order = list(PROVIDERS)
        random.shuffle(order)
        record = {
            "station": station,
            "story_title": story["title"],
            "options": {"A": results[order[0]], "B": results[order[1]]},
            "_reveal": {"A": order[0], "B": order[1]},
            "pick": None,
        }
        (out_dir / f"{station}.json").write_text(json.dumps(record, indent=2))
        index["stations"].append(station)
        for lbl in ("A", "B"):
            r = record["options"][lbl]
            log(f"       {lbl}: {'ok' if r['ok'] else r['error']}")

    (out_dir / "index.json").write_text(json.dumps(index, indent=2))
    log(f"\n[eval] saved -> {out_dir}/  (blind A/B — pick the winner in the dashboard)")
    return index


def record_pick(slug: str, station: str, choice: str) -> dict:
    """Record a blind pick ('A'|'B') and reveal which provider won."""
    path = EVAL_DIR / slug / f"{station}.json"
    record = json.loads(path.read_text())
    if choice not in ("A", "B"):
        raise ValueError("choice must be 'A' or 'B'")
    record["pick"] = {"choice": choice, "winner_provider": record["_reveal"][choice]}
    path.write_text(json.dumps(record, indent=2))
    return record["pick"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", default="", help="eval this topic instead of the Strategist's pick")
    ap.add_argument("--stations", default="hook,script", help="comma list: hook,script")
    args = ap.parse_args()
    stations = [s.strip() for s in args.stations.split(",") if s.strip() in STATION_PROMPTS]

    if args.topic:
        story = {"title": args.topic, "summary": args.topic, "lane": "ai_news", "name_anchor": ""}
    else:
        from . import strategist
        story = strategist.top_stories(1)[0]
    eval_story(story, stations)


if __name__ == "__main__":
    main()
