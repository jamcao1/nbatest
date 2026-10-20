"""Functional checks for the player atlas; use NBATEST_BASE_URL for a static build."""
import json
import os
from pathlib import Path
from playwright.sync_api import expect, sync_playwright


def main():
    base = os.environ.get('NBATEST_BASE_URL', 'http://127.0.0.1:8002/nbatest/')
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/chromium', headless=True, args=['--no-sandbox'])
        page = browser.new_page(viewport={'width': 1440, 'height': 1100})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(base+'players.html')
        expect(page.locator('.player-card')).to_have_count(2, timeout=30000)
        expect(page.locator('#players-error')).to_be_hidden()
        expect(page.locator('#players-notice')).to_contain_text('Regulation')
        expect(page.locator('#venue-context')).to_contain_text('Little Caesars Arena')
        first = page.locator('.player-card').first
        expect(first.locator('.player-heading p')).to_contain_text('Projected scoring leader')
        expect(first.locator('.zone-marker')).to_have_count(5)
        points = float(first.locator('.scoring-number strong').inner_text())
        assert points > 0
        table_points = sum(float(x) for x in first.locator('.shot-table tbody tr td:last-child').all_text_contents())
        assert abs(points-table_points) <= .5  # Displayed values round to tenths.
        first.locator('.zone-marker').first.click()
        expect(first.locator('.shot-table tr.selected')).to_have_count(1)
        slider = first.locator('input[type=range]')
        slider.fill('16')
        slider.dispatch_event('input')
        expect(first.locator('output')).to_contain_text('edited scenario')
        assert float(first.locator('.scoring-number strong').inner_text()) < points
        first.get_by_role('button', name='Reset', exact=True).click()
        assert float(first.locator('.scoring-number strong').inner_text()) == points
        first.get_by_role('button', name='Recorded shots', exact=True).click()
        assert first.locator('.shot-made').count() > 0
        assert first.locator('.shot-miss').count() > 0
        first.get_by_role('button', name='Misses', exact=True).click()
        expect(first.locator('.shot-made')).to_have_count(0)
        first.get_by_role('button', name='Makes', exact=True).click()
        expect(first.locator('.shot-miss')).to_have_count(0)
        first.get_by_role('button', name='Projected zones', exact=True).click()
        assert float(first.locator('.scoring-number strong').inner_text()) == points
        expect(page.locator('#player-market')).to_contain_text('opening')
        expect(page.locator('#player-evaluation')).to_contain_text('80 pregame-selected scoring leaders')
        page.screenshot(path='reports/players-desktop.png', full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path='reports/players-mobile.png', full_page=True)
        # Unrated players must not inherit the previous leader's numbers or dots.
        unrated = first.locator('select option').filter(has_text='Not rated')
        if unrated.count():
            first.locator('select').select_option(unrated.first.get_attribute('value'))
            expect(first.locator('.no-profile')).to_contain_text('Insufficient history')
            expect(first.locator('.scoring-number')).to_have_count(0)
            expect(first.locator('.court')).to_have_count(0)
        # Changing matchups switches both teams and their venue.
        second_id = page.locator('#player-game option').nth(1).get_attribute('value')
        page.locator('#player-game').select_option(second_id)
        expect(page.locator('.player-card')).to_have_count(2)
        expect(page.locator('#venue-context')).not_to_contain_text('Little Caesars Arena')
        # A failed refresh clears old estimates; retry restores the report.
        page.route('**/players.json', lambda route: route.fulfill(status=503, body='unavailable'))
        page.locator('#players-retry').click()
        expect(page.locator('#players-error')).to_be_visible()
        expect(page.locator('.player-card')).to_have_count(0)
        page.unroute('**/players.json')
        page.locator('#players-retry').click()
        expect(page.locator('.player-card')).to_have_count(2)
        expect(page.locator('#players-error')).to_be_hidden()
        # Explicit unavailable builds must never resurrect prior numbers.
        page.route('**/players.json', lambda route: route.fulfill(json={'status': 'unavailable', 'reason': 'Roster source unavailable', 'games': []}))
        page.locator('#players-retry').click()
        expect(page.locator('#players-error')).to_contain_text('Roster source unavailable')
        expect(page.locator('.player-card')).to_have_count(0)
        assert not errors, errors
        browser.close()
    print('Player atlas passed: leaders, venue, zone sums, minutes/reset, recorded makes/misses, unrated profiles, matchup switch, mobile, failed refresh and retry; no JS errors.')


if __name__ == '__main__':
    main()
