# Content Automation — Shorts/Reels Factory

Automated pipeline: AI news (RSS) → script → voiceover → b-roll → karaoke captions → finished 9:16 video in a review folder. One command per video, one manual step (your approval).

## Pipeline

```
scout → writer → voice → visuals → editor → packager → output/review/
 RSS     LLM    Eleven   Pexels    ffmpeg    metadata      YOU approve
                Labs              +whisper
```

The **brain** lives in `config/`:
- `style_guide.md` — hook rules, tone, structure (the Analyst agent will tune this in Phase 4)
- `feeds.yaml` — news sources
- `settings.yaml` — video/caption/timing knobs

## Setup (one time)

```bash
make setup          # installs deps, creates .env
# edit .env: ANTHROPIC_API_KEY (required for quality), ELEVENLABS_API_KEY, PEXELS_API_KEY
```

Keyless fallbacks exist for testing: Ollama for scripts, macOS `say` for voice, generated backgrounds for b-roll — the pipeline runs end-to-end with zero keys, just at draft quality.

## Daily use

```bash
make video                          # scout picks today's best AI story
make video-topic TOPIC="..."        # you choose the topic
```

Output lands in `output/review/<date>-<slug>/` with the .mp4 and platform-ready `metadata.json` (YouTube title/description, IG caption, hashtags).

Optional: drop royalty-free .mp3 tracks in `assets/music/` for an automatic background bed.

## Roadmap

- **Phase 1 (this)**: one-command video → review folder
- **Phase 2**: AI avatar station (HeyGen), Telegram approval bot, auto-publish (YouTube Data API + Instagram Graph API)
- **Phase 3**: cloned voice + avatar, multiple formats, batch weekly production
- **Phase 4**: analytics loop — Analyst agent reads YT/IG metrics, rewrites `style_guide.md`, A/B tests hooks
