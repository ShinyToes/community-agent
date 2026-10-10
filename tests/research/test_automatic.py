import asyncio
import importlib.util
import json
from pathlib import Path
import pytest
from community_research.agent.strategy import resolve_award_question, validate_strategy
from community_research.knowledge import KnowledgeError

spec=importlib.util.spec_from_file_location('collection_fixtures',Path(__file__).with_name('test_collection.py'))
fx=importlib.util.module_from_spec(spec); spec.loader.exec_module(fx)

def strategy(**changes):
    return dict(task='lookup',route='online',target='CS',queries=['CS','CS 饰品','饰品 CS'],summary='正在查找相关讨论',clarification='',comments=False,expanded=False,expansion_quote='',post_limit=None,time_range='未限定',dimensions=[],**{}) | changes

def prepare(tmp_path, decision=None, **kwargs):
    h,a,s,session=fx.make(tmp_path,**kwargs)
    planner=fx.ScriptModel([decision or strategy()])
    count=0
    def factory():
        nonlocal count
        count+=1
        return planner if count==1 else fx.valid_model()
    h.model_factory=factory
    return h,a,s,session,planner

def test_auto_default_total_and_no_confirmation(tmp_path):
    async def run():
        h,a,s,session,_=prepare(tmp_path)
        job=s.start_automatic(session,'收集一些CS帖子')
        assert job['status']=='running'
        with pytest.raises(KnowledgeError,match='session_busy'): s.start_automatic(session,'重复')
        await s.tasks[job['id']]
        result=s.get(job['id'])
        assert result['status']=='completed',result
        assert sum(c['notes'] for c in a.calls)==20 and len(a.calls)==3
        assert result['progress']['planner_calls']==1 and result['answer_run_id']
        yields=[branch['yield'] for branch in result['progress']['branches'] if branch['stage']=='posts']
        assert len(yields)==3 and sum(y['requested_posts'] for y in yields)==20
        assert yields[0]['new_snapshots']>=1
        assert yields[1]['repeated_snapshots']>=1
        assert all(y['elapsed_seconds']>=0 for y in yields)
        assert '已按授权' in str(h.run(result['answer_run_id'])['answer'])
    asyncio.run(run())

def test_local_prohibition_overrides_online_and_no_auto_old_plan(tmp_path):
    async def run():
        h,a,s,session,_=prepare(tmp_path)
        old=await s.propose(session,'旧计划',['CS'])
        job=s.start_automatic(session,'只看已有数据中的CS，不要联网')
        await s.tasks[job['id']]
        assert not a.calls and not a.owner
        assert s.get(old['id'])['status']=='proposed'
        assert s.get(job['id'])['progress']['strategy']['route']=='local'
    asyncio.run(run())

def test_comment_detail_reads_share_budget(tmp_path):
    async def run():
        h,a,s,session,_=prepare(tmp_path,strategy(comments=True,task='reputation'))
        job=s.start_automatic(session,'玩家如何评价CS饰品')
        await s.tasks[job['id']]
        assert s.get(job['id'])['status']=='completed',s.get(job['id'])
        assert any(c['post_ids'] for c in a.calls)
        assert sum(c['notes'] for c in a.calls)<=20
        assert a.calls[-1]['comments']==20
    asyncio.run(run())

@pytest.mark.parametrize('text,quote,expected',[('多找一些CS帖子','多找一些',40),('CS帖子','多找一些',20),('CS帖子','CS',20),('扩大到最近三个月','扩大到最近三个月',20)])
def test_expansion_requires_matching_quantity_request(text,quote,expected):
    result=validate_strategy(strategy(expanded=True,expansion_quote=quote),text)
    assert result['post_limit']==expected

def test_clarification_does_not_crawl_or_answer_with_claims(tmp_path):
    async def run():
        h,a,s,session,_=prepare(tmp_path,strategy(route='clarify',queries=[],target='',clarification='你说的是哪款游戏？'))
        job=s.start_automatic(session,'这游戏最近口碑如何')
        await s.tasks[job['id']]
        result=s.get(job['id'])
        assert result['status']=='waiting_user' and not a.calls
        assert h.run(result['answer_run_id'])['answer']['paragraphs'][0]['text']=='你说的是哪款游戏？'
    asyncio.run(run())

