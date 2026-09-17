from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

import pytest
from flask_login import login_user
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.models import Grade, File, User, Student, MajorChange, Enrollment
from app.services.grade_validation import parse_score, weighted_total
from app.services.file_service import save_uploaded_file, delete_file_record, resolve_file_path
from app.blueprints import grade_bp as grades


@pytest.mark.parametrize('value', ['NaN', 'Infinity', '-1', '101', 'abc'])
def test_invalid_score(value):
    with pytest.raises(ValueError):
        parse_score(value)


def test_zero_weight_and_incomplete_scores():
    assert weighted_total([None, None, 80], [0, 0, 1]) == Decimal('80.0')
    assert weighted_total([0, 0, 0], ['.3', '.3', '.4']) == 0
    assert weighted_total([100, None, 80], ['.3', '.3', '.4']) is None
    with pytest.raises(ValueError):
        weighted_total([90, 90, 90], [0, 0, 0])


def grade_form(token, s1='90', s2='80'):
    data = {'csrf_token': token}
    for sid, value in [('S1', s1), ('S2', s2)]:
        data.update({f'daily_{sid}': value, f'midterm_{sid}': value,
                     f'final_{sid}': value, f'makeup_{sid}': '', f'status_{sid}': '正常'})
    return data


def test_invalid_second_grade_leaves_entire_batch_unchanged(app, client, login):
    token = login('admin')
    result = client.post('/grades/offering/1', data=grade_form(token, s2='NaN'))
    assert result.status_code == 302
    with app.app_context():
        assert [g.total_score for g in Grade.query.order_by(Grade.grade_id)] == [50, 50]
        assert Grade.query.filter_by(enrollment_id=1).one().daily_score == 50


def test_failure_mid_batch_rolls_back(app, client, login, monkeypatch):
    token = login('admin')
    calls = []
    def gpa(score):
        calls.append(score)
        if len(calls) == 2:
            raise RuntimeError('injected model/database failure')
        return Decimal('4.0')
    monkeypatch.setattr(grades, 'score_to_gpa', gpa)
    with pytest.raises(RuntimeError):
        client.post('/grades/offering/1', data=grade_form(token))
    with app.app_context():
        assert [g.daily_score for g in Grade.query.order_by(Grade.grade_id)] == [50, 50]


def test_valid_batch_and_omitted_student(app, client, login, monkeypatch):
    token = login('admin')
    monkeypatch.setattr(grades, 'score_to_gpa', lambda _: Decimal('4.0'))
    data = grade_form(token, s1='0')
    data = {k: v for k, v in data.items() if not k.endswith('_S2')}
    assert client.post('/grades/offering/1', data=data).status_code == 302
    with app.app_context():
        assert Grade.query.filter_by(enrollment_id=1).one().total_score == 0
        assert Grade.query.filter_by(enrollment_id=2).one().total_score == 50
    page = client.get('/grades/offering/1').get_data(as_text=True)
    assert 'value="0.00"' in page


def test_upload_rolls_back_with_outer_student_edit(app):
    with app.test_request_context():
        login_user(db.session.get(User, 1))
        student = db.session.get(Student, 'S1')
        student.name = 'should rollback'
        file = save_uploaded_file(FileStorage(stream=BytesIO(b'hello'), filename='test.txt'), 'student', 'S1')
        path = resolve_file_path(file)
        assert path.exists()
        db.session.rollback()
        assert not path.exists()
        assert File.query.count() == 0
        assert db.session.get(Student, 'S1').name == '学生1'


def test_file_delete_deferred_until_commit(app):
    with app.test_request_context():
        login_user(db.session.get(User, 1))
        file = save_uploaded_file(FileStorage(stream=BytesIO(b'hello'), filename='test.txt'), 'student', 'S1')
        db.session.commit()
        fid = file.file_id
        path = resolve_file_path(file)
        delete_file_record(fid)
        assert path.exists()
        db.session.rollback()
        assert db.session.get(File, fid) and path.exists()
        delete_file_record(fid)
        db.session.commit()
        assert db.session.get(File, fid) is None and not path.exists()


