# Project Context · V2 RC1

Repository: `ai-ashao/game-keyword-radar`.

Purpose: local-first cross-platform Game Demand Radar and keyword / page opportunity research. Steam + Twitch discover; YouTube / Reddit / optional Trends enrich bounded candidates; question clusters trigger Page Graph; humans validate Semrush / SERP before Build / Skip.

Primary UX: local Dashboard. Keep CLI, reports, existing model fields and read-only V1 snapshots. Do not introduce SaaS, external DB, accounts, social posting, article generation, or a dependency on `game-content-radar`.

The user-provided design is preserved at `docs/V2_PLAN.md`. Implemented architecture and deliberate limits are documented at `docs/V2_ARCHITECTURE.md`, `docs/V2_SCORING.md` and `docs/V2_ACCEPTANCE.md`.

Never convert Twitch viewers, YouTube views or Google Trends indices into Google monthly search volume. Missing is null, not zero; incomplete samples and unavailable providers remain explicit. Pre-validation Page Opportunity Score is capped at 69. Game demand is a separate research score with evidence coverage.

RC1 is not a claim of completed live three-source acceptance. Credentials and network restrictions prevented that acceptance in the development environment. Use `scripts/live_acceptance.py` with real credentials locally.
