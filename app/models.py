from datetime import datetime, date
from app.extensions import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash


# ============================================================
# College (学院)
# ============================================================
class College(db.Model):
    __tablename__ = 'college'
    college_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    college_code = db.Column(db.String(20), unique=True, nullable=False)
    college_name = db.Column(db.String(100), nullable=False)
    dean = db.Column(db.String(50))
    office = db.Column(db.String(100))
    phone = db.Column(db.String(20))

    majors = db.relationship('Major', backref='college', lazy='dynamic')
    courses = db.relationship('Course', backref='college', lazy='dynamic')
    teachers = db.relationship('Teacher', backref='college', lazy='dynamic')

    def __repr__(self):
        return f'<College {self.college_name}>'


# ============================================================
# Major (专业)
# ============================================================
class Major(db.Model):
    __tablename__ = 'major'
    major_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    major_code = db.Column(db.String(20), unique=True, nullable=False)
    major_name = db.Column(db.String(100), nullable=False)
    duration = db.Column(db.SmallInteger, nullable=False, default=4)
    degree_type = db.Column(db.String(20), nullable=False)
    college_id = db.Column(db.Integer, db.ForeignKey('college.college_id', onupdate='CASCADE'), nullable=False)

    classes = db.relationship('Class', backref='major', lazy='dynamic')
    students = db.relationship('Student', backref='major', lazy='dynamic')

    def __repr__(self):
        return f'<Major {self.major_name}>'


# ============================================================
# Class (班级)
# ============================================================
class Class(db.Model):
    __tablename__ = 'class'
    class_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    class_name = db.Column(db.String(100), nullable=False)
    grade = db.Column(db.Integer, nullable=False)  # YEAR type mapped to int
    counselor = db.Column(db.String(50))
    major_id = db.Column(db.Integer, db.ForeignKey('major.major_id', onupdate='CASCADE'), nullable=False)

    students = db.relationship('Student', backref='class_', lazy='dynamic')

    def __repr__(self):
        return f'<Class {self.class_name}>'


# ============================================================
# Student (学生)
# ============================================================
class Student(db.Model):
    __tablename__ = 'student'
    student_id = db.Column(db.String(20), primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    gender = db.Column(db.String(1), nullable=False)
    birth_date = db.Column(db.Date)
    id_card = db.Column(db.String(18), unique=True)
    ethnicity = db.Column(db.String(20))
    political_status = db.Column(db.String(20))
    native_place = db.Column(db.String(100))
    home_address = db.Column(db.String(200))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(100))
    enrollment_year = db.Column(db.Integer, nullable=False)
    education_length = db.Column(db.SmallInteger, nullable=False, default=4)
    education_level = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), default='在读')
    photo = db.Column(db.String(255))
    major_id = db.Column(db.Integer, db.ForeignKey('major.major_id', onupdate='CASCADE'), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('class.class_id', onupdate='CASCADE'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    major_changes = db.relationship('MajorChange', backref='student',
                                     foreign_keys='MajorChange.student_id', lazy='dynamic')
    reward_punishments = db.relationship('RewardPunishment', backref='student', lazy='dynamic')
    enrollments = db.relationship('Enrollment', backref='student', lazy='dynamic')
    physical_exams = db.relationship('PhysicalExam', backref='student', lazy='dynamic')

    def __repr__(self):
        return f'<Student {self.student_id} {self.name}>'


# ============================================================
# MajorChange (专业变更)
# ============================================================
class MajorChange(db.Model):
    __tablename__ = 'major_change'
    change_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    student_id = db.Column(db.String(20), db.ForeignKey('student.student_id', onupdate='CASCADE', ondelete='CASCADE'), nullable=False)
    old_major_id = db.Column(db.Integer, db.ForeignKey('major.major_id', onupdate='CASCADE'), nullable=False)
    new_major_id = db.Column(db.Integer, db.ForeignKey('major.major_id', onupdate='CASCADE'), nullable=False)
    change_date = db.Column(db.Date, nullable=False)
    reason = db.Column(db.Text)
    approval_status = db.Column(db.String(20), default='待审批')
    approver_id = db.Column(db.Integer)
    approval_date = db.Column(db.DateTime)
    attachment = db.Column(db.String(255))

    old_major = db.relationship('Major', foreign_keys=[old_major_id])
    new_major = db.relationship('Major', foreign_keys=[new_major_id])

    def __repr__(self):
        return f'<MajorChange {self.change_id}>'


# ============================================================
# RewardPunishment (奖惩记录)
# ============================================================
class RewardPunishment(db.Model):
    __tablename__ = 'reward_punishment'
    record_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    student_id = db.Column(db.String(20), db.ForeignKey('student.student_id', onupdate='CASCADE', ondelete='CASCADE'), nullable=False)
    type = db.Column(db.String(10), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    level = db.Column(db.String(20))
    rp_date = db.Column(db.Date, nullable=False)
    description = db.Column(db.Text)
    evidence = db.Column(db.String(255))

    def __repr__(self):
        return f'<RewardPunishment {self.record_id}>'


# ============================================================
# Teacher (教师)
# ============================================================
class Teacher(db.Model):
    __tablename__ = 'teacher'
    teacher_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(50), nullable=False)
    gender = db.Column(db.String(1))
    title = db.Column(db.String(50))
    department = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(100))
    college_id = db.Column(db.Integer, db.ForeignKey('college.college_id', onupdate='CASCADE', ondelete='SET NULL'))

    course_offerings = db.relationship('CourseOffering', backref='teacher', lazy='dynamic')

    def __repr__(self):
        return f'<Teacher {self.name}>'


# ============================================================
# Course (课程)
# ============================================================
class Course(db.Model):
    __tablename__ = 'course'
    course_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    course_code = db.Column(db.String(20), unique=True, nullable=False)
    course_name = db.Column(db.String(100), nullable=False)
    credits = db.Column(db.Numeric(3, 1), nullable=False)
    hours = db.Column(db.Integer, nullable=False)
    course_type = db.Column(db.String(20), nullable=False)
    department = db.Column(db.String(100))
    description = db.Column(db.Text)
    syllabus = db.Column(db.String(255))
    college_id = db.Column(db.Integer, db.ForeignKey('college.college_id', onupdate='CASCADE', ondelete='SET NULL'))

    offerings = db.relationship('CourseOffering', backref='course', lazy='dynamic')

    def __repr__(self):
        return f'<Course {self.course_name}>'


# ============================================================
# CourseOffering (开课信息)
# ============================================================
class CourseOffering(db.Model):
    __tablename__ = 'course_offering'
    offering_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course.course_id', onupdate='CASCADE'), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teacher.teacher_id', onupdate='CASCADE'), nullable=False)
    academic_year = db.Column(db.String(9), nullable=False)
    semester = db.Column(db.String(10), nullable=False)
    classroom = db.Column(db.String(100))
    schedule = db.Column(db.String(200))
    max_students = db.Column(db.Integer, nullable=False, default=60)
    cur_students = db.Column(db.Integer, nullable=False, default=0)
    daily_weight = db.Column(db.Numeric(3, 2), nullable=False, default=0.30)
    midterm_weight = db.Column(db.Numeric(3, 2), nullable=False, default=0.30)
    final_weight = db.Column(db.Numeric(3, 2), nullable=False, default=0.40)

    enrollments = db.relationship('Enrollment', backref='offering', lazy='dynamic')

    def __repr__(self):
        return f'<CourseOffering {self.offering_id}>'


