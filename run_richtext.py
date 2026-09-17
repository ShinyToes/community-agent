"""Isolated rich-text trial, leaving the original 5001 service running."""
from community import create_app

app = create_app({'SESSION_COOKIE_NAME': 'community_richtext_session'})

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5002, debug=False, load_dotenv=False)
