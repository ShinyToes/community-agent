# 社区阶段 0：独立底座与身份认证

日期：2026-09-17。此文记录阶段 0 的交付。后续阶段 1 也已完成，最新功能与验收见 [阶段 1 说明](community-phase1.md)；下文测试数量和后续事项保留为阶段 0 的历史记录。

## 已实现

- 独立 `community/` 应用包、SQLAlchemy 元数据和 `run_community.py` 入口。旧 `app/`、`config.py`、`run.py`、数据库和文件保留。
- `.env.community` 配置使用独立变量名、随机密钥与数据库密码。正式运行仅允许 MySQL 数据库 `community_agent`，拒绝旧学籍库。SQLite 只允许在显式测试配置中使用。
- 独立 Compose 项目 `community-agent`、数据卷 `community-agent_community_mysql_data`、本地数据库端口 13307。Web 绑定 127.0.0.1:5001。
- Alembic 初始迁移创建用户、身份操作审计、共享限流计数表。应用启动不自动建表；迁移入口独立、可重复执行。
- 注册、登录、POST 退出、本人身份查询、管理员页面权限检查。普通注册只能获得 `member`；管理员由本地维护命令创建。
- 用户名规范化与唯一约束，scrypt 密码哈希，CSRF 与登录后令牌轮换，独立会话 Cookie，12 小时会话期限，逐请求停用账号检查。
- 基于数据库原子操作的注册/登录固定窗口限流：默认同一来源 IP 每 10 分钟注册最多 10 次、登录最多 20 次；不同进程共享计数。忽略客户端伪造的转发 IP 请求头。
- 统一错误响应与 request_id、安全响应头、就绪/存活检查、桌面与移动端页面。

`community/` 是方案目录建议的阶段性调整：它避免导入旧 `app/__init__.py` 时加载学籍配置和模型。后续社区服务、内容及 Worker 使用这一独立包扩展；不在同一个 SQLAlchemy 元数据中混入两套 user 表。

## 启动

在项目目录执行，IDE 解释器选择 `.venv-dev/Scripts/python.exe`：

```powershell
.\.venv-dev\Scripts\python.exe -m pip install -r requirements-community.txt
.\.venv-dev\Scripts\python.exe tools/setup_community.py
docker --context desktop-linux compose --env-file .env.community -f compose.community.yaml up -d --wait
.\.venv-dev\Scripts\python.exe -m community db-upgrade
.\.venv-dev\Scripts\python.exe run_community.py
```

先运行 Docker Desktop。初始化脚本不会覆盖已有 `.env.community`。开发服务关闭 debug，只供本机访问。

Windows 后台启动也可用 `tools/start_community.ps1`。若系统阻止脚本运行，可使用上面的逐条命令，无需修改全局执行策略。日志位于 `instance/community/`。

打开 http://127.0.0.1:5001/ 后自行注册账号；不预置通用密码。旧 `tools/start_local.ps1` 仍启动学籍服务，不适用于社区。

停止数据库使用同一 Compose 配置的 `stop`；日常停止不要删除数据卷。停止 Web 可在前台按 Ctrl+C；后台进程 ID 在 `instance/community/web.pid`，结束进程前核对其命令行确为本项目 `run_community.py`。

## 本地维护

```powershell
# 交互输入并确认密码；不覆盖已有用户，也不把普通账号自动提升为管理员。
.\.venv-dev\Scripts\python.exe -m community create-admin --username admin

# 停用后已有会话在下一次请求时失效，处理原因进入审计。
.\.venv-dev\Scripts\python.exe -m community disable-user --username alice --reason "管理员处理原因"

# 可定期执行，清除过期的身份限流窗口。
.\.venv-dev\Scripts\python.exe -m community prune-auth-counters
```

维护命令要求操作系统层面的项目及数据库访问权限，审计中的 actor_id 为 null 表示本地维护动作。浏览器中的治理操作和更完整的审计目标模型在阶段 2 扩展。

使用 `python -m community` 可避免 Flask CLI 默认加载旧 `.env`；社区配置代码也不读取旧 AGENT_* 变量。

## 接口

