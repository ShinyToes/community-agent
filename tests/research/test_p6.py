import asyncio
import importlib.util
import json
from pathlib import Path
import time
import uuid

import httpx
import pytest
from fastapi import FastAPI

from community_research.agent.runtime import Harness
from community_research.agent.scheduler import Scheduler
from community_research.api.router import create_router
from community_research.knowledge import KnowledgeError, KnowledgeStore
from community_research.knowledge.search import SearchService


def post(body='旧正文', ident='123', observed=1800000000000):
    return {'note_id': ident, 'title': '版本测试', 'desc': body, 'last_modify_ts': observed,
            'note_url': 'https://tieba.baidu.com/p/' + ident}


def comment(ident, body='评论', parent='123'):
    return {'comment_id': ident, 'note_id': parent, 'content': body}


def ingest(store, name, rows):
    path = store.root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
    source = store.register_source(path, platform='tieba')
    store.import_source(source['id'])
    return source['id']


class Adapter:
    def __init__(self, root, waiting=False, overflow=False, incomplete=False, start_fails=False):
        self.root, self.waiting, self.overflow = root, waiting, overflow
        self.incomplete, self.start_fails = incomplete, start_fails
        self.owner = None
        self.calls, self.stops, self.paths, self.states = [], [], {}, {}

    async def reserve(self, owner):
        if self.owner:
            return False
        self.owner = owner
        return True

    async def release(self, owner):
        assert self.owner == owner
        self.owner = None

    async def start(self, owner, **args):
        assert self.owner == owner
        self.calls.append((owner, args))
        if self.start_fails:
            return None
        task_id = uuid.uuid4().hex
        folder = self.root / 'MediaCrawler/data/tasks' / task_id
        (folder / 'output').mkdir(parents=True)
        state = 'failed' if self.incomplete else 'completed'
        (folder / 'task.json').write_text(json.dumps({'id': task_id, 'platform': 'tieba', 'status': state}), encoding='utf-8')
        rows = [post('新正文', ident, 1800000001000) for ident in args['post_ids']]
        for ident in args['post_ids']:
            if args['comments']:
                rows.extend([comment(ident + '-new-' + str(i), parent=ident)
                             for i in range(args['comments'] + int(self.overflow))])
        path = folder / 'output/data.json'
        path.write_text(json.dumps(rows), encoding='utf-8')
        self.paths[task_id], self.states[task_id] = [path], state
        return task_id

    def status(self, ident):
        return {'status': 'running' if self.waiting else self.states[ident], 'waiting_login': self.waiting}

    def files(self, ident):
        return self.paths[ident]

    async def stop(self, owner):
        assert owner == self.owner
        self.stops.append(owner)
        return True


def setup(tmp_path, **kwargs):
    store = KnowledgeStore(tmp_path)
    baseline = ingest(store, 'before.json', [post(), comment('old')])
    harness = Harness(store)
    adapter = Adapter(tmp_path, **kwargs)
    scheduler = Scheduler(harness, adapter, poll_seconds=.005)
    return store, baseline, harness, adapter, scheduler


def test_version_diff_and_exact_evidence(tmp_path):
    store = KnowledgeStore(tmp_path)
    before = ingest(store, 'before.json', [post(), comment('1', '旧评论'), comment('2', '未复采')])
    after = ingest(store, 'after.json', [post('新正文', observed=1800000001000), comment('1', '改过的评论'), comment('3', '新增评论')])
    result = store.compare_sources([before], [after])
    assert result['counts'] == {'added_posts': 0, 'added_comments': 1, 'changed_posts': 1,
                               'changed_comments': 1, 'unchanged': 0, 'not_observed': 1}
    missing = next(i for i in result['items'] if i['external_id'] == '2')
    assert missing['change'] == 'not_observed' and missing['after'] is None
    assert result['coverage']['absence_policy'] == 'not_observed_does_not_mean_deleted'
    tools = SearchService(store)
    for item in result['items']:
        for version in (item['before'], item['after']):
            for snippet in (version or {}).get('snippets', []):
                read = tools.call('read_evidence', {'evidence_ids': [snippet['evidence_id']]})
                assert read['items'][0]['quote'] == snippet['quote']
    assert all(v['file_hash'] for v in result['source_versions'])


