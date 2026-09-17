# 阶段 1：帖子与内容发布

2026-09-17 已完成。当前入口：http://127.0.0.1:5001/ 。继续使用原社区账号，密码最低 6 位。

## 可以做什么

- 登录后点击顶部「写帖子」，填写标题、Markdown 正文和标签。
- 正文输入暂停约 350 毫秒后自动刷新 Markdown 预览；打开已有帖子时自动预览，也可点击「刷新预览」立即重试。预览不会自动保存或发布。
- 「保存草稿」只保存为本人可见的内容；从「我的内容」继续编辑。
- 「发布帖子」使内容对访客和其他用户可见；首页按发布时间显示公开帖子。
- 已发布帖子可以由作者编辑，按钮明确显示「更新公开内容」。
- 在帖子详情点击「版本历史」，查看每次保存的标题、正文、标签与修改说明；历史仅作者可见。
- 删除帖子前弹窗确认，删除后从首页、本人列表和详情中消失；当前不提供恢复入口。
- 同时打开两个编辑窗口时，旧版本提交会被拒绝。错误留在编辑页，输入不清空，可在新窗口查看最新内容。

写作限制：标题 1–120 个字符，非空正文最多 30,000 个字符，最多 5 个标签，每个标签 1–24 个字符。标签用英文或中文逗号分隔，保存时统一大小写、去重排序。修改说明最多 500 个字符。草稿也要求非空标题和正文；目前没有自动保存，离开未保存的编辑页会触发浏览器提醒。

Markdown 禁止执行原始 HTML，预览和详情使用同一套服务器渲染及允许列表清理。第一版支持文字内容，不支持图片嵌入；原始 HTML 会作为普通文字显示。

## 手动验收

建议使用普通窗口登录账号 A，无痕窗口登录账号 B；另开未登录窗口检查访客访问。

| 步骤 | 预期 |
| --- | --- |
| A 写帖子，输入 Markdown 正文后稍作停顿 | 自动显示排版，代码块不会执行 |
| A 保存草稿，在「我的内容」找到它 | 显示草稿；首页不出现 |
| 将草稿详情 URL 复制到 B/未登录窗口 | 返回 404，不显示正文；管理员也没有默认访问别人的草稿权限 |
| A 点击发布，B 刷新首页 | 能看到并阅读帖子，B 看不到作者编辑按钮 |
| B 直接访问 A 的 `/posts/编号/edit` 或 `/posts/编号/revisions` | 返回 404，不能编辑或读取历史 |
| B 发布自己的帖子 | 两个账号均可独立创作 |
| A 打开同一帖子的两个编辑标签页 | 两页都带打开时的版本 |
| A 在第一个窗口修改并保存，再在第二个窗口修改并保存 | 第二个窗口出现冲突提示、保留输入，不覆盖第一个窗口的修改 |
| A 查看版本历史 | 旧正文和旧标签仍保留，最新修改说明可见 |
| A 删除，先取消，再确认 | 取消不影响帖子；确认后原 URL 返回 404，首页不再展示 |

冲突发生后，请保留当前输入，打开最新帖子核对差异，再基于最新编辑页手动合并。当前不自动合并、覆盖或恢复历史版本。

## 接口

GET 请求带 `Accept: application/json` 获取数据；不带该请求头时页面接口渲染 HTML。所有写入和预览都要求登录、JSON 和 `X-CSRFToken`。

| 接口 | 行为 |
| --- | --- |
| GET `/`、`/posts` | 公开帖子列表；每页最多 20 条；`/` 仅 HTML |
| GET `/me/posts` | 本人的草稿和公开帖子，每页最多 20 条 |
| GET `/posts/new` | 新建编辑页 |
| GET `/posts/{id}` | 当前可见版本 |
| GET `/posts/{id}/edit` | 本人编辑页 |
| GET `/posts/{id}/revisions` | 本人历史版本，每页最多 20 条 |
| POST `/posts` | 创建私有草稿；201 |
| PATCH `/posts/{id}` | 保存新版本；保持原 draft/published 状态 |
| POST `/posts/{id}/publish` | 将草稿发布为公开帖子 |
| DELETE `/posts/{id}` | 软删除；返回操作回执 |
| POST `/posts/preview` | 安全 Markdown 预览，不保存数据 |

