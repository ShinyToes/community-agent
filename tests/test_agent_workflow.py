from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from decimal import Decimal
import json
from unittest.mock import Mock

import pytest
from flask_login import login_user

from app.extensions import db
from app.models import User, Student, Grade, Course, CourseOffering, RewardPunishment
from app.agent_models import ImportBatch, ImportRow, ChangeEvent, ChangeDraft, Conversation
from app.services.imports.workflow import run_one
from app.services.imports.profiles import plan_row
from app.agent.tools import propose_change


@pytest.fixture(autouse=True)
def document_dir(app, tmp_path):
    app.config['DOCUMENT_FOLDER'] = str(tmp_path / 'documents')


def upload(client, token, content, kind='grades', options=None, filename='data.csv'):
    result = client.post('/imports', data={'csrf_token': token, 'kind': kind,
        'options': json.dumps(options or {}), 'file': (BytesIO(content), filename)})
    assert result.status_code == 202, result.data
    return result.json['id']


def process(app):
    with app.app_context():
        assert run_one()


def headers(token):
    return {'X-CSRFToken': token}


def post_json(client, token, path, value):
    return client.post(path, json=value, headers=headers(token))


def approve_rows(client, token, bid):
    detail = client.get('/imports/' + bid).json
    for row in detail['rows']:
        if row['plan'] and row['plan']['action'] == 'update':
            result = client.patch(f'/imports/{bid}/rows/{row["id"]}', json={
                'version': detail['version'], 'allow_update': True}, headers=headers(token))
            assert result.status_code == 200
            detail = client.get('/imports/' + bid).json
    return detail


def test_grade_import_preview_commit_provenance_and_idempotency(app, client, login):
    token = login('admin')
    bid = upload(client, token, '学号,姓名,平时,期中,期末\nS1,学生1,90,80,85\n'.encode(), options={'offering_id': 1})
    process(app)
    initial = client.get('/imports/' + bid).json
    assert initial['status'] == 'needs_review'
    with app.app_context():
        assert Grade.query.filter_by(enrollment_id=1).one().total_score == 50
    ready = approve_rows(client, token, bid)
    assert ready['status'] == 'ready'
    response = post_json(client, token, f'/imports/{bid}/commit', {'version': ready['version']})
    assert response.status_code == 200, response.data
    again = post_json(client, token, f'/imports/{bid}/commit', {'version': ready['version']})
    assert again.json == response.json
    with app.app_context():
        assert Grade.query.filter_by(enrollment_id=1).one().total_score == Decimal('85.0')
        event = ChangeEvent.query.one()
        assert event.source_type == 'document' and event.before['total_score'] == '50.00'
        row = db.session.get(ImportRow, event.row_id)
        assert row.source['row'] == 2 and row.raw['学号'] == 'S1'


@pytest.mark.parametrize('kind,content,model', [
    ('students', '学号,姓名,性别,专业编号,班级编号,入学年,学制,培养层次\n0007,新学生,女,1,1,2026,4,本科\n', Student),
    ('courses', '课程代码,课程名称,学分,学时,课程性质\nNEW,新课程,2,32,选修\n', Course),
    ('offerings', '课程代码,教师编号,学年,学期,容量\nCS1,1,2027-2028,第一学期,30\n', CourseOffering),
    ('rewards', '学号,类型,标题,日期\nS1,奖励,测试奖,2026-09-16\n', RewardPunishment),
])
def test_each_business_profile(app, client, login, kind, content, model):
    token = login('admin')
    with app.app_context():
        previous = model.query.count()
    bid = upload(client, token, content.encode(), kind=kind)
    process(app)
    ready = client.get('/imports/' + bid).json
    assert ready['status'] == 'ready', ready
    result = post_json(client, token, f'/imports/{bid}/commit', {'version': ready['version']})
    assert result.status_code == 200, result.data
    with app.app_context():
        assert model.query.count() == previous + 1
        if kind == 'students':
            assert db.session.get(Student, '0007')


def test_changed_database_rejects_old_preview(app, client, login):
    token = login('admin')
    bid = upload(client, token, b'student_id,daily_score,midterm_score,final_score\nS1,90,90,90', options={'offering_id': 1})
    process(app)
    ready = approve_rows(client, token, bid)
    with app.app_context():
        Grade.query.filter_by(enrollment_id=1).one().final_score = 60
        db.session.commit()
    result = post_json(client, token, f'/imports/{bid}/commit', {'version': ready['version']})
    assert result.status_code == 409
    with app.app_context():
        assert ChangeEvent.query.count() == 0


