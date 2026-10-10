import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI

from community_research.agent.model import ChatModel, ModelError, parse_action
from community_research.agent.runtime import Harness
from community_research.api.router import create_router
from community_research.knowledge import KnowledgeStore, KnowledgeError


PLAN = {'action': 'plan', 'goal': dict(entity='CS', domain='电竞', question='有哪些讨论', time_range='未限定', constraints='本地')}


class ScriptModel:
    def __init__(self, steps):
        self.steps = iter(steps)
        self.messages = []

    async def complete(self, messages):
        self.messages = messages.copy()
        step = next(self.steps)
        if isinstance(step, Exception):
            raise step
        value = step(messages) if callable(step) else step
        return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def read_action(messages):
    result = json.loads(messages[-1]['content'])['tool_result_untrusted']
    ident = result['items'][0]['snippets'][0]['evidence_id']
    return {'action': 'tool', 'name': 'read_evidence', 'arguments': {'evidence_ids': [ident]}}


def final_answer(messages):
    result = json.loads(messages[-1]['content'])['tool_result_untrusted']
    return {'action': 'answer', 'outcome': 'answered', 'paragraphs': [{'text': '帖子讨论了 CS 饰品。', 'evidence_ids': [result['items'][0]['evidence_id']]}], 'limitations': []}


def valid_model():
    return ScriptModel([PLAN, {'action': 'tool', 'name': 'search_posts', 'arguments': {'all_terms': ['cs']}}, read_action, final_answer])


def make(tmp_path, model=None):
    store = KnowledgeStore(tmp_path)
    path = tmp_path / 'posts.json'
    path.write_text(json.dumps([{'note_id': '1', 'title': 'CS', 'desc': 'CS 饰品讨论', 'note_url': 'https://tieba.baidu.com/p/1'}]), encoding='utf-8')
    source = store.register_source(path, platform='tieba')
    store.import_source(source['id'])
    return Harness(store, (lambda: model) if model else None), source


async def execute(harness, text='查 CS', budget=None, session=None):
    session = session or harness.create_session()['id']
    run = harness.start(session, text, budget)['run_id']
    await harness.tasks[run]
    return harness.run(run)


def test_grounded_run_persistence_and_invalidated_history(tmp_path):
    harness, source = make(tmp_path, valid_model())
    result = asyncio.run(execute(harness))
    assert result['status'] == 'completed', result
    assert result['usage'] == {'model_calls': 4, 'tool_calls': 2}
    assert result['answer_available']
    with harness.store.connection() as conn:
        event = conn.execute('SELECT * FROM research_events').fetchone()
        assert 'CS 饰品讨论' not in str(dict(event))
    restored = Harness(KnowledgeStore(tmp_path))
    assert restored.session(result['session_id'])['runs'][0]['answer'] == result['answer']
    restored.store.revoke(source['id'])
    assert not restored.run(result['id'])['answer_available']


def test_forged_or_unread_citation_rejected(tmp_path):
    forged = {'action': 'answer', 'outcome': 'answered', 'paragraphs': [{'text': '伪造结论', 'evidence_ids': ['ev_not_read']}], 'limitations': []}
    harness, _ = make(tmp_path, ScriptModel([forged, forged]))
    result = asyncio.run(execute(harness))
    assert result['error'] == 'unread_citation' and result['usage']['model_calls'] == 2
    assert result['answer'] is None


def test_no_matches_requires_successful_search(tmp_path):
    answer = {'action': 'answer', 'outcome': 'no_matches', 'paragraphs': [{'text': '本地没有匹配', 'evidence_ids': []}], 'limitations': []}
    harness, _ = make(tmp_path, ScriptModel([answer, answer]))
    assert asyncio.run(execute(harness))['error'] == 'unproven_no_matches'
    harness.model_factory = lambda: ScriptModel([PLAN, {'action': 'tool', 'name': 'search_posts', 'arguments': {'all_terms': ['不存在词']}}, answer])
    assert asyncio.run(execute(harness))['answer']['outcome'] == 'no_matches'


