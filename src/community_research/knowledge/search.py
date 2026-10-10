"""Bounded literal retrieval and immutable evidence for the future harness."""
from datetime import datetime, timezone
import json
import uuid

from .store import KnowledgeError, digest, encode


SCHEMA = '''
CREATE TABLE IF NOT EXISTS evidence(
 id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES snapshots(id),
 field TEXT NOT NULL, start INTEGER NOT NULL, end INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS search_cursors(
 id TEXT PRIMARY KEY, query_hash TEXT NOT NULL, revision INTEGER NOT NULL, offset INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS cursor_scope_offset ON search_cursors(query_hash,revision,offset);
'''


def date(value):
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        raise KnowledgeError('invalid_arguments') from None


def strings(value, maximum=20, width=128):
    if not isinstance(value, list) or len(value) > maximum:
        raise KnowledgeError('invalid_arguments')
    if any(not isinstance(v, str) or not 1 <= len(v.strip()) <= width for v in value):
        raise KnowledgeError('invalid_arguments')
    return list(dict.fromkeys(v.strip() for v in value))


def matched_span(text, term):
    """Map casefold expansions (e.g. ß -> ss) back to original code points."""
    folded = text.casefold()
    index = folded.find(term.casefold())
    if index < 0:
        return None
    positions = [i for i, char in enumerate(text) for _ in char.casefold()]
    return positions[index], positions[index + len(term.casefold()) - 1] + 1


