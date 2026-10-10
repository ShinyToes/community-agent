import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from community_research.knowledge import KnowledgeError, KnowledgeStore


@pytest.fixture
def store(tmp_path):
    return KnowledgeStore(tmp_path)


def write(store, name, rows):
    path = store.root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
    return path


def ingest(store, name, rows, **kwargs):
    path = write(store, name, rows)
    source = store.register_source(path, platform='tieba', **kwargs)
    return source, store.import_source(source['id'])


def post(**changes):
    return dict(note_id='123', title='CS', desc='饰品讨论', publish_time='2026-09-18 12:00:00', **changes)


def test_idempotency_and_multiple_origins(store):
    source, report = ingest(store, 'a.json', [post(source_keyword='cs')])
    original = (store.root / 'a.json').read_bytes()
    repeat = store.import_source(source['id'])
    assert (repeat['new_entities'], repeat['new_snapshots'], repeat['new_occurrences'], repeat['skipped']) == (0, 0, 0, 1)
    other, result = ingest(store, 'b.json', [post(source_keyword='饰品', last_modify_ts=1789717243804)])
    assert result['new_snapshots'] == 0 and result['new_occurrences'] == 1
    snapshot = store.list_snapshots()[0]['snapshot_id']
    assert len(store.read_snapshot(snapshot)['sources']) == 2
    store.revoke(source['id'])
    assert len(store.read_snapshot(snapshot)['sources']) == 1
    store.revoke(other['id'])
    with pytest.raises(KnowledgeError, match='evidence_unavailable'):
        store.read_snapshot(snapshot)
    with store.connection() as conn:
        assert conn.execute('SELECT payload FROM snapshots').fetchone()[0] is None
    assert (store.root / 'a.json').read_bytes() == original


def test_overwrite_creates_new_source_and_snapshot(store):
    source, _ = ingest(store, 'a.json', [post()])
    old = store.list_snapshots()[0]['snapshot_id']
    row = post(); row['desc'] = '新正文'
    other, result = ingest(store, 'a.json', [row])
    assert other['id'] != source['id'] and result['new_entities'] == 0
    assert result['new_snapshots'] == 1
    assert {s['id']: s['status'] for s in store.list_sources()}[source['id']] == 'superseded'
    with pytest.raises(KnowledgeError, match='evidence_unavailable'):
        store.read_snapshot(old)


def test_missing_file_invalidates_read(store):
    ingest(store, 'a.json', [post()])
    snapshot = store.list_snapshots()[0]['snapshot_id']
    (store.root / 'a.json').unlink()
    assert store.list_snapshots() == []
    assert store.list_sources()[0]['status'] == 'missing'
    with pytest.raises(KnowledgeError):
        store.read_snapshot(snapshot)


def test_comment_relations_late_resolution_and_cross_post_parent(store):
    ingest(store, 'c.json', [{'comment_id': 'c', 'note_id': '123', 'parent_comment_id': 'p', 'content': '回复'}])
    snapshot = store.list_snapshots()[0]['snapshot_id']
    assert store.read_snapshot(snapshot)['relations']['post']['status'] == 'unresolved'
    ingest(store, 'p.json', [post(), {'comment_id': 'p', 'note_id': '999', 'content': '另一帖子'}])
    relations = store.read_snapshot(snapshot)['relations']
    assert relations['post']['status'] == 'resolved'
    assert relations['parent']['status'] == 'unresolved'
    ingest(store, 'parent.json', [{'comment_id': 'p', 'note_id': '123', 'content': '正确父评论', 'last_modify_ts': 1789717243804}])
    assert store.read_snapshot(snapshot)['relations']['parent']['status'] == 'resolved'


def test_bad_records_and_empty_body(store):
    _, report = ingest(store, 'a.json', [None, {}, {'comment_id': '1'}, {'note_id': True}, {'note_id': 'empty', 'desc': ''}])
    assert report['status'] == 'partial' and report['valid'] == 1
    assert [r['locator'] for r in report['errors']] == [1, 2, 3, 4]
    assert report['warnings'] == [{'locator': 5, 'code': 'empty_body'}]
    assert store.reports()[0] == report


@pytest.mark.parametrize('raw', ['{broken', '{}', '\ufeff{broken'])
def test_bad_json_whole_file(store, raw):
    path = store.root / 'bad.json'; path.write_text(raw, encoding='utf-8')
    source = store.register_source(path, platform='tieba')
    report = store.import_source(source['id'])
    assert report['status'] == 'failed' and report['new_entities'] == 0


def test_jsonl_reports_physical_lines(store):
    path = store.root / 'a.jsonl'
    path.write_text('\ufeff' + json.dumps(post()) + '\n\ninvalid\n' + json.dumps({'note_id': '2', 'desc': 'body'}), encoding='utf-8')
    source = store.register_source(path, platform='tieba')
    report = store.import_source(source['id'])
    assert report['status'] == 'partial' and report['read'] == 3 and report['valid'] == 2
    assert report['errors'] == [{'locator': 3, 'code': 'invalid_json_line'}]


