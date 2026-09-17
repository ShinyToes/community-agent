const hex = /^#[0-9a-f]{6}$/i;
const rules = new Set();
export function colorClass(value, background = false) {
  if (!hex.test(value || '')) return '';
  value = value.toLowerCase();
  const name = `rt-${background ? 'bg' : 'fg'}-${value.slice(1)}`;
  if (!rules.has(name)) {
    document.getElementById('rich-color-styles').sheet.insertRule(`.${name}{${background ? 'background-color' : 'color'}:${value}}`);
    rules.add(name);
  }
  return name;
}

const palette = [
  '#172b2b','#000000','#434343','#667085','#999999','#cccccc','#eeeeee','#ffffff',
  '#b42318','#b54708','#8a6500','#175c4b','#175cd3','#6941c6','#a21caf','#be185d',
  '#ef4444','#f97316','#eab308','#22c55e','#3b82f6','#8b5cf6','#d946ef','#ec4899',
  '#fca5a5','#fdba74','#fde047','#86efac','#93c5fd','#c4b5fd','#f0abfc','#f9a8d4',
  '#fee2e2','#ffedd5','#fff3bf','#d3f9d8','#dbeafe','#ede9fe','#fae8ff','#fce7f3',
];

export function createColorPicker(select, apply) {
  const label = select.getAttribute('aria-label');
  const root = document.createElement('div'); root.className = 'color-picker';
  const trigger = document.createElement('button'); trigger.type = 'button';
  trigger.id = select.id; trigger.setAttribute('aria-label', label);
  trigger.setAttribute('aria-expanded', 'false');
  const indicator = document.createElement('span'); indicator.className = 'color-indicator';
  trigger.append(indicator, document.createTextNode(label === '字体颜色' ? '字色 ▾' : '底色 ▾'));
  const panel = document.createElement('div'); panel.className = 'color-panel'; panel.hidden = true;
  panel.id = select.id + '-panel'; trigger.setAttribute('aria-controls', panel.id);
  panel.setAttribute('role', 'group'); panel.setAttribute('aria-label', label + '面板');
  const title = document.createElement('strong'); title.textContent = label;
  const grid = document.createElement('div'); grid.className = 'color-grid';
  const swatches = [];
  const close = () => {panel.hidden = true; trigger.setAttribute('aria-expanded', 'false');};
  const choose = value => {if (apply(value)) close();};
  for (const color of palette) {
    const button = document.createElement('button'); button.type = 'button';
    button.className = 'color-swatch';
    const fill = document.createElement('span'); fill.className = 'swatch-fill ' + colorClass(color, true); button.append(fill);
    button.title = color; button.setAttribute('aria-label', label + ' ' + color);
    button.setAttribute('aria-pressed', 'false');
    button.addEventListener('click', () => choose(color));
    grid.append(button); swatches.push([button, color]);
  }
  const custom = document.createElement('label'); custom.textContent = '自选颜色';
  const picker = document.createElement('input'); picker.type = 'color'; picker.value = '#3478ab';
  picker.setAttribute('aria-label', label + '调色盘'); custom.append(picker);
  const row = document.createElement('div'); row.className = 'color-custom';
  const input = document.createElement('input'); input.type = 'text'; input.value = '#3478ab';
  input.maxLength = 7; input.setAttribute('aria-label', label + ' HEX 色号'); input.spellcheck = false;
  const use = document.createElement('button'); use.type = 'button'; use.textContent = '应用';
  const error = document.createElement('small'); error.className = 'form-error'; error.setAttribute('role', 'status');
  const applyInput = () => {
    const value = input.value.trim();
    if (!hex.test(value)) {error.textContent = '请输入六位色号，例如 #3478ab。'; input.setAttribute('aria-invalid', 'true'); return;}
    error.textContent = ''; input.removeAttribute('aria-invalid'); choose(value.toLowerCase());
  };
  picker.addEventListener('input', () => {input.value = picker.value;});
  use.addEventListener('click', applyInput);
  input.addEventListener('keydown', event => {if (event.key === 'Enter') {event.preventDefault(); applyInput();}});
  const reset = document.createElement('button'); reset.type = 'button'; reset.className = 'color-reset';
  reset.textContent = label === '字体颜色' ? '恢复默认字色' : '清除背景色';
  reset.addEventListener('click', () => choose(''));
  row.append(input, use); panel.append(title, grid, custom, row, error, reset);
  root.append(trigger, panel); select.closest('.toolbar-field').replaceWith(root);
  trigger.addEventListener('click', () => {
    const opening = panel.hidden;
    error.textContent = ''; input.removeAttribute('aria-invalid');
    document.dispatchEvent(new Event('close-color-panels'));
    panel.hidden = !opening; trigger.setAttribute('aria-expanded', String(opening));
  });
  document.addEventListener('close-color-panels', close);
  document.addEventListener('mousedown', event => {if (!root.contains(event.target)) close();});
  root.addEventListener('keydown', event => {if (event.key === 'Escape') {event.preventDefault(); close(); trigger.focus();}});
  return value => {
    const valid = hex.test(value || '') ? value.toLowerCase() : '';
    indicator.className = 'color-indicator ' + colorClass(valid, true);
    swatches.forEach(([button, color]) => button.setAttribute('aria-pressed', String(color === valid)));
    if (valid) {picker.value = valid; input.value = valid;}
  };
}