def test_processed_application_cannot_be_rejected(app, client, login):
    token = login('admin')
    with app.app_context():
        db.session.add(MajorChange(change_id=1, student_id='S1', old_major_id=1,
                                   new_major_id=2, change_date=date.today(), approval_status='已通过'))
        db.session.commit()
    assert client.post('/major-changes/1/reject', data={'csrf_token': token}).status_code == 302
    with app.app_context():
        assert db.session.get(MajorChange, 1).approval_status == '已通过'


def test_audit_helper_never_commits(app, monkeypatch):
    from app.utils.audit import set_audit_user
    with app.test_request_context():
        login_user(db.session.get(User, 1))
        bind = Mock()
        bind.dialect.name = 'mysql'
        monkeypatch.setattr(db.session, 'get_bind', lambda: bind)
        execute, commit = Mock(), Mock()
        monkeypatch.setattr(db.session, 'execute', execute)
        monkeypatch.setattr(db.session, 'commit', commit)
        set_audit_user()
        assert execute.call_args.args[1] == {'uid': 1}
        commit.assert_not_called()


def test_zero_score_statistics(app, client, login):
    login('admin')
    with app.app_context():
        for grade in Grade.query.all():
            grade.total_score = 0
        db.session.commit()
    result = client.get('/statistics/api/scatter')
    assert result.status_code == 200 and result.json[0]['y'] == 0


def test_grade_updates_pass_status(app, client, login, monkeypatch):
    token = login('admin')
    monkeypatch.setattr(grades, 'score_to_gpa', lambda _: Decimal('2.0'))
    data = grade_form(token, s1='70', s2='50')
    client.post('/grades/offering/1', data=data)
    with app.app_context():
        assert db.session.get(Enrollment, 1).status == '已通过'
        assert db.session.get(Enrollment, 2).status == '未通过'


def test_score_badge_escapes_user_content():
    from app.utils.helpers import get_status_badge
    value = str(get_status_badge('<img src=x onerror=alert(1)>'))
    assert '<img' not in value and '&lt;img' in value


def test_student_major_class_must_match(app):
    from app.utils.validation import validate_student
    with app.app_context():
        student = db.session.get(Student, 'S1')
        student.class_id = 2
        with pytest.raises(ValueError, match='班级'):
            validate_student(student)
        db.session.rollback()


def test_student_date_is_parsed(app):
    from app.utils.validation import validate_student
    with app.app_context():
        student = db.session.get(Student, 'S1')
        student.birth_date = '2005-01-02'
        validate_student(student)
        assert student.birth_date == date(2005, 1, 2)


def test_refuse_original_database():
    from app import create_app
    with pytest.raises(RuntimeError, match='原实验'):
        create_app({'SECRET_KEY': 'test', 'SQLALCHEMY_DATABASE_URI':
                    'mysql+pymysql://localhost/student_management'})


def test_enroll_route_uses_only_shared_service(app, client, login, monkeypatch):
    from app.blueprints import enrollment_bp
    token = login()
    service = Mock(return_value=(False, '课程名额已满'))
    monkeypatch.setattr(enrollment_bp, 'enroll_student', service)
    result = client.post('/enrollments/enroll', data={'csrf_token': token, 'offering_id': 1})
    assert result.status_code == 302
    service.assert_called_once_with('S1', 1)
    with app.app_context():
        assert Enrollment.query.count() == 2


def test_invalid_offering_id(client, login):
    token = login()
    assert client.post('/enrollments/enroll', data={'csrf_token': token, 'offering_id': 'bad'}).status_code == 400


def test_completed_academic_history_cannot_be_deleted(app, client, login):
    token = login('admin')
    with app.app_context():
        db.session.get(Enrollment, 1).status = '已通过'
        db.session.commit()
    client.post('/students/S1/delete', data={'csrf_token': token})
    with app.app_context():
        assert db.session.get(Student, 'S1') is not None
        assert Grade.query.filter_by(enrollment_id=1).count() == 1
