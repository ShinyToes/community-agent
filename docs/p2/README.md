# P2：条件检索与原文证据

2026-09-20：P1 复核通过后完成 P2.1—P2.5。P1 的 19 项测试及真实导入检查通过，P1/P2 联合验收 54 项测试通过。

P2 为后续智能在线搜索提供可复用工具：爬虫得到内容并自动导入后，助手可以调用这些工具过滤、阅读和引用。当前仍只读取已导入内容，不执行网站搜索，不调用 LLM；最终交互不要求用户手工处理 JSON。网页工具装配与对话入口属于后续阶段。

## 可调用接口

外层包 `community_research.knowledge.search.SearchService` 提供统一调用入口：

```python
from community_research.knowledge import KnowledgeStore
from community_research.knowledge.search import SearchService

tools = SearchService(KnowledgeStore())
result = tools.call("search_posts", {
    "platform": "tieba",
    "all_terms": ["cs", "饰品"],
    "fields": ["title", "body"],
    "limit": 20,
})
```

三个工具为 `search_posts`、`search_comments`、`read_evidence`。参数错误通过统一 error 结构返回；成功无匹配、尚未导入、来源失效与旧游标失效分别处理。

## 检索规则

- `all_terms` 全部命中、`any_terms` 至少一个命中、`exclude_terms` 任意命中排除；三组条件之间为 AND。每组至多 8 项，每项 trim 后 1—80 字符。
- 帖子字段可选 `title`、`body`，评论仅 `body`。评论不会因为原帖包含关键词而被算作命中；source_keyword、作者名和来源路径不参与匹配。
- Unicode casefold 后做连续子串匹配。`["cs", "饰品"]` 可匹配两词之间有其他文字的内容；单项 `"cs饰品"` 要求连续；不做别名扩展或语义相关性判断。
- `published_from`、`published_to` 必须带时区，采用左闭右开区间。时间未知记录排除并计数，计数范围是满足其他筛选条件的候选。
- `source_ids`、`task_ids` 可选，各至多 20 个，组合时取交集；task_ids 对应已登记来源的采集任务。历史文件没有任务 ID，不猜造任务。
- 评论可用 `post_ids`、`parent_id` 按标准内部实体 ID 过滤；不要填原网站帖子编号。可从搜索结果的 entity_id 获得。
- 同一实体在所选来源范围内选择最近采集的快照，然后做内容匹配；不会因为旧版命中就忽略新版不命中。选出的快照同时列出所有仍有效的支持来源。
- 最近采集版本按 observed_at、imported_at、snapshot_id 及 source_id 选择；来源声明的发布时间属于该出现记录。结果固定按标准发布时间降序、未知最后、entity_id 升序排列，不提供伪造的语义分数。
- limit 为 1—50，默认 20。下一页传回 next_cursor，其他参数不变。游标存储在数据库，绑定全部条件和索引版本；导入、来源删除/覆盖后拒绝旧游标，不静默跳页。

结果包含身份、快照、原网站 ID、来源 ID、命中字段及带证据 ID 的原文预览。预览每字段最多 400 字符，以首个命中附近为起点；相距很远的多个词可能不同时出现在预览内，可继续读取全文。无关键词列举时 matched_fields 为空，不把预览冒充词语命中。

## 证据读取

```python
evidence_id = result["items"][0]["snippets"][0]["evidence_id"]
evidence = tools.call("read_evidence", {
    "evidence_ids": [evidence_id],
    "include_context": True,
})
```

证据登记在 SQLite，ID 绑定 snapshot_id、field、start、end，可跨进程读取。返回 quote 严格等于原始字段 `[start:end]`，偏移按 Python Unicode 码点，大小写转换扩展字符也不会改变原文定位。空字段不创建证据。

- 每次读取 1—20 个 ID，每片最多 2000 字符；长文给出 previous_evidence_id、next_evidence_id。
- 单次响应预留元数据空间，将条目 JSON 累计限制为 20000 字符，并最终校验完整响应的紧凑 Unicode JSON 不超过 24000 字符（CLI 美化缩进不计入协议预算）；超过预算的条目列在 pending_evidence_ids，下一次读取。
- `include_context=true` 对评论返回帖子和父评论的关系状态、独立证据 ID。为控制响应大小，上下文文本通过再次调用 read_evidence 读取，不混入评论自身 quote。
- 所属帖子或父评论缺失返回 unresolved；父评论必须属于同一帖子。上下文选择读取时最新有效快照，其证据 ID 随后固定绑定该版本。
- 读取前重新验证来源；删除最后来源后 evidence_unavailable，不改指向新正文。不存在或未登记的 ID 为 evidence_not_found。
- 本层验证 ID 已登记且内容有效；“是否本轮实际返回并读取”的授权和引用集合由 P3 Harness 执行，本层不冒充会话控制。

## 状态与范围

统一返回 schema_version、status、items、coverage、error。coverage 明示 local_imported_data、来源范围、索引版本、分页、未知时间排除数量及不完整来源。

- 无匹配且范围完整：empty；已停止任务、历史文件、部分导入或来源部分失效：partial，即使 items 为空也保留不完整范围说明。
- 未登记/未导入数据：not_imported；范围全部来源已失效：source_unavailable。
- 错误条件：invalid_arguments、unsupported_platform、stale_cursor、evidence_not_found、evidence_unavailable；极端情况下单个证据元数据过大返回 response_too_large，避免无限返回同一个待处理项。

P2 新增 evidence 与 search_cursors 两张附属表，幂等创建，保留 P1 模式及原数据。未复制原文到证据表，因此 P1 清除失效快照正文时不会留下另一份可读引用缓存。

## 本地命令与复核

在项目根目录执行；使用现有 editable 包，不新增依赖：

```powershell
.\MediaCrawler\.venv\Scripts\python.exe -m community_research tool search_posts --arguments docs/p2/query-posts.json
.\MediaCrawler\.venv\Scripts\python.exe -m community_research tool search_comments --arguments docs/p2/query-comments.json
.\MediaCrawler\.venv\Scripts\python.exe tools/verify_p2_data.py
.\MediaCrawler\.venv\Scripts\python.exe -m pytest tests/research --confcutdir=tests/research -p no:cacheprovider -q
```

证据 CLI 使用相同方式，将参数写入 UTF-8 JSON 文件后调用 `tool read_evidence --arguments <文件>`。工具错误退出码为 1。

真实验证见 [validation-report.json](validation-report.json)：57 帖子分页 9 页、149 评论分页 22 页，无重复或遗漏；AND 10 帖、OR 25 帖、连续词 2 帖、评论 cs 7 条；58 个原文切片核对通过，4 份来源哈希保持不变。数值只属于当前已导入数据。

目前每次检索会核验活动来源并在内存中过滤，适用于当前小规模本地数据；没有搜索缓存、向量索引、全站覆盖保证或在线质量评测。证据和游标附属表暂不自动清理，后续有规模需求再增加过期策略。
