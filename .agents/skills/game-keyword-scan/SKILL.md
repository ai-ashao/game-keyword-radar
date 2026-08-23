---
name: game-keyword-scan
description: Review and extend Game Keyword Radar local scans. Use when the user asks to scan Steam games, inspect game keyword opportunities, prioritize a tool/guide/database idea, validate a candidate with live SERP evidence, or explain the latest Game Keyword Radar report.
---

# Game Keyword Scan

Use the repository's deterministic pipeline for collection and scoring. Use agent judgment only for evidence gathering and interpretation.

## Workflow

1. Read `docs/AUDIT.md` and `docs/IMPLEMENTATION_PLAN.md` when the request changes scope or scoring.
2. Check `data/latest.json`. If it is missing or stale for the user's purpose, run `game-radar scan --limit 10` from the repository root.
3. Confirm the snapshot market, timestamp, `is_demo`, source statuses, and errors before interpreting opportunities.
4. Shortlist at most five opportunities by score, mechanics fit, build effort, and evidence completeness.
5. For a requested or shortlisted opportunity, inspect the live SERP in the snapshot market. Follow [SERP evidence](references/serp-evidence.md).
6. Separate:
   - observed facts from Steam or live SERP;
   - rule-based inferences;
   - missing or unavailable metrics.
7. Recommend one next validation action. Do not recommend implementation until the exact intent and existing tool coverage are confirmed.

## Output

Lead with the highest-signal conclusion, then provide:

| Game | Opportunity | Score | Evidence present | Evidence missing | Next action |
|---|---|---:|---|---|---|

For live SERP work, list the query, market, check time, representative ranking URLs, domain classifications, intent finding, and tool coverage.

## Guardrails

- Treat `is_demo: true` as fixture data, never as current evidence.
- Do not call the score search volume, traffic potential, keyword difficulty, or revenue potential.
- Do not compare Google Trends 0-100 values across separate query batches as absolute demand.
- Do not turn missing Trends data into zero demand.
- Do not claim a game mechanic unless the snapshot or a cited source supports it.
- Do not raise an opportunity above `needs_validation` without live SERP evidence.
- Do not alter scoring rules without updating `docs/IMPLEMENTATION_PLAN.md` and tests.

Read [Scoring](references/scoring.md) when interpreting or changing scores.