# ============================================================
# Enrollment (选课记录)
# ============================================================
class Enrollment(db.Model):
    __tablename__ = 'enrollment'
    __table_args__ = (db.UniqueConstraint('student_id', 'offering_id', name='uk_student_offering'),)
    enrollment_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    student_id = db.Column(db.String(20), db.ForeignKey('student.student_id', onupdate='CASCADE', ondelete='CASCADE'), nullable=False)
    offering_id = db.Column(db.Integer, db.ForeignKey('course_offering.offering_id', onupdate='CASCADE'), nullable=False)
    enroll_date = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='在修')

    grade = db.relationship('Grade', backref='enrollment', uselist=False)

    def __repr__(self):
        return f'<Enrollment {self.enrollment_id}>'


# ============================================================
# Grade (成绩)
# ============================================================
class Grade(db.Model):
    __tablename__ = 'grade'
    grade_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    enrollment_id = db.Column(db.Integer, db.ForeignKey('enrollment.enrollment_id', onupdate='CASCADE', ondelete='CASCADE'), unique=True, nullable=False)
    daily_score = db.Column(db.Numeric(5, 2))
    midterm_score = db.Column(db.Numeric(5, 2))
    final_score = db.Column(db.Numeric(5, 2))
    total_score = db.Column(db.Numeric(5, 2))
    gpa = db.Column(db.Numeric(3, 2))
    makeup_score = db.Column(db.Numeric(5, 2))
    status = db.Column(db.String(20), default='正常')
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Grade {self.grade_id}>'


# ============================================================
# PhysicalExam (体检记录)
# ============================================================
class PhysicalExam(db.Model):
    __tablename__ = 'physical_exam'
    exam_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    student_id = db.Column(db.String(20), db.ForeignKey('student.student_id', onupdate='CASCADE', ondelete='CASCADE'), nullable=False)
    exam_date = db.Column(db.Date, nullable=False)
    height = db.Column(db.Numeric(5, 1))
    weight = db.Column(db.Numeric(5, 1))
    vision_left = db.Column(db.Numeric(4, 1))
    vision_right = db.Column(db.Numeric(4, 1))
    blood_type = db.Column(db.String(5))
    health_status = db.Column(db.String(50))
    hospital = db.Column(db.String(100))
    report_file = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<PhysicalExam {self.exam_id}>'


# ============================================================
# User (系统用户) — also used for Flask-Login
# ============================================================
class User(db.Model, UserMixin):
    __tablename__ = 'user'
    user_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    related_id = db.Column(db.String(20))
    last_login = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True)

    def get_id(self):
        return str(self.user_id)

    def check_password(self, pw):
        return check_password_hash(self.password, pw)

    @staticmethod
    def hash_password(pw):
        return generate_password_hash(pw)

    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def __repr__(self):
        return f'<User {self.username}>'


# ============================================================
# File (文件管理)
# ============================================================
class File(db.Model):
    __tablename__ = 'file'
    file_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    file_name = db.Column(db.String(255), nullable=False)
    file_type = db.Column(db.String(20), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    related_table = db.Column(db.String(50), nullable=False)
    related_id = db.Column(db.String(50), nullable=False)
    upload_time = db.Column(db.DateTime, default=datetime.utcnow)
    file_size = db.Column(db.BigInteger)

    def __repr__(self):
        return f'<File {self.file_name}>'


# ============================================================
# AuditLog (操作日志)
# ============================================================
class AuditLog(db.Model):
    __tablename__ = 'audit_log'
    log_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, nullable=False)
    action = db.Column(db.String(50), nullable=False)
    table_name = db.Column(db.String(50), nullable=False)
    record_id = db.Column(db.String(50))
    old_value = db.Column(db.JSON)
    new_value = db.Column(db.JSON)
    ip_address = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<AuditLog {self.log_id}>'
