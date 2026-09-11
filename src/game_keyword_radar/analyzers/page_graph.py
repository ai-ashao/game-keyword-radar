from __future__ import annotations
import hashlib
import re
from game_keyword_radar.models import PageOpportunity, EvidenceItem, GameOpportunity, KeywordCandidate, Confidence

# intent: keyword suffix, type, difficulty, maintenance, useful page value
PAGES = {
    'workshop': ('workshop download not working','guide','low','medium','Diagnose Workshop / SteamCMD download failures with actionable fixes.'),
    'calculator': ('crafting calculator','tool','medium','medium','Turn repeated quantity and dependency questions into a deterministic calculation.'),
    'tracker': ('progress tracker','tracker','medium','medium','Track repeated progress checks in one reusable view.'),
    'codes': ('codes','database','low','high','Verified active/expired redeem codes with redemption instructions.'),
    'tier-list': ('tier list','guide','medium','high','Compare explicitly requested characters, weapons or classes with evidence.'),
    'locations': ('boss locations','guide','medium','high','Answer observed location questions, with a searchable location reference.'),
    'builds': ('best builds','guide','medium','high','Explain choices and trade-offs behind observed build questions.'),
    'errors': ('errors and fixes','guide','low','medium','Resolve the specific failures found in source questions.'),
    'walkthrough': ('walkthrough','guide','medium','high','Organize actual puzzle/progression questions into specific solutions.'),
    'guide': ('beginner guide','guide','low','medium','Answer recurring beginner questions with tested steps.'),
}

def page_id(entity, key):
    # Stable within the entity registry; query copy edits do not reset validation.
    return hashlib.sha256(f'{entity.slug}:{key}'.encode()).hexdigest()[:16]

def route_existing(entity, keyword, triggers, settings):
    text = ' '.join([entity.canonical_name, keyword, *(e.title for e in triggers)]).casefold()
    matches = [(len(term), site, term) for site, terms in settings.existing_sites.items() for term in terms
               if re.search(r'(?<!\w)'+re.escape(term.casefold())+r'(?!\w)',text)]
    if not matches: return None, None
    _, site, term = sorted(matches, reverse=True)[0]
    return site, f'Existing-site configured intent match: {term}. Expansion still requires Semrush/SERP validation.'

