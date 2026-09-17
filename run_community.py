"""Community entry point. The legacy run.py remains independent."""
from community import create_app

app = create_app()

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5001, debug=False, load_dotenv=False)
