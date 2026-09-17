import { Editor } from '@tiptap/core';
import StarterKit from '@tiptap/starter-kit';
import { TableKit } from '@tiptap/extension-table';
import Image from '@tiptap/extension-image';
import { TextStyle, Color, BackgroundColor, FontSize } from '@tiptap/extension-text-style';
import { colorClass, createColorPicker } from './color-picker.js';

const form = document.getElementById('post-editor');
if (form) {
  const source = form.elements.markdown;
  const toolbar = document.getElementById('rich-toolbar');
  const notice = document.getElementById('rich-notice');
  const submit = [...form.querySelectorAll('button[type="submit"]')];
  let loading = true, locked = false, uploading = false;
  const colorPickers = {};
  const colors = {'#172b2b':'ink','#b42318':'red','#b54708':'orange','#8a6500':'gold','#175c4b':'green','#175cd3':'blue','#6941c6':'purple','#667085':'gray'};
  const backgrounds = {'#fff3bf':'yellow','#d3f9d8':'green','#dbeafe':'blue','#fce7f3':'pink'};
  const SafeTextStyle = TextStyle.extend({renderHTML({mark}) {
    const classes = [];
    classes.push(colorClass(mark.attrs.color), colorClass(mark.attrs.backgroundColor, true));
    if (colors[mark.attrs.color]) classes.push('rt-fg-' + colors[mark.attrs.color]);
    if (backgrounds[mark.attrs.backgroundColor]) classes.push('rt-bg-' + backgrounds[mark.attrs.backgroundColor]);
    if (['14px','16px','20px','24px','32px'].includes(mark.attrs.fontSize)) classes.push('rt-size-' + mark.attrs.fontSize.slice(0,-2));
    return ['span', {class: classes.join(' ')}, 0];
  }});
  const ManagedImage = Image.extend({
    addAttributes() {return {...this.parent?.(), displayWidth: {default: '100',
      renderHTML: attrs => ({class: `post-image rt-image-${['50','75','100'].includes(attrs.displayWidth) ? attrs.displayWidth : '100'}`})}};},
    parseHTML() {return [{tag: 'img', getAttrs: node => /^\/images\/[0-9a-f]{32}$/.test(node.getAttribute('src') || '') ? null : false}];},
  });
  function controls() {
    const blocked = loading || locked || uploading;
    rich.setEditable(!blocked, false);
    [...toolbar.querySelectorAll('button,select,input'), ...submit].forEach(button => button.disabled = blocked);
  }
  const rich = new Editor({
    element: document.getElementById('rich-editor'), injectCSS: false,
    extensions: [StarterKit.configure({link: {openOnClick: false, autolink: false}}), TableKit,
      ManagedImage.configure({allowBase64: false}), SafeTextStyle, Color, BackgroundColor, FontSize],
    content: '',
    editorProps: {attributes: {class: 'markdown-body rich-content', role: 'textbox',
      'aria-label': '富文本正文', 'aria-multiline': 'true'},
      handlePaste: (_view, event) => {
        const files = [...(event.clipboardData?.files || [])];
        if (files.length) {event.preventDefault(); upload(files[0]); return true;} return false;
      },
      handleDrop: (_view, event) => {
        const files = [...(event.dataTransfer?.files || [])];
        if (files.length) {event.preventDefault(); upload(files[0]); return true;} return false;
      }},
    onUpdate: ({editor}) => {
      if (loading) return;
      form.richContent = editor.getJSON();
      source.value = editor.getText({blockSeparator: '\n\n'}) || (editor.getHTML().includes('<img') ? '[图片]' : '');
      source.dispatchEvent(new Event('input', {bubbles: true}));
      notice.textContent = source.value.length > 30000 ? '文字超过30,000字符，请缩短后保存。' : '修改后请保存。图片可粘贴、拖入，或点击「插入图片」。';
    },
    onTransaction: ({editor}) => {
      toolbar.querySelectorAll('[data-mark]').forEach(button => button.setAttribute('aria-pressed', String(editor.isActive(button.dataset.mark))));
      const style = editor.getAttributes('textStyle');
      colorPickers.color?.(style.color);
      colorPickers.backgroundColor?.(style.backgroundColor);
      for (const [id, attribute] of [['font-size','fontSize']]) {
        const select = document.getElementById(id);
        select.value = [...select.options].some(option => option.value === style[attribute]) ? style[attribute] : '';
      }
      document.getElementById('image-width').value = editor.getAttributes('image').displayWidth || '100';
    },
  });
  async function initialize() {
    controls();
    try {
      const initial = JSON.parse(document.getElementById('initial-rich-content').textContent);
      if (initial) rich.commands.setContent(initial, {emitUpdate: false});
      else {
        const response = await fetch('/posts/preview', {method: 'POST', credentials: 'same-origin',
          headers: {'Content-Type': 'application/json', 'X-CSRFToken': form.elements.csrf_token.value},
          body: JSON.stringify({markdown: source.value})});
        if (!response.ok) throw new Error();
        rich.commands.setContent((await response.json()).html, {emitUpdate: false});
      }
      form.richContent = rich.getJSON();
      source.required = false;
      document.getElementById('rich-wrapper').hidden = false;
      document.getElementById('markdown-wrapper').hidden = true;
      notice.textContent = '选中文字设置样式。图片可粘贴、拖入，或点击「插入图片」。';
      loading = false; controls();
    } catch {
      notice.textContent = '编辑器加载失败，请刷新页面重试；未保存或改动原帖。';
      // Keep saving disabled, so formatted content is never overwritten by a plain fallback.
    }
  }
  async function upload(file) {
    if (loading || locked || uploading) return;
    if (!['image/jpeg','image/png','image/webp'].includes(file.type) || file.size > 5 * 1024 * 1024) {
      notice.textContent = '请选择不超过5MB的JPG、PNG或WebP静态图片。'; return;
    }
    const at = rich.state.selection.from;
    uploading = true; controls(); notice.textContent = '正在上传图片…';
    try {
      const body = new FormData(); body.append('file', file);
      const response = await fetch('/images', {method: 'POST', credentials: 'same-origin',
        headers: {'X-CSRFToken': form.elements.csrf_token.value, Accept: 'application/json'}, body});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || '图片上传失败。');
      if (!/^\/images\/[0-9a-f]{32}$/.test(result.url)) throw new Error('图片地址无效。');
      uploading = false; controls();
      rich.chain().focus().setTextSelection(at).setImage({src: result.url, alt: '配图', displayWidth: '100'}).run();
      notice.textContent = '图片已插入，保存草稿或发布后才会关联到帖子。';
    } catch (error) {notice.textContent = error.message || '上传失败，请重试。';}
    finally {uploading = false; controls();}
  }
  const actions = {
    paragraph: () => rich.chain().focus().setParagraph().run(),
    heading: () => rich.chain().focus().toggleHeading({level: 2}).run(),
    bold: () => rich.chain().focus().toggleBold().run(), italic: () => rich.chain().focus().toggleItalic().run(),
    underline: () => rich.chain().focus().toggleUnderline().run(), strike: () => rich.chain().focus().toggleStrike().run(),
    bullet: () => rich.chain().focus().toggleBulletList().run(), ordered: () => rich.chain().focus().toggleOrderedList().run(),
    quote: () => rich.chain().focus().toggleBlockquote().run(), code: () => rich.chain().focus().toggleCodeBlock().run(),
    table: () => rich.chain().focus().insertTable({rows: 3, cols: 3, withHeaderRow: true}).run(),
    row: () => rich.chain().focus().addRowAfter().run(), column: () => rich.chain().focus().addColumnAfter().run(),
    removeTable: () => rich.chain().focus().deleteTable().run(),
    undo: () => rich.chain().focus().undo().run(), redo: () => rich.chain().focus().redo().run(),
    clear: () => rich.chain().focus().unsetAllMarks().run(),
    image: () => document.getElementById('image-upload').click(),
  };
  toolbar.addEventListener('mousedown', event => {if (event.target.closest('button')) event.preventDefault();});
  toolbar.addEventListener('click', event => {
    const button = event.target.closest('[data-action]');
    if (button && !locked && !uploading) actions[button.dataset.action]?.();
  });
  document.getElementById('image-upload').addEventListener('change', event => {
    if (event.target.files[0]) upload(event.target.files[0]);
    event.target.value = '';
  });
  colorPickers.color = createColorPicker(document.getElementById('font-color'), value => {
    if (loading || locked || uploading) return false;
    const chain = rich.chain().focus(); return value ? chain.setColor(value).run() : chain.unsetColor().run();
  });
  colorPickers.backgroundColor = createColorPicker(document.getElementById('background-color'), value => {
    if (loading || locked || uploading) return false;
    const chain = rich.chain().focus(); return value ? chain.setBackgroundColor(value).run() : chain.unsetBackgroundColor().run();
  });
  document.getElementById('font-size').addEventListener('change', event => {
    const chain = rich.chain().focus(); event.target.value ? chain.setFontSize(event.target.value).run() : chain.unsetFontSize().run();
  });
  document.getElementById('image-width').addEventListener('change', event => {
    if (rich.isActive('image')) rich.chain().focus().updateAttributes('image', {displayWidth: event.target.value}).run();
    else notice.textContent = '请先点击选中正文中的图片，再设置宽度。';
  });
  form.addEventListener('editor-lock', event => {locked = event.detail; controls();});
  initialize();
}