def build_page_graph(entity, clusters, demand, settings):
    nodes = []
    for cluster in clusters:
        if cluster.intent not in PAGES: continue
        # Location content needs a relevant world/mechanic; explicit boss/resource queries
        # may establish it even where the Steam profile is not available.
        if cluster.intent=='locations' and not ({'open_world','crafting','rpg_builds'} & set(entity.mechanics)):
            if not any(re.search(r'\b(boss|resource|item|npc)\b',e.title,re.I) for e in cluster.examples): continue
        suffix, kind, difficulty, maintenance, value = PAGES[cluster.intent]
        if cluster.intent=='calculator':
            text = ' '.join(e.title for e in cluster.examples).casefold()
            suffix = 'damage calculator' if 'damage' in text else 'drop rate calculator' if 'drop' in text else 'resource calculator' if 'resource' in text else 'crafting calculator'
        if cluster.intent=='locations':
            suffix = 'boss locations' if any('boss' in e.title.casefold() for e in cluster.examples) else 'item locations'
        if cluster.intent=='workshop':
            suffix = 'steamcmd troubleshooting' if any('steamcmd' in e.title.casefold() for e in cluster.examples) else suffix
        triggers = cluster.examples[:20]
        keyword = f'{entity.canonical_name} {suffix}'.lower()
        site, why = route_existing(entity, keyword, triggers, settings)
        nodes.append(dict(intent=cluster.intent, suffix=suffix, kind=kind, difficulty=difficulty, maintenance=maintenance,
            value=value, triggers=triggers, count=cluster.question_count, source_count=cluster.source_count,
            site=site, why=why, keyword=keyword, evidence_level='observed_question' if any(e.source=='reddit' for e in triggers) else 'observed_content_proxy'))
    # Keep a small, explicitly inferred tool hypothesis when mechanics are known.
    # No generic codes, tier-list or map node is ever fabricated here.
    seen = {n['intent'] for n in nodes}
    inferred = [('crafting','calculator','crafting calculator'), ('rpg_builds','build-planner','build planner'),
                ('strategy_economy','production-calculator','production calculator')]
    for mechanic, intent, suffix in inferred:
        if mechanic not in entity.mechanics or intent in seen: continue
        trigger = EvidenceItem(id=f'mechanic:{entity.slug}:{mechanic}', source='mechanic_inference',
            title=f'Metadata indicates {mechanic}; actual query demand is not yet observed.', is_inference=True)
        keyword = f'{entity.canonical_name} {suffix}'.lower()
        site, why = route_existing(entity, keyword, [trigger], settings)
        nodes.append(dict(intent=intent,suffix=suffix,kind='tool',difficulty='high' if mechanic=='rpg_builds' else 'medium',
            maintenance='medium',value='Validate the underlying gameplay system before building a calculator/planner.',
            triggers=[trigger],count=0,source_count=0,site=site,why=why,keyword=keyword,evidence_level='hypothesis'))
    pages = []
    for node in nodes:
        is_observed = node['count']>0
        breakdown = {
            'problem_query_evidence':min(20,8+node['count']*2+max(0,node['source_count']-1)*3) if is_observed else 2,
            'search_page_intent':20 if node['kind'] in {'tool','tracker'} else 16,
            'page_graph_breadth':min(15,len(nodes)*3),
            'build_feasibility':{'low':15,'medium':10,'high':5}[node['difficulty']],
            'maintenance_cost':{'low':10,'medium':7,'high':3}[node['maintenance']],
            'game_demand_contribution':round((demand.score or 0)*.1*demand.coverage,2),
            'evidence_confidence':min(10,4+node['source_count']*2) if is_observed else 1,
        }
        raw = round(sum(breakdown.values()),1)
        pages.append(PageOpportunity(id=page_id(entity,node['intent']),game_slug=entity.slug,page_type=node['kind'],
            path='/'+node['suffix'].replace(' ','-'), primary_keyword_hypothesis=node['keyword'],
            supporting_queries=list(dict.fromkeys(e.title for e in node['triggers'] if not e.is_inference)),
            trigger_signals=node['triggers'],user_problem=node['value'],page_value=node['value'],
            maintenance_level=node['maintenance'],build_difficulty=node['difficulty'],
            existing_site_fit=node['site'],route_reason=node['why'],score=min(69,raw),raw_score=raw,score_breakdown=breakdown,
            evidence_level=node['evidence_level'],keyword_candidates=[KeywordCandidate(keyword=node['keyword'],
                cluster=node['intent'],page_type=node['kind'],intent=node['intent'],trigger='; '.join(e.id for e in node['triggers']),
                rationale=node['value'],build_difficulty=node['difficulty'],maintenance_level=node['maintenance'],
                evidence_confidence=Confidence.MEDIUM if is_observed else Confidence.LOW)]))
    return sorted(pages,key=lambda p:(-p.raw_score,p.id))

def route_game(entity, demand, pages):
    observed = [p for p in pages if p.evidence_level!='hypothesis']
    if observed and any(p.existing_site_fit for p in observed):
        action, reason = 'EXPAND_EXISTING_SITE', 'Observed demand fits an existing site; validate the page before expansion.'
    elif len(observed)>=4 and len(demand.available_sources)>=2:
        action, reason = 'VALIDATE_NEW_SITE', 'Several distinct observed page intents; research an independent site, not an automatic Build.'
    elif observed and len(demand.available_sources)>=2:
        action, reason = 'VALIDATE', 'Observed intent plus multiple platforms: inspect Semrush and live SERP.'
    elif demand.score is not None and demand.score<15 and not pages and demand.coverage>=.6:
        action, reason = 'SKIP', 'Low observed traction and no usable page intent within this sample.'
    else:
        action, reason = 'WATCH', 'Evidence is incomplete or inferred. Missing platforms are not evidence against demand.'
    best = max((p.raw_score for p in pages),default=0)
    priority = round((.55*(demand.score or 0)+.45*best)*(.4+.6*demand.coverage),1)
    return GameOpportunity(game_slug=entity.slug,demand=demand,page_ids=[p.id for p in pages],action=action,
        action_reason=reason,best_page_score=max((p.score for p in pages),default=None),research_priority=priority)
