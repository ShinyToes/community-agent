import asyncio
import io
import json
import os
import zipfile

import httpx
import pytest

from api.main import app
from api import task_store
from api.routers import data
from api.schemas import CrawlerStartRequest
from api.services.crawler_manager import CrawlerManager


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(task_store, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(data, 'DATA_DIR', tmp_path)
    return tmp_path


def sample(keyword='cs', status='completed'):
    row = task_store.create(CrawlerStartRequest(platform='tieba', keywords=keyword, cookies='SECRET_COOKIE', save_option='jsonl'))
    task_store.update(row['id'], status=status)
    folder = task_store.task_dir(row['id']) / 'output' / 'tieba' / 'jsonl'
    folder.mkdir(parents=True)
    for kind in ('contents', 'comments'):
        (folder / f'search_{kind}_2026-09-18.jsonl').write_text(json.dumps({'note_id': 'same-post', 'content': keyword, 'source_keyword': keyword}) + '\n', encoding='utf-8')
    return row['id']


@pytest.mark.asyncio
async def test_task_isolation_filter_export_delete_and_legacy(root):
    first, second = sample('cs'), sample('python')
    legacy = root / 'old.json'
    legacy.write_text('[{"old":true}]')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        rows = (await client.get('/api/data/tasks')).json()['tasks']
        assert len(rows) == 2 and all(len(row['files']) == 2 for row in rows)
        assert 'SECRET_COOKIE' not in json.dumps(rows)
        assert [r['id'] for r in (await client.get('/api/data/tasks', params={'keyword':'cs'})).json()['tasks']] == [first]
        assert len((await client.get('/api/data/files')).json()['files']) == 1
        file = next(r for r in rows if r['id'] == first)['files'][0]
        response = await client.get('/api/data/files/' + file['path'].replace('\\','/'))
        assert response.status_code == 200 and response.json()['data'][0]['source_keyword'] == 'cs'
        response = await client.get(f'/api/data/tasks/{first}/export')
        assert response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            assert len(archive.namelist()) == 3
            assert 'SECRET_COOKIE' not in archive.read('task.json').decode()
        assert (await client.delete('/api/data/files/' + file['path'].replace('\\','/'))).status_code == 400
        assert (await client.delete(f'/api/data/tasks/{first}')).status_code == 200
        assert not task_store.task_dir(first).exists()
        assert task_store.task_dir(second).exists() and legacy.exists()
        assert (await client.delete(f'/api/data/tasks/{first}')).status_code == 404
        assert (await client.delete('/api/data/files/old.json')).status_code == 200
        assert not legacy.exists() and task_store.task_dir(second).exists()


@pytest.mark.asyncio
async def test_running_tasks_cannot_be_deleted_or_exported(root):
    ident = sample(status='running')
    task_store.update(ident, pid=os.getpid())
    (root / 'old.json').write_text('[]')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.delete(f'/api/data/tasks/{ident}')).status_code == 409
        assert (await client.get(f'/api/data/tasks/{ident}/export')).status_code == 409
        assert (await client.delete('/api/data/files/old.json')).status_code == 409
    assert task_store.task_dir(ident).exists()


@pytest.mark.asyncio
async def test_paths_and_metadata_are_not_data_files(root):
    ident = sample()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        for path in ('..%5Coutside.json', '%2Fetc%2Fpasswd', f'tasks/{ident}/task.json'):
            assert (await client.get('/api/data/files/' + path)).status_code in (403,404)
            assert (await client.delete('/api/data/files/' + path)).status_code in (403,404)
        assert (await client.delete('/api/data/tasks/not-a-task')).status_code == 404
    assert task_store.load(ident)['keywords'] == 'cs'


def test_restart_marks_only_dead_tasks_interrupted(root):
    dead, alive = sample(status='running'), sample(status='running')
    task_store.update(alive, pid=os.getpid())
    task_store.reconcile()
    assert task_store.load(dead)['status'] == 'interrupted'
    assert task_store.load(alive)['status'] == 'running'