def test_auto_route_observes_local_evidence(tmp_path):
    async def run():
        h,a,s,session,planner=prepare(tmp_path,strategy(route='auto'))
        planner.steps=iter([strategy(route='auto'),{'route':'local','reason':'用户只追问当前资料'}])
        job=s.start_automatic(session,'刚才这些CS帖子说明什么')
        await s.tasks[job['id']]
        result=s.get(job['id'])
        assert result['progress']['strategy']['route']=='local' and not a.calls
        assert 'previews_untrusted' in planner.messages[-1]['content']
    asyncio.run(run())

def test_immediate_cancel_and_planning_cancel(tmp_path):
    async def run():
        h,a,s,session,_=prepare(tmp_path)
        job=s.start_automatic(session,'CS')
        await s.cancel(job['id'])
        assert s.get(job['id'])['status']=='cancelled' and not a.calls
        class Slow:
            async def complete(self,messages): await asyncio.sleep(30)
        h.model_factory=Slow
        job=s.start_automatic(session,'CS')
        await asyncio.sleep(.02)
        with pytest.raises(KnowledgeError,match='session_busy'): h.delete_session(session)
        await s.cancel(job['id'])
        assert not a.calls and s.get(job['id'])['status']=='cancelled'
    asyncio.run(run())

def test_explicit_small_limit_is_not_multiplied_by_queries(tmp_path):
    async def run():
        h,a,s,session,_=prepare(tmp_path,strategy(post_limit=1))
        job=s.start_automatic(session,'CS只采一帖')
        await s.tasks[job['id']]
        assert len(a.calls)==1 and a.calls[0]['notes']==1
    asyncio.run(run())

def test_bounded_alias_probe_keeps_original_target_and_budget(tmp_path):
    async def run():
        scope=dict(subject_scope='CS选手donk',content_intent='寻找选手讨论',include='确实指向选手',
                   exclude='动物和养殖',query_directions=['正式名称'])
        h,a,s,session,_=prepare(tmp_path)
        original=a.start
        async def start(owner, **args):
            ident=await original(owner,**args)
            path=a.paths[ident][0]
            if args.get('query')=='donk':
                rows=[{'note_id':'1','title':'CS donk称呼一','desc':'donk也被叫作小驴'},
                      {'note_id':'2','title':'CS donk称呼二','desc':'这里的小驴就是donk'}]
            else:
                rows=[{'note_id':'3','title':'养殖小驴','desc':'小驴今天吃草'}]
            path.write_text(json.dumps(rows,ensure_ascii=False),encoding='utf-8')
            return ident
        a.start=start
        decision=strategy(target='donk',queries=['donk'],semantic_scope=scope,comments=False)
        planner=fx.ScriptModel([decision])
        class Review:
            async def complete(self,messages):
                item=json.loads(messages[-1]['content'])['candidates_untrusted'][0]
                body=next(sn['quote'] for sn in item['snippets'] if sn['field']=='body')
                relevant=item['external_id'] in ('1','2')
                row={'post_id':item['external_id'],'label':'relevant' if relevant else 'irrelevant',
                     'reason':'按目标核对','quote':body}
                if relevant:
                    row['relations']=[{'term':'小驴','kind':'alias','quote':body,'reason':'原文称呼'}]
                return json.dumps({'items':[row]},ensure_ascii=False)
        count=0
        def factory():
            nonlocal count
            count+=1
            return planner if count==1 else Review() if count<=4 else fx.valid_model()
        h.model_factory=factory
        job=s.start_automatic(session,'到贴吧查找donk的讨论')
        await s.tasks[job['id']]
        result=s.get(job['id'])
        assert result['status']=='completed',result
        assert [c['query'] for c in a.calls]==['donk','小驴']
        assert sum(c['notes'] for c in a.calls)==20
        probe=result['progress']['branches'][1]
        assert probe['exploration']['target']=='donk' and probe['exploration']['kind']=='alias_probe'
        assert probe['yield']['new_relevant']==0
        assert result['progress']['relation_candidates'][0]['status']=='corroborated_candidate'
        assert h.run(result['answer_run_id'])['answer_available']
    asyncio.run(run())

def test_invalid_plan_gets_one_repair_no_network(tmp_path):
    async def run():
        h,a,s,session,planner=prepare(tmp_path)
        planner.steps=iter([{'route':'online'},{'route':'online'}])
        job=s.start_automatic(session,'CS')
        await s.tasks[job['id']]
        result=s.get(job['id'])
        assert result['error']=='invalid_task_strategy' and not a.calls
        assert result['progress']['planner_calls']==2
    asyncio.run(run())