def test_long_body_diff_points_to_changed_text(tmp_path):
    store = KnowledgeStore(tmp_path)
    prefix = '相同前文' * 300
    before = ingest(store, 'before.json', [post(prefix + '旧结论')])
    after = ingest(store, 'after.json', [post(prefix + '新结论', observed=1800000001000)])
    result = store.compare_sources([before], [after])
    row = result['items'][0]
    assert '旧结论' in next(s['quote'] for s in row['before']['snippets'] if s['field'] == 'body')
    assert '新结论' in next(s['quote'] for s in row['after']['snippets'] if s['field'] == 'body')


def test_large_comparison_pages_have_bounded_text_and_stable_cursor(tmp_path):
    store = KnowledgeStore(tmp_path)
    before = ingest(store, 'before.json', [post('旧' * 500, str(i)) for i in range(20)])
    after = ingest(store, 'after.json', [post('新' * 500, str(i), 1800000001000) for i in range(20)])
    first = store.compare_sources([before], [after], limit=50)
    repeat = store.compare_sources([before], [after], limit=50)
    assert len(json.dumps(first['items'], ensure_ascii=False)) < 17000
    assert first['coverage']['returned'] < 20 and first['coverage']['next_cursor']
    assert repeat['coverage']['next_cursor'] == first['coverage']['next_cursor']
    second = store.compare_sources([before], [after], limit=50, cursor=first['coverage']['next_cursor'])
    assert not ({i['entity_id'] for i in first['items']} & {i['entity_id'] for i in second['items']})


def test_restart_interrupts_collection_leases_instead_of_stranding_queue(tmp_path):
    async def run():
        _, _, harness, adapter, scheduler = setup(tmp_path)
        scheduler.enqueue('old-collection', 'collection', {})
        fresh = Scheduler(harness, adapter, poll_seconds=.005)
        assert fresh.get('old-collection')['status'] == 'interrupted'
        job = fresh.submit_refresh(['123'], 0)
        await fresh.tasks[job['id']]
        assert fresh.get(job['id'])['status'] == 'completed'
    asyncio.run(run())


def test_diff_idempotency_scope_and_pagination(tmp_path):
    store = KnowledgeStore(tmp_path)
    before = ingest(store, 'before.json', [post(), post(ident='456')])
    after = ingest(store, 'after.json', [post('改过', observed=1800000001000), post('另一个目标', '456', 1800000001000)] +
                   [comment(str(i)) for i in range(6)])
    result = store.compare_sources([before], [after], limit=2, post_ids=['123'])
    counts = result['counts']
    ids = set()
    while True:
        ids.update(item['entity_id'] for item in result['items'])
        assert all(item['external_id'] != '456' for item in result['items'])
        if not result['coverage']['has_more']:
            break
        result = store.compare_sources([before], [after], limit=2, post_ids=['123'], cursor=result['coverage']['next_cursor'])
    assert len(ids) == 7 and counts['added_comments'] == 6
    identical = store.compare_sources([after], [after])
    assert identical['counts']['unchanged'] == 8 and not identical['items']


def test_source_versions_discovery_excludes_unrelated_and_revoked(tmp_path):
    store = KnowledgeStore(tmp_path)
    old = ingest(store, 'old.json', [post()])
    new = ingest(store, 'new.json', [post('新正文', observed=1800000001000), comment('1')])
    ingest(store, 'other.json', [post(ident='456')])
    tools = SearchService(store)
    result = tools.call('source_versions', {'post_ids': ['123']})
    assert {row['source_id'] for row in result['items']} == {old, new}
    assert result['coverage']['total'] == 2 and all(row['file_hash'] for row in result['items'])
    store.revoke(old)
    assert [row['source_id'] for row in tools.call('source_versions', {'post_ids': ['123']})['items']] == [new]


def test_diff_unavailable_sources_and_stale_cursor(tmp_path):
    store = KnowledgeStore(tmp_path)
    before = ingest(store, 'before.json', [post()])
    after = ingest(store, 'after.json', [post('新正文', observed=1800000001000), comment('new')])
    cursor = store.compare_sources([before], [after], limit=1)['coverage']['next_cursor']
    ingest(store, 'third.json', [post(ident='789')])
    with pytest.raises(KnowledgeError, match='stale_cursor'):
        store.compare_sources([before], [after], limit=1, cursor=cursor)
    store.revoke(before)
    with pytest.raises(KnowledgeError, match='source_unavailable'):
        store.compare_sources([before], [after])