def test_import_failure_rolls_back_all_rows(app, client, login, monkeypatch):
    from app.services.imports import workflow
    token = login('admin')
    bid = upload(client, token, b'student_id,daily_score,midterm_score,final_score\nS1,90,90,90\nS2,80,80,80', options={'offering_id': 1})
    process(app)
    ready = approve_rows(client, token, bid)
    original, called = workflow.apply_plan, []
    def fail(plan):
        called.append(plan)
        if len(called) == 2:
            raise ValueError('injected failure')
        return original(plan)
    monkeypatch.setattr(workflow, 'apply_plan', fail)
    result = post_json(client, token, f'/imports/{bid}/commit', {'version': ready['version']})
    assert result.status_code == 400
    with app.app_context():
        assert [g.total_score for g in Grade.query.all()] == [50, 50]
        assert ChangeEvent.query.count() == 0
        assert db.session.get(ImportBatch, bid).status == 'ready'


def test_student_cannot_import_or_query_others(app, client, login):
    token = login()
    assert client.post('/imports', data={'csrf_token': token, 'kind': 'students',
        'file': (BytesIO(b'data'), 'test.csv')}).status_code == 403
    forbidden = post_json(client, token, '/agent/query', {'kind': 'grades', 'filters': {'student_id': 'S2'}})
    assert forbidden.status_code == 403
    own = post_json(client, token, '/agent/query', {'kind': 'grades', 'filters': {}})
    assert own.status_code == 200 and {r['student_id'] for r in own.json['rows']} == {'S1'}
    assert post_json(client, token, '/agent/query', {'kind': 'grade_summary', 'filters': {'offering_id': '1'}}).status_code == 403


def test_chat_mutation_is_only_a_draft_until_confirmed(app, client, login):
    token = login('admin')
    cid = post_json(client, token, '/agent/conversations', {}).json['id']
    mock = Mock()
    mock.complete.return_value = {'tool_calls': [{'id': 'call1', 'type': 'function', 'function': {
        'name': 'propose_change', 'arguments': json.dumps({'kind': 'grades',
            'candidate': {'student_id': 'S1', 'offering_id': '1', 'final_score': '85'},
            'reason': '教师复核'})}}]}
    app.config['LLM_CLIENT'] = mock
    response = post_json(client, token, f'/agent/conversations/{cid}/messages',
        {'text': '将S1在开课1的期末成绩改成85，原因教师复核'})
    assert response.status_code == 200, response.data
    draft = response.json['results'][0]['draft_id']
    with app.app_context():
        assert Grade.query.filter_by(enrollment_id=1).one().final_score == 50
    committed = post_json(client, token, f'/agent/drafts/{draft}/confirm', {})
    assert committed.status_code == 200, committed.data
    assert post_json(client, token, f'/agent/drafts/{draft}/confirm', {}).json == committed.json
    with app.app_context():
        assert Grade.query.filter_by(enrollment_id=1).one().final_score == 85
        assert ChangeEvent.query.one().source_type == 'conversation'


def test_model_cannot_call_raw_sql(app, client, login):
    token = login('admin')
    cid = post_json(client, token, '/agent/conversations', {}).json['id']
    mock = Mock()
    mock.complete.side_effect = [
        {'tool_calls': [{'id': 'evil', 'type': 'function', 'function': {
            'name': 'execute_sql', 'arguments': '{"sql":"DELETE FROM student"}'}}]},
        {'content': 'done'},
    ]
    app.config['LLM_CLIENT'] = mock
    result = post_json(client, token, f'/agent/conversations/{cid}/messages', {'text': '删除所有学生'})
    assert 'error' in result.json['results'][0]
    with app.app_context():
        assert Student.query.count() == 2


def test_xlsx_formula_rejected(app, client, login):
    from openpyxl import Workbook
    token = login('admin')
    wb = Workbook()
    wb.active.append(['student_id', 'final_score'])
    wb.active.append(['S1', '=1+1'])
    buffer = BytesIO()
    wb.save(buffer)
    bid = upload(client, token, buffer.getvalue(), options={'offering_id': 1}, filename='formula.xlsx')
    process(app)
    detail = client.get('/imports/' + bid).json
    assert detail['status'] == 'failed' and '公式' in detail['error']


