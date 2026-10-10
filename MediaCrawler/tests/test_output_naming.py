from pathlib import Path
import re

import config
from tools.output_naming import output_filename
from tools.async_file_writer import AsyncFileWriter


def test_task_names_are_unique_and_share_identity(tmp_path, monkeypatch):
    names = []
    for ident in ('a' * 32, 'b' * 32):
        monkeypatch.setattr(config, 'SAVE_DATA_PATH', str(tmp_path / 'tasks' / ident / 'output'))
        writer = AsyncFileWriter('tieba', 'search')
        first = writer._get_file_path('json', 'contents')
        assert first == AsyncFileWriter('tieba', 'search')._get_file_path('json', 'contents')
        comment = Path(writer._get_file_path('json', 'comments')).name
        assert comment.replace('_comments_', '_contents_') == Path(first).name
        assert re.fullmatch(r'search_contents_tieba_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_[a-f0-9]{12}\.json', Path(first).name)
        names.append(Path(first).name)
    assert names[0] != names[1]


def test_cli_and_formats_use_stable_run_identifier(monkeypatch):
    monkeypatch.setattr(config, 'SAVE_DATA_PATH', '')
    for ext in ('json', 'jsonl', 'csv', 'xlsx'):
        name = output_filename('tieba', 'detail', 'contents', ext)
        assert name == output_filename('tieba', 'detail', 'contents', ext)
        assert name.endswith('.' + ext) and '/' not in name and ':' not in name
