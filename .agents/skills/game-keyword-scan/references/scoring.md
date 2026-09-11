# Scoring boundaries

Game Demand and Page Opportunity are different scores. Source weights 25/20/15/15/15 plus optional direction confirmation 10; normalize observed sources and show coverage separately. Missing is null, never zero. Counts from different platforms are not added.

A source without a valid historical baseline has no 24h/7d direction. Twitch incomplete samples are lower bounds; concentrated audiences have lower confidence. YouTube velocity is views divided by video age, not measured hourly growth. Reddit is a sampled set of titles with community bias.

Page raw score is 0–100; pre-validation displayed score remains at most 69. Gameplay-only nodes are hypotheses. No score means a probability, monthly Google volume or revenue.

See repository `docs/V2_SCORING.md` for implemented formulas and `docs/V2_ACCEPTANCE.md` for tested versus unverified behavior.
