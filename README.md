# 社区内容研究助手

基于 [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) 构建的贴吧内容研究助手。`MediaCrawler/` 保留上游采集能力并包含本项目的任务管理、浏览器复用与界面改动；`src/community_research/` 实现独立的检索、证据核验、上下文管理及增量调度能力。

上游代码遵循 [非商业学习使用许可证 1.1](MediaCrawler/LICENSE)，发布副本保留其版权声明。项目用于学习与研究，当前研究层支持贴吧 JSON/JSONL，不能将上游多平台采集能力等同于已完成的多平台研究支持。

仓库不包含 API 密钥、平台登录状态、采集数据或本地运行数据库。运行前将 `.env.research.example` 复制为 `.env.research` 并按需配置；模型与浏览器登录信息仅保存在本地。

## 本地启动

在本目录运行：

```powershell
powershell -NoProfile -ExecutionPolicy RemoteSigned -File .\start.ps1
```

浏览器访问 http://127.0.0.1:8080 。停止前先在网页停止正在执行的采集，再运行 `stop.ps1`。

本地配置采用独立 Playwright Chromium（`ENABLE_CDP_MODE=False`）和文件存储。命令行默认 JSONL，网页默认 JSON，也可在页面选择其他格式。无需启动旧社区 Docker/MySQL，不使用原来的 5001 端口。首次打开网页会显示上游使用条款，首次采集对应平台时仍需扫码登录或完成平台验证。

- 采集配置：`MediaCrawler/config/base_config.py`。
- 标准浏览器渠道：`CHROMIUM_CHANNEL=None` 使用已安装的 Playwright Chromium；只有本机安装了相应浏览器，才改为 `"chrome"` 或 `"msedge"`。贴吧、B站、快手、知乎、微博已统一读取该配置，抖音和小红书原本就默认使用 Chromium。
- 默认数据目录：`MediaCrawler/data/`。
- 登录状态：`MediaCrawler/browser_data/`。
- Web 日志与 PID：`.runtime/`。
- 原项目说明：`MediaCrawler/README.md`。

## 按任务管理采集结果

网页点击“开始爬虫”后会创建独立任务，记录平台、关键词/目标、开始与结束时间、状态、输出格式及评论开关，不保存登录 Cookie。每次任务写入 `MediaCrawler/data/tasks/<任务ID>/output/`，同一天多次采集也不会再混到一起。同一帖子可在不同任务中分别保存，并通过各自任务参数追溯来源。

在“数据管理”中：

- **采集任务**：按关键词、平台、目标 ID 或任务编号筛选，选择任务后分别查看帖子和评论；JSONL 支持预览，Excel 可切换工作表。
- **导出任务 ZIP**：导出该任务的采集文件与参数说明。单个文件也可单独下载。
- **删除任务数据**：确认后永久删除该任务本地目录，不影响其他任务、网站原文或已下载的副本。运行中任务禁止删除和整包导出。
- **历史文件**：改造前按日期累计的文件原样保留，可能混合多次搜索。支持预览、下载和逐文件确认删除；采集中禁止删除历史文件。

任务状态包括启动中、采集中、已完成、完成但有错误、失败、已停止、已中断。状态反映执行结果，不保证平台返回内容与主题相关，也不保证采集完整。服务重启后，进程已经结束但未记录结果的任务标为已中断；仍存活的进程保持受保护状态。

网页任务目前支持 JSON、JSONL、CSV、Excel。SQLite/MySQL/MongoDB 等共享数据库存储仍可通过原命令行使用，不纳入网页的任务删除。直接使用命令行时也会生成独立运行文件名，但不会自动创建网页任务记录；可通过 `--save_data_path` 指定输出目录。

## 重新安装或构建

首页默认进入助手，地址 http://127.0.0.1:8080/#assistant ，模型配置位于根目录 `.env.research`。直接描述需求并发送：助手内部判断本地检索、在线补采或必要澄清，在默认预算内自动执行，无需选择模式、填写查询词或确认配置表。需要更多内容可说“多找一些”，也可明确“只看已有数据”。原爬虫配置保留在高级手动采集。最新自动化、可选向量接口和未完成项见 [P5基础能力](docs/p5/README.md)；历史交付见 [P1](docs/p1/README.md)、[P2](docs/p2/README.md)、[P3](docs/p3/README.md)、[P4](docs/p4/README.md)。数据库位于 `.runtime/research/index.sqlite3`。

```powershell
cd MediaCrawler
uv sync --locked
uv run playwright install chromium
cd webui
npm.cmd ci
npm.cmd run build
```

只构建应用前端 `webui`，无需安装项目根目录的文档站依赖。启动不自动开始采集，也不需要填写 LLM API 密钥。

完成上述依赖安装后，回到本项目根目录安装研究模块（重新 `uv sync` 后也应执行）：

```powershell
uv pip install --python .\MediaCrawler\.venv\Scripts\python.exe -e .
```

## 数据文件命名

2026-10-10 增加 [P6 贴吧增量复采与调度](docs/p6/README.md)：助手帖子来源卡片可“复采并检查更新”，与自动采集共用串行队列，显示新增评论、内容版本变化及前后证据；服务重启不会自动重新采集。默认仅读取有界最新评论窗口，不保证完整评论历史。多平台研究扩展按用户选择暂缓。

新采集文件使用“模式_数据类型_平台_日期_时分秒_任务标识.格式”，例如：

- search_contents_tieba_2026-09-18_17-30-05_a1b2c3d4e5f6.json
- search_comments_tieba_2026-09-18_17-30-05_a1b2c3d4e5f6.json

同一任务的正文与评论共享时间和标识，便于配对；不同任务即使同秒启动也可区分。JSON、JSONL、CSV、Excel均适用。旧文件不自动改名，新的规则从下次采集进程启动生效。命令行也会按每次运行生成独立名称，不再仅按日期累计。

## ????

???? Flask ??????????????????? `start.ps1` ? `MediaCrawler/`?????? [????](docs/legacy-community-README.md)?

## ??????

??????????????? Flask ??????

```powershell
.\MediaCrawler\.venv\Scripts\python.exe -m pytest tests/research
```

`docs/p0/fixtures.json` ??????????????????
