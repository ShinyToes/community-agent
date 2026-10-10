# P6：贴吧增量复采与单进程调度

实施日期：2026-10-10。本轮范围由用户明确选择为“先完成贴吧增量与调度”。该范围已实现；多平台、更多导入格式、作者扩展和独立向量数据库仍为按需后续项，不计入本轮完成声明。

## 使用入口

在助手回答的帖子来源卡片点击 **“复采并检查更新”**。系统固定本地基线，提交 FIFO 队列，复采该帖正文和最多 20 条最新一级评论，导入独立任务输出，再展示变化统计和前后原文片段。可展开“复采任务与队列”查看等待、登录、完成、部分完成或中断状态；等待中和运行中都能取消。

页面支持前后片段、差异分页和返回第一页；刷新页面不会重复提交。若基线或本次来源被删除/改写导致失效，页面停止展示失效的对比原文。原始采集文件不会被增量功能覆盖。

## 增量契约

- **固定基线**：提交时选取目标帖子及其已导入评论的活动来源 ID；不在排队结束后悄悄更换基线。对比以每组所选来源内的最新观测快照为准。
- **来源版本**：保留前后任务 ID、文件哈希、快照 ID 与证据偏移。仍沿用既有身份与多来源去重规则；同一内容重复复采不会被当成新增实体。
- **相对基线新增**：本次来源中存在、基线中不存在的帖子或评论。它可能是过去没采到的旧内容，不能称作网站刚发表。
- **版本变化**：同一实体的内容快照改变，返回具体变化字段。长正文片段定位到首处不同字符附近；片段不等于完整 diff，仍可用 `read_evidence` 及前后片段继续回读原文。
- **本次未观测**：基线存在、本次样本没有。不会当成网站删除，也不删除本地历史。
- **最新评论窗口**：复采从 `total_replay_page` 对应尾页向前读取，页内逆序，按评论 ID 去重、每帖最多 20 条，不采楼中楼。普通采集保持从第一页开始。大量新增评论、旧评论编辑和已删除内容可能落在窗口之外，不能宣称完整增量同步。
- **读取保护**：每次对比和队列结果读取都检查来源有效性。队列数据库只保存引用和统计，不另存一份可绕过撤销的正文。
- **部分结果**：采集有错误、目标没有全部返回、导入有坏记录、超时或超额均明确标记；已取得的文件保留。基线在排队期间失效时，在联网前拒绝执行。

## 调度契约

采用 SQLite `research_queue`，面向现有单进程 Web 服务和单爬虫，不建设分布式系统。

- 复采与自动助手的在线采集阶段共享同一 FIFO 租约；进入队列后按序获得爬虫。自动助手的规划和本地检索仍可独立执行，进入在线阶段才排队。
- 手动高级采集继续使用原有爬虫独占检查；其运行时队列等待，不强行停止手动任务。
- 同时最多 20 个活动/暂停队列项；复采最多 20 个已导入的数字帖子 ID，每帖 0–20 条评论，总时限 30–300 秒，默认 180 秒。等待、登录、采集、导入和对比均计入本次时限。
- 自动助手仍使用原有全轮配额和 180 秒总时限。排队后只使用剩余时间，没有因入队而重新获得一轮预算。
- `request_id` 用作幂等键：相同键与参数不重复提交，参数冲突返回错误。页面同步锁防止一次双击重复提交。
- 取消等待项不停止其他任务的爬虫；取消当前项只清理自己的进程/浏览器，并释放租约。
- 重启时未执行复采标为 `paused`，必须用户点击“继续复采”；已运行项标为 `interrupted`，不自动重试。旧对话采集租约标中断，不能因重启自动重放模型规划或联网。
- “继续复采”仅恢复尚未开始的暂停项，沿用原目标和基线，以新的显式继续操作开始该次等待/执行时限。它不是后台定时或无期限任务。

## 工具和 API

新增只读模型工具 `source_versions` 和 `compare_sources`，均可通过原 CLI `tool --arguments` 调用。前者按原帖数字 ID 发现可比较的本地来源；后者比较来源组，返回变化证据。模型仍必须本轮 `read_evidence` 后才可引用。来源按注册时间排序不代表网站变化时间；同一任务的帖子/评论文件必须归为同一观测轮次。

| API | 用途 |
|---|---|
| `POST /api/research/queue/refresh` | 提交复采：`post_ids`、可选 `comments_per_post`、`seconds`、`request_id` |
| `GET /api/research/queue/jobs` | 查看最近队列项，默认 50 项 |
| `GET /api/research/queue/jobs/{id}` | 读取任务和仍有效的对比结果 |
| `POST /api/research/queue/jobs/{id}/cancel` | 取消复采；对话租约走原对话取消接口 |
| `POST /api/research/queue/jobs/{id}/resume` | 显式恢复尚未执行的暂停复采 |
| `GET /api/research/sources` | 查看来源元数据 |
| `POST /api/research/sources/compare` | 按前后来源组对比，可限定原帖 ID，支持稳定分页 |
| `POST /api/research/maintenance` | 核验来源、清理失效缓存与旧游标、SQLite 优化及规模统计，不删除源文件 |

对比最多每页 50 项，同时将条目内容限制在约 16,000 字符内；页数和全量统计分开返回。游标绑定全部参数和索引 revision，来源变化后失效；同范围同 revision 的游标复用，避免轮询无限增生。维护只添加辅助索引和执行 SQLite 优化，不宣称未经测量的性能提升。

提交示例（目标必须已导入）：

```powershell
$p6Refresh = @{ post_ids=@('实际帖子数字ID'); comments_per_post=20; seconds=180; request_id='自行指定的幂等键' } | ConvertTo-Json
Invoke-RestMethod 'http://127.0.0.1:8080/api/research/queue/refresh' -Method Post -ContentType 'application/json' -Body $p6Refresh
```

## 验证及范围

验证记录见 [validation-report.json](validation-report.json) 和 [ui-validation.json](ui-validation.json)。新增回归覆盖差异与原文偏移、长正文、分页/预算、幂等、队列容量、FIFO、与自动采集互斥、立即取消/等待取消/运行取消、基线撤销、暂停恢复、失败清理及 HTTP 接口。真实本地 Chromium/子进程生命周期检查仍通过，平台操作采用隔离替身。

最终研究回归 **204 项通过**（含新增 26 项 P6），贴吧分页 4 项通过；P6 界面 13 项、原助手界面 18 项通过，JavaScript 错误 0；TypeScript 与生产构建通过。新版服务已启动，`/api/health` 为 `ok`，爬虫 `idle`，检查时队列 0 项。

本轮没有外部聊天模型请求或真实贴吧联网请求。因此工程行为已验证，真实平台的尾页返回、登录和新增评论覆盖仍需实采验收；不能用替身测试证明网站内容完整性。也没有实现后台周期复采、楼中楼增量、水位补齐、网站删除判定或多平台扩展。

```powershell
.\MediaCrawler\.venv\Scripts\python.exe -m pytest tests/research --confcutdir=tests/research -p no:cacheprovider -q --basetemp=.runtime/p6-test-run
.\MediaCrawler\.venv\Scripts\python.exe tools/check_p6_ui.py
.\MediaCrawler\.venv\Scripts\python.exe tools/check_p4_crawler.py
.\MediaCrawler\.venv\Scripts\python.exe tools/check_browser_session.py
```
