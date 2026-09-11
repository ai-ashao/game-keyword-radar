# Feature Status · V2 RC1

| Area | Implementation | Acceptance boundary |
|---|---|---|
| Steam / Twitch discovery | Implemented; bounded and independently degradable | Mocked integration passed; real joint scan not passed here |
| YouTube | Search → videos, intent sample, cache and persistent call budget | Offline transport tests passed; actual API key needed |
| Reddit | Public RSS + title clustering | Offline RSS tests passed; live access may be refused |
| Trends legacy | Optional provider, cache, missing-data semantics | Adapter behavior implemented; optional package / live service not exercised here |
| Trends official | Authorized adapter injection seam | No Alpha credentials or concrete authorized adapter supplied |
| Entity resolution | ID / exact / normalized / alias; fuzzy suggestions only | Offline tests passed |
| Page Graph / routing | Evidence-based nodes, explicit hypotheses, existing sites | Offline tests passed |
| Validation Queue | Browser form, server gates, separate persistence | Offline Chromium + ASGI workflow passed |
| V1 snapshot compatibility | Read-only restore, original core contracts preserved | Compatibility tests passed |
| History | Compatible observation windows, sample scope, rank / score / page diffs | Offline tests passed |
| Local Dashboard | Overview, detail, pages, queue, history, sources | Desktop / 390px / 768px offline browser checks passed |
| Reports / Skill | V2 Markdown, CSV export, updated Codex Skill | Artifact / contract tests passed |

No automatic article generation, social posting, SaaS, user accounts, database service, massive SERP crawler or auto Build is included.
