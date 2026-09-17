"""Optional browser check against the local demo server, using only fictional data."""
from pathlib import Path
import json
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


def main():
    credentials = dict(line.split(': ', 1) for line in (ROOT / 'instance/demo-login.txt').read_text().splitlines())
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1100})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto('http://127.0.0.1:5000/auth/login')
        page.locator('[name=username]').fill('demo_admin')
        page.locator('[name=password]').fill(credentials['demo_admin'])
        page.locator('button[type=submit]').click()
        page.wait_for_url('http://127.0.0.1:5000/')
        page.goto('http://127.0.0.1:5000/agent')
        page.locator('summary').filter(has_text='直接查询').click()
        page.locator('#queryKind').select_option('courses')
        page.locator('#directQuery').click()
        expect(page.locator('#messages')).to_contain_text('演示数据库课程')
        page.locator('[name=kind]').select_option('courses')
        page.locator('[name=file]').set_input_files(ROOT / 'examples/imports/courses.csv')
        page.locator('#uploadForm button[type=submit]').click()
        expect(page.locator('#batchDetail')).to_contain_text('待确认', timeout=30000)
        page.locator('#batchDetail details summary').click()
        expect(page.locator('#batchDetail')).to_contain_text('示例软件工程')
        page.screenshot(path=str(ROOT / 'instance/agent-ui.png'), full_page=True)
        page.get_by_role('button', name='取消批次', exact=True).click()
        expect(page.locator('#batchDetail')).to_contain_text('已取消')
        # Fresh context verifies student UI does not show administrator controls.
        student = browser.new_page()
        student.goto('http://127.0.0.1:5000/auth/login')
        student.locator('[name=username]').fill('demo_student')
        student.locator('[name=password]').fill(credentials['demo_student'])
        student.locator('button[type=submit]').click()
        student.wait_for_url('http://127.0.0.1:5000/')
        student.goto('http://127.0.0.1:5000/agent')
        expect(student.locator('#uploadForm')).to_have_count(0)
        expect(student.locator('#agentRoot')).to_contain_text('本人数据')
        browser.close()
        assert not errors, errors
        print(json.dumps({'admin_query': True, 'upload_worker_preview_cancel': True,
                          'student_scope_ui': True, 'javascript_errors': errors}))


if __name__ == '__main__':
    main()
