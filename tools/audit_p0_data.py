"""Read-only inventory for P0; emits counts/hashes, never cookies or post bodies."""
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
report = {'scope': ['testresult', 'MediaCrawler/data'], 'files': [], 'tasks': []}
for base in (ROOT / 'testresult', ROOT / 'MediaCrawler/data'):
    if not base.exists():
        continue
    for path in sorted(base.rglob('*')):
        if path.suffix not in ('.json', '.jsonl') or not path.is_file():
            continue
        if path.name == 'task.json':
            row = json.loads(path.read_text(encoding='utf-8-sig'))
            report['tasks'].append({key: row.get(key) for key in ('id', 'platform', 'status', 'created_at', 'max_notes_count', 'max_comments_count')})
            continue
        if '_contents_' not in path.name and '_comments_' not in path.name:
            continue
        raw = path.read_bytes()
        entry = {'path': path.relative_to(ROOT).as_posix(), 'sha256': hashlib.sha256(raw).hexdigest()}
        try:
            text = raw.decode('utf-8-sig')
            rows = json.loads(text) if path.suffix == '.json' else [json.loads(line) for line in text.splitlines() if line.strip()]
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError('Expected object records')
            kind = 'comment' if '_comments_' in path.name else 'post'
            key = 'comment_id' if kind == 'comment' else 'note_id'
            ids = [str(row[key]) for row in rows if row.get(key)]
            entry.update(kind=kind, records=len(rows), unique_ids=len(set(ids)), missing_id=len(rows)-len(ids),
                         keys=sorted(set().union(*(row.keys() for row in rows))),
                         missing_or_empty={field: sum(row.get(field) in (None, '') for row in rows)
                            for field in ('note_id', 'parent_comment_id', 'publish_time', 'last_modify_ts', 'source_keyword', 'desc' if kind == 'post' else 'content')},
                         source_keywords=dict(Counter(row.get('source_keyword', '<absent>') for row in rows)))
            entry['_ids'] = ids
            entry['_note_ids'] = [str(row['note_id']) for row in rows if row.get('note_id')]
        except (ValueError, UnicodeError) as exc:
            entry['error'] = type(exc).__name__
        report['files'].append(entry)
for scope in report['scope']:
    posts = set()
    for f in report['files']:
        if f['path'].startswith(scope + '/') and f.get('kind') == 'post':
            posts.update(f['_ids'])
    for f in report['files']:
        if f['path'].startswith(scope + '/') and f.get('kind') == 'comment':
            f['unmatched_post_ids_in_scope'] = sorted(set(f['_note_ids']) - posts)
for f in report['files']:
    f.pop('_ids', None); f.pop('_note_ids', None)
destination = ROOT / 'docs/p0/data-inventory.json'
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'files': len(report['files']), 'tasks': len(report['tasks']), 'samples': [f for f in report['files'] if f['path'].startswith('testresult/')]}, ensure_ascii=True))
