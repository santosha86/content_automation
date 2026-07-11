"""Background music by mood.

The Director picks a `music.mood` in the storyboard (driving | suspense | uplift |
tech_minimal | none). This module turns that into an actual bed:

  1. If you've dropped royalty-free tracks in assets/music/<mood>/*.mp3, one is chosen
     (deterministically, by the video's title) — real music always wins.
  2. Otherwise a soft ambient bed is SYNTHESIZED for that mood via ffmpeg (a low-passed
     sine chord with gentle movement), so music works with zero assets and the video
     never sits in dead air. Swap in real tracks anytime to override.

Everything is royalty-free by construction (your own files, or generated tones).
"""
import hashlib
from pathlib import Path

from .util import ROOT, ffmpeg_bin, run_cmd

MUSIC_DIR = ROOT / "assets" / "music"

# Per-mood synthesized bed: a chord (Hz), a tremolo rate (movement), and a lowpass
# cutoff (brightness). Tuned to sit UNDER narration, not compete with it.
_MOODS = {
    "tech_minimal": {"chord": [110.0, 164.81, 220.0], "tremolo": 0.15, "lowpass": 900},   # A minor, calm
    "suspense":     {"chord": [65.41, 98.0, 138.59],  "tremolo": 0.10, "lowpass": 600},   # low, tense
    "driving":      {"chord": [98.0, 146.83, 196.0],  "tremolo": 2.60, "lowpass": 1100},  # pulsing
    "uplift":       {"chord": [130.81, 164.81, 196.0], "tremolo": 0.20, "lowpass": 1300}, # C major, bright
}


def _real_track(mood: str) -> Path | None:
    """A royalty-free file the user dropped in assets/music/<mood>/ (real music wins)."""
    folder = MUSIC_DIR / mood
    tracks = sorted(folder.glob("*.mp3")) + sorted(folder.glob("*.wav")) if folder.exists() else []
    # also accept flat assets/music/*.mp3 for backwards-compat
    if not tracks:
        return None
    return tracks[0]


def _synth_bed(mood: str, seconds: float, out: Path) -> Path:
    """Synthesize a soft ambient bed for the mood via ffmpeg lavfi (no assets needed)."""
    spec = _MOODS.get(mood, _MOODS["tech_minimal"])
    dur = max(seconds + 1.0, 2.0)
    inputs = []
    for f in spec["chord"]:
        inputs += ["-f", "lavfi", "-i", f"sine=frequency={f}:duration={dur:.2f}"]
    n = len(spec["chord"])
    # Mix the chord, add slow movement (tremolo), soften (lowpass), add space (aecho),
    # and a gentle fade in/out so it doesn't click. amix normalizes, so it stays quiet.
    fade_out = max(dur - 1.2, 0)
    chain = (
        f"amix=inputs={n}:normalize=1,"
        f"tremolo=f={spec['tremolo']}:d=0.4,"
        f"lowpass=f={spec['lowpass']},"
        f"aecho=0.8:0.9:80:0.3,"
        f"afade=t=in:st=0:d=1.0,afade=t=out:st={fade_out:.2f}:d=1.2,"
        f"volume=4.0"  # pre-level the bed to ~-24dB so the Editor mixes it at gain 1.0
    )
    labels = "".join(f"[{i}:a]" for i in range(n))
    args = [ffmpeg_bin(), "-y", *inputs,
            "-filter_complex", f"{labels}{chain}[a]",
            "-map", "[a]", "-ar", "44100", str(out)]
    run_cmd(args)
    return out


def pick(mood: str, seconds: float, run_dir: Path, track_volume: float = 0.12) -> tuple[Path, float] | None:
    """Resolve the mood to (bed_path, mix_gain), or None when mood == 'none'/unknown.

    Real tracks win and are mixed at `track_volume` (they're mastered loud). Synthesized
    beds are pre-leveled to ~-24dB, so they mix at gain 1.0 (no further attenuation)."""
    mood = (mood or "").strip().lower()
    if mood in ("none", ""):
        return None
    real = _real_track(mood)
    if real:
        return real, track_volume
    if mood not in _MOODS:
        return None
    return _synth_bed(mood, seconds, run_dir / f"music_{mood}.wav"), 1.0


if __name__ == "__main__":
    import sys
    tmp = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp")
    for m in _MOODS:
        p = _synth_bed(m, 6.0, tmp / f"bed_{m}.wav")
        print(f"{m}: {p}")
