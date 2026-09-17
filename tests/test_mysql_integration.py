import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from decimal import Decimal
from io import BytesIO
import json

import pytest
from flask_login import login_user
from sqlalchemy import text
from app.extensions import db
from app.models import User, Student, Enrollment, CourseOffering, Grade, AuditLog
from app.agent_models import ImportBatch, ChangeEvent
from app.services.imports.workflow import run_one, commit_batch
from app.services.enrollment_service import enroll_student
from test_agent_workflow import upload, approve_rows, process, post_json

pytestmark = pytest.mark.skipif(not os.getenv('AGENT_TEST_DATABASE_URL'), reason='requires tools/test_mysql.py')


def test_mysql_real_functions_and_import(app, client, login):
    token = login('admin')
    bid = upload(client, token, b'student_id,daily_score,midterm_score,final_score\nS1,90,90,90\nS2,80,80,80', options={'offering_id': 1})
    process(app)
    ready = approve_rows(client, token, bid)
    result = post_json(client, token, f'/imports/{bid}/commit', {'version': ready['version']})
    assert result.status_code == 200, result.data
    with app.app_context():
        assert Grade.query.filter_by(enrollment_id=1).one().gpa == Decimal('4.00')
        assert db.session.execute(text("SELECT fn_GetCompletedCredits('S1')")).scalar() == 3
        assert ChangeEvent.query.count() == 2
        assert all(log.user_id == 1 for log in AuditLog.query.all())
        assert AuditLog.query.count() == 2


def test_mysql_atomic_failure_after_first_write(app, client, login, monkeypatch):
    from app.services.imports import workflow
    token = login('admin')
    bid = upload(client, token, b'student_id,daily_score,midterm_score,final_score\nS1,90,90,90\nS2,80,80,80', options={'offering_id': 1})
    process(app)
    ready = approve_rows(client, token, bid)
    original, calls = workflow.apply_plan, []
    def fail(plan):
        calls.append(plan)
        if len(calls) > 1:
            raise ValueError('injected second-row failure')
        return original(plan)
    monkeypatch.setattr(workflow, 'apply_plan', fail)
    assert post_json(client, token, f'/imports/{bid}/commit', {'version': ready['version']}).status_code == 400
    with app.app_context():
        assert [g.total_score for g in Grade.query.all()] == [50, 50]
        assert AuditLog.query.count() == 0 and ChangeEvent.query.count() == 0


def test_mysql_concurrent_confirmation_one_receipt(app, client, login):
    token = login('admin')
    bid = upload(client, token, b'student_id,daily_score,midterm_score,final_score\nS1,90,90,90', options={'offering_id': 1})
    process(app)
    ready = approve_rows(client, token, bid)
    barrier = Barrier(2)
    def commit():
        with app.test_request_context():
            actor = db.session.get(User, 1)
            login_user(actor)
            barrier.wait(timeout=10)
            return commit_batch(bid, ready['version'], actor)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(commit) for _ in range(2)]
        results = [f.result(timeout=20) for f in futures]
    assert results[0] == results[1]
    with app.app_context():
        assert ChangeEvent.query.count() == 1


def test_mysql_concurrent_enrollment_last_seat(app):
    with app.app_context():
        db.session.query(Grade).delete()
        db.session.query(Enrollment).delete()
        offering = db.session.get(CourseOffering, 1)
        offering.cur_students, offering.max_students = 0, 1
        db.session.commit()
    barrier = Barrier(2)
    def enroll(sid):
        with app.app_context():
            barrier.wait(timeout=10)
            return enroll_student(sid, 1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(enroll, sid) for sid in ('S1', 'S2')]
        results = [f.result(timeout=20) for f in futures]
    assert sum(success for success, _ in results) == 1
    with app.app_context():
        assert Enrollment.query.count() == 1
        assert db.session.get(CourseOffering, 1).cur_students == 1


def test_mysql_manual_grade_route_uses_shared_service_and_audit(app, client, login):
    token = login('admin')
    result = client.post('/grades/offering/1', data={'csrf_token': token, 'daily_S1':'90',
        'midterm_S1':'90', 'final_S1':'90', 'makeup_S1':'', 'status_S1':'正常'})
    assert result.status_code == 302
    with app.app_context():
        assert Grade.query.filter_by(enrollment_id=1).one().gpa == 4
        assert AuditLog.query.one().user_id == 1
        assert ChangeEvent.query.one().source_type == 'manual'
