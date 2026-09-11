#!/usr/bin/env python3
"""Real Chromium DOM integration against a local ASGI app; never a live upstream test.
Usage: python scripts/browser_smoke.py --url http://127.0.0.1:3000 --output evidence/browser
Requires the optional Playwright Python package and Chromium executable.
Uses an isolated server/data directory: demo and manual annotations are written.
"""
import argparse,json
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url',default='http://127.0.0.1:3000')
    p.add_argument('--output',type=Path,default=Path('evidence/browser'))
    p.add_argument('--chromium',default='/usr/bin/chromium')
    p.add_argument('--asgi-fixture',action='store_true',help='Offline in-process ASGI transport; not direct browser HTTP verification')
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    checks=[];errors=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=args.chromium,headless=True,args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':1440,'height':1000})
        page.on('pageerror',lambda e:errors.append(str(e)))
        client=None
        if args.asgi_fixture:
            import tempfile
            from urllib.parse import urlsplit
            from fastapi.testclient import TestClient
            from game_keyword_radar.config import Settings
            from game_keyword_radar.web.app import create_app
            temporary=tempfile.TemporaryDirectory(prefix='gkr-browser-fixture-')
            client=TestClient(create_app(Settings(project_root=Path(temporary.name))))
            # Offline DOM integration only. Do not navigate or change browser network policy.
            # The real application JS calls an in-process ASGI transport via a test binding.
            def transport(payload):
                address=urlsplit(payload['url'])
                if address.scheme or address.netloc or not address.path.startswith('/'):
                    raise ValueError('Offline fixture accepts only local application paths')
                response=client.request(payload.get('method','GET'),
                    address.path+('?' + address.query if address.query else ''),
                    content=payload.get('body'),headers=payload.get('headers') or {})
                return {'status':response.status_code,'body':response.text,
                        'headers':dict(response.headers)}
            page.expose_function('__fixtureFetch',transport)
            import re
            html=client.get('/').text
            html=re.sub(r'<script\b[^>]*src=[^>]*></script>', '', html, flags=re.I)
            html=re.sub(r'<link\b[^>]*>', '', html, flags=re.I)
            page.set_content(html,wait_until='domcontentloaded')
            webroot=Path(__file__).resolve().parents[1]/'src/game_keyword_radar/web'
            page.add_style_tag(content=(webroot/'static/styles.css').read_text())
            page.evaluate("""() => {
                window.fetch = async (url, options={}) => {
                    const r = await window.__fixtureFetch({url: String(url),
                      method: options.method || 'GET', body: options.body || null,
                      headers: options.headers || {}});
                    return new Response(r.body,{status:r.status,headers:r.headers});
                };
            }""")
            page.add_script_tag(content=(webroot/'static/app.js').read_text())
        else:
            page.goto(args.url,wait_until='networkidle')
        page.get_by_role('button',name='体验示例',exact=True).click()
        page.locator('.lane-section').first.wait_for()
        assert page.locator('.lane-section').count()==4
        assert page.locator('#games').get_by_text('Evergreen Arena',exact=True).count()==0
        assert page.locator('#games').get_by_text('Frontier Forge',exact=True).count()==1
        checks.append('four lanes; mature-only game excluded from default today')
        page.screenshot(path=str(args.output/'overview-desktop.png'),full_page=True)
        page.get_by_role('button',name='成熟 / 观察',exact=True).click()
        assert page.locator('#games').get_by_text('Evergreen Arena',exact=True).count()==1
        page.locator('#games [data-game="evergreen-arena"]').click()
        page.get_by_role('heading',name='Evergreen Arena',exact=True).wait_for()
        assert page.locator('#game-detail').get_by_text('仅观察',exact=True).count()>=1
        checks.append('mature game retained in inspectable monitor-only view')
        page.screenshot(path=str(args.output/'mature-observation-desktop.png'),full_page=True)
        page.locator('#back-overview').click()
        page.get_by_role('button',name='今日分组',exact=True).click()
        page.locator('#games [data-game="signal-tactics"]').click()
        assert page.locator('#game-detail').get_by_text('有可比增长',exact=True).count()==1
        assert '多点窗口 / 3 对' in page.locator('#game-detail').inner_text()
        checks.append('time-window growth and breadth shown separately from legacy score')
        page.screenshot(path=str(args.output/'growth-detail-desktop.png'),full_page=True)
        page.locator('#game-detail [data-validate]').first.click()
        page.locator('#validation-dialog[open]').wait_for()
        page.select_option('#validation-form [name=decision]','build')
        page.click('#save-validation')
        page.locator('#validation-error:not([hidden])').wait_for()
        checks.append('Build without evidence blocked by actual backend gate')
        page.click('#cancel-dialog')
        page.get_by_role('button',name='观察与监测',exact=False).click()
        page.locator('#monitor-status').get_by_text('定时监测未开启',exact=False).wait_for()
        checks.append('monitoring disabled by default and local scope explained')
        page.locator('#seed-form [name=canonical_name]').fill('Browser Fixture Seed')
        page.select_option('#seed-form [name=platform]','steam')
        page.locator('#seed-form [name=platform_id]').fill('7654321')
        page.locator('#seed-form [name=evidence_url]').fill('https://example.invalid/synthetic-source')
        page.locator('#seed-form [name=reason]').fill('Synthetic browser smoke test; do not use as real research.')
        page.locator('#seed-form button[type=submit]').click()
        page.locator('#toast').get_by_text('人工种子已保存',exact=False).wait_for()
        checks.append('manual seed saved without fetching arbitrary evidence URL')
        page.locator('summary').filter(has_text='本次服务的筛选').click()
        page.locator('#policy-json').wait_for(state='visible')
        policy=json.loads(page.locator('#policy-json').input_value())
        assert policy['selection']['new_release_weight']==4
        page.locator('#policy-json').fill(json.dumps({'selection':{'new_release_days':70}}))
        page.locator('#policy-form button').click()
        page.locator('#toast').get_by_text('已应用到当前服务会话',exact=False).wait_for()
        assert json.loads(page.locator('#policy-json').input_value())['selection']['new_release_days']==70
        checks.append('typed runtime policy editor round trip')
        page.get_by_role('button',name='历史变化',exact=False).click()
        page.locator('#history-list [data-load-snapshot]').first.click()
        page.locator('#games').wait_for()
        checks.append('historical report remains navigable after policy changes')
        for width,height,name in [(390,844,'mobile'),(768,1024,'tablet')]:
            page.set_viewport_size({'width':width,'height':height})
            page.get_by_role('button',name='今日分组',exact=True).click()
            page.wait_for_timeout(100)
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')
            page.screenshot(path=str(args.output/f'overview-{name}.png'),full_page=True)
            page.locator('#games [data-game="frontier-forge"]').click()
            page.wait_for_timeout(100)
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')
            page.screenshot(path=str(args.output/f'detail-{name}.png'),full_page=True)
            page.locator('#back-overview').click()
            checks.append(f'{name}: overview and detail have no horizontal overflow')
        assert not errors,errors
        checks.append('no JavaScript page errors')
        browser.close()
        if client:
            client.close()
            temporary.cleanup()
    result={'checks':checks,'count':len(checks),'page_errors':errors,'upstream_network_verified':False,
        'browser_transport':'Chromium DOM/JS + offline in-process ASGI binding fixture (no browser navigation/network)' if args.asgi_fixture else 'actual Chromium HTTP to loopback ASGI server',
        'fixture_notice':'All browser observations and actions use synthetic data'}
    (args.output/'browser-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
