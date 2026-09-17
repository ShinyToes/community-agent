"""Community CLI without Flask's implicit loading of the legacy .env file."""
from flask.cli import FlaskGroup

from . import create_app

cli = FlaskGroup(create_app=create_app, load_dotenv=False)

if __name__ == '__main__':
    cli()
