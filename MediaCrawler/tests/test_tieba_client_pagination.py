# -*- coding: utf-8 -*-

import asyncio
import pytest

from media_platform.tieba.client import BaiduTieBaClient
from model.m_baidu_tieba import TiebaComment, TiebaNote


class DummyPage:
    url = "https://tieba.baidu.com/"


@pytest.mark.asyncio
async def test_refresh_comments_start_at_tail_and_keep_quota():
    client = BaiduTieBaClient(playwright_page=DummyPage())
    note = TiebaNote(note_id='123', title='测试', note_url='https://tieba.baidu.com/p/123',
                    tieba_name='测试吧', tieba_link='https://tieba.baidu.com/f?kw=test', total_replay_page=100)
    pages, saved = [], []
    async def fetch(note_id, page=1):
        pages.append(page)
        return {'page': page}
    def extract(data, note_detail):
        return [TiebaComment(comment_id=str(data['page'] * 10 + i), note_id='123', content='评论',
                            note_url=note.note_url, tieba_id='1', tieba_name=note.tieba_name,
                            tieba_link=note.tieba_link) for i in range(3)]
    async def callback(note_id, comments):
        saved.extend(c.comment_id for c in comments)
    client._get_pc_page_data = fetch
    client._page_extractor.extract_tieba_note_parent_comments_from_api = extract
    client.get_comments_all_sub_comments = lambda *args, **kwargs: asyncio.sleep(0)
    result = await client.get_note_all_comments(note, crawl_interval=0, callback=callback, max_count=4, newest_first=True)
    assert pages == [100, 99]
    assert saved == ['1002', '1001', '1000', '992']
    assert len(result) == 4


@pytest.mark.asyncio
async def test_search_uses_requested_page_number():
    client = BaiduTieBaClient(playwright_page=DummyPage())
    calls = []

    async def fake_fetch(uri, method="GET", params=None, data=None, use_sign=False):
        calls.append((uri, params))
        return {"no": 0, "data": {"card_list": []}}

    client._fetch_json_by_browser = fake_fetch

    await client.get_notes_by_keyword("编程兼职", page=2, page_size=10)

    assert calls[0][0] == "/mo/q/search/multsearch"
    assert calls[0][1]["pn"] == 2


@pytest.mark.asyncio
async def test_comments_walk_pages_until_total_reply_page():
    client = BaiduTieBaClient(playwright_page=DummyPage())
    pages = []
    note = TiebaNote(
        note_id="9835114923",
        title="title",
        note_url="https://tieba.baidu.com/p/9835114923",
        tieba_name="加工中心吧",
        tieba_link="https://tieba.baidu.com/f?kw=%E5%8A%A0%E5%B7%A5%E4%B8%AD%E5%BF%83",
        total_replay_page=2,
    )

    async def fake_get_page_data(note_id, page=1):
        pages.append(page)
        return {"forum": {"id": 1, "name": "加工中心"}, "post_list": []}

    def fake_extract_comments(api_data, note_detail):
        page = pages[-1]
        return [
            TiebaComment(
                comment_id=str(page),
                content="comment",
                note_id=note_detail.note_id,
                note_url=note_detail.note_url,
                tieba_id="1",
                tieba_name=note_detail.tieba_name,
                tieba_link=note_detail.tieba_link,
            )
        ]

    client._get_pc_page_data = fake_get_page_data
    client._page_extractor.extract_tieba_note_parent_comments_from_api = fake_extract_comments

    await client.get_note_all_comments(note, crawl_interval=0, max_count=10)

    assert pages == [1, 2]


@pytest.mark.asyncio
async def test_creator_feed_walks_until_has_more_false(monkeypatch):
    client = BaiduTieBaClient(playwright_page=DummyPage())
    pages = []

    async def fake_get_notes_by_creator_portrait(portrait, page_number, page_size=20):
        pages.append(page_number)
        return {
            "error_code": 0,
            "data": {
                "has_more": 1 if page_number == 1 else 0,
                "list": [
                    {
                        "thread_info": {
                            "id": str(1000 + page_number),
                            "tid": str(1000 + page_number),
                        }
                    }
                ],
            },
        }

    async def fake_get_note_by_id(note_id):
        return TiebaNote(
            note_id=note_id,
            title="title",
            note_url=f"https://tieba.baidu.com/p/{note_id}",
            tieba_name="加工中心吧",
            tieba_link="https://tieba.baidu.com/f?kw=%E5%8A%A0%E5%B7%A5%E4%B8%AD%E5%BF%83",
        )

    async def fake_sleep(_):
        return None

    client.get_notes_by_creator_portrait = fake_get_notes_by_creator_portrait
    client.get_note_by_id = fake_get_note_by_id
    monkeypatch.setattr("media_platform.tieba.client.asyncio.sleep", fake_sleep)

    notes = await client.get_all_notes_by_creator_url("tb.1.creator", crawl_interval=0)

    assert pages == [1, 2]
    assert [note.note_id for note in notes] == ["1001", "1002"]
