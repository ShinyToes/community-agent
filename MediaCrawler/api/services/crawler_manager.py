# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/api/services/crawler_manager.py
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

import asyncio
import subprocess
import signal
import os
import sys
import re
import json
import uuid
from typing import Optional, List
from datetime import datetime
from pathlib import Path

from ..schemas import CrawlerStartRequest, LogEntry
from .. import task_store


class CrawlerManager:
    """Crawler process manager"""

    def __init__(self):
        self._lock = asyncio.Lock()
        self.process: Optional[subprocess.Popen] = None
        self.status = "idle"
        self.started_at: Optional[datetime] = None
        self.current_config: Optional[CrawlerStartRequest] = None
        self._log_id = 0
        self._logs: List[LogEntry] = []
        self._read_task: Optional[asyncio.Task] = None
        self.task_id = None
        self.had_errors = False
        self.owner = None
        self.session_dir = None
        # Project root directory
        self._project_root = Path(__file__).parent.parent.parent
        # Log queue - for pushing to WebSocket
        self._log_queue: Optional[asyncio.Queue] = None

    @property
    def logs(self) -> List[LogEntry]:
        return self._logs

    def get_log_queue(self) -> asyncio.Queue:
        """Get or create log queue"""
        if self._log_queue is None:
            self._log_queue = asyncio.Queue()
        return self._log_queue

    def _create_log_entry(self, message: str, level: str = "info") -> LogEntry:
        """Create log entry"""
        self._log_id += 1
        entry = LogEntry(
            id=self._log_id,
            timestamp=datetime.now().strftime("%H:%M:%S"),
            level=level,
            message=message
        )
        self._logs.append(entry)
        # Keep last 500 logs
        if len(self._logs) > 500:
            self._logs = self._logs[-500:]
        return entry

    async def _push_log(self, entry: LogEntry):
        """Push log to queue"""
        if self._log_queue is not None:
            try:
                self._log_queue.put_nowait(entry)
            except asyncio.QueueFull:
                pass

    def _parse_log_level(self, line: str) -> str:
        """Parse log level"""
        match = re.search(r'MediaCrawler\s+(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s', line)
        if match:
            return {'DEBUG': 'debug', 'INFO': 'info', 'WARNING': 'warning', 'ERROR': 'error', 'CRITICAL': 'error'}[match.group(1)]
        line_upper = line.upper()
        if "ERROR" in line_upper or "FAILED" in line_upper:
            return "error"
        elif "WARNING" in line_upper or "WARN" in line_upper:
            return "warning"
        elif "SUCCESS" in line_upper or "完成" in line or "成功" in line:
            return "success"
        elif "DEBUG" in line_upper:
            return "debug"
        return "info"

    async def reserve(self, owner):
        async with self._lock:
            task_store.reconcile()
            if self.owner or (self.process and self.process.poll() is None) or any(r['status'] in task_store.ACTIVE for r in task_store.list_tasks()):
                return False
            self.owner = owner
            self.session_dir = None
            return True

    async def release(self, owner):
        async with self._lock:
            if self.owner == owner:
                self.owner = None

    def sync_session_result(self, task_id):
        if not self.session_dir:
            return
        result_path = self.session_dir / (task_id + '.json')
        if result_path.is_file():
            result = json.loads(result_path.read_text(encoding='utf-8'))
            row = task_store.load(task_id)
            if row['status'] in task_store.ACTIVE:
                task_store.update(task_id, status=result['status'], finished_at=task_store.now(), exit_code=result['exit_code'], pid=None)

    def _queue_branch(self, task):
        temporary = self.session_dir / 'request.tmp'
        temporary.write_text(json.dumps({'task_id':task['id']}), encoding='utf-8')
        temporary.replace(self.session_dir / 'request.json')

    async def start(self, config: CrawlerStartRequest, owner=None, shared_session=False) -> bool:
        """Start crawler process"""
        async with self._lock:
            if self.owner is not None and self.owner != owner:
                return False
            if self.process and self.process.poll() is None:
                if shared_session and owner and self.owner == owner and self.session_dir:
                    self.sync_session_result(self.task_id)
                    if task_store.load(self.task_id)['status'] in task_store.ACTIVE:
                        return False
                    task = task_store.create(config)
                    self.task_id, self.current_config = task['id'], config
                    task_store.update(self.task_id, status='running', pid=self.process.pid)
                    self._queue_branch(task)
                    await self._push_log(self._create_log_entry('Reusing collection browser session for next branch', 'info'))
                    return True
                return False
            if shared_session and self.session_dir:
                # A crashed collection must not silently open a second browser.
                return False
            if self._read_task and not self._read_task.done():
                await self._read_task
            task_store.reconcile()
            if any(row['status'] in task_store.ACTIVE for row in task_store.list_tasks()):
                return False

            # Clear old logs
            self._logs = []
            self._log_id = 0

            # Clear pending queue (don't replace object to avoid WebSocket broadcast coroutine holding old queue reference)
            if self._log_queue is None:
                self._log_queue = asyncio.Queue()
            else:
                try:
                    while True:
                        self._log_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass

            # Build command line arguments
            cmd = self._build_command(config)
            task = task_store.create(config)
            self.task_id = task['id']
            self.had_errors = False
            self.session_dir = None
            if shared_session:
                if not owner or config.platform.value != 'tieba':
                    raise ValueError('shared_session_requires_owned_tieba')
                self.session_dir = task_store.DATA_DIR / 'browser_sessions' / uuid.uuid4().hex
                self.session_dir.mkdir(parents=True)
            cmd = [sys.executable, *cmd[3:], '--save_data_path', str(task_store.task_dir(self.task_id) / 'output')]

            # Log start information
            safe_cmd = list(cmd)
            if '--cookies' in safe_cmd:
                safe_cmd[safe_cmd.index('--cookies') + 1] = '[REDACTED]'
            entry = self._create_log_entry(f"Starting crawler: {' '.join(safe_cmd)}", "info")
            await self._push_log(entry)

            try:
                # Start subprocess
                self.process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding='utf-8',
                    bufsize=1,
                    cwd=str(self._project_root),
                    env={**os.environ, "PYTHONUNBUFFERED": "1", "RESEARCH_COMMENT_ORDER": config.comment_order,
                         **({"RESEARCH_COLLECTION_OWNER": owner} if owner else {}),
                         **({'RESEARCH_SESSION_DIR':str(self.session_dir.resolve()), 'RESEARCH_PARENT_PID':str(os.getpid())} if self.session_dir else {})}
                )

                self.status = "running"
                self.started_at = datetime.now()
                self.current_config = config
                task_store.update(self.task_id, status='running', pid=self.process.pid)
                if self.session_dir:
                    self._queue_branch(task)

                entry = self._create_log_entry(
                    f"Crawler started on platform: {config.platform.value}, type: {config.crawler_type.value}",
                    "success"
                )
                await self._push_log(entry)

                # Start log reading task
                self._read_task = asyncio.create_task(self._read_output())

                return True
            except Exception as e:
                self.status = "error"
                task_store.update(self.task_id, status='failed', finished_at=task_store.now())
                entry = self._create_log_entry(f"Failed to start crawler: {str(e)}", "error")
                await self._push_log(entry)
                return False

    async def stop(self, owner=None) -> bool:
        """Stop crawler process"""
        async with self._lock:
            if owner is not None and self.owner != owner:
                return False
            if not self.process or self.process.poll() is not None:
                return False

            self.status = "stopping"
            if self.session_dir:
                self.sync_session_result(self.task_id)
            if task_store.load(self.task_id)['status'] in task_store.ACTIVE:
                task_store.update(self.task_id, status='stopping')
            entry = self._create_log_entry("Sending SIGTERM to crawler process...", "warning")
            await self._push_log(entry)

            try:
                if self.session_dir:
                    (self.session_dir / 'stop').touch()
                    for _ in range(25):
                        if self.process.poll() is not None:
                            break
                        await asyncio.sleep(.2)
                if self.process.poll() is None and os.name == 'nt':
                    await asyncio.to_thread(subprocess.run, ['taskkill', '/PID', str(self.process.pid), '/T', '/F'],
                                            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                elif self.process.poll() is None:
                    self.process.send_signal(signal.SIGTERM)

                # Wait for graceful exit (up to 15 seconds)
                for _ in range(30):
                    if self.process.poll() is not None:
                        break
                    await asyncio.sleep(0.5)

                # If still not exited, force kill
                if self.process.poll() is None:
                    entry = self._create_log_entry("Process not responding, sending SIGKILL...", "warning")
                    await self._push_log(entry)
                    self.process.kill()
                await asyncio.to_thread(self.process.wait, timeout=10)

                entry = self._create_log_entry("Crawler process terminated", "info")
                await self._push_log(entry)
                if self.process.poll() is None:
                    return False

            except Exception as e:
                entry = self._create_log_entry(f"Error stopping crawler: {str(e)}", "error")
                await self._push_log(entry)
                if self.process.poll() is None:
                    return False

            self.status = "idle"
            if self.session_dir:
                self.sync_session_result(self.task_id)
            if task_store.load(self.task_id)['status'] in task_store.ACTIVE:
                task_store.update(self.task_id, status='stopped', finished_at=task_store.now(), exit_code=self.process.returncode, pid=None)
            self.current_config = None

            # Cancel log reading task
            if self._read_task:
                self._read_task.cancel()
                self._read_task = None

            return True

    def get_status(self) -> dict:
        """Get current status"""
        return {
            "status": self.status,
            "platform": self.current_config.platform.value if self.current_config else None,
            "crawler_type": self.current_config.crawler_type.value if self.current_config else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "error_message": None
        }

    def _build_command(self, config: CrawlerStartRequest) -> list:
        """Build main.py command line arguments"""
        cmd = ["uv", "run", "python", "main.py"]

        cmd.extend(["--platform", config.platform.value])
        cmd.extend(["--lt", config.login_type.value])
        cmd.extend(["--type", config.crawler_type.value])
        cmd.extend(["--save_data_option", config.save_option.value])

        # Pass different arguments based on crawler type
        if config.crawler_type.value == "search" and config.keywords:
            cmd.extend(["--keywords", config.keywords])
        elif config.crawler_type.value == "detail" and config.specified_ids:
            cmd.extend(["--specified_id", config.specified_ids])
        elif config.crawler_type.value == "creator" and config.creator_ids:
            cmd.extend(["--creator_id", config.creator_ids])

        if config.start_page != 1:
            cmd.extend(["--start", str(config.start_page)])

        cmd.extend(["--get_comment", "true" if config.enable_comments else "false"])
        cmd.extend(["--get_sub_comment", "true" if config.enable_sub_comments else "false"])

        if config.max_notes_count is not None:
            cmd.extend(["--crawler_max_notes_count", str(config.max_notes_count)])

        if config.max_comments_count is not None:
            cmd.extend(["--max_comments_count_singlenotes", str(config.max_comments_count)])

        if config.cookies:
            cmd.extend(["--cookies", config.cookies])

        cmd.extend(["--headless", "true" if config.headless else "false"])

        return cmd

    async def _read_output(self):
        """Asynchronously read process output"""
        loop = asyncio.get_event_loop()

        try:
            while self.process and self.process.poll() is None:
                # Read a line in thread pool
                line = await loop.run_in_executor(
                    None, self.process.stdout.readline
                )
                if line:
                    line = line.strip()
                    if line:
                        level = self._parse_log_level(line)
                        self.had_errors |= level == 'error'
                        entry = self._create_log_entry(line, level)
                        await self._push_log(entry)

            # Read remaining output
            if self.process and self.process.stdout:
                remaining = await loop.run_in_executor(
                    None, self.process.stdout.read
                )
                if remaining:
                    for line in remaining.strip().split('\n'):
                        if line.strip():
                            level = self._parse_log_level(line)
                            self.had_errors |= level == 'error'
                            entry = self._create_log_entry(line.strip(), level)
                            await self._push_log(entry)

            # Process ended
            if self.status == "running":
                exit_code = self.process.returncode if self.process else -1
                self.sync_session_result(self.task_id)
                if task_store.load(self.task_id)['status'] in task_store.ACTIVE:
                    task_store.update(self.task_id, status='failed' if self.session_dir else ('completed_with_errors' if self.had_errors else 'completed') if exit_code == 0 else 'failed',
                                      finished_at=task_store.now(), exit_code=exit_code, pid=None)
                if exit_code == 0:
                    entry = self._create_log_entry("Crawler completed successfully", "success")
                else:
                    entry = self._create_log_entry(f"Crawler exited with code: {exit_code}", "warning")
                await self._push_log(entry)
                self.status = "idle"

        except asyncio.CancelledError:
            pass
        except Exception as e:
            entry = self._create_log_entry(f"Error reading output: {str(e)}", "error")
            await self._push_log(entry)


# Global singleton
crawler_manager = CrawlerManager()
