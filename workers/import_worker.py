from pathlib import Path
import sys
import argparse
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from app.extensions import db
from app.services.imports.workflow import run_one

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    app = create_app()
    while True:
        with app.app_context():
            try:
                worked = run_one()
            except Exception:
                db.session.rollback()
                app.logger.exception('Import worker failed')
                worked = False
        if args.once:
            break
        if not worked:
            time.sleep(2)
