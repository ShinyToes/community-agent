# 审查发现

## 2026-09-17 阶段 1

- 公开内容当前片段随正文版本同步更新；草稿不生成片段，软删除移除片段。当前尚无检索/问答API，不宣称后续Agent验收完成。
- 数据库version条件更新在SQLite/MySQL均拒绝过期编辑，MySQL锁定用户后复核账号状态；发布操作回执使并发重复请求只创建一个新版本。
- MarkdownIt显式关闭原始HTML和图片，再经nh3允许列表清理；默认CommonMark允许HTML，不可直接用于不可信正文。官方文档链接已列在docs/community-phase1.md。
- MySQL TEXT容量不足以容纳30,000个中文字符，正文选MEDIUMTEXT，实际中文边界用例通过。

## 2026-09-17 阶段 0 已实施

- 独立 community 包避免 import app 时加载旧模型/配置；社区只允许名为 community_agent 的 MySQL，测试显式启用 SQLite。
- Docker Desktop 启动后 desktop-linux 引擎可用；正式项目 community-agent 的 MySQL 绑定13307；迁移已完成。临时测试项目使用13308，测试结束仅移除其容器/卷。
- 身份限流使用数据库原子 upsert，不能信任客户端 X-Forwarded-For；生产代理需后续明确部署边界。
- 实际测试与页面结果见 docs/community-phase0.md；前次环境缺项和旧实现描述仅为历史状态。
- 实现核对了官方 Alembic tutorial、Flask-WTF csrf、Flask config 文档（链接已列在阶段文档）。社区 CLI 显式禁止默认 dotenv 自动加载。

## 2026-09-17 社区环境核查

当前核查详见 docs/environment-check.md：.venv-dev 可用，pip check 通过；旧 .venv 引用不存在的 Python。Alembic 和检查的 Markdown 渲染/清理库缺失。Docker 客户端存在但引擎不可达，配置读取受到当前环境权限限制。13306/13307 未监听，社区配置和迁移尚未建立；当前代码仍为学籍应用。Git 存在大量未提交/未跟踪工作，正式改造前需要可恢复快照。

初始结构：Flask 蓝图、SQLAlchemy 模型、服务层、MySQL 存储过程/触发器、Jinja 页面。原目录包含虚拟环境和 Git 历史。本次仅修改复制项目。
## 已确认
- 学生详情/名单/API 缺少资源级权限；附件仅登录验证、路径由请求组成、存储在可公开读取的 static/uploads。
- 转专业申请使用表单学号，可冒用其他学生；拒绝审批未校验状态。
- 无 CSRF；next 可外部跳转；GET 登出；禁用用户的既有会话仍加载。
- set_audit_user 在批量循环内 commit，提前提交成绩；零权重被 or 替换；分数缺少有限性和范围校验。
- 重新选课直接激活旧记录，绕过容量/冲突校验；原存储过程恢复路径也跳过冲突。
- 附件服务内 commit 导致外围学生操作非原子；统计把零分当作无成绩且可能除零。
- 复制虚拟环境启动器引用原机器 Python 路径。全局 Python 可加载其依赖，但缺 Flask-WTF；创建独立 .venv-dev。
- 官方核对：Flask-WTF csrf 文档推荐全局保护和 AJAX token；SQLAlchemy session 文档说明 commit/flush 与事务边界。
## 补充审查
- get_status_badge 将任意状态插入 Markup，可能形成存储型 XSS，已改转义格式化；转专业页面姓名拼接 innerHTML 已改 textContent。
- 原成绩页 DataTables 分页会使未显示行不在表单提交中；改不分页并使服务端跳过未提交学生。原零分显示成空值也已修复。
- schema 的 user.related_id 原为 INT，与模型 VARCHAR(20) 不符；已修正新建脚本，避免丢学号前导零。
- 原 seed.py 自动重置统一弱密码并删除旧账号；改为显式创建单账号，不覆盖、不删账号、不显示密码。
- 新分数规则：缺少正权重分项时不生成总评；零权重有效；总评或补考达到60记已通过，缺考未通过，缓考在修。绩点仍以原总评为准，校级补考/重修政策需后续确认。
- SQL 与 ORM 的唯一约束、学生专业和班级一致性纳入修复；具体 MySQL 触发器/并发行为仍待独立实例测试。
## Agent 设计轮次（仅文档）
- 第一条导入链路默认成绩表；CSV/XLSX 优先，文字 PDF 和扫描件分阶段纳入，不把扫描识别当作现有能力。
- grade_validation 已可复用，但批次保存、绩点及 enrollment 状态仍在 grade_bp，设计先抽共享业务服务；enrollment_service 会 commit，不适合嵌入导入大事务。
- file_service 只允许已有 student/major_change 等关联记录，设计新增独立 document/import_batch，而不绕过旧接口授权。
- 查询设计为授权工具 + 参数化 ORM，不开放任意 SQL；不为结构化学籍数据额外引入向量库。
- 官方核对：DeepSeek JSON Output 仍需处理空输出/截断和业务 schema；pypdf 不提供 OCR。Function Calling 旧地址超时，改跟随 JSON 页的 Tool Calls 链接。
用户已确认多种文档需求；最终方案首批建议学生名单、成绩表、课程/开课表、奖惩记录，成绩表仅作为详细流程样例。Tool Calls 官方链接再次超时，未据此断言具体模型能力，留待实现时验证。
## 实施进度
历史学籍阶段记录；当前项目已在后续轮次更名 community-agent，社区方案见 docs/agent-design.md，下列中间进度不作为当前状态。
- 用户确认沿用 DeepSeek，要求准备本地独立 MySQL。
- 启动已安装 Docker Desktop；新建 compose 项目，只绑定127.0.0.1:13306；随机口令写入忽略文件，未输出。
- 新库初始化遇到06脚本 SQL_SAFE_UPDATES，修复为暂存/恢复设置后完成；已建 Agent 增量表和虚构演示业务数据。
- 已完成多Profile预览/确认/来源日志、只读工具、会话修改草稿、后台Worker和页面。扫描识别容器构建中。
- 60项隔离测试通过（47项原测试+13项新增），真实MySQL测试运行中；真实DeepSeek尚无密钥，不声称验证真实模型效果。

Color picker: previous frontend and backend limited colors to presets. Custom colors require validated HEX and nonce-authorized generated stylesheet to preserve strict CSP.
