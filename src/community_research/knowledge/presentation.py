"""Source cards derived from verified evidence, never from model-generated titles."""
import json
from urllib.parse import urlparse

from .store import KnowledgeError


def source_cards(tools, evidence_ids):
    tools.store.refresh()
    cards, invalid = {}, []
    with tools.store.connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        catalog = tools._latest(tools._catalog(conn))
        posts = {row['external_id']: row for row in catalog if row['kind'] == 'post'}
        for ident in dict.fromkeys(evidence_ids):
            try:
                piece, payload = tools._read_piece(conn, ident)
            except KnowledgeError:
                invalid.append(ident)
                continue
            entity = piece['entity_id']
            if entity not in cards:
                parent_row = posts.get(payload['post_external_id']) if payload['kind'] == 'comment' else None
                parent = json.loads(parent_row['payload']) if parent_row else payload if payload['kind'] == 'post' else None
                post_snapshot = parent_row['snapshot_id'] if parent_row else piece['snapshot_id'] if payload['kind'] == 'post' else None
                stats = conn.execute('''SELECT m.reply_count,o.observed_at,o.timezone_basis FROM occurrences o
                    JOIN sources s ON s.id=o.source_id LEFT JOIN record_metadata m
                    ON m.source_id=o.source_id AND m.snapshot_id=o.snapshot_id AND m.locator=o.locator
                    WHERE o.snapshot_id=? AND s.status='active'
                    ORDER BY o.observed_at DESC,o.imported_at DESC,o.source_id DESC LIMIT 1''', (post_snapshot,)).fetchone()
                url = payload['source_url'] or (parent or {}).get('source_url')
                try:
                    valid_url = url and urlparse(url).scheme in ('http', 'https') and urlparse(url).hostname
                except ValueError:
                    valid_url = False
                cards[entity] = {'entity_id': entity, 'kind': payload['kind'], 'external_id': payload['external_id'],
                                 'snapshot_id': piece['snapshot_id'], 'post_snapshot_id': post_snapshot,
                                 'title': (parent or {}).get('title') or '标题未采集', 'source_url': url if valid_url else None,
                                 'post_published_at': (parent or {}).get('published_at_raw'),
                                 'post_reply_count': stats['reply_count'] if stats else None,
                                 'post_observed_at': stats['observed_at'] if stats else None,
                                 'post_timezone_basis': stats['timezone_basis'] if stats else None,
                                 'evidence_ids': [], 'excerpts': []}
            card = cards[entity]
            card['evidence_ids'].append(ident)
            quote = piece['quote'].strip()
            if quote and not any(e['quote'] == quote[:240] for e in card['excerpts']):
                card['excerpts'].append({'field': piece['field'], 'quote': quote[:240], 'truncated': len(quote) > 240 or piece['truncated'], 'evidence_id': ident})
    return list(cards.values()), invalid
