# 2.1.0rc1 — Selection correction

Base: 99f7f9e42cae7967f53ffde3c7b339eea08a9963 / 2.0.0rc1. No GitHub write performed.

- Replaced popularity-first Deep slicing with basic observation -> history -> lifecycle/trigger admission -> lane allocation.
- Protected recent-release ingress and directed Twitch queries; preserved Twitch-only entities and explicit unresolved identity.
- Added versioned policy models, observation identity, compatible multi-point history, reasons, cooldown, annotations and local monitoring.
- Separated actual questions, content proxies, and mechanic hypotheses. Legacy score is not the primary selector or main UI score.
- Corrected unchanged/counting history regressions and old-platform release date replacement.
- Added process-only browser policy controls, monitoring, manual seeds, WHY NOW, funnel and diagnostics; kept existing validation gates.
- Added regression cases derived from A01-A40 and offline Chromium/ASGI integration harness.

Existing test expectation changes: asset version ->2.1.0rc1; UI demo now five synthetic cases rather than three; second full scan may create new pages due to fair lane rotation (existing stable IDs must remain a subset). No existing validation or source-failure assertions were removed.
