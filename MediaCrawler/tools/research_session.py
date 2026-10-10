"""Sequential assistant branches inside one initialized Tieba browser context."""
import asyncio
import json
import logging
import os
from pathlib import Path
import time

import config
from api import task_store
from var import crawler_type_var, source_keyword_var


class BranchErrors(logging.Handler):
    def __init__(self):
        super().__init__(logging.ERROR)
        self.seen = False

    def emit(self, record):
        self.seen = True


async def run_branches(crawler):
    folder = Path(os.environ['RESEARCH_SESSION_DIR']).resolve()
    parent = int(os.environ['RESEARCH_PARENT_PID'])
    async def stop_requested():
        while not (folder / 'stop').exists() and task_store.process_alive(parent):
            await asyncio.sleep(.2)

    stop = asyncio.create_task(stop_requested())
    idle_since = time.monotonic()
    active = None
    try:
        while not stop.done() and time.monotonic()-idle_since < 330:
            request = folder / 'request.json'
            if not request.exists():
                await asyncio.sleep(.1)
                continue
            ident = json.loads(request.read_text(encoding='utf-8'))['task_id']
            row = task_store.load(ident)
            request.unlink()
            if row['platform'] != 'tieba' or row['crawler_type'] not in ('search','detail') or row['save_option'] != 'json':
                raise ValueError('invalid_session_branch')
            config.CRAWLER_TYPE = row['crawler_type']
            config.KEYWORDS = row['keywords'] or ''
            config.TIEBA_SPECIFIED_ID_LIST = (row['specified_ids'] or '').split(',') if row['specified_ids'] else []
            config.CRAWLER_MAX_NOTES_COUNT = row['max_notes_count']
            config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES = row['max_comments_count']
            config.ENABLE_GET_COMMENTS = row['enable_comments']
            config.ENABLE_GET_SUB_COMMENTS = False
            config.TIEBA_COMMENT_ORDER = row.get('comment_order', 'oldest')
            config.START_PAGE = row['start_page']
            config.SAVE_DATA_PATH = str(task_store.task_dir(ident) / 'output')
            crawler_type_var.set(config.CRAWLER_TYPE)
            source_keyword_var.set('')
            handler = BranchErrors()
            logging.getLogger('MediaCrawler').addHandler(handler)
            status, code = 'completed', 0
            try:
                active = asyncio.create_task(crawler.search() if config.CRAWLER_TYPE=='search' else crawler.get_specified_notes())
                done, _ = await asyncio.wait([active,stop],return_when=asyncio.FIRST_COMPLETED)
                if stop in done:
                    active.cancel()
                    await asyncio.gather(active,return_exceptions=True)
                    status, code = 'stopped', 1
                else:
                    await active
                    if handler.seen:
                        status = 'completed_with_errors'
            except Exception:
                status, code = 'failed', 1
                logging.getLogger('MediaCrawler').exception('Research branch failed')
            finally:
                logging.getLogger('MediaCrawler').removeHandler(handler)
            temporary = folder / (ident+'.tmp')
            temporary.write_text(json.dumps({'status':status,'exit_code':code}),encoding='utf-8')
            temporary.replace(folder / (ident+'.json'))
            print('[RESEARCH_BRANCH_FINISHED] '+ident,flush=True)
            idle_since = time.monotonic()
            if status in ('failed','stopped'):
                break
    finally:
        stop.cancel()
        if active and not active.done():
            active.cancel()
        await asyncio.gather(stop,*([active] if active else []),return_exceptions=True)
