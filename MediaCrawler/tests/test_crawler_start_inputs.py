from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from api.routers.crawler import start_crawler
from api.services import crawler_manager
from api.schemas import CrawlerStartRequest
from media_platform.tieba.login import BaiduTieBaLogin


@pytest.mark.asyncio
@pytest.mark.parametrize('keywords,login_type,cookies', [('', 'qrcode', ''), (' , ', 'qrcode', ''), ('cs', 'cookie', ' ')])
async def test_invalid_inputs_never_start_process(monkeypatch, keywords, login_type, cookies):
    start = AsyncMock()
    monkeypatch.setattr(crawler_manager, 'start', start)
    with pytest.raises(HTTPException) as error:
        await start_crawler(CrawlerStartRequest(platform='tieba', keywords=keywords, login_type=login_type, cookies=cookies))
    assert error.value.status_code == 400
    start.assert_not_called()


@pytest.mark.asyncio
async def test_keyword_reaches_command(monkeypatch):
    start = AsyncMock(return_value=True)
    monkeypatch.setattr(crawler_manager, 'start', start)
    request = CrawlerStartRequest(platform='tieba', keywords=' cs, , python ', login_type='qrcode')
    await start_crawler(request)
    command = crawler_manager._build_command(start.call_args.args[0])
    assert command[command.index('--keywords') + 1] == 'cs,python'


@pytest.mark.asyncio
async def test_tieba_empty_cookie_does_not_silently_succeed():
    browser = AsyncMock()
    login = BaiduTieBaLogin('cookie', browser, None, cookie_str=' ')
    with pytest.raises(ValueError, match='Cookie'):
        await login.login_by_cookies()
    browser.add_cookies.assert_not_called()
