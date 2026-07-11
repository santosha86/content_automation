"""Editor: assemble segments into a captioned 9:16 video, all local (ffmpeg + whisper).

Editing style codified from observation1.md (reference-short teardown):
- RULE_HOOK: first frame clean (image only), headline builds word-by-word
- RULE_CAPTIONS: 2-4 word chunks on a dark chip, synced to speech
- RULE_TRANSITIONS: short full-frame flash masks the hook -> body cut
- RULE_BOOKEND: CTA reuses the hook's kinetic text treatment
"""
import hashlib
from pathlib import Path

from . import shots as shotplan
from .util import ROOT, ffmpeg_bin, media_duration, run_cmd, settings

HOOK_T0 = 0.5      # frame 0 stays text-free — the image is the scroll-stopper
HOOK_STEP = 0.45   # seconds per word in the kinetic build
FLASH_LEN = 0.08   # white flash masking the hook -> body cut

# Ken-Burns moves (reference uses subtle motion so stills/loops don't feel dead).
# zoompan with d=1 + pzoom accumulates a continuous move across a video clip.
# NOTE: zoompan defaults its output to 1280x720 — the `s=`/`fps=` are appended per
# render from settings so the frame stays 9:16, else the export silently goes landscape.
_CAMERA_Z = {
    "zoom_in":  "min(pzoom+0.0012,1.12)",
    "punch_in": "min(pzoom+0.0026,1.18)",
    "zoom_out": "min(pzoom+0.0010,1.10)",
}


