from __future__ import annotations
import json
import time
from datetime import timedelta
from pathlib import Path
import httpx
import pytest
from game_keyword_radar.config import Settings
from game_keyword_radar.models import GameEntity, SourceState, utc_now
from game_keyword_radar.sources.base import JsonCache, safe_error, BudgetExceeded
from game_keyword_radar.sources.twitch import TwitchProvider
from game_keyword_radar.sources.youtube import YouTubeProvider,relevant
from game_keyword_radar.sources.reddit import RedditProvider
from game_keyword_radar.sources.trends import OfficialTrendsProvider,LegacyTrendsProvider
from game_keyword_radar.sources.steam import SteamProvider,SearchRow,PLAYER_COUNT_URL

@pytest.fixture
def entity():return GameEntity(canonical_name='Example Game',slug='example-game',platform_ids={'twitch':'42'})
@pytest.fixture
def settings(tmp_path):return Settings(project_root=tmp_path,twitch_client_id='id',twitch_client_secret='secret',youtube_api_key='key')

def test_twitch_deduplicates_streams():
    rows=[{'id':'1','game_id':'42','viewer_count':50,'user_id':'u1'},{'id':'1','game_id':'42','viewer_count':50,'user_id':'u1'},{'id':'2','game_id':'42','viewer_count':20,'user_id':'u2'}]
    m=TwitchProvider.aggregate(rows)
    assert m['total_viewers']==70 and m['live_channels']==2 and m['metric_label']=='sample_lower_bound'

def test_twitch_empty_full_sample_real_zero():
    m=TwitchProvider.aggregate([],complete=True,scope='game_streams')
    assert m['total_viewers']==0 and m['sampling_complete']

async def test_twitch_missing_credentials_no_network(tmp_path,entity):
    provider=TwitchProvider(Settings(project_root=tmp_path),httpx.AsyncClient(transport=httpx.MockTransport(lambda r:(_ for _ in ()).throw(AssertionError()))))
    signal=await provider.fetch(entity)
    assert signal.status==SourceState.UNAVAILABLE and signal.metrics=={}

