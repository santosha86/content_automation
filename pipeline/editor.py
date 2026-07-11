"""Editor: assemble segments into a captioned 9:16 video, all local (ffmpeg + whisper).

Editing style codified from observation1.md (reference-short teardown):
- RULE_HOOK: first frame clean (image only), headline builds word-by-word
- RULE_CAPTIONS: 2-4 word chunks on a dark chip, synced to speech
- RULE_TRANSITIONS: short full-frame flash masks the hook -> body cut
- RULE_BOOKEND: CTA reuses the hook's kinetic text treatment
"""
import hashlib
from pathlib import Path

from .util import ROOT, ffmpeg_bin, media_duration, run_cmd, settings

HOOK_T0 = 0.5      # frame 0 stays text-free — the image is the scroll-stopper
HOOK_STEP = 0.45   # seconds per word in the kinetic build
FLASH_LEN = 0.08   # white flash masking the hook -> body cut


def _ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int(seconds % 3600 // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _transcribe_words(wav: Path) -> list[dict]:
    from faster_whisper import WhisperModel
    cfg = settings()["whisper"]
    model = WhisperModel(cfg["model"], device="cpu", compute_type=cfg["compute_type"])
    segments, _ = model.transcribe(str(wav), word_timestamps=True, language="en")
    words = []
    for seg in segments:
        for w in seg.words or []:
            words.append({"word": w.word.strip(), "start": w.start, "end": w.end})
    return words


def _kinetic_events(text: str, style: str, t_start: float, t_end: float) -> list[str]:
    """Headline that assembles one word at a time (cumulative), then holds."""
    words = [w.upper() for w in text.split()]
    if not words:
        return []
    step = min(HOOK_STEP, max(0.2, (t_end - t_start - 0.6) / len(words)))
    events = []
    for k in range(1, len(words) + 1):
        s = t_start + step * (k - 1)
        if s >= t_end:
            break
        e = t_start + step * k if k < len(words) else t_end
        events.append(f"Dialogue: 1,{_ts(s)},{_ts(e)},{style},,0,0,0,,{' '.join(words[:k])}")
    return events


def _build_ass(words: list[dict], script: dict, bounds: list[tuple[float, float]], out: Path) -> None:
    cap = settings()["captions"]
    chip = "&HB4000000"  # dark translucent caption chip
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{cap['font']},{cap['font_size']},&H00FFFFFF,&H000000FF,{chip},{chip},-1,0,0,0,100,100,0,0,4,16,0,2,60,60,640,1
Style: Hook,{cap['font']},{int(cap['font_size'] * 1.15)},{cap['highlight_color']},&H000000FF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,4,2,8,70,70,320,1
Style: Overlay,{cap['font']},{int(cap['font_size'] * 0.55)},&H00FFFFFF,&H000000FF,{chip},{chip},-1,0,0,0,100,100,0,0,4,12,0,8,70,70,340,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    # kinetic hook over the first segment
    if script.get("hook_text"):
        lines += _kinetic_events(script["hook_text"], "Hook", HOOK_T0, bounds[0][1])
    # CTA bookend: last segment's overlay in the same kinetic style
    segments = script["segments"]
    cta = (segments[-1].get("overlay") or "").strip()
    if cta and len(segments) > 1:
        lines += _kinetic_events(cta, "Hook", bounds[-1][0] + 0.2, bounds[-1][1])
    # mid-segment info overlays (numbers, names)
    for i, seg in enumerate(segments[1:-1], start=1):
        text = (seg.get("overlay") or "").strip()
        if text:
            lines.append(
                f"Dialogue: 0,{_ts(bounds[i][0] + 0.3)},{_ts(bounds[i][1])},Overlay,,0,0,0,,{text.upper()}"
            )
    # speech-synced caption chips
    n = cap["words_per_chunk"]
    for i in range(0, len(words), n):
        chunk = words[i : i + n]
        # RULE_HOOK: frame 0 carries no text at all — captions wait out the clean window
        start, end = max(chunk[0]["start"], HOOK_T0), chunk[-1]["end"]
        if end <= HOOK_T0:
            continue
        longest = max(range(len(chunk)), key=lambda j: len(chunk[j]["word"]))
        parts = []
        for j, w in enumerate(chunk):
            t = w["word"].upper()
            if j == longest:
                t = f"{{\\c{cap['highlight_color']}}}{t}{{\\c&H00FFFFFF}}"
            parts.append(t)
        lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Caption,,0,0,0,,{' '.join(parts)}")
    out.write_text(header + "\n".join(lines) + "\n")


def _pick_music(script: dict) -> Path | None:
    tracks = sorted((ROOT / "assets" / "music").glob("*.mp3"))
    if not tracks:
        return None
    idx = int(hashlib.sha1(script["topic"]["title"].encode()).hexdigest(), 16) % len(tracks)
    return tracks[idx]


def assemble(script: dict, seg_audio: list[Path], seg_video: list[Path], run_dir: Path) -> Path:
    v = settings()["video"]
    ff = ffmpeg_bin()

    # 1. concat voiceover
    alist = run_dir / "audio_list.txt"
    alist.write_text("\n".join(f"file '{p}'" for p in seg_audio))
    voiceover = run_dir / "voiceover.wav"
    run_cmd([ff, "-y", "-f", "concat", "-safe", "0", "-i", str(alist),
             "-ar", "44100", "-ac", "1", str(voiceover)])

    # 2. per-segment video, trimmed/looped to its narration length
    durs = [media_duration(p) for p in seg_audio]
    bounds = []
    t = 0.0
    for d in durs:
        bounds.append((t, t + d))
        t += d
    fit = (f"scale={v['width']}:{v['height']}:force_original_aspect_ratio=increase,"
           f"crop={v['width']}:{v['height']},setsar=1,fps={v['fps']}")
    seg_outs = []
    for i, (dur, vid) in enumerate(zip(durs, seg_video)):
        out = run_dir / f"cut_{i:02d}.mp4"
        run_cmd([ff, "-y", "-stream_loop", "-1", "-i", str(vid), "-t", f"{dur:.3f}",
                 "-vf", fit, "-an", "-c:v", "libx264", "-preset", "fast",
                 "-pix_fmt", "yuv420p", str(out)])
        seg_outs.append(out)

    # 3. concat video
    vlist = run_dir / "video_list.txt"
    vlist.write_text("\n".join(f"file '{p}'" for p in seg_outs))
    concat = run_dir / "concat.mp4"
    run_cmd([ff, "-y", "-f", "concat", "-safe", "0", "-i", str(vlist), "-c", "copy", str(concat)])

    # 4. captions from whisper word timing
    print("  [editor] transcribing for caption timing...")
    words = _transcribe_words(voiceover)
    subs = run_dir / "subs.ass"
    _build_ass(words, script, bounds, subs)

    # 5. final mux: captions burned, flash at hook cut, voiceover + optional music bed
    final = run_dir / "final.mp4"
    music = _pick_music(script)
    flash_t = bounds[0][1]
    vfilter = (f"ass='{subs}',"
               f"eq=brightness=0.85:enable='between(t,{flash_t:.2f},{flash_t + FLASH_LEN:.2f})'")
    if music:
        vol = settings()["music"]["volume"]
        run_cmd([ff, "-y", "-i", str(concat), "-i", str(voiceover),
                 "-stream_loop", "-1", "-i", str(music),
                 "-filter_complex",
                 f"[0:v]{vfilter}[v];[2:a]volume={vol}[m];[1:a][m]amix=inputs=2:duration=first:normalize=0[a]",
                 "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium",
                 "-crf", "20", "-c:a", "aac", "-b:a", "192k", "-shortest", str(final)])
    else:
        run_cmd([ff, "-y", "-i", str(concat), "-i", str(voiceover),
                 "-vf", vfilter, "-map", "0:v", "-map", "1:a",
                 "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                 "-c:a", "aac", "-b:a", "192k", "-shortest", str(final)])
    return final
