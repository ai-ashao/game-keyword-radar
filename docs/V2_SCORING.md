> Historical V2 RC1 reference. V2.1 implementation is governed by V2_1_PLAN.md and V2_1_IMPLEMENTATION.md; legacy Demand is no longer the initial selector.

# Scoring contract · V2 RC1

## Game Demand Momentum

Source weights: Steam 25, Twitch 20, Trends 15, YouTube 15, Reddit 15. Sources are normalized independently on explicit heuristic scales; raw counts from different platforms are never added.

Each component is `null` when its metrics are missing, unavailable or failed. A measured zero remains a measured zero. The score is the weighted average of **observed components**, not the sum of all weights with missing set to zero. Coverage is `observed source weights / 90` and is displayed separately. A one-source score of 80 is not equivalent in confidence to a four-source score of 80.

Steam emphasizes log-scaled current players, a review-scale proxy and release age. Twitch emphasizes log-scaled sampled viewers and channels; a top streamer above 70% of observed viewers multiplies its source component by 0.65. YouTube emphasizes sampled guide count, creator breadth, views-per-hour proxy and intent share. Reddit emphasizes question count, repeated title-intent clusters and known authors. Trends uses relative change, not absolute Google volume.

An observed 24h / 7d rise above 10% adds 10 normalized source points (bounded at 100); a fall below -10% subtracts 10. Missing historical samples do not invent a direction. Trends uses its collected relative series direction.

Cross-platform confirmation is 4 / 7 / 10 points when at least 2 / 3 / 4 sources have an observed rising direction. It is only scored when at least two historical directions are known; otherwise that component is null. When present, it is an additional weight-10 dimension. This avoids interpreting missing directions as disagreement.

Final card ordering blends 55% Demand with 45% strongest raw Page score and discounts incomplete coverage by `(0.4 + 0.6 * coverage)`. This is an adjustable **research priority**, not a probability, predicted revenue, or Google monthly search volume.

## Page Opportunity

Independent 0–100 raw score: problem/query evidence 20, page intent 20, graph breadth 15, feasibility 15, maintenance cost 10, demand contribution 10, evidence confidence 10.

`score = min(raw_score, 69)`, `validation_status = needs_validation` in immutable snapshots. The UI exposes raw score for research ordering but retains the pre-validation cap. Manually completing a record does not rewrite historical score or automatically raise it to 100.

Evidence levels: `observed_question` (Reddit title evidence), `observed_content_proxy` (answer-oriented video evidence), `hypothesis` (explicit gameplay inference). Repeated titles and creators are only proxies; they are not search queries observed in GSC.

## Validation

Pending Semrush permits incomplete evidence. Pending SERP requires nonnegative observed Semrush volume (zero allowed), a concrete evidence note and a timezone-aware, non-future check time. Validated additionally requires at least three distinct HTTP(S) result URLs, SERP notes, a check time, Build / Skip and a rationale. This validates the completeness of a **human record**, not the factual truth of its contents.

Existing-site routing always precedes a new-site research suggestion when observed page demand fits an existing site. Expansion is still subject to human validation.
