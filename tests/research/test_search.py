import json
from pathlib import Path
import subprocess
import sys

import pytest

from community_research.knowledge import KnowledgeStore
from community_research.knowledge.search import SearchService


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = json.loads((ROOT / 'docs/p0/fixtures.json').read_text(encoding='utf-8'))


def add(store, name, rows, **kwargs):
    path = store.root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
    source = store.register_source(path, platform='tieba', **kwargs)
    store.import_source(source['id'])
    return source


@pytest.fixture
def system(tmp_path):
    store = KnowledgeStore(tmp_path)
    mapping = {r['id']: r['external_id'] for r in FIXTURES['records']}
    rows = []
    for r in FIXTURES['records']:
        row = {'publish_time': r.get('published_at'), 'source_keyword': r.get('source_keyword')}
        if r['kind'] == 'post':
            row.update(note_id=r['external_id'], title=r['title'], desc=r['body'])
        else:
            row.update(comment_id=r['external_id'], content=r['body'], note_id=mapping.get(r['post_id'], 'missing'),
                       parent_comment_id=mapping.get(r['parent_id']))
        rows.append(row)
    source = add(store, 'fixture.json', rows)
    return store, SearchService(store), source


@pytest.mark.parametrize('case', [c for c in FIXTURES['cases'] if c['id'] in ['E07', 'E08', 'E09', 'E10', 'E11']], ids=lambda c: c['id'])
def test_p0_literal_expectations(system, case):
    _, service, _ = system
    result = service.call('search_comments' if case['action'] == 'comment_search' else 'search_posts', case['query'])
    mapping = {r['id']: r['external_id'] for r in FIXTURES['records']}
    assert result['error'] is None
    assert {r['external_id'] for r in result['items']} == {mapping[i] for i in case['expected_ids']}


def test_time_boundaries_and_unknown(system):
    _, service, _ = system
    result = service.call('search_posts', {'published_from': '2026-09-17T08:00:00+08:00', 'published_to': '2026-09-18T00:00:00Z'})
    assert [r['external_id'] for r in result['items']] == ['103']
    assert result['coverage']['excluded_unknown_time'] == 2


@pytest.mark.parametrize('query', [
    {'fields': []}, {'fields': ['source_keyword']}, {'limit': True}, {'limit': 51}, {'all_terms': ['']},
    {'any_terms': ['a'] * 9}, {'all_terms': 'cs'}, {'published_from': '2026-09-18'},
    {'published_from': '2026-09-19T00:00:00Z', 'published_to': '2026-09-18T00:00:00Z'},
    {'source_ids': ['unknown']}, {'task_ids': ['unknown']}, {'extra': 'ignored?'},
])
def test_invalid_arguments(system, query):
    assert system[1].call('search_posts', query)['error']['code'] == 'invalid_arguments'


def test_platform_and_empty_not_imported(tmp_path):
    service = SearchService(KnowledgeStore(tmp_path))
    assert service.call('search_posts', {})['error']['code'] == 'not_imported'
    assert service.call('search_posts', {'platform': 'bili'})['error']['code'] == 'unsupported_platform'
    source = add(service.store, 'empty.json', [])
    # Legacy source coverage is partial even when no match exists.
    result = service.call('search_posts', {})
    assert result['status'] == 'partial' and result['coverage']['total'] == 0
    service.store.revoke(source['id'])
    assert service.call('search_posts', {})['error']['code'] == 'source_unavailable'


def test_unicode_offsets_and_persisted_evidence(system):
    store, service, _ = system
    body = '🙂 Straße CS 中间有文字 饰品'
    add(store, 'unicode.json', [{'note_id': 'u', 'desc': body}])
    result = service.call('search_posts', {'all_terms': ['STRASSE', 'cs', '饰品'], 'fields': ['body']})
    assert [r['external_id'] for r in result['items']] == ['u']
    snippet = result['items'][0]['snippets'][0]
    new_service = SearchService(KnowledgeStore(store.root))
    read = new_service.call('read_evidence', {'evidence_ids': [snippet['evidence_id']]})
    assert read['items'][0]['quote'] == body[snippet['start']:snippet['end']]
    assert new_service.call('read_evidence', {'evidence_ids': ['ev_madeup']})['error']['code'] == 'evidence_not_found'


