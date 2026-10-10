"""Stable names shared by all writers in one crawl process."""
from datetime import datetime
from pathlib import Path
import re
import uuid

import config

_STARTED = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
_RUN_ID = uuid.uuid4().hex[:12]


def output_filename(platform: str, crawler_type: str, item_type: str, extension: str) -> str:
    # Web tasks carry their identity in the server-controlled output directory.
    path = Path(config.SAVE_DATA_PATH) if config.SAVE_DATA_PATH else None
    ident = _RUN_ID
    if path and path.name == 'output' and path.parent.parent.name == 'tasks' and re.fullmatch(r'[a-f0-9]{32}', path.parent.name):
        ident = path.parent.name[:12]
    return f'{crawler_type}_{item_type}_{platform}_{_STARTED}_{ident}.{extension}'