def test_semantic_cache_and_source_revocation(tmp_path):
    from community_research.knowledge.search import SearchService
    from community_research.knowledge import KnowledgeStore
    store=KnowledgeStore(tmp_path)
    file=tmp_path/'posts.json'; file.write_text(json.dumps([{'note_id':'1','title':'库存抛售','desc':'玩家集中出售库存，市场承压'}]),encoding='utf-8')
    source=store.register_source(file,platform='tieba');store.import_source(source['id'])
    tools=SearchService(store)
    class Embeddings:
        configured=True
        identity='fixture'
        calls=[]
        def vectors(self,texts):
            self.calls.append(texts)
            return [[1.,0.] for _ in texts]
    embedder=Embeddings(); tools.embedder=embedder
    result=tools.call('hybrid_search',{'query':'价格下跌原因'})
    assert result['items'] and result['coverage']['semantic_available']
    evidence=result['items'][0]['snippets'][0]['evidence_id']
    assert tools.call('read_evidence',{'evidence_ids':[evidence]})['items']
    tools.call('hybrid_search',{'query':'价格下跌原因'})
    assert len(embedder.calls[-1])==1
    store.revoke(source['id'])
    with store.connection() as conn: assert conn.execute('SELECT COUNT(*) FROM semantic_vectors').fetchone()[0]==0
    assert tools.call('read_evidence',{'evidence_ids':[evidence]})['error']

def test_semantic_unconfigured_reports_literal_fallback(tmp_path):
    h,_,_,_,_=prepare(tmp_path)
    file=tmp_path/'posts.json';file.write_text(json.dumps([{'note_id':'1','title':'CS','desc':'CS'}]),encoding='utf-8')
    h.store.import_source(h.store.register_source(file,platform='tieba')['id'])
    class NoneConfigured: configured=False
    h.tools.embedder=NoneConfigured()
    result=h.tools.call('hybrid_search',{'query':'CS'})
    assert result['coverage']['retrieval']=='literal_fallback' and not result['coverage']['semantic_available']

def test_fastembed_backend_uses_local_query_and_passage_paths(tmp_path, monkeypatch):
    import numpy as np
    from community_research.knowledge import semantic
    (tmp_path / '.env.research').write_text('RESEARCH_EMBEDDING_BACKEND=fastembed\n', encoding='utf-8')
    calls = []
    class LocalModel:
        def query_embed(self, query):
            calls.append(('query', query))
            yield np.array([1., 0.])
        def embed(self, passages):
            calls.append(('passages', passages))
            yield from (np.array([0., 1.]) for _ in passages)
    monkeypatch.setattr(semantic, '_local_model', lambda model, cache: LocalModel())
    embedder = semantic.Embedder(tmp_path)
    assert embedder.configured and embedder.model == 'BAAI/bge-small-zh-v1.5'
    assert embedder.vectors(['价格原因', '库存抛售']) == [[1., 0.], [0., 1.]]
    assert calls == [('query', '价格原因'), ('passages', ['库存抛售'])]

def test_evidence_exposes_post_stats_without_comment_collection(tmp_path):
    h,_,_,_,_=prepare(tmp_path)
    file=tmp_path/'posts.json';file.write_text(json.dumps([{'note_id':'1','title':'评分帖','desc':'给角色评分','total_replay_num':25,'publish_time':'2026-09-21 12:00:00'}]),encoding='utf-8')
    h.store.import_source(h.store.register_source(file,platform='tieba')['id'])
    hit=h.tools.call('search_posts',{'all_terms':['评分']})['items'][0]
    item=h.tools.call('read_evidence',{'evidence_ids':[hit['snippets'][0]['evidence_id']]})['items'][0]
    assert item['post_stats']['reply_count']==25 and item['post_stats']['published_at']=='2026-09-21 12:00:00'

def test_source_deleted_during_embedding_is_not_resurrected(tmp_path):
    from community_research.knowledge.search import SearchService
    from community_research.knowledge import KnowledgeStore
    store=KnowledgeStore(tmp_path);path=tmp_path/'p.json'
    path.write_text(json.dumps([{'note_id':'1','title':'内容','desc':'文本'}]),encoding='utf-8')
    source=store.register_source(path,platform='tieba');store.import_source(source['id'])
    tools=SearchService(store)
    class DeletingEmbedder:
        configured=True;identity='delete-test'
        def vectors(self,texts):
            store.revoke(source['id'])
            return [[1.,0.] for _ in texts]
    tools.embedder=DeletingEmbedder()
    result=tools.call('hybrid_search',{'query':'相似内容'})
    assert not result['items']
    with store.connection() as conn: assert conn.execute('SELECT COUNT(*) FROM semantic_vectors').fetchone()[0]==0