def test_field_selection_and_empty_evidence(system):
    _, service, _ = system
    result = service.call('search_posts', {'all_terms': ['价格'], 'fields': ['title']})
    assert result['items'][0]['matched_fields'] == ['title']
    empty = service.call('search_posts', {'fields': ['body']})
    assert next(r for r in empty['items'] if r['external_id'] == '105')['snippets'] == []


def test_pagination_binding_and_mutation(system):
    store, service, _ = system
    first = service.call('search_posts', {'limit': 2})
    cursor = first['coverage']['next_cursor']
    second = service.call('search_posts', {'limit': 2, 'cursor': cursor})
    assert not {r['entity_id'] for r in first['items']} & {r['entity_id'] for r in second['items']}
    assert service.call('search_posts', {'limit': 3, 'cursor': cursor})['error']['code'] == 'stale_cursor'
    add(store, 'new.json', [{'note_id': 'new', 'desc': 'new'}])
    assert service.call('search_posts', {'limit': 2, 'cursor': cursor})['error']['code'] == 'stale_cursor'


def test_sources_versions_and_evidence_invalidation(system):
    store, service, source = system
    old = service.call('search_posts', {'all_terms': ['下跌']})['items'][0]
    alternative = add(store, 'version.json', [{'note_id': '101', 'desc': '价格上涨', 'last_modify_ts': 1789717243804}])
    assert not service.call('search_posts', {'all_terms': ['下跌']})['items']
    assert service.call('search_posts', {'all_terms': ['下跌'], 'source_ids': [source['id']]})['items']
    ident = old['snippets'][0]['evidence_id']
    assert service.call('read_evidence', {'evidence_ids': [ident]})['items'][0]['snapshot_id'] == old['snapshot_id']
    store.revoke(source['id'])
    assert service.call('read_evidence', {'evidence_ids': [ident]})['error']['code'] == 'evidence_unavailable'
    assert service.call('search_posts', {'all_terms': ['上涨']})['items']


def test_duplicate_sources_and_delete_one(system):
    store, service, source = system
    rows = json.loads((store.root / 'fixture.json').read_text(encoding='utf-8'))
    other = add(store, 'copy.json', rows)
    item = service.call('search_posts', {'all_terms': ['donk']})['items'][0]
    assert set(item['source_ids']) == {source['id'], other['id']}
    (store.root / 'fixture.json').unlink()
    read = service.call('read_evidence', {'evidence_ids': [item['snippets'][0]['evidence_id']]})
    assert read['items'][0]['source_ids'] == [other['id']]


def test_comment_filters_and_context(system):
    _, service, _ = system
    posts = service.call('search_posts', {'all_terms': ['cs']})['items']
    comments = service.call('search_comments', {'post_ids': [posts[0]['entity_id']]})['items']
    assert {r['external_id'] for r in comments} == {'201', '202'}
    parent = next(r for r in comments if r['external_id'] == '201')
    child = service.call('search_comments', {'parent_id': parent['entity_id']})['items'][0]
    assert child['external_id'] == '202'
    read = service.call('read_evidence', {'evidence_ids': [child['snippets'][0]['evidence_id']], 'include_context': True})
    context = read['items'][0]['context']
    assert {c['relation'] for c in context} == {'post', 'parent'}
    ids = [i for c in context for i in c['evidence_ids']]
    assert service.call('read_evidence', {'evidence_ids': ids})['items']
    orphan = service.call('search_comments', {'all_terms': ['缺少']})['items'][0]
    read = service.call('read_evidence', {'evidence_ids': [orphan['snippets'][0]['evidence_id']], 'include_context': True})
    assert read['items'][0]['context'][0]['status'] == 'unresolved'


