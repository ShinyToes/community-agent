from io import BytesIO
from pathlib import Path

import pytest

from app.extensions import db
from app.models import User, File, MajorChange
from conftest import csrf


def test_login_csrf_and_open_redirect(client):
    assert client.post('/auth/login', data={'username': 'admin'}).status_code == 400
    token = csrf(client)
    result = client.post('/auth/login?next=https://example.org', data={
        'username': 'admin', 'password': 'testing-password', 'csrf_token': token,
    })
    assert result.status_code == 302 and result.location == '/'


def test_local_redirect(client):
    token = csrf(client)
    result = client.post('/auth/login?next=/students/', data={
        'username': 'admin', 'password': 'testing-password', 'csrf_token': token,
    })
    assert result.location == '/students/'


def test_logout_requires_post_and_csrf(client, login):
    token = login()
    assert client.get('/auth/logout').status_code == 405
    assert client.post('/auth/logout').status_code == 400
    assert client.post('/auth/logout', data={'csrf_token': token}).status_code == 302


@pytest.mark.parametrize('path', [
    '/students/S2', '/students/api/students/S2', '/files/list/student/S2',
    '/statistics/api/student-status', '/statistics/api/grade-distribution',
    '/statistics/api/scatter', '/exams/api/stats', '/rewards/api/stats-summary',
    '/rewards/api/stats-by-month',
])
def test_student_cannot_read_others_or_aggregates(client, login, path):
    login()
    assert client.get(path).status_code == 403


def test_student_list_is_scoped(client, login):
    login()
    page = client.get('/students/').get_data(as_text=True)
    assert '学生1' in page and '学生2' not in page
    assert client.get('/students/api/students/S1').status_code == 200


def test_disabled_session_revoked(app, client, login):
    login()
    with app.app_context():
        db.session.get(User, 2).is_active = False
        db.session.commit()
    assert client.get('/students/S1').status_code == 302


def test_major_change_cannot_impersonate(app, client, login):
    token = login()
    assert client.post('/major-changes/apply', data={
        'csrf_token': token, 'student_id': 'S2', 'new_major_id': '2',
    }).status_code == 403
    with app.app_context():
        assert MajorChange.query.count() == 0


def test_major_change_real_multipart_and_duplicate(app, client, login):
    token = login()
    result = client.post('/major-changes/apply', data={
        'csrf_token': token, 'student_id': 'S1', 'new_major_id': '2',
        'attachment': (BytesIO(b'evidence'), 'evidence.txt'),
    })
    assert result.status_code == 302
    client.post('/major-changes/apply', data={
        'csrf_token': token, 'student_id': 'S1', 'new_major_id': '2',
    })
    with app.app_context():
        assert MajorChange.query.count() == 1
        change = MajorChange.query.one()
        assert change.student_id == 'S1' and change.attachment.endswith('/download')
        assert File.query.count() == 1


def test_file_access_and_static_bypass(app, client, login):
    with app.app_context():
        db.session.add(File(file_id=1, file_name='secret.txt', file_type='document',
                            file_path='uploads/student/S2/secret.txt',
                            related_table='student', related_id='S2'))
        db.session.commit()
    assert client.get('/static/uploads/student/S2/secret.txt').status_code == 404
    token = login()
    assert client.get('/files/1/download').status_code == 403
    assert client.post('/files/1/delete', data={'csrf_token': token}).status_code == 403
    assert client.post('/files/upload/student/S2', data={
        'csrf_token': token, 'file': (BytesIO(b'bad'), 'bad.txt'),
    }).status_code == 403


def test_admin_upload_download_delete(app, client, login):
    token = login('admin')
    response = client.post('/files/upload/student/S1', data={
        'csrf_token': token, 'file': (BytesIO(b'hello'), 'data.csv'),
    }, headers={'X-Requested-With': 'XMLHttpRequest'})
    assert response.status_code == 200
    file_id = response.json['file']['file_id']
    downloaded = client.get(f'/files/{file_id}/download')
    assert downloaded.data == b'hello'
    assert downloaded.headers['Content-Disposition'].startswith('attachment')
    downloaded.close()
    assert client.post(f'/files/{file_id}/delete', data={'csrf_token': token}).status_code == 302
    assert not list(Path(app.config['UPLOAD_FOLDER']).iterdir())


@pytest.mark.parametrize('filename', ['script.html', 'vector.svg', 'malware.exe'])
def test_active_upload_types_rejected(app, client, login, filename):
    token = login('admin')
    result = client.post('/files/upload/student/S1', data={
        'csrf_token': token, 'file': (BytesIO(b'content'), filename),
    })
    assert result.status_code == 400
    with app.app_context():
        assert File.query.count() == 0


def test_path_traversal_record_rejected(app, client, login):
    login('admin')
    with app.app_context():
        db.session.add(File(file_id=1, file_name='x.txt', file_type='document',
                            file_path='private/../../config.py', related_table='student', related_id='S1'))
        db.session.commit()
    assert client.get('/files/1/download').status_code == 400


def test_unknown_file_target_rejected(client, login):
    token = login('admin')
    assert client.post('/files/upload/unknown/S1', data={'csrf_token': token}).status_code == 400


def test_all_post_forms_have_csrf(app):
    import re
    for path in Path(app.template_folder).rglob('*.html'):
        text = path.read_text(encoding='utf-8')
        for form in re.findall(r'<form\b.*?</form>', text, re.S | re.I):
            if re.search(r'method=["\x27]post["\x27]', form, re.I):
                assert 'csrf_token' in form, str(path)


def test_all_templates_compile(app):
    for name in app.jinja_env.list_templates():
        app.jinja_env.get_template(name)
