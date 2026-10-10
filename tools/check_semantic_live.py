"""Real model checks with isolated replay; never starts a real crawler."""
import asyncio
import importlib.util
import json
from pathlib import Path
import sqlite3
import uuid

from community_research.agent.model import ChatModel, parse_action
from community_research.agent.strategy import PROMPT, validate_strategy

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('collection_fixture',ROOT/'tests/research/test_collection.py')
fx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fx)


async def main():
    report = {'mode':'real_model_isolated_replay_no_live_crawl','plans':[]}
    for question in ['收集一些动漫打分贴','想看看玩家对最近游戏更新的实际体验','找一些关于手机续航的用户讨论']:
        raw = await ChatModel(ROOT).complete([{'role':'system','content':PROMPT},{'role':'user','content':question}])
        plan = validate_strategy(parse_action(raw),question)
        assert plan.get('semantic_scope') and len(plan['queries'])<=3
        report['plans'].append({'question':question,'plan':plan})
        print(json.dumps({'question':question,'queries':plan['queries'],'scope':plan['semantic_scope']},ensure_ascii=False),flush=True)
    # Replay actual user corpus in an isolated project, preserving the original.
    with sqlite3.connect(f'file:{ROOT.as_posix()}/.runtime/research/index.sqlite3?mode=ro',uri=True) as conn:
        progress = json.loads(conn.execute('SELECT progress FROM research_collections WHERE answer_run_id=?',('803eb61157b244f886abbbd7fd64bac4',)).fetchone()[0])
        rows = []
        for sid in progress['source_ids']:
            for (payload,) in conn.execute("SELECT DISTINCT p.payload FROM snapshots p JOIN occurrences o ON o.snapshot_id=p.id JOIN entities e ON e.id=p.entity_id WHERE o.source_id=? AND e.kind='post'",(sid,)):
                p = json.loads(payload)
                rows.append({'note_id':p['external_id'],'title':p['title'],'desc':p['body'],'note_url':p['source_url'],'publish_time':p['published_at_raw'],'tieba_name':p['forum_name']})
    work = ROOT/'.runtime'/('semantic-replay-'+uuid.uuid4().hex)
    h, adapter, service, session = fx.make(work)
    plan = json.loads(json.dumps(report['plans'][0]['plan']))
    # Supply original 13 candidates in one fixture task, avoiding new search noise.
    plan.update(queries=['replay'],post_limit=20,comments=False,route='online')
    plan['semantic_scope']['query_directions']=['原始采集结果回放']
    calls = 0
    def factory():
        nonlocal calls
        calls += 1
        return fx.ScriptModel([plan]) if calls==1 else ChatModel(ROOT)
    h.model_factory = factory
    original = adapter.start
    async def start(owner, **args):
        ident = await original(owner,**args)
        adapter.paths[ident][0].write_text(json.dumps(rows,ensure_ascii=False),encoding='utf-8')
        return ident
    adapter.start = start
    job = service.start_automatic(session,'收集一些动漫打分贴')
    await service.tasks[job['id']]
    job = service.get(job['id'])
    report['replay'] = {'status':job['status'],'error':job['error'],'review':job['progress'].get('candidate_review'),'run':h.run(job['answer_run_id']) if job['answer_run_id'] else None}
    destination = ROOT/'docs/p5/semantic-validation.json'
    destination.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'replay_status':job['status'],'review':report['replay']['review']},ensure_ascii=False),flush=True)
    assert job['status'] in ('completed','partial'),job['error']
    assert report['replay']['review']['status']=='ok'


if __name__=='__main__':
    asyncio.run(main())
