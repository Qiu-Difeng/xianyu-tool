/* 界面基础：弹窗工厂、界面状态、三主题切换 */
// ===== 弹窗工厂 =====
// 统一弹窗骨架：图标 / 标题 / 描述 / 主体 / 提示 / 按钮组 / 底部说明。
// 各弹窗只写自己的业务字段，不再复制一整套内联样式。
const Modal = {
  open(opt) {
    this.close(opt.id);
    const overlay = document.createElement('div');
    overlay.id = opt.id;
    overlay.className = 'modal-overlay';

    const iconHtml = opt.icon
      ? '<div class="modal-icon"><svg class="ico"><use href="#' + opt.icon + '"/></svg></div>' : '';
    const titleHtml = opt.title ? '<h2 class="modal-title">' + opt.title + '</h2>' : '';
    const descHtml = opt.desc ? '<p class="modal-desc">' + opt.desc + '</p>' : '';
    const footHtml = opt.footer ? '<p class="modal-foot">' + opt.footer + '</p>' : '';

    let actionsHtml = '';
    if (opt.actions && opt.actions.length) {
      actionsHtml = '<div class="modal-actions">' + opt.actions.map((a, i) => {
        const cls = 'modal-btn' + (a.primary ? ' primary' : '');
        const attr = a.id ? ' id="' + a.id + '"' : '';
        return '<button class="' + cls + '"' + attr + ' data-action="' + i + '">' + a.text + '</button>';
      }).join('') + '</div>';
    }

    overlay.innerHTML =
      '<div class="modal-card' + (opt.wide ? ' modal-wide' : '') + '">' +
        iconHtml + titleHtml + descHtml + (opt.body || '') + actionsHtml + footHtml +
      '</div>';
    document.body.appendChild(overlay);

    (opt.actions || []).forEach((a, i) => {
      if (typeof a.onclick !== 'function') return;
      const btn = overlay.querySelector('[data-action="' + i + '"]');
      if (btn) btn.addEventListener('click', () => a.onclick());
    });
    return overlay;
  },

  close(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
  },

  exists(id) {
    return !!document.getElementById(id);
  },
};

// 统一提示样式（替代各处手写 style.color）
function setHint(el, msg, level) {
  const node = typeof el === 'string' ? document.getElementById(el) : el;
  if (!node) return;
  node.textContent = msg;
  node.className = 'modal-hint' + (level ? ' ' + level : '');
}


// 注意：pywebview 用 html= 直接渲染时页面是 about:blank，
// localStorage 与 sessionStorage 都会抛 SecurityError，
// 所以状态必须存到后端文件（%LOCALAPPDATA%\XianyuTool\ui_state.json）。
let _uiState = { guide_seen: false, theme: 'system', skip_version: '' };

function loadUiState() {
  return pywebview.api.get_ui_state().then(st => {
    if (st && typeof st === 'object') _uiState = st;
    return _uiState;
  }).catch(() => _uiState);
}

function patchUiState(patch) {
  Object.assign(_uiState, patch);
  try {
    pywebview.api.save_ui_state(patch).catch(() => {});
  } catch (e) {}
}

function guideSeenBefore() { return !!_uiState.guide_seen; }

// ===== 主题：system / dark / light =====
let _systemTheme = 'dark';

function applyTheme(mode) {
  const root = document.documentElement;
  const actual = (mode === 'system') ? _systemTheme : mode;
  root.setAttribute('data-theme', actual === 'light' ? 'light' : 'dark');
  root.setAttribute('data-theme-mode', mode);

  const use = document.getElementById('themeUse');
  const btn = document.getElementById('themeBtn');
  const iconMap = { system: '#i-monitor', dark: '#i-moon', light: '#i-sun' };
  const labelMap = { system: '跟随系统', dark: '深色', light: '浅色' };
  if (use) use.setAttribute('href', iconMap[mode] || '#i-monitor');
  if (btn) btn.title = '当前：' + (labelMap[mode] || '跟随系统') + '（点击切换）';
}

function setTheme(mode) {
  applyTheme(mode);
  patchUiState({ theme: mode });
}

function cycleTheme() {
  const order = ['system', 'dark', 'light'];
  const cur = order.indexOf(_uiState.theme) === -1 ? 'system' : _uiState.theme;
  const next = order[(order.indexOf(cur) + 1) % order.length];
  setTheme(next);
  addLog('主题已切换为「' + ({ system: '跟随系统', dark: '深色', light: '浅色' })[next] + '」', 'accent');
}

// 系统主题变化时，若处于跟随模式则实时同步
(function watchSystemTheme() {
  try {
    const mq = window.matchMedia('(prefers-color-scheme: light)');
    const onChange = (e) => {
      _systemTheme = e.matches ? 'light' : 'dark';
      if ((_uiState.theme || 'system') === 'system') applyTheme('system');
    };
    if (mq.addEventListener) mq.addEventListener('change', onChange);
    else if (mq.addListener) mq.addListener(onChange);
  } catch (e) {}
})();

window.addEventListener('pywebviewready', () => {
  loadUiState().then(() => {
    // 系统主题以注册表为准（WebView2 的 prefers-color-scheme 不一定跟随系统）
    return pywebview.api.get_system_theme().catch(() => null);
  }).then(sys => {
    if (sys && sys.theme) _systemTheme = sys.theme;
    applyTheme(_uiState.theme || 'system');
    return pywebview.api.get_key_status();
  }).then(s => {
    _keyConfigured = !!(s && s.configured);
    updateKeyBtn(s);
    if (!_keyConfigured) {
      setTimeout(() => showKeyModal(true), 400);
    } else if (!guideSeenBefore()) {
      setTimeout(() => showGuide(), 800);
    }
  }).catch(() => {
    applyTheme(_uiState.theme || 'system');
    _keyConfigured = null;
    if (!guideSeenBefore()) {
      setTimeout(() => showGuide(), 800);
    }
  });
});

