# Community Agent · 社区内容助手

**已正式采用富文本编辑，支持配图、文字颜色、背景色和字号。** 原5001服务及账号可继续使用，详情见 [图文编辑说明](docs/rich-media.md)。Markdown基线保留在标签 `markdown-phase1`，初版试用过程保留在experiment/rich-text分支。

面向技术学习与项目交流的社区：发帖、评论、收藏，上传资料生成发布草稿，通过助手检索社区内容并获得带引用的回答。

**当前状态：阶段 0、1 已实现，支持账号权限、私有草稿、Markdown 帖子、标签、发布编辑、版本历史及软删除。** 互动、资料导入和助手功能尚未实现。旧学籍代码保留在 `app/`，社区代码使用独立 `community/` 包。

本地入口：http://127.0.0.1:5001/ 。安装、迁移、启动、管理员创建和测试命令见 [阶段 0 实施与运行说明](docs/community-phase0.md)。

发帖使用方式、双用户权限与版本冲突验收见 [阶段 1 实施与验收说明](docs/community-phase1.md)。

## 第一版方案

见 [社区第一版实现方案](docs/agent-design.md)。这是当前实施依据，已替换原学籍 Agent 设计。

第一版闭环：注册登录 → 发布帖子与评论 → 上传资料生成私有草稿 → 编辑确认发布 → 助手检索公开帖子并引用回答。

暂不做推荐算法、私信、支付、手写识别或自动发布。Agent 不直接修改数据库，资料整理使用固定工作流，社区问答使用受限的检索工具。

## 现有代码如何处理

- 复用并调整：Flask、SQLAlchemy、登录与 CSRF、私有文件、后台任务、DeepSeek 客户端、预览确认和变更记录的实现经验。
- 重建社区业务：用户角色、帖子及版本、评论、收藏、举报、来源关系、内容检索和引用校验。
- 学籍模型、成绩规则和数据库脚本是历史代码，不能直接改表名冒充社区模型。
- [原项目审查](docs/review-2026-09-16.md)与[学籍 Agent 实施记录](docs/agent-implementation.md)保留为历史记录。

## 重命名说明

项目目录已从 `student-management-agent` 改为 `community-agent`。请在编辑器中重新打开新目录，并选择 `.venv-dev/Scripts/python.exe`。

旧 `.env.agent`、Docker Compose 名称、MySQL 数据库和数据卷保留，用于保存历史学籍环境。社区服务现使用 `run_community.py` 或 `tools/start_community.ps1`；旧 `tools/start_local.ps1` 启动的仍是学籍系统。

社区已使用独立配置 `.env.community`、数据库 `community_agent` 和独立数据卷，不对旧库执行替换或清表。使用现有可运行的 `.venv-dev/Scripts/python.exe` 和 `python -m pip`；旧 `.venv` 已失效，旧激活脚本或命令启动器可能包含原路径。

示例账号文件仍在 `instance/demo-login.txt`，仅适用于旧学籍服务。原文、密钥、日志和演示密码都不应提交 Git。
