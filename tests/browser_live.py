"""Live-source smoke test and browser scenarios; serve the static build at :8001/nbatest/."""
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main():
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':1440,'height':1000})
        errors=[]
        base=os.environ.get('NBATEST_BASE_URL','http://127.0.0.1:8001/nbatest/')
        page.on('pageerror',lambda error:errors.append(str(error)))
        # Keep TLS verification enabled. Preserve the source's real CORS response
        # while using Python's installed proxy CA trust for network transport.
        def verified_source(route):
            request=urllib.request.Request(route.request.url,headers={'Origin':base.split('/nbatest/')[0]})
            with urllib.request.urlopen(request,timeout=30) as response:
                headers={'content-type':response.headers.get('Content-Type','application/json')}
                cors=response.headers.get('Access-Control-Allow-Origin')
                if cors:headers['access-control-allow-origin']=cors
                route.fulfill(status=response.status,body=response.read(),headers=headers)
        page.route('https://site.api.espn.com/**',verified_source)
        page.goto(base+'live.html')
        expect(page.locator('#live-game option')).not_to_have_text(['Loading today’s games…'],timeout=60000)
        expect(page.locator('#live-status')).not_to_have_text('Connecting to the public feed…',timeout=60000)
        expect(page.locator('#live-error')).to_be_hidden()
        print('Current public scoreboard/summary fetched through verified TLS with actual CORS headers.',flush=True)
        page.locator('#live-mode').select_option('replay')
        expect(page.locator('#live-status')).to_contain_text('HISTORICAL REPLAY')
        expect(page.locator('#live-summary .stat')).to_have_count(4)
        expect(page.locator('#live-evaluation')).to_contain_text('59 historical games')
        page.locator('#market-line').fill('50.5')
        page.locator('#market-over').fill('-110')
        page.locator('#market-under').fill('-110')
        page.locator('#market-confirm').click()
        expect(page.locator('#market-result')).to_contain_text('No signal')
        expect(page.locator('#market-result')).to_contain_text('Historical replay')
        page.locator('#market-line').fill('51.5')
        expect(page.locator('#market-result')).to_contain_text('Confirm the edited line')
        page.locator('#replay-time').fill('1080')
        page.locator('#replay-time').dispatch_event('input')
        expect(page.locator('#live-scope')).to_have_value('q2')
        expect(page.locator('#market-line')).to_have_value('')
        page.locator('#live-scope').select_option('game')
        expect(page.locator('#market-rules')).to_contain_text('including overtime')
        page.screenshot(path='reports/live-desktop.png',full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        page.screenshot(path='reports/live-mobile.png',full_page=True)
        # Simulated in-progress feed made from a real past game's first six minutes.
        # This fixture is only a UI test and is never published or presented as live evidence.
        active=json.loads(Path('data/pace_replay.json').read_text())['summary']
        def elapsed(play):
            value=play['clock']['displayValue']
            remaining=sum(float(v)*factor for v,factor in zip(value.split(':'),(60,1))) if ':' in value else float(value)
            return (play['period']['number']-1)*720+720-remaining
        active['plays']=[p for p in active['plays'] if elapsed(p)<=360]
        active['header']['id']=page.locator('#live-game').input_value()
        comp=active['header']['competitions'][0]
        comp['status']={'period':1,'displayClock':'6:00','type':{'state':'in','detail':'6:00 - 1st Quarter'}}
        comp['date']=datetime.now(timezone.utc).isoformat()
        for team in comp['competitors']:team['score']=str(active['plays'][-1][team['homeAway']+'Score'])
        for play in active['plays']:play['wallclock']=datetime.now(timezone.utc).isoformat()
        page.unroute('https://site.api.espn.com/**')
        page.route('https://site.api.espn.com/**',lambda route:route.fulfill(json=active if '/summary?' in route.request.url else {'events':[]},headers={'access-control-allow-origin':'*'}))
        page.locator('#live-mode').select_option('live')
        expect(page.locator('#live-status')).to_contain_text('6:00 - 1st Quarter')
        expect(page.locator('#live-summary .stat')).to_have_count(4)
        page.locator('#market-line').fill('50.5');page.locator('#market-over').fill('-110');page.locator('#market-under').fill('-110')
        page.locator('#market-confirm').click()
        expect(page.locator('#market-result')).to_contain_text('No signal')
        expect(page.locator('#market-result')).to_contain_text('cannot be reconciled')
        # A failed source must clear an earlier replay/forecast rather than label it live.
        page.unroute('https://site.api.espn.com/**')
        page.route('https://site.api.espn.com/**',lambda route:route.fulfill(status=503,body='unavailable',headers={'access-control-allow-origin':'*'}))
        page.locator('#live-refresh').click()
        expect(page.locator('#live-error')).to_be_visible()
        expect(page.locator('#live-summary .stat')).to_have_count(0)
        expect(page.locator('#live-status')).to_contain_text('Comparisons are paused')
        assert not errors,errors
        browser.close()
    print('Live UI passed: current-source access, replay, quarter changes, market entry/reset, full-game rules, mobile, and source-failure handling; no JS errors.')


if __name__=='__main__':
    main()
