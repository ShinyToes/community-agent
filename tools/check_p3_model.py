"""Opt-in live-provider smoke test, separate from deterministic tests."""
import argparse
import asyncio
import json
from pathlib import Path

from community_research.agent.model import ChatModel
from community_research.agent.runtime import Harness
from community_research.knowledge import KnowledgeStore


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--question', default='已导入的帖子中，有哪些同时讨论 CS 和饰品？请读取证据后引用回答。')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if not ChatModel(root).configured:
        print(json.dumps({'status': 'not_run', 'reason': 'model_not_configured'}))
        return 2
    # Use the existing web runtime; avoid interrupting active runs with a second harness.
    import httpx
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8080', timeout=15) as client:
        session = await client.post('/api/research/sessions'); session.raise_for_status()
        response = await client.post('/api/research/sessions/' + session.json()['id'] + '/runs', json={'text': args.question})
        response.raise_for_status(); ident = response.json()['run_id']
        for _ in range(100):
            response = await client.get('/api/research/runs/' + ident); response.raise_for_status()
            result = response.json()
            if result['status'] not in ('queued', 'running'):
                break
            await asyncio.sleep(1)
        report = {'run_id': ident, 'session_id': session.json()['id'], 'status': result['status'], 'error': result['error'],
                  'usage': result['usage'], 'outcome': (result.get('answer') or {}).get('outcome'),
                  'manual_semantic_review': 'pending', 'answer_available': result.get('answer_available')}
        destination = root / 'docs/p3'; destination.mkdir(exist_ok=True)
        (destination / 'live-validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report))
        return 0 if result['status'] in ('completed', 'partial', 'waiting_user') else 1


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
