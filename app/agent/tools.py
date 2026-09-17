"""Typed, permission-scoped tools. No SQL or direct commit tool is exposed."""
from datetime import datetime
from sqlalchemy import func
from app.extensions import db
from app.models import Student, Grade, Enrollment, CourseOffering, Course, RewardPunishment, User
from app.agent_models import ChangeDraft, ChangeEvent, ImportBatch
from app.services.imports.profiles import plan_row, apply_plan, snapshot
from app.services.imports.workflow import require_admin, Conflict
from app.services.grade_validation import parse_score
from app.utils.audit import set_audit_user

FILTERS = {'student_id', 'name', 'offering_id', 'course_name', 'course_code',
           'academic_year', 'semester', 'class_id', 'major_id', 'status', 'below',
           'date_from', 'date_to', 'type', 'page'}


def current_actor(actor):
    user = db.session.get(User, actor.user_id, populate_existing=True)
    if not user or not user.is_active or user.role not in ('student', 'admin'):
        raise PermissionError('账号权限失效')
    return user


def _number(value, label):
    if isinstance(value, bool):
        raise ValueError(label + '必须是正整数')
    try:
        result = int(str(value))
    except ValueError:
        raise ValueError(label + '必须是正整数') from None
    if result <= 0:
        raise ValueError(label + '必须是正整数')
    return result


