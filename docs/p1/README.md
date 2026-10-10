# P1：本地导入、快照和来源

完成日期：2026-09-20。P0 材料重新校验通过后实施 P1.1—P1.5。P1 是后续助手的数据基础，目前没有新增对话界面、条件搜索或模型调用。

## 已实现

- 显式导入项目内的贴吧 JSON 数组与 JSONL；保存原始 ID、文件相对路径、文件 SHA256 和记录序号/物理行号。
- SQLite 分离内容身份、内容快照、文件来源、来源出现记录及导入报告。同一平台/类型/原始 ID 复用身份，同内容复用快照；跨文件保留独立来源。
- 评论通过同平台帖子 ID、父评论 ID 延迟关联；父评论必须属于同一帖子。缺少正文返回 unresolved，不补造正文。
- 重复导入不增加关联。文件覆盖后旧来源 superseded，重新显式导入生成新来源；新正文形成新快照，旧编号不指向新正文。
- 历史文件不补造任务信息；已停止/失败任务标为部分来源。报告的 completed 只表示导入无错误，不表示平台数据完整。
- 现有任务删除与历史文件删除接口在删除前同步撤销索引。每次列举/读取快照重新核验活动来源文件哈希，发现手工删除或覆盖后撤销旧来源。
- 最后一个来源失效时清除快照正文，保留身份、哈希和来源状态；其他来源仍支持同一快照时可以继续读取。相同内容日后重新显式导入可再次获得来源支持。

## 安装与命令

在项目根目录运行。已在现有虚拟环境安装；以后重新执行 MediaCrawler 的 `uv sync` 后应重新安装外层包：

```powershell
uv pip install --python .\MediaCrawler\.venv\Scripts\python.exe -e .

# 历史文件：注册并导入。时区由导入者声明，不从文件名猜测。
.\MediaCrawler\.venv\Scripts\python.exe -m community_research ingest testresult/search_contents_2026-09-18-1.json --platform tieba --timezone Asia/Shanghai

# 查看来源、快照目录、导入报告
.\MediaCrawler\.venv\Scripts\python.exe -m community_research sources
.\MediaCrawler\.venv\Scripts\python.exe -m community_research snapshots
.\MediaCrawler\.venv\Scripts\python.exe -m community_research reports

# 复现真实文件验收（仅限 P0 清单内、哈希未变的文件）
.\MediaCrawler\.venv\Scripts\python.exe tools/verify_p1_data.py
```

任务文件用 `ingest <文件路径> --platform tieba --type task --task-id <32位任务ID> --timezone Asia/Shanghai`；路径必须属于该任务 output，且任务已经结束。

`register` 只登记，`import <source_id>` 导入已登记来源；`read <snapshot_id>` 返回内容与有效来源、关系状态；`refresh` 核验来源；`revoke <source_id>` 仅撤销知识库来源，不删除原文件。返回 JSON；业务参数错误退出码 2，整次导入失败为 1，成功或部分导入为 0，部分结果需读取报告。

默认根目录由包位置确定，不依赖当前工作目录；可通过全局 `--root` 或 `COMMUNITY_RESEARCH_ROOT` 指定。默认数据库是 `.runtime/research/index.sqlite3`，可通过 `--db` 单独指定。网页删除联动使用项目默认数据库；额外自定义数据库靠自身读取时核验来源，不承诺即时同步。

## 验收

- P0：9 条合成记录、20 个未来验收场景、5 个字面匹配预期、4 个真实文件哈希校验通过。这是材料校验，不是 P2/P3 功能测试。
- P1：19 项自动测试通过，覆盖幂等、多来源、版本变化、缺失文件、延迟关联、父评论跨帖拒绝、JSON/JSONL 错误定位、空正文、时间语义、路径/平台约束、运行中任务拒绝、非项目目录调用 CLI，以及现有两类删除入口的真实联动（使用临时数据）。
- 真实数据：4 个来源、358 条来源出现记录；206 个内容身份（57 帖子、149 评论）、209 个快照；所有评论有可关联原帖；重复导入新增为 0；4 个源文件字节不变。报告见 [validation-report.json](validation-report.json)。
- 真实数据没有父评论 ID，子回复关联使用合成用例验证；未进行联网采集或 LLM 质量评测。

```powershell
.\MediaCrawler\.venv\Scripts\python.exe -m pytest tests/research --confcutdir=tests/research -p no:cacheprovider -q
```

## 约定和限制

实体/快照/来源 ID 为内部 UUID，外部 ID 保留字符串。数据库字段名 `path/file_hash/task_id/locator/observed_at` 分别实现 P0 契约中的 relative_path/file_sha256/collection_task_id/record_locator/observed_at_utc。规范化发布时间及其时区依据放在来源出现记录上，避免不同来源的时区声明相互覆盖。

单文件上限 50 MiB，按文件事务导入；JSONL 坏行跳过并记录行号。无时区时间未声明来源时区时保留原文、标准时间为空；不拿采集时间充当发布时间。未知字段继续留在原始文件，不自动纳入正文。

空正文可以入库但有警告；P1 的 read 是快照读取，不是 P2 的片段证据接口。P2 必须拒绝创建空文本证据。旧回答的界面失效标记将在 P3 实现，目前没有回答对象。

当前读取会逐一核验活动文件，适合小规模本地使用；大量来源时再优化验证缓存。删除前同步失败会阻止源文件删除，避免留下看似有效的旧索引；若实际文件删除失败，索引保持撤销状态，可修复后重新显式导入。

下一阶段为 P2：字段和条件检索、分页、版本绑定的片段证据；本轮未提前实现。
