"""Community configuration never imports or loads the legacy app/config."""
import os
from datetime import timedelta
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]


def settings():
    values = {**dotenv_values(ROOT / '.env.community'), **os.environ}
    return {
        'SECRET_KEY': values.get('COMMUNITY_SECRET_KEY'),
        'SQLALCHEMY_DATABASE_URI': values.get('COMMUNITY_DATABASE_URL'),
        'SQLALCHEMY_TRACK_MODIFICATIONS': False,
        'SESSION_COOKIE_NAME': 'community_session',
        'SESSION_COOKIE_HTTPONLY': True,
        'SESSION_COOKIE_SAMESITE': 'Lax',
        'SESSION_COOKIE_SECURE': values.get('COMMUNITY_HTTPS') == '1',
        'PERMANENT_SESSION_LIFETIME': timedelta(hours=12),
        'MAX_CONTENT_LENGTH': 256 * 1024,
        'POST_RATE_LIMIT': 60,
        'IMAGE_RATE_LIMIT': 30,
        'LOGIN_RATE_LIMIT': 20,
        'REGISTER_RATE_LIMIT': 10,
        'AUTH_RATE_WINDOW': 600,
    }


def validate_database(uri, *, testing=False):
    try:
        url = make_url(uri)
    except Exception:
        raise RuntimeError('请设置有效的 COMMUNITY_DATABASE_URL。') from None
    if testing and url.drivername == 'sqlite':
        return url
    if url.drivername != 'mysql+pymysql' or url.database != 'community_agent':
        raise RuntimeError('社区只允许 mysql+pymysql 连接 community_agent；拒绝旧库或其他库。')
    return url
