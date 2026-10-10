"""Opt-in live smoke: one Tieba query, one post, no comments, 180 seconds."""
import asyncio
import json
from pathlib import Path
import httpx


async def main():
    root = Path(__file__).resolve().parents[1]
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8080', timeout=40) as client:
        async def post(path, data):
            response = await client.post('/api/research' + path, json=data)
            response.raise_for_status()
            return response.json()
        session = await post('/sessions', {})
        question = '到贴吧搜索 donk，最多采集一个帖子，不采集评论，告诉我这次新采集帖子的标题和内容要点，引用原文。'
        job = await post('/sessions/' + session['id'] + '/collections', {'text': question})
        # Reviewing the generated query is part of this concrete one-post test budget.
        plan = {**job['plan'], 'queries': ['donk'], 'posts_per_query': 1, 'comment_posts': 0, 'seconds': 180}
        job = await post('/collections/' + job['id'] + '/execute', {'plan': plan})
        print(json.dumps({'session_id': session['id'], 'collection_id': job['id'], 'approved_plan': plan}), flush=True)
        previous = None
        for _ in range(210):
            response = await client.get('/api/research/sessions/' + session['id'] + '/collections'); response.raise_for_status()
            job = next(j for j in response.json() if j['id'] == job['id'])
            if job['status'] != previous:
                print(json.dumps({'status': job['status'], 'error': job['error']}), flush=True)
                previous = job['status']
            if job['status'] not in ('running', 'waiting_login', 'importing', 'answering'):
                break
            await asyncio.sleep(1)
        else:
            job = await post('/collections/' + job['id'] + '/cancel', {})
        report = {'session_id': session['id'], 'collection_id': job['id'], 'status': job['status'], 'error': job['error'],
                  'plan': job['plan'], 'progress': job['progress'], 'answer_run_id': job['answer_run_id'], 'manual_semantic_review': 'pending'}
        if job['answer_run_id']:
            response = await client.get('/api/research/runs/' + job['answer_run_id']); response.raise_for_status()
            run = response.json()
            report.update(answer_status=run['status'], usage=run['usage'], answer_available=run.get('answer_available'), answer=run['answer'], source_cards=run.get('source_cards'))
        target = root / 'docs/p4'; target.mkdir(exist_ok=True)
        (target / 'live-validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({key: report[key] for key in ('status', 'error', 'answer_run_id')}), flush=True)
        return 0 if job['status'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
