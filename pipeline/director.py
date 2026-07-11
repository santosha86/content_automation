"""Director: assemble the validated storyboard — the pipeline's brain artifact.

The upstream stations hand the Director hard content: a chosen story, a chosen hook,
and Critic-approved beats (narration + emotion, verbatim). The Director's job is the
*visual through-line*: one continuous concept, and per-beat visual + composition that
serve it. It fills only the visual layer, merges it onto the locked narration, then
validates the whole storyboard against config/storyboard.schema.json — retrying with
the validator's own errors fed back until it conforms.
"""
import json

import jsonschema

from .util import ROOT, llm_json, settings, strategy_skill

SCHEMA_PATH = ROOT / "config" / "storyboard.schema.json"


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def validate(storyboard: dict) -> list[str]:
    """Return a list of human-readable schema errors ([] means valid)."""
    validator = jsonschema.Draft202012Validator(_schema())
    errors = sorted(validator.iter_errors(storyboard), key=lambda e: list(e.path))
    return [f"{'/'.join(str(p) for p in e.path) or '(root)'}: {e.message}" for e in errors]


def _scaffold(story: dict, hook: dict, script: dict) -> dict:
    """Deterministic skeleton: locks topic, hook, and narration so the LLM can only
    author the visual layer — narration integrity is never at the model's mercy."""
    beats = []
    for i, b in enumerate(script["beats"], start=1):
        beats.append({
            "id": i,
            "narration": b["narration"],
            "emotion": b["emotion"],
            "est_seconds": float(b.get("est_seconds", 6)),
            "music_intensity": int(b.get("music_intensity", 1)),
            "overlay": b.get("overlay", ""),
        })
    return {
        "topic": {
            "title": story["title"],
            "source_url": story.get("url", ""),
            "lane": story.get("lane", "ai_news"),
            "name_anchor": story.get("name_anchor", ""),
            "framing_notes": script.get("framing_notes", ""),
            "sources": script.get("sources", []),
        },
        "hook": {
            "type": hook.get("type", "kinetic_text"),
            "text": hook["text"],
            "variant_rank": int(hook.get("variant_rank", 1)),
            "rationale": hook.get("rationale", ""),
        },
        "beats": beats,
    }


def _visual_layer(scaffold: dict, fix_note: str = "") -> dict:
    """Ask the Director for concept + per-beat visual/composition + music + cta."""
    beat_lines = "\n".join(
        f'  beat {b["id"]} [{b["emotion"]}]: "{b["narration"]}" (overlay: {b["overlay"] or "-"})'
        for b in scaffold["beats"]
    )
    return llm_json(
        f"""You are the Director. The story, hook, and narration are LOCKED. Author only
the VISUAL through-line for this vertical AI-news Short.

TOPIC: {scaffold['topic']['title']}
NAME ANCHOR: {scaffold['topic']['name_anchor'] or '(none)'}
FRAMING: {scaffold['topic']['framing_notes']}
HOOK ({scaffold['hook']['type']}): "{scaffold['hook']['text']}"
BEATS (narration is fixed — plan a frame for each):
{beat_lines}

STRATEGY (b-roll must show the subject, not the theme):
{strategy_skill()}

Design ONE continuous visual concept (a single authored idea carrying the whole video,
not a slideshow), and for EACH beat a visual + composition that serves it.

Reply with JSON only:
{{
  "concept": {{
    "metaphor": "<one continuous visual idea>",
    "escalation": "<how the imagery evolves across beats with the stakes>",
    "continuity": "<exact recurring character/object/style, prepended to every image prompt>",
    "negative_prompt": "<global negatives: deformed anatomy, embedded text, logos, watermarks...>"
  }},
  "beats": [
    {{
      "id": <int matching the beat>,
      "visual": {{
        "source": "broll_video|broll_image|generated_image|face|screen_capture",
        "query": "<stock query tied to the beat's concrete subject; for generated_image leave empty>",
        "prompt": "<image-gen prompt when source=generated_image, else empty>",
        "must_show": "<the one thing the frame MUST contain for the beat to make sense>"
      }},
      "composition": {{
        "layout": "full|split_face_bottom|split_face_top|pip_face",
        "camera": "none|zoom_in|zoom_out|punch_in",
        "transition_in": "cut|flash"
      }}
    }}
  ],
  "music": {{"mood": "driving|suspense|uplift|tech_minimal|none", "duck_under_voice": true, "end_with_silence": true}},
  "cta": {{"text": "<3-5 punchy words>", "ask": "follow|comment|share|link"}}
}}
Use transition_in "flash" only on the hook->body cut (beat 2). {fix_note}""",
        system="You are a short-form video Director. Output valid JSON only.",
        station="writer",
    )


def _merge(scaffold: dict, layer: dict) -> dict:
    """Fold the LLM's visual layer onto the locked scaffold into a full storyboard."""
    sb = dict(scaffold)
    sb["concept"] = layer.get("concept", {})
    sb["music"] = layer.get("music", {"mood": "tech_minimal"})
    sb["cta"] = layer.get("cta") or {"text": scaffold["beats"][-1]["overlay"] or "Follow for more", "ask": "follow"}
    by_id = {b.get("id"): b for b in layer.get("beats", [])}
    for beat in sb["beats"]:
        lb = by_id.get(beat["id"], {})
        beat["visual"] = lb.get("visual", {"source": "broll_video", "query": beat["narration"][:40]})
        beat["composition"] = lb.get("composition", {"layout": "full"})
    return sb


def build_storyboard(story: dict, hook: dict, script: dict, max_retries: int = 3, log=print) -> dict:
    """Produce a storyboard that validates against the schema, retrying on errors."""
    scaffold = _scaffold(story, hook, script)
    fix_note = ""
    storyboard = None
    for attempt in range(1, max_retries + 1):
        layer = _visual_layer(scaffold, fix_note)
        storyboard = _merge(scaffold, layer)
        errors = validate(storyboard)
        if not errors:
            log(f"      storyboard valid on attempt {attempt}")
            return storyboard
        log(f"      storyboard invalid (attempt {attempt}): {len(errors)} error(s)")
        fix_note = "The previous attempt failed schema validation. Fix exactly these and " \
            "return the SAME shape:\n" + "\n".join(f"- {e}" for e in errors[:12])

    # Exhausted retries — surface the errors rather than shipping a broken contract.
    errors = validate(storyboard)
    raise RuntimeError("Storyboard never validated:\n" + "\n".join(errors[:12]))


if __name__ == "__main__":
    from . import hooksmith, scriptwriter, strategist
    story = strategist.top_stories(1)[0]
    hook = hooksmith.make_hooks(story)[0]
    script = scriptwriter.write_and_critique(story, hook)
    sb = build_storyboard(story, hook, script)
    print(json.dumps(sb, indent=2)[:2000])
    print("\nVALID:", not validate(sb))
