"""Optional browser integration check. Requires Playwright and local Chromium.

Start `python -m nbasim.app` first. These tools are already installed in the
prepared cloud machine; they are not required by the application itself.
"""
import json
import re
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

BASE = 'http://127.0.0.1:8000'
OUTPUT = Path(__file__).resolve().parent.parent / 'reports'


def main():
    OUTPUT.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/chromium', headless=True, args=['--no-sandbox'])
        page = browser.new_page(viewport={'width':1440,'height':1100})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(BASE)
        page.wait_for_selector('.game-card')
        assert page.locator('.game-card').count() == 49
        page.locator('.game-card').first.click()
        assert page.locator('dialog[open] .histogram rect').count() == 6
        page.keyboard.press('Escape')
        page.locator('#search').fill('BOS')
        assert page.locator('.game-card').count() == 3
        page.locator('#search').fill('')

        dataset = page.request.get(BASE+'/api/demo').json()
        page.locator('#dataset-file').set_input_files({'name':'dataset.json','mimeType':'application/json','buffer':json.dumps(dataset).encode()})
        expect(page.locator('#notice')).to_have_text(re.compile(r'^IMPORTED'))
        expect(page.locator('#run')).to_be_enabled()
        page.locator('#seed').fill('24')
        with page.expect_response('**/api/simulate') as response:
            page.locator('#run').click()
        assert response.value.status == 200
        expect(page.locator('#run')).to_be_enabled()

        # Explicitly synthetic odds used only to validate the import interaction.
        gid = dataset['schedule'][0]['id']
        odds = f'game_id,observed_at,home_spread,total,home_moneyline,away_moneyline\n{gid},2015-04-05T12:00:00-04:00,-3.5,205,-150,130\n'
        page.locator('#odds-file').set_input_files({'name':'synthetic-test-odds.csv','mimeType':'text/csv','buffer':odds.encode()})
        expect(page.locator('#clear-odds')).to_be_visible()
        page.locator('.game-card').first.click()
        assert 'Home / away cover' in page.locator('#detail-content').inner_text()
        assert 'no-vig' in page.locator('#detail-content').inner_text()
        page.keyboard.press('Escape')
        with page.expect_download() as download:
            page.locator('#export').click()
        exported = json.loads(Path(download.value.path()).read_text())
        assert len(exported['games']) == 49
        assert exported['seed'] == 24
        assert 'market' in exported['games'][0]

        # Fail the live request explicitly; the UI must retain and label old results.
        page.route('**/api/live?*', lambda route: route.fulfill(status=400, content_type='application/json', body=json.dumps({'error':'Live feed unavailable (test).'})))
        page.locator('#live').click()
        page.wait_for_selector('#error:not([hidden])')
        assert 'Results below remain from imported' in page.locator('#notice').inner_text()
        assert page.locator('.game-card').count() == 49
        page.unroute('**/api/live?*')
        page.locator('#demo').click()
        expect(page.locator('#notice')).to_have_text(re.compile(r'^HISTORICAL'))
        expect(page.locator('#run')).to_be_enabled()
        page.screenshot(path=str(OUTPUT/'desktop.png'))
        page.set_viewport_size({'width':390,'height':844})
        page.evaluate('window.scrollTo(0,0)')
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        page.screenshot(path=str(OUTPUT/'mobile.png'))
        page.locator('#backtest').click()
        page.wait_for_selector('.backtest-grid')
        assert '70.2%' in page.locator('.backtest-grid').inner_text()
        assert not errors, errors
        browser.close()
    print('Browser checks passed: rendering, details, search, JSON import/rerun, odds import, export, failure state, mobile layout, backtest; no JavaScript errors.')


if __name__ == '__main__':
    main()
