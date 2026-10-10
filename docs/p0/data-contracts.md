# P0 数据契约 v0.1

以下为 P1—P3 的接口与存储约定。P1 的身份、快照、来源、导入与失效处理已实现，字段映射及验收见 [P1 说明](../p1/README.md)；Evidence 及 Agent 对象仍待 P2/P3 实施。ID 均为字符串，避免平台长整数精度损失；平台显式指定为 `tieba`，不靠文件名猜平台。

## 最小对象

| 对象 | 必需字段与约束 |
| --- | --- |
| Entity 内容身份 | `entity_id`（内部 UUID）、`platform`、`kind=post/comment`、`external_id`；三元组唯一 |
| Snapshot 内容快照 | `snapshot_id`（UUID）、`entity_id`、`schema_version`、`content_hash`、`payload`、`created_at`；同实体同内容哈希唯一 |
| Source 来源 | `source_id`、`type=task/legacy`、`platform`、`relative_path`、`file_sha256`、`status=active/missing/deleted/superseded`；可空 `collection_task_id` |
| Occurrence 来源出现 | `source_id`、`snapshot_id`、`record_locator`、可空 `source_keyword`、`observed_at`；同来源同位置同快照唯一 |
| ImportRun 导入记录 | `import_id`、`source_id`、开始/结束时间、状态、读入/新增/复用/跳过/错误数、逐条错误定位 |
| Evidence 证据 | `evidence_id`、`snapshot_id`、`field`、`start`、`end`、`quote`、`source_ids`；绑定确定版本和范围 |
| ResearchTask 研究任务 | `research_id`、`session_id`、`goal_revision`、目标/领域/问题/时间限制、预算、状态；可以关联多个采集任务 |
| GoalRevision 目标修订 | `research_id`、版本号、用户输入/澄清依据、创建时间；模型查询不能覆盖该记录 |
| Session/Message 对话 | 会话 ID、消息 ID、角色、文本、创建时间；助手消息关联 run_id 和证据引用 |
| AgentRun 执行 | `run_id`、研究任务/目标版本、状态、预算初值与实际消耗、结果范围、错误/停止原因 |
| ToolEvent 工具事件 | `run_id`、`call_id`、工具名/版本、状态、耗时、条数、证据 ID；不保存 Cookie 或全量原文 |
| QueryBranch 查询分支（P4/P5） | 目标版本、父分支、表达、主线/探索、关系假设、证据、预算、状态和收益；M1 只预留契约 |

## 帖子与评论字段映射

| 原字段 | 标准字段/规则 |
| --- | --- |
| 帖子 `note_id` | `external_id`，非空字符串 |
| 帖子 `title` / `desc` | `title` / `body`，保留原文 Unicode；缺失用 null，空字符串保持空字符串 |
| 评论 `comment_id` / `content` | `external_id` / `body` |
| 评论 `note_id` | `post_external_id`，关联同平台 post；不得跨平台匹配 |
| 评论 `parent_comment_id` | `parent_external_id`；空字符串转 null，仅表示未给出父评论关系 |
| `note_url` | `source_url`，显示/跳转用；导入不访问 URL，模型不能据 URL 自动获取内容 |
| `tieba_name` / `tieba_id` | `forum_name` / 可空 `forum_external_id` |
| `publish_time` | `published_at_raw`、可空 `published_at_utc`、`timezone_basis` |
| `last_modify_ts` | `observed_at_raw`；验证为毫秒时间戳后转 `observed_at_utc`，不作为编辑时间 |
| `source_keyword` | Occurrence 来源元数据，不进入内容匹配字段和内容哈希 |
| `creator_hash` / `user_nickname` | 不透明的来源作者标记/显示名；不推断真实身份 |
| 回复数量字段 | 来源宣称的计数，不作为已采集条数或完整性证明 |

缺评论自身 ID 或所属帖子 ID 是逐条导入错误；合法但为空的正文/评论可入库，标记 `empty_body`，不生成空文本证据。未知字段保留于来源原始记录，不自动进入标准检索字段。

## 时间语义

- 标准内部时间使用带 `Z` 的 UTC ISO 8601。原始值始终保留。
- 无时区发布时间必须由来源注册携带 `source_timezone` 才能标准化；现有样例若指定 Asia/Shanghai，要记录为导入者声明，不能声称源数据自带时区。
- 未指定或解析失败时 UTC 字段为 null；严格时间筛选排除这些记录，同时报告排除数量，不默认补当前时间。
- 日期范围采用 `[from, to)`；用户说“最近一个月”时由目标整理层明确具体边界和时区，检索工具不自行猜日期。

## 来源、版本与幂等

1. 显式注册允许读取的项目内来源；任务来源只接受对应 `output` 下文件。Downloads 或外部文件需要用户指定后复制/登记为独立来源，不全盘扫描。
2. 同来源路径与文件哈希不变的重复导入复用记录；同字节文件出现在另一路径，建立另一来源，但复用内容快照。
3. 来源文件变化生成新 Source 版本，旧来源标为 superseded；已发回答不重定向到新正文。
4. 内容哈希由规范化字段对象计算：包括正文、标题、关系、原始发布时间和来源作者标记，不含路径、查询词、采集更新时间及回复计数；JSON 键排序、UTF-8、无多余空白。关系或正文变化形成新快照。
5. 最新视图按有效 `observed_at_utc`、导入时间和快照 ID 排序，明确它表示“最近采集到的版本”，并非网站当前版本。
6. 源关系使用外部 ID 延迟关联，正文/父评论缺失时返回 `relation_status=unresolved`；之后导入对应内容可补关系，不改变原始评论文本。
7. JSON 数组用从 1 开始的记录序号定位；JSONL 用从 1 开始的物理行号定位。坏 JSON 文件整体报格式错误；JSONL 坏行记录错误并继续，结果标 partial。

## 证据与删除

- 偏移按 Python Unicode 码点计算，区间 `[start,end)`，针对保留的标准原文；匹配用的 casefold 文本不作为引用原文。
- `quote` 必须等于对应字段切片，引用必须属于本轮工具实际返回并读取的证据集合。引用合法不等于语义结论正确。
- M1 证据视图读取本地已采集快照，不宣称原站当前仍公开或未修改。
- 删除某来源先标记不可用并移除其活动索引贡献；其他来源仍支持同一快照时，内容仍可检索。
- 最后一个有效来源消失时，从检索和证据正文读取中排除；保留 ID 与失效原因的墓碑，不保留可直接展示的失效原文。相关旧回答标为不可用，禁止再次送入模型当作有效证据。
- 单次导入保存的历史快照在来源仍可验证时可用于历史引用；来源已删除/覆盖/丢失时不能自动换成最新快照。
- 每次检索与证据读取检查来源可用性；缓存仅以已验证文件状态复用，变更时重新核对哈希。删除接口联动和手工删除后的失效检测必须在 P1 验收。

## 三类“任务”

研究任务是用户要解决的问题与目标；AgentRun 是围绕该目标的一次执行；CollectionTask 是 MediaCrawler 的一次平台采集。它们不共享 ID，不用一个 status 字段互相代替。

AgentRun 状态：queued → running → completed/partial/failed/cancelled/interrupted；需要澄清或登录时进入 waiting_user，暂停自动行动，恢复沿用原预算。新一轮追问产生新 run，并明确关联的目标版本。

采集状态沿用现有 starting/running/stopping/completed/completed_with_errors/failed/stopped/interrupted。退出码 0 不等于内容完整，只有实际记录数，不提供未知的平台总量。
