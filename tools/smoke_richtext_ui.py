"""Browser acceptance for the isolated rich-text trial on port 5002."""
from pathlib import Path
import secrets
import sys
import json

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
BASE = 'http://127.0.0.1:5002'
sys.path.insert(0, str(ROOT))


def main():
    username = 'rich_' + secrets.token_hex(5)
    password = secrets.token_urlsafe(20)
    errors = []
    folder = ROOT / 'instance/community'
    folder.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('dialog', lambda dialog: dialog.accept())
        page.goto(BASE + '/auth/register')
        page.get_by_label('用户名', exact=True).fill(username)
        page.get_by_label('密码', exact=True).fill(password)
        page.get_by_role('button', name='创建账号', exact=True).click()
        page.wait_for_url(BASE + '/')
        page.goto(BASE + '/posts/new')
        rich = page.get_by_role('textbox', name='富文本正文', exact=True)
        expect(rich).to_be_visible()
        page.get_by_label('标题', exact=True).fill('富文本编辑体验')
        rich.fill('直接选中文字，就能设置排版')
        rich.press('Control+a')
        page.get_by_role('button', name='加粗', exact=True).click()
        expect(rich.locator('strong')).to_have_text('直接选中文字，就能设置排版')
        page.get_by_role('button', name='标题', exact=True).click()
        expect(rich.locator('h2')).to_contain_text('直接选中文字')
        page.get_by_role('button', name='Markdown', exact=True).click()
        source = page.get_by_label('正文 · Markdown', exact=True)
        expect(source).to_be_visible()
        assert '**' in source.input_value() and '##' in source.input_value()
        content = '## 直接编辑，直接看到效果\n\n这是 **加粗** 和 *斜体*。\n\n- 记录想法\n- 分享学习笔记\n\n> 在同一块区域里完成编辑与排版。\n\n```python\nprint("Hello")\n```\n\n| 功能 | 体验 |\n| --- | --- |\n| 加粗 | 点一下按钮 |'
        source.fill(content)
        page.get_by_role('button', name='富文本（试用）', exact=True).click()
        expect(rich.locator('table')).to_be_visible()
        assert page.locator('#markdown').input_value() == content
        page.screenshot(path=str(folder / 'richtext-desktop.png'), full_page=True)
        page.get_by_role('button', name='保存草稿', exact=True).click()
        expect(page.locator('#editor-message')).to_contain_text('草稿已保存')
        post_id = page.locator('#post-editor').get_attribute('data-post-id')
        page.reload()
        expect(rich.locator('h2')).to_have_text('直接编辑，直接看到效果')
        # Loading and switching modes without edits must retain exact original Markdown.
        page.get_by_role('button', name='Markdown', exact=True).click()
        assert source.input_value() == content
        page.get_by_role('button', name='富文本（试用）', exact=True).click()
        expect(rich).to_be_visible()
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        page.screenshot(path=str(folder / 'richtext-mobile.png'), full_page=True)
        page.get_by_role('button', name='发布帖子', exact=True).click()
        page.wait_for_url(BASE + '/posts/' + post_id)
        expect(page.locator('.article-body strong')).to_have_text('加粗')
        expect(page.locator('.article-body table')).to_be_visible()
        page.get_by_role('button', name='删除帖子', exact=True).click()
        page.get_by_role('button', name='确认删除', exact=True).click()
        page.wait_for_url(BASE + '/me/posts')
        browser.close()
    from community import create_app
    result = create_app().test_cli_runner().invoke(args=['disable-user', '--username', username,
        '--reason', '富文本浏览器验收完成'])
    assert result.exit_code == 0, result.output
    assert not errors, errors
    print(json.dumps({'toolbar': True, 'mode_switch': True, 'preserve_unedited_markdown': True,
        'save_reload_publish': True, 'table': True, 'mobile': True, 'javascript_errors': errors}))


if __name__ == '__main__':
    main()