def _camera_vf(camera: str) -> str:
    z = _CAMERA_Z.get(camera)
    if not z:
        return ""
    v = settings()["video"]
    return (f"zoompan=z='{z}':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":s={v['width']}x{v['height']}:fps={v['fps']}")


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


def _endcard_clip(run_dir: Path, seconds: float) -> Path:
    """Render the reusable branded end-card (solid bg + brand text via libass, so it
    uses the same font stack as the captions). Identical every video (reference rule)."""
    v = settings()["video"]
    b = settings().get("branding", {})
    cap = settings()["captions"]
    W, H = v["width"], v["height"]
    name = b.get("name", "SIGNAL")
    sub = " · ".join(x for x in [b.get("handle", ""), b.get("tagline", "")] if x)
    accent = b.get("accent_color", cap["highlight_color"])
    ass = run_dir / "endcard.ass"
    ass.write_text(f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Brand,{cap['font']},{int(cap['font_size'] * 1.4)},{accent},&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,2,0,1,0,0,5,80,80,0,1
Style: Sub,{cap['font']},{int(cap['font_size'] * 0.5)},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,1,0,1,0,0,5,80,80,-180,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:{seconds:05.2f},Brand,,0,0,0,,{{\\fad(200,150)}}{name.upper()}
Dialogue: 0,0:00:00.25,0:00:{seconds:05.2f},Sub,,0,0,0,,{{\\fad(250,150)}}{sub}
""")
    out = run_dir / "endcard.mp4"
    run_cmd([ffmpeg_bin(), "-y", "-f", "lavfi",
             "-i", f"color=c={settings().get('branding', {}).get('bg_color', '0x0B1020')}:s={W}x{H}:d={seconds:.2f}:r={v['fps']}",
             "-vf", f"ass='{ass}'", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)])
    return out


def _pick_music(script: dict, seconds: float, run_dir: Path) -> tuple[Path, float] | None:
    """Music bed for the storyboard's mood (real track from assets/music/<mood>/ if
    present, else a synthesized bed). Returns (path, mix_gain) or None for mood 'none'."""
    from . import music
    mood = (script.get("music") or {}).get("mood", "tech_minimal")
    # music.pick reads music.synth_volume / music.track_volume from settings itself.
    return music.pick(mood, seconds, run_dir)


def _cut_shot(clip: Path, dur: float, camera: str, out: Path, fit: str) -> None:
    """Trim/loop one shot clip to `dur`, applying its Ken-Burns move. Falls back to a
    static fit if the motion filter errors, so a single clip never fails the render."""
    ff = ffmpeg_bin()
    move = _camera_vf(camera)
    vf = f"{fit},{move}" if move else fit
    try:
        run_cmd([ff, "-y", "-stream_loop", "-1", "-i", str(clip), "-t", f"{dur:.3f}",
                 "-vf", vf, "-an", "-c:v", "libx264", "-preset", "fast",
                 "-pix_fmt", "yuv420p", str(out)])
    except RuntimeError:
        run_cmd([ff, "-y", "-stream_loop", "-1", "-i", str(clip), "-t", f"{dur:.3f}",
                 "-vf", fit, "-an", "-c:v", "libx264", "-preset", "fast",
                 "-pix_fmt", "yuv420p", str(out)])


def assemble(script: dict, seg_audio: list[Path], seg_video: list[list[Path]], run_dir: Path) -> Path:
    v = settings()["video"]
    ff = ffmpeg_bin()

    # 1. concat voiceover
    alist = run_dir / "audio_list.txt"
    alist.write_text("\n".join(f"file '{p}'" for p in seg_audio))
    voiceover = run_dir / "voiceover.wav"
    run_cmd([ff, "-y", "-f", "concat", "-safe", "0", "-i", str(alist),
             "-ar", "44100", "-ac", "1", str(voiceover)])

    # 2. expand each segment into per-shot cuts that fill its narration span, so the
    #    b-roll cuts WITH the words instead of one static clip per beat.
    durs = [media_duration(p) for p in seg_audio]
    bounds = []
    t = 0.0
    for d in durs:
        bounds.append((t, t + d))
        t += d
    fit = (f"scale={v['width']}:{v['height']}:force_original_aspect_ratio=increase,"
           f"crop={v['width']}:{v['height']},setsar=1,fps={v['fps']}")
    seg_outs = []
    for i, (dur, clips) in enumerate(zip(durs, seg_video)):
        shot_meta = script["segments"][i].get("shots") or [{"camera": "none"}]
        spans = shotplan.split_durations(dur, shot_meta)  # length = shots kept
        for k, span in enumerate(spans):
            clip = clips[k] if k < len(clips) else clips[-1]
            camera = shot_meta[k].get("camera", "none") if k < len(shot_meta) else "none"
            out = run_dir / f"cut_{i:02d}_{k:02d}.mp4"
            _cut_shot(clip, span, camera, out, fit)
            seg_outs.append(out)

    # 2b. branded end-card appended after the last beat (reference bookend rule B8)
    endcard_sec = float(settings().get("branding", {}).get("endcard_seconds", 0) or 0)
    if endcard_sec > 0:
        seg_outs.append(_endcard_clip(run_dir, endcard_sec))

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

    # 5. final mux: captions burned, flash at hook cut, voiceover + optional music bed.
    # The narration audio is padded by the end-card length so the card plays out over
    # silence/music instead of being truncated by -shortest.
    final = run_dir / "final.mp4"
    total_dur = bounds[-1][1] + endcard_sec
    music = _pick_music(script, total_dur, run_dir)
    flash_t = bounds[0][1]
    vfilter = (f"ass='{subs}',"
               f"eq=brightness=0.85:enable='between(t,{flash_t:.2f},{flash_t + FLASH_LEN:.2f})'")
    apad = f"[1:a]apad=pad_dur={endcard_sec:.2f}[vo]" if endcard_sec > 0 else "[1:a]anull[vo]"
    # +faststart moves the moov atom to the front so players/previews and the YouTube/IG
    # uploaders can start before the whole file loads; -ac 2 gives IG the stereo it prefers.
    tail = ["-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-movflags", "+faststart",
            "-shortest", str(final)]
    if music:
        track, gain = music
        run_cmd([ff, "-y", "-i", str(concat), "-i", str(voiceover),
                 "-stream_loop", "-1", "-i", str(track),
                 "-filter_complex",
                 f"[0:v]{vfilter}[v];{apad};[2:a]volume={gain}[m];[vo][m]amix=inputs=2:duration=first:normalize=0[a]",
                 "-map", "[v]", "-map", "[a]", *tail])
    else:
        run_cmd([ff, "-y", "-i", str(concat), "-i", str(voiceover),
                 "-filter_complex", f"[0:v]{vfilter}[v];{apad}",
                 "-map", "[v]", "-map", "[vo]", *tail])
    return final
