# 社区实现前环境核查

核查日期：2026-09-17。本轮先核查环境，尚未实施社区业务、安装依赖或修改数据库。

## 技术栈

后端语言为 Python，Flask 负责 HTTP 路由，SQLAlchemy/PyMySQL 访问 MySQL，Jinja 渲染页面；前端使用 HTML/CSS/JavaScript。独立 Worker 也可以用 Python，不需要增加一种后端语言。按现有方案，第一版不要求 Node 构建环境、Redis、向量库或本地大模型/GPU。

## 实测结果

| 项目 | 结果 |
| --- | --- |
| `.venv-dev/Scripts/python.exe` | Python 3.13.15，能够运行 |
| `.venv/Scripts/python.exe` | 无法启动，引用不存在的旧 Python 路径 |
| Python 依赖 | Flask 3.1.3、SQLAlchemy 2.0.54、Flask-SQLAlchemy 3.1.1、Flask-Login 0.6.3、Flask-WTF 1.3.0、PyMySQL 1.2.0、pypdf 6.18.1、httpx 0.28.1、pytest 9.1.1 导入通过 |
| 依赖一致性 | `.venv-dev/Scripts/python.exe -m pip check` 通过 |
| 迁移 | 未安装 Alembic，未建立 `migrations/` |
| Markdown | 未安装检查的 Markdown/markdown-it-py 渲染库和 bleach/nh3 清理库；实施时每类选一种即可 |
| Docker | 客户端 29.7.2、Compose v5.5.0 可运行；引擎命名管道不存在，无法查询容器 |
| Docker 配置读取 | 当前执行环境读取用户 Docker 配置被拒绝，需在启动/联调时另行核实；不能据此断言 Docker 未安装 |
| MySQL 端口 | 本地 13306、13307 均未监听；尚未验证数据库认证或查询 |
| 社区隔离配置 | `.env.community` 不存在；现有 config.py 加载 `.env.agent`，Compose 仍为学籍项目和旧库 |
| DeepSeek | 当前进程环境变量中存在 API Key；未输出密钥，未验证其有效性或余额 |

IDE 解释器应使用本项目 `.venv-dev/Scripts/python.exe`。调用工具使用 `python.exe -m pip`、`python.exe -m pytest`，避免目录移动后旧入口脚本引用过期路径。

## 实施顺序

1. 为当前旧实现建立可恢复快照：Git 当前存在大量修改和未跟踪文件，HEAD `a685a0e` 并未覆盖现状。快照不应纳入密钥、虚拟环境、私有上传资料。
2. 补齐 Alembic；内容发布阶段补充 Markdown 渲染与 HTML 清理依赖。
3. 准备独立 `.env.community`、Compose 项目和数据卷，以 127.0.0.1:13307 运行新 MySQL 数据库 `community_agent`；保留旧库和资料。
4. 实施方案阶段 0：社区应用入口、配置隔离、用户角色、注册登录、CSRF、版本迁移；验证不会连接旧库。
5. 再按阶段 1–5 实现发布、互动、资料草稿、问答和交付评测。DeepSeek 配置和真实调用在模型功能接入时核实，不阻塞基本社区开发。

本次没有启动旧应用、执行旧初始化脚本、连接数据库或调用收费模型 API。环境导入通过不代表社区功能已实现或通过验收。
