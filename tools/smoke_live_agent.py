"""Small live-model checks using only the project's fictional demo data."""
from pathlib import Path
import sys
import re
import json
from io import BytesIO
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from app.extensions import db
from app.models import User, Student
from app.agent_models import ChangeDraft
from app.services.imports.workflow import run_one

if __name__ == '__main__':
    app = create_app()
    if not app.config.get('LLM_API_KEY'):
        raise SystemExit('DeepSeek key is not configured; no external requests sent.')
    client = app.test_client()
    with app.app_context():
        actor = User.query.filter_by(username='demo_admin', role='admin').one()
        actor_id = actor.user_id
        learner = db.session.get(Student, 'S2027001')
        if learner is None or learner.name != '演示学生':
            raise SystemExit('Fictional demo record missing; refusing to use other data.')
    with client.session_transaction() as session:
        session['_user_id'], session['_fresh'] = str(actor_id), True
    page = client.get('/agent')
    token = re.search(r'data-csrf="([^"]+)"', page.get_data(as_text=True)).group(1)
    headers = {'X-CSRFToken': token}
    results = []
    for label, prompt in [
        ('course_query', '查询当前数据库有哪些开课，给出开课编号和课程名称，不要假设当前学期。'),
        ('contact_draft', '将学号 S2027001 的邮箱改成 learner@example.org，原因：演示联系方式复核。只生成草稿。'),
    ]:
        cid = client.post('/agent/conversations', json={}, headers=headers).json['id']
        response = client.post(f'/agent/conversations/{cid}/messages', json={'text': prompt}, headers=headers)
        body = response.get_json()
        ok = response.status_code == 200 and bool(body.get('results'))
        if label == 'course_query':
            ok = ok and any(r.get('kind') == 'courses' and r.get('rows') for r in body['results'])
        else:
            drafts = [r['draft_id'] for r in (body or {}).get('results', []) if 'draft_id' in r]
            ok = ok and bool(drafts)
            with app.app_context():
                ok = ok and db.session.get(Student, 'S2027001').email is None
            for draft in drafts:
                client.post(f'/agent/drafts/{draft}/cancel', json={}, headers=headers)
        results.append({'case': label, 'passed': bool(ok), 'http_status': response.status_code,
                        'answer': (body or {}).get('answer', (body or {}).get('error'))})
    # Nonstandard headers: only header text is sent for model mapping.
    csv = '学生号码,学生姓名,奖励类别,荣誉名称,发生日期\nS2027001,演示学生,奖励,演示识别奖,2026-09-16\n'
    response = client.post('/imports', data={'csrf_token': token, 'kind': 'rewards',
        'file': (BytesIO(csv.encode()), 'live-header-test.csv')})
    bid = response.json['id']
    with app.app_context():
        run_one()
    result = client.get('/imports/' + bid).json
    results.append({'case': 'header_mapping', 'passed': result['status'] == 'ready',
                    'status': result['status'], 'error': result['error']})
    client.post(f'/imports/{bid}/cancel', json={}, headers=headers)
    output = Path(app.instance_path) / 'live-model-smoke.json'
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps([{'case': r['case'], 'passed': r['passed']} for r in results]))
    raise SystemExit(0 if all(r['passed'] for r in results) else 1)
