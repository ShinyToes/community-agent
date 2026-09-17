from datetime import date
from decimal import Decimal
import re
import os

import pytest
from sqlalchemy import event

from app import create_app
from app.extensions import db
from app.models import (College, Major, Class, Student, User, Teacher, Course,
                        CourseOffering, Enrollment, Grade)


@pytest.fixture
def app(tmp_path):
    application = create_app({
        'TESTING': True, 'SECRET_KEY': 'isolated-test-key',
        'SQLALCHEMY_DATABASE_URI': os.getenv('AGENT_TEST_DATABASE_URL', 'sqlite://'),
        'SQLALCHEMY_ENGINE_OPTIONS': {'isolation_level': 'READ COMMITTED'} if os.getenv('AGENT_TEST_DATABASE_URL') else {},
        'UPLOAD_FOLDER': str(tmp_path / 'uploads'),
        'UPLOADED_PHOTOS_DEST': str(tmp_path / 'uploads'),
        'MAX_CONTENT_LENGTH': 16 * 1024 * 1024,
    })
    with application.app_context():
        if db.engine.dialect.name == 'sqlite':
            @event.listens_for(db.engine, 'connect')
            def foreign_keys(connection, _):
                connection.execute('PRAGMA foreign_keys=ON')
        else:
            for table in reversed(db.metadata.sorted_tables):
                db.session.execute(table.delete())
            db.session.commit()
        db.create_all()
        db.session.add(College(college_id=1, college_code='C', college_name='学院'))
        db.session.flush()
        for i in (1, 2):
            db.session.add(Major(major_id=i, major_code=f'M{i}', major_name=f'专业{i}',
                                 degree_type='学士', college_id=1))
        db.session.flush()
        for i in (1, 2):
            db.session.add(Class(class_id=i, class_name=f'班级{i}', grade=2026, major_id=i))
        db.session.flush()
        for i in (1, 2):
            db.session.add(Student(student_id=f'S{i}', name=f'学生{i}', gender='男',
                                   enrollment_year=2026, education_level='本科',
                                   major_id=1, class_id=1, status='在读'))
        password = User.hash_password('testing-password')
        db.session.add_all([
            User(user_id=1, username='admin', password=password, role='admin'),
            User(user_id=2, username='student1', password=password, role='student', related_id='S1'),
            User(user_id=3, username='student2', password=password, role='student', related_id='S2'),
            User(user_id=4, username='unsupported', password=password, role='teacher'),
        ])
        db.session.add(Teacher(teacher_id=1, name='教师', college_id=1))
        db.session.add(Course(course_id=1, course_code='CS1', course_name='数据库',
                              credits=3, hours=48, course_type='必修'))
        db.session.flush()
        db.session.add(CourseOffering(offering_id=1, course_id=1, teacher_id=1,
                                      academic_year='2026-2027', semester='第一学期',
                                      max_students=2, cur_students=0 if db.engine.dialect.name == 'mysql' else 2,
                                      daily_weight=Decimal('.3'), midterm_weight=Decimal('.3'),
                                      final_weight=Decimal('.4')))
        db.session.flush()
        for i in (1, 2):
            db.session.add(Enrollment(enrollment_id=i, student_id=f'S{i}', offering_id=1))
        db.session.flush()
        for i in (1, 2):
            db.session.add(Grade(enrollment_id=i, daily_score=50, midterm_score=50,
                                final_score=50, total_score=50, gpa=0))
        db.session.commit()
    yield application
    with application.app_context():
        db.session.remove()
        if db.engine.dialect.name == 'sqlite':
            db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def csrf(client):
    response = client.get('/auth/login')
    return re.search(r'name="csrf_token" value="([^"]+)"', response.get_data(as_text=True)).group(1)


@pytest.fixture
def login(client):
    def perform(username='student1'):
        token = csrf(client)
        result = client.post('/auth/login', data={
            'username': username, 'password': 'testing-password', 'csrf_token': token,
        })
        assert result.status_code == 302
        return token
    return perform
