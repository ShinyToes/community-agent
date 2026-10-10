"""Persistent FIFO for one crawler; no automatic network replay after restart."""
import asyncio
import json
import time
import uuid

from ..knowledge.store import KnowledgeError, encode, now, digest
from ..knowledge.search import SearchService, strings

ACTIVE = ('queued', 'reserved', 'running', 'waiting_login', 'importing')
SCHEMA = '''CREATE TABLE IF NOT EXISTS research_queue(
 sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
 kind TEXT NOT NULL, request_hash TEXT NOT NULL, payload TEXT NOT NULL,
 status TEXT NOT NULL, created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
 result TEXT NOT NULL, error TEXT);
CREATE INDEX IF NOT EXISTS queue_fifo ON research_queue(status,sequence);'''


class Scheduler:
    def __init__(self, harness, adapter, poll_seconds=.5):
        self.harness, self.store, self.adapter = harness, harness.store, adapter
        self.poll_seconds = poll_seconds
        self.tasks = {}
        self._lock = asyncio.Lock()
        with self.store.connection() as conn:
            conn.executescript(SCHEMA)
            conn.execute("UPDATE research_queue SET status='paused',error='restart_requires_resume' WHERE status='queued' AND kind='refresh'")
            conn.execute("UPDATE research_queue SET status='interrupted',error='service_restarted',finished_at=? WHERE status IN ('reserved','running','waiting_login','importing') OR (status='queued' AND kind='collection')", (now(),))

    def get(self, ident):
        with self.store.connection() as conn:
            row = conn.execute('SELECT * FROM research_queue WHERE id=?', (ident,)).fetchone()
        if not row:
            raise KnowledgeError('job_not_found')
        result = dict(row)
        for key in ('payload', 'result'):
            result[key] = json.loads(result[key])
        if result['kind'] == 'refresh' and result['result'].get('changes') is not None:
            # The queue persists IDs, not a second copy of revocable source text.
            try:
                result['result']['changes'] = self.store.compare_sources(result['payload']['before_source_ids'],
                    result['result']['after_source_ids'], post_ids=result['payload']['post_ids'])
            except KnowledgeError as exc:
                result['result']['changes'] = None
                result['result']['changes_error'] = exc.code
        return result

    def list(self, limit=50):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise KnowledgeError('invalid_arguments')
        with self.store.connection() as conn:
            ids = [r[0] for r in conn.execute('SELECT id FROM research_queue ORDER BY sequence DESC LIMIT ?', (limit,))]
        return [self.get(i) for i in ids]

    def _update(self, ident, **values):
        if values.keys() - {'status', 'error', 'result', 'started_at', 'finished_at'}:
            raise ValueError('invalid update')
        with self.store.connection() as conn:
            from .working_memory import shrink_result
            conn.execute('UPDATE research_queue SET ' + ','.join(k + '=?' for k in values) + ' WHERE id=?',
                         tuple(encode(shrink_result(v)) if k == 'result' else v for k, v in values.items()) + (ident,))

    def enqueue(self, ident, kind, payload):
        fingerprint = digest(encode([kind, payload]).encode())
        with self.store.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            existing = conn.execute('SELECT request_hash FROM research_queue WHERE id=?', (ident,)).fetchone()
            if existing:
                if existing['request_hash'] != fingerprint:
                    raise KnowledgeError('job_id_conflict')
                return False
            if conn.execute("SELECT COUNT(*) FROM research_queue WHERE status IN ('queued','reserved','running','waiting_login','importing','paused')").fetchone()[0] >= 20:
                raise KnowledgeError('queue_full')
            conn.execute('INSERT INTO research_queue(id,kind,request_hash,payload,status,created_at,result) VALUES(?,?,?,?,?,?,?)',
                         (ident, kind, fingerprint, encode(payload), 'queued', now(), '{}'))
        return True

    async def acquire(self, ident, deadline):
        if self.adapter is None:
            raise KnowledgeError('collection_unavailable')
        while time.monotonic() < deadline:
            if self.get(ident)['status'] != 'queued':
                raise KnowledgeError('job_not_queued')
            async with self._lock:
                with self.store.connection() as conn:
                    first = conn.execute("SELECT id FROM research_queue WHERE status='queued' ORDER BY sequence LIMIT 1").fetchone()
                    busy = conn.execute("SELECT 1 FROM research_queue WHERE status IN ('reserved','running','waiting_login','importing')").fetchone()
                if first and first['id'] == ident and not busy:
                    reserved = await self.adapter.reserve(ident)
                    if reserved:
                        # Cancellation of a waiting task must never cancel another owner's process.
                        try:
                            self._update(ident, status='reserved', started_at=now())
                        except BaseException:
                            await self.adapter.release(ident)
                            raise
                        return
            await asyncio.sleep(self.poll_seconds)
        raise TimeoutError()

    def submit_refresh(self, post_ids, comments_per_post=20, seconds=180, request_id=None):
        targets = strings(post_ids, 20, 32)
        if not targets or any(not p.isascii() or not p.isdigit() for p in targets):
            raise KnowledgeError('invalid_post_ids')
        if type(comments_per_post) is not int or not 0 <= comments_per_post <= 20 or type(seconds) is not int or not 30 <= seconds <= 300:
            raise KnowledgeError('invalid_budget')
        if self.adapter is None:
            raise KnowledgeError('collection_unavailable')
        if request_id is not None and (not isinstance(request_id, str) or not 1 <= len(request_id) <= 100):
            raise KnowledgeError('invalid_arguments')
        ident = request_id or uuid.uuid4().hex
        request = {'post_ids': targets, 'comments_per_post': comments_per_post, 'seconds': seconds}
        with self.store.connection() as conn:
            previous = conn.execute('SELECT payload FROM research_queue WHERE id=?', (ident,)).fetchone()
        if previous:
            saved = json.loads(previous[0])
            if any(saved.get(k) != v for k, v in request.items()):
                raise KnowledgeError('job_id_conflict')
            return self.get(ident)
        self.store.refresh()
        with self.store.connection() as conn:
            catalog = SearchService._catalog(conn, platform='tieba')
        known = {r['external_id'] for r in catalog if r['kind'] == 'post'}
        if set(targets) - known:
            raise KnowledgeError('post_not_imported')
        baseline = sorted({r['source_id'] for r in catalog if
            (r['external_id'] if r['kind'] == 'post' else json.loads(r['payload'])['post_external_id']) in targets})
        if len(baseline) > 100:
            raise KnowledgeError('too_many_baseline_sources')
        self.enqueue(ident, 'refresh', {**request, 'before_source_ids': baseline})
        self._launch(ident)
        return self.get(ident)

    def _launch(self, ident):
        task = asyncio.create_task(self._refresh(ident))
        self.tasks[ident] = task
        task.add_done_callback(lambda _: self.tasks.pop(ident, None))

    def resume(self, ident):
        job = self.get(ident)
        if job['kind'] != 'refresh' or job['status'] != 'paused':
            raise KnowledgeError('job_not_paused')
        self._update(ident, status='queued', error=None)
        self._launch(ident)
        return self.get(ident)

    async def cancel(self, ident):
        job = self.get(ident)
        if job['kind'] != 'refresh':
            raise KnowledgeError('use_collection_cancel')
        task = self.tasks.get(ident)
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if self.get(ident)['status'] in ACTIVE:
                self._update(ident, status='cancelled', error='cancelled', finished_at=now())
        elif job['status'] in ('queued', 'paused'):
            self._update(ident, status='cancelled', error='cancelled', finished_at=now())
        return self.get(ident)

    async def _refresh(self, ident):
        job = self.get(ident)
        payload = job['payload']
        result = {'before_source_ids': payload['before_source_ids'], 'after_source_ids': [], 'task_id': None,
                  'imports': [], 'changes': None, 'coverage': 'bounded_recrawl_not_complete_comment_history'}
        deadline = time.monotonic() + payload['seconds']
        reserved = False
        launch_attempted = False
        terminal, error = 'failed', None
        try:
            async with asyncio.timeout(payload['seconds']):
                await self.acquire(ident, deadline)
                reserved = True
                # A queued job can outlive its baseline files. Check before any network work.
                self.store.compare_sources(payload['before_source_ids'], payload['before_source_ids'],
                                           post_ids=payload['post_ids'])
                self._update(ident, status='running')
                launch_attempted = True
                task_id = await self.adapter.start(ident, post_ids=payload['post_ids'],
                    notes=len(payload['post_ids']), comments=payload['comments_per_post'], latest_comments=True)
                if not task_id:
                    raise KnowledgeError('crawler_start_failed')
                result['task_id'] = task_id
                self._update(ident, result=result)
                while True:
                    state = self.adapter.status(task_id)
                    if state['status'] not in ('starting', 'running', 'stopping'):
                        break
                    self._update(ident, status='waiting_login' if state.get('waiting_login') else 'running')
                    await asyncio.sleep(self.poll_seconds)
                self._update(ident, status='importing')
                for path in self.adapter.files(task_id):
                    source = self.store.register_source(path, platform='tieba', source_type='task',
                        task_id=task_id, source_timezone='Asia/Shanghai')
                    report = await asyncio.to_thread(self.store.import_source, source['id'])
                    result['after_source_ids'].append(source['id'])
                    result['imports'].append(report)
                    self._update(ident, result=result)
                if not result['after_source_ids']:
                    raise KnowledgeError('collection_no_data')
                with self.store.connection() as conn:
                    rows = SearchService._latest(SearchService._catalog(conn, source_ids=result['after_source_ids']))
                posts = [r for r in rows if r['kind'] == 'post']
                comments = [r for r in rows if r['kind'] == 'comment']
                comment_counts = {}
                for row in comments:
                    parent = json.loads(row['payload'])['post_external_id']
                    comment_counts[parent] = comment_counts.get(parent, 0) + 1
                if any(r['external_id'] not in payload['post_ids'] for r in posts) or any(
                    p not in payload['post_ids'] or n > payload['comments_per_post'] for p, n in comment_counts.items()) or len(posts) > len(payload['post_ids']):
                    raise KnowledgeError('crawler_budget_violation')
                result['changes'] = await asyncio.to_thread(self.store.compare_sources,
                    payload['before_source_ids'], result['after_source_ids'], 20, None, payload['post_ids'])
                self._update(ident, result=result)
                observed = {r['external_id'] for r in posts}
                incomplete = state['status'] != 'completed' or any(r['status'] != 'completed' for r in result['imports']) or observed != set(payload['post_ids'])
                terminal = 'partial' if incomplete else 'completed'
                error = 'recrawl_incomplete' if incomplete else None
        except asyncio.CancelledError:
            terminal, error = 'cancelled', 'cancelled'
        except TimeoutError:
            terminal = 'partial' if result['after_source_ids'] else 'failed'
            error = 'collection_timeout' if reserved else 'queue_timeout'
        except KnowledgeError as exc:
            terminal = 'partial' if result['after_source_ids'] else 'failed'
            error = exc.code
        except Exception:
            terminal, error = 'failed', 'refresh_internal_error'
        finally:
            if reserved:
                try:
                    if launch_attempted:
                        stopped = await self.adapter.stop(ident)
                        if stopped is False and result['task_id']:
                            terminal, error = 'failed', 'crawler_cleanup_failed'
                except Exception:
                    terminal, error = 'failed', 'crawler_cleanup_failed'
                finally:
                    await self.adapter.release(ident)
            self._update(ident, status=terminal, error=error, result=result, finished_at=now())

    async def shutdown(self):
        jobs = {ident: self.get(ident)['status'] for ident in self.tasks}
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for ident, status in jobs.items():
            if status == 'queued':
                self._update(ident, status='paused', error='restart_requires_resume', finished_at=None)
            else:
                self._update(ident, status='interrupted', error='service_restarted', finished_at=now())
