import asyncio
import json
import uuid

import pytest

from community_research.agent.collection import CollectionService, validate_plan
from community_research.agent.runtime import Harness
from community_research.knowledge import KnowledgeStore, KnowledgeError
class ScriptModel:
    def __init__(self, steps):
        self.steps = iter(steps)
        self.messages = []

    async def complete(self, messages):
        self.messages = messages.copy()
        step = next(self.steps)
        return json.dumps(step(messages) if callable(step) else step)


def valid_model():
    def read(messages):
        result = json.loads(messages[-1]['content'])['tool_result_untrusted']
        return {'action': 'tool', 'name': 'read_evidence', 'arguments': {'evidence_ids': [result['items'][0]['snippets'][0]['evidence_id']]}}

    def answer(messages):
        result = json.loads(messages[-1]['content'])['tool_result_untrusted']
        return {'action': 'answer', 'outcome': 'answered', 'paragraphs': [{'text': '帖子讨论 CS 饰品。', 'evidence_ids': [result['items'][0]['evidence_id']]}], 'limitations': []}
    return ScriptModel([{'action': 'tool', 'name': 'search_posts', 'arguments': {'all_terms': ['CS']}}, read, answer])


class Adapter:
    def __init__(self, root, waiting=False, failed=False, overflow=False):
        self.root, self.waiting, self.failed, self.overflow = root, waiting, failed, overflow
        self.owner = None
        self.calls, self.paths, self.rows, self.stops = [], {}, {}, []

    async def reserve(self, owner):
        if self.owner:
            return False
        self.owner = owner
        return True

    async def release(self, owner):
        assert owner == self.owner
        self.owner = None

    async def start(self, owner, **args):
        assert owner == self.owner
        self.calls.append(args)
        ident = uuid.uuid4().hex
        folder = self.root / 'MediaCrawler/data/tasks' / ident
        (folder / 'output').mkdir(parents=True)
        status = 'failed' if self.failed else 'completed'
        (folder / 'task.json').write_text(json.dumps({'id': ident, 'platform': 'tieba', 'status': status}), encoding='utf-8')
        post = {'note_id': '123', 'title': 'CS 饰品', 'desc': 'CS 饰品讨论', 'total_replay_num': 12, 'publish_time': '2026-09-20 10:00:00', 'note_url': 'https://tieba.baidu.com/p/123'}
        rows = [post]
        if args.get('post_ids'):
            rows.append({'comment_id': '456', 'note_id': '123', 'content': 'CS 饰品价格变化'})
        if self.overflow:
            rows.extend([{**post, 'note_id': str(i)} for i in range(10)])
        path = folder / 'output/contents.json'
        path.write_text(json.dumps(rows), encoding='utf-8')
        self.paths[ident], self.rows[ident] = [path], status
        return ident

    def status(self, ident):
        return {'status': 'running' if self.waiting else self.rows[ident], 'waiting_login': self.waiting}

    def files(self, ident):
        return self.paths[ident]

    async def stop(self, owner):
        self.stops.append(owner)
        return True


def make(tmp_path, **kwargs):
    harness = Harness(KnowledgeStore(tmp_path), valid_model)
    adapter = Adapter(tmp_path, **kwargs)
    service = CollectionService(harness, adapter)
    return harness, adapter, service, harness.create_session()['id']


@pytest.mark.parametrize('change', [{'queries': []}, {'queries': ['a,b']}, {'queries': ['a'] * 4}, {'posts_per_query': 21}, {'seconds': 301}, {'comment_posts': True}, {'cookies': 'secret'}])
def test_invalid_budget(change):
    with pytest.raises(KnowledgeError):
        validate_plan({'queries': ['CS'], **change})


def test_approved_collection_import_answer_and_idempotency(tmp_path):
    async def run():
        h, a, s, session = make(tmp_path)
        job = await s.propose(session, '找 CS 饰品帖子和评论', ['CS'])
        assert not a.calls and job['status'] == 'proposed'
        assert job['progress']['local_preview'][0]['local_posts'] is None
        plan = {**job['plan'], 'comment_posts': 1, 'posts_per_query': 1}
        started = await s.execute(job['id'], plan)
        assert (await s.execute(job['id'], plan))['id'] == started['id']
        with pytest.raises(KnowledgeError, match='session_busy'):
            h.start(session, '另一个问题')
        with pytest.raises(KnowledgeError, match='session_busy'):
            h.delete_session(session)
        await s.tasks[job['id']]
        result = s.get(job['id'])
        assert result['status'] == 'completed', result
        assert len(a.calls) == 2 and a.calls[1]['post_ids'] == ['123']
        assert len(result['progress']['source_ids']) == 2
        answer = h.run(result['answer_run_id'])
        assert answer['user_text'] == job['question'] and answer['answer']['paragraphs'][0]['evidence_ids']
        assert '未进行在线搜索' not in str(answer['answer']['limitations'])
        assert a.owner is None and a.stops == [job['id']]
        await s.execute(job['id'], plan)
        assert len(a.calls) == 2
        with pytest.raises(KnowledgeError, match='plan_already_started'):
            await s.execute(job['id'], {**plan, 'seconds': 120})
        h.delete_session(session)
        assert len(h.store.list_sources()) == 2
    asyncio.run(run())


