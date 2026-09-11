"""Observed-source research ranking. No cross-platform counts are added together."""
from __future__ import annotations
import math
from game_keyword_radar.models import DemandScore, Confidence, SourceState

WEIGHTS = {'steam':25, 'twitch':20, 'trends':15, 'youtube':15, 'reddit':15}
VALID = {SourceState.OK, SourceState.PARTIAL}

def number(x):
    return isinstance(x, (float,int)) and not isinstance(x,bool) and math.isfinite(x)

def logarithmic(value, cap):
    return min(100, max(0, 100*math.log1p(value)/math.log1p(cap))) if number(value) and value>=0 else None

def average(parts):
    present = [(v,w) for v,w in parts if v is not None]
    return sum(v*w for v,w in present)/sum(w for _,w in present) if present else None

def direction(signal):
    if signal.status not in VALID: return None
    if signal.source == 'trends':
        return signal.metrics.get('trend_direction')
    # Never treat two nearby local scans as a 24h change.
    for period in ('24h','7d'):
        comparison = signal.history.get(period) or {}
        percent = comparison.get('primary_percent')
        if number(percent):
            return 'rising' if percent>10 else 'falling' if percent < -10 else 'flat'
    return None

def component(signal):
    if signal.status not in VALID: return None
    m = signal.metrics
    if signal.source == 'steam':
        base = average([(logarithmic(m.get('current_players'),100000), .7),
                        (logarithmic(m.get('reviews_total'),100000), .2),
                        (max(0, 100-m['release_age_days']) if number(m.get('release_age_days')) and m['release_age_days']>=0 else None, .1)])
    elif signal.source == 'twitch':
        base = average([(logarithmic(m.get('total_viewers'),100000), .7), (logarithmic(m.get('live_channels'),500), .3)])
        concentration = m.get('audience_concentration')
        if base is not None and number(concentration) and concentration>.7:
            base *= .65
    elif signal.source == 'youtube':
        base = average([(logarithmic(m.get('recent_guide_video_count'),50),.4),
                        (logarithmic(m.get('creator_count'),20),.2),
                        (logarithmic(m.get('view_velocity_proxy'),10000),.2),
                        (100*m['intent_video_share'] if number(m.get('intent_video_share')) else None,.2)])
    elif signal.source == 'reddit':
        base = average([(logarithmic(m.get('question_count'),30),.4),
                        (logarithmic(m.get('repeated_question_clusters'),5),.4),
                        (logarithmic(m.get('unique_authors'),20),.2)])
    elif signal.source == 'trends':
        delta = m.get('direction_delta')
        ratio = m.get('recent_vs_baseline')
        base = min(100,max(0,50+25*math.log2(max(ratio,.01)))) if number(ratio) else min(100,max(0,50+delta)) if number(delta) else None
    else: return None
    if base is None: return None
    change = direction(signal)
    if signal.source != 'trends':
        base = min(100,base+10) if change=='rising' else max(0,base-10) if change=='falling' else base
    return round(base,2)

def score_demand(signals):
    lookup = {s.source:s for s in signals}
    parts = {source:component(lookup[source]) if source in lookup else None for source in WEIGHTS}
    present = [k for k,v in parts.items() if v is not None]
    observed = sum(WEIGHTS[k] for k in present)
    directions = {k:direction(lookup[k]) for k in present}
    known = [d for d in directions.values() if d is not None]
    rising = [k for k,d in directions.items() if d=='rising']
    confirmation = 10 if len(rising)>=4 else 7 if len(rising)==3 else 4 if len(rising)==2 else 0
    # Unknown historical directions do not count as disagreement or a zero component.
    parts['cross_platform'] = float(confirmation) if len(known)>=2 else None
    numerator = sum(parts[k]*WEIGHTS[k] for k in present)
    denominator = observed
    if parts['cross_platform'] is not None:
        numerator += confirmation*100
        denominator += 10
    score = round(numerator/denominator,1) if denominator else None
    confidence = Confidence.HIGH if len(present)>=4 and len(rising)>=3 else Confidence.MEDIUM if len(present)>=2 else Confidence.LOW
    return DemandScore(score=score, components=parts, observed_weight=observed, coverage=round(observed/90,3),
        available_sources=present, rising_sources=rising, confidence=confidence,
        note='Source components use their own scales. Score normalizes observed weights; missing is null. Coverage is separate. Research ranking, not Google volume or success probability.')
