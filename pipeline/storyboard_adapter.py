"""Bridge the Director's storyboard into the render path.

voice/visuals/editor/packager/reviewer all consume the legacy `script` shape
(hook_text, segments[voiceover/emotion/broll_query/overlay], topic, youtube,
instagram, hashtags). The storyboard is richer but carries no platform metadata,
so the adapter maps beats->segments and generates the YouTube/IG copy once.

This keeps Phase A's brain artifact authoritative while reusing the Phase-1 renderer
untouched. Per-beat visual craft (generated_image/FLUX, layouts, camera) lands in
Phase B on top of this bridge.
"""
import json

from . import shots as shotplan
from .util import llm_json, style_guide


def _broll_query(beat: dict) -> str:
    """Best stock-search query for a beat, even when the Director planned a generated
    image (FLUX gen isn't wired yet — fall back to must_show, then the narration)."""
    v = beat.get("visual", {})
    return (v.get("query") or v.get("must_show")
            or " ".join(beat.get("narration", "").split()[:6])).strip()


def _platform_meta(storyboard: dict) -> dict:
    """YouTube title/description, IG caption, hashtags — the storyboard schema omits
    these (they're packaging, not direction), so generate them from its content."""
    topic = storyboard["topic"]
    beats = " ".join(b["narration"] for b in storyboard["beats"])
    try:
        return llm_json(
            f"""Write platform metadata for this finished AI-news Short.

TITLE: {topic['title']}
HOOK: {storyboard['hook']['text']}
SCRIPT: {beats}
SOURCE: {topic.get('source_url', '')}

STYLE:
{style_guide()}

Reply JSON only:
{{"youtube": {{"title": "<under 80 chars>", "description": "<2-3 lines + source URL>"}},
  "instagram": {{"caption": "<1 strong line, 2-3 context lines, a question>"}},
  "hashtags": ["<4-5 tags without #>"]}}""",
            system="You write short-form video metadata. Output valid JSON only.",
            station="writer",
        )
    except Exception:
        # Never let metadata generation block a render — ship a usable default.
        return {
            "youtube": {"title": topic["title"][:80],
                        "description": f"{storyboard['hook']['text']}\n\n{topic.get('source_url', '')}"},
            "instagram": {"caption": f"{storyboard['hook']['text']}\n\nWhat do you think?"},
            "hashtags": ["ai", "ainews", "tech", "artificialintelligence"],
        }


def to_script(storyboard: dict) -> dict:
    """Map a validated storyboard onto the legacy render `script` contract."""
    concept = storyboard.get("concept", {})
    segments = []
    for b in storyboard["beats"]:
        planned = shotplan.plan_from_beat(b)
        # Prepend the concept's continuity to every generated-image prompt so identity
        # stays consistent across shots (schema: concept.continuity).
        for s in planned:
            if s["source"] == "generated_image" and s.get("prompt"):
                cont = concept.get("continuity", "")
                s["prompt"] = f"{cont} {s['prompt']}".strip() if cont else s["prompt"]
                s["negative_prompt"] = concept.get("negative_prompt", "")
        segments.append({
            "voiceover": b["narration"],
            "emotion": b.get("emotion", "confident"),
            "broll_query": _broll_query(b),
            "overlay": b.get("overlay", ""),
            "shots": planned,
        })

    meta = _platform_meta(storyboard)
    topic = storyboard["topic"]
    return {
        "hook_text": storyboard["hook"]["text"],
        "segments": segments,
        "topic": {"title": topic["title"], "url": topic.get("source_url", ""),
                  "source": topic.get("lane", "director"), "summary": "", "why": ""},
        "youtube": meta["youtube"],
        "instagram": meta["instagram"],
        "hashtags": meta.get("hashtags", []),
        "music": storyboard.get("music", {}),  # mood drives the Editor's bed selection
        "storyboard": storyboard,  # keep the brain artifact attached for later stages
    }


if __name__ == "__main__":
    import sys
    sb = json.loads(open(sys.argv[1]).read())
    script = to_script(sb)
    print(json.dumps({k: v for k, v in script.items() if k != "storyboard"}, indent=2)[:1500])