class SearchService:
    def __init__(self, store):
        self.store = store
        with store.connection() as conn:
            conn.executescript(SCHEMA)

    def call(self, tool, arguments):
        """Single tool boundary; exceptions never masquerade as empty matches."""
        try:
            if not isinstance(arguments, dict) or tool not in ('search_posts', 'search_comments', 'read_evidence', 'hybrid_search', 'compare_sources', 'source_versions'):
                raise KnowledgeError('invalid_arguments')
            return getattr(self, tool)(**arguments)
        except (KnowledgeError, TypeError) as exc:
            code = exc.code if isinstance(exc, KnowledgeError) else 'invalid_arguments'
            return {'schema_version': '0.1', 'status': 'error', 'items': [], 'coverage': None,
                    'error': {'code': code, 'message': code, 'retryable': False, 'details': {}}}

    def search_posts(self, **arguments):
        return self._search('post', arguments)

    def hybrid_search(self, **arguments):
        from .semantic import hybrid_search
        return hybrid_search(self, **arguments)

    def search_comments(self, **arguments):
        return self._search('comment', arguments)

    def compare_sources(self, **arguments):
        return self.store.compare_sources(**arguments)

    def source_versions(self, post_ids, limit=20):
        """Discover comparison inputs without requiring users to type source UUIDs."""
        targets = strings(post_ids, 20, 32)
        if not targets or any(not p.isascii() or not p.isdigit() for p in targets) or type(limit) is not int or not 1 <= limit <= 50:
            raise KnowledgeError('invalid_arguments')
        self.store.refresh()
        with self.store.connection() as conn:
            catalog = self._catalog(conn, platform='tieba')
            relevant = {r['source_id'] for r in catalog if (r['external_id'] if r['kind'] == 'post'
                       else json.loads(r['payload'])['post_external_id']) in targets}
            sources = [dict(r) for r in conn.execute("SELECT id AS source_id,task_id,path,file_hash,created_at,partial FROM sources WHERE status='active' ORDER BY created_at DESC,id DESC") if r['source_id'] in relevant]
        return {'schema_version': '0.1', 'status': 'partial' if any(r['partial'] for r in sources) else 'ok',
                'items': sources[:limit], 'error': None, 'coverage': {'scope': 'local_source_versions',
                'total': len(sources), 'returned': min(limit, len(sources)), 'has_more': len(sources) > limit,
                'post_ids': targets, 'sort': 'registration_time_desc_not_site_change_time'}}

    def _validate(self, kind, arguments):
        allowed = {'platform', 'source_ids', 'task_ids', 'all_terms', 'any_terms', 'exclude_terms', 'fields',
                   'published_from', 'published_to', 'limit', 'cursor'}
        if kind == 'comment':
            allowed |= {'post_ids', 'parent_id'}
        if arguments.keys() - allowed:
            raise KnowledgeError('invalid_arguments')
        q = dict(platform='tieba', source_ids=[], task_ids=[], all_terms=[], any_terms=[], exclude_terms=[],
                 fields=['title', 'body'] if kind == 'post' else ['body'], published_from=None,
                 published_to=None, limit=20, cursor=None)
        if kind == 'comment':
            q.update(post_ids=[], parent_id=None)
        q.update(arguments)
        if q['platform'] != 'tieba':
            raise KnowledgeError('unsupported_platform')
        if type(q['limit']) is not int or not 1 <= q['limit'] <= 50:
            raise KnowledgeError('invalid_arguments')
        for field in ('source_ids', 'task_ids', 'post_ids'):
            if field in q:
                q[field] = strings(q[field])
        for field in ('all_terms', 'any_terms', 'exclude_terms'):
            q[field] = strings(q[field], 8, 80)
        q['fields'] = strings(q['fields'], 2, 5)
        if not q['fields'] or set(q['fields']) - ({'title', 'body'} if kind == 'post' else {'body'}):
            raise KnowledgeError('invalid_arguments')
        for key in ('published_from', 'published_to'):
            if q[key] is not None:
                q[key] = date(q[key]).isoformat()
        if q['published_from'] and q['published_to'] and date(q['published_from']) >= date(q['published_to']):
            raise KnowledgeError('invalid_arguments')
        for key in ('cursor', 'parent_id'):
            if q.get(key) is not None:
                q[key] = strings([q[key]])[0]
        return q

    @staticmethod
    def _catalog(conn, source_ids=None, kind=None, platform=None):
        conditions, args = [], []
        if source_ids is not None:
            if not source_ids:
                return []
            conditions.append('o.source_id IN (' + ','.join('?' for _ in source_ids) + ')')
            args.extend(source_ids)
        for field, value in (('e.kind', kind), ('e.platform', platform)):
            if value is not None:
                conditions.append(field + '=?')
                args.append(value)
        rows = conn.execute('''SELECT p.id AS snapshot_id,p.entity_id,p.payload,e.kind,e.external_id,e.platform,
          o.source_id,o.observed_at,o.imported_at,o.published_at_utc,s.task_id,s.partial
          FROM snapshots p JOIN entities e ON e.id=p.entity_id JOIN occurrences o ON o.snapshot_id=p.id
          JOIN sources s ON s.id=o.source_id WHERE s.status='active' AND p.payload IS NOT NULL'''
          + ((' AND ' + ' AND '.join(conditions)) if conditions else ''), args).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _latest(rows):
        def key(row):
            return (date(row['observed_at']).timestamp() if row['observed_at'] else float('-inf'),
                    date(row['imported_at']).timestamp(), row['snapshot_id'], row['source_id'])
        latest = {}
        for row in sorted(rows, key=key):
            latest[row['entity_id']] = row
        return list(latest.values())

    @staticmethod
    def _evidence(conn, snapshot, field, start, end):
        ident = 'ev_' + digest(encode([snapshot, field, start, end]).encode())
        conn.execute('INSERT OR IGNORE INTO evidence VALUES(?,?,?,?,?)', (ident, snapshot, field, start, end))
        return ident

    def _search(self, kind, arguments):
        q = self._validate(kind, arguments)
        self.store.refresh()
        with self.store.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            revision = conn.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0]
            fingerprint = digest(encode([kind, {k: v for k, v in q.items() if k != 'cursor'}]).encode())
            offset = 0
            if q['cursor']:
                cursor = conn.execute('SELECT * FROM search_cursors WHERE id=?', (q['cursor'],)).fetchone()
                if not cursor or cursor['query_hash'] != fingerprint or cursor['revision'] != revision:
                    raise KnowledgeError('stale_cursor')
                offset = cursor['offset']
            sources = [dict(r) for r in conn.execute('SELECT * FROM sources')]
            if set(q['source_ids']) - {s['id'] for s in sources} or set(q['task_ids']) - {s['task_id'] for s in sources}:
                raise KnowledgeError('invalid_arguments')
            selected = [s for s in sources if (not q['source_ids'] or s['id'] in q['source_ids'])
                        and (not q['task_ids'] or s['task_id'] in q['task_ids'])]
            active = {s['id'] for s in selected if s['status'] == 'active'}
            unavailable = [s['id'] for s in selected if s['status'] != 'active']
            partial = [s['id'] for s in selected if s['status'] == 'active' and s['partial']]
            incomplete = {r[0] for r in conn.execute("SELECT DISTINCT source_id FROM imports WHERE status != 'completed'")}
            partial = sorted(set(partial) | (active & incomplete))
            if not active:
                raise KnowledgeError('source_unavailable' if unavailable else 'not_imported')
            imported = {r[0] for r in conn.execute('SELECT DISTINCT source_id FROM imports')}
            if not active & imported:
                raise KnowledgeError('not_imported')
            unimported = sorted(active - imported)
            entities = {r['id']: dict(r) for r in conn.execute('SELECT * FROM entities')}
            for ident in q.get('post_ids', []):
                if ident not in entities or entities[ident]['kind'] != 'post':
                    raise KnowledgeError('invalid_arguments')
            if q.get('parent_id') and (q['parent_id'] not in entities or entities[q['parent_id']]['kind'] != 'comment'):
                raise KnowledgeError('invalid_arguments')
            post_ids = {entities[i]['external_id'] for i in q.get('post_ids', [])}
            parent = entities[q['parent_id']]['external_id'] if q.get('parent_id') else None
            catalog = self._catalog(conn, kind=kind, platform=q['platform'])
            candidates = self._latest([r for r in catalog if r['source_id'] in active and r['kind'] == kind and r['platform'] == q['platform']])
            matches, unknown = [], 0
            for row in candidates:
                payload = json.loads(row['payload'])
                if post_ids and payload['post_external_id'] not in post_ids or parent and payload['parent_external_id'] != parent:
                    continue
                texts = {f: payload.get(f) or '' for f in q['fields']}
                def hit(term):
                    return any(term.casefold() in t.casefold() for t in texts.values())
                if not all(hit(t) for t in q['all_terms']) or (q['any_terms'] and not any(hit(t) for t in q['any_terms'])) or any(hit(t) for t in q['exclude_terms']):
                    continue
                published = row['published_at_utc']
                if q['published_from'] or q['published_to']:
                    if not published:
                        unknown += 1; continue
                    if q['published_from'] and date(published) < date(q['published_from']) or q['published_to'] and date(published) >= date(q['published_to']):
                        continue
                row['content'] = payload
                matches.append(row)
            matches.sort(key=lambda r: (-(date(r['published_at_utc']).timestamp()) if r['published_at_utc'] else float('inf'), r['entity_id']))
            items = []
            for row in matches[offset:offset + q['limit']]:
                snippets = []
                for field in q['fields']:
                    text = row['content'].get(field) or ''
                    spans = [matched_span(text, term) for term in q['all_terms'] + q['any_terms']]
                    spans = [span for span in spans if span is not None]
                    if not text or (q['all_terms'] + q['any_terms'] and not spans):
                        continue
                    start = max(0, min(s[0] for s in spans) - 80) if spans else 0
                    end = min(len(text), start + 400)
                    snippets.append({'field': field, 'start': start, 'end': end, 'quote': text[start:end],
                                     'evidence_id': self._evidence(conn, row['snapshot_id'], field, start, end)})
                origins = sorted({r['source_id'] for r in catalog if r['snapshot_id'] == row['snapshot_id']})
                items.append({'entity_id': row['entity_id'], 'snapshot_id': row['snapshot_id'], 'external_id': row['external_id'],
                              'kind': kind, 'published_at_utc': row['published_at_utc'], 'source_ids': origins,
                              'matched_fields': [s['field'] for s in snippets] if q['all_terms'] + q['any_terms'] else [],
                              'snippets': snippets, 'source_url': row['content']['source_url'],
                              'forum_name': row['content'].get('forum_name')})
            has_more = offset + len(items) < len(matches)
            cursor_id = None
            if has_more:
                cursor_id = uuid.uuid4().hex
                conn.execute('INSERT INTO search_cursors VALUES(?,?,?,?)', (cursor_id, fingerprint, revision, offset + len(items)))
            coverage = {'scope': 'local_imported_data', 'source_ids': sorted(active), 'index_revision': revision,
                        'returned': len(items), 'total': len(matches), 'has_more': has_more, 'next_cursor': cursor_id,
                        'excluded_unknown_time': unknown, 'partial_sources': partial, 'unavailable_sources': unavailable,
                        'unimported_sources': unimported, 'sort': 'published_at_desc_nulls_last,entity_id_asc',
                        'version_policy': 'latest_observed_within_selected_sources', 'matching': 'unicode_casefold_substring'}
            return {'schema_version': '0.1', 'status': 'partial' if partial or unavailable or unimported else 'ok' if items else 'empty',
                    'items': items, 'coverage': coverage, 'error': None}

    def _read_piece(self, conn, ident):
        evidence = conn.execute('SELECT * FROM evidence WHERE id=?', (ident,)).fetchone()
        if not evidence:
            raise KnowledgeError('evidence_not_found')
        snapshot, origins = self.store._active(conn, evidence['snapshot_id'])
        payload = json.loads(snapshot['payload'])
        text = payload[evidence['field']]
        start, end = evidence['start'], evidence['end']
        next_id = self._evidence(conn, snapshot['id'], evidence['field'], end, min(end + 2000, len(text))) if end < len(text) else None
        previous_id = self._evidence(conn, snapshot['id'], evidence['field'], max(0, start - 2000), start) if start else None
        stats = None
        if payload['kind']=='post':
            row = conn.execute('''SELECT m.reply_count,o.observed_at,o.timezone_basis FROM occurrences o
                JOIN sources s ON s.id=o.source_id LEFT JOIN record_metadata m
                ON m.source_id=o.source_id AND m.snapshot_id=o.snapshot_id AND m.locator=o.locator
                WHERE o.snapshot_id=? AND s.status='active'
                ORDER BY o.observed_at DESC,o.imported_at DESC,o.source_id DESC LIMIT 1''',(snapshot['id'],)).fetchone()
            stats = {'title':payload.get('title'),'published_at':payload.get('published_at_raw'),
                     'reply_count':row['reply_count'] if row else None,'observed_at':row['observed_at'] if row else None,
                     'timezone_basis':row['timezone_basis'] if row else None}
        return {'evidence_id': ident, 'snapshot_id': snapshot['id'], 'entity_id': snapshot['entity_id'],
                'field': evidence['field'], 'start': start, 'end': end, 'quote': text[start:end],
                'source_ids': sorted({r['source_id'] for r in origins}), 'source_url': payload['source_url'],
                'truncated': next_id is not None or start > 0, 'next_evidence_id': next_id, 'previous_evidence_id': previous_id, 'post_stats':stats}, payload

    def read_evidence(self, evidence_ids, include_context=False):
        ids = strings(evidence_ids)
        if not ids or type(include_context) is not bool:
            raise KnowledgeError('invalid_arguments')
        self.store.refresh()
        with self.store.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            revision = conn.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0]
            catalog = self._latest(self._catalog(conn)) if include_context else []
            items, pending, used = [], [], 0
            source_ids = set()
            for ident in ids:
                piece, payload = self._read_piece(conn, ident)
                piece['context'] = []
                if include_context and payload['kind'] == 'comment':
                    for relation, kind, external in [('post', 'post', payload['post_external_id']), ('parent', 'comment', payload['parent_external_id'])]:
                        if not external:
                            continue
                        related = next((r for r in catalog if r['kind'] == kind and r['external_id'] == external and r['platform'] == 'tieba'), None)
                        target = json.loads(related['payload']) if related else None
                        if not related or relation == 'parent' and target['post_external_id'] != payload['post_external_id']:
                            piece['context'].append({'relation': relation, 'status': 'unresolved', 'external_id': external})
                            continue
                        context_ids = [self._evidence(conn, related['snapshot_id'], field, 0, min(2000, len(target[field])))
                                       for field in ('title', 'body') if target.get(field)]
                        piece['context'].append({'relation': relation, 'status': 'resolved', 'entity_id': related['entity_id'],
                                                 'evidence_ids': context_ids})
                # Keep room for response metadata and all remaining identifiers.
                size = len(encode(piece))
                if used + size > 20000:
                    pending.append(ident); continue
                used += size; items.append(piece)
                source_ids.update(piece['source_ids'])
            partial_sources = [r['id'] for r in conn.execute('SELECT id,partial FROM sources') if r['id'] in source_ids and r['partial']]
            truncated = bool(pending) or any(p['truncated'] for p in items)
            if pending and not items:
                raise KnowledgeError('response_too_large')
            result = {'schema_version': '0.1', 'status': 'partial' if truncated or partial_sources else 'ok', 'items': items,
                    'coverage': {'scope': 'local_imported_data', 'index_revision': revision, 'returned': len(items),
                                 'partial_sources': partial_sources, 'pending_evidence_ids': pending,
                                 'context_policy': 'separate_ids_read_explicitly'}, 'error': None}
            while len(encode(result)) > 24000 and items:
                pending.insert(0, items.pop()['evidence_id'])
                remaining_sources = {s for item in items for s in item['source_ids']}
                result['coverage']['partial_sources'] = [s for s in partial_sources if s in remaining_sources]
                result['coverage']['returned'] = len(items)
                result['status'] = 'partial'
            if not items:
                raise KnowledgeError('response_too_large')
            return result
