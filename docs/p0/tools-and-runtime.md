# P0 工具与首版运行契约 v0.1

P2已实现本地检索和证据工具，见 [P2说明](../p2/README.md)。P3 Harness与对话HTTP接口已实现、真实模型验收待配置，见 [P3说明](../p3/README.md)。采集调度工具尚未实施。

P2 契约补充：检索增加 task_ids（最多20个，限已注册来源的采集任务）；与source_ids取交集。include_context返回独立上下文证据ID，再通过read_evidence读取原文，以限制响应大小。单次证据响应包含待继续读取ID；极端单条元数据过大返回response_too_large。每轮引用授权集合仍由P3实施。

P3追问补充：Harness还允许重新读取同一会话最近历史回答中经校验仍有效的引用ID；引用输出仍必须本轮实际读取，不复用旧的已读状态。直接只读工具调用不强制先消耗一次模型调用生成计划，系统会记录请求范围。

## 首批只读工具

所有工具：`schema_version="0.1"`；拒绝额外参数，字符串 trim 后校验长度，禁止把未知字段当 SQL/路径/URL 执行。调用身份、run_id、预算由 Harness 注入，不接受模型覆盖。导入不支持的平台返回 unsupported_platform，不伪装为无结果。

### search_posts / search_comments

共同参数：

| 字段 | 类型、默认与限制 |
| --- | --- |
| platform | 字符串，M1 仅 `tieba` |
| source_ids | 可选字符串数组，最多 20；空数组=全部当前可用来源；未知 ID 返回 invalid_arguments |
| all_terms / any_terms / exclude_terms | 字符串数组，各最多 8 项，每项 1–80 字符，默认空 |
| fields | 帖子默认 `[title,body]`，评论只能 `[body]`；显式空数组非法 |
| published_from / published_to | 可空带时区 ISO 时间，起点小于终点，左闭右开 |
| limit | 整数 1–50，默认 20；不接受布尔值 |
| cursor | 可空服务端不透明游标，绑定完整筛选条件与索引版本 |

帖子：在所选字段中，all_terms 每项至少命中一个字段；any_terms 非空时至少命中一项；exclude_terms 任一命中即排除。各条件之间为 AND。匹配采用 Unicode casefold 后的连续子串，不做自动同义词扩展、不忽略中间字符。`all_terms=["cs","饰品"]` 能匹配 `CS 中间有文字 饰品`，单项 `"cs饰品"` 则要求连续命中。

评论额外参数 `post_ids`（标准实体 ID 数组，最多 20）、`parent_id`（可空）用于关系过滤；不能因原帖命中词语就认定评论正文命中。所有词项均为空时允许列出范围内记录，仍分页限量。

时间未知记录不进入有时间边界的结果。相同内容多来源去重展示一次，但返回全部可用来源；不同版本默认使用有效最新视图。固定排序：标准发布时间降序（未知最后），实体 ID 升序。索引版本变化使旧游标返回 stale_cursor，而非悄悄漏项或重复。

### read_evidence

入参 `evidence_ids`：1–20 个由本轮检索返回的 ID；`include_context`：布尔值，默认 false。每条正文片段最多 2000 字符，总响应最多 24000 字符；父评论/帖子上下文生成独立证据 ID，注明关系，不冒充评论自身文本。超出范围时返回截断信息和继续读取入口。

返回确定快照、原文片段、偏移、来源、可空的帖子/父评论上下文。未知证据 ID 返回 evidence_not_found，来源失效返回 evidence_unavailable；两者都不能变成“内容不存在”。

### 统一返回

```json
{
  "schema_version": "0.1",
  "status": "ok",
  "items": [],
  "coverage": {
    "scope": "local_imported_data",
    "source_ids": [],
    "index_revision": 1,
    "returned": 0,
    "has_more": false,
    "next_cursor": null,
    "excluded_unknown_time": 0,
    "partial_sources": []
  },
  "error": null
}
```

状态为 ok/empty/partial/error。检索成功无匹配用 empty；来源未导入用 error/not_imported；部分来源不可用或结果片段截断用 partial，并说明原因。`has_more=true` 单独表示还有分页，不意味着执行失败。items 包含实体 ID、快照 ID、原始 ID、实际命中字段/片段、来源和证据 ID；没有经过模型筛选时，不返回伪造的主题相关性分数。

