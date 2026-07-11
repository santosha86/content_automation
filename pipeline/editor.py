"""Editor: assemble segments into a captioned 9:16 video, all local (ffmpeg + whisper)."""
import hashlib
from pathlib import Path

from .util import ROOT, ffmpeg_bin, media_duration, run_cmd, settings


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


def _build_ass(words: list[dict], hook_text: str, out: Path) -> None:
    cap = settings()["captions"]
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{cap['font']},{cap['font_size']},&H00FFFFFF,&H000000FF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,7,3,2,60,60,640,1
Style: Hook,{cap['font']},{int(cap['font_size'] * 1.15)},{cap['highlight_color']},&H000000FF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,8,4,8,70,70,320,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    if hook_text:
        lines.append(f"Dialogue: 1,0:00:00.00,0:00:02.60,Hook,,0,0,0,,{hook_text.upper()}")
    n = cap["words_per_chunk"]
    for i in range(0, len(words), n):
        chunk = words[i : i + n]
        start, end = chunk[0]["start"], chunk[-1]["end"]
        # accent the longest word in the chunk
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
    fit = (f"scale={v['width']}:{v['height']}:force_original_aspect_ratio=increase,"
           f"crop={v['width']}:{v['height']},setsar=1,fps={v['fps']}")
    seg_outs = []
    for i, (aud, vid) in enumerate(zip(seg_audio, seg_video)):
        dur = media_duration(aud)
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
    _build_ass(words, script.get("hook_text", ""), subs)

    # 5. final mux: captions burned, voiceover + optional music bed
    final = run_dir / "final.mp4"
    music = _pick_music(script)
    sub_filter = f"ass='{subs}'"
    if music:
        vol = settings()["music"]["volume"]
        run_cmd([ff, "-y", "-i", str(concat), "-i", str(voiceover),
                 "-stream_loop", "-1", "-i", str(music),
                 "-filter_complex",
                 f"[0:v]{sub_filter}[v];[2:a]volume={vol}[m];[1:a][m]amix=inputs=2:duration=first:normalize=0[a]",
                 "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium",
                 "-crf", "20", "-c:a", "aac", "-b:a", "192k", "-shortest", str(final)])
    else:
        run_cmd([ff, "-y", "-i", str(concat), "-i", str(voiceover),
                 "-vf", sub_filter, "-map", "0:v", "-map", "1:a",
                 "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                 "-c:a", "aac", "-b:a", "192k", "-shortest", str(final)])
    return final