def test_clarification_and_goal_revisions(tmp_path):
    clarify = {'action': 'answer', 'outcome': 'needs_clarification', 'paragraphs': [{'text': '你指的是电竞选手还是动物？', 'evidence_ids': []}], 'limitations': []}
    model = ScriptModel([clarify, clarify])
    harness, _ = make(tmp_path, model)
    first = asyncio.run(execute(harness, '小驴最近怎么样'))
    assert first['status'] == 'waiting_user'
    second = asyncio.run(execute(harness, '指 donk', session=first['session_id']))
    assert second['revision'] == 2
    assert '小驴最近怎么样' in model.messages[1]['content'] and 'donk' in model.messages[1]['content']
    assert model.messages[2] == {'role': 'user', 'content': '小驴最近怎么样'}
    assert model.messages[3]['role'] == 'assistant'
    assert json.loads(model.messages[3]['content'])['action'] == 'answer'
    assert model.messages[-1] == {'role': 'user', 'content': '指 donk'}


def test_followup_restores_role_order_after_restart_and_isolates_sessions(tmp_path):
    harness, _ = make(tmp_path, valid_model())
    first = asyncio.run(execute(harness, '查 CS 饰品'))
    response = {'action': 'answer', 'outcome': 'needs_clarification', 'paragraphs': [{'text': '你想继续了解哪方面？', 'evidence_ids': []}], 'limitations': []}
    model = ScriptModel([response, response])
    restored = Harness(KnowledgeStore(tmp_path), lambda: model)
    asyncio.run(execute(restored, '刚才那条再详细说说', session=first['session_id']))
    transcript = model.messages[2:]
    assert [m['role'] for m in transcript] == ['user', 'assistant', 'user']
    assert '帖子讨论了 CS 饰品' in transcript[1]['content']
    assert transcript[-1]['content'] == '刚才那条再详细说说'
    asyncio.run(execute(restored, '新的话题'))
    assert not any('帖子讨论了 CS 饰品' in m['content'] for m in model.messages)


@pytest.mark.parametrize('code', ['model_timeout', 'model_auth_failed', 'model_service_error', 'model_not_configured'])
def test_model_errors_remain_errors(tmp_path, code):
    harness, _ = make(tmp_path, ScriptModel([ModelError(code)]))
    result = asyncio.run(execute(harness))
    assert result['status'] == 'failed' and result['error'] == code and result['answer'] is None


def test_call_budget_and_repair_budget(tmp_path):
    harness, _ = make(tmp_path, ScriptModel(['bad', PLAN]))
    result = asyncio.run(execute(harness, budget={'model_calls': 2}))
    assert result['error'] == 'budget_exceeded' and result['usage']['model_calls'] == 2


def test_tool_budget_stops_before_next_tool(tmp_path):
    harness, _ = make(tmp_path, valid_model())
    result = asyncio.run(execute(harness, budget={'tool_calls': 1}))
    assert result['error'] == 'budget_exceeded' and result['usage']['tool_calls'] == 1
    assert len(result['events']) == 1 and result['answer'] is None


def test_expired_answer_is_not_reused_as_model_context(tmp_path):
    harness, source = make(tmp_path, valid_model())
    first = asyncio.run(execute(harness))
    harness.store.revoke(source['id'])
    model = ScriptModel([{'action': 'answer', 'outcome': 'needs_clarification', 'paragraphs': [{'text': '请补充范围', 'evidence_ids': []}], 'limitations': []}])
    harness.model_factory = lambda: model
    asyncio.run(execute(harness, '继续看看', session=first['session_id']))
    assert not any('帖子讨论了 CS 饰品' in m['content'] for m in model.messages)


def test_unregistered_tool_and_cross_run_evidence_blocked(tmp_path):
    action = {'action': 'tool', 'name': 'delete_source', 'arguments': {}}
    harness, _ = make(tmp_path, ScriptModel([PLAN, action, action]))
    assert asyncio.run(execute(harness))['error'] == 'invalid_tool_action'
    action = {'action': 'tool', 'name': 'read_evidence', 'arguments': {'evidence_ids': ['ev_other_run']}}
    harness.model_factory = lambda: ScriptModel([PLAN, action, action])
    assert asyncio.run(execute(harness))['error'] == 'evidence_not_in_run'


def test_cancel_and_duplicate_run(tmp_path):
    class Waiting:
        async def complete(self, messages):
            await asyncio.sleep(30)
    harness, _ = make(tmp_path, Waiting())
    async def scenario():
        session = harness.create_session()['id']
        run = harness.start(session, 'CS')['run_id']
        await asyncio.sleep(.02)
        with pytest.raises(KnowledgeError, match='session_busy'):
            harness.start(session, 'duplicate')
        with pytest.raises(KnowledgeError, match='session_busy'):
            harness.delete_session(session)
        task = harness.tasks[run]
        harness.cancel(run)
        await task
        assert harness.run(run)['status'] == 'cancelled'
        assert harness.run(run)['usage']['tool_calls'] == 0
    asyncio.run(scenario())


