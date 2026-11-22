# Horizon on Railway

One-click Railway template for [Horizon](https://github.com/Thysrael/Horizon) (MIT), an AI news radar by Thysrael. Horizon collects stories from Hacker News, RSS feeds, Reddit, Telegram channels, GitHub and more, has your LLM score, filter, de-duplicate and summarise them, and writes a daily Markdown briefing.

**Version:** Horizon commit [`e17ea80`](https://github.com/Thysrael/Horizon/commit/e17ea80ced84e575e89489f3905b75eabf7e249b) (main, 2026-11-22). Upstream publishes no releases, tags or images, so the [`Dockerfile`](Dockerfile) builds upstream's own install steps from that pinned commit on `python:3.11.18-slim@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535`, with `uv` 0.11.26 pinned by digest and dependencies from upstream's `uv.lock`.

## What the template deploys

One service, **Horizon**, built from this repo, with a volume at `/app/data` and a public HTTPS domain.

Horizon itself is a run-once command-line program. This template adds a small wrapper ([`railway/server.py`](railway/server.py), Python standard library only):

- a **web UI behind a login** (HTTP basic auth, user `admin`, generated password) to read the briefings, edit `config.json` (validated with Horizon's own loader before saving), start a run, and read the last run's log;
- a **daily schedule**: Horizon runs once on first boot, then every day at `HORIZON_RUN_AT` (UTC);
- **`/healthz`** (no login) for Railway's health check.

Everything Horizon keeps (`config.json`, `summaries/`, run logs) is on the volume, so it survives redeploys, restarts and updates. A crash exits non-zero, so Railway's on-failure restart policy brings it back on every plan. Memory use is small: about 25 MB idle and well under 0.5 GB during a run, so it fits Railway's Free and Trial plan limit.

## Variables

| Variable | Default | What it does |
|---|---|---|
| `LLM_API_KEY` | **you enter it** | API key for your LLM provider (OpenAI by default). Horizon sends every collected story to it. |
| `LLM_PROVIDER` | `openai` | `openai`, `anthropic`, `gemini`, `deepseek`, `ali` (Qwen), `doubao`, `minimax` or `ollama`. |
| `LLM_MODEL` | empty | Model name. Empty picks a default for the provider (`gpt-4.1-mini` for OpenAI). |
| `LLM_BASE_URL` | empty | Optional OpenAI-compatible endpoint (OpenRouter, a proxy, your own Ollama). Empty uses the provider's own API. |
| `HORIZON_PASSWORD` | generated | Password for the web UI (user `admin`). |
| `HORIZON_RUN_AT` | `07:00` | Time of the daily run, `HH:MM` in UTC. |
| `PORT` | `8080` | Port of the web UI; the domain targets it. |

The `${LLM_PROVIDER}`, `${LLM_MODEL}` and `${LLM_BASE_URL}` references in the default `config.json` read these variables, so you can change provider or model in Railway's Variables tab without editing the file.

Optional upstream features need extra variables on the service (see upstream's [configuration guide](https://github.com/Thysrael/Horizon/blob/e17ea80ced84e575e89489f3905b75eabf7e249b/docs/configuration.md)): `GITHUB_TOKEN` for higher GitHub rate limits, `HORIZON_WEBHOOK_URL` plus `"webhook"` in the config to push briefings to Slack, Feishu, Discord or any webhook, email delivery through SMTP, and `FIRECRAWL_API_KEY` and similar for other full-text extractors. Twitter/X scraping needs Playwright, which this image (like upstream's) doesn't include.

## After deploying

1. Copy `HORIZON_PASSWORD` from the Horizon service's Variables tab, open the public URL and sign in as `admin`.
2. The first briefing is being written (a few minutes; see **Run log**). It covers the last 24 hours of the default sources: Hacker News, Simon Willison, Ars Technica and Sean Goedecke.
3. Open **Config** to add your own sources (RSS feeds, subreddits, Telegram channels, GitHub users and repos), change score thresholds, or add `"zh"` to `ai.languages` for a Chinese briefing as well. **Run Horizon now** applies the change at once.

LLM cost: each run sends every collected story to the model (one scoring call per story, plus a few calls per selected story). With the defaults that is roughly 50–150 calls a day.

## Updates

This template builds from this repository, so Railway shows everyone who deployed it an "update available" notice when a new version is merged to `main`. Read [`CHANGELOG.md`](CHANGELOG.md) (breaking changes come first) before you apply an update. Your `config.json` and briefings stay on the volume; the template never overwrites an existing `config.json`.

## Testing

[`test/compose.yml`](test/compose.yml) runs the same image locally with a 0.5 GB / 1 CPU limit. [`test/stub/`](test/stub) is a tiny stand-in for an OpenAI-compatible API (and an RSS feed) used to test the template without a paid key; it isn't part of the template.

## Licence

Horizon is MIT, © Thysrael and contributors. This repository only contains the Railway wrapper (Dockerfile, start script, web UI, docs), also MIT. The template icon is the 🌅 emoji Horizon uses as its own site icon, from [Twemoji](https://github.com/jdecked/twemoji) (CC-BY 4.0).