错误结构：`{code,message,retryable,details}`，details 仅允许字段错误位置、来源 ID、限制值等安全信息。错误类别：invalid_arguments、not_imported、source_unavailable、stale_cursor、evidence_not_found、evidence_unavailable、budget_exceeded、cancelled、timeout、internal_error。只有瞬时超时可在剩余总预算内有限重试；重试不重置预算。

## 导入与采集不放入首批模型工具

P1 导入为用户/服务操作：`register_source(platform,path,type,collection_task_id?,source_timezone?)` → source_id；`import_source(source_id)` → import_id 与计数报告。路径校验在服务层，模型不能提供任意磁盘路径。来源删除也是用户操作。

P4 才启用采集适配器：创建任务传平台、模式、关键词/目标、数量上限和研究分支 ID；返回 collection_task_id；通过 ID 查询和取消。沿用现有 `/api/crawler/start`、`/status`、`/stop` 与 `/api/data/tasks` 的能力，但需要补上研究任务关联、幂等启动键、有效预算核对和明确等待登录状态，不把现有接口当成已经满足完整契约。

模型看到的只是 `auth_profile_id` 或 `login_required`，不会收到 Cookie。M1 无在线采集工具，即使模型请求也拒绝调用。

## 目标与回答契约

目标对象含实体/主题、领域、具体问题、时间范围和用户约束；保存独立版本。M1 遇到无法确定“小驴”指代时输出 needs_clarification；已明确 donk 的上下文不重复询问，也不自动扩展到动物。

回答对象：`outcome=answered/partial/no_matches/needs_clarification/failed`、`paragraphs[{text,evidence_ids}]`、`scope`、`limitations`、`run_id`。answered 的事实段落必须引用本轮已读取证据；no_matches 必须存在一次正确工具成功返回空结果，不能由异常推导。模型语义是否忠实在评测中核对，不以 JSON 合法代替。

初始默认预算（工程起点，非质量最优值）：单轮模型调用最多 8 次、只读工具最多 10 次、总执行 90 秒、单次模型最多 30 秒；最多一次格式纠正，共享原预算。P3 允许用户配置更小的值，扩大上限需明确配置，不由模型自行修改。

## 首版运行结构决定

- 外层新增标准 Python distribution `community-research-agent`，采用 `src/community_research/` 包名，内部为 `knowledge/`、`agent/`、`api/`。这是对顶层方案概念目录的具体化，避免与上游的 `config`、`tools`、`api` 同名。
- Python 使用现有 3.11 环境；P1 使用标准库 sqlite3，数据库固定到外层 `.runtime/research/index.sqlite3`，路径根据显式配置或模块定位计算，不依赖 cwd。运行数据不进入源码。
- P1 创建外层 pyproject.toml，使用 editable 安装到既有 `.venv`；工具与测试通过包入口 `python -m community_research...` 调用，不临时拼 sys.path。
- P3 由现有 FastAPI 挂载外层包提供的 `/api/research/*` router；网页复用现有 WebUI 增加助手页，仍使用 8080。上游改动限于 router 装配与页面入口，业务代码留在外层包。
- 不在 P0 创建这些模块、安装新依赖或改启动脚本。新增依赖在引入时固定版本并做兼容测试，SQLite 开启外键与显式事务，采用迁移版本表；本地单进程优先。
- 外层 `tests/research/` 与采集项目测试分开运行，避免同名包和 conftest 串入。样例放 `docs/p0/`，测试从测试文件定位路径，不从当前目录猜测。
- `.env.research`（未来）保存模型配置，凭据不写日志、快照或版本库；仅有配置时才启用真实模型评测。

## P1 首个工作包

先实现来源注册、SQLite 迁移、JSON/JSONL 导入及报告；随后实现内容身份/快照/出现记录、延迟关系和删除失效。P1 不提前实现模型调用或采集调度。开发前确认当前 Git 布局，避免把缺失的历史仓库当成已存在的隔离基础。