def query_data(actor, kind, filters):
    actor = current_actor(actor)
    if kind not in ('students', 'grades', 'courses', 'rewards', 'grade_summary'):
        raise ValueError('不支持的查询类型')
    if not isinstance(filters, dict) or set(filters) - FILTERS:
        raise ValueError('未知查询参数')
    if any(not isinstance(v, (str, int, float, type(None))) or isinstance(v, bool) for v in filters.values()):
        raise ValueError('查询条件必须为文本或数字')
    filters = {k: v for k, v in filters.items() if v not in (None, '')}
    if actor.role == 'student':
        if kind == 'grade_summary':
            raise PermissionError('学生不能查看全班统计')
        if not actor.related_id:
            raise PermissionError('账号未关联学号')
        if filters.get('student_id') and str(filters['student_id']) != actor.related_id:
            raise PermissionError('只能查询本人数据')
        if any(k in filters for k in ('name', 'class_id', 'major_id')):
            raise PermissionError('学生不能搜索其他学生')
        if kind != 'courses':
            filters['student_id'] = actor.related_id
    if kind in ('grades', 'grade_summary'):
        q = db.session.query(Student, Enrollment, Grade, CourseOffering, Course).select_from(Enrollment).join(
            Student, Enrollment.student_id == Student.student_id).join(
            CourseOffering, Enrollment.offering_id == CourseOffering.offering_id).join(
            Course, CourseOffering.course_id == Course.course_id).outerjoin(
            Grade, Grade.enrollment_id == Enrollment.enrollment_id).filter(Enrollment.status != '退课')
    elif kind == 'students':
        q = Student.query
    elif kind == 'courses':
        q = db.session.query(CourseOffering, Course).join(Course, CourseOffering.course_id == Course.course_id)
    else:
        q = db.session.query(RewardPunishment, Student).join(Student, RewardPunishment.student_id == Student.student_id)
    allowed = {
        'students': {'student_id', 'name', 'class_id', 'major_id', 'status', 'page'},
        'grades': {'student_id', 'name', 'class_id', 'major_id', 'status', 'below', 'offering_id',
                   'course_name', 'course_code', 'academic_year', 'semester', 'page'},
        'grade_summary': {'offering_id', 'academic_year', 'semester', 'page'},
        'courses': {'offering_id', 'course_name', 'course_code', 'academic_year', 'semester', 'page'},
        'rewards': {'student_id', 'name', 'type', 'date_from', 'date_to', 'page'},
    }[kind]
    if set(filters) - allowed:
        raise ValueError('该查询不支持指定条件')
    columns = {'student_id': Student.student_id, 'name': Student.name, 'class_id': Student.class_id,
        'major_id': Student.major_id, 'offering_id': CourseOffering.offering_id,
        'course_name': Course.course_name, 'course_code': Course.course_code,
        'academic_year': CourseOffering.academic_year, 'semester': CourseOffering.semester,
        'type': RewardPunishment.type}
    for key, value in filters.items():
        if key in columns:
            if key in ('class_id', 'major_id', 'offering_id'):
                value = _number(value, key)
            q = q.filter(columns[key] == value)
    if filters.get('status'):
        q = q.filter((Student.status if kind == 'students' else Enrollment.status) == filters['status'])
    if 'below' in filters:
        q = q.filter(Grade.total_score < parse_score(filters['below']))
    from datetime import date
    if filters.get('date_from'):
        q = q.filter(RewardPunishment.rp_date >= date.fromisoformat(filters['date_from']))
    if filters.get('date_to'):
        q = q.filter(RewardPunishment.rp_date <= date.fromisoformat(filters['date_to']))
    if kind == 'grade_summary':
        if 'offering_id' not in filters:
            raise ValueError('统计必须先明确开课编号')
        result = q.with_entities(func.count(Grade.total_score), func.avg(Grade.total_score),
                                 func.min(Grade.total_score), func.max(Grade.total_score)).one()
        rows = [{'已录总评人数': result[0], '平均分': str(round(result[1], 2)) if result[1] is not None else None,
                 '最低分': str(result[2]) if result[2] is not None else None,
                 '最高分': str(result[3]) if result[3] is not None else None}]
        return {'kind': kind, 'filters': filters, 'total': 1, 'page': 1, 'rows': rows,
                'definition': '仅统计已有总评且未退课的选课记录；空成绩不计，零分计入'}
    page = _number(filters.get('page', 1), 'page')
    if page > 200:
        raise ValueError('页码过大，请缩小范围')
    total = q.count()
    ordering = {'students': Student.student_id, 'grades': Enrollment.enrollment_id,
                'courses': CourseOffering.offering_id, 'rewards': RewardPunishment.record_id}[kind]
    records = q.order_by(ordering).offset((page - 1) * 50).limit(50).all()
    rows = []
    for record in records:
        if kind == 'students':
            rows.append({k: getattr(record, k) for k in ('student_id', 'name', 'major_id', 'class_id', 'status')})
        elif kind == 'courses':
            offering, course = record
            rows.append({'offering_id': offering.offering_id, 'course_name': course.course_name,
                         'course_code': course.course_code, 'teacher_id': offering.teacher_id,
                         'academic_year': offering.academic_year, 'semester': offering.semester,
                         'remaining': max(0, offering.max_students - offering.cur_students)})
        elif kind == 'grades':
            learner, enrollment, grade, offering, course = record
            rows.append({'student_id': learner.student_id, 'name': learner.name, 'offering_id': offering.offering_id,
                         'course_name': course.course_name, 'academic_year': offering.academic_year,
                         'semester': offering.semester, 'status': enrollment.status,
                         **{k: str(getattr(grade, k)) if grade and getattr(grade, k) is not None else None
                            for k in ('daily_score', 'midterm_score', 'final_score', 'total_score', 'gpa')}})
        else:
            reward, learner = record
            rows.append({'student_id': learner.student_id, 'name': learner.name, 'type': reward.type,
                         'title': reward.title, 'date': str(reward.rp_date)})
    return {'kind': kind, 'filters': filters, 'total': total, 'page': page, 'page_size': 50,
            'rows': rows, 'queried_at': datetime.utcnow().isoformat()}


