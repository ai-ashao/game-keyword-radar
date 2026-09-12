# V2.2 RC change log

- Added conservative cross-platform entity resolution: name-only matches become review suggestions instead of automatic merges.
- Strengthened observation scope keys so provider/window/measurement/market differences cannot silently form one numeric time series.
- Upgraded question mining and Page Graph from intent-only buckets to deterministic task-level clusters.
- Added public Sitemap/Sitemap Index incremental discovery with first-run baseline semantics and partial-coverage safety.
- Added Google Trends Trending RSS discovery plus a deduplicated Discovery Inbox; hints remain unresolved until entity review.
- Added validation-pack export plus append-only Semrush and Google Trends CSV evidence imports.
- Added a persistent circuit breaker for optional best-effort providers.
- Added zero-new-credential YouTube fallback through an already-installed `yt-dlp`; it runs only when the existing Deep path asks YouTube for evidence.
- Explicitly does **not** automate SullyGnome scraping; Twitch third-party public statistics remain manual evidence when no Twitch credentials are configured.
- Roblox remains experimental and is not part of the zero-key core until anonymous access is verified at implementation time.
