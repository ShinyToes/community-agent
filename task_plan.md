# Community Agent 项目计划（含历史学籍阶段）

## 当前任务：正式采用富文本，增加图片与文字颜色

- 保留Markdown基线tag与独立功能分支：complete
- 富文本结构持久化、图片权限与增量迁移：complete
- 图片上传、颜色/背景/字号/基础排版及编辑恢复：complete
- SQLite/MySQL与浏览器验证：complete
- 备份部署到原5001服务、合并main及运行说明：in_progress（部署/文档已完成，待推送）

## 当前任务：GitHub基线与富文本可回退试用

- 清理并检查发布源码、独立仓库main基线推送：complete
- experiment/rich-text分支、Tiptap本地资源及模式切换：complete
- 独立5002服务/13309数据库/会话隔离：complete
- 浏览器与37项SQLite测试、回退说明：complete
- 提交与推送试验分支：complete（远程main与experiment/rich-text均已核对）

## 当前任务：阶段 1 内容发布

- 阶段0源码快照、需求与现状核对：complete
- 帖子/版本/标签/操作回执/内容审计及迁移：complete
- 私有草稿、发布、编辑冲突、软删除、安全预览与页面：complete
- SQLite/MySQL权限、并发、幂等测试与浏览器验收：complete
- 数据库升级、运行文档及交付：complete

结果：SQLite 37 passed；临时MySQL 37 passed；双用户浏览器验收通过。正式库已备份并升级到0002_posts，5001服务已重启，用户账号保留。当前实施记录为 docs/community-phase1.md，下一阶段为阶段2。

延续用户偏好：密码至少6位；表单错误在原页面提示，不跳通用错误页。保留现有账号及旧系统数据。

## 当前进展：社区阶段 0 已完成（2026-09-17）

授权：用户要求开始逐步实现。本轮完成社区底座、迁移和身份认证；阶段 1–5 仍待逐步推进。
- 快照、独立配置与新 MySQL：complete
- 社区入口、角色、注册登录、CSRF、限流、停用会话：complete
- Alembic 升级/回滚、SQLite/MySQL、浏览器验证：complete
- 运行说明、旧测试回归、实际服务健康核验：complete

验收结果：社区 SQLite 24 passed，独立 MySQL 24 passed；浏览器注册/登录/退出/越权/移动端通过；旧测试 68 passed / 5 skipped。服务运行在 http://127.0.0.1:5001/，实际连接 community_agent；详见 docs/community-phase0.md。

## 当前任务：实施前环境核查（2026-09-17）

用户要求根据社区方案逐步实现，先确认环境及后端语言。本轮范围为环境核查。
- 阅读方案、现有实现和工作区状态：complete
- 核查 Python、依赖、Docker、数据库端口及配置：complete
- 记录缺项和阶段 0 实施入口：complete
- 社区阶段 0–5：pending，尚未开始编码

结果见 docs/environment-check.md。已发现旧虚拟环境失效、Alembic/Markdown 相关依赖缺失、Docker 引擎不可达、社区独立配置尚未创建。首次文档读取因 PowerShell 默认编码显示乱码，改用 UTF-8 后正常；未改动原方案文件。

## 当前任务：社区第一版方案与项目改名（2026-09-16）

授权：替换原设计方案、重命名项目；本轮不实现社区业务，不替换旧数据库。
- 核对现有目录和运行进程：complete
- 项目目录改为 community-agent：complete
- 覆盖 docs/agent-design.md、更新 README：complete
- 核验路径、文档与迁移后基础环境：complete

当前实施依据是 docs/agent-design.md；下文为历史任务，不代表社区已实现。

授权：审查并优化复制项目；需要整体重建时提出具体方案申请，不自行重建。

## 阶段
- 架构、权限、数据操作和运行条件审查：complete
- 确定修复范围并实现：complete
- 隔离回归测试与结果审查：complete
- 交付问题清单、变更和限制：complete

约束：不读取展示 .env 密钥，不连接修改原实验数据库；优先保留可用代码；不新增 Agent 功能。

结果：保留框架并修复权限、事务、文件、成绩、选课入口和初始化；47 项隔离测试通过。MySQL 实例不可用，真实 SQL/触发器/并发验证和学校业务口径列为后续事项，不声称已验证。

## 新任务：Agent 设计方案（2026-09-16）

本轮授权仅设计，不新增运行代码或操作数据库。此前“不新增 Agent 功能”约束属于审查轮次。
- 核对当前模型与能力边界：complete
- 设计导入、查询、权限与状态流程：complete
- 写入方案并检查文档链接：complete

用户补充：多种文档都需要。设计改为学生名单、成绩、课程/开课、奖惩四类 Profile 与多格式解析；成绩仅为详细样例。

## 实施任务（2026-09-16）

授权：用户要求按设计实施；增加来源记录和会话修改草稿，确认才写入。保留原实验目录与数据库。
- 共享业务服务、来源/批次/变更模型及增量迁移：complete
- 多业务导入、解析 Worker、预览确认：complete（第一版；可视化表头映射等差异见实施记录）
- 查询 Agent、会话修改草稿与界面：complete
- 自动测试、独立 MySQL/模型/OCR 环境验证：complete（扫描识别未达到免修正标准，保留失败证据）
- 文档、限制和交付核验：complete

环境结果：已按用户回复接入 DeepSeek，准备并启动独立本地 MySQL、Web 和 Worker。SQLite 68通过/5跳过，MySQL 73通过，真实模型三类任务及浏览器流程通过。扫描 PDF 有误识别；原设计大样本评测和扩展项未完成，不宣称全部验收通过。详见 docs/agent-implementation.md。

## 社区阶段 0 实施（2026-09-17）
用户已授权开始实现。继续使用 planning-with-files 记录进展。
- 旧源码快照与校验：complete
- 独立配置、应用入口、迁移、注册登录：complete
- SQLite/MySQL 隔离与权限测试、运行说明：complete

实施中问题：pip 默认网络受限，批准联网后安装 Alembic；Docker 默认沙箱端点不可达，启动 Docker Desktop 并通过 desktop-linux 上下文运行独立项目；首轮 pytest 缺父临时目录，新增测试入口自动建立目录；测试包名称与 community 应用冲突，移除测试目录 __init__.py 并使用 importlib 模式。均已修正并验证，没有遗留阻塞。