def propose_change(actor, conversation, kind, candidate, options, reason):
    require_admin(current_actor(actor))
    if conversation.owner_id != actor.user_id:
        raise PermissionError('会话不属于当前用户')
    if kind not in ('students', 'grades') or not isinstance(candidate, dict):
        raise ValueError('会话修改仅支持联系方式或单个成绩分项')
    allowed = {'student_id', 'phone', 'email'} if kind == 'students' else {
        'student_id', 'offering_id', 'daily_score', 'midterm_score', 'final_score', 'makeup_score'}
    if set(candidate) - allowed:
        raise ValueError('此字段不能通过会话修改')
    changes = set(candidate) - {'student_id', 'offering_id'}
    if len(changes) != 1 or not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 500:
        raise ValueError('一次仅修改一个字段，并填写修改原因')
    plan = plan_row(kind, candidate, options, allow_update=True)
    if plan['action'] != 'update':
        raise ValueError('必须选择已有记录，且新值与旧值不同')
    draft = ChangeDraft(owner_id=actor.user_id, conversation_id=conversation.id, kind=kind,
        candidate=candidate, options=options, plan=plan, reason=reason.strip())
    db.session.add(draft)
    db.session.flush()
    return {'draft_id': draft.id, 'before': plan['before'], 'after': plan['after'],
            'reason': draft.reason, 'message': '仅创建修改草稿，尚未写入；请在页面核对并确认'}


def confirm_draft(draft_id, actor):
    require_admin(current_actor(actor))
    draft = ChangeDraft.query.filter_by(id=draft_id, owner_id=actor.user_id).with_for_update().populate_existing().first()
    if not draft:
        raise LookupError('草稿不存在')
    if draft.status == 'committed':
        return draft.receipt
    if draft.status != 'pending':
        raise Conflict('草稿已取消或失效')
    fresh = plan_row(draft.kind, draft.candidate, draft.options, lock=True, allow_update=True)
    if fresh != draft.plan:
        raise Conflict('原数据已变化，请重新提出修改并确认')
    set_audit_user()
    record = apply_plan(fresh)
    db.session.flush()
    event = ChangeEvent(actor_id=actor.user_id, source_type='conversation', draft_id=draft.id,
        entity=record.__tablename__, entity_id=str(getattr(record, list(record.__table__.primary_key.columns)[0].name)),
        student_id=fresh['student_id'], before=fresh['before'], after=snapshot(record), reason=draft.reason)
    db.session.add(event)
    db.session.flush()
    draft.status = 'committed'
    draft.receipt = {'draft_id': draft.id, 'change_event_id': event.id, 'message': '修改已提交并保存变更记录'}
    db.session.commit()
    return draft.receipt


QUERY_SCHEMA = {
    'type': 'function', 'function': {'name': 'query_data',
    'description': '查询真实学籍数据。只能使用准确条件；课程不明确先查courses。below是原始总评低于阈值，未通过用status。students只返回基本信息。',
    'parameters': {'type': 'object', 'properties': {
        'kind': {'type': 'string', 'enum': ['students', 'grades', 'courses', 'rewards', 'grade_summary']},
        'filters': {'type': 'object', 'properties': {k: {'type': 'string'} for k in FILTERS}, 'additionalProperties': False}},
        'required': ['kind', 'filters'], 'additionalProperties': False}}}
DRAFT_SCHEMA = {
    'type': 'function', 'function': {'name': 'propose_change',
    'description': '管理员提出单字段修改草稿（成绩分项或电话/邮箱），绝不直接提交。先查清学生/开课；原因由用户提供，未提供则追问。',
    'parameters': {'type': 'object', 'properties': {
        'kind': {'type': 'string', 'enum': ['students', 'grades']},
        'candidate': {'type': 'object', 'properties': {k: {'type': 'string'} for k in
            ['student_id', 'offering_id', 'phone', 'email', 'daily_score', 'midterm_score', 'final_score', 'makeup_score']},
            'additionalProperties': False},
        'reason': {'type': 'string'}}, 'required': ['kind', 'candidate', 'reason'], 'additionalProperties': False}}}
