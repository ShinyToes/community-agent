"""Explicit live multi-turn regression; uses configured web runtime and a fresh session."""
import asyncio
import json
from pathlib import Path
import httpx


async def main():
    reports = []
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8080', timeout=20) as client:
        response = await client.get('/api/research/config'); response.raise_for_status()
        if not response.json()['configured']:
            raise RuntimeError('model_not_configured')
        response = await client.post('/api/research/sessions'); response.raise_for_status()
        session = response.json()['id']
        for question in ['已采集内容中，是否有关于小蜜蜂的评论或帖子', '返回所有关于小蜜蜂的帖子或者评论', '就这两条吗', '就这两条吗']:
            response = await client.post(f'/api/research/sessions/{session}/runs', json={'text': question})
            response.raise_for_status(); run = response.json()['run_id']
            for _ in range(100):
                response = await client.get('/api/research/runs/' + run); response.raise_for_status()
                result = response.json()
                if result['status'] not in ('running', 'queued'):
                    break
                await asyncio.sleep(1)
            row = {'turn': len(reports) + 1, 'run_id': run, 'status': result['status'], 'error': result['error'],
                   'usage': result['usage'], 'answer_available': result.get('answer_available')}
            reports.append(row); print(json.dumps(row), flush=True)
            if result['error']:
                break
    output = {'session_id': session, 'runs': reports, 'passed': len(reports) == 4 and all(not r['error'] and r['answer_available'] for r in reports), 'semantic_review': 'pending'}
    (Path(__file__).resolve().parents[1] / 'docs/p3/followup-validation.json').write_text(json.dumps(output, indent=2), encoding='utf-8')
    return 0 if output['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
