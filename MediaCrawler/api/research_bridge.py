"""The only adapter allowed to touch crawler process state; no credentials returned."""
from .services import crawler_manager
from .schemas import CrawlerStartRequest
from . import task_store


class CollectionAdapter:
    async def reserve(self, owner):
        return await crawler_manager.reserve(owner)

    async def release(self, owner):
        await crawler_manager.release(owner)

    async def start(self, owner, query=None, post_ids=None, notes=5, comments=10, latest_comments=False):
        request = CrawlerStartRequest(platform='tieba', login_type='qrcode', crawler_type='detail' if post_ids else 'search',
                                      keywords=query or '', specified_ids=','.join(post_ids or []), enable_comments=bool(post_ids) and comments > 0,
                                      enable_sub_comments=False, save_option='json', headless=False,
                                      max_notes_count=notes, max_comments_count=max(1, comments),
                                      comment_order='latest' if latest_comments else 'oldest')
        if not await crawler_manager.start(request, owner=owner, shared_session=True):
            return None
        return crawler_manager.task_id

    def status(self, task_id):
        crawler_manager.sync_session_result(task_id)
        row = task_store.load(task_id)
        waiting = False
        if crawler_manager.task_id == task_id:
            for line in crawler_manager.logs:
                if '[RESEARCH_LOGIN_REQUIRED]' in line.message:
                    waiting = True
                elif '[RESEARCH_LOGIN_READY]' in line.message:
                    waiting = False
        return {'status': row['status'], 'waiting_login': waiting, 'exit_code': row.get('exit_code')}

    def files(self, task_id):
        return [str(p) for p in task_store.output_files(task_id) if p.suffix.lower() in ('.json', '.jsonl')]

    async def stop(self, owner):
        return await crawler_manager.stop(owner=owner)
