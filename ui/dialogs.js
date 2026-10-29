/* 各类弹窗：运行日志、新手引导、问题反馈 */
// ===== 运行日志查看 =====
// 后端 get_log_info 返回日志路径与末尾内容；
// 这里做成弹窗，方便用户直接复制发给开发者，或打开文件夹取完整文件。
window._logText = window._logText || '';
window._logDir = window._logDir || '';

function showLogModal() {
  Modal.open({
    id: 'logOverlay',
    icon: 'i-info',
    title: '运行日志',
    desc: '遇到问题时把日志发给开发者，能快速定位原因',
    wide: true,
    body:
      '<div id="logBody" class="log-box-scroll">' +
        '<pre id="logPre" class="log-pre">读取中…</pre>' +
      '</div>',
    actions: [
      { text: '打开日志文件夹', onclick: openLogFolder },
      { text: '<svg class="ico"><use href="#i-copy"/></svg> 复制日志', primary: true, onclick: copyLog },
      { text: '关闭', onclick: () => Modal.close('logOverlay') },
    ],
    footer: '日志只保存在本机，不会上传',
  });

  pywebview.api.get_log_info(300).then(function (info) {
    const pre = document.getElementById('logPre');
    if (!pre) return;
    if (!info || !info.success) {
      pre.textContent = (info && info.error) || '暂无日志内容';
      return;
    }
    window._logText = info.content || '';
    window._logDir = info.dir || '';
    pre.textContent = window._logText || '(本次运行还没有输出)';
    const box = document.getElementById('logBody');
    if (box) box.scrollTop = box.scrollHeight;
  }).catch(function (e) {
    const pre = document.getElementById('logPre');
    if (pre) pre.textContent = '读取日志失败：' + e;
  });
}

function copyLog() {
  if (!window._logText) {
    addLog('日志内容为空，暂无可复制的内容', 'warn');
    return;
  }
  if (navigator.clipboard) {
    navigator.clipboard.writeText(window._logText).then(function () {
      addLog('日志已复制到剪贴板，可直接粘贴发送', 'success');
    }).catch(function () {
      addLog('复制失败，可点「打开日志文件夹」手动取文件', 'error');
    });
  } else {
    addLog('当前环境不支持剪贴板，请打开日志文件夹手动复制', 'warn');
  }
}

function openLogFolder() {
  if (!window._logDir) {
    addLog('还没产生日志文件', 'warn');
    return;
  }
  pywebview.api.open_file(window._logDir).then(function (r) {
    if (!r || !r.success) addLog('打开文件夹失败：' + ((r && r.error) || '未知'), 'error');
  }).catch(function (e) {
    addLog('打开文件夹异常：' + e, 'error');
  });
}

// === 首次使用引导 ===
function showGuide() {
  // 引导需要按步骤重绘，不适合静态的 Modal 工厂，
  // 因此复用同一套 .modal-* 样式类，去掉内联样式。
  const overlay = document.createElement('div');
  overlay.id = 'guideOverlay';
  overlay.className = 'modal-overlay';
  overlay.style.zIndex = '9999';

  const steps = [
    { icon: 'i-fish', title: '欢迎使用闲鱼辅助工具', desc: '帮你一键解析闲鱼商品、去水印、生成三版文案、搜补充图' },
    { icon: 'i-link', title: '第一步：粘贴链接', desc: '把闲鱼商品分享链接粘贴到顶部输入框，点「开始」' },
    { icon: 'i-key', title: '第二步：首次需扫码登录', desc: '首次使用会弹出浏览器窗口，扫码登录闲鱼即可，之后自动记住登录态' },
    { icon: 'i-sparkle', title: '第三步：等待处理完成', desc: '自动解析商品 → 下载图片 → 去水印 → 生成三版文案，约 1-2 分钟' },
    { icon: 'i-download', title: '第四步：保存结果', desc: '图片、文案、补充图都可以一键保存到你选的位置' },
    { icon: 'i-info', title: '遇到问题？', desc: '点击底部的「问题反馈」按钮描述你遇到的问题' },
  ];

  let currentStep = 0;

  function renderStep() {
    const step = steps[currentStep];
    const isLast = currentStep === steps.length - 1;
    const isFirst = currentStep === 0;

    const dots = steps.map((_, i) =>
      '<span class="guide-dot' + (i === currentStep ? ' active' : '') + '"></span>'
    ).join('');

    let actions = '';
    if (!isFirst) actions += '<button class="modal-btn" data-guide="prev">上一步</button>';
    actions += isLast
      ? '<button class="modal-btn primary" data-guide="done"><svg class="ico"><use href="#i-check"/></svg>开始使用</button>'
      : '<button class="modal-btn primary" data-guide="next">下一步</button>';

    overlay.innerHTML =
      '<div class="modal-card" style="text-align:center;padding:34px 32px;">' +
        '<div class="modal-icon"><svg class="ico" style="width:44px;height:44px;"><use href="#' + step.icon + '"/></svg></div>' +
        '<h2 class="modal-title">' + step.title + '</h2>' +
        '<p class="modal-desc" style="margin-bottom:24px;">' + step.desc + '</p>' +
        '<div class="guide-dots">' + dots + '</div>' +
        '<div class="modal-actions">' + actions + '</div>' +
        (isFirst ? '<p class="modal-foot" style="cursor:pointer;margin-top:14px;" data-guide="skip">跳过引导</p>' : '') +
      '</div>';

    overlay.querySelectorAll('[data-guide]').forEach(function (el) {
      el.addEventListener('click', function () {
        const act = el.getAttribute('data-guide');
        if (act === 'next') { currentStep++; renderStep(); }
        else if (act === 'prev') { currentStep--; renderStep(); }
        else { closeGuide(); }
      });
    });
  }

  function closeGuide() {
    const ov = document.getElementById('guideOverlay');
    if (ov) ov.remove();
    patchUiState({ guide_seen: true });
  }

  window.guideNext = function () { if (currentStep < steps.length - 1) { currentStep++; renderStep(); } };
  window.guidePrev = function () { if (currentStep > 0) { currentStep--; renderStep(); } };
  window.closeGuide = closeGuide;

  renderStep();
  document.body.appendChild(overlay);
}