def test_total_timeout(tmp_path):
    class Waiting:
        async def complete(self, messages):
            await asyncio.sleep(30)
    harness, _ = make(tmp_path, Waiting())
    assert asyncio.run(execute(harness, budget={'seconds': 1}))['error'] == 'total_timeout'


def test_restart_marks_unfinished(tmp_path):
    harness, _ = make(tmp_path, valid_model())
    result = asyncio.run(execute(harness))
    with harness.store.connection() as conn:
        conn.execute("UPDATE research_runs SET status='running',answer=NULL WHERE id=?", (result['id'],))
    restored = Harness(KnowledgeStore(tmp_path))
    assert restored.run(result['id'])['status'] == 'interrupted'


def test_api_session_run_evidence_and_secret_exclusion(tmp_path):
    harness, _ = make(tmp_path, valid_model())
    app = FastAPI(); app.include_router(create_router(harness))
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            session = (await client.post('/api/research/sessions')).json()['id']
            response = await client.post(f'/api/research/sessions/{session}/runs', json={'text': 'CS'})
            run = response.json()['run_id']; await harness.tasks[run]
            record = (await client.get('/api/research/runs/' + run)).json()
            evidence = record['answer']['paragraphs'][0]['evidence_ids'][0]
            view = await client.get(f'/api/research/runs/{run}/evidence/{evidence}')
            assert view.status_code == 200 and view.json()['evidence']['quote']
            assert (await client.get(f'/api/research/runs/{run}/evidence/ev_bad')).status_code == 404
            assert (await client.post(f'/api/research/sessions/{session}/runs', json={'text': 'CS', 'extra': 1})).status_code == 422
            assert 'key' not in (await client.get('/api/research/config')).text.lower()
            assert (await client.get('/api/research/sessions/' + session)).json()['runs'][0]['answer']
    asyncio.run(scenario())


@pytest.mark.parametrize('status,code', [(401, 'model_auth_failed'), (429, 'model_rate_limited'), (400, 'model_request_rejected'), (500, 'model_service_error')])
def test_transport_errors_are_sanitized(tmp_path, monkeypatch, status, code):
    for key, value in {'RESEARCH_BASE_URL': 'https://model.example/v1', 'RESEARCH_API_KEY': 'secret-test', 'RESEARCH_MODEL': 'test'}.items():
        monkeypatch.setenv(key, value)
    factory = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: factory(transport=httpx.MockTransport(lambda request: httpx.Response(status, text='secret-test diagnostic')), **kwargs))
    with pytest.raises(ModelError, match=code):
        asyncio.run(ChatModel(tmp_path).complete([]))


def test_transport_compatible_json(tmp_path, monkeypatch):
    for key, value in {'RESEARCH_BASE_URL': 'https://model.example/v1', 'RESEARCH_API_KEY': 'secret-test', 'RESEARCH_MODEL': 'test'}.items():
        monkeypatch.setenv(key, value)
    def transport(request):
        assert request.url.path == '/v1/chat/completions'
        assert request.headers['Authorization'] == 'Bearer secret-test'
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(PLAN)}}]})
    factory = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: factory(transport=httpx.MockTransport(transport), **kwargs))
    assert json.loads(asyncio.run(ChatModel(tmp_path).complete([]))) == PLAN


@pytest.mark.parametrize('wrap', [lambda s:s, lambda s:'```json\n'+s+'\n```', lambda s:'\ufeff'+s])
def test_complete_json_wrappers(wrap):
    assert parse_action(wrap(json.dumps(PLAN))) == PLAN


@pytest.mark.parametrize('raw', ['Here is JSON: {}', '{} {}', '{"a":1,"a":2}', '{"x":NaN}', '{"action":'])
def test_malformed_json_not_guessed(raw):
    with pytest.raises(ValueError):
        parse_action(raw)


