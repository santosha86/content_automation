"""Shot planning: turn a beat/segment into an ordered list of timed sub-shots.

The reference short cuts b-roll every ~2-4s and each cut shows the exact thing being
said. One static clip per 6s beat is the dead giveaway of an auto-generated video, so
the Director plans a shot list per beat (visual.shots) and this module normalizes it
into shots the Editor can time: each shot carries a `weight` (its phrase's share of the
beat, by word count) that the Editor turns into a sub-span of the beat's narration.
"""

MIN_SHOT_SECONDS = 1.6  # don't cut faster than this — sub-second flashes read as glitchy


def _weight(phrase: str) -> float:
    return max(1, len(phrase.split()))


def plan_from_beat(beat: dict) -> list[dict]:
    """Normalize a storyboard beat's visual.shots into weighted shots.

    Falls back to a single shot from the beat's top-level visual when the Director
    planned no shots (or the beat isn't from the Director path)."""
    visual = beat.get("visual", {})
    shots = visual.get("shots") or []
    out = []
    for s in shots:
        out.append({
            "source": s.get("source") or visual.get("source", "broll_video"),
            "query": s.get("query") or visual.get("query", ""),
            "prompt": s.get("prompt") or visual.get("prompt", ""),
            "must_show": s.get("must_show", ""),
            "camera": s.get("camera", "zoom_in"),
            "weight": _weight(s.get("phrase", s.get("query", "x"))),
        })
    if not out:
        out = [{
            "source": visual.get("source", "broll_video"),
            "query": visual.get("query", "") or beat.get("narration", "")[:40],
            "prompt": visual.get("prompt", ""),
            "must_show": visual.get("must_show", ""),
            "camera": beat.get("composition", {}).get("camera", "none"),
            "weight": 1.0,
        }]
    return out


def split_durations(total: float, shots: list[dict]) -> list[float]:
    """Split a beat's duration across its shots by weight, keeping only as many shots
    as can each hold >= MIN_SHOT_SECONDS. Returns durations aligned 1:1 with the FIRST
    len(result) shots (ordered by narration), so the Editor uses those clips and drops
    the rest — cuts never get glitchy-fast, phrase order is preserved."""
    if len(shots) <= 1 or total <= MIN_SHOT_SECONDS:
        return [total]
    keep = max(1, min(len(shots), int(total // MIN_SHOT_SECONDS)))
    weights = [shots[i]["weight"] for i in range(keep)]
    wsum = sum(weights) or 1.0
    return [total * w / wsum for w in weights]
