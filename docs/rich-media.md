# 富文本图文编辑

2026-09-17：用户确认采用富文本，已升级原 http://127.0.0.1:5001/ 社区。继续使用原账号，无需重新注册。

## 使用

1. 点击「写帖子」，直接在正文区域输入文字。
2. 选中文字后设置加粗、斜体、下划线、删除线、字体颜色、背景色和字号。颜色提供8种、背景色4种，字号为14/16/20/24/32；选择默认可取消对应样式。
3. 点击「插入图片」选择本机图片，或将图片拖入正文、粘贴剪贴板图片。一次处理一张，上传期间暂停保存，避免保存到未完成的图片。
4. 点击正文中的图片，再选择50%/75%/100%宽度。选中图片后按Delete/Backspace可移除。
5. 支持标题、列表、编号、引用、代码块、表格及增行/增列/删除表格；保留撤销、重做和清除文字样式。
6. 保存草稿后可以重新打开继续编辑，发布后其他人看到相同的颜色和配图；历史版本保留该版排版与图片引用。

正文最多30,000个文字字符、12张图片。单张原始文件最多5MB，仅接受静态JPG/PNG/WebP，不支持SVG、GIF、动画和外链图片。解码像素最多1600万，最长边会缩至2400，重编码为WebP以移除原始元数据。

正文不自动保存。默认使用正式富文本编辑器，不再提供会丢失颜色/图片的Markdown编辑切换。已有Markdown帖子仍能显示，打开后可在富文本中修改；原版本继续保留。

## 图片权限

- 上传后仅本人可读取；草稿中的图片也仅本人可读。
- 只有图片被某篇**当前公开版本**引用时，访客才能读取。
- 修改帖子移除图片、隐藏或删除帖子后，原图片地址不再向访客开放，除非仍被另一篇公开帖子使用。
- 作者可继续读取自己上传的图片，以查看旧版本。管理员没有默认读取其他人私有图片的权限。
- 即使图片已经公开，也不能冒用其他用户的上传图片引用，服务端保存时检查所有权。
- 图片位于 `instance/community/images/`，不在静态目录，下载接口每次重新检查权限并设置no-store。

图片移出正文后不会立即从磁盘物理删除，历史版本仍可能引用。未采纳的上传也保持私有；目前没有自动清理任务或用户素材管理页。

## 保存与显示

新增迁移 `0003_rich_media`：post_revision新增rich_content JSON，新增image_asset及revision_image。JSON保存受限的编辑器节点及样式，服务端验证并规范化后写入，不信任前端HTML。

文字、颜色、字号、图片节点和图片关系与帖子版本在同一事务中保存。markdown字段为旧版正文或新富文本的可检索文字摘要；正文显示优先读取结构化内容。已有Markdown版本不批量改写。

服务端只生成允许的HTML标签和预定义CSS类；不接收任意style/script或图片URL。字体样式也使用CSS类，不放宽CSP的内联样式限制。富文本前端已不依赖实验性Markdown转换层。

写入接口POST `/posts`、PATCH `/posts/{id}`可传 `rich_content`。保存已有富文本版本时必须提供rich_content，以防旧客户端用纯文本覆盖图文格式。标题、标签、base_version和operation_key语义保持不变。

图片POST `/images`使用multipart字段 `file` 和CSRF令牌，成功返回id、url、宽高；GET `/images/{id}`按当前引用权限返回WebP。图片上传按来源IP每10分钟最多30次。

## 部署、验证与版本

原5001社区部署目录仍为 `community-agent`，保留原.env.community和13307数据库；GitHub发布源码在相邻 `community-agent-richtext` 仓库维护。本次复制部署只涉及社区源码、前端、迁移、测试和文档，不改原目录的Git历史、旧学籍代码或密钥。

部署前备份：原目录私有 `instance/snapshots/before-rich-media-20260917-154315.zip` 和 `database-before-rich-media-20260917-154315.sql`。账号关键字段摘要、帖子及版本数量在升级前后核对一致。

- SQLite完整50项通过；后续补充重复图片计数/节点结构限制后，相关13项再次通过。
- 独立临时MySQL 8.4完整50项通过；测试容器和测试卷已清理。存在1条pytest缓存目录权限警告，不影响测试断言。
- 浏览器在隔离5002和原5001服务验证：字色/背景/字号、图片上传/宽度、保存重载、发布、历史、草稿私有、删除后图片拒绝访客、手机布局；均通过，无JS错误。
- 原5001账号、帖子及历史版本未被替换。浏览器验收只使用虚构帖子和账号，成功验收后删除测试帖并停用该账号。

```powershell
.\.venv-dev\Scripts\python.exe -m pip install -r requirements-community.txt
.\.venv-dev\Scripts\python.exe -m community db-upgrade
.\.venv-dev\Scripts\python.exe run_community.py

# 浏览器验收，需本机已有Edge和运行中的5001服务
$env:COMMUNITY_UI_BASE='http://127.0.0.1:5001'
.\.venv-dev\Scripts\python.exe tools/smoke_rich_media_ui.py
```

前端源码位于frontend/rich-editor.js。使用 `npm ci` 和 `npm run build` 重新生成已提交的bundle；浏览器从本机加载，不依赖外部CDN。

Markdown基线保存在Git标签 `markdown-phase1`，初版试验保留在experiment/rich-text。回看旧代码不会自动恢复数据；不要直接降级数据库清除rich_content和图片表。旧版本不具备图文显示能力。

实现参考：[Tiptap颜色扩展](https://tiptap.dev/docs/editor/extensions/functionality/color)、[图片扩展](https://tiptap.dev/docs/editor/extensions/nodes/image)、[Pillow图像解码](https://pillow.readthedocs.io/en/stable/reference/Image.html)。
