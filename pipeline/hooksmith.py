"""Hook Smith: generate 3 competing hook variants for a chosen story.

Each variant uses a DISTINCT formula from the strategy skill, is anchored to the
story's famous name when one genuinely applies, is 4-6 words, and declares a
`type` (kinetic_text | visual_spectacle) matching how it should stop the scroll.

The `hook_pick` checkpoint (auto|manual) decides whether the agent's ranked
variant_rank=1 is taken or the user chooses in the dashboard.
"""
from .util import llm_json, strategy_skill

# Names line up with the storyboard schema's hook.type enum.
_TYPES = ("kinetic_text", "visual_spectacle")


def make_hooks(story: dict) -> list[dict]:
    """Return exactly 3 hook variants, ranked best-first, each with a different formula.

    Variant shape:
      {text, type, formula, name_anchor, rationale, variant_rank}
    """
    anchor = story.get("name_anchor", "")
    result = llm_json(
        f"""You are the Hook Smith for a daily AI-news YouTube Short / Instagram Reel.
Write 3 COMPETING opening hooks for the story below. Each must use a DIFFERENT
formula and must be true — hyperbolic opinion is fine, fabricated events are not.

STORY
Title: {story['title']}
Lane: {story.get('lane', 'ai_news')}
Summary: {story.get('summary', '')}
Name anchor (use when it genuinely fits, never force it): {anchor or '(none)'}

Follow this house strategy exactly — especially the hook formulas, the name-anchor
rule, and the fabrication guardrail:

{strategy_skill()}

Rules:
- Exactly 3 variants, each a DIFFERENT formula (name+shock verb, stakes question,
  insider reveal, number+consequence, you-frame...). Name the formula you used.
- 4-6 words, buildable word-by-word, no punctuation that can't render as a text chip.
- Anchor to the famous name when the story genuinely involves it; leave name_anchor
  empty rather than forcing a mismatched one.
- type: "kinetic_text" when the words are the scroll-stopper (default);
  "visual_spectacle" only when the imagery should carry it and text stays minimal.
- Rank them best-first: variant_rank 1 = strongest.

Reply with JSON only:
{{"variants": [
  {{"text": "<4-6 words>", "type": "kinetic_text|visual_spectacle",
    "formula": "<which formula>", "name_anchor": "<name or empty>",
    "rationale": "<one sentence>", "variant_rank": <1-3>}}
]}}""",
        system="You are an expert short-form hook writer. Output valid JSON only.",
        station="writer",
        stage="hooksmith.variants",
    )

    variants = result.get("variants", [])[:3]
    # Normalize: enforce type enum + sequential ranks so downstream schema stays valid.
    for i, v in enumerate(variants, start=1):
        if v.get("type") not in _TYPES:
            v["type"] = "kinetic_text"
        v["name_anchor"] = v.get("name_anchor", anchor) or anchor
        v.setdefault("formula", "")
        v.setdefault("rationale", "")
    variants.sort(key=lambda v: v.get("variant_rank", 99))
    for i, v in enumerate(variants, start=1):
        v["variant_rank"] = i
    if not variants:
        raise RuntimeError("Hook Smith returned no variants.")
    return variants


if __name__ == "__main__":
    from . import strategist
    story = strategist.top_stories(1)[0]
    print(f"STORY: {story['title']}\n")
    for v in make_hooks(story):
        print(f"#{v['variant_rank']} [{v['type']}] ({v['formula']}) \"{v['text']}\"")
        print(f"    anchor: {v['name_anchor'] or '-'} | {v['rationale']}")
