"""Check P0 documents/fixtures only; this is not a production retrieval implementation."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs/p0'
fixture = json.loads((DOCS / 'fixtures.json').read_text(encoding='utf-8'))
records = {row['id']: row for row in fixture['records']}
assert len(records) == len(fixture['records'])
assert len({case['id'] for case in fixture['cases']}) == len(fixture['cases'])
checked_queries = 0
for case in fixture['cases']:
    for ident in case.get('record_ids', []) + case.get('expected_ids', []):
        assert ident in records, (case['id'], ident)
    assert case.get('expected') or 'expected_ids' in case
    if case['action'] not in ('post_search', 'comment_search'):
        continue
    kind = 'post' if case['action'] == 'post_search' else 'comment'
    q = case['query']
    matched = []
    for row in records.values():
        if row['kind'] != kind:
            continue
        texts = [str(row.get(field, '')).casefold() for field in ('title', 'body')]
        def hit(term):
            return any(term.casefold() in text for text in texts)
        if all(hit(term) for term in q.get('all_terms', [])) and (not q.get('any_terms') or any(hit(term) for term in q['any_terms'])) and not any(hit(term) for term in q.get('exclude_terms', [])):
            matched.append(row['id'])
    assert sorted(matched) == sorted(case['expected_ids']), (case['id'], matched)
    checked_queries += 1
for doc in DOCS.glob('*.md'):
    for link in re.findall(r'\]\(([^)]+)\)', doc.read_text(encoding='utf-8')):
        if '://' not in link and not link.startswith('#'):
            assert (doc.parent / link.split('#')[0]).exists(), (doc.name, link)
inventory = json.loads((DOCS / 'data-inventory.json').read_text(encoding='utf-8'))
for entry in inventory['files']:
    assert hashlib.sha256((ROOT / entry['path']).read_bytes()).hexdigest() == entry['sha256'], entry['path']
result = {'status': 'passed', 'scope': 'P0 materials only; no product implementation or model evaluation',
          'fixture_records': len(records), 'specified_cases': len(fixture['cases']),
          'literal_expectations_checked': checked_queries, 'source_hashes_checked': len(inventory['files'])}
(DOCS / 'validation-report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(result))
