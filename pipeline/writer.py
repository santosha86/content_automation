"""Writer: turn a picked article into a segmented shorts script + platform metadata."""
from .util import llm_json, settings, style_guide


def write_script(topic: dict) -> dict:
    cfg = settings()["video"]
    script = llm_json(
        f"""Write a script for a {cfg['target_seconds']}-second vertical video (YouTube Short / IG Reel).

SOURCE ARTICLE
Title: {topic['title']}
Source: {topic['source']}
Summary: {topic['summary']}
URL: {topic['url']}

FOLLOW THIS STYLE GUIDE EXACTLY:
{style_guide()}

Reply with JSON only:
{{
  "hook_text": "<on-screen hook headline, 4-6 words, reads well when built one word at a time>",
  "segments": [
    {{
      "voiceover": "<1-2 spoken sentences, written to be SAID with the segment's emotion>",
      "emotion": "<one of: excited | curious | serious | amazed | urgent | confident>",
      "broll_query": "<2-3 word stock-video search phrase, visually concrete (e.g. 'server room', 'person typing laptop')>",
      "overlay": "<2-4 word on-screen label, or empty string>"
    }}
  ],
  "youtube": {{"title": "<under 80 chars>", "description": "<2-3 lines + source URL>"}},
  "instagram": {{"caption": "<per style guide>"}},
  "hashtags": ["<4-5 tags without #>"]
}}

Use 4 to {cfg['max_segments']} segments. Total spoken length must fit ~{cfg['target_seconds']} seconds
(~{int(cfg['target_seconds'] * 2.5)} words total). The first segment IS the hook.
The LAST segment's overlay must be the CTA as 3-5 punchy words (e.g. "COMMENT AI FOR GUIDE") —
it is rendered in the same kinetic style as the hook (bookend rule).""",
        system="You are an expert short-form video scriptwriter. Output valid JSON only.",
        station="writer",
    )
    script["topic"] = topic
    return script
