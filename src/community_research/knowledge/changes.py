"""Compare observed source versions; absence in a sample is never deletion."""
import json
import uuid

from .store import KnowledgeError, digest, encode


def compare_sources(store, before_source_ids, after_source_ids, limit=20, cursor=None, post_ids=None):
    from .search import SearchService, strings
    before = strings(before_source_ids, 100)
    after = strings(after_source_ids, 100)
    targets = strings([] if post_ids is None else post_ids, 20)
    if not after or type(limit) is not int or not 1 <= limit <= 50:
        raise KnowledgeError('invalid_arguments')
    if cursor is not None and (not isinstance(cursor, str) or not cursor):
        raise KnowledgeError('invalid_arguments')
    service = SearchService(store)
    store.refresh()
    with store.connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        source_rows = {r['id']: dict(r) for r in conn.execute('SELECT * FROM sources')}
        selected = set(before + after)
        if selected - source_rows.keys():
            raise KnowledgeError('source_not_found')
        if any(source_rows[s]['status'] != 'active' for s in selected):
            raise KnowledgeError('source_unavailable')
        imported = {r[0] for r in conn.execute('SELECT DISTINCT source_id FROM imports')}
        if selected - imported:
            raise KnowledgeError('not_imported')
        revision = conn.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0]
        fingerprint = digest(encode(['changes', sorted(before), sorted(after), sorted(targets), limit]).encode())
        offset = 0
        if cursor:
            saved = conn.execute('SELECT * FROM search_cursors WHERE id=?', (cursor,)).fetchone()
            if not saved or saved['query_hash'] != fingerprint or saved['revision'] != revision:
                raise KnowledgeError('stale_cursor')
            offset = saved['offset']
        catalog = service._catalog(conn, source_ids=sorted(selected))
        def view(ids):
            rows = service._latest([r for r in catalog if r['source_id'] in ids])
            result = {}
            for row in rows:
                payload = json.loads(row['payload'])
                if targets and (payload['external_id'] if row['kind'] == 'post' else payload['post_external_id']) not in targets:
                    continue
                row['content'] = payload
                result[row['entity_id']] = row
            return result
        older, newer = view(set(before)), view(set(after))
        counts = {'added_posts': 0, 'added_comments': 0, 'changed_posts': 0,
                  'changed_comments': 0, 'unchanged': 0, 'not_observed': 0}
        changes = []
        for entity in sorted(older.keys() | newer.keys()):
            left, right = older.get(entity), newer.get(entity)
            row = right or left
            if left is None:
                status = 'added'
                fields = ['title', 'body'] if row['kind'] == 'post' else ['body']
                counts['added_posts' if row['kind'] == 'post' else 'added_comments'] += 1
            elif right is None:
                status, fields = 'not_observed', []
                counts['not_observed'] += 1
            elif left['snapshot_id'] == right['snapshot_id']:
                counts['unchanged'] += 1
                continue
            else:
                status = 'changed'
                fields = sorted(k for k in left['content'].keys() | right['content'].keys()
                                if left['content'].get(k) != right['content'].get(k))
                counts['changed_posts' if row['kind'] == 'post' else 'changed_comments'] += 1
            changes.append({'entity_id': entity, 'external_id': row['external_id'], 'kind': row['kind'],
                            'platform': row['platform'], 'change': status, 'changed_fields': fields,
                            'before_row': left, 'after_row': right})
        def version(row, counterpart):
            if row is None:
                return None
            payload = row['content']
            snippets = []
            for field in ('title', 'body'):
                text = payload.get(field) or ''
                if text:
                    other = (counterpart or {}).get('content', {}).get(field) or ''
                    position = 0
                    if counterpart and text != other:
                        # Locate the first differing code point without copying the full field.
                        while position < min(len(text), len(other)) and text[position] == other[position]:
                            position += 1
                    start = max(0, min(position, len(text)) - 80)
                    end = min(start + 400, len(text))
                    snippets.append({'field': field, 'quote': text[start:end], 'start': start, 'end': end,
                                     'evidence_id': service._evidence(conn, row['snapshot_id'], field, start, end)})
            return {'snapshot_id': row['snapshot_id'], 'source_id': row['source_id'],
                    'observed_at': row['observed_at'], 'source_url': payload['source_url'], 'snippets': snippets}
        items = []
        for change in changes[offset:offset + limit]:
            left, right = change.pop('before_row'), change.pop('after_row')
            item = {**change, 'before': version(left, right), 'after': version(right, left)}
            if len(encode(items + [item])) > 16000:
                if not items:
                    raise KnowledgeError('response_too_large')
                break
            items.append(item)
        has_more = offset + len(items) < len(changes)
        next_cursor = None
        if has_more:
            next_offset = offset + len(items)
            existing = conn.execute('SELECT id FROM search_cursors WHERE query_hash=? AND revision=? AND offset=? LIMIT 1',
                                    (fingerprint, revision, next_offset)).fetchone()
            next_cursor = existing['id'] if existing else uuid.uuid4().hex
            if not existing:
                conn.execute('INSERT INTO search_cursors VALUES(?,?,?,?)', (next_cursor, fingerprint, revision, next_offset))
        partial = sorted(s for s in selected if source_rows[s]['partial'] or conn.execute(
            "SELECT 1 FROM imports WHERE source_id=? AND status!='completed'", (s,)).fetchone())
        versions = [{'source_id': s, 'path': source_rows[s]['path'], 'file_hash': source_rows[s]['file_hash'],
                     'task_id': source_rows[s]['task_id']} for s in sorted(selected)]
    return {'schema_version': '0.1', 'status': 'partial' if partial else 'ok', 'items': items,
            'counts': counts, 'source_versions': versions, 'error': None,
            'coverage': {'scope': 'observed_source_versions', 'index_revision': revision,
                         'before_source_ids': before, 'after_source_ids': after, 'post_ids': targets,
                         'returned': len(items), 'total': len(changes), 'has_more': has_more,
                         'next_cursor': next_cursor, 'partial_sources': partial,
                         'absence_policy': 'not_observed_does_not_mean_deleted'}}
