"""Isolated built-UI smoke test with scripted model; never contacts a provider."""
import asyncio
import json
from pathlib import Path
import socket
import tempfile
import threading
import time

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from playwright.sync_api import sync_playwright
import uvicorn

from community_research.agent.runtime import Harness
from community_research.api.router import create_router
from community_research.knowledge import KnowledgeStore


ROOT = Path(__file__).resolve().parents[1]


class DemoModel:
    def __init__(self):
        self.step = 0

    async def complete(self, messages):
        if json.loads(messages[1]['content'])['recent_user_turns'][-1] == '停止测试':
            await asyncio.sleep(30)
        self.step += 1
        await asyncio.sleep(.15)
        if self.step == 1:
            result = {'action': 'plan', 'goal': dict(entity='CS 饰品', domain='电竞', question='示例评论', time_range='不限', constraints='本地')}
        elif self.step == 2:
            result = {'action': 'tool', 'name': 'search_comments', 'arguments': {'all_terms': ['CS']}}
        elif self.step == 3:
            data = json.loads(messages[-1]['content'])['tool_result_untrusted']
            result = {'action': 'tool', 'name': 'read_evidence', 'arguments': {'evidence_ids': [data['items'][0]['snippets'][0]['evidence_id']], 'include_context': True}}
        else:
            data = json.loads(messages[-1]['content'])['tool_result_untrusted']
            result = {'action': 'answer', 'outcome': 'partial', 'paragraphs': [{'text': '这条评论讨论 CS 饰品价格。', 'evidence_ids': [data['items'][0]['evidence_id']]}], 'limitations': ['浏览器测试使用脚本模型，不是真实模型质量评测。']}
        return json.dumps(result, ensure_ascii=False)


