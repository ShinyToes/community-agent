"""Explicit, local-only P1 ingestion commands."""
import argparse
import json
import sys
from pathlib import Path

from .knowledge import KnowledgeError, KnowledgeStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root')
    parser.add_argument('--db')
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('register', 'ingest'):
        command = commands.add_parser(name)
        command.add_argument('path')
        command.add_argument('--platform', required=True, choices=['tieba'])
        command.add_argument('--type', dest='source_type', choices=['legacy', 'task'], default='legacy')
        command.add_argument('--task-id')
        command.add_argument('--timezone', dest='source_timezone')
    for name in ('import', 'read', 'revoke'):
        commands.add_parser(name).add_argument('id')
    for name in ('sources', 'snapshots', 'refresh', 'maintenance'):
        commands.add_parser(name)
    commands.add_parser('reports').add_argument('--source')
    query = commands.add_parser('tool', help='Call a P2 read-only tool using a UTF-8 JSON arguments file')
    query.add_argument('tool', choices=['search_posts', 'search_comments', 'read_evidence', 'hybrid_search', 'compare_sources', 'source_versions'])
    query.add_argument('--arguments', required=True)
    args = parser.parse_args()
    try:
        store = KnowledgeStore(args.root, args.db)
        if args.command == 'tool':
            from .knowledge.search import SearchService
            try:
                arguments = json.loads(Path(args.arguments).read_text(encoding='utf-8-sig'))
            except (OSError, ValueError):
                raise KnowledgeError('invalid_arguments') from None
            result = SearchService(store).call(args.tool, arguments)
        elif args.command in ('register', 'ingest'):
            result = store.register_source(args.path, platform=args.platform, source_type=args.source_type,
                                          task_id=args.task_id, source_timezone=args.source_timezone)
            if args.command == 'ingest':
                result = store.import_source(result['id'])
        elif args.command == 'import':
            result = store.import_source(args.id)
        elif args.command == 'read':
            result = store.read_snapshot(args.id)
        elif args.command == 'revoke':
            store.revoke(args.id)
            result = {'status': 'revoked', 'source_id': args.id}
        elif args.command == 'reports':
            result = store.reports(args.source)
        else:
            result = getattr(store, {'sources': 'list_sources', 'snapshots': 'list_snapshots', 'refresh': 'refresh', 'maintenance': 'maintenance'}[args.command])()
    except KnowledgeError as exc:
        print(json.dumps({'error': exc.code}))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if isinstance(result, dict) and result.get('status') in ('failed', 'error') else 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
