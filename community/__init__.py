import uuid
import secrets

from flask import Flask, g, jsonify, render_template, request
from flask_wtf.csrf import CSRFError, generate_csrf
from sqlalchemy import event, text
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import HTTPException

from .config import ROOT, settings, validate_database
from .extensions import csrf, db, login_manager


def create_app(overrides=None):
    app = Flask(__name__, instance_path=str(ROOT / 'instance' / 'community'))
    app.config.from_mapping(settings())
    if overrides:
        app.config.update(overrides)
    if not isinstance(app.secret_key, str) or len(app.secret_key) < 32:
        raise RuntimeError('COMMUNITY_SECRET_KEY 至少需要 32 个字符，请运行 tools/setup_community.py。')
    url = validate_database(app.config.get('SQLALCHEMY_DATABASE_URI'),
                            testing=app.testing)
    if url.drivername.startswith('mysql'):
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            'pool_pre_ping': True, 'pool_recycle': 3600,
            'isolation_level': 'READ COMMITTED',
            'connect_args': {'connect_timeout': 5, 'read_timeout': 10, 'write_timeout': 10},
        }

    @app.before_request
    def request_identity():
        g.request_id = uuid.uuid4().hex
        g.style_nonce = secrets.token_urlsafe(24)
        if request.path == '/images' and request.method == 'POST':
            request.max_content_length = 6 * 1024 * 1024

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    from .models import User

    @login_manager.user_loader
    def load_user(user_id):
        try:
            user = db.session.get(User, int(user_id))
        except (ValueError, TypeError):
            return None
        return user if user and user.active else None

    @login_manager.unauthorized_handler
    def unauthorized():
        from flask import abort
        abort(401)

    if url.drivername == 'sqlite':
        with app.app_context():
            @event.listens_for(db.engine, 'connect')
            def sqlite_foreign_keys(connection, _):
                connection.execute('PRAGMA foreign_keys=ON')

    from .auth import bp
    from .security import require_admin
    app.register_blueprint(bp)
    from .posts import bp as posts_bp, listing
    app.register_blueprint(posts_bp)
    from .images import bp as images_bp
    app.register_blueprint(images_bp)

    @app.get('/')
    def index():
        posts, cursor = listing()
        return render_template('index.html', posts=posts, next_cursor=cursor)

    @app.get('/auth/csrf')
    def csrf_token():
        return jsonify(csrf_token=generate_csrf())

    @app.get('/admin')
    @require_admin
    def admin():
        return render_template('admin.html')

    @app.get('/health/live')
    def live():
        return jsonify(status='ok', service='community-agent')

    @app.get('/health/ready')
    def ready():
        from alembic.script import ScriptDirectory
        from .cli import migration_config
        expected = ScriptDirectory.from_config(migration_config()).get_current_head()
        current = db.session.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
        if current != expected:
            return jsonify(status='unavailable', request_id=g.request_id), 503
        return jsonify(status='ok', database='community_agent', migration=current)

    def error_response(status, message):
        if request.is_json or request.accept_mimetypes.best == 'application/json' or request.path.startswith('/health/'):
            response = jsonify(error=message, request_id=g.request_id)
            response.status_code = status
        else:
            response = app.make_response((render_template('error.html', status=status, message=message), status))
        if status == 429:
            response.headers['Retry-After'] = str(app.config['AUTH_RATE_WINDOW'])
        return response

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        return error_response(400, '安全令牌缺失或过期，请刷新页面后重试。')

    @app.errorhandler(HTTPException)
    def http_error(error):
        defaults = {400: '请求参数无效。', 401: '请先登录。', 403: '没有权限。',
                    404: '内容不存在或不可见。', 405: '不支持此请求方法。',
                    409: '操作冲突，请重试。', 413: '请求内容过大。', 429: '操作过于频繁，请稍后重试。'}
        # Only application-defined messages are displayed; framework text stays generic.
        message = error.description if error.description != type(error).description else defaults.get(error.code, '请求失败。')
        return error_response(error.code, message)

    @app.errorhandler(SQLAlchemyError)
    def database_error(error):
        db.session.rollback()
        app.logger.error('request_id=%s database_error=%s', g.request_id, type(error).__name__)
        # Do not render a template that loads current_user against the failed DB.
        return jsonify(error='数据服务暂时不可用，请稍后重试。', request_id=g.request_id), 503

    @app.errorhandler(500)
    def internal_error(error):
        return error_response(500, '服务暂时不可用，请稍后重试。')

    @app.after_request
    def security_headers(response):
        response.headers['X-Request-ID'] = g.request_id
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = (
            f"default-src 'self'; script-src 'self'; style-src 'self' 'nonce-{g.style_nonce}'; "
            "img-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        if response.mimetype == 'text/html' and not response.direct_passthrough:
            rules = ''.join(sorted(getattr(g, 'rich_color_rules', set())))
            style = f'<style id="rich-color-styles" nonce="{g.style_nonce}">{rules}</style>'
            response.set_data(response.get_data(as_text=True).replace('</head>', style + '</head>', 1))
        if request.endpoint != 'static':
            response.headers['Cache-Control'] = 'no-store'
        return response

    from .cli import register_commands
    register_commands(app)
    return app
