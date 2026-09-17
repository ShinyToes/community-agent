"""Whitelisted business profiles; model output never controls table/column names."""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json

from app.extensions import db
from app.models import (Student, Major, Class, Course, CourseOffering, Teacher,
                        Enrollment, Grade, RewardPunishment)
from app.services.grade_validation import parse_score, validate_weights, weighted_total
from app.services.grade_writer import write_grade, GRADE_FIELDS, score_gpa
from app.utils.validation import validate_student

ALIASES = {
    '学号': 'student_id', '学生编号': 'student_id', '姓名': 'name', '学生姓名': 'name',
    '性别': 'gender', '专业': 'major_name', '专业编号': 'major_id',
    '班级': 'class_name', '班级编号': 'class_id', '入学年': 'enrollment_year',
    '入学年份': 'enrollment_year', '学制': 'education_length', '培养层次': 'education_level',
    '学历': 'education_level', '电话': 'phone', '邮箱': 'email', '出生日期': 'birth_date',
    '平时': 'daily_score', '平时成绩': 'daily_score', '期中': 'midterm_score',
    '期中成绩': 'midterm_score', '期末': 'final_score', '期末成绩': 'final_score',
    '补考成绩': 'makeup_score', '总评': 'total_score', '总评成绩': 'total_score', '绩点': 'gpa',
    '课程代码': 'course_code', '课程名称': 'course_name', '课程': 'course_name',
    '学分': 'credits', '学时': 'hours', '课程性质': 'course_type',
    '开课编号': 'offering_id', '教师编号': 'teacher_id', '教师': 'teacher_name',
    '学年': 'academic_year', '学期': 'semester', '容量': 'max_students',
    '上课时间': 'schedule', '教室': 'classroom',
    '类型': 'type', '标题': 'title', '级别': 'level', '日期': 'rp_date', '说明': 'description',
}
FIELDS = {
    'students': {'student_id', 'name', 'gender', 'major_id', 'major_name', 'class_id', 'class_name',
                 'enrollment_year', 'education_length', 'education_level', 'phone', 'email', 'birth_date'},
    'grades': {'student_id', 'name', 'offering_id', *GRADE_FIELDS, 'total_score', 'gpa'},
    'courses': {'course_code', 'course_name', 'credits', 'hours', 'course_type'},
    'offerings': {'offering_id', 'course_code', 'course_name', 'teacher_id', 'teacher_name',
                  'academic_year', 'semester', 'max_students', 'schedule', 'classroom'},
    'rewards': {'student_id', 'name', 'type', 'title', 'level', 'rp_date', 'description'},
}
MODELS = {'students': Student, 'grades': Grade, 'courses': Course,
          'offerings': CourseOffering, 'rewards': RewardPunishment}


def serial(value):
    if isinstance(value, (Decimal, date, datetime)):
        return str(value)
    return value


def snapshot(record):
    if record is None:
        return {}
    return {column.name: serial(getattr(record, column.name)) for column in record.__table__.columns}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def required(data, field):
    value = data.get(field)
    if value is None or not str(value).strip():
        raise ValueError(f'缺少字段：{field}')
    return str(value).strip()


def integer(data, field, minimum=1, maximum=100000):
    raw = required(data, field)
    try:
        number = int(raw)
    except (ValueError, TypeError):
        raise ValueError(f'{field} 必须是整数') from None
    if not minimum <= number <= maximum:
        raise ValueError(f'{field} 超出允许范围')
    return number


def unique(query, label):
    found = query.limit(2).all()
    if len(found) != 1:
        raise ValueError(f'{label}不存在或不唯一，请提供明确编号')
    return found[0]


def student(data, lock=False):
    sid = required(data, 'student_id')
    query = Student.query.filter_by(student_id=sid)
    record = (query.with_for_update() if lock else query).first()
    if not record:
        raise ValueError(f'学生 {sid} 不存在')
    if data.get('name') and str(data['name']).strip() != record.name:
        raise ValueError('姓名与学号不匹配')
    return record


