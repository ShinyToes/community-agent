"""Explicit live smoke of automatic task routing, no confirmation API."""
import asyncio
import json
import sys
from pathlib import Path
import httpx

async def main():
    results=[]
    questions=['只看已有数据，不要联网：有哪些提到donk的帖子？列举一条并附原文。','某某游戏最近在玩家群体里的评价如何？','到贴吧收集一些热门的打分帖，最多采1个帖子，不采评论。请说明样本限制并附原帖。']
    if '--online-only' in sys.argv:
        results=json.loads((Path(__file__).resolve().parents[1]/'docs/p5/live-validation.json').read_text(encoding='utf-8'))[:2]
        questions=questions[-1:]
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8080',timeout=20) as client:
        for question in questions:
            response=await client.post('/api/research/sessions',json={});response.raise_for_status();session=response.json()['id']
            response=await client.post(f'/api/research/sessions/{session}/messages',json={'text':question});response.raise_for_status();job=response.json()
            print(json.dumps({'session_id':session,'task_id':job['id']}),flush=True)
            for _ in range(210):
                response=await client.get(f'/api/research/sessions/{session}/collections');response.raise_for_status()
                job=next(j for j in response.json() if j['id']==job['id'])
                if job['status'] not in ('running','waiting_login','importing','answering'): break
                await asyncio.sleep(1)
            else:
                response=await client.post(f"/api/research/collections/{job['id']}/cancel",json={});response.raise_for_status();job=response.json()
            result={'question':question,'session_id':session,'job':job}
            if job['answer_run_id']:
                response=await client.get('/api/research/runs/'+job['answer_run_id']);response.raise_for_status()
                result['answer']=response.json()
            results.append(result)
            print(json.dumps({'status':job['status'],'error':job['error'],'route':job['progress'].get('strategy',{}).get('route'),'branches':len(job['progress']['branches'])}),flush=True)
            destination=Path(__file__).resolve().parents[1]/'docs/p5';destination.mkdir(exist_ok=True)
            (destination/'live-validation.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    # A one-post sample cannot establish popularity: an evidence-backed partial answer is correct.
    passed = results[0]['job']['status']=='completed' and not results[0]['job']['progress']['branches']
    passed &= results[1]['job']['status']=='waiting_user' and not results[1]['job']['progress']['branches']
    last=results[2]
    passed &= last['job']['status'] in ('completed','partial') and last.get('answer',{}).get('answer_available') is True
    passed &= bool(last['job']['progress']['branches']) and sum(b.get('posts',0) for b in last['job']['progress']['branches'])==1 and all(not b.get('comments') for b in last['job']['progress']['branches'])
    return 0 if passed else 1

if __name__=='__main__': raise SystemExit(asyncio.run(main()))
