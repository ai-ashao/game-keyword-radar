# Scoring reference

Game signal is a deterministic 0-100 prioritization score derived from Steam rank, current players, review scale, release recency, and mechanics-understanding confidence.

Keyword opportunity score combines problem intensity, page intent, feasibility, low maintenance, game signal, and evidence confidence.

Hard limits:

- No live SERP evidence: maximum 69 and `needs_validation`.
- Low mechanics confidence: maximum 59.
- Missing fields contribute no points and reduce completeness; they are not imputed.
- Optional Trends data describes within-query direction only.

The current formula and weights live in `docs/IMPLEMENTATION_PLAN.md`. Python implementations live in `src/game_keyword_radar/analyzers/scoring.py`.
