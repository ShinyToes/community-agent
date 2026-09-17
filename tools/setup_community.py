"""Create local community secrets once; no database access or secret output."""
from pathlib import Path
import secrets


def main():
    root = Path(__file__).resolve().parents[1]
    target = root / '.env.community'
    password = secrets.token_hex(24)
    try:
        with target.open('x', encoding='utf-8') as output:
            output.write(
                f'COMMUNITY_SECRET_KEY={secrets.token_hex(32)}\n'
                f'COMMUNITY_DATABASE_URL=mysql+pymysql://community_user:{password}'
                '@127.0.0.1:13307/community_agent?charset=utf8mb4\n'
                'COMMUNITY_HTTPS=0\n'
                f'COMMUNITY_MYSQL_ROOT_PASSWORD={secrets.token_hex(32)}\n'
                f'COMMUNITY_MYSQL_PASSWORD={password}\n'
            )
    except FileExistsError:
        print('.env.community already exists; left unchanged.')
    else:
        print('Created .env.community with independent local credentials.')


if __name__ == '__main__':
    main()
