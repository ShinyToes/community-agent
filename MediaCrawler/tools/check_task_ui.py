"""Isolated local WebUI acceptance. Never crawls or touches real collected data."""
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from api import task_store
from api.schemas import CrawlerStartRequest
from playwright.sync_api import sync_playwright, expect


def main():
    runtime = ROOT.parent / '.runtime'
    runtime.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='task-ui-', dir=runtime) as temp:
        task_store.DATA_DIR = Path(temp)
        ids = []
        for keyword, status in [('cs', 'completed'), ('python', 'failed'), ('active', 'running')]:
            row = task_store.create(CrawlerStartRequest(platform='tieba', keywords=keyword, save_option='jsonl'))
            ident = row['id']; ids.append(ident)
            task_store.update(ident, status=status)
            if status == 'completed':
                output = task_store.task_dir(ident) / 'output' / 'tieba' / 'jsonl'
                output.mkdir(parents=True)
                for kind, text in [('contents', '样例帖子'), ('comments', '样例回复')]:
                    (output / f'search_{kind}_test.jsonl').write_text(json.dumps({'note_id': '42', 'content': text}, ensure_ascii=False) + '\n', encoding='utf-8')
        (Path(temp) / 'legacy.json').write_text('[{"old":true}]')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        bootstrap = "from pathlib import Path; from api import task_store; from api.routers import data; task_store.DATA_DIR=data.DATA_DIR=Path(%r); from api.main import app; import uvicorn; uvicorn.run(app,host='127.0.0.1',port=%d,log_level='error')" % (temp, port)
        log = (runtime / 'task-ui-server.log').open('w')
        server = subprocess.Popen([sys.executable, '-c', bootstrap], cwd=ROOT, stdout=log, stderr=log,
                                  creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        url = f'http://127.0.0.1:{port}'
        try:
            task_store.update(ids[2], pid=os.getpid())
            for attempt in range(100):
                try:
                    urllib.request.urlopen(url + '/api/health', timeout=1).close(); break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError('Test server did not start')
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(locale='zh-CN', viewport={'width': 1400, 'height': 1000})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.route('**/api/env/check', lambda route: route.fulfill(json={'success': True, 'message': 'test environment'}))
                page.goto(url)
                page.get_by_role('button', name='我已知晓并同意上述条款').click()
                page.get_by_role('button', name='数据管理', exact=True).click()
                page.get_by_role('button', name=re.compile('tieba · cs')).click()
                page.get_by_role('button', name='评论 (1)', exact=True).click()
                page.get_by_role('button', name='预览', exact=True).click()
                expect(page.get_by_text('样例回复', exact=True)).to_be_visible()
                page.keyboard.press('Escape')
                with page.expect_download() as download:
                    page.get_by_role('button', name='导出任务 ZIP').click()
                exported = Path(temp) / 'export.zip'
                download.value.save_as(exported)
                with zipfile.ZipFile(exported) as archive:
                    assert len(archive.namelist()) == 3
                page.screenshot(path=str(runtime / 'task-management.png'), full_page=True)
                page.once('dialog', lambda dialog: dialog.dismiss())
                page.get_by_role('button', name='删除任务数据').click()
                assert task_store.task_dir(ids[0]).exists()
                page.once('dialog', lambda dialog: dialog.accept())
                page.get_by_role('button', name='删除任务数据').click()
                expect(page.get_by_role('button', name=re.compile('tieba · cs'))).to_have_count(0)
                assert not task_store.task_dir(ids[0]).exists()
                assert task_store.task_dir(ids[1]).exists()
                page.get_by_role('button', name=re.compile('tieba · active')).click()
                expect(page.get_by_role('button', name='删除任务数据')).to_be_disabled()
                expect(page.get_by_role('button', name='导出任务 ZIP')).to_be_disabled()
                page.get_by_role('textbox', name='筛选采集任务').fill('python')
                expect(page.get_by_role('button', name=re.compile('tieba · active'))).to_have_count(0)
                expect(page.get_by_role('button', name=re.compile('tieba · python'))).to_be_visible()
                task_store.update(ids[2], status='stopped', pid=None)
                page.get_by_role('button', name='历史文件', exact=True).click()
                expect(page.get_by_text('legacy.json', exact=True)).to_be_visible()
                page.once('dialog', lambda dialog: dialog.accept())
                page.get_by_role('button', name='删除此历史文件').click()
                expect(page.get_by_text('legacy.json', exact=True)).to_have_count(0)
                assert not errors, errors
                browser.close()
                print('PASS: task selection, comment JSONL preview, ZIP download, cancel/confirm deletion, active protection, keyword filter, legacy deletion; no JS errors')
        finally:
            if os.name == 'nt' and server.poll() is None:
                subprocess.run(['taskkill', '/PID', str(server.pid), '/T', '/F'], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            elif server.poll() is None:
                server.terminate()
            server.wait(timeout=10)
            log.close()


if __name__ == '__main__':
    main()
