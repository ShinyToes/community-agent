"""Explicit local ingestion with immutable identities, provenance and revocable reads."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class KnowledgeError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def project_root():
    return Path(os.environ.get('COMMUNITY_RESEARCH_ROOT', Path(__file__).resolve().parents[3])).resolve()


SCHEMA = '''
CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO schema_version VALUES(1);
CREATE TABLE IF NOT EXISTS sources(
 id TEXT PRIMARY KEY, platform TEXT NOT NULL, type TEXT NOT NULL, path TEXT NOT NULL,
 file_hash TEXT NOT NULL, status TEXT NOT NULL, task_id TEXT, source_timezone TEXT,
 partial INTEGER NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS entities(
 id TEXT PRIMARY KEY, platform TEXT NOT NULL, kind TEXT NOT NULL, external_id TEXT NOT NULL,
 UNIQUE(platform,kind,external_id));
CREATE TABLE IF NOT EXISTS snapshots(
 id TEXT PRIMARY KEY, entity_id TEXT NOT NULL REFERENCES entities(id),
 content_hash TEXT NOT NULL, payload TEXT, created_at TEXT NOT NULL, schema_version TEXT NOT NULL,
 UNIQUE(entity_id,content_hash));
CREATE TABLE IF NOT EXISTS occurrences(
 source_id TEXT NOT NULL REFERENCES sources(id), snapshot_id TEXT NOT NULL REFERENCES snapshots(id),
 locator INTEGER NOT NULL, source_keyword TEXT, observed_at TEXT, observed_at_raw TEXT,
 published_at_utc TEXT, timezone_basis TEXT, imported_at TEXT NOT NULL,
 UNIQUE(source_id,locator,snapshot_id));
CREATE TABLE IF NOT EXISTS imports(
 id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id), started_at TEXT NOT NULL,
 finished_at TEXT NOT NULL, status TEXT NOT NULL, report TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value INTEGER NOT NULL);
INSERT OR IGNORE INTO meta VALUES('revision',0);
CREATE INDEX IF NOT EXISTS occurrence_snapshot ON occurrences(snapshot_id);
CREATE INDEX IF NOT EXISTS source_path ON sources(path,status);
CREATE INDEX IF NOT EXISTS occurrence_source ON occurrences(source_id,snapshot_id);
CREATE INDEX IF NOT EXISTS snapshot_entity ON snapshots(entity_id);
CREATE TABLE IF NOT EXISTS record_metadata(
 source_id TEXT NOT NULL REFERENCES sources(id), snapshot_id TEXT NOT NULL REFERENCES snapshots(id),
 locator INTEGER NOT NULL, reply_count INTEGER, PRIMARY KEY(source_id,snapshot_id,locator));
'''


class KnowledgeStore:
    def __init__(self, root=None, db_path=None):
        self.root = Path(root).resolve() if root else project_root()
        self.db_path = Path(db_path).resolve() if db_path else self.root / '.runtime/research/index.sqlite3'
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            if conn.execute("SELECT name FROM sqlite_master WHERE name='schema_version'").fetchone():
                versions = [r[0] for r in conn.execute('SELECT version FROM schema_version')]
                if versions != [1]:
                    raise KnowledgeError('unsupported_schema_version')
            conn.executescript(SCHEMA)

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _path(self, value):
        path = (self.root / value).resolve()
        if not path.is_relative_to(self.root) or path.suffix.lower() not in ('.json', '.jsonl'):
            raise KnowledgeError('invalid_source_path')
        return path

    def _bytes(self, path):
        try:
            if path.stat().st_size > 50 * 1024 * 1024:
                raise KnowledgeError('source_too_large')
            return path.read_bytes()
        except OSError:
            raise KnowledgeError('source_unavailable') from None

    def _task(self, path, task_id, platform):
        if not task_id or not re.fullmatch('[a-f0-9]{32}', task_id):
            raise KnowledgeError('invalid_task_id')
        folder = self.root / 'MediaCrawler/data/tasks' / task_id
        if not path.is_relative_to((folder / 'output').resolve()) or not folder.resolve().is_relative_to(self.root):
            raise KnowledgeError('invalid_task_path')
        try:
            task = json.loads((folder / 'task.json').read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            raise KnowledgeError('task_unavailable') from None
        if not isinstance(task, dict) or task.get('platform') != platform or task.get('id') != task_id:
            raise KnowledgeError('task_mismatch')
        if task.get('status') not in ('completed', 'completed_with_errors', 'failed', 'stopped', 'interrupted'):
            raise KnowledgeError('task_not_finished')
        return task.get('status') != 'completed'

    def register_source(self, path, *, platform, source_type='legacy', task_id=None, source_timezone=None):
        if platform != 'tieba':
            raise KnowledgeError('unsupported_platform')
        if source_type not in ('task', 'legacy') or (source_type == 'legacy' and task_id is not None):
            raise KnowledgeError('invalid_arguments')
        if source_timezone:
            try:
                ZoneInfo(source_timezone)
            except (ZoneInfoNotFoundError, ValueError):
                raise KnowledgeError('invalid_timezone') from None
        path = self._path(path)
        relative = path.relative_to(self.root).as_posix()
        if source_type == 'legacy' and relative.startswith('MediaCrawler/data/tasks/'):
            raise KnowledgeError('task_source_required')
        partial = self._task(path, task_id, platform) if source_type == 'task' else True
        file_hash = digest(self._bytes(path))
        self.refresh()
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute("SELECT * FROM sources WHERE path=? AND status='active'", (relative,)).fetchone()
            if row:
                if (row['platform'], row['type'], row['task_id'], row['source_timezone']) != (platform, source_type, task_id, source_timezone):
                    raise KnowledgeError('source_metadata_conflict')
                return dict(row)
            ident = uuid.uuid4().hex
            conn.execute('INSERT INTO sources VALUES(?,?,?,?,?,?,?,?,?,?)',
                         (ident, platform, source_type, relative, file_hash, 'active', task_id, source_timezone, int(partial), now()))
            self._bump(conn)
            return dict(conn.execute('SELECT * FROM sources WHERE id=?', (ident,)).fetchone())

    @staticmethod
    def _bump(conn):
        conn.execute("UPDATE meta SET value=value+1 WHERE key='revision'")

    @staticmethod
    def _purge(conn):
        conn.execute("""UPDATE snapshots SET payload=NULL WHERE payload IS NOT NULL AND NOT EXISTS(
          SELECT 1 FROM occurrences o JOIN sources s ON s.id=o.source_id
          WHERE o.snapshot_id=snapshots.id AND s.status='active')""")
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='semantic_vectors'").fetchone():
            conn.execute('DELETE FROM semantic_vectors WHERE snapshot_id IN (SELECT id FROM snapshots WHERE payload IS NULL)')

    def refresh(self):
        changes = []
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            for row in conn.execute("SELECT * FROM sources WHERE status='active'").fetchall():
                status = None
                try:
                    path = self._path(row['path'])
                    if row['type'] == 'task':
                        self._task(path, row['task_id'], row['platform'])
                    if digest(self._bytes(path)) != row['file_hash']:
                        status = 'superseded'
                except KnowledgeError:
                    status = 'missing'
                if status:
                    conn.execute('UPDATE sources SET status=? WHERE id=?', (status, row['id']))
                    changes.append({'source_id': row['id'], 'status': status})
            if changes:
                self._purge(conn); self._bump(conn)
        return changes

    def revoke(self, source_id):
        """Unregister one indexed source; never delete the original file."""
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if not conn.execute('SELECT 1 FROM sources WHERE id=?', (source_id,)).fetchone():
                raise KnowledgeError('source_not_found')
            conn.execute("UPDATE sources SET status='deleted' WHERE id=?", (source_id,))
            self._purge(conn); self._bump(conn)

    def invalidate_path(self, path):
        """Deletion hook for one file or an entire task directory, without reading data."""
        target = (self.root / path).resolve()
        if not target.is_relative_to(self.root):
            raise KnowledgeError('invalid_source_path')
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            for row in conn.execute("SELECT id,path FROM sources WHERE status='active'").fetchall():
                source = (self.root / row['path']).resolve()
                if source == target or source.is_relative_to(target):
                    conn.execute("UPDATE sources SET status='deleted' WHERE id=?", (row['id'],))
            self._purge(conn); self._bump(conn)

    @staticmethod
    def _normalize(row, source_timezone):
        if not isinstance(row, dict):
            raise KnowledgeError('record_not_object')
        kind = 'comment' if any(key in row for key in ('comment_id', 'content', 'parent_comment_id')) else 'post'
        def ident(key, required=False):
            value = row.get(key)
            if value in (None, ''):
                if required:
                    raise KnowledgeError('missing_' + key)
                return None
            if type(value) not in (str, int) or not str(value).strip():
                raise KnowledgeError('invalid_' + key)
            return str(value)
        def text(key):
            value = row.get(key)
            if value is not None and not isinstance(value, str):
                raise KnowledgeError('invalid_' + key)
            return value
        external_id = ident('comment_id' if kind == 'comment' else 'note_id', True)
        payload = {'kind': kind, 'external_id': external_id,
            'title': text('title') if kind == 'post' else None,
            'body': text('desc' if kind == 'post' else 'content'),
            'post_external_id': ident('note_id', True) if kind == 'comment' else None,
            'parent_external_id': ident('parent_comment_id') if kind == 'comment' else None,
            'published_at_raw': text('publish_time'), 'creator_hash': text('creator_hash'),
            'user_nickname': text('user_nickname'), 'forum_name': text('tieba_name'),
            'forum_external_id': ident('tieba_id'), 'source_url': text('note_url')}
        if kind == 'comment' and payload['parent_external_id'] == external_id:
            raise KnowledgeError('self_parent')
        keyword = text('source_keyword')
        warnings, published, basis = [], None, 'unknown'
        if not payload['body']:
            warnings.append('empty_body')
        raw = payload['published_at_raw']
        if raw:
            try:
                dt = datetime.fromisoformat(raw)
                if dt.tzinfo is None:
                    if source_timezone:
                        dt = dt.replace(tzinfo=ZoneInfo(source_timezone)); basis = 'source_declared:' + source_timezone
                    else:
                        warnings.append('unknown_timezone'); dt = None
                else:
                    basis = 'source_explicit'
                if dt:
                    published = dt.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
            except ValueError:
                warnings.append('invalid_publish_time')
        observed_raw = row.get('last_modify_ts')
        observed = None
        if observed_raw is not None:
            if type(observed_raw) is int and 1_000_000_000_000 <= observed_raw < 100_000_000_000_000:
                try:
                    observed = datetime.fromtimestamp(observed_raw / 1000, timezone.utc).isoformat().replace('+00:00', 'Z')
                except (OverflowError, OSError, ValueError):
                    warnings.append('invalid_observed_time')
            else:
                warnings.append('invalid_observed_time')
        return payload, keyword, observed, observed_raw, published, basis, warnings

    def import_source(self, source_id):
        self.refresh()
        with self.connection() as conn:
            source = conn.execute('SELECT * FROM sources WHERE id=?', (source_id,)).fetchone()
        if not source:
            raise KnowledgeError('source_not_found')
        if source['status'] != 'active':
            raise KnowledgeError('source_unavailable')
        raw = self._bytes(self._path(source['path']))
        if digest(raw) != source['file_hash']:
            raise KnowledgeError('source_changed')
        report = {'import_id': uuid.uuid4().hex, 'source_id': source_id, 'started_at': now(),
                  'read': 0, 'valid': 0, 'new_entities': 0, 'new_snapshots': 0, 'new_occurrences': 0,
                  'reused_snapshots': 0, 'skipped': 0, 'errors': [], 'warnings': [], 'source_partial': bool(source['partial'])}
        records = []
        try:
            text = raw.decode('utf-8-sig')
            if source['path'].lower().endswith('.jsonl'):
                for index, line in enumerate(text.splitlines(), 1):
                    if not line.strip():
                        continue
                    report['read'] += 1
                    try:
                        records.append((index, json.loads(line)))
                    except ValueError:
                        report['errors'].append({'locator': index, 'code': 'invalid_json_line'})
            else:
                rows = json.loads(text)
                if not isinstance(rows, list):
                    raise ValueError()
                records = list(enumerate(rows, 1)); report['read'] = len(rows)
        except (ValueError, UnicodeError):
            report['errors'].append({'locator': None, 'code': 'invalid_file_format'})
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            current = conn.execute('SELECT status FROM sources WHERE id=?', (source_id,)).fetchone()
            if current['status'] != 'active' or digest(self._bytes(self._path(source['path']))) != source['file_hash']:
                raise KnowledgeError('source_changed')
            for locator, row in records:
                try:
                    payload, keyword, observed, observed_raw, published, basis, warnings = self._normalize(row, source['source_timezone'])
                except KnowledgeError as exc:
                    report['errors'].append({'locator': locator, 'code': exc.code}); continue
                report['valid'] += 1
                report['warnings'].extend({'locator': locator, 'code': w} for w in warnings)
                entity = conn.execute('SELECT id FROM entities WHERE platform=? AND kind=? AND external_id=?',
                                      (source['platform'], payload['kind'], payload['external_id'])).fetchone()
                entity_id = entity['id'] if entity else uuid.uuid4().hex
                if not entity:
                    conn.execute('INSERT INTO entities VALUES(?,?,?,?)', (entity_id, source['platform'], payload['kind'], payload['external_id']))
                    report['new_entities'] += 1
                content_hash = digest(encode(payload).encode('utf-8'))
                snapshot = conn.execute('SELECT id FROM snapshots WHERE entity_id=? AND content_hash=?', (entity_id, content_hash)).fetchone()
                snapshot_id = snapshot['id'] if snapshot else uuid.uuid4().hex
                if snapshot:
                    conn.execute('UPDATE snapshots SET payload=? WHERE id=?', (encode(payload), snapshot_id))
                    report['reused_snapshots'] += 1
                else:
                    conn.execute('INSERT INTO snapshots VALUES(?,?,?,?,?,?)', (snapshot_id, entity_id, content_hash, encode(payload), now(), '0.1'))
                    report['new_snapshots'] += 1
                result = conn.execute('INSERT OR IGNORE INTO occurrences VALUES(?,?,?,?,?,?,?,?,?)',
                                     (source_id, snapshot_id, locator, keyword, observed, encode(observed_raw), published, basis, report['started_at']))
                report['new_occurrences'] += result.rowcount
                report['skipped'] += 1 - result.rowcount
                count = row.get('total_replay_num') if payload['kind'] == 'post' else None
                if isinstance(count, str) and count.isascii() and count.isdigit():
                    count = int(count)
                if type(count) is not int or not 0 <= count <= 9223372036854775807:
                    count = None
                conn.execute('INSERT OR REPLACE INTO record_metadata VALUES(?,?,?,?)', (source_id, snapshot_id, locator, count))
            report['status'] = 'partial' if report['errors'] and report['valid'] else 'failed' if report['errors'] else 'completed'
            report['error_count'] = len(report['errors'])
            report['warning_count'] = len(report['warnings'])
            report['finished_at'] = now()
            conn.execute('INSERT INTO imports VALUES(?,?,?,?,?,?)', (report['import_id'], source_id, report['started_at'], report['finished_at'], report['status'], encode(report)))
            if report['new_occurrences']:
                self._bump(conn)
        return report

    def list_sources(self):
        self.refresh()
        with self.connection() as conn:
            return [dict(r) for r in conn.execute('SELECT * FROM sources ORDER BY created_at,id')]

    def _active(self, conn, snapshot_id):
        snapshot = conn.execute('SELECT * FROM snapshots WHERE id=?', (snapshot_id,)).fetchone()
        if not snapshot:
            raise KnowledgeError('snapshot_not_found')
        rows = conn.execute("""SELECT o.*,s.path,s.partial FROM occurrences o JOIN sources s ON s.id=o.source_id
            WHERE o.snapshot_id=? AND s.status='active' ORDER BY o.observed_at DESC,o.imported_at DESC,o.source_id""", (snapshot_id,)).fetchall()
        if not rows or snapshot['payload'] is None:
            raise KnowledgeError('evidence_unavailable')
        return snapshot, rows

    def read_snapshot(self, snapshot_id):
        self.refresh()
        with self.connection() as conn:
            snapshot, rows = self._active(conn, snapshot_id)
            result = dict(snapshot); result['payload'] = json.loads(result['payload'])
            result['sources'] = [dict(r) for r in rows]
            payload = result['payload']
            result['relations'] = {}
            platform = conn.execute('SELECT platform FROM entities WHERE id=?', (snapshot['entity_id'],)).fetchone()[0]
            for label, kind, external in [('post', 'post', payload['post_external_id']), ('parent', 'comment', payload['parent_external_id'])]:
                if not external:
                    continue
                related = conn.execute("""SELECT e.id,p.payload FROM entities e JOIN snapshots p ON p.entity_id=e.id
                  JOIN occurrences o ON o.snapshot_id=p.id JOIN sources s ON s.id=o.source_id
                  WHERE e.platform=? AND e.kind=? AND e.external_id=? AND s.status='active' AND p.payload IS NOT NULL
                  ORDER BY o.observed_at DESC,o.imported_at DESC,p.id LIMIT 1""", (platform, kind, external)).fetchone()
                valid = related and (label != 'parent' or json.loads(related['payload'])['post_external_id'] == payload['post_external_id'])
                result['relations'][label] = {'status': 'resolved' if valid else 'unresolved', 'entity_id': related['id'] if valid else None, 'external_id': external}
            return result

    def list_snapshots(self):
        self.refresh()
        with self.connection() as conn:
            return [dict(r) for r in conn.execute("""SELECT DISTINCT p.id AS snapshot_id,e.id AS entity_id,e.kind,e.external_id
              FROM snapshots p JOIN entities e ON e.id=p.entity_id JOIN occurrences o ON o.snapshot_id=p.id
              JOIN sources s ON s.id=o.source_id WHERE s.status='active' AND p.payload IS NOT NULL ORDER BY e.kind,e.external_id,p.id""")]

    def reports(self, source_id=None):
        with self.connection() as conn:
            return [json.loads(r[0]) for r in conn.execute('SELECT report FROM imports WHERE (? IS NULL OR source_id=?) ORDER BY started_at,id', (source_id, source_id))]

    def compare_sources(self, before_source_ids, after_source_ids, limit=20, cursor=None, post_ids=None):
        from .changes import compare_sources
        return compare_sources(self, before_source_ids, after_source_ids, limit, cursor, post_ids)

    def maintenance(self):
        """Explicit local maintenance; no source deletion or remote requests."""
        changes = self.refresh()
        with self.connection() as conn:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='search_cursors'").fetchone():
                conn.execute("DELETE FROM search_cursors WHERE revision != (SELECT value FROM meta WHERE key='revision')")
            self._purge(conn)
            conn.execute('PRAGMA optimize')
            counts = {table: conn.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                      for table in ('sources', 'entities', 'snapshots', 'occurrences')}
            counts['active_snapshots'] = conn.execute('SELECT COUNT(*) FROM snapshots WHERE payload IS NOT NULL').fetchone()[0]
            counts['cached_vectors'] = conn.execute('SELECT COUNT(*) FROM semantic_vectors').fetchone()[0] if conn.execute("SELECT 1 FROM sqlite_master WHERE name='semantic_vectors'").fetchone() else 0
        return {'status': 'ok', 'changes': changes, 'counts': counts, 'database_bytes': self.db_path.stat().st_size,
                'storage': 'sqlite_single_process', 'source_files_deleted': 0}