@pytest.mark.parametrize('arguments', [([], []), (['missing'], ['missing']), ('not-array', []), ([], [])])
def test_diff_invalid_inputs(tmp_path, arguments):
    store = KnowledgeStore(tmp_path)
    with pytest.raises(KnowledgeError):
        store.compare_sources(*arguments)


def test_refresh_baseline_changes_and_idempotency(tmp_path):
    async def run():
        store, baseline, _, adapter, scheduler = setup(tmp_path)
        job = scheduler.submit_refresh(['123'], comments_per_post=2, request_id='same-request')
        assert job['status'] == 'queued' and not adapter.calls
        assert scheduler.submit_refresh(['123'], 2, request_id='same-request')['id'] == job['id']
        await scheduler.tasks[job['id']]
        result = scheduler.get(job['id'])
        assert result['status'] == 'completed', result
        assert result['result']['changes']['counts']['added_comments'] == 2
        assert result['result']['changes']['counts']['changed_posts'] == 1
        assert baseline in result['payload']['before_source_ids']
        assert len(adapter.calls) == 1 and adapter.owner is None
        with pytest.raises(KnowledgeError, match='job_id_conflict'):
            scheduler.submit_refresh(['123'], 1, request_id='same-request')
        with store.connection() as conn:
            persisted = conn.execute('SELECT result FROM research_queue WHERE id=?', (job['id'],)).fetchone()[0]
        assert '新正文' not in persisted and '旧正文' not in persisted
        store.revoke(baseline)
        invalid = scheduler.get(job['id'])
        assert invalid['result']['changes'] is None and invalid['result']['changes_error'] == 'source_unavailable'
    asyncio.run(run())


def test_baseline_revoked_while_queued_does_not_recrawl(tmp_path):
    async def run():
        store, baseline, _, adapter, scheduler = setup(tmp_path)
        adapter.owner = 'manual-owner'
        job = scheduler.submit_refresh(['123'])
        await asyncio.sleep(.02)
        store.revoke(baseline)
        adapter.owner = None
        await scheduler.tasks[job['id']]
        result = scheduler.get(job['id'])
        assert result['error'] == 'source_unavailable'
        assert not adapter.calls and not adapter.stops and adapter.owner is None
    asyncio.run(run())


def test_harness_compares_versions_then_reads_before_answer(tmp_path):
    async def run():
        store = KnowledgeStore(tmp_path)
        before = ingest(store, 'before.json', [post()])
        after = ingest(store, 'after.json', [post('新正文', observed=1800000001000)])
        class Model:
            def __init__(self):
                self.calls = 0
            async def complete(self, messages):
                self.calls += 1
                if self.calls == 1:
                    return json.dumps({'action': 'tool', 'name': 'compare_sources', 'arguments':
                        {'before_source_ids': [before], 'after_source_ids': [after]}})
                output = json.loads(messages[-1]['content'])['tool_result_untrusted']
                if self.calls == 2:
                    ids = [s['evidence_id'] for side in ('before', 'after') for s in output['items'][0][side]['snippets'] if s['field'] == 'body']
                    return json.dumps({'action': 'tool', 'name': 'read_evidence', 'arguments': {'evidence_ids': ids}})
                return json.dumps({'action': 'answer', 'outcome': 'answered', 'paragraphs': [
                    {'text': '该帖正文从旧正文变成新正文。', 'evidence_ids': [i['evidence_id'] for i in output['items']]}], 'limitations': []})
        model = Model()
        harness = Harness(store, lambda: model)
        run_id = harness.start(harness.create_session()['id'], '比较两个已导入版本')['run_id']
        await harness.tasks[run_id]
        result = harness.run(run_id)
        assert result['status'] == 'completed', result
        assert [event['tool'] for event in result['events']] == ['compare_sources', 'read_evidence']
        assert len(result['answer']['paragraphs'][0]['evidence_ids']) == 2
    asyncio.run(run())


