import { Editor } from '@tiptap/core';
import StarterKit from '@tiptap/starter-kit';
import { TableKit } from '@tiptap/extension-table';
import { Markdown } from '@tiptap/markdown';

const form = document.getElementById('post-editor');
if (form) {
  const source = form.elements.markdown;
  const host = document.getElementById('rich-editor');
  const wrapper = document.getElementById('rich-wrapper');
  const plain = document.getElementById('markdown-wrapper');
  const notice = document.getElementById('rich-notice');
  const modes = [...document.querySelectorAll('[data-editor-mode]')];
  const toolbar = document.getElementById('rich-toolbar');
  let switching = false, locked = false, richMode = false;
  const rich = new Editor({
    element: host,
    injectCSS: false,
    extensions: [StarterKit.configure({underline: false, strike: false,
      link: {openOnClick: false, autolink: false}}), TableKit, Markdown],
    content: '',
    editorProps: {attributes: {class: 'markdown-body rich-content', role: 'textbox',
      'aria-label': '富文本正文', 'aria-multiline': 'true'},
      handleDrop: (_view, event) => {if (event.dataTransfer?.files.length) {event.preventDefault(); return true;} return false;}},
    onUpdate: ({editor}) => {
      if (switching) return;
      source.value = editor.getMarkdown();
      source.dispatchEvent(new Event('input', {bubbles: true}));
      notice.textContent = source.value.length > 30000 ? '正文超过 30,000 字符，请缩短后保存。' : '富文本试用 · 修改后请保存；可随时切回 Markdown。';
    },
    onTransaction: ({editor}) => {
      toolbar.querySelectorAll('[data-mark]').forEach(button =>
        button.setAttribute('aria-pressed', String(editor.isActive(button.dataset.mark))));
    },
  });
  async function mode(next) {
    if (switching || locked) return;
    if (next === 'rich' && !richMode) {
      switching = true;
      modes.forEach(button => button.disabled = true);
      source.readOnly = true;
      form.querySelectorAll('button[type="submit"]').forEach(button => button.disabled = true);
      notice.textContent = '正在准备富文本编辑器…';
      try {
        const response = await fetch('/posts/preview', {method: 'POST', credentials: 'same-origin',
          headers: {'Content-Type': 'application/json', 'X-CSRFToken': form.elements.csrf_token.value},
          body: JSON.stringify({markdown: source.value})});
        if (!response.ok) throw new Error('preview unavailable');
        const data = await response.json();
        // Import only the server-sanitized HTML; keep original Markdown until an actual edit.
        rich.commands.setContent(data.html, {emitUpdate: false});
        richMode = true;
      } catch {
        notice.textContent = '富文本加载失败，仍可使用 Markdown 编辑。';
        return;
      } finally {
        switching = false; source.readOnly = false;
        modes.forEach(button => button.disabled = false);
        form.querySelectorAll('button[type="submit"]').forEach(button => button.disabled = false);
      }
    } else if (next === 'markdown') richMode = false;
    wrapper.hidden = !richMode;
    plain.hidden = richMode;
    source.required = !richMode;
    notice.textContent = richMode ? '富文本试用 · 修改后请保存；可随时切回 Markdown。' : 'Markdown 模式 · 保留原来的实时预览。';
    modes.forEach(button => button.setAttribute('aria-pressed', String((button.dataset.editorMode === 'rich') === richMode)));
  }
  modes.forEach(button => button.addEventListener('click', () => mode(button.dataset.editorMode)));
  const actions = {
    paragraph: () => rich.chain().focus().setParagraph().run(),
    heading: () => rich.chain().focus().toggleHeading({level: 2}).run(),
    bold: () => rich.chain().focus().toggleBold().run(),
    italic: () => rich.chain().focus().toggleItalic().run(),
    bullet: () => rich.chain().focus().toggleBulletList().run(),
    ordered: () => rich.chain().focus().toggleOrderedList().run(),
    quote: () => rich.chain().focus().toggleBlockquote().run(),
    code: () => rich.chain().focus().toggleCodeBlock().run(),
    table: () => rich.chain().focus().insertTable({rows: 3, cols: 3, withHeaderRow: true}).run(),
    undo: () => rich.chain().focus().undo().run(),
    redo: () => rich.chain().focus().redo().run(),
  };
  toolbar.addEventListener('mousedown', event => {if (event.target.closest('button')) event.preventDefault();});
  toolbar.addEventListener('click', event => {
    const button = event.target.closest('[data-action]');
    if (button && !locked) actions[button.dataset.action]?.();
  });
  form.addEventListener('editor-lock', event => {
    locked = event.detail;
    rich.setEditable(!locked, false);
    [...modes, ...toolbar.querySelectorAll('button')].forEach(button => button.disabled = locked);
  });
  // The original Markdown editor remains usable even if this bundle fails to load.
  mode(new URLSearchParams(location.search).get('editor') === 'markdown' ? 'markdown' : 'rich');
}
