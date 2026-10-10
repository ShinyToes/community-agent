"""Exercise the real crawler boundary without contacting Tieba."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'MediaCrawler'))
import config
from media_platform.tieba.core import TieBaCrawler
from api.research_bridge import CollectionAdapter
from api.services.crawler_manager import CrawlerManager
from media_platform.tieba.login import BaiduTieBaLogin, BrowserTimeout


async def main():
    locator = SimpleNamespace(wait_for=AsyncMock(side_effect=BrowserTimeout('selector missing')), click=AsyncMock(side_effect=BrowserTimeout('selector missing')))
    login = BaiduTieBaLogin('qrcode', None, SimpleNamespace(locator=lambda _: locator))
    login.check_login_state = AsyncMock(return_value=True)
    with patch.dict('os.environ', {'RESEARCH_COLLECTION_OWNER': 'test'}), patch('media_platform.tieba.login.asyncio.sleep', new=AsyncMock()):
        await login.login_by_qrcode()
    login.check_login_state.assert_awaited_once()
    for quota in (1, 11, 20):
        crawler = TieBaCrawler()
        async def search(**kwargs):
            offset = (kwargs['page'] - 1) * 10
            return [SimpleNamespace(note_id=str(i)) for i in range(offset, offset + 10)]
        crawler.tieba_client = SimpleNamespace(get_notes_by_keyword=search)
        captured = []
        async def detail(note_id_list):
            captured.extend(note_id_list)
        crawler.get_specified_notes = detail
        with patch.object(config, 'KEYWORDS', 'CS'), patch.object(config, 'START_PAGE', 1), patch.object(config, 'CRAWLER_MAX_NOTES_COUNT', quota), patch.object(config, 'CRAWLER_MAX_SLEEP_SEC', 0):
            await crawler.search()
        assert len(captured) == len(set(captured)) == quota
    manager = SimpleNamespace(task_id='a' * 32, start=AsyncMock(return_value=True))
    with patch('api.research_bridge.crawler_manager', manager):
        adapter = CollectionAdapter()
        await adapter.start('owner', query='CS 饰品', notes=1, comments=2)
        request = manager.start.call_args.args[0]
        assert request.keywords == 'CS 饰品' and not request.enable_comments
        cmd = CrawlerManager()._build_command(request)
        assert cmd[cmd.index('--crawler_max_notes_count') + 1] == '1'
        assert '--cookies' not in cmd
        await adapter.start('owner', post_ids=['123'], notes=1, comments=2)
        request = manager.start.call_args.args[0]
        assert request.specified_ids == '123' and request.enable_comments and not request.enable_sub_comments
        assert request.max_comments_count == 2
        await adapter.start('owner', post_ids=['123'], notes=1, comments=0, latest_comments=True)
        request = manager.start.call_args.args[0]
        assert not request.enable_comments and request.comment_order == 'latest'
        assert request.max_comments_count == 1
    print(json.dumps({'status': 'passed', 'checks': ['quota_1', 'quota_11', 'quota_20', 'exact_query', 'post_only_first', 'selected_comments', 'no_cookie_arguments', 'missing_login_selector_waits_for_user']}))


if __name__ == '__main__':
    asyncio.run(main())