def test_automatic_waiter_and_refresh_share_one_crawler(tmp_path):
    async def run():
        spec = importlib.util.spec_from_file_location('automatic_p6_fixture', Path(__file__).with_name('test_automatic.py'))
        fx = importlib.util.module_from_spec(spec); spec.loader.exec_module(fx)
        harness, adapter, service, session, _ = fx.prepare(tmp_path)
        ingest(harness.store, 'baseline.json', [post('CS 饰品旧正文', observed=None)])
        adapter.waiting = True
        service.scheduler.poll_seconds = .005
        refresh = service.scheduler.submit_refresh(['123'], 1)
        automatic = service.start_automatic(session, '收集CS帖子')
        for _ in range(300):
            if service.get(automatic['id'])['progress'].get('queue_status') == 'waiting':
                break
            await asyncio.sleep(.01)
        assert adapter.owner == refresh['id']
        assert service.get(automatic['id'])['progress']['queue_status'] == 'waiting'
        await service.cancel(automatic['id'])
        assert adapter.owner == refresh['id'] and not adapter.stops
        assert service.scheduler.get(automatic['id'])['status'] == 'cancelled'
        adapter.waiting = False
        await service.scheduler.tasks[refresh['id']]
        assert service.scheduler.get(refresh['id'])['status'] == 'completed'
        assert adapter.owner is None
    asyncio.run(run())


def test_automatic_and_refresh_complete_serially(tmp_path):
    async def run():
        spec = importlib.util.spec_from_file_location('automatic_p6_fifo', Path(__file__).with_name('test_automatic.py'))
        fx = importlib.util.module_from_spec(spec); spec.loader.exec_module(fx)
        harness, adapter, service, session, _ = fx.prepare(tmp_path)
        ingest(harness.store, 'baseline.json', [post('CS 饰品旧正文', observed=None)])
        adapter.waiting = True
        service.scheduler.poll_seconds = .005
        automatic = service.start_automatic(session, '收集CS帖子')
        for _ in range(300):
            if adapter.owner == automatic['id']:
                break
            await asyncio.sleep(.01)
        assert adapter.owner == automatic['id']
        refresh = service.scheduler.submit_refresh(['123'], 1)
        await asyncio.sleep(.02)
        assert service.scheduler.get(refresh['id'])['status'] == 'queued'
        adapter.waiting = False
        await asyncio.gather(service.tasks[automatic['id']], service.scheduler.tasks[refresh['id']])
        assert service.get(automatic['id'])['status'] == 'completed', service.get(automatic['id'])
        assert service.scheduler.get(refresh['id'])['status'] == 'completed'
        assert adapter.stops == [automatic['id'], refresh['id']]
        assert adapter.owner is None
    asyncio.run(run())


def test_fifo_cancel_waiter_does_not_stop_current_owner(tmp_path):
    async def run():
        _, _, _, adapter, scheduler = setup(tmp_path, waiting=True)
        first = scheduler.submit_refresh(['123'], comments_per_post=1)
        second = scheduler.submit_refresh(['123'], comments_per_post=1)
        await asyncio.sleep(.03)
        assert scheduler.get(first['id'])['status'] == 'waiting_login'
        assert scheduler.get(second['id'])['status'] == 'queued'
        await scheduler.cancel(second['id'])
        assert not adapter.stops and adapter.owner == first['id']
        adapter.waiting = False
        await scheduler.tasks[first['id']]
        assert [owner for owner, _ in adapter.calls] == [first['id']]
        assert scheduler.get(second['id'])['status'] == 'cancelled'
    asyncio.run(run())


def test_fifo_two_jobs_complete_in_order(tmp_path):
    async def run():
        _, _, _, adapter, scheduler = setup(tmp_path)
        first = scheduler.submit_refresh(['123'], 0)
        second = scheduler.submit_refresh(['123'], 0)
        tasks = list(scheduler.tasks.values())
        await asyncio.gather(*tasks)
        assert [owner for owner, _ in adapter.calls] == [first['id'], second['id']]
        assert all(scheduler.get(j['id'])['status'] == 'completed' for j in (first, second))
        assert all(args['comments'] == 0 for _, args in adapter.calls)
    asyncio.run(run())


def test_cancel_immediately_and_active_cleanup(tmp_path):
    async def run():
        _, _, _, adapter, scheduler = setup(tmp_path, waiting=True)
        instant = scheduler.submit_refresh(['123'])
        assert (await scheduler.cancel(instant['id']))['status'] == 'cancelled'
        assert not adapter.calls and not adapter.stops
        active_job = scheduler.submit_refresh(['123'])
        await asyncio.sleep(.03)
        await scheduler.cancel(active_job['id'])
        assert adapter.stops == [active_job['id']] and adapter.owner is None
        assert scheduler.get(active_job['id'])['status'] == 'cancelled'
    asyncio.run(run())


