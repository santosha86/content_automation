"""Writer + Critic loop: draft narrative beats, grade them against the retention
structure, and rewrite until they pass (or the round budget runs out).

The Writer drafts ordered beats (narration + emotion + pacing); the Critic scores
them against the strategy skill's retention structure and fabrication guardrail and
hands back concrete fixes. This is the loop that makes the *words* good before the
Director ever plans a single frame.
"""
import json

from .util import llm, llm_json, settings, strategy_skill, style_guide

# The named checks the Critic must grade every draft on — lifted straight from the
# retention structure + guardrails in the strategy skill.
RETENTION_CHECKS = [
    "hook_earns_next_3s",     # 0-2s: opens on the surprising concrete thing, not context
    "context_concrete_2_8s",  # one concrete sentence of what actually happened
    "escalating_specifics",   # 8-30s: each beat raises stakes or reveals a detail
    "no_repeated_emotion",    # never two consecutive beats with the same emotion
    "payoff_you_frame",       # 30-38s: what it means for the viewer ("you")
    "cta_bookend",            # last beat is a 3-5 word CTA in hook style
    "fits_30_40s",            # total spoken ~30-40s
    "no_fabrication",         # every claim traces to the source; opinion may be hyperbolic
]


def _draft(story: dict, hook: dict, fixes: list[str]) -> dict:
    cfg = settings()["video"]
    fix_block = ""
    if fixes:
        fix_block = "\nThe Critic rejected the last draft. Fix EXACTLY these, keep the rest:\n" + \
            "\n".join(f"- {f}" for f in fixes)
    return llm_json(
        f"""You are the Writer for a {cfg['target_seconds']}s vertical AI-news Short.
Turn the story + chosen hook into ordered narrative BEATS.

STORY
Title: {story['title']}
Summary: {story.get('summary', '')}
Source: {story.get('url', '')}
Name anchor: {story.get('name_anchor', '') or '(none)'}

CHOSEN HOOK (beat 1 narration must land this, spoken): "{hook['text']}"

STYLE GUIDE:
{style_guide()}

STRATEGY (retention structure + guardrails — obey exactly):
{strategy_skill()}
{fix_block}

Reply with JSON only:
{{
  "framing_notes": "<how claims must be framed, e.g. 'reported allegation, not proven'>",
  "sources": ["<url every factual claim traces to>"],
  "beats": [
    {{
      "narration": "<exact spoken voiceover, 1-2 sentences said with the emotion>",
      "emotion": "<excited|curious|serious|amazed|urgent|confident>",
      "est_seconds": <number>,
      "music_intensity": <0-3, rising with the stakes>,
      "overlay": "<2-4 word on-screen chip, empty for none; last beat overlay = CTA>"
    }}
  ]
}}
Use 3 to {cfg['max_segments']} beats totaling ~{cfg['target_seconds']}s
(~{int(cfg['target_seconds'] * 2.5)} words). Never repeat an emotion back-to-back.
The last beat's overlay is the CTA (3-5 punchy words, hook style).""",
        system="You are an expert short-form scriptwriter. Output valid JSON only.",
        station="writer",
    )


def _critique(story: dict, hook: dict, draft: dict) -> dict:
    return llm_json(
        f"""You are the Critic. Grade this beat draft against the retention structure
and fabrication guardrail. Be strict — a draft passes only if it would actually hold
a viewer for the full 30-40s and states nothing the source doesn't support.

STRATEGY (the standard you grade against):
{strategy_skill()}

STORY SUMMARY (the only facts allowed): {story.get('summary', '')}
CHOSEN HOOK: "{hook['text']}"
DRAFT BEATS:
{json.dumps(draft.get('beats', []), indent=2)}
FRAMING NOTES: {draft.get('framing_notes', '')}

Grade each of these named checks true/false with a one-line note:
{json.dumps(RETENTION_CHECKS)}

Reply with JSON only:
{{
  "pass": <true only if EVERY check passes>,
  "score": <0-100>,
  "checks": [{{"name": "<check name>", "pass": <bool>, "note": "<one line>"}}],
  "fixes": ["<specific, actionable fix>", ...]
}}""",
        system="You are a demanding short-form content critic. Output valid JSON only.",
        station="reviewer",
    )


def write_and_critique(story: dict, hook: dict, max_rounds: int = 3, log=print) -> dict:
    """Draft → grade → rewrite until the Critic passes or `max_rounds` is spent.

    Returns the best draft plus the loop record:
      {beats, framing_notes, sources, critique, rounds, passed}
    """
    fixes: list[str] = []
    best = None
    best_score = -1
    critique = {}
    for rnd in range(1, max_rounds + 1):
        draft = _draft(story, hook, fixes)
        critique = _critique(story, hook, draft)
        score = int(critique.get("score", 0))
        log(f"      critic round {rnd}: score {score}/100, pass={critique.get('pass')}")
        if score > best_score:
            best, best_score = draft, score
        if critique.get("pass"):
            best = draft
            break
        fixes = critique.get("fixes", [])[:6]

    return {
        "beats": best.get("beats", []),
        "framing_notes": best.get("framing_notes", ""),
        "sources": best.get("sources", []) or [story.get("url", "")],
        "critique": critique,
        "rounds": rnd,
        "passed": bool(critique.get("pass")),
    }


if __name__ == "__main__":
    from . import hooksmith, strategist
    story = strategist.top_stories(1)[0]
    hook = hooksmith.make_hooks(story)[0]
    out = write_and_critique(story, hook)
    print(f"\nPassed: {out['passed']} in {out['rounds']} round(s), score {out['critique'].get('score')}")
    for i, b in enumerate(out["beats"], 1):
        print(f"  {i}. [{b['emotion']}] {b['narration']}  (overlay: {b.get('overlay','')})")
