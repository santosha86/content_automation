"""Reviewer Agent: vision QA of the finished video against Gate B of checklist.schema.json.

Contract: checklist.schema.json (grading items) + reviewer-agent.prompt.md (system prompt).
Gap-only feedback; runs only when ANTHROPIC_API_KEY is set.
"""
import base64
import json
import os
import re
import subprocess
from pathlib import Path

from .util import ROOT, ffmpeg_bin, media_duration, run_cmd, station_provider

FALLBACK_MODEL = "claude-sonnet-5"


def _keyframes(video: Path, run_dir: Path) -> list[tuple[str, Path]]:
    dur = media_duration(video)
    marks = [
        ("frame_0", 0.05),
        ("frames_0_2s_a", 0.9),
        ("frames_0_2s_b", 1.8),
        ("sampled_mid1", dur * 0.35),
        ("broll", dur * 0.55),
        ("outro", dur * 0.85),
        ("last", max(dur - 0.3, 0)),
    ]
    frames = []
    for label, t in marks:
        out = run_dir / f"qa_{label}.jpg"
        run_cmd([ffmpeg_bin(), "-y", "-ss", f"{t:.2f}", "-i", str(video),
                 "-frames:v", "1", "-vf", "scale=540:-2", "-q:v", "4", str(out)])
        frames.append((label, out))
    return frames


def _silence_report(video: Path) -> str:
    proc = subprocess.run(
        [ffmpeg_bin(), "-i", str(video), "-af", "silencedetect=noise=-40dB:d=0.4",
         "-f", "null", "-"],
        capture_output=True, text=True,
    )
    gaps = re.findall(r"silence_(?:start|end): ([\d.]+)", proc.stderr)
    return f"silence gaps >0.4s at (start/end pairs, seconds): {gaps}" if gaps else "no dead-air gaps > 0.4s detected"


def _export_metadata(video: Path, slug: str) -> dict:
    proc = subprocess.run(
        [ffmpeg_bin("ffprobe"), "-v", "quiet", "-show_entries",
         "stream=width,height:format=duration", "-of", "json", str(video)],
        capture_output=True, text=True,
    )
    info = json.loads(proc.stdout)
    stream = next(s for s in info["streams"] if s.get("width"))
    return {
        "width": stream["width"], "height": stream["height"],
        "aspect": f"{stream['width']}:{stream['height']}",
        "duration_s": round(float(info["format"]["duration"]), 1),
        "filename": video.name,
        "filename_convention": f"{slug}.mp4",
    }


def _parse_caption_cues(subs: Path) -> list[dict]:
    """One entry per Caption-style dialogue line, with an explicit word_count
    so B3 grading doesn't have to eyeball adjacent short cues in raw ASS text."""
    cues = []
    for line in subs.read_text().splitlines():
        if not line.startswith("Dialogue: 0,") or ",Caption,,0,0,0,," not in line:
            continue
        head, text = line.split(",Caption,,0,0,0,,", 1)
        _, start, end, *_ = head.split(",")
        clean = re.sub(r"\{[^}]*\}", "", text).strip()
        cues.append({"start": start, "end": end, "text": clean, "word_count": len(clean.split())})
    return cues


def grade(video: Path, run_dir: Path, review_dir: Path, script: dict, slug: str) -> dict | None:
    if station_provider("reviewer", "anthropic") == "skip":
        print("  [reviewer] provider=skip — QA gate disabled in config")
        return None
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("  [reviewer] no ANTHROPIC_API_KEY — skipping QA gate")
        return None
    import anthropic

    checklist = json.loads((ROOT / "checklist.schema.json").read_text())
    gate_b = [i for i in checklist["gates"]["gate_b_pre_publish"] if i["auto_checkable"]]
    system = (ROOT / "reviewer-agent.prompt.md").read_text()

    subs = run_dir / "subs.ass"
    caption_cues = _parse_caption_cues(subs) if subs.exists() else "caption file missing"
    payload = {
        "checklist": gate_b,
        "caption_file": caption_cues,
        "audio_meta": _silence_report(video),
        "export_metadata": _export_metadata(video, slug),
        "script_context": {
            "topic": script["topic"]["title"],
            "hook_text": script.get("hook_text", ""),
            "broll_queries": [s.get("broll_query", "") for s in script["segments"]],
            "note": "Phase 1 pipeline: no face-cam or branded end-card yet (arrive in Phase 2) — grade B4/B8 factually.",
        },
    }
    content = []
    for label, frame in _keyframes(video, run_dir):
        content.append({"type": "text", "text": f"keyframe: {label}"})
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg",
                       "data": base64.b64encode(frame.read_bytes()).decode()},
        })
    content.append({"type": "text", "text": json.dumps(payload, indent=1)})

    client = anthropic.Anthropic()
    model = os.getenv("REVIEWER_MODEL", os.getenv("LLM_MODEL", FALLBACK_MODEL))
    report = None
    for attempt_model in [model, FALLBACK_MODEL]:
        try:
            msg = client.messages.create(
                model=attempt_model, max_tokens=4096, system=system,
                output_config={"effort": "low"},
                messages=[{"role": "user", "content": content}],
            )
            if msg.stop_reason == "refusal":
                continue  # refusal -> fall back to next model per reviewer prompt
            text = "".join(b.text for b in msg.content if b.type == "text")
            m = re.search(r"\{.*\}", text, re.DOTALL)
            report = json.loads(m.group(0))
            break
        except Exception as e:
            print(f"  [reviewer] {attempt_model} failed: {e}")
    if report is None:
        report = {"overall": "fail", "items": [],
                  "summary": "reviewer_unavailable_fallback"}

    (review_dir / "review_report.json").write_text(json.dumps(report, indent=2))
    gaps = [i for i in report.get("items", []) if i.get("result") == "fail"]
    print(f"  [reviewer] overall: {report.get('overall', '?').upper()}")
    for g in gaps:
        print(f"    GAP {g['id']}: {g.get('gap_note', '')}")
    return report
