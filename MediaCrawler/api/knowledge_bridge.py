"""Invalidate optional research indexes before removing crawler source data."""
from pathlib import Path
from fastapi import HTTPException

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def invalidate(path):
    database = PROJECT_ROOT / '.runtime/research/index.sqlite3'
    if not database.exists():
        return
    try:
        from community_research.knowledge import KnowledgeStore
        KnowledgeStore(PROJECT_ROOT, database).invalidate_path(path)
    except Exception as exc:
        # Fail closed: do not delete sources while leaving a live index behind.
        raise HTTPException(503, '无法同步知识库失效状态，未删除源数据。请检查 community-research-agent 安装和数据库状态。') from exc