@pytest.mark.parametrize('vectors',[[[float('nan')]],[[0.,0.]],[[1e308,1e308]],[[1.],[1.,2.]]])
def test_invalid_vectors_rejected(vectors):
    from community_research.knowledge.semantic import validate_vectors
    with pytest.raises(KnowledgeError): validate_vectors(vectors,len(vectors))

@pytest.mark.parametrize('question,route',[('到贴吧收集打分帖','online'),('不要到贴吧收集，只看已有数据','local'),('不要只查本地，请联网搜索打分帖','online')])
def test_explicit_tool_instruction_wins(question,route):
    assert validate_strategy(strategy(route='auto'),question)['route']==route

@pytest.mark.parametrize('instruction',['不要采集评论','不需要抓取评论','别爬取评论'])
def test_skipping_comments_does_not_forbid_online_posts(instruction):
    result=validate_strategy(strategy(route='auto',comments=True),'到贴吧采集CS帖子，'+instruction)
    assert result['route']=='online'
    assert result['comments'] is False

def test_comment_opt_out_keeps_explicit_network_prohibition():
    result=validate_strategy(strategy(route='online',comments=True),'不要采集评论，也不要联网，只看已有数据')
    assert result['route']=='local' and result['comments'] is False


def test_ambiguous_golden_ball_requires_domain_before_collection():
    decision=strategy(target='影视金球奖',queries=['金球奖获奖影片'],route='online')
    result=validate_strategy(decision,'收集各届金球奖得主打分贴')
    assert result['route']=='clarify' and result['queries']==[]
    assert '足球金球奖' in result['clarification'] and '影视金球奖' in result['clarification']
    explicit=validate_strategy(strategy(target='足球金球奖',queries=['足球金球奖得主打分贴']),
                               '收集各届足球金球奖得主打分贴')
    assert explicit['route']=='online'
    contextual=validate_strategy(strategy(target='足球金球奖',queries=['金球奖得主打分贴']),
                                 '继续收集金球奖得主打分贴',['刚才说的是足球金球奖'])
    assert contextual['route']=='online'


def test_golden_ball_domain_is_recovered_from_previous_collection_without_sending_history(tmp_path):
    question='收集各届金球奖得主打分贴'
    assert resolve_award_question(question,['收集足球金球奖（Ballon d’Or）得主打分贴']) == '收集各届足球金球奖得主打分贴'
    async def run():
        h,a,s,session,planner=prepare(tmp_path,strategy(target='足球金球奖',queries=['足球金球奖 得主 打分贴']))
        with h.store.connection() as conn:
            conn.execute('INSERT INTO research_collections VALUES(?,?,?,?,?,?,?,?,?)',
                ('prior',session,'2026-01-01T00:00:00Z','failed','收集足球金球奖得主打分贴',
                 json.dumps({'queries':['待规划']}),json.dumps({}), 'invalid_task_strategy',None))
        job=s.start_automatic(session,question)
        await s.tasks[job['id']]
        result=s.get(job['id'])
        assert result['progress']['resolved_question']=='收集各届足球金球奖得主打分贴'
        assert result['progress']['strategy']['route']=='online'
        assert result['status']=='completed',result
        payload=json.loads(planner.messages[1]['content'])
        assert payload['history']==[] and payload['previous_questions']==[]
        assert payload['question']==result['progress']['resolved_question']
        assert not any('金球奖' in str(x) for x in payload['history'])
    asyncio.run(run())


def test_ambiguous_golden_ball_clarifies_before_model_or_crawler(tmp_path):
    async def run():
        h,a,s,session,planner=prepare(tmp_path)
        job=s.start_automatic(session,'收集各届金球奖得主打分贴')
        await s.tasks[job['id']]
        result=s.get(job['id'])
        assert result['progress']['strategy']['route']=='clarify'
        assert result['progress']['planner_calls']==0
        assert not planner.messages and not a.calls
        assert result['status']=='waiting_user'
    asyncio.run(run())

def test_post_only_request_reaches_crawler_without_comment_branch(tmp_path):
    async def run():
        h,a,s,session,_=prepare(tmp_path,strategy(route='auto',comments=True,post_limit=1))
        job=s.start_automatic(session,'到贴吧采集CS帖子，只要1帖，不要采集评论')
        await s.tasks[job['id']]
        assert s.get(job['id'])['status']=='completed'
        assert len(a.calls)==1 and a.calls[0]['query']=='CS' and not a.calls[0]['post_ids']
    asyncio.run(run())