def test_duplicate_and_invalid_rows_block_commit(app, client, login):
    token = login('admin')
    bid = upload(client, token, b'student_id,daily_score,midterm_score,final_score\nS1,90,90,90\nS1,80,80,80\nS2,NaN,70,70', options={'offering_id': 1})
    process(app)
    detail = approve_rows(client, token, bid)
    assert detail['status'] == 'needs_review'
    assert any('重复' in (r['error'] or '') for r in detail['rows'])
    assert post_json(client, token, f'/imports/{bid}/commit', {'version': detail['version']}).status_code == 409


def test_cancel_prevents_worker_and_confirmation(app, client, login):
    token = login('admin')
    bid = upload(client, token, b'student_id,final_score\nS1,80', options={'offering_id': 1})
    assert post_json(client, token, f'/imports/{bid}/cancel', {}).status_code == 200
    with app.app_context():
        assert not run_one()
    assert post_json(client, token, f'/imports/{bid}/commit', {'version': 1}).status_code == 409


def test_numeric_xlsx_identifier_preserves_explicit_padding(app, tmp_path):
    from openpyxl import Workbook
    from app.services.imports.parsers import parse_document
    wb = Workbook()
    wb.active.append(['student_id', 'name'])
    wb.active.append([7, '学生'])
    wb.active['A2'].number_format = '0000'
    path = tmp_path / 'padded.xlsx'
    wb.save(path)
    with app.app_context():
        assert parse_document(path, 'students', {})[0]['candidate']['student_id'] == '0007'


def test_row_must_belong_to_batch_and_version_must_match(app, client, login):
    token = login('admin')
    content = b'student_id,final_score\nS1,80'
    first = upload(client, token, content, options={'offering_id': 1})
    second = upload(client, token, content, options={'offering_id': 1})
    process(app)
    process(app)
    a, b = (client.get('/imports/' + bid).json for bid in (first, second))
    url = f'/imports/{first}/rows/{b["rows"][0]["id"]}'
    assert client.patch(url, json={'version': a['version'], 'excluded': True}, headers=headers(token)).status_code == 404
    url = f'/imports/{first}/rows/{a["rows"][0]["id"]}'
    assert client.patch(url, json={'version': a['version'] - 1, 'excluded': True}, headers=headers(token)).status_code == 409
    client.post('/auth/logout', data={'csrf_token': token})
    token = login('student1')
    assert client.get('/imports/' + first).status_code == 403
    assert client.get(f'/imports/{first}/document').status_code == 403


def test_cancelled_lease_cannot_publish(app, client, login, monkeypatch):
    from app.services.imports import workflow
    token = login('admin')
    bid = upload(client, token, b'student_id,final_score\nS1,80', options={'offering_id': 1})
    def cancelled(*args, **kwargs):
        batch = db.session.get(ImportBatch, bid)
        batch.status, batch.lease_token = 'cancelled', None
        db.session.commit()
        kwargs['heartbeat']()
    monkeypatch.setattr(workflow, 'parse_document', cancelled)
    process(app)
    detail = client.get('/imports/' + bid).json
    assert detail['status'] == 'cancelled' and detail['rows'] == []


def test_unstructured_model_must_supply_source_evidence(app, tmp_path, monkeypatch):
    from app.services.imports import parsers
    monkeypatch.setattr(parsers, '_text_sections', lambda *args: [{'page': 1, 'text': 'S1 score 80'}])
    mock = Mock()
    mock.complete.return_value = {'content': json.dumps({'rows': [
        {'source_index': 0, 'data': {'student_id': 'S1', 'final_score': '99'}}]})}
    app.config['LLM_CLIENT'] = mock
    with app.app_context(), pytest.raises(ValueError, match='原文证据'):
        parsers.parse_document(tmp_path / 'source.pdf', 'grades', {})


@pytest.mark.parametrize('kind,candidate', [
    ('students', {'student_id': 'N1', 'name': '新生', 'gender': '女', 'major_id': '1', 'class_id': '2', 'enrollment_year': '2026', 'education_level': '本科', 'education_length': '4'}),
    ('courses', {'course_code': 'BAD', 'course_name': '课程', 'credits': '-1', 'hours': '32', 'course_type': '必修'}),
    ('offerings', {'course_code': 'CS1', 'teacher_id': '999', 'academic_year': '2027-2028', 'semester': '第一学期', 'max_students': '30'}),
    ('rewards', {'student_id': 'S1', 'type': '奖励', 'title': '奖项', 'rp_date': '2026-99-99'}),
])
def test_invalid_business_profile_rejected(app, kind, candidate):
    with app.app_context(), pytest.raises(ValueError):
        plan_row(kind, candidate)