def main():
    runtime_dir = ROOT / '.runtime'; runtime_dir.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='p3-ui-', dir=runtime_dir) as temporary:
        root = Path(temporary)
        store = KnowledgeStore(root)
        path = root / 'data.json'
        path.write_text(json.dumps([{'note_id': 'p', 'title': '示例原帖', 'desc': '讨论饰品变化', 'note_url': 'https://tieba.baidu.com/p/1'},
                                    {'comment_id': 'c', 'note_id': 'p', 'content': 'CS 饰品价格变了。', 'note_url': 'https://tieba.baidu.com/p/1'}], ensure_ascii=False), encoding='utf-8')
        source = store.register_source(path, platform='tieba'); store.import_source(source['id'])
        harness = Harness(store, DemoModel)
        app = FastAPI(); app.include_router(create_router(harness))
        @app.get('/api/crawler/status')
        def status():
            return {'status': 'idle', 'platform': None, 'crawler_type': None, 'start_time': None}
        webui = ROOT / 'MediaCrawler/api/webui'
        app.mount('/assets', StaticFiles(directory=webui / 'assets'))
        app.mount('/logos', StaticFiles(directory=webui / 'logos'))
        @app.get('/')
        def index():
            return FileResponse(webui / 'index.html')
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=0, log_level='error'))
        sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True); thread.start()
        try:
            for _ in range(100):
                if server.started:
                    break
                time.sleep(.05)
            assert server.started
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1280, 'height': 900})
                def check_input():
                    page.get_by_role('dialog', name='删除会话', exact=True).wait_for(state='detached')
                    page.wait_for_function("document.activeElement?.getAttribute('aria-label') === '输入问题'")
                    entry = page.get_by_label('输入问题')
                    entry.click(timeout=3000)
                    page.keyboard.insert_text('删除后输入测试')
                    assert entry.input_value() == '删除后输入测试'
                    entry.fill('')
                errors = []; page.on('pageerror', lambda exc: errors.append(str(exc)))
                page.add_init_script("localStorage.setItem('mediacrawler_env_checked','true');localStorage.setItem('mediacrawler_license_accepted','true')")
                page.add_init_script('''
                  window.raceStats = {creates:0, runs:0, lists:0, captured:0};
                  window.delayNextList = true;
                  const originalFetch = window.fetch.bind(window);
                  window.fetch = async (input, options) => {
                    const url = String(input), method = options?.method || 'GET';
                    const list = url.endsWith('/api/research/sessions') && method === 'GET';
                    const create = url.endsWith('/api/research/sessions') && method === 'POST';
                    const delay = list && window.delayNextList;
                    if (delay) window.delayNextList = false;
                    if (list) window.raceStats.lists++;
                    if (create) window.raceStats.creates++;
                    if (url.endsWith('/runs') && method === 'POST') window.raceStats.runs++;
                    const response = await originalFetch(input, options);
                    if (delay) { window.raceStats.captured++; await new Promise(r => setTimeout(r, 2500)); }
                    if (create) await new Promise(r => setTimeout(r, 600));
                    return response;
                  };
                ''')
                page.goto(f'http://127.0.0.1:{port}/#assistant')
                page.wait_for_function('window.raceStats.captured === 1')
                page.get_by_role('button', name='新对话', exact=True).evaluate('(el) => { el.click(); el.click(); }')
                page.wait_for_function("new URLSearchParams(location.hash.split('?')[1]).get('session')")
                first_session = page.evaluate("new URLSearchParams(location.hash.split('?')[1]).get('session')")
                page.wait_for_timeout(2800)
                assert page.evaluate("new URLSearchParams(location.hash.split('?')[1]).get('session')") == first_session
                assert page.evaluate('window.raceStats.creates') == 1
                page.get_by_label('输入问题').fill('哪些评论讨论 CS？')
                page.get_by_role('button', name='发送', exact=True).evaluate('(el) => { el.click(); el.click(); }')
                page.get_by_text('这条评论讨论 CS 饰品价格。', exact=False).wait_for(timeout=15000)
                assert page.evaluate('window.raceStats.runs') == 1
                assert len(harness.sessions()) == 1
                page.get_by_text('本次展示：0 个帖子、1 条评论', exact=True).wait_for()
                card = page.locator('[data-source-kind="comment"]')
                assert card.get_by_role('link', name='示例原帖', exact=True).get_attribute('href') == 'https://tieba.baidu.com/p/1'
                assert card.get_by_text('CS 饰品价格变了。', exact=True).is_visible()
                assert card.get_by_role('link', name='打开网站原帖 ↗', exact=True).get_attribute('target') == '_blank'
                page.get_by_role('link', name='查看评论原文与上下文', exact=True).click()
                page.locator('mark').wait_for()
                assert page.locator('mark').inner_text() == 'CS 饰品价格变了。'
                assert page.get_by_text('讨论饰品变化', exact=True).is_visible()
                page.reload(); page.locator('mark').wait_for()
                page.screenshot(path=str(runtime_dir / 'p3-evidence.png'), full_page=True)
                page.get_by_role('link', name='← 返回刚才的对话').click()
                page.get_by_text('这条评论讨论 CS 饰品价格。', exact=False).wait_for()
                page.reload(); page.get_by_text('这条评论讨论 CS 饰品价格。', exact=False).wait_for()
                page.get_by_label('输入问题').fill('停止测试')
                page.get_by_role('button', name='发送', exact=True).click()
                page.get_by_role('button', name='停止本轮').click(timeout=10000)
                page.get_by_text('状态：已取消', exact=False).wait_for(timeout=10000)
                store.revoke(source['id'])
                page.get_by_text('这份回答引用的部分来源已失效，不应继续作为有效依据。', exact=True).wait_for(timeout=10000)
                page.screenshot(path=str(runtime_dir / 'p3-assistant.png'), full_page=True)
                assert 'CS 饰品' in page.get_by_role('button', name='选择对话', exact=True).inner_text()
                assert len(harness.sessions()) == 1
                page.get_by_role('button', name='选择对话', exact=True).click()
                page.screenshot(path=str(runtime_dir / 'p3-session-picker.png'), full_page=True)
                page.get_by_role('button', name='删除会话：CS 饰品', exact=True).click()
                page.get_by_role('button', name='取消', exact=True).click()
                check_input()
                assert page.get_by_text('哪些评论讨论 CS？', exact=True).is_visible()
                page.get_by_role('button', name='选择对话', exact=True).click()
                page.get_by_role('button', name='删除会话：CS 饰品', exact=True).click()
                page.get_by_role('button', name='确认删除', exact=True).click()
                check_input()
                page.get_by_text('哪些评论讨论 CS？', exact=True).wait_for(state='detached')
                page.reload()
                page.get_by_role('button', name='选择对话', exact=True).click()
                page.get_by_text('暂无历史对话', exact=True).wait_for()
                # Repeat create/delete transitions, including deletion of a nonselected session
                # while an old list response is deliberately held in flight.
                for _ in range(3):
                    created = []
                    for _ in range(2):
                        old = page.evaluate('location.hash')
                        page.get_by_role('button', name='新对话', exact=True).evaluate('(el) => { el.click(); el.click(); }')
                        page.wait_for_function('(old) => location.hash !== old', arg=old)
                        created.append(page.evaluate("new URLSearchParams(location.hash.split('?')[1]).get('session')"))
                        page.wait_for_function("!Array.from(document.querySelectorAll('button')).find(b => b.textContent === '新对话').disabled")
                    assert len(harness.sessions()) == 2
                    for selected in (created[0], created[1]):
                        page.get_by_role('button', name='选择对话', exact=True).click()
                        page.locator(f'[data-session-id="{selected}"]').get_by_role('button', name='新对话', exact=True).click()
                        page.wait_for_function('(id) => new URLSearchParams(location.hash.split("?")[1]).get("session") === id', arg=selected)
                    page.set_viewport_size({'width': 390, 'height': 844})
                    page.get_by_role('button', name='选择对话', exact=True).click()
                    bounds = page.locator('#session-picker').bounding_box()
                    assert bounds and bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= 390
                    page.screenshot(path=str(runtime_dir / 'p3-session-picker-mobile.png'), full_page=True)
                    page.get_by_role('button', name='选择对话', exact=True).click()
                    page.set_viewport_size({'width': 1280, 'height': 900})
                    page.evaluate('window.delayNextList = true; window.raceStats.captured = 0')
                    page.wait_for_function('window.raceStats.captured > 0', timeout=7000)
                    page.get_by_role('button', name='选择对话', exact=True).click()
                    page.locator(f'[data-session-id="{created[0]}"]').get_by_role('button', name='删除会话：新对话', exact=True).click()
                    page.get_by_role('button', name='确认删除', exact=True).click()
                    check_input()
                    page.locator(f'[data-session-id="{created[0]}"]').wait_for(state='detached')
                    assert page.evaluate("new URLSearchParams(location.hash.split('?')[1]).get('session')") == created[1]
                    page.get_by_role('button', name='选择对话', exact=True).click()
                    page.locator(f'[data-session-id="{created[1]}"]').get_by_role('button', name='删除会话：新对话', exact=True).click()
                    page.get_by_role('button', name='确认删除', exact=True).click()
                    check_input()
                    page.get_by_role('button', name='选择对话', exact=True).click()
                    page.get_by_text('暂无历史对话', exact=True).wait_for()
                    page.wait_for_timeout(2800)
                    assert not harness.sessions()
                    assert page.locator('[data-session-id]').count() == 0
                # Actual mouse click/keyboard input/send after deletion, without refresh.
                page.get_by_role('button', name='选择对话', exact=True).click()
                page.get_by_label('输入问题').click()
                page.keyboard.insert_text('停止测试')
                page.get_by_role('button', name='发送', exact=True).click()
                page.get_by_role('button', name='停止本轮').click(timeout=10000)
                page.get_by_text('状态：已取消', exact=False).wait_for(timeout=10000)
                assert len(harness.sessions()) == 1
                page.goto(f'http://127.0.0.1:{port}/#assistant?session={first_session}')
                page.wait_for_function("new URLSearchParams(location.hash.split('?')[1]).get('session') === ''", timeout=10000)
                page.screenshot(path=str(runtime_dir / 'p3-session-races.png'), full_page=True)
                assert not errors, errors
                browser.close()
            output = {'status': 'passed', 'model': 'scripted_test_double', 'checks': ['ask', 'cited_answer', 'comment_highlight', 'post_context', 'evidence_reload', 'return_to_conversation', 'conversation_reload', 'cancel', 'invalidated_answer_warning', 'topic_title', 'delete_dismiss', 'delete_confirm', 'deleted_session_reload', 'delayed_list_after_create', 'double_click_new', 'double_click_send', 'three_repeated_delete_cycles', 'nonselected_delete', 'stale_list_after_delete', 'deleted_url_recovery', 'switch_sessions', 'mobile_picker_bounds', 'cancel_restores_input_focus', 'each_delete_mouse_and_keyboard_input', 'send_after_delete'], 'javascript_errors': errors}
            destination = ROOT / 'docs/p3'; destination.mkdir(exist_ok=True)
            (destination / 'ui-validation.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(output))
        finally:
            server.should_exit = True; thread.join(timeout=5); sock.close()


if __name__ == '__main__':
    main()
