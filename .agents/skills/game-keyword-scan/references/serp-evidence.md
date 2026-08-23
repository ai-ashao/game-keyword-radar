# SERP evidence

For each checked keyword, record:

- exact query;
- country and language;
- UTC check time;
- top representative URLs and titles;
- domain type: `official`, `large_publisher`, `wiki`, `community`, `video`, `independent_site`, `interactive_tool`, `marketplace`, or `unrelated`;
- whether the result directly satisfies the query;
- whether a working interactive tool already exists;
- whether version freshness affects usefulness.

Decide page clustering by shared intent and overlapping result types, not lexical similarity alone.

Never infer exact traffic from rank position or third-party marketing copy. If the live search tool is unavailable, report `SERP evidence unavailable` and keep the opportunity at `needs_validation`.