@pytest.mark.parametrize('reason,content,code', [('length', '{"action":', 'model_output_truncated'), ('stop', '', 'model_empty_response'), ('content_filter', '', 'model_content_filtered')])
def test_deepseek_output_diagnostics(tmp_path, monkeypatch, reason, content, code):
    for key, value in {'RESEARCH_BASE_URL': 'https://api.deepseek.com', 'RESEARCH_API_KEY': 'private-test-key', 'RESEARCH_MODEL': 'deepseek-flash'}.items():
        monkeypatch.setenv(key, value)
    def transport(request):
        payload = json.loads(request.content)
        assert payload['response_format'] == {'type': 'json_object'}
        assert payload['thinking'] == {'type': 'disabled'}
        return httpx.Response(200, json={'choices':[{'finish_reason':reason,'message':{'content':content}}]})
    factory = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: factory(transport=httpx.MockTransport(transport), **kwargs))
    model = ChatModel(tmp_path)
    with pytest.raises(ModelError, match=code):
        asyncio.run(model.complete([]))
    assert model.diagnostics['finish_reason'] == reason
    assert 'private-test-key' not in str(model.diagnostics)


def test_parse_failure_records_location_without_content(tmp_path):
    harness, _ = make(tmp_path, ScriptModel(['{"secret":', '{"secret":']))
    run = asyncio.run(execute(harness))
    assert run['error'] == 'invalid_model_json'
    with harness.store.connection() as conn:
        rows = [dict(r) for r in conn.execute('SELECT * FROM research_diagnostics')]
    assert len(rows) == 2 and 'secret' not in str(rows)
    assert 'position' in json.loads(rows[0]['metadata'])


def test_missing_citation_repair_uses_read_ids(tmp_path):
    invalid = {'action': 'answer', 'outcome': 'answered', 'paragraphs': [{'text': 'CS讨论', 'evidence_ids': []}], 'limitations': []}
    def repair(messages):
        feedback = json.loads(messages[-1]['content'])['tool_result_untrusted']
        assert feedback['error'] == 'missing_citation'
        assert feedback['read_evidence_ids']
        return {'action': 'answer', 'outcome': 'partial', 'paragraphs': [{'text': 'CS讨论', 'evidence_ids': feedback['read_evidence_ids']}], 'limitations': ['仅本地']}
    model = ScriptModel([PLAN, {'action': 'tool', 'name': 'search_posts', 'arguments': {'all_terms': ['cs']}}, read_action, invalid, repair])
    harness, _ = make(tmp_path, model)
    result = asyncio.run(execute(harness))
    assert result['status'] == 'partial' and result['usage']['model_calls'] == 5


def test_distinct_plan_and_citation_errors_each_get_one_repair(tmp_path):
    invalid_plan = {'action':'plan','goal':{**PLAN['goal'],'extra':'unused'}}
    unread = {'action':'answer','outcome':'answered',
              'paragraphs':[{'text':'CS讨论','evidence_ids':['ev_not_read']}], 'limitations':[]}
    def repaired_answer(messages):
        feedback=json.loads(messages[-1]['content'])['tool_result_untrusted']
        assert feedback['error']=='unread_citation' and feedback['read_evidence_ids']
        return {'action':'answer','outcome':'partial',
                'paragraphs':[{'text':'CS讨论','evidence_ids':feedback['read_evidence_ids']}],
                'limitations':[]}
    model=ScriptModel([invalid_plan,PLAN,
        {'action':'tool','name':'search_posts','arguments':{'all_terms':['cs']}},
        read_action,unread,repaired_answer])
    harness,_=make(tmp_path,model)
    result=asyncio.run(execute(harness))
    assert result['status']=='partial' and result['usage']['model_calls']==6


def test_session_titles_and_delete_cascade_preserves_sources(tmp_path):
    harness, _ = make(tmp_path, valid_model())
    result = asyncio.run(execute(harness, '请介绍 CS 饰品'))
    other = harness.create_session()['id']
    titles = {s['id']: s['title'] for s in harness.sessions()}
    assert titles[result['session_id']] == 'CS'
    assert titles[other] == '新对话'
    snapshots = harness.store.list_snapshots()
    harness._diagnostic(result['id'], 1, 'test', {'position': 1})
    harness.delete_session(result['session_id'])
    assert harness.store.list_snapshots() == snapshots
    assert [s['id'] for s in harness.sessions()] == [other]
    with harness.store.connection() as conn:
        for table in ('research_goals', 'research_runs', 'research_events', 'research_diagnostics'):
            assert conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 0
    with pytest.raises(KnowledgeError, match='session_not_found'):
        harness.session(result['session_id'])


