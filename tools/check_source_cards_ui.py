"""Read-only check of source cards on an existing completed conversation."""
from pathlib import Path
import json
import httpx
from playwright.sync_api import sync_playwright


def main():
    with httpx.Client(base_url='http://127.0.0.1:8080', timeout=20) as client:
        chosen = None
        for session in client.get('/api/research/sessions').json():
            runs = client.get('/api/research/sessions/' + session['id']).json()['runs']
            chosen = next((r for r in reversed(runs) if r.get('source_cards')), None)
            if chosen:
                break
        assert chosen, 'No completed answer with valid sources'
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 960})
        page.add_init_script("localStorage.setItem('mediacrawler_env_checked','true');localStorage.setItem('mediacrawler_license_accepted','true')")
        page.goto('http://127.0.0.1:8080/#assistant?session=' + chosen['session_id'])
        page.locator('[data-source-kind]').first.wait_for()
        assert not page.get_by_role('link', name='[原文 1.1]', exact=True).count()
        page.locator('[data-source-kind]').last.scroll_into_view_if_needed()
        path = Path(__file__).resolve().parents[1] / '.runtime/source-cards.png'
        page.screenshot(path=str(path), full_page=True)
        print(json.dumps({'post_cards': page.locator('[data-source-kind="post"]').count(),
                          'comment_cards': page.locator('[data-source-kind="comment"]').count(),
                          'site_links': page.get_by_role('link', name='打开网站原帖 ↗', exact=True).count()}))
        browser.close()


if __name__ == '__main__':
    main()
