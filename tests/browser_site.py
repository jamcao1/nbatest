"""Optional static-site check; serve the build at /nbatest/ on port 8001."""
import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/chromium', headless=True, args=['--no-sandbox'])
        page = browser.new_page(viewport={'width':1440,'height':1100})
        errors, requests = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda request: requests.append((request.method,request.url)))
        base = os.environ.get('NBATEST_BASE_URL','http://127.0.0.1:8001/nbatest/')
        report = page.request.get(base+'weekly.json').json()
        page.goto(base)
        expect(page.locator('.game-card')).to_have_count(len(report['games']))
        expect(page.locator('.toolbar')).to_be_hidden()
        expect(page.locator('.data-actions')).to_be_hidden()
        assert 'PUBLISHED WEEKLY FORECAST' in page.locator('#notice').inner_text()
        assert 'Updated' in page.locator('#published-at').inner_text()
        if page.locator('body').get_attribute('data-rosters') == 'true':
            roster = page.request.get(base+'rosters.json').json()
            expect(page.locator('#roster-controls')).to_be_visible()
            expect(page.locator('#roster-team option')).to_have_count(30)
            page.locator('#roster-team').select_option('BOS')
            expect(page.locator('#roster-team-detail tbody tr')).to_have_count(len(roster['teams']['BOS']['players']))
            expect(page.locator('#roster-status')).to_contain_text('not applied')
            expect(page.locator('#roster-evaluation')).to_contain_text('277 held-out games')
            expect(page.locator('#roster-evaluation')).to_contain_text('0.1877')
        page.locator('.game-card').first.click()
        expect(page.locator('dialog[open] .histogram rect')).to_have_count(6)
        assert 'No market lines were supplied' in page.locator('#detail-content').inner_text()
        page.keyboard.press('Escape')
        team = report['games'][0]['home']
        page.locator('#search').fill(team)
        assert 0 < page.locator('.game-card').count() <= len(report['games'])
        page.locator('#search').fill('')
        with page.expect_download() as downloaded:
            page.locator('#export').click()
        saved = json.loads(Path(downloaded.value.path()).read_text())
        assert saved['games'] == report['games']
        page.locator('#backtest').click()
        expect(page.locator('.backtest-grid')).to_be_visible()
        page.evaluate('window.scrollTo(0,0)')
        page.screenshot(path='reports/pages-desktop.png')
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        page.screenshot(path='reports/pages-mobile.png')

        if page.locator('body').get_attribute('data-rosters') == 'true':
            page.route('**/rosters.json', lambda route: route.fulfill(json={'week_start': report['week_start'], 'status':'unavailable'}))
            page.reload()
            expect(page.locator('#roster-status')).to_contain_text('unavailable')
            expect(page.locator('#roster-controls')).to_be_hidden()
            expect(page.locator('.game-card')).to_have_count(len(report['games']))
            page.unroute('**/rosters.json')

        # Past reports and failures must be explicit, rather than silently claiming current data.
        old = {**report,'week_start':'2015-04-06'}
        page.route('**/weekly.json', lambda route: route.fulfill(json=old))
        page.reload()
        expect(page.locator('#notice')).to_contain_text('PAST FORECAST')
        page.unroute('**/weekly.json')
        page.route('**/weekly.json', lambda route: route.fulfill(status=404,body='Not found'))
        page.reload()
        expect(page.locator('#error')).to_be_visible()
        expect(page.locator('.game-card')).to_have_count(0)
        assert not errors, errors
        assert all(method == 'GET' and '/api/' not in url for method,url in requests), requests
        browser.close()
    print('Static site verified at /nbatest/: rendering, search, details, exports, backtest, mobile, stale data, missing report; no API calls or JavaScript errors.')


if __name__ == '__main__':
    main()
