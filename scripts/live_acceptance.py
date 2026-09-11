#!/usr/bin/env python3
"""Explicit live V2.1 acceptance (never used by default offline tests).

Exit 0 requires real Steam, directed Twitch and YouTube evidence, including a
joined Steam/Twitch entity. Cross-day evidence and manual product review are
reported separately: a network pass alone never makes this a production release.
Uses bounded real requests; no fixture fallback or credential output.
"""
from __future__ import annotations
import argparse
import asyncio
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from game_keyword_radar.config import Settings
from game_keyword_radar.pipeline import Scanner
from game_keyword_radar.models import SourceState

VALID={SourceState.OK,SourceState.PARTIAL}


def real_signal(signal):
    return signal.origin == 'live' and signal.status in VALID


def accepted_sources(snapshot):
    steam={s.game_slug for s in snapshot.platform_signals if real_signal(s)
           and s.source=='steam' and isinstance(s.metrics.get('current_players'),int)
           and not isinstance(s.metrics.get('current_players'),bool)}
    twitch={s.game_slug for s in snapshot.platform_signals if real_signal(s)
            and s.source=='twitch' and s.metrics.get('sampling_scope')=='game_streams'
            and isinstance(s.metrics.get('total_viewers'),(int,float))
            and not isinstance(s.metrics.get('total_viewers'),bool)}
    youtube={s.game_slug for s in snapshot.platform_signals if real_signal(s)
             and s.source=='youtube' and any(e.source=='youtube' and e.url and not e.is_inference for e in s.evidence)}
    return {'steam':bool(steam),'directed_twitch':bool(twitch),'youtube_evidence':bool(youtube),
            'joined_steam_twitch_entity':bool(steam & twitch)}, sorted(steam & twitch)


async def run(args):
    settings=Settings.load(args.root)
    settings.request_timeout=args.timeout
    settings.steam_enabled=True;settings.twitch_enabled=True;settings.youtube_enabled=True
    settings.reddit_enabled=False;settings.trends_enabled=False
    snapshot=await Scanner(settings).run(discovery_limit=args.discovery,deep=args.deep,with_trends=False)
    checks,joined=accepted_sources(snapshot)
    comparable=[{'game_slug':d.game_slug,'state':d.momentum.state,
                 'periods':sorted({c.period for c in d.momentum.comparisons if c.qualified})}
                for d in snapshot.selection_decisions if any(c.qualified for c in d.momentum.comparisons)]
    leaks=[d.game_slug for d in snapshot.selection_decisions if d.entry_origin=='automatic'
           and d.selected_for_deep and 'mature_without_new_trigger' in d.reason_codes]
    result={'version':'2.1.0rc1','acceptance':'passed' if all(checks.values()) and not snapshot.is_demo else 'not_passed',
        'run_id':snapshot.run_id,'is_demo':snapshot.is_demo,'checks':checks,'joined_entities':joined,
        'credentials_configured':{'twitch':bool(settings.twitch_client_id and settings.twitch_client_secret),
                                  'youtube':bool(settings.youtube_api_key)},
        'L1_core_chain':'passed' if checks['steam'] and checks['directed_twitch'] and joined else 'not_passed',
        'L2_qualified_windows':comparable,'L2_state':'observed' if comparable else 'not_yet_observed',
        'L3_page_evidence':'passed' if checks['youtube_evidence'] else 'not_passed',
        'L4_mature_without_trigger_leaks':leaks,'L4_manual_review':'pending',
        'selection_summary':snapshot.selection_summary,
        'source_statuses':[s.model_dump(mode='json') for s in snapshot.source_statuses],
        'note':'Token, HTTP 200, category ranks and demo data do not pass. L2 and manual usefulness still require separate evidence.'}
    output=args.output or settings.reports_dir/'live-acceptance.json'
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['acceptance']=='passed' else 2


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output',type=Path)
    parser.add_argument('--discovery',type=int,default=30)
    parser.add_argument('--deep',type=int,default=10)
    parser.add_argument('--timeout',type=float,default=15)
    args=parser.parse_args()
    if not 1<=args.discovery<=100 or not 0<=args.deep<=30 or not 0<args.timeout<=60:
        parser.error('discovery: 1..100; deep: 0..30; timeout: (0,60]')
    try:return asyncio.run(run(args))
    except Exception as exc:
        from game_keyword_radar.sources.base import safe_error
        print('Live acceptance failed: '+safe_error(exc),file=sys.stderr)
        return 1

if __name__=='__main__':raise SystemExit(main())
