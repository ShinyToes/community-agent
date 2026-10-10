"""Offline smoke check of actual platform browser launch paths; no login or crawling."""
import asyncio
import importlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config
from playwright.async_api import async_playwright


async def main():
    platforms = [('tieba', 'TieBaCrawler'), ('bilibili', 'BilibiliCrawler'),
                 ('kuaishou', 'KuaishouCrawler'), ('zhihu', 'ZhihuCrawler'),
                 ('weibo', 'WeiboCrawler')]
    with tempfile.TemporaryDirectory(prefix='crawler-browser-check-') as temp:
        config.USER_DATA_DIR = str(Path(temp) / '%s')
        async with async_playwright() as playwright:
            for platform, class_name in platforms:
                crawler = getattr(importlib.import_module(f'media_platform.{platform}.core'), class_name)()
                for persistent, headless in [(True, True), (False, True)] + ([(True, False)] if platform == 'tieba' else []):
                    config.PLATFORM = platform
                    config.SAVE_LOGIN_STATE = persistent
                    context = await crawler.launch_browser(playwright.chromium, None, None, headless=headless)
                    browser = context.browser
                    try:
                        page = await context.new_page()
                        await page.set_content('<title>Browser launch verified</title><p>Local check</p>')
                        assert await page.title() == 'Browser launch verified'
                        print(json.dumps(dict(platform=platform, persistent=persistent, headless=headless, passed=True)), flush=True)
                    finally:
                        await context.close()
                        if browser and browser.is_connected():
                            await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