@pytest.mark.asyncio
@pytest.mark.parametrize('exit_code,logged_error,expected', [(0, False, 'completed'), (1, False, 'failed'), (0, True, 'completed_with_errors')])
async def test_real_process_lifecycle_and_unique_output(root, monkeypatch, exit_code, logged_error, expected):
    manager = CrawlerManager()
    script = "import sys,pathlib; p=pathlib.Path(sys.argv[-1])/'tieba'/'json'; p.mkdir(parents=True); (p/'search_contents.json').write_text('[{}]'); print('MediaCrawler %s (test.py:1) - test'); sys.exit(%s)" % ('ERROR' if logged_error else 'INFO', exit_code)
    monkeypatch.setattr(manager, '_build_command', lambda config: ['uv','run','python','-c',script])
    for _ in range(2):
        assert await manager.start(CrawlerStartRequest(platform='tieba', keywords='cs'))
        await asyncio.wait_for(manager._read_task, timeout=15)
        assert task_store.load(manager.task_id)['status'] == expected
    rows = task_store.list_tasks()
    assert len(rows) == 2 and all(len(task_store.output_files(r['id'])) == 1 for r in rows)


@pytest.mark.asyncio
async def test_launch_failure_remains_visible(root, monkeypatch):
    manager = CrawlerManager()
    def fail(*args, **kwargs):
        raise OSError('test launch failure')
    import subprocess
    monkeypatch.setattr(subprocess, 'Popen', fail)
    assert not await manager.start(CrawlerStartRequest(platform='tieba', keywords='cs'))
    assert task_store.load(manager.task_id)['status'] == 'failed'


def test_post_text_does_not_change_log_level():
    assert CrawlerManager()._parse_log_level('MediaCrawler INFO (file.py:1) - content: 成功 ERROR SUCCESS') == 'info'


@pytest.mark.asyncio
async def test_stop_and_delete_after_process_exit(root, monkeypatch):
    manager = CrawlerManager()
    monkeypatch.setattr(manager, '_build_command', lambda config: ['uv','run','python','-c','import time; time.sleep(60)'])
    assert await manager.start(CrawlerStartRequest(platform='tieba', keywords='cs'))
    ident = manager.task_id
    assert await manager.stop()
    assert manager.process.poll() is not None
    assert task_store.load(ident)['status'] == 'stopped'
    task_store.delete(ident)
    assert not task_store.task_dir(ident).exists()


@pytest.mark.asyncio
async def test_actual_writer_preserves_same_post_in_different_tasks(root, monkeypatch):
    import config
    from tools.async_file_writer import AsyncFileWriter
    first, second = sample('cs'), sample('饰品')
    for ident, keyword in [(first, 'cs'), (second, '饰品')]:
        monkeypatch.setattr(config, 'SAVE_DATA_PATH', str(task_store.task_dir(ident) / 'output'))
        await AsyncFileWriter('tieba', 'search').write_single_item_to_json({'note_id': '42', 'source_keyword': keyword}, 'contents')
    first_json = next(p for p in task_store.output_files(first) if p.suffix == '.json')
    second_json = next(p for p in task_store.output_files(second) if p.suffix == '.json')
    assert json.loads(first_json.read_text(encoding='utf-8'))[0]['source_keyword'] == 'cs'
    assert json.loads(second_json.read_text(encoding='utf-8'))[0]['source_keyword'] == '饰品'


@pytest.mark.asyncio
async def test_excel_sheets_and_database_mode_boundary(root):
    from openpyxl import Workbook
    workbook = Workbook()
    workbook.active.title = '帖子'
    workbook.active.append(['title']); workbook.active.append(['cs'])
    comments = workbook.create_sheet('评论')
    comments.append(['content']); comments.append(['reply'])
    workbook.save(root / 'sample.xlsx')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.get('/api/data/files/sample.xlsx', params={'sheet': '评论'})
        assert response.status_code == 200
        assert response.json()['data'] == [{'content': 'reply'}]
        assert response.json()['sheets'] == ['帖子', '评论']
        assert (await client.get('/api/data/files/sample.xlsx', params={'sheet': 'missing'})).status_code == 400
        assert (await client.post('/api/crawler/start', json={'platform':'tieba','keywords':'cs','save_option':'db'})).status_code == 400
