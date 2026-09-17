"""Validate a bounded Tiptap document and render it without trusting supplied HTML."""
import re
from html import escape
from urllib.parse import urlsplit

from flask import abort, g, has_request_context
from markupsafe import Markup

FG = {'#172b2b': 'ink', '#b42318': 'red', '#b54708': 'orange', '#8a6500': 'gold',
      '#175c4b': 'green', '#175cd3': 'blue', '#6941c6': 'purple', '#667085': 'gray'}
BG = {'#fff3bf': 'yellow', '#d3f9d8': 'green', '#dbeafe': 'blue', '#fce7f3': 'pink'}
SIZES = {'14px', '16px', '20px', '24px', '32px'}


def compile_document(document):
    images = set()
    count = 0
    characters = 0
    image_count = 0

    def fail(message='正文包含不支持的格式，请调整后重试。'):
        abort(400, description=message)

    def text(value, limit=30000):
        if not isinstance(value, str) or len(value) > limit or '\x00' in value:
            fail()
        return value

    def node(value, depth=0):
        nonlocal count, characters, image_count
        count += 1
        if count > 5000 or depth > 24 or not isinstance(value, dict):
            fail('正文结构过于复杂，请减少嵌套或分段发布。')
        kind = value.get('type')
        if not isinstance(kind, str): fail()
        attrs = value.get('attrs') or {}
        if not isinstance(attrs, dict): fail()
        if kind == 'text':
            raw = text(value.get('text')); characters += len(raw)
            html = escape(raw)
            plain = raw
            normalized = {'type': 'text', 'text': raw}
            marks = value.get('marks', [])
            if not isinstance(marks, list) or len(marks) > 8: fail()
            valid_marks = []
            for mark in marks:
                if not isinstance(mark, dict): fail()
                name = mark.get('type'); ma = mark.get('attrs') or {}
                if not isinstance(name, str): fail()
                if not isinstance(ma, dict): fail()
                normalized_mark = {'type': name}
                simple = {'bold': 'strong', 'italic': 'em', 'underline': 'u', 'strike': 's', 'code': 'code'}
                if name in simple:
                    html = f'<{simple[name]}>{html}</{simple[name]}>'
                elif name == 'textStyle':
                    classes = []; kept = {}
                    for attr, choices, prefix in [('color', FG, 'rt-fg-'), ('backgroundColor', BG, 'rt-bg-')]:
                        color = ma.get(attr)
                        if color is None: continue
                        if not isinstance(color, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', color): fail('颜色需要使用六位 HEX 色号，例如 #3478ab。')
                        color = color.lower(); kept[attr] = color
                        if color in choices: classes.append(prefix + choices[color])
                        color_class = prefix + color[1:]
                        classes.append(color_class)
                        if has_request_context():
                            if not hasattr(g, 'rich_color_rules'): g.rich_color_rules = set()
                            prop = 'color' if attr == 'color' else 'background-color'
                            g.rich_color_rules.add(f'.{color_class}{{{prop}:{color}}}')
                    size = ma.get('fontSize')
                    if size is not None:
                        if not isinstance(size, str) or size not in SIZES: fail('请选择工具栏提供的字号。')
                        kept['fontSize'] = size; classes.append('rt-size-' + size[:-2])
                    normalized_mark['attrs'] = kept
                    html = f'<span class="{" ".join(classes)}">{html}</span>'
                elif name == 'link':
                    href = text(ma.get('href'), 2000).strip()
                    if any(ord(c) < 32 for c in href) or '\\' in href: fail('链接格式无效。')
                    try: parts = urlsplit(href)
                    except ValueError: fail('链接格式无效。')
                    if parts.scheme not in ('https', 'http', 'mailto') or (parts.scheme != 'mailto' and not parts.netloc):
                        fail('链接仅支持 http、https 或 mailto。')
                    normalized_mark['attrs'] = {'href': href, 'target': '_blank', 'rel': 'nofollow noopener noreferrer'}
                    html = f'<a href="{escape(href, quote=True)}" rel="nofollow noopener noreferrer">{html}</a>'
                else: fail()
                valid_marks.append(normalized_mark)
            if valid_marks: normalized['marks'] = valid_marks
            return normalized, html, plain
        if kind == 'image':
            image_count += 1
            if image_count > 12: fail('每篇帖子最多使用 12 张图片。')
            src = attrs.get('src')
            if not isinstance(src, str) or not re.fullmatch(r'/images/[0-9a-f]{32}', src):
                fail('请使用上传按钮插入图片，不支持外部图片地址。')
            image_id = src.rsplit('/', 1)[1]; images.add(image_id)
            if len(images) > 12: fail('每篇帖子最多使用 12 张图片。')
            alt = text(attrs.get('alt') or '图片', 200)
            width = attrs.get('displayWidth', '100')
            if width not in ('50', '75', '100'): fail()
            return {'type': kind, 'attrs': {'src': src, 'alt': alt, 'displayWidth': width}}, (
                f'<img src="{src}" alt="{escape(alt, quote=True)}" class="post-image rt-image-{width}" loading="lazy">'), f'\n[图片：{alt}]\n'
        tags = {'doc': None, 'paragraph': 'p', 'heading': 'h2', 'bulletList': 'ul',
                'orderedList': 'ol', 'listItem': 'li', 'blockquote': 'blockquote',
                'codeBlock': 'pre', 'table': 'table', 'tableRow': 'tr',
                'tableHeader': 'th', 'tableCell': 'td', 'hardBreak': 'br', 'horizontalRule': 'hr'}
        if kind not in tags or (kind == 'doc' and depth != 0): fail()
        children = value.get('content', [])
        if not isinstance(children, list): fail()
        allowed_children = {
            'doc': {'paragraph','heading','bulletList','orderedList','blockquote','codeBlock','table','image','horizontalRule'},
            'paragraph': {'text','hardBreak'}, 'heading': {'text','hardBreak'}, 'codeBlock': {'text'},
            'bulletList': {'listItem'}, 'orderedList': {'listItem'}, 'table': {'tableRow'},
            'tableRow': {'tableCell','tableHeader'},
        }
        allowed = allowed_children.get(kind)
        if kind in ('listItem', 'blockquote', 'tableCell', 'tableHeader'):
            allowed = {'paragraph','heading','bulletList','orderedList','blockquote','codeBlock','image','horizontalRule'}
        if allowed is not None and any(not isinstance(c, dict) or c.get('type') not in allowed for c in children): fail()
        rendered = [node(child, depth + 1) for child in children]
        normalized = {'type': kind}
        if rendered: normalized['content'] = [r[0] for r in rendered]
        inner = ''.join(r[1] for r in rendered)
        plain = ''.join(r[2] for r in rendered)
        tag = tags[kind]; extra = ''
        if kind == 'heading':
            level = attrs.get('level', 2)
            if type(level) is not int or level not in range(1, 7): fail()
            normalized['attrs'] = {'level': level}; tag = 'h' + str(level)
        elif kind == 'orderedList':
            start = attrs.get('start', 1)
            if type(start) is not int or not 1 <= start <= 10000: fail()
            normalized['attrs'] = {'start': start}; extra = f' start="{start}"'
        elif kind == 'codeBlock':
            language = attrs.get('language')
            if language is not None and (not isinstance(language, str) or not re.fullmatch(r'[\w+-]{0,30}', language)): fail()
            normalized['attrs'] = {'language': language}; inner = '<code>' + inner + '</code>'
        elif kind in ('tableCell', 'tableHeader'):
            normalized['attrs'] = {'colspan': 1, 'rowspan': 1, 'colwidth': None}
            if attrs.get('colspan', 1) != 1 or attrs.get('rowspan', 1) != 1: fail('暂不支持合并单元格。')
        if kind == 'hardBreak': return normalized, '<br>', '\n'
        if kind == 'horizontalRule': return normalized, '<hr>', '\n---\n'
        return normalized, (f'<{tag}{extra}>{inner}</{tag}>' if tag else inner), plain + ('\n\n' if kind != 'doc' else '')

    if not isinstance(document, dict) or document.get('type') != 'doc': fail()
    normalized, html, plain = node(document)
    if characters > 30000 or (not plain.strip() and not images): fail('正文需要文字或图片，文字最多30,000个字符。')
    return normalized, Markup(html), plain.strip(), images


def render_revision(revision):
    if revision.rich_content:
        return compile_document(revision.rich_content)[1]
    from .markdown import render_markdown
    return render_markdown(revision.markdown)
