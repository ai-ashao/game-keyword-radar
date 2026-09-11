# Feature status — 2.1.0rc1

Implemented: release provenance and first_seen separation; provisional new-release lane; four-lane admission and deterministic budgets; pre-deep Steam/Twitch directed observations and compatible history; observation identity and 24h/7d one-to-one windows; low-base/sample/concentration safeguards; opt-in local lightweight monitoring; manual seed and annotations; dashboard WHY NOW/funnel/deferred/monitor views; single-source page validation eligibility; real-question vs content-proxy counts; safe historical counts/comparisons; CLI/Skill/report updates.

Defaults: Deep10 ->4/3/1/2, exploration cap40%, cooldown24h, release90days, observation120minutes. These are research heuristics, not measured predictive accuracy.

Not verified here: real Steam+Twitch+YouTube joint run, cross-day live window, browser direct HTTP (browser policy blocks network navigation), installed wheel build (hatchling unavailable). Offline Chromium DOM + ASGI binding is tested separately. Detailed test scope: V2_1_ACCEPTANCE.md.

Not implemented by design: automatic global first-release research, full-market Twitch history, automatic subreddit discovery, paid SERP collection, cloud scheduling, auto Build. Manual seed/evidence is the explicit fallback, not fabricated automatic evidence.
