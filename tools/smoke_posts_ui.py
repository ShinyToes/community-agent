"""Phase 1 browser acceptance on local service, using only generated test content."""
from pathlib import Path
import json
import secrets
import sys
import uuid

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE = 'http://127.0.0.1:5001'


def main():
    from community import create_app
    from community.extensions import db
    from community.models import Post, User
    from community.services.posts import mutate
    from sqlalchemy import select
    suffix = secrets.token_hex(5)
    accounts = ['writer_' + suffix, 'reader_' + suffix]
    password = secrets.token_urlsafe(18)
    errors = []
    output = ROOT / 'instance' / 'community'
    output.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='msedge', headless=True)
            author = browser.new_context(viewport={'width': 1440, 'height': 1050})
            other = browser.new_context(viewport={'width': 1440, 'height': 1050})
            page = author.new_page(); reader = other.new_page()
            for target, name in [(page, accounts[0]), (reader, accounts[1])]:
                target.on('pageerror', lambda error: errors.append(str(error)))
                target.on('dialog', lambda dialog: dialog.accept())
                target.goto(BASE + '/auth/register')
                target.get_by_label('用户名', exact=True).fill(name)
                target.get_by_label('密码', exact=True).fill(password)
                target.get_by_role('button', name='创建账号', exact=True).click()
                target.wait_for_url(BASE + '/')
            page.get_by_role('link', name='写帖子', exact=True).click()
            page.get_by_label('标题', exact=True).fill('理解数据库事务：一次完整的学习记录')
            page.get_by_label('标签', exact=True).fill('数据库, Python')
            original = '# 为什么需要事务？\n\n一次操作中的多个修改，应当一起成功或一起失败。\n\n## 一个例子\n\n```python\nwith session.begin():\n    save_post()\n    update_index()\n```\n\n> 先理解原子性，再讨论隔离性。\n\n<script>window.unsafeExecuted=true</script>'
            page.get_by_label('正文 · Markdown', exact=True).fill(original)
            expect(page.locator('#preview-panel h1')).to_have_text('为什么需要事务？')
            page.get_by_label('正文 · Markdown', exact=True).fill('# 自动刷新验证')
            expect(page.locator('#preview-panel h1')).to_have_text('自动刷新验证')
            page.get_by_label('正文 · Markdown', exact=True).fill('')
            expect(page.locator('#preview-panel')).to_contain_text('开始输入正文')
            page.get_by_label('正文 · Markdown', exact=True).fill(original)
            expect(page.locator('#preview-panel h1')).to_have_text('为什么需要事务？')
            assert page.evaluate('window.unsafeExecuted === undefined')
            page.screenshot(path=str(output / 'post-editor.png'), full_page=True)
            page.get_by_role('button', name='保存草稿', exact=True).click()
            expect(page.locator('#editor-message')).to_contain_text('草稿已保存')
            post_id = page.locator('#post-editor').get_attribute('data-post-id')
            assert reader.goto(BASE + '/posts/' + post_id).status == 404
            reader.goto(BASE + '/')
            expect(reader.get_by_role('link', name='理解数据库事务：一次完整的学习记录', exact=True)).to_have_count(0)
            page.get_by_role('button', name='发布帖子', exact=True).click()
            page.wait_for_url(BASE + '/posts/' + post_id)
            assert reader.goto(BASE + '/posts/' + post_id).status == 200
            expect(reader.get_by_role('link', name='编辑帖子', exact=True)).to_have_count(0)
            assert reader.goto(BASE + '/posts/' + post_id + '/edit').status == 404
            page.screenshot(path=str(output / 'post-published.png'), full_page=True)
            page.get_by_role('link', name='编辑帖子', exact=True).click()
            expect(page.locator('#preview-panel h1')).to_have_text('为什么需要事务？')
            stale = author.new_page()
            stale.on('dialog', lambda dialog: dialog.accept())
            stale.goto(BASE + '/posts/' + post_id + '/edit')
            page.get_by_label('正文 · Markdown', exact=True).fill(original + '\n\n补充：事务还能帮助处理并发。')
            page.get_by_label('修改说明（可选）', exact=True).fill('补充并发说明')
            page.get_by_role('button', name='更新公开内容', exact=True).click()
            expect(page.locator('#editor-message')).to_contain_text('公开内容已更新')
            stale.get_by_label('正文 · Markdown', exact=True).fill('这个旧窗口的内容必须保留，不能覆盖最新版本。')
            stale.get_by_role('button', name='更新公开内容', exact=True).click()
            expect(stale.locator('#editor-message')).to_contain_text('其他窗口更新')
            expect(stale.get_by_label('正文 · Markdown', exact=True)).to_have_value('这个旧窗口的内容必须保留，不能覆盖最新版本。')
            expect(stale.locator('#latest-version')).to_be_visible()
            stale.screenshot(path=str(output / 'post-conflict.png'), full_page=True)
            stale.close()
            page.goto(BASE + '/posts/' + post_id + '/revisions')
            expect(page.locator('details')).to_have_count(3)
            page.locator('details').first.locator('summary').click()
            expect(page.locator('details').first).to_contain_text('补充并发说明')
            page.goto(BASE + '/posts/' + post_id + '/edit')
            page.set_viewport_size({'width': 390, 'height': 844})
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            page.screenshot(path=str(output / 'post-mobile.png'), full_page=True)
            # A second independent author can publish without sharing the first author's identity.
            reader.goto(BASE + '/posts/new')
            reader.get_by_label('标题', exact=True).fill('第二位用户的独立帖子')
            reader.get_by_label('正文 · Markdown', exact=True).fill('这是第二位用户自己的内容。')
            reader.get_by_role('button', name='发布帖子', exact=True).click()
            reader.wait_for_url('**/posts/*')
            expect(reader.locator('.article > h1')).to_have_text('第二位用户的独立帖子')
            page.goto(BASE + '/posts/' + post_id)
            page.get_by_role('button', name='删除帖子', exact=True).click()
            page.get_by_role('button', name='取消', exact=True).click()
            expect(page.locator('#delete-dialog')).not_to_be_visible()
            page.get_by_role('button', name='删除帖子', exact=True).click()
            page.get_by_role('button', name='确认删除', exact=True).click()
            page.wait_for_url(BASE + '/me/posts')
            assert reader.goto(BASE + '/posts/' + post_id).status == 404
            browser.close()
        assert not errors, errors
    finally:
        app = create_app()
        with app.app_context():
            users = db.session.scalars(select(User).where(User.username.in_(accounts))).all()
            for user in users:
                posts = db.session.scalars(select(Post).where(Post.author_id == user.id,
                    Post.status.in_(['draft', 'published']))).all()
                for post in posts:
                    mutate(user.id, 'delete', {'base_version': post.version,
                        'operation_key': uuid.uuid4().hex}, post.id)
                result = app.test_cli_runner().invoke(args=['disable-user', '--username', user.username,
                    '--reason', '阶段1浏览器验收账号停用'])
                assert result.exit_code == 0, result.output
    print(json.dumps({'draft_privacy': True, 'publish': True, 'two_authors': True,
        'version_conflict_keeps_input': True, 'history': True, 'safe_markdown': True,
        'delete': True, 'mobile_no_overflow': True, 'javascript_errors': errors}))


if __name__ == '__main__':
    main()
