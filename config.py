import os
from pathlib import Path
from dotenv import load_dotenv

# A copied lab .env must never silently reconnect this project to the lab DB.
load_dotenv(Path(__file__).with_name('.env.agent'))


class Config:
    SECRET_KEY = os.getenv('AGENT_SECRET_KEY')
    SQLALCHEMY_DATABASE_URI = os.getenv('AGENT_DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True, 'pool_recycle': 3600,
        'isolation_level': 'READ COMMITTED',
    }
    UPLOADED_PHOTOS_DEST = str(Path(__file__).parent / 'instance' / 'uploads')
    UPLOAD_FOLDER = UPLOADED_PHOTOS_DEST
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = os.getenv('AGENT_HTTPS', '0') == '1'
    DOCUMENT_FOLDER = str(Path(__file__).parent / 'instance' / 'documents')
    LLM_API_KEY = os.getenv('DEEPSEEK_API_KEY')
    LLM_MODEL = os.getenv('DEEPSEEK_MODEL', 'deepseek-chat')
    LLM_BASE_URL = os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com')
    OCR_EXECUTABLE = os.getenv('OCR_EXECUTABLE')
    OCR_BACKEND = os.getenv('OCR_BACKEND', 'docker')
    OCR_LANGUAGES = os.getenv('OCR_LANGUAGES', 'chi_sim+eng')
    CURRENT_ACADEMIC_YEAR = os.getenv('CURRENT_ACADEMIC_YEAR')
    CURRENT_SEMESTER = os.getenv('CURRENT_SEMESTER')
