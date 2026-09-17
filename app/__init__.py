import os
from flask import Flask, render_template
from config import Config


def create_app(config_class=Config):
    app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), 'templates'))
    app.config.from_object(config_class)
    if isinstance(config_class, dict):
        app.config.update(config_class)
    app.config.setdefault('DOCUMENT_FOLDER', os.path.join(app.instance_path, 'documents'))
    if not app.config.get('SECRET_KEY') or not app.config.get('SQLALCHEMY_DATABASE_URI'):
        raise RuntimeError('请在 .env.agent 设置 AGENT_SECRET_KEY 和独立的 AGENT_DATABASE_URL；不使用原实验 .env。')
    from sqlalchemy.engine import make_url
    if make_url(app.config['SQLALCHEMY_DATABASE_URI']).database == 'student_management':
        raise RuntimeError('拒绝连接原实验 student_management 数据库，请使用独立数据库。')

    # Init extensions
    from app.extensions import db, login_manager, photos, csrf
    from flask_uploads import configure_uploads
    db.init_app(app)
    with app.app_context():
        if db.engine.dialect.name == 'mysql':
            from sqlalchemy import event
            @event.listens_for(db.engine, 'checkout')
            def reset_audit_actor(connection, record, proxy):
                with connection.cursor() as cursor:
                    cursor.execute('SET @current_user_id = NULL')
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = '请先登录后再访问此页面'
    configure_uploads(app, photos)
    csrf.init_app(app)
    from app.utils.security import register_security
    register_security(app)

    from sqlalchemy.exc import SQLAlchemyError
    @app.errorhandler(SQLAlchemyError)
    def database_error(error):
        db.session.rollback()
        app.logger.error('Database operation failed (%s)', type(error).__name__)
        return '数据操作失败，请检查输入或联系管理员。', 500

    # Register user_loader
    from . import auth as _auth  # noqa: F401
    from . import agent_models as _agent_models  # noqa: F401

    # Register blueprints
    from app.blueprints.auth_bp import auth_bp
    from app.blueprints.college_bp import college_bp
    from app.blueprints.major_bp import major_bp
    from app.blueprints.class_bp import class_bp
    from app.blueprints.student_bp import student_bp
    from app.blueprints.major_change_bp import major_change_bp
    from app.blueprints.reward_punish_bp import reward_punish_bp
    from app.blueprints.course_bp import course_bp
    from app.blueprints.enrollment_bp import enrollment_bp
    from app.blueprints.grade_bp import grade_bp
    from app.blueprints.physical_exam_bp import physical_exam_bp
    from app.blueprints.statistics_bp import statistics_bp
    from app.blueprints.file_bp import file_bp
    from app.blueprints.audit_bp import audit_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(college_bp, url_prefix='/colleges')
    app.register_blueprint(major_bp, url_prefix='/majors')
    app.register_blueprint(class_bp, url_prefix='/classes')
    app.register_blueprint(student_bp, url_prefix='/students')
    app.register_blueprint(major_change_bp, url_prefix='/major-changes')
    app.register_blueprint(reward_punish_bp, url_prefix='/rewards')
    app.register_blueprint(course_bp, url_prefix='/courses')
    app.register_blueprint(enrollment_bp, url_prefix='/enrollments')
    app.register_blueprint(grade_bp, url_prefix='/grades')
    app.register_blueprint(physical_exam_bp, url_prefix='/exams')
    app.register_blueprint(statistics_bp, url_prefix='/statistics')
    app.register_blueprint(file_bp, url_prefix='/files')
    app.register_blueprint(audit_bp, url_prefix='/audit')
    from app.blueprints.agent_bp import agent_bp
    app.register_blueprint(agent_bp)

    # Root route
    @app.route('/')
    def index():
        from flask_login import current_user
        from app.models import Student, Course, Teacher, MajorChange, Enrollment, Class
        from app.services.grade_service import get_student_gpa, get_completed_credits

        if current_user.is_authenticated:
            role = current_user.role
            if role == 'student':
                sid = current_user.related_id
                stats = {
                    'title': '我的概览',
                    'card1': {'label': '我的GPA', 'value': f"{get_student_gpa(sid) or 0:.2f}"},
                    'card2': {'label': '已修学分', 'value': f"{get_completed_credits(sid) or 0:.1f}"},
                    'card3': {'label': '在修课程', 'value': Enrollment.query.filter_by(student_id=sid, status='在修').count()},
                    'card4': {'label': '已通过课程', 'value': Enrollment.query.filter_by(student_id=sid, status='已通过').count()},
                }
            else:
                # 管理员
                stats = {
                    'title': '系统概览',
                    'card1': {'label': '在校学生', 'value': Student.query.filter(Student.status.in_(['在读', '休学'])).count()},
                    'card2': {'label': '开设课程', 'value': Course.query.count()},
                    'card3': {'label': '教师人数', 'value': Teacher.query.count()},
                    'card4': {'label': '待审批变更', 'value': MajorChange.query.filter_by(approval_status='待审批').count()},
                }
        else:
            stats = {}
        return render_template('dashboard/index.html', stats=stats)

    # Context processor for sidebar
    @app.context_processor
    def inject_globals():
        return {}

    return app
