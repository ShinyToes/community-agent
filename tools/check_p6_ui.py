"""P6 browser check against an isolated local API and crawler fixture."""
import asyncio
import importlib.util
import json
from pathlib import Path
import socket
import tempfile
import threading
import time

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from playwright.sync_api import sync_playwright, expect
import uvicorn

from community_research.agent.runtime import Harness
from community_research.api.router import create_router
from community_research.knowledge import KnowledgeStore

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def main():
    p6 = module('p6_fixture', ROOT / 'tests/research/test_p6.py')
    models = module('harness_fixture', ROOT / 'tests/research/test_harness.py')
    with tempfile.TemporaryDirectory(prefix='p6-ui-', dir=ROOT / '.runtime') as temporary:
        root = Path(temporary)
        (root / '.env.research').write_text('RESEARCH_BASE_URL=http://test\nRESEARCH_API_KEY=test\nRESEARCH_MODEL=test\n')
        store = KnowledgeStore(root)
        baseline = p6.ingest(store, 'baseline.json', [p6.post(), p6.comment('old')])
        scripted = models.ScriptModel([models.PLAN, {'action': 'tool', 'name': 'search_posts', 'arguments': {}},
                                       models.read_action, models.final_answer])
        harness = Harness(store, lambda: scripted)
        session = harness.create_session()['id']
        asyncio.run(models.execute(harness, session=session))
        adapter = p6.Adapter(root, waiting=True)
        app = FastAPI()
        app.include_router(create_router(harness, adapter))
        @app.get('/api/crawler/status')
        def status():
            return {'status': 'idle', 'platform': None, 'crawler_type': None, 'started_at': None}
        web = ROOT / 'MediaCrawler/api/webui'
        app.mount('/assets', StaticFiles(directory=web / 'assets'))
        app.mount('/logos', StaticFiles(directory=web / 'logos'))
        @app.get('/')
        def index():
            return FileResponse(web / 'index.html')
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=0, log_level='error'))
        sock = socket.socket(); sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
        thread.start()
        checks, errors = [], []
        try:
            for _ in range(100):
                if server.started:
                    break
                time.sleep(.05)
            assert server.started
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1100, 'height': 850})
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.add_init_script("localStorage.setItem('mediacrawler_env_checked','true');localStorage.setItem('mediacrawler_license_accepted','true')")
                page.goto(f'http://127.0.0.1:{port}/#assistant?session={session}')
                refresh = page.get_by_role('button', name='复采并检查更新')
                refresh.wait_for()
                checks.append('source_card_refresh_action')
                refresh.evaluate('(button)=>{button.click();button.click()}')
                page.get_by_text('等待扫码登录', exact=True).wait_for(timeout=10000)
                assert len(adapter.calls) == 1
                assert adapter.calls[0][1]['latest_comments'] is True
                checks.extend(['double_click_submits_once', 'latest_comments_requested', 'login_wait_visible'])
                refresh.click()
                page.get_by_text('排队中', exact=True).wait_for(timeout=10000)
                checks.append('second_job_waits_in_fifo')
                queue = page.get_by_label('复采任务与队列')
                queued = queue.locator('article').filter(has_text='排队中')
                queued.get_by_role('button', name='取消复采').click()
                expect(queued.get_by_role('button', name='取消复采')).to_have_count(0)
                assert adapter.owner is not None and not adapter.stops
                checks.append('cancel_waiter_keeps_current_owner')
                adapter.waiting = False
                queue.get_by_text('已完成', exact=True).wait_for(timeout=10000)
                expect(queue).to_contain_text('新增评论 20')
                expect(queue).to_contain_text('帖子版本变化 1')
                expect(queue).to_contain_text('本次未观测 1')
                checks.extend(['delta_counts', 'absence_is_not_deletion'])
                queue.get_by_role('button', name='下一页对比项').click()
                expect(queue.get_by_role('button', name='返回第一页')).to_be_visible()
                queue.get_by_role('button', name='返回第一页').click()
                checks.append('comparison_pagination')
                if not queue.get_by_text('帖子 · 内容变化', exact=True).count():
                    queue.get_by_role('button', name='下一页对比项').click()
                changed = queue.locator('details').filter(has=page.locator('summary').filter(has_text='帖子 · 内容变化')).last
                changed.locator('summary').click()
                expect(changed).to_contain_text('旧正文')
                expect(changed).to_contain_text('新正文')
                checks.append('before_after_original_quotes')
                page.reload()
                page.get_by_label('复采任务与队列').locator('summary').first.click()
                expect(page.get_by_label('复采任务与队列')).to_contain_text('新增评论 20')
                assert len(adapter.calls) == 1
                checks.append('reload_preserves_jobs_without_replay')
                store.revoke(baseline)
                page.get_by_text('对比来源已失效；无法读取前后对比。', exact=True).wait_for(timeout=10000)
                expect(page.get_by_label('复采任务与队列')).not_to_contain_text('旧正文')
                checks.append('source_revocation_removes_quotes')
                page.set_viewport_size({'width': 390, 'height': 844})
                page.get_by_label('输入问题').fill('继续查看本地内容')
                expect(page.get_by_label('输入问题')).to_have_value('继续查看本地内容')
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                checks.append('narrow_view_and_input')
                assert not errors, errors
                browser.close()
        finally:
            server.should_exit = True
            thread.join(timeout=10)
        report = {'status': 'passed', 'mode': 'isolated_api_model_crawler', 'checks': checks, 'javascript_errors': errors,
                  'external_model_calls': 0, 'real_platform_requests': 0}
        target = ROOT / 'docs/p6/ui-validation.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
