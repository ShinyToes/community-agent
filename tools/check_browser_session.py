"""Real local Chromium/process check; all platform operations are offline fixtures."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'MediaCrawler'))


async def worker():
    import config
    from api import task_store
    from media_platform.tieba.core import TieBaCrawler
    from media_platform.tieba.login import BaiduTieBaLogin
    task_store.DATA_DIR = Path(os.environ['BROWSER_TEST_ROOT'])/'data'
    config.ENABLE_IP_PROXY = config.ENABLE_CDP_MODE = False
    events = Path(os.environ['BROWSER_TEST_ROOT'])/'events.jsonl'
    def record(value):
        with events.open('a',encoding='utf-8') as f:
            f.write(json.dumps(value)+'\n')
    crawler = TieBaCrawler()
    async def launch(chromium,*args,**kwargs):
        browser = await chromium.launch(headless=True)
        record({'event':'launch','pid':os.getpid(),'driver_pid':chromium._impl_obj._connection._transport._proc.pid})
        return await browser.new_context()
    async def noop(): pass
    async def navigate(): await crawler.context_page.goto('about:blank')
    class Client:
        async def pong(self,**kwargs): return os.environ.get('BROWSER_TEST_MODE')!='login_cancel'
    async def login(self):
        await asyncio.sleep(120)
    BaiduTieBaLogin.begin=login
    async def client(*args): return Client()
    async def branch():
        record({'event':'branch','query':config.KEYWORDS,'kind':config.CRAWLER_TYPE,'context':id(crawler.browser_context),'page':id(crawler.context_page),'path':config.SAVE_DATA_PATH})
        if config.KEYWORDS=='wait':
            await asyncio.sleep(120)
        if config.KEYWORDS=='crash':
            os._exit(7)
        await crawler.context_page.goto('about:blank#'+config.CRAWLER_TYPE)
        path = Path(config.SAVE_DATA_PATH)/'result.json'
        path.write_text(json.dumps({'query':config.KEYWORDS,'ids':config.TIEBA_SPECIFIED_ID_LIST,'notes':config.CRAWLER_MAX_NOTES_COUNT,'comments':config.ENABLE_GET_COMMENTS}),encoding='utf-8')
    crawler.launch_browser=launch
    crawler._inject_anti_detection_scripts=noop
    crawler._navigate_to_tieba_via_baidu=navigate
    crawler.create_tieba_client=client
    crawler.search=crawler.get_specified_notes=branch
    try:
        await crawler.start()
    finally:
        record({'event':'closed'})


async def main():
    from api import task_store
    from api.services.crawler_manager import CrawlerManager
    from api.research_bridge import CollectionAdapter
    reports=[]
    for mode in ('complete','cancel','login_cancel','crash'):
        with tempfile.TemporaryDirectory(prefix='browser-session-',dir=ROOT/'.runtime') as temporary:
            root=Path(temporary)
            manager=CrawlerManager()
            manager._build_command=lambda request: ['uv','run','python',str(Path(__file__).resolve()),'--worker']
            with patch.object(task_store,'DATA_DIR',root/'data'),patch.dict(os.environ,{'BROWSER_TEST_ROOT':str(root),'BROWSER_TEST_MODE':mode}),patch('api.research_bridge.crawler_manager',manager):
                adapter=CollectionAdapter()
                assert await adapter.reserve('test-owner')
                ids=[]
                try:
                    branches=[('one',None),('two',None),('three',None),(None,['123']),(None,['456'])] if mode=='complete' else [(('wait' if mode=='cancel' else 'crash'),None)]
                    for query,post_ids in branches:
                        ident=await adapter.start('test-owner',query=query,post_ids=post_ids,notes=1,comments=2)
                        assert ident
                        ids.append(ident)
                        for _ in range(200):
                            state=adapter.status(ident)
                            if mode=='login_cancel' and state.get('waiting_login'): break
                            if mode=='cancel' and (root/'events.jsonl').exists() and 'branch' in (root/'events.jsonl').read_text(): break
                            if state['status'] not in task_store.ACTIVE: break
                            await asyncio.sleep(.1)
                        else: raise AssertionError('branch timeout')
                        if mode=='complete': assert state['status']=='completed',state
                    if mode=='crash':
                        assert state['status']=='failed',state
                        assert await adapter.start('test-owner',query='no-restart',notes=1) is None
                    await adapter.stop('test-owner')
                    assert manager.process.poll() is not None
                    events=[json.loads(line) for line in (root/'events.jsonl').read_text().splitlines()]
                    assert len([e for e in events if e['event']=='launch'])==1
                    driver_pid=next(e['driver_pid'] for e in events if e['event']=='launch')
                    for _ in range(30):
                        if not task_store.process_alive(driver_pid): break
                        await asyncio.sleep(.1)
                    assert not task_store.process_alive(driver_pid), 'browser driver leaked'
                    executed=[e for e in events if e['event']=='branch']
                    if executed:
                        assert len({e['context'] for e in executed})==len({e['page'] for e in executed})==1
                    if mode=='complete':
                        assert len(executed)==5 and len({e['path'] for e in executed})==5
                        assert all(task_store.load(i)['status']=='completed' for i in ids)
                    if mode in ('cancel','login_cancel'): assert task_store.load(ids[0])['status']=='stopped'
                    if mode not in ('crash','login_cancel'): assert events[-1]['event']=='closed'
                    reports.append({'mode':mode,'browser_launches':1,'branches':len(executed),'process_exited':True})
                finally:
                    await adapter.stop('test-owner')
                    await adapter.release('test-owner')
                    if manager._read_task: await asyncio.gather(manager._read_task,return_exceptions=True)
    (ROOT/'docs/p5/browser-session-validation.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')
    print(json.dumps(reports))


if __name__=='__main__':
    asyncio.run(worker() if '--worker' in sys.argv else main())
