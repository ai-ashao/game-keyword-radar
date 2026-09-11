#!/usr/bin/env python3
"""Explicit live acceptance, outside default offline tests.
Run in the existing project after configuring personal API credentials.
Exit 0 only when Steam, Twitch AND YouTube have actual usable observations.
No fixture fallback is permitted.
"""
from __future__ import annotations
import argparse
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from game_keyword_radar.config import Settings
from game_keyword_radar.pipeline import Scanner
from game_keyword_radar.models import SourceState

async def run(args):
    settings=Settings.load(args.root)
    settings.request_timeout=args.timeout
    # Acceptance is small but should include enough candidate games for exact matching.
    settings.steam_enabled=True;settings.twitch_enabled=True;settings.youtube_enabled=True
    settings.reddit_enabled=False;settings.trends_enabled=False
    snapshot=await Scanner(settings).run(discovery_limit=args.discovery,deep=args.deep,with_trends=False)
    checks={source:any(s.source==source and s.status in {SourceState.OK,SourceState.PARTIAL} and bool(s.metrics)
        for s in snapshot.platform_signals) for source in ('steam','twitch','youtube')}
    result={'acceptance':'passed' if all(checks.values()) and not snapshot.is_demo else 'not_passed',
        'run_id':snapshot.run_id,'is_demo':snapshot.is_demo,'checks':checks,
        'credentials_configured':{'twitch':bool(settings.twitch_client_id and settings.twitch_client_secret),'youtube':bool(settings.youtube_api_key)},
        'source_statuses':[s.model_dump(mode='json') for s in snapshot.source_statuses],
        'note':'Passing requires actual observations; configured credentials and fixtures alone do not count.'}
    output=args.output or settings.reports_dir/'live-acceptance.json'
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['acceptance']=='passed' else 2

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output',type=Path)
    parser.add_argument('--discovery',type=int,default=10)
    parser.add_argument('--deep',type=int,default=5)
    parser.add_argument('--timeout',type=float,default=15)
    args=parser.parse_args()
    try:return asyncio.run(run(args))
    except Exception as exc:
        from game_keyword_radar.sources.base import safe_error
        print('Live acceptance failed: '+safe_error(exc),file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
