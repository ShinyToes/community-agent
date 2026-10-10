"""Durable, cookie-free task metadata. Each task owns a separate output directory."""
import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

DATA_DIR = Path(__file__).resolve().parents[1] / 'data'
ACTIVE = {'starting', 'running', 'stopping'}
FILE_TYPES = {'.json', '.jsonl', '.csv', '.xlsx', '.xls'}


def now():
    return datetime.now(timezone.utc).isoformat()


def task_dir(ident):
    if not re.fullmatch(r'[a-f0-9]{32}', ident):
        raise HTTPException(404, '任务不存在')
    root = DATA_DIR.resolve() / 'tasks'
    path = root / ident
    if root.resolve().parent != DATA_DIR.resolve() or path.resolve().parent != root.resolve() or path.is_symlink():
        raise HTTPException(403, '非法任务路径')
    return path


def save(row):
    path = task_dir(row['id'])
    path.mkdir(parents=True, exist_ok=True)
    temporary = path / 'task.tmp'
    temporary.write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path / 'task.json')
    return row


def create(config):
    # Explicit whitelist: never persist cookies or the full CLI command.
    fields = ('platform', 'crawler_type', 'keywords', 'specified_ids', 'creator_ids',
              'save_option', 'enable_comments', 'enable_sub_comments', 'comment_order', 'start_page',
              'max_notes_count', 'max_comments_count')
    raw = config.model_dump(mode='json')
    row = {key: raw.get(key) for key in fields}
    row.update(id=uuid.uuid4().hex, created_at=now(), finished_at=None,
               status='starting', exit_code=None, pid=None)
    save(row)
    (task_dir(row['id']) / 'output').mkdir()
    return row


def load(ident):
    path = task_dir(ident) / 'task.json'
    if not path.is_file() or path.is_symlink():
        raise HTTPException(404, '任务不存在')
    return json.loads(path.read_text(encoding='utf-8'))


def update(ident, **changes):
    row = load(ident)
    row.update(changes)
    return save(row)


def list_tasks():
    root = DATA_DIR / 'tasks'
    rows = []
    if root.exists():
        for path in root.iterdir():
            try:
                rows.append(load(path.name))
            except (HTTPException, ValueError, OSError):
                continue
    return sorted(rows, key=lambda row: row['created_at'], reverse=True)


def process_alive(pid):
    if not pid:
        return False
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        handle = kernel.OpenProcess(0x1000, False, int(pid))
        if not handle:
            return ctypes.get_last_error() == 5  # Access denied: conservatively treat as alive.
        try:
            code = ctypes.c_ulong()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def reconcile():
    for row in list_tasks():
        if row['status'] in ACTIVE and not process_alive(row.get('pid')):
            update(row['id'], status='interrupted', finished_at=now())


def ensure_finished(row):
    if row['status'] in ACTIVE or process_alive(row.get('pid')):
        raise HTTPException(409, '任务仍在运行，请先停止采集再操作。')


def delete(ident):
    row = load(ident)
    ensure_finished(row)
    from .knowledge_bridge import invalidate
    invalidate(task_dir(ident))
    # Never accept an arbitrary filesystem path; only this task's validated UUID directory.
    shutil.rmtree(task_dir(ident))


def output_files(ident):
    root = task_dir(ident) / 'output'
    if not root.exists():
        return []
    files = []
    for path in root.rglob('*'):
        if path.is_file() and path.suffix.lower() in FILE_TYPES:
            if not path.is_symlink() and path.resolve().is_relative_to(root.resolve()) and root.resolve().is_relative_to(task_dir(ident).resolve()):
                files.append(path)
    return sorted(files)
