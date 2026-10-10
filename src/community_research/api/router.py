from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..agent.runtime import Harness
from ..agent.model import ChatModel
from ..knowledge import KnowledgeStore, KnowledgeError


class Ask(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    text: str = Field(min_length=1, max_length=4000)
    budget: dict | None = None


class CollectPlan(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    text: str = Field(min_length=1, max_length=4000)
    queries: list[str] | None = None


class CollectExecute(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    plan: dict


class ReviewCorrection(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    snapshot_id: str = Field(min_length=1, max_length=100)
    label: str
    reason: str = Field(default='', max_length=300)


class RefreshPosts(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    post_ids: list[str] = Field(min_length=1, max_length=20)
    comments_per_post: int = Field(default=20, ge=0, le=20)
    seconds: int = Field(default=180, ge=30, le=300)
    request_id: str | None = Field(default=None, min_length=1, max_length=100)


class SourceComparison(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    before_source_ids: list[str] = Field(max_length=100)
    after_source_ids: list[str] = Field(min_length=1, max_length=100)
    post_ids: list[str] | None = Field(default=None, max_length=20)
    limit: int = Field(default=20, ge=1, le=50)
    cursor: str | None = None


def create_router(harness=None, collection_adapter=None):
    runtime = harness or Harness(KnowledgeStore())
    router = APIRouter(prefix='/api/research', tags=['research'])
    from ..agent.collection import CollectionService
    from ..agent.model import ModelError
    import asyncio
    collector = CollectionService(runtime, collection_adapter)

    def available():
        if collector is None:
            raise HTTPException(503, 'collection_unavailable')
        return collector

    async def collection_call(fn, *args):
        try:
            return await fn(*args)
        except (KnowledgeError, ModelError) as exc:
            raise HTTPException(409 if str(exc) in ('crawler_busy', 'session_busy', 'plan_already_started') else 400, str(exc)) from None
        except TimeoutError:
            raise HTTPException(504, 'collection_plan_timeout') from None

    @router.post('/sessions/{session_id}/messages')
    async def message(session_id: str, request: Ask):
        if request.budget is not None:
            raise HTTPException(400,'use_natural_language_limits')
        return checked(collector.start_automatic,session_id,request.text)

    @router.get('/sessions/{session_id}/collections')
    async def collections(session_id: str):
        return available().list(session_id)

    @router.post('/sessions/{session_id}/collections')
    async def propose(session_id: str, request: CollectPlan):
        return await collection_call(available().propose, session_id, request.text, request.queries)

    @router.post('/collections/{ident}/execute')
    async def execute(ident: str, request: CollectExecute):
        return await collection_call(available().execute, ident, request.plan)

    @router.post('/collections/{ident}/cancel')
    async def cancel_collection(ident: str):
        return await collection_call(available().cancel, ident)

    @router.post('/collections/{ident}/review-corrections')
    async def correct_review(ident: str, request: ReviewCorrection):
        return checked(available().correct_review, ident, request.snapshot_id, request.label, request.reason)

    def checked(fn, *args):
        try:
            return fn(*args)
        except KnowledgeError as exc:
            code = 404 if str(exc).endswith('_not_found') else 409 if str(exc) == 'session_busy' else 400
            raise HTTPException(code, str(exc)) from None

    @router.get('/queue/jobs')
    async def queue_jobs(limit: int = 50):
        return checked(collector.scheduler.list, limit)

    @router.post('/queue/refresh')
    async def refresh_posts(request: RefreshPosts):
        return checked(collector.scheduler.submit_refresh, request.post_ids, request.comments_per_post,
                       request.seconds, request.request_id)

    @router.get('/queue/jobs/{ident}')
    async def queue_job(ident: str):
        return checked(collector.scheduler.get, ident)

    @router.post('/queue/jobs/{ident}/cancel')
    async def cancel_job(ident: str):
        return await collection_call(collector.scheduler.cancel, ident)

    @router.post('/queue/jobs/{ident}/resume')
    async def resume_job(ident: str):
        return checked(collector.scheduler.resume, ident)

    @router.post('/sources/compare')
    async def compare_sources(request: SourceComparison):
        return checked(runtime.store.compare_sources, request.before_source_ids, request.after_source_ids,
                       request.limit, request.cursor, request.post_ids)

    @router.get('/sources')
    async def sources():
        return checked(runtime.store.list_sources)

    @router.post('/maintenance')
    async def maintenance():
        return checked(runtime.store.maintenance)

    @router.get('/config')
    async def config():
        model = ChatModel(runtime.store.root)
        return {'configured': model.configured, 'model': model.model, 'scope': 'automatic', 'collection_enabled': collection_adapter is not None, 'automatic_enabled': collection_adapter is not None}

    @router.get('/sessions')
    async def sessions():
        return runtime.sessions()

    @router.post('/sessions')
    async def create():
        return runtime.create_session()

    @router.get('/sessions/{session_id}')
    async def session(session_id: str):
        return checked(runtime.session, session_id)

    @router.delete('/sessions/{session_id}')
    async def delete_session(session_id: str):
        return checked(runtime.delete_session, session_id)

    @router.post('/sessions/{session_id}/runs')
    async def ask(session_id: str, request: Ask):
        return checked(runtime.start, session_id, request.text, request.budget)

    @router.get('/runs/{run_id}')
    async def run(run_id: str):
        return checked(runtime.run, run_id)

    @router.post('/runs/{run_id}/cancel')
    async def cancel(run_id: str):
        return checked(runtime.cancel, run_id)

    @router.get('/runs/{run_id}/evidence/{evidence_id}')
    async def evidence(run_id: str, evidence_id: str):
        record = checked(runtime.run, run_id)
        refs = {i for p in (record.get('answer') or {}).get('paragraphs', []) for i in p['evidence_ids']}
        if evidence_id not in refs:
            raise HTTPException(404, 'evidence_not_in_answer')
        result = runtime.tools.call('read_evidence', {'evidence_ids': [evidence_id], 'include_context': True})
        if result['error']:
            raise HTTPException(410, result['error']['code'])
        item = result['items'][0]
        snapshot = checked(runtime.store.read_snapshot, item['snapshot_id'])
        contexts = []
        for context in item['context']:
            if context.get('evidence_ids'):
                read = runtime.tools.call('read_evidence', {'evidence_ids': context['evidence_ids']})
                contexts.append({**context, 'items': read['items'], 'error': read['error']})
            else:
                contexts.append(context)
        # Full original field is bounded in the HTTP response; locate around exact evidence.
        text = snapshot['payload'].get(item['field']) or ''
        start, end = max(0, item['start'] - 2000), min(len(text), item['end'] + 2000)
        return {'evidence': item, 'context': contexts, 'text': text[start:end], 'text_start': start,
                'external_id': snapshot['payload']['external_id'], 'kind': snapshot['payload']['kind']}

    async def shutdown():
        if collector:
            await collector.shutdown()
        for ident in list(runtime.tasks):
            runtime.cancel(ident)

    router.add_event_handler('shutdown', shutdown)

    return router