@pytest.mark.parametrize('zone,raw,expected,basis', [
    (None, '2026-09-18 12:00:00', None, 'unknown'),
    ('Asia/Shanghai', '2026-09-18 12:00:00', '2026-09-18T04:00:00Z', 'source_declared:Asia/Shanghai'),
    (None, '2026-09-18T12:00:00+08:00', '2026-09-18T04:00:00Z', 'source_explicit'),
])
def test_time_semantics(store, zone, raw, expected, basis):
    row = post(); row['publish_time'] = raw
    ingest(store, 'a.json', [row], source_timezone=zone)
    occurrence = store.read_snapshot(store.list_snapshots()[0]['snapshot_id'])['sources'][0]
    assert occurrence['published_at_utc'] == expected and occurrence['timezone_basis'] == basis


def test_paths_and_platform_are_explicit(store):
    path = write(store, 'a.json', [post()])
    with pytest.raises(KnowledgeError, match='unsupported_platform'):
        store.register_source(path, platform='bili')
    with pytest.raises(KnowledgeError, match='invalid_source_path'):
        store.register_source('../outside.json', platform='tieba')
    with pytest.raises(KnowledgeError, match='invalid_timezone'):
        store.register_source(path, platform='tieba', source_timezone='made-up')


def task_source(store, status='stopped'):
    ident = 'a' * 32
    directory = store.root / 'MediaCrawler/data/tasks' / ident
    write(store, str(directory / 'task.json'), {'id': ident, 'platform': 'tieba', 'status': status, 'created_at': '2026-09-18T12:00:00Z'})
    path = write(store, str(directory / 'output/tieba/json/a.json'), [post()])
    return ident, directory, path


def test_task_provenance_and_deletion_bridge(store):
    ident, directory, path = task_source(store)
    with pytest.raises(KnowledgeError, match='task_source_required'):
        store.register_source(path, platform='tieba')
    source = store.register_source(path, platform='tieba', source_type='task', task_id=ident)
    assert store.import_source(source['id'])['source_partial'] is True
    module_path = Path(__file__).resolve().parents[2] / 'MediaCrawler/api/knowledge_bridge.py'
    spec = importlib.util.spec_from_file_location('bridge_test', module_path)
    bridge = importlib.util.module_from_spec(spec); spec.loader.exec_module(bridge)
    bridge.PROJECT_ROOT = store.root
    bridge.invalidate(directory)
    assert store.list_snapshots() == [] and path.exists()
    assert store.list_sources()[0]['status'] == 'deleted'


def test_active_task_rejected(store):
    ident, _, path = task_source(store, 'running')
    with pytest.raises(KnowledgeError, match='task_not_finished'):
        store.register_source(path, platform='tieba', source_type='task', task_id=ident)


def test_comment_missing_self_id_is_not_post(store):
    _, report = ingest(store, 'a.json', [{'note_id': '123', 'content': 'missing comment ID'}])
    assert report['errors'] == [{'locator': 1, 'code': 'missing_comment_id'}]
    assert store.list_snapshots() == []


def test_cli_from_unrelated_directory(store, tmp_path):
    path = write(store, 'a.json', [post()])
    result = subprocess.run([sys.executable, '-m', 'community_research', '--root', str(store.root), 'ingest', str(path), '--platform', 'tieba'], cwd=tmp_path.parent, capture_output=True, encoding='utf-8')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['new_entities'] == 1


@pytest.mark.parametrize('mode', ['task', 'legacy'])
def test_existing_delete_entrypoints_invalidate_index(store, mode):
    if mode == 'task':
        ident, _, path = task_source(store)
        source = store.register_source(path, platform='tieba', source_type='task', task_id=ident)
    else:
        path = write(store, 'MediaCrawler/data/tieba/a.json', [post()])
        source = store.register_source(path, platform='tieba')
    store.import_source(source['id'])
    script = '''
import asyncio, sys
from pathlib import Path
from api import task_store, knowledge_bridge
from api.routers import data
root = Path(sys.argv[1])
knowledge_bridge.PROJECT_ROOT = root
task_store.DATA_DIR = root / 'MediaCrawler/data'
task_store.TASKS_DIR = task_store.DATA_DIR / 'tasks'
data.DATA_DIR = task_store.DATA_DIR
if sys.argv[2] == 'task':
    asyncio.run(data.delete_task('a' * 32))
else:
    asyncio.run(data.delete_legacy_file('tieba/a.json'))
'''
    crawler = Path(__file__).resolve().parents[2] / 'MediaCrawler'
    result = subprocess.run([sys.executable, '-c', script, str(store.root), mode], cwd=crawler, capture_output=True, encoding='utf-8', errors='replace')
    assert result.returncode == 0, result.stderr
    assert not path.exists()
    assert store.list_sources()[0]['status'] == 'deleted'
    assert store.list_snapshots() == []
