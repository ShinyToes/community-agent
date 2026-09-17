# 可回退的富文本试用版

后续更新：用户已确认采用富文本，正式版本加入图文能力并部署到5001，见 [图文编辑说明](rich-media.md)。本文保留最初试验阶段的对比及验证记录。

## 对比入口

- Markdown 基线：`main`，首次提交 `77c2fdc`。原本机目录 `community-agent` 和 http://127.0.0.1:5001/ 保持不动。
- 富文本试用：`experiment/rich-text`。本机目录 `community-agent-richtext`，访问 http://127.0.0.1:5002/ 。
- 试用版使用独立13309 MySQL、独立Compose项目/数据卷和独立会话Cookie，需要重新注册试用账号。不会使用原社区的账号或帖子。

进入「写帖子」，默认打开富文本编辑器。直接选中文字，点击标题、加粗、斜体、列表、引用、代码块或表格按钮即可看到效果；支持撤销/重做。点击右上方「Markdown」即可比较原编辑方式。

## 如何回退

1. 只想使用原版本：回到 http://127.0.0.1:5001/ 即可，无需恢复数据库或改代码。
2. 只想切换当前编辑方式：点击编辑页「Markdown」，也可以使用 `/posts/new?editor=markdown` 打开。
3. 在此独立源码目录切回基线：确认试验修改已提交，再执行 `git switch main`。没有使用强制重置或删除历史的命令。

试用分支尚未合并到main。原项目另有私有快照 `instance/snapshots/markdown-before-richtext.zip`，不上传到GitHub。

## 本地启动

本机会话已启动，无需重复执行。新环境先创建Python虚拟环境并安装 `requirements-community.txt`。初始化配置后将 `.env.community` 中的数据库连接端口设置为13309，再执行：

```powershell
$env:COMMUNITY_MYSQL_PORT = '13309'
docker --context desktop-linux compose --env-file .env.community -f compose.community.yaml -p community-agent-richtext up -d --wait
python -m community db-upgrade
python run_richtext.py
```

本机本次复用了相邻 `community-agent/.venv-dev/Scripts/python.exe`；运行目录必须为试用项目。不要使用旧的 `tools/start_community.ps1` 启动本试用服务，该脚本用于5001基线。

## 构建与边界

富文本基于Tiptap 3.31.3，资源已打包在本地 `community/static/rich-editor.js`，浏览器不从第三方CDN加载。修改 `frontend/rich-editor.js` 后：

```powershell
cd frontend
npm ci
npm run build
```

Node仅用于重新构建前端，已提交的bundle可直接由Flask服务。npm锁文件固定依赖版本，第三方许可证见 `frontend/THIRD_PARTY_LICENSES.txt`。

数据仍保存为Markdown，沿用原发布、版本历史、权限和服务器清理逻辑，没有数据库模型变更。打开已有内容时从服务器的安全预览导入；仅切模式或保存未编辑内容，不改写原Markdown。实际富文本编辑会重新序列化，空行、语法选择、代码语言标记等可能变化；不承诺任意Markdown无损往返。图片、字体颜色、合并单元格等不在本次试用范围。

Markdown适配层目前在[Tiptap官方文档](https://tiptap.dev/docs/editor/markdown)中标为beta，因此保留为独立试验分支；未将其当作已完成的正式迁移。

## 已验证

- 浏览器：加粗、标题、表格显示、双向模式切换、未修改Markdown逐字保留、保存后重载、发布与删除、390px手机布局；无JavaScript错误。
- 原37项SQLite社区测试通过；本次未改变后端事务/模型，没有重复运行MySQL并发套件。
- 依赖安装时npm审计结果为0项已知漏洞；不代表不存在未知问题。
- 桌面/手机截图在私有 `instance/community/richtext-desktop.png`、`richtext-mobile.png`。
