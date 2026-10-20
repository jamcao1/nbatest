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
        # Install before navigation so the application's own intervals are controlled.
        page.clock.install(time=datetime.now(timezone.utc))
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
        expect(page.get_by_role('heading',name='Are Miami and Denver always fast?')).to_have_count(0)
        expect(page.locator('#live-history')).to_contain_text('Team history through')
        if 'Waiting for tipoff' in page.locator('#live-diagnosis').inner_text():
            expect(page.locator('#market-confirm')).to_be_disabled()
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
        page.locator('#replay-time').fill('720')
        page.locator('#replay-time').dispatch_event('input')
        expect(page.locator('#live-diagnosis')).to_contain_text('This quarter has ended')
        expect(page.locator('#market-confirm')).to_be_disabled()
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
        failures={'schedule':False,'summary':False}
        requests={'summary':0}
        def simulated_source(route):
            summary='/summary?' in route.request.url
            if summary:requests['summary']+=1
            if failures['summary' if summary else 'schedule']:
                route.fulfill(status=503,body='unavailable',headers={'access-control-allow-origin':'*'})
            else:
                event={'id':active['header']['id'],'shortName':'DEN @ SA','season':{'type':2},
                       'status':{'type':{'state':'in','description':'In progress'}}}
                route.fulfill(json=active if summary else {'events':[event]},headers={'access-control-allow-origin':'*'})
        page.route('https://site.api.espn.com/**',simulated_source)
        page.locator('#live-mode').select_option('live')
        expect(page.locator('#live-status')).to_contain_text('6:00 - 1st Quarter')
        expect(page.locator('#live-summary .stat')).to_have_count(4)
        page.locator('#live-scope').select_option('q1')
        page.locator('#market-line').fill('50.5');page.locator('#market-over').fill('-110');page.locator('#market-under').fill('-110')
        page.locator('#market-confirm').click()
        expect(page.locator('#market-result')).to_contain_text('No signal')
        expect(page.locator('#market-result')).to_contain_text('cannot be reconciled')
        # The same six-minute fixture with reconciled box-score possession inputs.
        # Counts are from the archived game at 6:00 Q1, not its final box score.
        for team in active['boxscore']['teams']:
            values={'fieldGoalsMade-fieldGoalsAttempted':'6-12' if str(team['team']['id'])=='24' else '7-11',
                    'freeThrowsMade-freeThrowsAttempted':'4-4','offensiveRebounds':'1',
                    'totalTurnovers':'1' if str(team['team']['id'])=='24' else '2'}
            team['statistics']=[{'name':k,'displayValue':v} for k,v in values.items()]
        page.locator('#live-refresh').click()
        expect(page.locator('#market-result')).not_to_contain_text('cannot be reconciled')
        expect(page.locator('#live-summary .stat')).to_have_count(4)
        # Exercise the actual timer; summary updates must survive a failed game-list refresh.
        failures['schedule']=True
        comp['status']['type']['detail']='6:00 - 1st Quarter · updated'
        page.clock.fast_forward(61000)
        expect(page.locator('#live-status')).to_contain_text('updated')
        expect(page.locator('#live-notice')).to_contain_text('Continuing to fetch the selected game')
        expect(page.locator('#live-error')).to_be_hidden()
        expect(page.locator('#market-result')).to_contain_text('over 60 seconds old')
        failures['schedule']=False
        # These are source-state scenarios, not claims of observing tonight's game live.
        transitions=[
            (1,'12:00','In progress','Waiting for the first recorded possession','q1'),
            (1,'0.0','End of 1st Quarter','Period break','q1'),
            (2,'12:00','Start of 2nd Quarter','Period break','q2'),
            (2,'0.0','Halftime','Period break','q2'),
            (5,'5:00','Overtime','Overtime','q4'),
        ]
        for period,display,detail,message,scope in transitions:
            comp['status']={'period':period,'displayClock':display,'type':{'state':'in','detail':detail}}
            page.locator('#live-refresh').click()
            expect(page.locator('#live-diagnosis')).to_contain_text(message)
            expect(page.locator('#live-error')).to_be_hidden()
            expect(page.locator('#market-confirm')).to_be_disabled()
            expect(page.locator('#live-scope')).to_have_value(scope)
        comp['status']={'period':1,'displayClock':'6:00','type':{'state':'in','detail':'6:00 - 1st Quarter'}}
        page.locator('#live-refresh').click()
        expect(page.locator('#live-summary .stat')).to_have_count(4)
        # A failed source must clear an earlier replay/forecast rather than label it live.
        failures['summary']=True
        page.locator('#live-refresh').click()
        expect(page.locator('#live-error')).to_be_visible()
        expect(page.locator('#live-summary .stat')).to_have_count(0)
        expect(page.locator('#live-status')).to_contain_text('Comparisons are paused')
        page.locator('#live-scope').select_option('game')
        expect(page.locator('#live-summary .stat')).to_have_count(0)
        expect(page.locator('#market-confirm')).to_be_disabled()
        # Retry must also recover a failed initial prior-data load without reloading the tab.
        failures['summary']=False
        page.route('**/pace-priors.json',lambda route:route.fulfill(status=503,body='unavailable'))
        page.reload()
        expect(page.locator('#live-error')).to_be_visible()
        expect(page.locator('#market-confirm')).to_be_disabled()
        page.unroute('**/pace-priors.json')
        page.locator('#live-refresh').click()
        expect(page.locator('#live-summary .stat')).to_have_count(4)
        expect(page.locator('#live-error')).to_be_hidden()
        # Hidden tabs must not keep polling.
        before=requests['summary']
        page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,get:()=>true})")
        page.clock.fast_forward(61000)
        assert requests['summary']==before
        page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,get:()=>false});document.dispatchEvent(new Event('visibilitychange'))")
        expect(page.locator('#live-refresh')).to_be_enabled()
        assert requests['summary']>before
        assert not errors,errors
        browser.close()
    print('Live UI passed: current source, replay, mobile, market freshness, tipoff, quarter breaks, halftime, overtime, timed refresh, schedule failure, failed-feed isolation, retry recovery, and hidden-tab polling; no JS errors.')


if __name__=='__main__':
    main()
