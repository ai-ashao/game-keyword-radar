# V2.1 Implementation receipt

## Implemented specification map

M0: original V2 docs retained as historical references. V2_1_PLAN is current spec; README/context/Skill/status use2.1 semantics.
M1: research_models.py, observations.py, analyzers/lifecycle.py and momentum.py; first_seen/chronology separate; actual timestamp identity; window and point-pair levels; immutable legacy snapshots; Twitch-only counts and unchanged fixed.
M2: pipeline.py Observe -> Compare -> Admit -> Allocate -> Deep; sources/steam.py protects new-release metadata and keeps raw rows; sources/twitch.py direct game queries and bounded attempts; candidate_selection.py deterministic quotas, OR attention triggers, exploration cap, manual budget and cooldown.
M3: monitoring.py and monitoring snapshots, shared fcntl lock, opt-in service loop, gaps without historical fabrication; Deep sources not called in monitor mode.
M4: frontend WHY NOW, four lanes, funnel, deferred/monitor views, manual seed/evidence, process-only policy editor; reporter/Skill updated; questions vs proxies separated; actual manual SERP gate retained.
M5: offline tests and browser DOM integration executed; live levels not passed in this environment. See acceptance log, not previous release test totals.

## Explicit implementation choices

- Default recent dated task evidence window is14days, configurable selection.recent_demand_days. This fills the spec's unspecified “近期” window; it is not a measured market rule.
- Broad source_row_limit100 and runtime discovery_limit80 are per-source request caps; total union entity count may exceed80. Metadata budget, active pool and Deep count are independent.
- Unknown Twitch-only release chronology stays unknown. Exact aliases/platform mappings can be set manually; no automatic whole-web release research or fuzzy merge.
- A mature untriggered entity stays in raw/monitor view. To maintain regular history off the listing, explicitly add it to the watch list. The radar does not observe every mature game in the market.
- Policy editor is process-local. Persist settings manually in radar.toml; upgrade never overwrites user config.
- Full scans and monitor-only runs share the provider and history layer. Monitor mode may refresh bounded discovery/metadata but never performs YouTube/Reddit/Trends deep enrichment or replaces full report.
- Group sorts are deterministic research heuristics (provenance grade, comparison evidence, observation/deep wait, slug). No learned probability or SERP competition estimate is introduced.
- Old multi-source Demand remains available for old readers. New PageOpportunity uses evidence support; actual Google Volume must be manually supplied.

## Local commands

`game-radar scan --deep 10 --selection-profile opportunity`, `monitor-once`, `candidates --lane exploration`, `explain SLUG --run-id ID`, existing serve/report/compare/validate/sources.

## API changes

GET/PUT /api/policy (typed, process-only, no secrets); GET /api/monitoring; POST /api/monitoring/start, /stop, /once; GET /api/candidates; GET /api/explain/{slug}; POST /api/seeds; PUT /api/annotations. Existing snapshot/report/validation routes remain. Write requests enforce local host/origin boundaries and share operation locks where applicable.

## Business regression index

`test_v21_selection.py`: A01-03, A06-33 and A40 applicable lifecycle/selection/window scenarios; use regression XML for exact parametrized cases rather than treating the matrix as40 independent test functions.
`test_v21_pipeline.py`: A04/A05 directed chain, A25 no-Deep, A36 separated deltas, A37 monitoring/shared lock/gaps, manual seed/policy/source budgets; MockTransport not live network.
`test_v21_regressions.py`: A34 counts1/1 and A35 unchanged.
Existing v1_contracts/v2_core/v2_pipeline_web plus restored test_web cover historical readers, demo/live isolation and manual Build rejection (A38/A39). Browser smoke exercises actual DOM forms against ASGI, not live upstream.

The original 40 scenarios remain the product acceptance rubric; new tests combine related scenarios and parameterize boundaries. Their success does not substitute real L1-L4 evidence.
