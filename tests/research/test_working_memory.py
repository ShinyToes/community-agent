import asyncio
import importlib.util
import json
from pathlib import Path
import pytest

def fixture(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

fx=fixture('test_automatic')
hx=fixture('test_harness')


def add(store,name,rows):
    path=store.root/name
    path.write_text(json.dumps(rows,ensure_ascii=False),encoding='utf-8')
    source=store.register_source(path,platform='tieba')
    store.import_source(source['id'])
    return source['id']


def setup(tmp_path,rows):
    h,a,s,session=fx.fx.make(tmp_path)
    source=add(h.store,'posts.json',rows)
    scope=dict(subject_scope='本轮目标',content_intent='评分讨论',include='正文支持',exclude='无关内容',query_directions=['核心'])
    return h,s,session,source,fx.strategy(queries=['核心'],semantic_scope=scope)


def test_independent_reviews_budget_checkpoint_and_repeat(tmp_path):
    async def run():
        rows=[{'note_id':str(i),'title':f'独立对象{i}','desc':f'只属于对象{i}的正文'} for i in range(9)]
        h,s,session,source,strategy=setup(tmp_path,rows)
        job=await s.propose(session,'寻找评分讨论',['核心'])
        progress=job['progress'];progress.update(strategy=strategy,source_ids=[source])
        seen=[]
        class Model:
            async def complete(self,messages):
                assert len(messages)==2
                data=json.loads(messages[1]['content'])
                assert len(data['candidates_untrusted'])==1
                item=data['candidates_untrusted'][0]
                seen.append(item['external_id'])
                for other in rows:
                    if other['note_id']!=item['external_id']: assert other['desc'] not in messages[1]['content']
                return json.dumps({'items':[{'post_id':item['external_id'],'label':'relevant','reason':'本帖有评分依据','quote':item['snippets'][0]['quote']}]})
        h.model_factory=Model
        await s._review_candidates(job['id'],progress)
        assert len(seen)==8 and len(set(seen))==8
        assert progress['candidate_review']['counts']==dict(relevant=8,irrelevant=0,uncertain=0,unreviewed=1)
        assert progress['review_calls']==8
        await s._review_candidates(job['id'],progress)
        assert len(seen)==8
        assert s.get(job['id'])['progress']['candidate_review']['items']==progress['candidate_review']['items']
        assert h.tools.call('search_posts',{})['coverage']['total']==9
    asyncio.run(run())


def test_new_snapshot_is_rechecked(tmp_path):
    async def run():
        h,s,session,source,strategy=setup(tmp_path,[{'note_id':'1','title':'版本一','desc':'旧内容','last_modify_ts':1700000000000}])
        job=await s.propose(session,'评分讨论',['核心'])
        progress=job['progress'];progress.update(strategy=strategy,source_ids=[source])
        calls=[]
        class Model:
            async def complete(self,messages):
                item=json.loads(messages[-1]['content'])['candidates_untrusted'][0]
                calls.append(item['snapshot_id'])
                return json.dumps({'items':[dict(post_id='1',label='uncertain',reason='内容不足',quote=item['snippets'][0]['quote'])]})
        h.model_factory=Model
        await s._review_candidates(job['id'],progress)
        newer=add(h.store,'new.json',[{'note_id':'1','title':'版本二','desc':'新内容','last_modify_ts':1800000000000}])
        progress['source_ids'].append(newer)
        await s._review_candidates(job['id'],progress)
        assert len(calls)==2 and calls[0]!=calls[1]
        assert len(progress['candidate_review']['items'])==1
    asyncio.run(run())


def test_review_cannot_persist_revoked_evidence(tmp_path):
    async def run():
        h,s,session,source,strategy=setup(tmp_path,[{'note_id':'1','title':'评分','desc':'原文'}])
        job=await s.propose(session,'评分讨论',['核心'])
        progress=job['progress'];progress.update(strategy=strategy,source_ids=[source])
        class Model:
            async def complete(self,messages):
                h.store.revoke(source)
                return json.dumps({'items':[dict(post_id='1',label='relevant',reason='有依据',quote='评分')]})
        h.model_factory=Model
        await s._review_candidates(job['id'],progress)
        assert not progress['candidates']
        assert progress['candidate_review']['status']=='unavailable'
    asyncio.run(run())


def test_alias_hypotheses_keep_quotes_and_remain_candidates(tmp_path):
    async def run():
        rows=[{'note_id':'1','title':'称呼一','desc':'donk也被叫作小驴'},
              {'note_id':'2','title':'称呼二','desc':'这里说的小驴就是donk'}]
        h,s,session,source,strategy=setup(tmp_path,rows)
        strategy['target']='donk'
        job=await s.propose(session,'查donk',['donk'])
        progress=job['progress'];progress.update(strategy=strategy,source_ids=[source])
        class Model:
            async def complete(self,messages):
                item=json.loads(messages[-1]['content'])['candidates_untrusted'][0]
                quote=next(s['quote'] for s in item['snippets'] if '小驴' in s['quote'])
                return json.dumps({'items':[{'post_id':item['external_id'],'label':'relevant',
                    'reason':'明确说明称呼','quote':quote,'relations':[{'term':'小驴','kind':'alias',
                    'quote':quote,'reason':'原文明确指代'}]}]})
        h.model_factory=Model
        await s._review_candidates(job['id'],progress)
        relations=progress['relation_candidates']
        assert len(relations)==1 and relations[0]['status']=='corroborated_candidate'
        assert relations[0]['term']=='小驴' and len(relations[0]['supporting_snapshots'])==2
        assert len(relations[0]['evidence_ids'])==2
        assert s.get(job['id'])['progress']['relation_candidates']==relations
    asyncio.run(run())


def test_alias_without_target_in_quoted_evidence_is_rejected(tmp_path):
    async def run():
        h,s,session,source,strategy=setup(tmp_path,[{'note_id':'1','title':'称呼','desc':'小驴今天吃草'}])
        strategy['target']='donk'
        job=await s.propose(session,'查donk',['donk'])
        progress=job['progress'];progress.update(strategy=strategy,source_ids=[source])
        class Model:
            async def complete(self,messages):
                return json.dumps({'items':[{'post_id':'1','label':'relevant','reason':'猜测称呼',
                    'quote':'小驴今天吃草','relations':[{'term':'小驴','kind':'alias',
                    'quote':'小驴今天吃草','reason':'猜测'}]}]})
        h.model_factory=Model
        await s._review_candidates(job['id'],progress)
        assert not progress['relation_candidates']
        assert progress['candidate_review']['status']=='unavailable'
    asyncio.run(run())


def test_two_versions_of_one_post_do_not_corroborate_alias(tmp_path):
    async def run():
        h,s,session,source,strategy=setup(tmp_path,[{'note_id':'1','title':'称呼','desc':'donk也叫小驴'}])
        strategy['target']='donk'
        job=await s.propose(session,'查donk',['donk'])
        progress=job['progress'];progress.update(strategy=strategy,source_ids=[source])
        class Model:
            async def complete(self,messages):
                item=json.loads(messages[-1]['content'])['candidates_untrusted'][0]
                quote=next(sn['quote'] for sn in item['snippets'] if 'donk' in sn['quote'])
                return json.dumps({'items':[{'post_id':'1','label':'relevant','reason':'原文称呼',
                    'quote':quote,'relations':[{'term':'小驴','kind':'alias','quote':quote,'reason':'原文称呼'}]}]})
        h.model_factory=Model
        await s._review_candidates(job['id'],progress)
        newer=add(h.store,'new-alias.json',[{'note_id':'1','title':'称呼二','desc':'小驴就是donk'}])
        progress['source_ids'].append(newer)
        await s._review_candidates(job['id'],progress)
        relation=progress['relation_candidates'][0]
        assert len(relation['supporting_snapshots'])==2
        assert len(relation['supporting_entities'])==1
        assert relation['status']=='candidate'
    asyncio.run(run())


def test_compaction_can_reread_original_without_archiving_duplicate_text(tmp_path):
    ident=[]
    def read(messages):
        output=json.loads(messages[-1]['content'])['tool_result_untrusted']
        ident.append(output['items'][0]['snippets'][0]['evidence_id'])
        return {'action':'tool','name':'read_evidence','arguments':{'evidence_ids':[ident[0]]}}
    def other(messages):
        return {'action':'tool','name':'search_posts','arguments':{'all_terms':['没有匹配']}}
    def recover(messages):
        # The original tool response is gone, but its identity remains discoverable.
        assert 'CS 饰品讨论' not in str(messages)
        state=next(json.loads(m['content'])['working_memory'] for m in messages if m['content'].startswith('{"instruction":') and 'working_memory' in m['content'])
        assert ident[0] in state['available_evidence_ids']
        assert state['usage']['tool_calls']==3
        return {'action':'tool','name':'read_evidence','arguments':{'evidence_ids':[ident[0]]}}
    model=hx.ScriptModel([{'action':'tool','name':'search_posts','arguments':{'fields':['body']}},read,other,recover,hx.final_answer])
    h,_=hx.make(tmp_path,model)
    result=asyncio.run(hx.execute(h))
    assert result['status']=='completed',result
    with h.store.connection() as conn:
        steps=conn.execute('SELECT result_refs FROM research_working_steps').fetchall()
        assert len(steps)==4 and 'CS 饰品讨论' not in str([r[0] for r in steps])
    h.delete_session(result['session_id'])
    with h.store.connection() as conn:
        assert conn.execute('SELECT count(*) FROM research_working_steps').fetchone()[0]==0


def test_cancel_preserves_finished_single_post_notes(tmp_path):
    async def run():
        h,s,session,source,strategy=setup(tmp_path,[{'note_id':str(i),'title':f'对象{i}','desc':'评分'} for i in range(2)])
        job=await s.propose(session,'评分讨论',['核心'])
        progress=job['progress'];progress.update(strategy=strategy,source_ids=[source])
        started=asyncio.Event()
        calls=0
        class Model:
            async def complete(self,messages):
                nonlocal calls
                calls+=1
                item=json.loads(messages[-1]['content'])['candidates_untrusted'][0]
                if calls==2:
                    started.set()
                    await asyncio.sleep(30)
                return json.dumps({'items':[dict(post_id=item['external_id'],label='relevant',reason='评分依据',quote='评分')]})
        h.model_factory=Model
        task=asyncio.create_task(s._review_candidates(job['id'],progress))
        await started.wait()
        for _ in range(100):
            if s.get(job['id'])['progress'].get('candidate_review',{}).get('items'): break
            await asyncio.sleep(.01)
        task.cancel()
        await asyncio.gather(task,return_exceptions=True)
        assert len(s.get(job['id'])['progress']['candidate_review']['items'])==1
        assert h.tools.call('search_posts',{})['coverage']['total']==2
    asyncio.run(run())


def test_batch_is_reviewed_before_next_collection_branch(tmp_path):
    async def run():
        h,adapter,s,session=fx.fx.make(tmp_path)
        scope=dict(subject_scope='CS',content_intent='讨论',include='实际讨论',exclude='无关',query_directions=['一','二'])
        decision=fx.strategy(queries=['CS','饰品'],semantic_scope=scope)
        original=adapter.start
        calls=0
        async def start(owner,**args):
            nonlocal calls
            calls+=1
            if calls==2: assert s.get(owner)['progress']['candidate_review']['items']
            ident=await original(owner,**args)
            path=adapter.paths[ident][0]
            rows=json.loads(path.read_text(encoding='utf-8'))
            rows[0]['note_id']=str(calls)
            path.write_text(json.dumps(rows),encoding='utf-8')
            return ident
        adapter.start=start
        class Review:
            async def complete(self,messages):
                item=json.loads(messages[-1]['content'])['candidates_untrusted'][0]
                return json.dumps({'items':[dict(post_id=item['external_id'],label='relevant',reason='CS讨论',quote='CS 饰品讨论')]})
        models=iter([fx.fx.ScriptModel([decision]),Review(),Review(),fx.fx.valid_model()])
        h.model_factory=lambda:next(models)
        job=s.start_automatic(session,'收集CS讨论')
        await s.tasks[job['id']]
        result=s.get(job['id'])
        assert result['status']=='completed',result
        assert result['progress']['review_calls']==2
    asyncio.run(run())
