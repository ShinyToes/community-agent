"""Exercise local registration/login with a fictional account, then disable it."""
from pathlib import Path
import json
import secrets
import sys

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    username = 'ui_' + secrets.token_hex(6)
    password = secrets.token_urlsafe(24)
    output = ROOT / 'instance' / 'community'
    output.mkdir(parents=True, exist_ok=True)
    errors = []
    registered = False
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='msedge', headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto('http://127.0.0.1:5001/')
            expect(page.get_by_role('heading', level=1)).to_contain_text('每一次探索')
            page.screenshot(path=str(output / 'home-desktop.png'), full_page=True)
            page.get_by_role('link', name='创建你的账号').click()
            page.get_by_label('用户名', exact=True).fill(username)
            page.get_by_label('密码', exact=True).fill(password)
            page.screenshot(path=str(output / 'register-desktop.png'), full_page=True)
            page.get_by_role('button', name='创建账号', exact=True).click()
            page.wait_for_url('http://127.0.0.1:5001/')
            registered = True
            expect(page.locator('.account')).to_have_text(username)
            page.get_by_role('button', name='退出', exact=True).click()
            page.goto('http://127.0.0.1:5001/auth/register')
            page.get_by_label('用户名', exact=True).fill(username)
            page.get_by_label('密码', exact=True).fill(password)
            page.evaluate('window.registrationPageMarker = true')
            page.get_by_role('button', name='创建账号', exact=True).click()
            expect(page.locator('#register-error')).to_contain_text('该用户名已被使用')
            assert page.url.endswith('/auth/register')
            assert page.evaluate('window.registrationPageMarker === true')
            expect(page.get_by_label('用户名', exact=True)).to_have_value(username)
            expect(page.get_by_label('密码', exact=True)).to_have_value(password)
            expect(page.get_by_role('button', name='创建账号', exact=True)).to_be_enabled()
            page.screenshot(path=str(output / 'register-duplicate.png'), full_page=True)
            page.get_by_label('用户名', exact=True).fill(username + '_new')
            expect(page.locator('#register-error')).to_be_hidden()
            page.get_by_role('link', name='登录', exact=True).click()
            page.get_by_label('用户名', exact=True).fill(username)
            page.get_by_label('密码', exact=True).fill(password)
            page.get_by_role('button', name='登录', exact=True).click()
            page.wait_for_url('http://127.0.0.1:5001/')
            response = page.goto('http://127.0.0.1:5001/admin')
            assert response.status == 403
            expect(page.get_by_role('alert')).to_contain_text('没有权限')
            page.set_viewport_size({'width': 390, 'height': 844})
            page.goto('http://127.0.0.1:5001/')
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            page.screenshot(path=str(output / 'home-mobile.png'), full_page=True)
            browser.close()
        assert not errors, errors
    finally:
        if registered:
            from community import create_app
            result = create_app().test_cli_runner().invoke(args=[
                'disable-user', '--username', username, '--reason', '自动化浏览器验收账号已停用'])
            assert result.exit_code == 0, result.output
    print(json.dumps({'registration': True, 'login_logout': True, 'admin_denied': True,
                      'duplicate_registration_inline': True,
                      'mobile_no_overflow': True, 'javascript_errors': errors,
                      'test_account_disabled': registered}))


if __name__ == '__main__':
    main()
