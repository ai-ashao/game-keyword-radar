# Project Context — V2.1 RC

Local-first Game Demand Radar + Keyword / Page Opportunity Research Workbench.
Current implementation source: docs/V2_1_PLAN.md; base commit 99f7f9e42cae7967f53ffde3c7b339eea08a9963.

Steam/Twitch basic observation and eligible history MUST run before automatic Deep allocation. New release / rising / new demand / exploration are separate lanes. A mature high-volume game with no new trigger is monitor_only, never a filler. Local first_seen is not release age. Missing data is null, not zero or stable.

Legacy Demand remains diagnostic only. Decisions are immutable and replayable with policy hash, as_of and evidence IDs. Keep V1/V2 historical reads; do not rewrite old snapshots or validation records. Preserve .env/radar.toml/data/reports on upgrade. Never push GitHub unless explicitly requested.

UI is primary, local monitoring is opt-in and process-bound; no jobs run after process shutdown or during sleep. All runtime evidence is separate from synthetic tests. No live joint/cross-day acceptance is claimed by this RC.

Not a content publishing tool; no hard dependency on game-content-radar or ShipLean. No automatic Build / domain purchase / paid API purchase. Semrush/SERP evidence must be human verified.
