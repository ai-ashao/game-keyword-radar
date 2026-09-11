---
name: game-keyword-scan
description: Read local Game Keyword Radar snapshots, cross-platform demand evidence, question clusters and Page Graph; prioritize manual Semrush/SERP validation without inventing search volume or automatically building sites.
---

# Game Keyword Scan · V2.1

Use for the user's game discovery, keyword/page research and Build / Skip review. This is NOT a social-content radar, article generator or automatic website builder.

## Read the requested evidence first

Use the supplied snapshot or `data/latest.json`. Respect `is_demo`, `schema_version`, `country`, `language`, timestamps and all source statuses. V1 / V1.1 records are read-only; lack of V2 fields is not evidence that a game has no cross-platform demand. Never replace a failed live scan with Demo.

For V2 inspect `entities`, `game_opportunities`, `platform_signals`, `question_clusters`, `page_opportunities`, `source_statuses`, `raw_metadata` and the separate `data/validation/` records. Do not edit `data/processed/` to make a result appear validated.

## Research order

Read source states -> lifecycle and release provenance -> WHY NOW and selection_decisions -> compatible Momentum comparisons -> lane budgets/deferred reasons -> actual questions/content proxies -> Page Graph -> manual SERP evidence.

Use before_deep_selection and the saved policy/config hash to explain why a game was chosen at that time. Do not re-rank historical snapshots with today's facts. Legacy Demand is diagnostic only; no “90 means build” reasoning. Missing sources are not zero, first_seen is not first release, no history is not stable, a partial global Twitch sample is not full game growth.

Check new_release / rising / new_demand / exploration independently. Mature high-volume games without new triggers remain monitor_only. First-time scans must still preserve provisional platform-release and weak-signal exploration candidates. Do not require Twitch or multiple sources for every candidate. Manual requests consume explicit budget, never masquerade as automatic discoveries.

For each proposed page explain WHY THIS PAGE EXISTS, source URL and publication time. Separate actual questions, answer-video proxies and gameplay hypotheses. Never give every game the same codes/tier-list/map set. Existing-site fit is page-level, not a bypass for mature-game selection or validation.

## Validation and decisions

Without real user-supplied or inspected Semrush / GSC / SERP evidence, leave the page at `needs_validation`; retain the 69 pre-validation cap. Twitch viewers, YouTube views and Trends indices must NEVER be converted into Google monthly searches.

When manual evidence is provided, identify market, keyword, date, inspected results and the smallest useful page before recommending Build / Skip. A queue record marked validated is a human-entered record, not proof that the application automatically verified the sources. Do not auto-persist a Build merely because a score is high.

## Output

Prioritize 3–10 games only when evidence warrants it; fewer or none is a valid outcome. For each include game identity, research reason, source availability, actual repeated problem, proposed pages, existing-site fit, next validation task and missing evidence. State when an empty result comes from filters, budgets, missing credentials or collection failure rather than low demand.

Use `references/scoring.md` and `references/serp-evidence.md`. The Dashboard remains the user's daily interface; CLI commands are optional execution support.

## V2.1 output contract

`candidate_lane / why_now / evidence / limitations / page_to_validate / next_action`. Include whether evidence is observed, manual or inferred and whether the record is demo. Unknown monthly search volume stays null. Monitoring only runs while the explicitly enabled local process is alive; do not imply background cloud work.
