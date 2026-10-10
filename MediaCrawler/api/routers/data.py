# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/api/routers/data.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#
# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。

import os
import json
from pathlib import Path
from typing import Optional
import tempfile
import zipfile
from starlette.background import BackgroundTask
from .. import task_store

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(prefix="/data", tags=["data"])

# Data directory
DATA_DIR = Path(__file__).parent.parent.parent / "data"


def safe_file(file_path):
    root = DATA_DIR.resolve()
    path = (root / file_path).resolve()
    if not path.is_relative_to(root) or path == root:
        raise HTTPException(403, 'Access denied')
    if path.name in ('task.json', 'task.tmp') or path.suffix.lower() not in task_store.FILE_TYPES:
        raise HTTPException(403, 'Not a data file')
    if not path.is_file():
        raise HTTPException(404, 'File not found')
    return path


def get_file_info(file_path: Path) -> dict:
    """Get file information"""
    stat = file_path.stat()
    record_count = None

    # Try to get record count
    try:
        if file_path.suffix == ".json":
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    record_count = len(data)
        elif file_path.suffix == '.jsonl':
            with file_path.open(encoding='utf-8') as f:
                record_count = sum(1 for line in f if line.strip())
        elif file_path.suffix == ".csv":
            with open(file_path, "r", encoding="utf-8") as f:
                record_count = sum(1 for _ in f) - 1  # Subtract header row
    except Exception:
        pass

    return {
        "name": file_path.name,
        "path": str(file_path.relative_to(DATA_DIR)),
        "size": stat.st_size,
        "modified_at": stat.st_mtime,
        "record_count": record_count,
        "type": file_path.suffix[1:] if file_path.suffix else "unknown"
    }


@router.get("/files")
async def list_data_files(platform: Optional[str] = None, file_type: Optional[str] = None):
    """Get data file list"""
    if not DATA_DIR.exists():
        return {"files": []}

    files = []
    supported_extensions = task_store.FILE_TYPES

    for root, dirs, filenames in os.walk(DATA_DIR):
        if Path(root) == DATA_DIR:
            dirs[:] = [d for d in dirs if d != 'tasks']
        root_path = Path(root)
        for filename in filenames:
            file_path = root_path / filename
            if file_path.suffix.lower() not in supported_extensions:
                continue

            # Platform filter
            if platform:
                rel_path = str(file_path.relative_to(DATA_DIR))
                if platform.lower() not in rel_path.lower():
                    continue

            # Type filter
            if file_type and file_path.suffix[1:].lower() != file_type.lower():
                continue

            try:
                files.append(get_file_info(safe_file(str(file_path.relative_to(DATA_DIR)))))
            except Exception:
                continue

    # Sort by modification time (newest first)
    files.sort(key=lambda x: x["modified_at"], reverse=True)

    return {"files": files}