def test_session_title_fallback_and_existing_data(tmp_path):
    harness, _ = make(tmp_path, ScriptModel([ModelError('model_not_configured')]))
    result = asyncio.run(execute(harness, '已采集内容中，是否有介绍小蜜蜂战队的评论或帖子'))
    assert harness.sessions()[0]['title'] == '是否有介绍小蜜蜂战队的评论或帖子'
    restored = Harness(KnowledgeStore(tmp_path))
    assert restored.sessions()[0]['title'] == harness.sessions()[0]['title']
    async def scenario():
        app = FastAPI(); app.include_router(create_router(restored))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            path = '/api/research/sessions/' + result['session_id']
            assert (await client.delete(path)).status_code == 200
            assert (await client.delete(path)).status_code == 404
            assert (await client.get('/api/research/runs/' + result['id'])).status_code == 404
    asyncio.run(scenario())


def test_bare_answer_normalization_does_not_bypass_citations(tmp_path):
    bare = {'outcome': 'answered', 'paragraphs': [{'text': '猜测', 'evidence_ids': ['ev_wrong']}], 'limitations': []}
    assert parse_action(json.dumps(bare))['action'] == 'answer'
    harness, _ = make(tmp_path, ScriptModel([bare, bare]))
    assert asyncio.run(execute(harness))['error'] == 'unread_citation'


def test_invalid_action_repair_can_read_then_answer(tmp_path):
    def repair(messages):
        feedback = json.loads(messages[-1]['content'])['tool_result_untrusted']
        assert feedback['error'] == 'invalid_model_action'
        assert feedback['read_evidence_ids'] == []
        return {'action': 'tool', 'name': 'read_evidence', 'arguments': {'evidence_ids': feedback['available_evidence_ids'][:1]}}
    model = ScriptModel([PLAN, {'action': 'tool', 'name': 'search_posts', 'arguments': {'all_terms': ['CS']}},
                         {'action': 'confirm', 'text': '就这两条'}, repair, final_answer])
    harness, _ = make(tmp_path, model)
    assert asyncio.run(execute(harness, '就这两条吗'))['status'] == 'completed'


def test_repeated_followup_receives_only_protocol_shaped_answers(tmp_path):
    harness, _ = make(tmp_path, valid_model())
    first = asyncio.run(execute(harness))
    for _ in range(2):
        model = valid_model(); harness.model_factory = lambda: model
        result = asyncio.run(execute(harness, '就这两条吗', session=first['session_id']))
        assert result['error'] is None
        for message in model.messages:
            if message['role'] == 'assistant':
                assert json.loads(message['content'])['action'] in ('plan', 'tool', 'answer')


def test_direct_followup_tool_after_single_format_repair(tmp_path):
    search = {'action': 'tool', 'name': 'search_posts', 'arguments': {'all_terms': ['CS']}}
    model = ScriptModel([json.dumps(search) + '\n' + json.dumps(search), search, read_action, final_answer])
    harness, _ = make(tmp_path, model)
    result = asyncio.run(execute(harness, '就这两条吗'))
    assert result['status'] == 'completed' and result['usage']['model_calls'] == 4
    assert result['plan']['question'] == '就这两条吗'
    assert harness.sessions()[0]['title'] == '就这两条吗'
    with harness.store.connection() as conn:
        diagnostic = json.loads(conn.execute('SELECT metadata FROM research_diagnostics').fetchone()[0])
    assert diagnostic['multiple_json_values'] is True


@pytest.mark.parametrize('name', ['search_posts', 'search_comments', 'read_evidence'])
def test_read_only_tool_shorthand(name):
    assert parse_action(json.dumps({'action': name, 'arguments': {}})) == {'action': 'tool', 'name': name, 'arguments': {}}
    assert parse_action('{"action":"delete_source","arguments":{}}')['action'] == 'delete_source'


def test_shorthand_still_checks_evidence_authorization(tmp_path):
    action = {'action': 'read_evidence', 'arguments': {'evidence_ids': ['ev_other_run']}}
    harness, _ = make(tmp_path, ScriptModel([action, action]))
    assert asyncio.run(execute(harness))['error'] == 'evidence_not_in_run'