| 接口 | 行为 |
| --- | --- |
| GET `/auth/register`、`/auth/login` | 表单页面 |
| GET `/auth/csrf` | 返回当前会话 CSRF token；JSON POST 通过 `X-CSRFToken` 传回 |
| POST `/auth/register` | 注册；JSON 成功为 201；表单成功为 303 跳转首页 |
| POST `/auth/login` | 登录；JSON 成功为 200；表单成功为 303 |
| POST `/auth/logout` | 退出；JSON 成功为 204 |
| GET `/auth/me` | 本人 id、用户名、角色；未登录为 401 |
| GET `/admin` | 管理员入口；普通用户为 403 |
| GET `/health/live` | 进程存活，不要求数据库可用 |
| GET `/health/ready` | 数据库可连接且 Alembic 版本为当前 head；否则 503 |

注册/登录字段为 username、password。用户名 3–32 位 ASCII 字母、数字、下划线，不区分大小写；密码 6–128 个字符。身份变更后重新获取 CSRF token。JSON 错误带 request_id，不输出 SQL 或连接口令。

## 验证结果

2026-09-17 实测：

- SQLite：24 项测试通过。
- MySQL 8.4：相同 24 项测试通过，在独立临时 Compose 项目 `community-agent-identity-tests`、13308 端口执行；结束后删除的仅为测试项目和测试卷。测试脚本后续运行使用此名称加随机后缀，避免共享测试项目。
- MySQL 主库：初始迁移连续执行两次成功；不执行清表或回滚。
- 自动化覆盖旧库拒绝、迁移升级/回滚/模型一致性、双用户隔离、密码哈希、重复注册及并发唯一性、CSRF、退出方法、Cookie、管理员越权、停用会话、共享限流、错误脱敏和旧路由隔离。
- 无头 Edge：真实注册、退出、重新登录、管理员越权拒绝、390px 移动端无横向溢出，通过；无 JavaScript 错误。使用的虚构验收账号已停用，截图位于 `instance/community/`。
- 现有 Python 环境 `pip check` 通过。
- 旧学籍 SQLite 回归：68 通过、5 项 MySQL 专属用例跳过；存在 754 条旧依赖/Query API 警告，不影响断言。没有连接旧 MySQL 运行测试。
- 实际服务 `/`、`/health/live`、`/health/ready` 均返回 200，数据库查询确认当前连接为 `community_agent`。

```powershell
.\.venv-dev\Scripts\python.exe -m pip install -r requirements-community-dev.txt
.\.venv-dev\Scripts\python.exe tools/run_community_tests.py
.\.venv-dev\Scripts\python.exe tools/test_community_mysql.py
# 需要已安装 Microsoft Edge 和运行中的 5001 社区 Web
.\.venv-dev\Scripts\python.exe tools/smoke_community_ui.py
```

社区测试独立于旧学籍测试配置，避免加载旧数据库设置。旧 `tools/run_tests.py` 显式排除社区目录。

## 保留与后续

实现前将 132 个源码/配置样例/文档文件归档至 `instance/snapshots/before-community-20260917.zip`，内含 HEAD 与逐文件 SHA-256 清单，已校验。没有覆盖旧 Git 修改或提交密钥。快照不包含虚拟环境、数据库、真实密钥或私有上传资料，这些仍保留在原位置。

下一阶段是帖子、不可变版本、草稿、标签、发布/编辑/删除及安全 Markdown。当前首页明确显示“社区筹备中”，尚无发帖、互动、文件导入、Worker、模型问答或完整治理页面。当前不用 DeepSeek，也不会产生模型调用费用。

登录限流是固定窗口/IP 限流，共用出口的用户共享额度，窗口边界允许短时突发；反向代理部署时需要明确可信代理并重新验证来源 IP。公网部署、HTTPS 和生产 WSGI 配置属于后续交付工作，不将 Flask 开发服务当作生产部署。

实现参考：[Alembic 迁移教程](https://alembic.sqlalchemy.org/en/latest/tutorial.html)、[Flask-WTF CSRF 文档](https://flask-wtf.readthedocs.io/en/1.2.x/csrf/)、[Flask 配置文档](https://flask.palletsprojects.com/en/stable/config/)。