def test_long_evidence_paging_and_response_budget(system):
    store, service, _ = system
    text = '开头' * 3000 + 'TARGET' + '后面' * 5000
    add(store, 'long.json', [{'note_id': 'long', 'desc': text}])
    item = service.call('search_posts', {'all_terms': ['TARGET']})['items'][0]
    ident = item['snippets'][0]['evidence_id']
    read = service.call('read_evidence', {'evidence_ids': [ident]})
    piece = read['items'][0]
    assert piece['previous_evidence_id'] and piece['next_evidence_id']
    assert piece['quote'] == text[piece['start']:piece['end']]
    ids = []
    while piece['next_evidence_id']:
        ids.append(piece['next_evidence_id'])
        piece = service.call('read_evidence', {'evidence_ids': [ids[-1]]})['items'][0]
        assert len(piece['quote']) <= 2000
    # Several long records force a bounded response and explicit deferred IDs.
    add(store, 'many.json', [{'note_id': f'm{i}', 'desc': 'X' * 5000} for i in range(20)])
    items = service.call('search_posts', {'all_terms': ['X'], 'limit': 20})['items']
    next_ids = [service.call('read_evidence', {'evidence_ids': [r['snippets'][0]['evidence_id']]})['items'][0]['next_evidence_id'] for r in items]
    result = service.call('read_evidence', {'evidence_ids': next_ids})
    assert result['coverage']['pending_evidence_ids'] and len(json.dumps(result, ensure_ascii=False)) <= 24000


def test_task_filter_and_empty_status(tmp_path):
    store = KnowledgeStore(tmp_path)
    task_id = 'a' * 32
    folder = store.root / 'MediaCrawler/data/tasks' / task_id
    folder.mkdir(parents=True)
    (folder / 'task.json').write_text(json.dumps({'id': task_id, 'platform': 'tieba', 'status': 'completed'}), encoding='utf-8')
    add(store, f'MediaCrawler/data/tasks/{task_id}/output/a.json', [{'note_id': '1', 'desc': 'hello'}], source_type='task', task_id=task_id)
    service = SearchService(store)
    assert service.call('search_posts', {'task_ids': [task_id]})['status'] == 'ok'
    assert service.call('search_posts', {'task_ids': [task_id], 'all_terms': ['nope']})['status'] == 'empty'


def test_cli_tool(system):
    store, _, _ = system
    arguments = store.root / 'arguments.json'
    arguments.write_text('{"all_terms":["cs"]}', encoding='utf-8')
    run = subprocess.run([sys.executable, '-m', 'community_research', '--root', str(store.root), 'tool', 'search_comments', '--arguments', str(arguments)], cwd=store.root, capture_output=True, encoding='utf-8')
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout)['items'][0]['external_id'] == '202'


def test_manual_overwrite_invalidates_cursor_and_evidence(system):
    store, service, _ = system
    result = service.call('search_posts', {'limit': 1})
    ident = result['items'][0]['snippets'][0]['evidence_id']
    (store.root / 'fixture.json').write_text('[]', encoding='utf-8')
    assert service.call('search_posts', {'limit': 1, 'cursor': result['coverage']['next_cursor']})['error']['code'] == 'stale_cursor'
    assert service.call('read_evidence', {'evidence_ids': [ident]})['error']['code'] == 'evidence_unavailable'


def test_search_does_not_borrow_post_terms(system):
    _, service, _ = system
    assert not service.call('search_comments', {'all_terms': ['下跌']})['items']
    assert service.call('search_posts', {'all_terms': ['下跌']})['items']


def test_long_casefold_expansion_locates_original(system):
    store, service, _ = system
    body = 'ß' * 600 + 'needle' + 'end' * 800
    add(store, 'fold.json', [{'note_id': 'fold', 'desc': body}])
    snippet = service.call('search_posts', {'all_terms': ['NEEDLE']})['items'][0]['snippets'][0]
    assert snippet['start'] == 520 and 'needle' in snippet['quote']
    assert snippet['quote'] == body[snippet['start']:snippet['end']]


@pytest.mark.parametrize('arguments', [{'evidence_ids': []}, {'evidence_ids': ['x'] * 21},
                                    {'evidence_ids': ['x'], 'include_context': 'true'},
                                    {'evidence_ids': ['x'], 'arbitrary': True}])
def test_evidence_argument_validation(system, arguments):
    assert system[1].call('read_evidence', arguments)['error']['code'] == 'invalid_arguments'
