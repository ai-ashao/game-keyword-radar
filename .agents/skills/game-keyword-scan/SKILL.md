---
name: game-keyword-scan
description: Read local Game Keyword Radar snapshots, cross-platform demand evidence, question clusters and Page Graph; prioritize manual Semrush/SERP validation without inventing search volume or automatically building sites.
---

# Game Keyword Scan · V2

Use for the user's game discovery, keyword/page research and Build / Skip review. This is NOT a social-content radar, article generator or automatic website builder.

## Read the requested evidence first

Use the supplied snapshot or `data/latest.json`. Respect `is_demo`, `schema_version`, `country`, `language`, timestamps and all source statuses. V1 / V1.1 records are read-only; lack of V2 fields is not evidence that a game has no cross-platform demand. Never replace a failed live scan with Demo.

For V2 inspect `entities`, `game_opportunities`, `platform_signals`, `question_clusters`, `page_opportunities`, `source_statuses`, `raw_metadata` and the separate `data/validation/` records. Do not edit `data/processed/` to make a result appear validated.

## Research order

Read each game's actual source coverage and confidence before its score. Inspect Twitch sample completeness / concentration, YouTube sample scope / guide demand, Reddit title examples and any real Trends direction. Follow provenance URLs and timestamps only when research is requested and access is available.

For every proposed page, explain WHY THIS PAGE EXISTS with its gameplay mechanism and actual trigger evidence. Separate observed questions, answer-video proxies and gameplay hypotheses. No universal codes / tier-list / map template. Preserve question clusters and supporting queries; do not silently invent missing evidence.

Check existing-site fit first: WorkshopFetch for relevant Workshop / SteamCMD, GameKitHQ for relevant reusable tools, FN Sprite Hub for explicit Fortnite Sprite demand. `EXPAND_EXISTING_SITE` is still a validation action, not authorization to deploy.

## Validation and decisions

Without real user-supplied or inspected Semrush / GSC / SERP evidence, leave the page at `needs_validation`; retain the 69 pre-validation cap. Twitch viewers, YouTube views and Trends indices must NEVER be converted into Google monthly searches.

When manual evidence is provided, identify market, keyword, date, inspected results and the smallest useful page before recommending Build / Skip. A queue record marked validated is a human-entered record, not proof that the application automatically verified the sources. Do not auto-persist a Build merely because a score is high.

## Output

Prioritize 3–10 games only when evidence warrants it; fewer or none is a valid outcome. For each include game identity, research reason, source availability, actual repeated problem, proposed pages, existing-site fit, next validation task and missing evidence. State when an empty result comes from filters, budgets, missing credentials or collection failure rather than low demand.

Use `references/scoring.md` and `references/serp-evidence.md`. The Dashboard remains the user's daily interface; CLI commands are optional execution support.
