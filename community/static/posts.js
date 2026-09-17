(() => {
  async function send(url, method, payload, csrf, signal) {
    const response = await fetch(url, {method, signal, credentials: 'same-origin',
      headers: {'Content-Type': 'application/json', 'Accept': 'application/json', 'X-CSRFToken': csrf},
      body: JSON.stringify(payload)});
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw Object.assign(new Error(result.error || '保存失败，请稍后重试。'), {status: response.status});
    return result;
  }
  const editor = document.getElementById('post-editor');
  if (editor) {
    let postId = editor.dataset.postId;
    let version = Number(editor.dataset.version);
    let status = editor.dataset.status;
    let dirty = false, busy = false, pending = null;
    const message = document.getElementById('editor-message');
    const csrf = editor.elements.csrf_token.value;
    const buttons = [...editor.querySelectorAll('button[type="submit"]')];
    const show = (text, error = false) => { message.textContent = text; message.className = error ? 'form-error' : 'success-message'; };
    const values = () => ({title: editor.elements.title.value, markdown: editor.elements.markdown.value,
      tags: editor.elements.tags.value.split(/[,，]/).map(t => t.trim()).filter(Boolean),
      change_reason: editor.elements.change_reason?.value || ''});
    editor.addEventListener('input', () => { dirty = true; });
    window.addEventListener('beforeunload', (event) => { if (dirty) {event.preventDefault(); event.returnValue = '';}});
    const markdown = editor.elements.markdown;
    const previewPanel = document.getElementById('preview-panel');
    const previewStatus = document.getElementById('preview-status');
    let previewTimer, previewController, previewSequence = 0, composing = false;
    function cancelPreview() {
      clearTimeout(previewTimer);
      previewController?.abort();
      previewSequence += 1;
    }
    async function refreshPreview() {
      cancelPreview();
      const sequence = previewSequence;
      if (!markdown.value.trim()) {
        previewPanel.textContent = '开始输入正文，这里会自动显示排版。';
        previewStatus.textContent = '实时预览';
        previewPanel.removeAttribute('aria-busy');
        return;
      }
      previewController = new AbortController();
      previewStatus.textContent = '正在更新预览…';
      previewPanel.setAttribute('aria-busy', 'true');
      try {
        const result = await send('/posts/preview', 'POST', {markdown: markdown.value}, csrf, previewController.signal);
        if (sequence !== previewSequence) return;
        // Only the server's Markdown renderer + allowlist sanitizer produces this HTML.
        previewPanel.innerHTML = result.html;
        previewStatus.textContent = '预览已更新';
      } catch (error) {
        if (error.name !== 'AbortError' && sequence === previewSequence) {
          previewStatus.textContent = '预览更新失败，可点击刷新重试。';
        }
      } finally {
        if (sequence === previewSequence) previewPanel.removeAttribute('aria-busy');
      }
    }
    function schedulePreview() {
      cancelPreview();
      previewPanel.removeAttribute('aria-busy');
      previewStatus.textContent = '等待输入完成…';
      if (!composing) previewTimer = setTimeout(refreshPreview, 350);
    }
    markdown.addEventListener('input', schedulePreview);
    markdown.addEventListener('compositionstart', () => { composing = true; cancelPreview(); });
    markdown.addEventListener('compositionend', () => { composing = false; schedulePreview(); });
    document.getElementById('preview-button').addEventListener('click', () => {
      if (!composing) refreshPreview();
    });
    refreshPreview();
    async function operation(url, method, payload) {
      const signature = JSON.stringify([url, method, payload]);
      if (!pending || pending.signature !== signature) pending = {signature, key: crypto.randomUUID()};
      const result = await send(url, method, {...payload, operation_key: pending.key}, csrf);
      pending = null;
      return result;
    }
    editor.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (busy) return;
      if (!editor.elements.markdown.value.trim() || editor.elements.markdown.value.length > 30000) {
        show('正文需要 1–30,000 个字符。', true);
        return;
      }
      const publish = event.submitter?.value === 'publish';
      busy = true; buttons.forEach(b => b.disabled = true); show('正在保存…');
      editor.dispatchEvent(new CustomEvent('editor-lock', {detail: true}));
      const fields = [...editor.querySelectorAll('input:not([type="hidden"]), textarea')];
      fields.forEach(field => field.readOnly = true);
      try {
        const payload = values();
        if (!postId || dirty) {
          if (postId) payload.base_version = version;
          const result = await operation(postId ? `/posts/${postId}` : '/posts', postId ? 'PATCH' : 'POST', payload);
          postId = result.id; version = result.version; status = result.status; dirty = false;
          editor.dataset.postId = postId;
          window.history.replaceState(null, '', `/posts/${postId}/edit`);
        }
        if (publish && status === 'draft') {
          const result = await operation(`/posts/${postId}/publish`, 'POST', {base_version: version});
          version = result.version; status = result.status;
          window.location.assign(`/posts/${postId}`);
        } else { show(status === 'published' ? '公开内容已更新。' : '草稿已保存，仅自己可见。'); }
      } catch (error) {
        show(error.message, true);
        if (error.status === 409 && postId) {
          const link = document.getElementById('latest-version');
          link.href = `/posts/${postId}`; link.hidden = false;
        }
      } finally {busy = false; fields.forEach(field => field.readOnly = false); buttons.forEach(b => b.disabled = false); editor.dispatchEvent(new CustomEvent('editor-lock', {detail: false}));}
    });
  }
  const remove = document.getElementById('delete-post');
  if (remove) {
    const dialog = document.getElementById('delete-dialog');
    const confirm = document.getElementById('confirm-delete');
    const key = crypto.randomUUID();
    remove.addEventListener('click', () => dialog.showModal());
    document.getElementById('cancel-delete').addEventListener('click', () => dialog.close());
    confirm.addEventListener('click', async () => {
      confirm.disabled = true;
      try {
        await send(`/posts/${remove.dataset.postId}`, 'DELETE',
          {base_version: Number(remove.dataset.version), operation_key: key}, remove.dataset.csrf);
        window.location.assign('/me/posts');
      } catch (error) {document.getElementById('delete-message').textContent = error.message;}
      finally {confirm.disabled = false;}
    });
  }
})();