def plan_row(kind, candidate, options=None, *, lock=False, allow_update=False):
    if kind not in FIELDS:
        raise ValueError('不支持的业务类型')
    if not isinstance(candidate, dict) or set(candidate) - FIELDS[kind]:
        raise ValueError('存在不支持的字段')
    if any(not isinstance(v, (str, int, float, type(None))) or isinstance(v, bool) for v in candidate.values()):
        raise ValueError('字段必须为文本或数字，不能嵌套对象')
    # Blank cells are never a request to erase existing values.
    data = {k: str(v).strip() for k, v in candidate.items() if v is not None and str(v).strip()}
    options = options or {}
    old, deps, entity_id, sid = None, {}, None, None
    def locked(query):
        return query.with_for_update().populate_existing() if lock else query
    if kind == 'grades':
        oid = integer({'offering_id': data.get('offering_id', options.get('offering_id'))}, 'offering_id')
        offering = locked(CourseOffering.query.filter_by(offering_id=oid)).first()
        if not offering:
            raise ValueError('开课不存在')
        sid = required(data, 'student_id')
        enrollment = locked(Enrollment.query.filter_by(student_id=sid, offering_id=oid)).first()
        learner = student(data)
        if not enrollment or enrollment.status == '退课':
            raise ValueError('没有有效选课记录，不能直接导入成绩')
        old = locked(Grade.query.filter_by(enrollment_id=enrollment.enrollment_id)).first()
        values = {key: serial(parse_score(data[key])) for key in GRADE_FIELDS if key in data}
        if not values:
            raise ValueError('必须提供成绩分项，不能仅导入总评')
        scores = [values.get(key, getattr(old, key, None)) for key in GRADE_FIELDS[:3]]
        total = weighted_total(scores, (offering.daily_weight, offering.midterm_weight, offering.final_weight))
        if total is None:
            raise ValueError('缺少正权重成绩分项')
        if 'total_score' in data and parse_score(data['total_score']) != total:
            raise ValueError('原文总评与系统计算不一致')
        if 'gpa' in data:
            try:
                valid_gpa = Decimal(data['gpa']) == score_gpa(total)
            except InvalidOperation:
                valid_gpa = False
            if not valid_gpa:
                raise ValueError('原文绩点与系统计算不一致')
        deps = {'offering': snapshot(offering), 'enrollment': snapshot(enrollment), 'student': snapshot(learner)}
        entity_id = str(enrollment.enrollment_id)
        computed = {'total_score': str(total), 'gpa': str(score_gpa(total))}
    elif kind == 'students':
        sid = required(data, 'student_id')
        if len(sid) > 20:
            raise ValueError('学号过长')
        old = locked(Student.query.filter_by(student_id=sid)).first()
        values = {k: v for k, v in data.items() if k not in {'major_name', 'class_name'}}
        if 'major_name' in data and 'major_id' not in data:
            values['major_id'] = unique(Major.query.filter_by(major_name=data['major_name']), '专业').major_id
        if 'class_name' in data and 'class_id' not in data:
            q = Class.query.filter_by(class_name=data['class_name'])
            mid = values.get('major_id', getattr(old, 'major_id', None))
            if mid:
                q = q.filter_by(major_id=int(mid))
            values['class_id'] = unique(q, '班级').class_id
        merged = snapshot(old) | values
        for key in ('student_id', 'name', 'gender', 'education_level'):
            required(merged, key)
        for key in ('major_id', 'class_id', 'education_length', 'enrollment_year'):
            merged[key] = integer(merged, key)
            if key in values or not old:
                values[key] = merged[key]
        if old and (merged['major_id'] != old.major_id or merged['class_id'] != old.class_id):
            raise ValueError('已有学生的专业/班级变更须走专门流程')
        transient = Student(**{k: v for k, v in merged.items() if k in Student.__table__.columns.keys()
                               and k not in ('created_at', 'updated_at')})
        transient.status = getattr(old, 'status', '在读')
        validate_student(transient)
        if 'birth_date' in values:
            values['birth_date'] = str(transient.birth_date)
        deps = {'class': snapshot(locked(Class.query.filter_by(class_id=merged['class_id'])).first())}
        entity_id = sid
        computed = {}
    elif kind == 'courses':
        code = required(data, 'course_code')
        old = locked(Course.query.filter_by(course_code=code)).first()
        values = dict(data)
        merged = snapshot(old) | values
        for key in ('course_code', 'course_name', 'course_type'):
            required(merged, key)
        merged['hours'] = integer(merged, 'hours', maximum=2000)
        try:
            credits = Decimal(str(merged.get('credits', '')))
        except InvalidOperation:
            raise ValueError('学分必须是数字') from None
        if not credits.is_finite() or not 0 < credits < 100 or credits.as_tuple().exponent < -1:
            raise ValueError('学分应在 0–100 之间，最多一位小数')
        values.update(hours=merged['hours'], credits=str(credits))
        if old and CourseOffering.query.filter_by(course_id=old.course_id).first():
            if any(str(values.get(k, getattr(old, k))) != str(getattr(old, k)) for k in ('credits', 'hours', 'course_type')):
                raise ValueError('已开课课程的学分/学时/性质须在业务页面处理')
        entity_id = code
        computed = {}
    elif kind == 'offerings':
        oid = data.get('offering_id')
        old = locked(CourseOffering.query.filter_by(offering_id=integer(data, 'offering_id'))).first() if oid else None
        if oid and not old:
            raise ValueError('指定的开课编号不存在；新增时不填编号')
        course_q = Course.query.filter_by(course_code=data['course_code']) if data.get('course_code') else Course.query.filter_by(course_name=required(data, 'course_name'))
        course = unique(locked(course_q), '课程')
        teacher_q = Teacher.query.filter_by(teacher_id=integer(data, 'teacher_id')) if data.get('teacher_id') else Teacher.query.filter_by(name=required(data, 'teacher_name'))
        teacher = unique(locked(teacher_q), '教师')
        year, semester = required(data, 'academic_year'), required(data, 'semester')
        import re
        if not re.fullmatch(r'\d{4}-\d{4}', year) or int(year[5:]) != int(year[:4]) + 1:
            raise ValueError('学年格式应为 2026-2027')
        if semester not in ('第一学期', '第二学期'):
            raise ValueError('学期应为第一学期或第二学期')
        values = {'course_id': course.course_id, 'teacher_id': teacher.teacher_id,
                  'academic_year': year, 'semester': semester,
                  'max_students': integer(data, 'max_students', maximum=10000)}
        for key in ('schedule', 'classroom'):
            if key in data:
                values[key] = data[key]
        if old:
            if any(getattr(old, k) != values[k] for k in ('course_id', 'teacher_id', 'academic_year', 'semester')):
                raise ValueError('不允许通过导入改变已有开课归属')
            if values['max_students'] < old.cur_students:
                raise ValueError('容量不能低于已选人数')
        else:
            existing = CourseOffering.query.filter_by(course_id=course.course_id, teacher_id=teacher.teacher_id,
                academic_year=year, semester=semester).first()
            if existing:
                raise ValueError('存在相似开课，请显式指定已有开课编号，或在开课页面新增')
        deps = {'course': snapshot(course), 'teacher': snapshot(teacher)}
        entity_id = str(old.offering_id) if old else f'{course.course_id}:{teacher.teacher_id}:{year}:{semester}'
        computed = {}
    else:
        learner = student(data, lock=lock)
        sid = learner.student_id
        kind_value = required(data, 'type')
        if kind_value not in ('奖励', '惩罚'):
            raise ValueError('奖惩类型只能为奖励或惩罚')
        rp_date = date.fromisoformat(required(data, 'rp_date'))
        title = required(data, 'title')
        existing = RewardPunishment.query.filter_by(student_id=sid, type=kind_value, title=title, rp_date=rp_date).first()
        if existing:
            raise ValueError('存在疑似重复奖惩，请在业务页面人工核对，不自动覆盖')
        values = {k: v for k, v in data.items() if k != 'name'}
        values.update(student_id=sid, type=kind_value, title=title, rp_date=str(rp_date))
        deps = {'student': snapshot(learner)}
        entity_id = f'{sid}:{kind_value}:{rp_date}:{title}'
        computed = {}
    before = snapshot(old)
    # Preflight column sizes instead of relying on database truncation/errors.
    for key, value in values.items():
        column = MODELS[kind].__table__.columns.get(key)
        length = getattr(column.type, 'length', None) if column is not None else None
        if length and len(str(value)) > length:
            raise ValueError(f'{key} 超出字段长度')
    def equivalent(key, value):
        original = before.get(key)
        if original is None or value is None:
            return original is value
        column = MODELS[kind].__table__.columns.get(key)
        if column is not None and isinstance(column.type, (db.Numeric, db.Integer, db.SmallInteger)):
            return Decimal(str(original)) == Decimal(str(value))
        return str(original) == str(value)
    changed = {k: v for k, v in values.items() if not equivalent(k, v)}
    action = 'insert' if old is None else ('update' if changed else 'unchanged')
    return {'kind': kind, 'key': entity_id, 'id': serial(getattr(old, list(old.__table__.primary_key.columns)[0].name)) if old else None,
            'student_id': sid, 'action': action, 'values': values, 'before': before,
            'after': before | values | computed, 'baseline': digest({'before': before, 'deps': deps})}


def apply_plan(plan):
    kind, values = plan['kind'], dict(plan['values'])
    if plan['action'] == 'unchanged':
        return db.session.get(MODELS[kind], plan['id'])
    if kind == 'grades':
        enrollment = db.session.get(Enrollment, int(plan['key']))
        return write_grade(enrollment, enrollment.offering, values)
    for key in ('birth_date', 'rp_date'):
        if values.get(key):
            values[key] = date.fromisoformat(values[key])
    record = db.session.get(MODELS[kind], plan['id']) if plan['id'] is not None else MODELS[kind]()
    for key, value in values.items():
        setattr(record, key, value)
    db.session.add(record)
    return record
