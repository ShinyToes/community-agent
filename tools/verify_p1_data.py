"""Import only the four P0-inventoried files and verify real-data invariants."""
import hashlib
import json
from pathlib import Path

from community_research.knowledge import KnowledgeStore


def main():
    root = Path(__file__).resolve().parents[1]
    inventory = json.loads((root / 'docs/p0/data-inventory.json').read_text(encoding='utf-8'))
    store = KnowledgeStore(root)
    results = []
    for entry in inventory['files']:
        path = root / entry['path']
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        assert before == entry['sha256'], f"P0 source changed: {entry['path']}"
        relative = path.relative_to(root)
        is_task = relative.parts[:3] == ('MediaCrawler', 'data', 'tasks')
        source = store.register_source(path, platform='tieba', source_type='task' if is_task else 'legacy',
                                       task_id=relative.parts[3] if is_task else None, source_timezone='Asia/Shanghai')
        report = store.import_source(source['id'])
        assert report['valid'] == entry['records'] and not report['errors']
        repeat = store.import_source(source['id'])
        assert all(repeat[field] == 0 for field in ('new_entities', 'new_snapshots', 'new_occurrences'))
        assert hashlib.sha256(path.read_bytes()).hexdigest() == before
        results.append({'path': entry['path'], 'source_id': source['id'], 'records': report['valid'],
                        'warnings': report['warnings'], 'source_partial': report['source_partial'],
                        'repeat_added': 0, 'original_unchanged': True})
    snapshots = store.list_snapshots()
    unresolved = sum(store.read_snapshot(row['snapshot_id'])['relations']['post']['status'] != 'resolved'
                     for row in snapshots if row['kind'] == 'comment')
    assert unresolved == 0
    with store.connection() as conn:
        counts = {table: conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                  for table in ('sources', 'entities', 'snapshots', 'occurrences')}
        kinds = dict(conn.execute('SELECT kind,COUNT(*) FROM entities GROUP BY kind').fetchall())
    output = {'status': 'passed', 'timezone_declaration': 'Asia/Shanghai (importer declared, not inferred)',
              'sources': results, 'counts': counts, 'entities_by_kind': kinds, 'unresolved_comment_posts': unresolved}
    folder = root / 'docs/p1'; folder.mkdir(exist_ok=True)
    (folder / 'validation-report.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': 'passed', 'counts': counts, 'entities_by_kind': kinds, 'unresolved_comment_posts': unresolved}))


if __name__ == '__main__':
    main()
