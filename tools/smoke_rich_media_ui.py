"""Verify rich formatting and real image permissions in a browser."""
from pathlib import Path
import json
import os
import secrets
import sys

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE = os.getenv('COMMUNITY_UI_BASE', 'http://127.0.0.1:5001')


def main():
    folder = ROOT / 'instance/community'; folder.mkdir(parents=True, exist_ok=True)
    picture = folder / 'media-test.png'
    im = Image.new('RGB', (900, 480), '#e7f1ea')
    draw = ImageDraw.Draw(im)
    draw.rounded_rectangle((70, 70, 830, 410), radius=35, fill='#175c4b')
    draw.ellipse((120, 140, 310, 330), fill='#c4e0c9')
    draw.rectangle((370, 180, 740, 200), fill='#ffffff')
    draw.rectangle((370, 240, 620, 260), fill='#c4e0c9')
    im.save(picture)
    username = 'media_' + secrets.token_hex(5)
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width':1440,'height':1050})
        guest = browser.new_context()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('dialog', lambda d: d.accept())
        page.goto(BASE + '/auth/register')
        page.get_by_label('用户名', exact=True).fill(username)
        page.get_by_label('密码', exact=True).fill(secrets.token_urlsafe(20))
        page.get_by_role('button', name='创建账号', exact=True).click()
        page.wait_for_url(BASE + '/')
        page.goto(BASE + '/posts/new')
        rich = page.get_by_role('textbox', name='富文本正文', exact=True)
        expect(rich).to_be_visible()
        page.get_by_label('标题', exact=True).fill('图文笔记：给想法加一点颜色')
        page.get_by_label('标签', exact=True).fill('学习笔记, 图文')
        rich.fill('这是一段有颜色的重点内容')
        rich.press('Control+a')
        page.get_by_label('字体颜色', exact=True).select_option('#b42318')
        page.get_by_label('文字背景色', exact=True).select_option('#fff3bf')
        page.get_by_label('字号', exact=True).select_option('24px')
        page.get_by_role('button', name='加粗', exact=True).click()
        expect(rich.locator('.rt-fg-red').first).to_be_visible()
        assert rich.locator('.rt-fg-red').first.evaluate('(el) => getComputedStyle(el).color') == 'rgb(180, 35, 24)'
        rich.press('ArrowRight'); rich.press('Enter')
        page.get_by_role('button', name='清除文字样式', exact=True).click()
        page.keyboard.insert_text('在笔记里插入配图，保存后再发布。')
        rich.press('Enter')
        with page.expect_file_chooser() as file_chooser:
            page.get_by_role('button', name='插入图片', exact=True).click()
        file_chooser.value.set_files(picture)
        image = rich.locator('img')
        expect(image).to_be_visible()
        image.click()
        page.get_by_label('图片宽度', exact=True).select_option('75')
        expect(image).to_have_class('post-image rt-image-75 ProseMirror-selectednode')
        src = image.get_attribute('src')
        assert guest.request.get(BASE + src).status == 404
        page.get_by_role('button', name='保存草稿', exact=True).click()
        expect(page.locator('#editor-message')).to_contain_text('草稿已保存')
        post_id = page.locator('#post-editor').get_attribute('data-post-id')
        page.reload()
        expect(rich.locator('.rt-fg-red').first).to_be_visible()
        expect(rich.locator('.rt-bg-yellow').first).to_be_visible()
        expect(rich.locator('.rt-size-24').first).to_be_visible()
        expect(rich.locator('img.rt-image-75')).to_be_visible()
        page.screenshot(path=str(folder / 'rich-media-editor.png'), full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(folder / 'rich-media-mobile.png'), full_page=True)
        page.get_by_role('button', name='发布帖子', exact=True).click()
        page.wait_for_url(BASE + '/posts/' + post_id)
        expect(page.locator('.article-body .rt-fg-red').first).to_be_visible()
        expect(page.locator('.article-body img')).to_be_visible()
        assert guest.request.get(BASE + src).status == 200
        page.get_by_role('link', name='编辑帖子', exact=True).click()
        expect(rich.locator('.rt-fg-red').first).to_be_visible()
        page.goto(BASE + '/posts/' + post_id + '/revisions')
        page.locator('summary').first.click()
        expect(page.locator('details').first.locator('.rt-fg-red').first).to_be_visible()
        page.goto(BASE + '/posts/' + post_id)
        page.get_by_role('button', name='删除帖子', exact=True).click()
        page.get_by_role('button', name='确认删除', exact=True).click()
        page.wait_for_url(BASE + '/me/posts')
        assert guest.request.get(BASE + src).status == 404
        browser.close()
    from community import create_app
    result = create_app().test_cli_runner().invoke(args=['disable-user','--username',username,'--reason','图文编辑自动验收完成'])
    assert result.exit_code == 0, result.output
    assert not errors, errors
    print(json.dumps({'color_background_size':True,'upload_reload_publish':True,
        'draft_image_private':True,'deleted_image_private':True,'history':True,'mobile':True,'js_errors':errors}))


if __name__ == '__main__':
    main()
