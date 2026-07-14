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

from . import entities
from .util import ROOT, learnings_block, llm_json, settings, strategy_skill

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
    # Entity anchoring: the brands this story is actually about, each with a page they OWN.
    names = entities.detect(
        scaffold["topic"]["title"], scaffold["topic"]["framing_notes"],
        scaffold["hook"]["text"], *[b["narration"] for b in scaffold["beats"]],
    )
    entity_names = ", ".join(names) if names else "(none)"
    return llm_json(
        f"""You are the Director. The story, hook, and narration are LOCKED. Author only
the VISUAL through-line for this vertical AI-news Short.

TOPIC: {scaffold['topic']['title']}
NAME ANCHOR: {scaffold['topic']['name_anchor'] or '(none)'}
FRAMING: {scaffold['topic']['framing_notes']}
HOOK ({scaffold['hook']['type']}): "{scaffold['hook']['text']}"
BEATS (narration is fixed — plan a frame for each):
{beat_lines}

ENTITIES IN THIS STORY (the protagonist is first):
{entities.brief(names)}

ENTITY ANCHORING — THE RULE THAT MATTERS MOST:
When a beat NAMES a company, the frame MUST SHOW THAT COMPANY. Not the theme it belongs to.
"Meta built its own chip" => show Meta (its page, its product, its logo) — NOT a generic
data-center hallway. A themed stock shot while the voice says a brand name is the single
biggest quality failure in this format: it reads as filler and the viewer scrolls.
  - Set each shot's `entity` to the company that shot must show, EXACTLY as spelled in the
    ENTITIES list above ({entity_names}). Leave it "" only for shots that genuinely show no
    company (a person's hands, a chart, an abstract consequence).
  - Every shot whose `phrase` mentions a company MUST carry that company's `entity`.
  - The strongest anchor is a screen_capture of the company's OWN page (URLs listed above —
    they are screenshot-safe). Use it for at least one shot of the protagonist.
  - A shot carrying an `entity` gets that brand's REAL logo composited on the frame
    automatically — so you do NOT need to describe a logo in the image prompt (generated
    logos come out as garbled fakes). Describe the SCENE; the real mark is added for you.

STRATEGY (b-roll must show the subject, not the theme):
{strategy_skill()}
{learnings_block("director_realism")}

Design ONE continuous visual concept (a single authored idea carrying the whole video,
not a slideshow), and for EACH beat a visual + composition that serves it.

REALISM IS THE #1 RULE — footage must look SHOT ON A CAMERA, never AI-generated. The whole
video fails the moment a frame looks synthetic/fancy. So every generated_image prompt must
read like a real photograph of an ordinary scene:
  - Lead every prompt with a realism anchor: "Photorealistic candid photo, natural light,"
    (or "documentary photo", "smartphone photo", "over-the-shoulder shot"). Shoot mundane,
    believable, everyday scenes — a real desk, a real screen, a real office, real hands
    typing — the kind of B-roll a human editor would film.
  - BANNED vocabulary (these are what SCREAM "AI art" — never use them): glowing, holographic,
    translucent, neon, futuristic, sci-fi, cyberpunk, neural core, floating UI, particle
    effects, energy, aura, cinematic teal-and-orange, 3D render, digital art, concept art,
    surreal, hyper-detailed, octane, unreal engine.
  - Bias toward SCENES and OBJECTS and over-the-shoulder framing. AVOID close-up faces and
    close-up hands — those carry the worst AI tells (bad fingers, uncanny eyes). A laptop on
    a desk beats a person's face; a screen beats a portrait.
  - NEVER put readable text on a screen or paper in a generated_image — the model renders it
    as gibberish, the #1 giveaway. If a screen/document is in frame, describe it as OUT OF
    FOCUS, showing a simple chart/graph, a blurred UI, or angled away — never "a screen
    showing a notice/article/message/paragraph". When you need to show real on-screen text
    (a notice, a headline, a repo), that's a screen_capture shot of a real page, not FLUX.

A/B ROUTING — prefer REAL PROOF over generation, but ONLY from cleanly-screenshottable pages:
  - GOOD screen_capture targets (open, no paywall, no bot-wall): GitHub repos, product/docs
    landing pages, a company's own launch blog post, pricing pages, changelogs, model cards
    on huggingface. For these, set the shot's source to "screen_capture" and put the exact
    URL in its `query`. A screenshot of the actual thing beats any generated frame.
  - DO NOT screen_capture news aggregators or paywalled/bot-protected sites (businessinsider,
    nytimes, bloomberg, wsj, theinformation, medium, most openai.com pages behind Cloudflare)
    — they return a paywall or a "Verifying you are human" page, not the content. If the beat
    is about a company's announcement, screen_capture the COMPANY's OWN page (e.g. the vendor's
    product/blog URL), not the news article. If no clean official page exists, use a realistic
    generated_image instead. The TOPIC source_url is {scaffold['topic']['source_url'] or '(none)'} — only reuse it if it is an official/open page, not a news site.
  - Use "generated_image" (a realistic photo, per the rules above) for abstract beats and
    whenever the only source is a paywalled/bot-walled page.
  - Use "broll_video" for generic motion (typing, city, servers) that stock footage covers.

CRUCIAL — cut with the words: split each beat's narration into 1-3 short PHRASES and give
each phrase its own shot whose imagery shows THAT phrase's concrete subject. This is what
keeps images in sync with the script and makes the cut rhythm feel human (every ~2-4s), not
one static clip per beat. A one-idea beat may have a single shot; a beat that names two
things (a company AND a product, a cause AND an effect) should have a shot for each. Every
shot's `phrase` must be an exact substring of that beat's narration.

Reply with JSON only:
{{
  "concept": {{
    "metaphor": "<one continuous visual idea>",
    "escalation": "<how the imagery evolves across beats with the stakes>",
    "continuity": "<a REALISTIC recurring style anchor prepended to every image prompt — e.g. 'Photorealistic candid photography, natural daylight, muted real-world colors, shallow depth of field'. No fancy/sci-fi words.>",
    "negative_prompt": "<global negatives — always include these AI-art tells: glowing, holographic, neon, cinematic, 3d render, cgi, digital art, illustration, deformed hands, extra fingers, embedded text, logos, watermarks, oversaturated, plastic skin>"
  }},
  "beats": [
    {{
      "id": <int matching the beat>,
      "visual": {{
        "source": "broll_video|broll_image|generated_image|face|screen_capture",
        "query": "<stock query tied to the beat's concrete subject; for generated_image leave empty>",
        "prompt": "<image-gen prompt when source=generated_image, else empty>",
        "must_show": "<the one thing the frame MUST contain for the beat to make sense>",
        "shots": [
          {{
            "phrase": "<the exact run of words from THIS beat's narration this shot covers>",
            "source": "broll_video|generated_image|screen_capture",
            "query": "<stock query for this phrase's concrete subject>",
            "prompt": "<image-gen prompt if source=generated_image, else empty>",
            "must_show": "<the one thing this shot must show>",
            "entity": "<the company this shot must show, spelled exactly as in the ENTITIES
              list; "" only if the shot genuinely shows no company. Its real logo is
              composited onto the frame for you — never describe a logo in the prompt.>",
            "camera": "none|zoom_in|zoom_out|punch_in",
            "motion": <true ONLY for a source=generated_image shot that genuinely needs REAL
              movement — an action happening, a process, motion the eye expects. NEVER set
              motion:true on a screen_capture or broll_video shot (they can't be animated — it
              wastes the flag). Else omit or false. Mark AT MOST 2 shots in the WHOLE video as
              motion:true — these are the ones worth animating.>"
          }}
        ]
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
        stage="director.storyboard",
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
        visual = lb.get("visual", {"source": "broll_video", "query": beat["narration"][:40]})
        # Drop malformed shots so an odd model reply can't fail schema validation;
        # a beat with no valid shots simply falls back to its single visual.
        shots = [s for s in visual.get("shots", []) if isinstance(s, dict) and s.get("phrase") and s.get("must_show")]
        if shots:
            visual["shots"] = shots[:3]
        else:
            visual.pop("shots", None)
        beat["visual"] = visual
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
            # Entity anchoring is an invariant, not a suggestion — the model proposes the
            # anchors, this corrects them (see entities.normalize).
            fixed = entities.normalize(storyboard)
            anchored = sum(1 for b in storyboard["beats"]
                           for s in b["visual"].get("shots", []) if s.get("entity"))
            total = sum(len(b["visual"].get("shots", [])) for b in storyboard["beats"])
            log(f"      entity anchoring: {anchored}/{total} shots"
                + (f" ({fixed} corrected)" if fixed else ""))
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