def test_cancel_waiting_login_and_global_reservation(tmp_path):
    async def run():
        h, a, s, session = make(tmp_path, waiting=True)
        job = await s.propose(session, 'CS', ['CS'])
        await s.execute(job['id'], job['plan'])
        await asyncio.sleep(.03)
        assert s.get(job['id'])['status'] == 'waiting_login'
        other = await s.propose(h.create_session()['id'], 'CS', ['CS'])
        with pytest.raises(KnowledgeError, match='crawler_busy'):
            await s.execute(other['id'], other['plan'])
        result = await s.cancel(job['id'])
        assert result['status'] == 'cancelled'
        assert result['progress']['branches'][0]['status'] == 'stopped'
        assert len(a.calls) == 1 and a.owner is None and a.stops
        await s.cancel(other['id'])
        assert s.get(other['id'])['status'] == 'cancelled'
    asyncio.run(run())


@pytest.mark.parametrize('failed,overflow,error', [(True, False, None), (False, True, 'crawler_budget_violation')])
def test_partial_data_and_budget_violation(tmp_path, failed, overflow, error):
    async def run():
        h, a, s, session = make(tmp_path, failed=failed, overflow=overflow)
        job = await s.propose(session, 'CS', ['CS'])
        await s.execute(job['id'], job['plan'])
        await s.tasks[job['id']]
        result = s.get(job['id'])
        assert result['status'] == 'partial', result
        assert result['error'] == error and a.owner is None
    asyncio.run(run())


def test_planner_uses_only_questions_and_rejects_bad_output(tmp_path):
    async def run():
        h, a, s, session = make(tmp_path)
        model = ScriptModel([{'queries': ['CS'], 'comment_posts': 1}, {'queries': ['CS'], 'cookies': 'secret'}])
        h.model_factory = lambda: model
        job = await s.propose(session, 'CS 评论')
        assert job['plan']['comment_posts'] == 1 and not a.calls
        assert 'cookies' not in str(model.messages)
        with pytest.raises(KnowledgeError, match='invalid_collection_plan'):
            await s.propose(session, 'CS')
    asyncio.run(run())


def test_nonmatching_candidate_does_not_fetch_comments(tmp_path):
    async def run():
        h, a, s, session = make(tmp_path)
        job = await s.propose(session, '动物', ['动物'])
        await s.execute(job['id'], {**job['plan'], 'comment_posts': 2})
        await s.tasks[job['id']]
        assert len(a.calls) == 1 and not s.get(job['id'])['progress']['candidates']
    asyncio.run(run())


def test_restart_marks_active_interrupted(tmp_path):
    h, a, s, session = make(tmp_path)
    job = asyncio.run(s.propose(session, 'CS', ['CS']))
    s._update(job['id'], status='running')
    restored = CollectionService(h, a)
    assert restored.get(job['id'])['status'] == 'interrupted' and not a.calls


def test_timeout_stops_reserved_crawler(tmp_path, monkeypatch):
    async def run():
        h, a, s, session = make(tmp_path, waiting=True)
        original_timeout = asyncio.timeout
        monkeypatch.setattr(asyncio, 'timeout', lambda seconds: original_timeout(.05))
        job = await s.propose(session, 'CS', ['CS'])
        await s.execute(job['id'], job['plan'])
        await s.tasks[job['id']]
        result = s.get(job['id'])
        assert result['error'] == 'collection_login_timeout' and a.owner is None
        assert len(a.calls) == 1 and a.stops == [job['id']]
    asyncio.run(run())


def test_concurrent_execute_starts_once(tmp_path):
    async def run():
        h, a, s, session = make(tmp_path, waiting=True)
        reserve = a.reserve
        async def slow(owner):
            await asyncio.sleep(.02)
            return await reserve(owner)
        a.reserve = slow
        job = await s.propose(session, 'CS', ['CS'])
        results = await asyncio.gather(*(s.execute(job['id'], job['plan']) for _ in range(3)))
        assert all(r['id'] == job['id'] for r in results)
        assert len(a.calls) == 1
        await s.cancel(job['id'])
    asyncio.run(run())


def test_http_plan_execute_and_cancel(tmp_path):
    import httpx
    from fastapi import FastAPI
    from community_research.api.router import create_router
    async def run():
        h, a, _, session = make(tmp_path, waiting=True)
        app = FastAPI(); app.include_router(create_router(h, a))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            assert (await client.get('/api/research/config')).json()['collection_enabled']
            job = (await client.post(f'/api/research/sessions/{session}/collections', json={'text': 'CS', 'queries': ['CS']})).json()
            assert not a.calls
            bad = await client.post(f"/api/research/collections/{job['id']}/execute", json={'plan': {**job['plan'], 'seconds': 999}})
            assert bad.status_code == 400 and not a.calls
            started = await client.post(f"/api/research/collections/{job['id']}/execute", json={'plan': job['plan']})
            assert started.status_code == 200
            await asyncio.sleep(.02)
            assert (await client.post(f'/api/research/sessions/{session}/runs', json={'text': 'CS'})).status_code == 409
            result = (await client.post(f"/api/research/collections/{job['id']}/cancel")).json()
            assert result['status'] == 'cancelled' and a.owner is None
    asyncio.run(run())