def test_same_session_history_can_be_reread_but_not_directly_cited(tmp_path):
    harness, _ = make(tmp_path, valid_model())
    first = asyncio.run(execute(harness))
    ident = first['answer']['paragraphs'][0]['evidence_ids'][0]
    read = {'action': 'read_evidence', 'arguments': {'evidence_ids': [ident]}}
    harness.model_factory = lambda: ScriptModel([read, final_answer])
    followup = asyncio.run(execute(harness, '再看看这条', session=first['session_id']))
    assert followup['status'] == 'completed' and followup['usage']['tool_calls'] == 1
    answer = {'action': 'answer', **{k:first['answer'][k] for k in ('outcome', 'paragraphs', 'limitations')}}
    harness.model_factory = lambda: ScriptModel([answer, answer])
    assert asyncio.run(execute(harness, '再回答', session=first['session_id']))['error'] == 'unread_citation'
    harness.model_factory = lambda: ScriptModel([read, read])
    assert asyncio.run(execute(harness, '其他会话'))['error'] == 'evidence_not_in_run'


def test_source_cards_distinguish_posts_comments_and_merge_fragments(tmp_path):
    from community_research.knowledge.presentation import source_cards
    harness, source = make(tmp_path, valid_model())
    path = tmp_path / 'comments.json'
    path.write_text(json.dumps([{'comment_id': 'c', 'note_id': '1', 'content': 'CS 评论观点', 'note_url': 'https://tieba.baidu.com/p/1'}]), encoding='utf-8')
    comment_source = harness.store.register_source(path, platform='tieba')
    harness.store.import_source(comment_source['id'])
    post = harness.tools.call('search_posts', {'all_terms': ['CS']})['items'][0]
    comment = harness.tools.call('search_comments', {'all_terms': ['CS']})['items'][0]
    ids = [s['evidence_id'] for s in post['snippets']] + [comment['snippets'][0]['evidence_id']]
    cards, invalid = source_cards(harness.tools, ids + ids)
    assert not invalid and len(cards) == 2
    assert cards[0]['kind'] == 'post' and cards[0]['title'] == 'CS'
    assert cards[1]['kind'] == 'comment' and cards[1]['title'] == 'CS'
    assert cards[1]['source_url'] == 'https://tieba.baidu.com/p/1'
    assert cards[1]['excerpts'][0]['quote'] == 'CS 评论观点'
    assert len(cards[0]['evidence_ids']) == len(post['snippets'])
    harness.store.revoke(source['id'])
    cards, invalid = source_cards(harness.tools, ids)
    assert len(cards) == 1 and cards[0]['title'] == '标题未采集'
    assert len(invalid) == len(post['snippets'])


