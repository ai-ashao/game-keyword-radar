# V2 RC1 architecture

## Integration rather than a new framework

The existing Python package, Pydantic models, FastAPI/Jinja local UI, JSON storage, CLI, Markdown reporter and Steam gameplay inference remain the foundation. `GameCandidate`, `KeywordCandidate`, legacy opportunity data and V1 history remain readable. The new pipeline preserves legacy `games` / `opportunities` alongside V2 entities and Page Graph.

New modules:

- `sources/base.py`: bounded HTTP provider, hashed JSON cache, sanitized failures.
- `sources/steam.py`: broad store discovery and independent metadata / current-player hydration. Legacy `collectors/steam.py` remains for old callers; V2 uses the new adapter.
- `sources/twitch.py`: client-credentials token cache; top games, game metadata, global stream sample, bounded per-game streams; stream deduplication and concentration.
- `sources/youtube.py`: relevant recent search sample, videos statistics, per-scan and persistent local daily budgets.
- `sources/reddit.py`: public Atom RSS, explicit subreddit overrides, deduplicated title evidence. No comment-count invention.
- `sources/trends.py`: optional legacy provider; authorized official adapter seam. No unauthenticated official endpoint is assumed.
- `analyzers/entity_resolution.py`: explicit ID / exact / normalized / alias merge; fuzzy suggestions only.
- `analyzers/question_mining.py`: deterministic intent clusters retaining title, URL, source, author when available and timestamps.
- `analyzers/demand_momentum.py`: observed-source normalization and separate coverage.
- `analyzers/page_graph.py`: evidence-triggered nodes, narrowly scoped gameplay hypotheses and existing-site routing.
- `history_v2.py`: per-signal time-window matching and compatible-sample comparison, alongside legacy history.
- `validation.py`: manual records stored separately from immutable scan evidence.

## Pipeline

1. Acquire a local nonblocking scan lock, preventing simultaneous CLI / browser scans.
2. Discover Steam and Twitch independently; source failure does not discard the other's candidates.
3. Resolve entities against the persisted registry and explicit aliases. Keep Twitch-only games.
4. Bound the merged pool and select Top N by preliminary observed traction.
5. Fetch Twitch / YouTube / Reddit / optional Trends for Top N only. Catch failures per game and source.
6. Add all five per-game source states, including skipped / unavailable / insufficient data.
7. Match actual observation timestamps to compatible historical samples.
8. Cluster title evidence; score demand separately; generate and score Page Graph; route existing sites first.
9. Save raw evidence, entity registry, immutable snapshot, history index and Markdown report. Failed empty scans save diagnostics but never replace the last usable snapshot.

## Intent discipline

Codes are triggered by redeem / promo / gift-code evidence, not a universal template. Tier lists need explicit comparison titles. Location pages need relevant mechanics or explicit boss / item / resource questions. Gameplay-only fallback is limited to calculators / planners and marked `hypothesis`.

A Page Graph is a research graph, not an automatic page factory. Each node keeps its source triggers and explains its user problem, value, cost and routing rationale. No inferred node is described as proven Google search demand.

## Browser routes

`/`, `/api/snapshot`, `/api/snapshots`, `/api/snapshots/{run_id}`, `/api/scan`, `/api/status`, `/api/demo`, `/api/report`, `/api/compare`, `/api/sources`, `/api/validation`, `/api/keywords.csv`, `/health`.

The HTML shell, stylesheet and JS are local assets. External titles and URLs are escaped / protocol checked. Writes reject cross-origin requests; allowed hosts are loopback plus the in-process test hostname. CSP disables external scripts and framing. No credentials appear in configuration responses.

## Deliberate RC1 limits

The canonical configuration is TOML, not YAML: Python 3.11 supplies a parser, avoiding another dependency. Official Trends Alpha only has an authorized adapter seam. Automatic subreddit discovery is deferred; explicit game subreddits and generic r/gaming / r/Steam searches are implemented. View counts and Reddit title counts describe retrieved samples. No live endpoint success is claimed without `live_acceptance.py` evidence. Font files and API credentials are never part of the release package.
