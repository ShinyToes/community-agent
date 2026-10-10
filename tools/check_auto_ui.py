"""Automatic assistant UI smoke, isolated model/crawler fixtures."""
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
from community_research.agent.collection import CollectionService
from community_research.api.router import create_router
from community_research.knowledge import KnowledgeStore

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('auto_fixtures',ROOT/'tests/research/test_automatic.py')
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)

def main():
    with tempfile.TemporaryDirectory(prefix='auto-ui-',dir=ROOT/'.runtime') as temporary:
        root=Path(temporary)
        (root/'.env.research').write_text('RESEARCH_BASE_URL=http://test\nRESEARCH_API_KEY=test\nRESEARCH_MODEL=test\n')
        count=0
        def model():
            nonlocal count
            count+=1
            if count in (1,3,4): return fixture.fx.ScriptModel([fixture.strategy(route='local' if count==4 else 'online',post_limit=1)])
            return fixture.fx.valid_model()
        h=Harness(KnowledgeStore(root),model);a=fixture.fx.Adapter(root)
        service=CollectionService(h,a);session=h.create_session()['id']
        old=asyncio.run(service.propose(session,'旧计划不能自动启动',['CS']))
        app=FastAPI();app.include_router(create_router(h,a))
        @app.get('/api/crawler/status')
        def status(): return {'status':'idle','platform':None,'crawler_type':None,'start_time':None}
        web=ROOT/'MediaCrawler/api/webui'
        app.mount('/assets',StaticFiles(directory=web/'assets'));app.mount('/logos',StaticFiles(directory=web/'logos'))
        @app.get('/')
        def index(): return FileResponse(web/'index.html')
        server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=0,log_level='error'))
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);thread.start()
        try:
            for _ in range(100):
                if server.started: break
                time.sleep(.05)
            assert server.started
            with sync_playwright() as p:
                browser=p.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1280,'height':900})
                errors=[];submitted=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.on('request',lambda r:submitted.append(r.post_data_json) if r.method=='POST' and r.url.endswith('/messages') else None)
                page.add_init_script("localStorage.setItem('mediacrawler_env_checked','true');localStorage.setItem('mediacrawler_license_accepted','true')")
                page.add_init_script('''
                    const originalFetch = window.fetch.bind(window);
                    window.holdResearchConfig = !sessionStorage.getItem('test-config-delay-used');
                    window.fetch = async (...args) => {
                        const response = await originalFetch(...args);
                        if (String(args[0]).endsWith('/api/research/config') && window.holdResearchConfig) {
                            window.holdResearchConfig = false;
                            sessionStorage.setItem('test-config-delay-used', 'true');
                            await new Promise(resolve => {window.releaseResearchConfig = resolve;});
                        }
                        return response;
                    };
                ''')
                page.goto(f'http://127.0.0.1:{port}/#assistant?session={session}')
                page.wait_for_function('typeof window.releaseResearchConfig === "function"')
                page.get_by_label('输入问题').fill('收集一些CS帖子')
                expect(page.get_by_role('button',name='发送',exact=True)).to_be_disabled(timeout=1000)
                page.evaluate('window.releaseResearchConfig()')
                page.get_by_text('历史待确认计划（未执行）',exact=True).wait_for()
                assert page.locator('footer').count()==0
                expect(page.locator('header button').filter(has_text='1.')).not_to_be_visible()
                assert page.get_by_role('radio').count()==0 and page.get_by_role('spinbutton').count()==0
                assert page.get_by_role('button',name='确认计划并采集').count()==0
                page.get_by_label('输入问题').fill('收集一些CS帖子')
                page.get_by_role('button',name='发送',exact=True).evaluate('(e)=>{e.click();e.click()}')
                page.get_by_text('帖子讨论 CS 饰品。',exact=True).wait_for(timeout=15000)
                assert submitted==[{'text':'收集一些CS帖子'}] and len(a.calls)==1
                expect(page.locator('[data-source-kind="post"]')).to_contain_text('回复数（采集时）：12')
                assert service.get(old['id'])['status']=='proposed'
                page.reload();page.get_by_text('帖子讨论 CS 饰品。',exact=True).wait_for()
                a.waiting=True
                page.get_by_label('输入问题').fill('继续采集CS')
                page.get_by_role('button',name='发送',exact=True).click()
                page.get_by_text('请在打开的贴吧窗口完成登录，完成后自动继续。',exact=True).wait_for()
                page.get_by_role('button',name='停止本轮',exact=True).click()
                page.get_by_text('已停止',exact=True).wait_for()
                page.get_by_label('输入问题').fill('只看已有数据中的CS，不要联网')
                page.get_by_role('button',name='发送',exact=True).click()
                expect(page.get_by_text('帖子讨论 CS 饰品。',exact=True)).to_have_count(2,timeout=15000)
                assert len(a.calls)==2 and a.owner is None
                page.get_by_text('高级',exact=True).click()
                page.get_by_role('link',name='高级手动采集',exact=True).click()
                expect(page.get_by_label('输入问题')).not_to_be_visible()
                page.get_by_role('link',name='社区研究助手',exact=True).click()
                try:
                    expect(page.get_by_text('帖子讨论 CS 饰品。',exact=True)).to_have_count(2,timeout=10000)
                except Exception:
                    print(json.dumps({'url':page.url,'selected':page.evaluate("localStorage.getItem('research-session')"),'errors':errors,'body':page.locator('body').inner_text()[:1800]},ensure_ascii=True))
                    raise
                first_job=next(job for job in service.list(session) if job['question']=='收集一些CS帖子' and job['status']=='completed')
                post=h.tools.call('search_posts',{'source_ids':first_job['progress']['source_ids'],'limit':1})['items'][0]
                preview=next(sn for sn in post['snippets'] if sn['field']=='body')
                progress=first_job['progress']
                progress['candidate_review']={'status':'ok','items':[{'snapshot_id':post['snapshot_id'],
                    'post_id':post['external_id'],'entity_id':post['entity_id'],'status':'reviewed',
                    'label':'relevant','reason':'初筛相关','quote':preview['quote'],
                    'evidence_ids':[preview['evidence_id']],'title':'CS 饰品'}],
                    'counts':{'relevant':1,'irrelevant':0,'uncertain':0,'unreviewed':0}}
                service._update(first_job['id'],progress=progress)
                page.reload()
                page.get_by_text('执行详情',exact=True).first.click()
                page.get_by_text('逐帖筛选依据',exact=True).click()
                page.get_by_label('更正理由').fill('人工核对后排除')
                page.get_by_role('button',name='改为无关').click()
                page.get_by_text('筛选依据已更正；原回答尚未重新生成，请继续提问以获得更新结论。',exact=True).wait_for()
                assert service.get(first_job['id'])['progress']['candidate_review']['counts']['irrelevant']==1
                page.get_by_label('输入问题').scroll_into_view_if_needed()
                page.screenshot(path=str(ROOT/'.runtime/automatic-assistant.png'),full_page=True)
                assert not errors,errors
                browser.close()
            report={'status':'passed','mode':'isolated_model_and_crawler','checks':['no_mode_controls','no_budget_form','no_confirmation_button','natural_language_auto_execution','duplicate_send_once','old_plan_not_run','metadata_and_evidence','reload','login_wait','cancel','local_only_no_crawl','input_after_cancel','advanced_crawler_and_return','wait_for_capabilities_before_send','promotional_footer_hidden','header_banner_hidden','user_review_correction','correction_counts_and_stale_answer'],'javascript_errors':errors}
            destination=ROOT/'docs/p5';destination.mkdir(exist_ok=True)
            (destination/'ui-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(report))
        finally:
            server.should_exit=True;thread.join(timeout=5);sock.close()

if __name__=='__main__': main()
