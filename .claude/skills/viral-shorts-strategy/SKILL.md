---
name: viral-shorts-strategy
description: Content strategy for AI-news YouTube Shorts / Instagram Reels — hook formulas, name-anchor rule, retention structure, fabrication guardrail. Use whenever picking stories, writing hooks/scripts, or planning storyboards for this pipeline.
---

# Viral Shorts Strategy

House strategy for every story pick, hook, script, and storyboard this pipeline produces.
`config/style_guide.md` holds the format rules; this skill holds the *judgment*.

## Name-anchor rule

Anchor hooks to famous names and brands whenever the story genuinely involves them —
Sam Altman, OpenAI, Claude, Anthropic, Google, Sundar Pichai, Elon Musk, Meta, Apple.
Names are the strongest scroll-stoppers in the AI niche.

- **Hyperbole about a real event is fine** ("Sam Altman just broke the internet") — it reads as opinion.
- **Fabricated events are never fine** ("Sam Altman was crying") — that's a false factual claim.
  If a hook implies something happened, it must have happened. When in doubt, rewrite as
  opinion/stakes ("This should terrify OpenAI") instead of invented fact.
- Never force an anchor onto a story that has none; a mismatched name reads as clickbait and
  kills trust. Leave `name_anchor` empty in the storyboard.

## Story selection (Strategist)

Score candidates on, in order:
1. **Name gravity** — does a famous person/company drive the story?
2. **Stakes** — money, jobs, power shifts, "this changes X".
3. **Freshness** — <48h; prefer <24h.
4. **Explainability** — can the core be told in 30-40 spoken seconds without losing the truth?
5. **Visual availability** — is there real proof b-roll (product UI, repo, demo, footage)?

Two lanes, same scoring: **ai_news** (feeds/Tavily) and **github_trending** (a repo trending
hard is a story: what it does, why now, who should care).

## Hook formulas (generate 3 variants, different formulas)

1. **Name + shock verb**: "Google just killed [X]"
2. **Stakes question**: "Is this the end of [X]?"
3. **Insider reveal**: "Nobody noticed what OpenAI shipped"
4. **Number + consequence**: "3 words that broke [X]"
5. **You-frame**: "Your [job/app/stack] just changed"

Constraints: 4-6 words, buildable word-by-word (kinetic hook), no punctuation that can't
render as chips, must be true (see fabrication guardrail).

## Retention structure (30-40s)

- **0-2s** hook (kinetic text, clean frame 0) — earns the next 3 seconds
- **2-8s** context: what actually happened, one sentence, concrete
- **8-30s** 2-3 escalating specifics — each beat raises stakes or reveals a detail; never
  two consecutive beats with the same emotion; every beat's b-roll shows the *subject*, not
  the theme
- **30-38s** payoff: what it means for the viewer ("you" frame)
- **last beat** CTA bookend, 3-5 words, Hook style (checklist B7)

## Guardrails

- No fabricated quotes, events, numbers, or demos. Hyperbolic *opinion* only.
- Claims sourced from the article/repo; if the script states a number, it's in the source.
- One idea per video. If the story has two ideas, that's two videos.
- CTA asks for one action only.