def test_collection_result_cards_exclude_screening_evidence(tmp_path):
    from community_research.agent.collection import SCHEMA as COLLECTION_SCHEMA
    harness, _ = make(tmp_path, valid_model())
    extra = tmp_path / 'extra.json'
    extra.write_text(json.dumps([
        {'note_id': '2', 'title': '无关帖', 'desc': '仅用于说明排除依据'},
        {'note_id': '3', 'title': '待核实帖', 'desc': '上下文不足'},
        {'comment_id': 'c2', 'note_id': '2', 'content': '评论可能有独立的相关信息'},
    ], ensure_ascii=False), encoding='utf-8')
    source = harness.store.register_source(extra, platform='tieba')
    harness.store.import_source(source['id'])
    run = asyncio.run(execute(harness))
    posts = [harness.tools.call('search_posts', {'all_terms': [term]})['items'][0]
             for term in ('CS', '无关帖', '待核实帖')]
    ids = [p['snippets'][0]['evidence_id'] for p in posts]
    comment = harness.tools.call('search_comments', {'all_terms': ['独立的相关信息']})['items'][0]
    comment_id = comment['snippets'][0]['evidence_id']
    answer = dict(run['answer'], paragraphs=[
        {'text': '正式结果', 'evidence_ids': [ids[0]]},
        {'text': '排除理由', 'evidence_ids': [ids[1]]},
        {'text': '仍待核实', 'evidence_ids': [ids[2]]},
        {'text': '混合依据', 'evidence_ids': [ids[0], ids[1]]},
        {'text': '评论待核实', 'evidence_ids': [comment_id]},
    ])
    notes = [{'snapshot_id': p['snapshot_id'], 'status': 'reviewed', 'label': label,
              'reason': '初筛理由', 'evidence_ids': [ident]}
             for p, ident, label in zip(posts, ids, ('relevant', 'irrelevant', 'uncertain'))]
    with harness.store.connection() as conn:
        conn.executescript(COLLECTION_SCHEMA)
        conn.execute('UPDATE research_runs SET answer=? WHERE id=?', (json.dumps(answer), run['id']))
        conn.execute('''INSERT INTO research_collections
            (id,session_id,created_at,status,question,plan,progress,answer_run_id)
            VALUES(?,?,?,?,?,?,?,?)''', ('c', run['session_id'], '2026-09-24', 'completed', '筛选', '{}',
            json.dumps({'candidate_review': {'items': notes, 'counts': {'relevant': 1, 'irrelevant': 1, 'uncertain': 1, 'unreviewed': 0}}}), run['id']))
    result = harness.run(run['id'])
    assert [c['external_id'] for c in result['result_cards']] == ['1']
    assert [c['external_id'] for c in result['pending_cards']] == ['3', 'c2']
    assert result['excluded_card_count'] == 1
    assert len(result['source_cards']) == 4  # Audit trail remains intact.
    assert [p['text'] for p in result['result_paragraphs']] == ['正式结果']
    assert [p['text'] for p in result['screening_paragraphs']] == ['排除理由']
    assert [p['text'] for p in result['pending_paragraphs']] == ['仍待核实', '混合依据', '评论待核实']
    with harness.store.connection() as conn:
        progress = {'candidate_review': {'items': notes}, 'comment_review': {'items': [
            {'snapshot_id': comment['snapshot_id'], 'status': 'reviewed', 'label': 'relevant'}]}}
        conn.execute('UPDATE research_collections SET progress=? WHERE answer_run_id=?',
                     (json.dumps(progress), run['id']))
    with_comment = harness.run(run['id'])
    assert [c['external_id'] for c in with_comment['result_cards']] == ['1', 'c2']
    assert '评论待核实' in [p['text'] for p in with_comment['result_paragraphs']]
    from community_research.agent.collection import CollectionService
    collection = CollectionService(harness, None)
    corrected = collection.correct_review('c', posts[1]['snapshot_id'], 'relevant', '用户指出该帖实际相关')
    assert corrected['progress']['candidate_review']['counts']['relevant'] == 2
    assert corrected['progress']['review_corrections'][0]['before']['label'] == 'irrelevant'
    updated_run = harness.run(run['id'])
    assert updated_run['answer_needs_review']
    assert [c['external_id'] for c in updated_run['result_cards']] == ['1', '2', 'c2']
    app = FastAPI(); app.include_router(create_router(harness))
    async def api_correction():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            response = await client.post('/api/research/collections/c/review-corrections',json={
                'snapshot_id':posts[2]['snapshot_id'],'label':'irrelevant','reason':'用户核对后排除'})
            assert response.status_code==200, response.text
            assert response.json()['progress']['candidate_review']['counts']['irrelevant']==1
    asyncio.run(api_correction())
    with harness.store.connection() as conn:
        conn.execute('UPDATE research_runs SET answer=? WHERE id=?',
            (json.dumps({'outcome': 'needs_clarification', 'paragraphs': [{'text': '请确认对象', 'evidence_ids': []}],
                         'limitations': []}), run['id']))
    clarified = harness.run(run['id'])
    assert [p['text'] for p in clarified['result_paragraphs']] == ['请确认对象']


@pytest.mark.parametrize('count,expected', [(0, 0), ('17', 17), (None, None), (-1, None), (True, None)])
def test_post_stats_and_comment_parent_stats(tmp_path, count, expected):
    from community_research.knowledge.presentation import source_cards
    harness, _ = make(tmp_path, valid_model())
    path = tmp_path / 'stats.json'
    path.write_text(json.dumps([{'note_id': 'stats', 'title': '统计帖子', 'desc': 'metadata test', 'publish_time': '2026-09-17 09:30:00', 'total_replay_num': count},
                               {'comment_id': 'stats_c', 'note_id': 'stats', 'content': 'metadata reply', 'publish_time': '2026-09-18 10:00:00'}]), encoding='utf-8')
    source = harness.store.register_source(path, platform='tieba'); harness.store.import_source(source['id'])
    ids = [harness.tools.call(tool, {'all_terms': ['metadata']})['items'][0]['snippets'][0]['evidence_id'] for tool in ('search_posts', 'search_comments')]
    cards, invalid = source_cards(harness.tools, ids)
    assert not invalid
    for card in cards:
        assert card['post_published_at'] == '2026-09-17 09:30:00'
        assert card['post_reply_count'] == expected
