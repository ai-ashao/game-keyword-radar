# 2.0.0rc1 — 2026-09-11

Added cross-platform GameEntity / PlatformSignal / QuestionCluster / PageOpportunity schemas without removing V1 fields. Added Twitch, YouTube, public Reddit RSS, optional Trends provider boundary, separate Demand scoring, evidence-triggered Page Graph, existing-site routing, manual validation persistence, source/budget UI, time-aware historical comparison and keyword CSV export.

Reworked the local Dashboard around games rather than a large keyword table. Retained CLI and Markdown reporting; refreshed the Codex Skill. Steam detail and player failures are isolated. Added cache, request caps, secret-safe diagnostics, local scan locking, immutable snapshot writes and failed-scan / demo isolation.

Validation status: offline tests and browser/ASGI checks passed; actual Steam + Twitch + YouTube joint acceptance remains unpassed in the development environment. Official Trends is an extension seam, not a claimed operational Alpha integration.
