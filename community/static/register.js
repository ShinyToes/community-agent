(() => {
  const form = document.getElementById('register-form');
  if (!form) return;
  const username = form.elements.username;
  const error = document.getElementById('register-error');
  const button = form.querySelector('button[type="submit"]');
  const label = button.textContent;
  let submitting = false;

  function clearError() {
    error.textContent = '';
    error.hidden = true;
    username.removeAttribute('aria-invalid');
  }
  form.addEventListener('input', clearError);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (submitting) return;
    clearError();
    submitting = true;
    button.disabled = true;
    button.textContent = '正在创建…';
    form.setAttribute('aria-busy', 'true');
    try {
      const response = await fetch(form.action, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
          'X-CSRFToken': form.elements.csrf_token.value,
        },
        body: JSON.stringify({username: username.value, password: form.elements.password.value}),
      });
      if (response.ok) {
        window.location.assign(form.dataset.successUrl);
        return;
      }
      const result = await response.json().catch(() => ({}));
      error.textContent = response.status === 409
        ? '该用户名已被使用，请换一个用户名。'
        : result.error || '暂时无法注册，请稍后重试。';
      error.hidden = false;
      if (response.status === 409) {
        username.setAttribute('aria-invalid', 'true');
        username.focus();
      }
    } catch {
      error.textContent = '网络连接失败，请检查网络后重试。';
      error.hidden = false;
    } finally {
      submitting = false;
      button.disabled = false;
      button.textContent = label;
      form.removeAttribute('aria-busy');
    }
  });
})();
