# Changelog

Each entry is one version of this Railway template. Breaking changes come first.
Railway shows deployers an "update available" notice when `main` changes; read the entry before you apply it.

## 2026-11-22: Horizon e17ea80 (first release)

- Builds [Thysrael/Horizon](https://github.com/Thysrael/Horizon) at commit `e17ea80ced84e575e89489f3905b75eabf7e249b` (main, 2026-11-22; upstream publishes no releases or images) on `python:3.11.18-slim@sha256:07d48240…`, with `uv` 0.11.26 pinned by digest.
- Adds a small wrapper (`railway/`): password-protected web UI to read briefings, edit `config.json` and start a run; a daily scheduler (`HORIZON_RUN_AT`, UTC); `/healthz` for Railway's health check.
- README starts with the Deploy on Railway button for the published template (`horizon`).
- All state (`config.json`, `summaries/`, run logs) lives on the `/app/data` volume.
