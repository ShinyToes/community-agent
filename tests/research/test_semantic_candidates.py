"""Online candidates must survive changes in wording, without bypassing reads."""
import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('automatic_fixtures', Path(__file__).with_name('test_automatic.py'))
fx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fx)


@pytest.mark.parametrize('question,title,body', [
    ('收集动漫打分贴', '给这些角色排个座次', '请为鸣人和路飞分别给出一到十分，并说明理由。'),
    ('找手机续航体验', '通勤一天下来还剩多少电', '这款手机早上满电，晚上到家还剩三成。'),
    ('看看餐厅服务评价', '这顿饭等得我没脾气', '点菜后等了一个小时，叫服务员也没人回应。'),
])
def test_nonliteral_candidates_are_available_but_require_read(tmp_path, question, title, body):
    async def run():
        h, adapter, service, session, _ = fx.prepare(tmp_path)
        original = adapter.start
        async def start(owner, **args):
            ident = await original(owner, **args)
            path = adapter.paths[ident][0]
            rows = json.loads(path.read_text(encoding='utf-8'))
            rows[0].update(title=title, desc=body)
            path.write_text(json.dumps(rows), encoding='utf-8')
            return ident
        adapter.start = start
        def read(messages):
            candidates = json.loads(messages[-1]['content'])['collection_candidates_untrusted']
            assert candidates['coverage']['total'] == 1
            assert candidates['items'][0]['matched_fields'] == []
            snippet = next(s for s in candidates['items'][0]['snippets'] if s['field'] == 'body')
            assert snippet['quote'] == body
            return {'action':'tool','name':'read_evidence','arguments':{'evidence_ids':[snippet['evidence_id']]}}
        def answer(messages):
            result = json.loads(messages[-1]['content'])['tool_result_untrusted']
            return {'action':'answer','outcome':'answered','paragraphs':[{'text':body,'evidence_ids':[result['items'][0]['evidence_id']]}],'limitations':[]}
        models = iter([fx.fx.ScriptModel([fx.strategy(queries=[question],post_limit=1)]), fx.fx.ScriptModel([read,answer])])
        h.model_factory = lambda: next(models)
        job = service.start_automatic(session, question)
        await service.tasks[job['id']]
        result = service.get(job['id'])
        assert result['status'] == 'completed', result
        record = h.run(result['answer_run_id'])
        assert record['usage']['tool_calls'] == 2
        assert '在线采集' in record['plan']['domain']
        assert record['answer']['paragraphs'][0]['text'] == body
    asyncio.run(run())


def test_semantic_scope_validation_and_unchanged_budget():
    scope = dict(subject_scope='用户指定领域内的对象及子类',content_intent='邀请参与者评价',include='有实际互动或评分依据',exclude='无关闲聊',query_directions=['核心概念','对象子类','互动表达'])
    result = fx.validate_strategy(fx.strategy(semantic_scope=scope), '找一些相关讨论')
    assert result['post_limit'] == 20 and not result['expanded']
    with pytest.raises(fx.KnowledgeError):
        fx.validate_strategy(fx.strategy(semantic_scope={**scope,'query_directions':['不对应']}), '找一些')


@pytest.mark.parametrize('label,quote,expect_comments', [
    ('relevant','CS 饰品讨论',True),
    ('uncertain','CS 饰品讨论',False),
    ('irrelevant','CS 饰品讨论',False),
    ('relevant','编造出来的原文',False),
])
def test_comment_selection_uses_review_and_rejects_invented_quote(tmp_path,label,quote,expect_comments):
    async def run():
        h, adapter, service, session, _ = fx.prepare(tmp_path)
        scope = dict(subject_scope='游戏虚拟物品',content_intent='讨论价格与交易',include='实际物品讨论',exclude='动物话题',query_directions=['物品讨论'])
        decision = fx.strategy(queries=['虚拟物品价格'],comments=True,semantic_scope=scope)
        reviewer = fx.fx.ScriptModel([{'items':[{'post_id':'123','label':label,'reason':'核对讨论对象','quote':quote}]}])
        comment_reviewer = fx.fx.ScriptModel([{'items':[{'comment_id':'456','label':'relevant',
            'reason':'评论讨论饰品价格','quote':'CS 饰品价格变化'}]}])
        models = iter([fx.fx.ScriptModel([decision]),reviewer] + ([comment_reviewer] if expect_comments else []) + [fx.fx.valid_model()])
        h.model_factory = lambda: next(models)
        job = service.start_automatic(session,'收集游戏物品价格讨论和评论')
        await service.tasks[job['id']]
        result = service.get(job['id'])
        assert result['status']=='completed',result
        assert any(c['post_ids'] for c in adapter.calls) == expect_comments
        assert sum(c['notes'] for c in adapter.calls)<=20
        review = result['progress']['candidate_review']
        assert review['status'] == ('unavailable' if quote=='编造出来的原文' else 'ok')
        if expect_comments:
            assert result['progress']['comment_review']['counts']['relevant']==1
        assert result['progress']['planner_calls']==(3 if expect_comments else 2)
    asyncio.run(run())


def test_comment_review_cannot_use_parent_quote_as_comment_evidence(tmp_path):
    from community_research.agent.review import review_comments
    async def run():
        h,_,service,session,_=fx.prepare(tmp_path)
        path=tmp_path/'comments.json'
        path.write_text(json.dumps([{'note_id':'1','title':'CS 饰品讨论','desc':'原帖观点是市场承压'},
            {'comment_id':'c1','note_id':'1','content':'这次降得太快'}],ensure_ascii=False),encoding='utf-8')
        source=h.store.register_source(path,platform='tieba');h.store.import_source(source['id'])
        job=await service.propose(session,'看评论',['CS'])
        progress=job['progress'];progress['strategy']=fx.strategy(comments=True,semantic_scope=dict(
            subject_scope='CS饰品',content_intent='价格讨论',include='相关评论',exclude='无关',query_directions=['核心']))
        result=h.tools.call('search_comments',{'source_ids':[source['id']],'limit':20})
        h.model_factory=lambda: fx.fx.ScriptModel([{'items':[{'comment_id':'c1','label':'relevant',
            'reason':'错用父帖','quote':'原帖观点是市场承压'}]}])
        await review_comments(service,job['id'],progress,result)
        assert progress['comment_review']['status']=='unavailable'
        assert progress['comment_review']['items'][0]['status']=='unavailable'
    asyncio.run(run())