def test_external_crawler_busy_waits_and_queue_deadline(tmp_path):
    async def run():
        _, _, _, adapter, scheduler = setup(tmp_path)
        adapter.owner = 'manual-owner'
        scheduler.enqueue('lease', 'collection', {})
        with pytest.raises(TimeoutError):
            await scheduler.acquire('lease', time.monotonic() + .02)
        assert adapter.owner == 'manual-owner' and not adapter.stops
        adapter.owner = None
        await scheduler.acquire('lease', time.monotonic() + 1)
        assert adapter.owner == 'lease'
        await adapter.release('lease')
        scheduler._update('lease', status='completed')
    asyncio.run(run())


def test_restart_pauses_waiters_no_implicit_network_and_resume(tmp_path):
    async def run():
        _, _, harness, adapter, scheduler = setup(tmp_path, waiting=True)
        first = scheduler.submit_refresh(['123'])
        second = scheduler.submit_refresh(['123'])
        await asyncio.sleep(.03)
        await scheduler.shutdown()
        assert scheduler.get(first['id'])['status'] == 'interrupted'
        assert scheduler.get(second['id'])['status'] == 'paused'
        calls = len(adapter.calls)
        fresh = Scheduler(harness, adapter, poll_seconds=.005)
        await asyncio.sleep(.01)
        assert len(adapter.calls) == calls
        adapter.waiting = False
        fresh.resume(second['id'])
        await fresh.tasks[second['id']]
        assert fresh.get(second['id'])['status'] == 'completed'
        assert len(adapter.calls) == calls + 1
    asyncio.run(run())


@pytest.mark.parametrize('options,error', [({'overflow': True}, 'crawler_budget_violation'),
                                          ({'incomplete': True}, 'recrawl_incomplete'),
                                          ({'start_fails': True}, 'crawler_start_failed')])
def test_refresh_partial_failures_preserve_output_and_cleanup(tmp_path, options, error):
    async def run():
        _, _, _, adapter, scheduler = setup(tmp_path, **options)
        job = scheduler.submit_refresh(['123'], 1)
        await scheduler.tasks[job['id']]
        result = scheduler.get(job['id'])
        assert result['error'] == error and result['status'] in ('partial', 'failed')
        assert adapter.owner is None and adapter.stops == [job['id']]
    asyncio.run(run())


def test_queue_limits_unknown_targets_and_maintenance(tmp_path):
    async def run():
        store, _, _, _, scheduler = setup(tmp_path)
        with pytest.raises(KnowledgeError, match='post_not_imported'):
            scheduler.submit_refresh(['999'])
        for i in range(20):
            scheduler.enqueue(str(i), 'collection', {})
        with pytest.raises(KnowledgeError, match='queue_full'):
            scheduler.submit_refresh(['123'])
        report = store.maintenance()
        assert report['source_files_deleted'] == 0 and report['counts']['active_snapshots'] == 2
    asyncio.run(run())


def test_http_refresh_compare_and_no_extra_config_fields(tmp_path):
    async def run():
        _, baseline, harness, adapter, _ = setup(tmp_path)
        app = FastAPI()
        router = create_router(harness, adapter)
        app.include_router(router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            rejected = await client.post('/api/research/queue/refresh', json={'post_ids': ['123'], 'cookies': 'private'})
            assert rejected.status_code == 422
            response = await client.post('/api/research/queue/refresh', json={'post_ids': ['123'], 'comments_per_post': 0, 'request_id': 'http-test'})
            assert response.status_code == 200 and response.json()['status'] == 'queued'
            for _ in range(100):
                result = (await client.get('/api/research/queue/jobs/http-test')).json()
                if result['status'] not in ('queued', 'reserved', 'running', 'waiting_login', 'importing'):
                    break
                await asyncio.sleep(.01)
            assert result['status'] == 'completed', result
            compared = await client.post('/api/research/sources/compare', json={'before_source_ids': [baseline],
                'after_source_ids': result['result']['after_source_ids']})
            assert compared.status_code == 200 and compared.json()['counts']['changed_posts'] == 1
            assert (await client.get('/api/research/queue/jobs')).status_code == 200
            assert (await client.post('/api/research/maintenance')).status_code == 200
    asyncio.run(run())