// === 问题反馈 ===
function showFeedback() {
  const body =
    '<p class="modal-note" style="text-align:left;margin:0 0 14px;">遇到 bug 或有建议？描述一下，复制后发邮件给卖家</p>' +
    '<textarea id="feedbackContent" class="modal-input" placeholder="请描述遇到的问题..." style="height:120px;resize:none;margin-bottom:12px;"></textarea>' +
    '<input type="text" id="feedbackContact" class="modal-input" placeholder="联系方式（选填，方便回复你）" />';

  Modal.open({
    id: 'feedbackOverlay',
    icon: 'i-pen',
    title: '问题反馈',
    body: body,
    actions: [
      { text: '取消', onclick: () => Modal.close('feedbackOverlay') },
      { text: '提交', primary: true, onclick: submitFeedback },
    ],
  });
}

function submitFeedback() {
  const content = document.getElementById('feedbackContent').value.trim();
  if (!content) return;
  const contact = document.getElementById('feedbackContact').value.trim();

  const timeStr = new Date().toLocaleString('zh-CN');
  let feedbackText = '【闲鱼辅助工具-问题反馈】\n';
  feedbackText += '时间：' + timeStr + '\n';
  feedbackText += '问题：' + content + '\n';
  if (contact) feedbackText += '\n联系方式：' + contact;
  window._feedbackText = feedbackText;

  const body =
    '<div class="code-box" style="margin-bottom:14px;">' +
      '<pre class="code-pre">' +
      escapeHtml(feedbackText) + '</pre>' +
    '</div>' +
    '<div class="mail-box">' +
      '<p class="mail-label"><svg class="ico"><use href="#i-mail"/></svg> 卖家邮箱</p>' +
      '<p class="mail-addr">3144994163@qq.com</p>' +
    '</div>';

  Modal.open({
    id: 'feedbackOverlay',
    icon: 'i-download',
    title: '反馈已生成',
    desc: '请复制以下内容，发给卖家反馈问题',
    body: body,
    actions: [
      { text: '<svg class="ico"><use href="#i-copy"/></svg> 一键复制反馈内容', primary: true, id: 'copyFbBtn', onclick: copyFeedbackText },
      { text: '关闭', onclick: () => Modal.close('feedbackOverlay') },
    ],
  });
}

function copyFeedbackText() {
  const text = window._feedbackText || '';
  if (navigator.clipboard) {
    navigator.clipboard.writeText(text).then(() => {
      const btn = document.getElementById('copyFbBtn');
      btn.innerHTML = '<svg class="ico"><use href="#i-check"/></svg> 已复制，发邮件给卖家';
      btn.style.background = 'linear-gradient(135deg, #4CAF50, #45a049)';
    });
  } else {
    // fallback
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    const btn = document.getElementById('copyFbBtn');
    btn.innerHTML = '<svg class="ico"><use href="#i-check"/></svg> 已复制，去QQ发给卖家';
    btn.style.background = 'linear-gradient(135deg, #4CAF50, #45a049)';
  }
}