@router.get("/files/{file_path:path}")
async def get_file_content(file_path: str, preview: bool = True, limit: int = 100, sheet: Optional[str] = None):
    """Get file content or preview"""
    full_path = safe_file(file_path)

    if not full_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    if not full_path.is_file():
        raise HTTPException(status_code=400, detail="Not a file")

    # Security check: ensure within DATA_DIR
    try:
        full_path.resolve().relative_to(DATA_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    if preview:
        limit = max(1, min(limit, 1000))
        # Return preview data
        try:
            if full_path.suffix == ".json":
                with open(full_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return {"data": data[:limit], "total": len(data)}
                    return {"data": data, "total": 1}
            elif full_path.suffix == '.jsonl':
                rows, total = [], 0
                with full_path.open(encoding='utf-8') as f:
                    for line in f:
                        if line.strip():
                            if len(rows) < limit:
                                rows.append(json.loads(line))
                            total += 1
                return {'data': rows, 'total': total}
            elif full_path.suffix == ".csv":
                import csv
                with open(full_path, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    rows = []
                    for i, row in enumerate(reader):
                        if i >= limit:
                            break
                        rows.append(row)
                    # Re-read to get total count
                    f.seek(0)
                    total = sum(1 for _ in f) - 1
                    return {"data": rows, "total": total}
            elif full_path.suffix.lower() in (".xlsx", ".xls"):
                import pandas as pd
                with pd.ExcelFile(full_path) as workbook:
                    sheets = workbook.sheet_names
                selected_sheet = sheet or sheets[0]
                if selected_sheet not in sheets:
                    raise HTTPException(400, '工作表不存在')
                # Read first limit rows
                df = pd.read_excel(full_path, nrows=limit, sheet_name=selected_sheet)
                # Get total row count (only read first column to save memory)
                df_count = pd.read_excel(full_path, usecols=[0], sheet_name=selected_sheet)
                total = len(df_count)
                # Convert to list of dictionaries, handle NaN values
                rows = df.where(pd.notnull(df), None).to_dict(orient='records')
                return {
                    "data": rows,
                    "total": total,
                    "columns": list(df.columns),
                    "sheets": sheets, "sheet": selected_sheet
                }
            else:
                raise HTTPException(status_code=400, detail="Unsupported file type for preview")
        except HTTPException:
            raise
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON file")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    else:
        # Return file download
        return FileResponse(
            path=full_path,
            filename=full_path.name,
            media_type="application/octet-stream"
        )


@router.get("/download/{file_path:path}")
async def download_file(file_path: str):
    """Download file"""
    full_path = safe_file(file_path)

    if not full_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    if not full_path.is_file():
        raise HTTPException(status_code=400, detail="Not a file")

    # Security check
    try:
        full_path.resolve().relative_to(DATA_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    return FileResponse(
        path=full_path,
        filename=full_path.name,
        media_type="application/octet-stream"
    )


@router.get("/stats")
async def get_data_stats():
    """Get data statistics"""
    if not DATA_DIR.exists():
        return {"total_files": 0, "total_size": 0, "by_platform": {}, "by_type": {}}

    stats = {
        "total_files": 0,
        "total_size": 0,
        "by_platform": {},
        "by_type": {}
    }

    supported_extensions = task_store.FILE_TYPES

    for root, dirs, filenames in os.walk(DATA_DIR):
        root_path = Path(root)
        for filename in filenames:
            file_path = root_path / filename
            if filename == 'task.json':
                continue
            if file_path.suffix.lower() not in supported_extensions:
                continue

            try:
                stat = file_path.stat()
                stats["total_files"] += 1
                stats["total_size"] += stat.st_size

                # Statistics by type
                file_type = file_path.suffix[1:].lower()
                stats["by_type"][file_type] = stats["by_type"].get(file_type, 0) + 1

                # Statistics by platform (inferred from path)
                rel_path = str(file_path.relative_to(DATA_DIR))
                for platform in ["xhs", "dy", "ks", "bili", "wb", "tieba", "zhihu"]:
                    if platform in rel_path.lower():
                        stats["by_platform"][platform] = stats["by_platform"].get(platform, 0) + 1
                        break
            except Exception:
                continue

    return stats


@router.get('/tasks')
async def tasks(keyword: str = ''):
    from ..services import crawler_manager
    async with crawler_manager._lock:
        task_store.reconcile()
        rows = task_store.list_tasks()
        if keyword.strip():
            term = keyword.strip().casefold()
            rows = [r for r in rows if term in ' '.join(str(r.get(k) or '') for k in ('keywords', 'specified_ids', 'creator_ids', 'platform', 'id')).casefold()]
        for row in rows:
            row['files'] = [get_file_info(p) for p in task_store.output_files(row['id'])]
        return {'tasks': rows}


@router.delete('/tasks/{ident}')
async def delete_task(ident: str):
    from ..services import crawler_manager
    async with crawler_manager._lock:
        task_store.reconcile()
        task_store.delete(ident)
    return {'status': 'deleted', 'id': ident}


@router.get('/tasks/{ident}/export')
async def export_task(ident: str):
    from ..services import crawler_manager
    async with crawler_manager._lock:
        task_store.reconcile()
        row = task_store.load(ident)
        task_store.ensure_finished(row)
        fd, name = tempfile.mkstemp(suffix='.zip', prefix='crawler-export-')
        os.close(fd)
        try:
            with zipfile.ZipFile(name, 'w', zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('task.json', json.dumps(row, ensure_ascii=False, indent=2))
                for path in task_store.output_files(ident):
                    archive.write(path, str(path.relative_to(task_store.task_dir(ident) / 'output')))
        except Exception:
            Path(name).unlink(missing_ok=True)
            raise
    return FileResponse(name, filename=f'task-{ident}.zip', media_type='application/zip',
                        background=BackgroundTask(Path(name).unlink, missing_ok=True))


@router.delete('/files/{file_path:path}')
async def delete_legacy_file(file_path: str):
    from ..services import crawler_manager
    async with crawler_manager._lock:
        task_store.reconcile()
        if (crawler_manager.process and crawler_manager.process.poll() is None) or any(r['status'] in task_store.ACTIVE for r in task_store.list_tasks()):
            raise HTTPException(409, '采集中不能删除历史文件，请先停止任务。')
        path = safe_file(file_path)
        if path.is_relative_to((DATA_DIR / 'tasks').resolve()):
            raise HTTPException(400, '请按任务删除，避免破坏任务数据。')
        from ..knowledge_bridge import invalidate
        invalidate(path)
        path.unlink()
    return {'status': 'deleted'}