创建和编辑字段为 `title`、`markdown`、`tags`（字符串数组）、可选 `change_reason`。每次写操作带 UUID `operation_key`；编辑、发布和删除还带整数 `base_version`。拒绝客户端指定作者或状态等不支持字段。预览只传 `markdown`，不用操作标识。

同一用户以相同操作标识、相同内容重试，返回原回执，不新增帖子或版本；同一标识换内容则返回 409。旧版本编辑返回 409；越权内容统一 404；未登录写入返回 401。写请求使用共享数据库计数限流，同一来源 IP 每 10 分钟最多 60 次（含失败请求和重试），超限返回 429。

## 实现与迁移

- 新迁移 `0002_posts` 增加 post、post_revision、tag、post_tag、content_chunk、post_operation；扩展现有 audit_event，保留原用户审计。
- 正文写入不可变版本，post 指向当前版本；标签也进入每版 JSON 快照。MySQL 正文使用 MEDIUMTEXT，支持 30,000 个中文字符。
- 编辑通过 `UPDATE ... WHERE version = base_version` 原子占用版本；MySQL 同时锁定当前操作用户，以复核停用状态。SQLite 也依靠版本条件拒绝竞争写入。
- 新版本、当前版本指针、标签关系、当前公开检索片段、审计与操作回执在一个事务中提交；失败整体回滚。
- 公开片段在发布/编辑时同步更新；草稿不建片段，删除时清除片段。搜索和 AI 问答接口在后续阶段实现。
- 隐藏状态已纳入模型和访问限制，作者不能通过编辑或再次发布绕过；管理员隐藏/恢复 UI 属于阶段 2。
- 首页使用签名 `(published_at, id)` 游标，本人列表按 id 降序分页。当前时间显示 UTC，编辑不会把旧帖子重新顶到首页。

迁移前已将社区库备份到 `instance/snapshots/community-before-phase1-20260917-144752.sql`，阶段 0 源码快照为 `before-phase1-20260917-143149.zip`。备份含账号数据，只保存在被 Git 忽略的私有目录。正式库只执行升级，现有账号保留；旧学籍库未操作。

安装与启动方式延续阶段 0：

```powershell
.\.venv-dev\Scripts\python.exe -m pip install -r requirements-community.txt
.\.venv-dev\Scripts\python.exe -m community db-upgrade
.\.venv-dev\Scripts\python.exe run_community.py
```

已有后台服务需要重启以加载代码；当前本机会话中的 5001 服务已完成重启。

## 验证结果

- SQLite：37 项通过，包含阶段 0 的 24 项和新增 13 项内容测试。
- 独立临时 MySQL 8.4：同样 37 项通过；临时容器及卷已清理，正式社区库保留。
- 测试覆盖草稿隔离（包括管理员）、双账号所有权、历史版本/标签保留、幂等创建/发布/编辑/删除、并发编辑、并发重复发布、隐藏状态、XSS、完整中文长度、分页、限流、注入故障回滚以及已有用户跨迁移保留。
- 无头 Edge：两个账号分别发布、草稿隔离、Markdown 预览、两个窗口冲突并保留输入、历史查看、删除取消/确认、390px 手机布局全部通过，无 JavaScript 错误。
- 浏览器验收的虚构帖子已软删除，验收账号已停用；没有替换用户自己发布的内容。
- 首页、`/posts`、`/health/ready` 返回 200，实际数据库版本为 `0002_posts`；Python 编译、JavaScript 语法和 pip 依赖检查通过。

```powershell
.\.venv-dev\Scripts\python.exe tools/run_community_tests.py
.\.venv-dev\Scripts\python.exe tools/test_community_mysql.py
# 需要 5001 社区服务和 Microsoft Edge
.\.venv-dev\Scripts\python.exe tools/smoke_posts_ui.py
```

浏览器截图位于 `instance/community/post-editor.png`、`post-published.png`、`post-conflict.png`、`post-mobile.png`。

本阶段没有实现评论、点赞、收藏、搜索、举报处理、文件导入或 AI 助手。下一阶段为社区互动与治理。

安全实现参考：[markdown-it-py 不可信内容处理](https://markdown-it-py.readthedocs.io/en/latest/security.html)、[nh3 HTML 清理](https://nh3.readthedocs.io/en/latest/)。