async def test_twitch_oauth_refresh_and_private_cache(settings,entity):
    tokens=0;requests=0
    def handler(request):
        nonlocal tokens,requests
        if request.url.path.endswith('/token'):
            tokens+=1
            assert b'client_secret=secret' in request.content
            return httpx.Response(200,json={'access_token':f'token{tokens}','expires_in':3600})
        requests+=1
        if requests==1:return httpx.Response(401,json={'error':'expired'})
        assert request.headers['authorization']=='Bearer token2'
        return httpx.Response(200,json={'data':[{'id':'s1','user_id':'u1','viewer_count':20,'game_id':'42'}],'pagination':{}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider=TwitchProvider(settings,client);signal=await provider.fetch(entity)
        assert tokens==2 and signal.metrics['total_viewers']==20
        assert provider.token_path.stat().st_mode&0o777==0o600
        assert 'token2' not in json.dumps(provider.raw)
        again=await provider.fetch(entity)
        assert again.cache_hit and requests==2

async def test_twitch_expired_token_disk_cache(settings):
    called=[]
    def handler(request):
        called.append(str(request.url));return httpx.Response(200,json={'access_token':'new','expires_in':3600})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider=TwitchProvider(settings,client);provider.token_path.parent.mkdir(parents=True)
        provider.token_path.write_text(json.dumps({'token':'old','expires_at':time.time()-10}))
        assert await provider.token()=='new' and len(called)==1

async def test_twitch_missing_in_global_sample_not_zero(settings):
    def handler(req):
        if '/oauth2/token' in str(req.url):return httpx.Response(200,json={'access_token':'t','expires_in':3600})
        if req.url.path.endswith('/games/top') or req.url.path.endswith('/games'):
            return httpx.Response(200,json={'data':[{'id':'42','name':'Example Game'},{'id':'43','name':'Other Game'}]})
        return httpx.Response(200,json={'data':[{'id':'s','user_id':'u','game_id':'42','viewer_count':20}],'pagination':{'cursor':'next'}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        p=TwitchProvider(settings,client);games,signals=await p.discover(2)
        absent=next(s for s in signals if s['game_id']=='43')
        assert 'total_viewers' not in absent['metrics']
        present=next(s for s in signals if s['game_id']=='42')
        assert present['metrics']['total_viewers']==20

def test_relevance_boundaries(entity):
    assert relevant(entity,'Best Example Game builds')
    assert not relevant(entity,'Best Example Gamespot builds')

def youtube_handler(req):
    if req.url.path.endswith('/search'):
        return httpx.Response(200,json={'items':[{'id':{'videoId':'v1'},'snippet':{'title':'Example Game best build guide'}},{'id':{'videoId':'v1'},'snippet':{'title':'Example Game best build guide'}}]})
    return httpx.Response(200,json={'items':[{'id':'v1','snippet':{'title':'Example Game best build guide','channelId':'c1','publishedAt':(utc_now()-timedelta(days=2)).isoformat()},'statistics':{'viewCount':'4800'}}]})

async def test_youtube_dedup_stats_and_cache(settings,entity):
    async with httpx.AsyncClient(transport=httpx.MockTransport(youtube_handler)) as client:
        p=YouTubeProvider(settings,client);s=await p.fetch(entity)
        assert s.metrics['recent_video_count']==1 and s.metrics['recent_guide_video_count']==1
        assert s.metrics['sample_only'] and s.metrics['creator_count']==1
        assert 99<s.metrics['view_velocity_proxy']<=100
        assert p.search_calls==2 and p.video_calls==1
        again=await p.fetch(entity)
        assert again.cache_hit and p.search_calls==2 and again.captured_at==s.captured_at
        assert '"key"' not in json.dumps(p.raw) and 'key=' not in json.dumps(p.raw)

async def test_youtube_budget_keeps_partial(settings,entity):
    settings.youtube_search_budget=1
    async with httpx.AsyncClient(transport=httpx.MockTransport(youtube_handler)) as client:
        p=YouTubeProvider(settings,client);s=await p.fetch(entity)
        assert p.search_calls==1 and s.status==SourceState.PARTIAL and s.evidence

async def test_youtube_zero_budget_no_fake_zero(settings,entity):
    settings.youtube_search_budget=0
    async with httpx.AsyncClient(transport=httpx.MockTransport(youtube_handler)) as client:
        p=YouTubeProvider(settings,client);s=await p.fetch(entity)
        assert s.status==SourceState.BUDGET_EXHAUSTED and s.metrics=={} and p.calls==0

async def test_youtube_daily_budget_persists(settings,entity):
    settings.youtube_daily_search_budget=1
    async with httpx.AsyncClient(transport=httpx.MockTransport(youtube_handler)) as client:
        p=YouTubeProvider(settings,client);await p.fetch(entity)
        q=YouTubeProvider(settings,client)
        with pytest.raises(BudgetExceeded):q._reserve_search()

def test_http_error_does_not_leak_api_key():
    req=httpx.Request('GET','https://example.com/?key=very-secret')
    response=httpx.Response(403,request=req)
    with pytest.raises(httpx.HTTPStatusError) as ex:response.raise_for_status()
    assert safe_error(ex.value)=='HTTP 403'

RSS='''<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>post1</id><title>Example Game crafting calculator?</title><author><name>u/example</name></author><published>2026-09-01T00:00:00Z</published><link href="https://www.reddit.com/r/gaming/comments/post1/"/><content>How many materials?</content></entry></feed>'''

def test_reddit_rss_parse_no_comment_invention(entity):
    items=RedditProvider.parse_feed(RSS,entity)
    assert len(items)==1 and items[0].metrics['comment_count'] is None and items[0].author=='u/example'

def test_reddit_xml_external_entities_rejected(entity):
    with pytest.raises(ValueError):RedditProvider.parse_feed('<!DOCTYPE feed [<!ENTITY bad SYSTEM "file:///etc/passwd">]><feed/>',entity)

async def test_reddit_dedup_across_sources(settings,entity):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,text=RSS))) as client:
        p=RedditProvider(settings,client);s=await p.fetch(entity)
        assert s.metrics['question_count']==1 and len(s.evidence)==1 and s.metrics['comment_activity'] is None

async def test_reddit_403_no_bypass_or_retry(settings,entity):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(403,text='blocked'))) as client:
        p=RedditProvider(settings,client);s=await p.fetch(entity)
        assert p.calls==1 and s.status==SourceState.UNAVAILABLE and not s.evidence

async def test_official_trends_no_fake_endpoint(settings,entity):
    s=await OfficialTrendsProvider(settings).fetch(entity)
    assert s.status==SourceState.UNAVAILABLE and s.metrics=={}

async def test_steam_partial_hydration_preserves_details(settings):
    def handler(req):
        if req.url.path.endswith('/appdetails'):
            return httpx.Response(200,json={'123':{'success':True,'data':{'type':'game','name':'Example Game','genres':[{'description':'RPG'}],'recommendations':{'total':200}}}})
        return httpx.Response(503)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        p=SteamProvider(settings,client)
        row=SearchRow('123','Example Game',1,'top_sellers','https://store.steampowered.com/app/123/')
        g=await p._hydrate(row,{'123:top_sellers':row})
        assert g.genres==['RPG'] and g.reviews_total==200 and g.current_players is None
        assert any(e.source=='collector_error' for e in g.evidence)

async def test_steam_partial_hydration_preserves_players(settings):
    def handler(req):
        if req.url.path.endswith('/appdetails'):return httpx.Response(503)
        return httpx.Response(200,json={'response':{'result':1,'player_count':123}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        p=SteamProvider(settings,client);row=SearchRow('123','Example Game',1,'top_sellers','https://store.steampowered.com/app/123/')
        g=await p._hydrate(row,{'123:top_sellers':row})
        assert g.current_players==123 and g.name=='Example Game'

async def test_steam_broad_limit_not_old_30(settings):
    def handler(req):
        assert req.url.params['count']=='80'
        return httpx.Response(200,json={'results_html':''})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await SteamProvider(settings,client).fetch_listing('top_sellers',80)

def test_cache_failure_does_not_remove_old_payload(tmp_path):
    cache=JsonCache(tmp_path);cache.put('x','key',{'valid':True})
    assert cache.get('x','key',100)['payload']=={'valid':True}
    assert cache.get('x','key',-1) is None
    assert cache.path('x','key').exists()
