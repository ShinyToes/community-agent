"""Read-only real-data search checks; writes only evidence/cursors and this report."""
import hashlib
import json
from pathlib import Path

from community_research.knowledge import KnowledgeStore
from community_research.knowledge.search import SearchService


def main():
    root = Path(__file__).resolve().parents[1]
    inventory = json.loads((root / 'docs/p0/data-inventory.json').read_text(encoding='utf-8'))
    def verify_files():
        for entry in inventory['files']:
            assert hashlib.sha256((root / entry['path']).read_bytes()).hexdigest() == entry['sha256']
    verify_files()
    store = KnowledgeStore(root)
    service = SearchService(store)
    counts = {}
    for tool, expected in [('search_posts', 57), ('search_comments', 149)]:
        ids, cursor, pages = [], None, 0
        while True:
            result = service.call(tool, {'limit': 7, 'cursor': cursor})
            assert result['error'] is None
            ids.extend(row['entity_id'] for row in result['items'])
            pages += 1
            cursor = result['coverage']['next_cursor']
            if not cursor:
                break
        assert len(ids) == len(set(ids)) == expected
        counts[tool] = {'unique_entities': len(ids), 'pages': pages}
    queries = {'and': {'all_terms': ['cs', '饰品']}, 'or': {'any_terms': ['cs', '饰品']},
               'contiguous': {'all_terms': ['cs饰品']}, 'comment_cs': {'all_terms': ['cs']}}
    stats, sets, evidence_checks = {}, {}, 0
    for label, query in queries.items():
        result = service.call('search_comments' if label == 'comment_cs' else 'search_posts', dict(query, limit=50))
        assert result['error'] is None
        stats[label] = result['coverage']['total']
        assert not result['coverage']['has_more']
        sets[label] = {r['entity_id'] for r in result['items']}
        for row in result['items']:
            snapshot = store.read_snapshot(row['snapshot_id'])
            for snippet in row['snippets']:
                read = service.call('read_evidence', {'evidence_ids': [snippet['evidence_id']]})
                assert read['error'] is None
                piece = read['items'][0]
                assert piece['quote'] == snapshot['payload'][piece['field']][piece['start']:piece['end']]
                assert piece['snapshot_id'] == row['snapshot_id']
                evidence_checks += 1
    assert sets['contiguous'] <= sets['and'] <= sets['or']
    verify_files()
    report = {'status': 'passed', 'scope': 'local_imported_data_only', 'paging': counts, 'query_totals': stats,
              'evidence_slice_checks': evidence_checks, 'source_hashes_unchanged': len(inventory['files']),
              'limitations': ['literal matching, not semantic relevance', 'no online collection or model evaluation']}
    output = root / 'docs/p2/validation-report.json'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True))


if __name__ == '__main__':
    main()
