/**
 * copy —— 从 workflow.js 拆出来的一块
 *
 * 函数实现原样搬过来，没改逻辑。全局状态（_outputDir 等）还在 workflow.js，
 * 这里只是在函数体内引用，调用时已经定义，不受加载顺序影响。
 */

function startCopyPolling(outputDir) {
  if (_copyPollTimer) clearInterval(_copyPollTimer);
  let pollCount = 0;
  _copyPollTimer = setInterval(() => {
    pollCount++;
    pywebview.api.check_copy_status(outputDir).then(data => {
      if (data && data.done === false) return; // 还没完成
      if (data && data.error) {
        clearInterval(_copyPollTimer);
        _copyPollTimer = null;
        document.getElementById('pane3').innerHTML = '<div class="empty"><span class="emoji"><svg class="ico"><use href="#i-pen"/></svg></span><p>文案生成失败: ' + escapeHtml(data.error) + '</p></div>';
        return;
      }
      if (data && data.versions && data.versions.length > 0) {
        clearInterval(_copyPollTimer);
        _copyPollTimer = null;
        _copiesData = data;
        document.getElementById('pane3').innerHTML = renderCopies(data);
        addLog('文案生成完成！V1/V2/V3已就绪', 'success');
      }
    });
    // 超时保护：5分钟
    if (pollCount > 100) {
      clearInterval(_copyPollTimer);
      _copyPollTimer = null;
      document.getElementById('pane3').innerHTML = '<div class="empty"><span class="emoji"><svg class="ico"><use href="#i-pen"/></svg></span><p>文案生成超时，请点击刷新重试</p></div>';
    }
  }, 3000); // 每3秒检查一次
}


function renderCopies(data) {
  if (!data.versions || data.versions.length === 0) return '<div class="empty"><span class="emoji"><svg class="ico"><use href="#i-pen"/></svg></span><p>无文案</p></div>';
  let html = '<div class="copy-tabs">';
  data.versions.forEach((v, i) => {
    html += '<div class="copy-tab' + (i === 0 ? ' active' : '') + '" onclick="switchCopy(' + i + ')" data-version="' + escapeHtml(v.key) + '">' +
      '<span>' + escapeHtml(v.label) + '</span><span class="refresh-icon" onclick="event.stopPropagation();refreshCopy(' + i + ')" title="重新生成"><svg class="ico"><use href="#i-refresh"/></svg></span></div>';
  });
  html += '</div><div id="copyBody"></div>';
  // 控制区跟着当前版本变：V1 显示替换明细，V2/V3 显示各自的提示词框
  html += '<div id="copyControl"></div>';
  window._copies = data.versions;
  window._v1Changes = data.v1_changes || [];
  setTimeout(() => { switchCopy(0); }, 50);
  return html;
}


// 按当前版本渲染控制区
function renderCopyControl(key) {
  const box = document.getElementById('copyControl');
  if (!box) return;

  if (key === 'v1') {
    // V1：显示改了哪些词，每个词都能换同义词
    const changes = window._v1Changes || [];
    if (!changes.length) {
      // 一个词都没替换也要给按钮：用户可能想再试一次，或者原文确实没词典词
      box.innerHTML = '<div class="custom-prompt-area"><div class="cp-label">' +
        '<svg class="ico"><use href="#i-info"/></svg> V1 词典替换</div>' +
        '<div class="cp-empty">这一版没有替换任何词（原文里没有词典中的词）</div>' +
        '<div class="cp-row"><button class="btn-refresh cp-btn" onclick="applyV1Choices(true)">' +
        '<svg class="ico"><use href="#i-sparkle"/></svg> 随机换一批试试</button></div></div>';
      return;
    }
    let h = '<div class="custom-prompt-area">';
    h += '<div class="cp-label"><svg class="ico"><use href="#i-info"/></svg> ' +
         'V1 词典替换：改了 ' + changes.length + ' 个词，可以逐个改选同义词</div>';
    h += '<div class="v1-changes">';
    changes.forEach(function (c) {
      h += '<div class="vc-row">' +
        '<span class="vc-orig">' + escapeHtml(c.original) + '</span>' +
        '<span class="vc-arrow">→</span>' +
        '<select class="vc-select" data-orig="' + escapeHtml(c.original) + '">' +
          c.options.map(function (o, j) {
            return '<option value="' + j + '"' + (j === c.index ? ' selected' : '') + '>' +
                   escapeHtml(o) + '</option>';
          }).join('') +
        '</select>' +
        '<span class="vc-count">出现 ' + c.count + ' 次</span>' +
      '</div>';
    });
    h += '</div>';
    h += '<div class="cp-row">';
    h += '<button class="btn-refresh cp-btn" onclick="applyV1Choices()">' +
         '<svg class="ico"><use href="#i-refresh"/></svg> 按选择重新替换</button>';
    h += '<button class="btn-refresh cp-btn" onclick="applyV1Choices(true)" ' +
         'title="每个词随机换一个别的说法">' +
         '<svg class="ico"><use href="#i-sparkle"/></svg> 随机换一批</button>';
    h += '</div>';
    h += '</div>';
    box.innerHTML = h;
    return;
  }

  // V2 / V3：各自的提示词框
  const isV2 = key === 'v2';
  const label = isV2 ? 'V2 自定义提示词（可选，不填则默认微调）'
                     : 'V3 自定义提示词（可选，不填则默认重写）';
  const ph = isV2 ? '例如：保留原结构，只把语气改得更热情'
                  : '例如：突出性价比，加上使用场景，语气活泼一点';
  const inputId = key + 'CustomPrompt';
  let h = '<div class="custom-prompt-area">';
  h += '<div class="cp-label"><svg class="ico"><use href="#i-info"/></svg> ' + label + '</div>';
  h += '<div class="cp-row">';
  h += '<input type="text" id="' + inputId + '" class="cp-input" placeholder="' + ph + '" />';
  h += '<button class="btn-refresh cp-btn" onclick="savePromptTemplate(\'' + key + '\')">' +
       '<svg class="ico"><use href="#i-download"/></svg> 存为模板</button>';
  h += '<button class="btn-refresh cp-btn" onclick="customRewrite(\'' + key + '\')">' +
       '<svg class="ico"><use href="#i-refresh"/></svg> 按提示词重写</button>';
  h += '</div>';
  h += '<div id="' + key + 'TplChips" class="cp-chips"></div>';
  h += '</div>';
  box.innerHTML = h;
  setTimeout(function () { loadPromptTemplates(key); }, 60);
}


// 收集 V1 的下拉选择，重新替换
function applyV1Choices(randomize) {
  // randomize=true 时忽略下拉框，每个词随机选一个同义词
  const sels = document.querySelectorAll('#copyControl .vc-select');
  const choices = {};
  if (!randomize) {
    sels.forEach(function (s) { choices[s.dataset.orig] = parseInt(s.value, 10) || 0; });
  }
  if (!_outputDir) { addLog('还没有商品数据', 'warn'); return; }
  addLog(randomize ? '随机换一批同义词…' : '按当前选择重新做词典替换…', 'accent');
  pywebview.api.regenerate_copy(_outputDir, 'v1', null,
                                randomize ? null : choices, !!randomize).then(function (r) {
    if (!r || !r.success) {
      addLog('替换失败：' + ((r && r.error) || '未知原因'), 'error');
      return;
    }
    window._copies[0].text = r.text;
    window._copies[0].banned = r.banned;
    if (r.changes) window._v1Changes = r.changes;
    switchCopy(0);
    addLog((randomize ? '随机替换完成' : 'V1 重新替换完成') +
           '（' + r.text.length + ' 字，改了 ' + ((r.changes || []).length) + ' 个词）', 'success');
  }).catch(function (e) { addLog('替换异常：' + e, 'error'); });
}


// V2 / V3 按各自提示词重写
function customRewrite(key) {
  const el = document.getElementById(key + 'CustomPrompt');
  const prompt = el ? el.value.trim() : '';
  if (!_outputDir) { addLog('还没有商品数据', 'warn'); return; }
  if (!prompt) {
    addLog('提示词是空的，留空请直接点标签上的刷新图标', 'warn');
    return;
  }
  addLog(key.toUpperCase() + ' 按提示词重写中…', 'accent');
  pywebview.api.regenerate_copy(_outputDir, key, prompt).then(function (r) {
    if (!r || !r.success) {
      addLog('重写失败：' + ((r && r.error) || '未知原因'), 'error');
      return;
    }
    const idx = key === 'v2' ? 1 : 2;
    window._copies[idx].text = r.text;
    window._copies[idx].banned = r.banned;
    switchCopy(idx);
    addLog(key.toUpperCase() + ' 重写完成（' + r.text.length + ' 字）', 'success');
  }).catch(function (e) { addLog('重写异常：' + e, 'error'); });
}


function switchCopy(idx) {
  document.querySelectorAll('.copy-tab').forEach((t, i) => t.classList.toggle('active', i === idx));
  const v = window._copies[idx];
  const badge = v.banned.length > 0
    ? '<span class="badge-warn"><svg class="ico"><use href="#i-alert"/></svg> 违禁词: ' + escapeHtml(v.banned.join(',')) + '</span>'
    : '<span class="badge-ok"><svg class="ico"><use href="#i-check"/></svg> 零违禁词</span>';
  document.getElementById('copyBody').innerHTML =
    '<div class="copy-meta"><span>' + v.text.length + '字</span>' + badge +
    '<button class="btn-copy" onclick="showCopyHistory(' + idx + ')" title="查看生成历史" style="margin-left:auto;padding:4px 12px;border-radius:6px;border:1px solid var(--glass-border);background:var(--glass-light);color:var(--text);cursor:pointer;font-size:12px;"><svg class="ico"><use href="#i-clock"/></svg> 历史</button>' +
    '<button class="btn-copy" onclick="copyText(' + idx + ')" style="margin-left:6px;padding:4px 12px;border-radius:6px;border:1px solid var(--glass-border);background:var(--glass-light);color:var(--text);cursor:pointer;font-size:12px;"><svg class="ico"><use href="#i-copy"/></svg> 一键复制</button></div>' +
    '<div class="copy-content" id="copyText_' + idx + '">' + escapeHtml(v.text) + '</div>';

  // 控制区跟着当前版本切换
  renderCopyControl(v.key);
}


function refreshCopy(idx) {
  if (!_outputDir || !window._copies) return;
  const v = window._copies[idx];
  const tab = document.querySelectorAll('.copy-tab')[idx];
  const refreshIcon = tab.querySelector('.refresh-icon');
  refreshIcon.innerHTML = '<svg class="ico spin-ico"><use href="#i-loader"/></svg>';

  addLog('重新生成 ' + v.label + '...', 'accent');

  pywebview.api.regenerate_copy(_outputDir, v.key).then(r => {
    if (r.success) {
      window._copies[idx].text = r.text;
      window._copies[idx].banned = r.banned;
      switchCopy(idx);
      addLog('' + v.label + ' 重新生成完成 (' + r.text.length + '字)', 'success');
    } else {
      addLog('重新生成失败: ' + r.error, 'error');
    }
    // 原实现用 textContent 塞 HTML 字符串，界面上会显示成标签源码
    refreshIcon.innerHTML = '<svg class="ico"><use href="#i-refresh"/></svg>';
  });
}


function copyText(idx) {
  if (!window._copies || !window._copies[idx]) return;
  const text = window._copies[idx].text;
  const title = window._copies[idx].label;

  // webview 不是安全上下文（isSecureContext=false），navigator.clipboard 压根不存在。
  // 原来先调 clipboard.writeText，那行直接抛 TypeError，.then/.catch 都不会跑，
  // 结果就是点了复制什么都没发生、也没有任何提示。
  // 所以直接用 execCommand，它在 webview 里是有效的。
  if (doCopyFallback(text)) {
    addLog('已复制 ' + title + ' (' + text.length + ' 字)', 'success');
    return;
  }

  // 万一 execCommand 也不行，再试 clipboard API（某些环境可能有）
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(function () {
      addLog('已复制 ' + title + ' (' + text.length + ' 字)', 'success');
    }).catch(function (e) {
      addLog('复制失败：' + e + '，请手动选中文字复制', 'error');
    });
    return;
  }

  addLog('复制失败，请手动选中文字复制', 'error');
}


function doCopyFallback(text) {
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    // 放到屏幕外，避免页面跳动
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    ta.style.top = '0';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    ta.setSelectionRange(0, text.length);
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return !!ok;
  } catch (e) {
    return false;
  }
}



// ===== 文案历史版本 =====
function showCopyHistory(idx) {
  const v = window._copies && window._copies[idx];
  if (!v || !_outputDir) return;

  window._histVersion = v.key;
  window._histLabel = v.label;

  Modal.open({
    id: 'copyHistoryOverlay',
    icon: 'i-clock',
    title: v.label + ' · 历史版本',
    desc: '每次重新生成前会自动备份上一版，最多留 10 个',
    wide: true,
    body: '<div id="copyHistoryList"><p class="modal-note" style="text-align:center;">读取中…</p></div>',
    actions: [
      { text: '关闭', onclick: function () { Modal.close('copyHistoryOverlay'); } },
    ],
  });
  loadCopyHistory(v.key);
}


function loadCopyHistory(version) {
  const box = document.getElementById('copyHistoryList');
  if (!box) return;
  pywebview.api.list_copy_history(_outputDir, version).then(function (r) {
    if (!r || !r.success) {
      box.innerHTML = '<p class="modal-note" style="text-align:center;color:var(--error);">' +
        escapeHtml((r && r.error) || '读取失败') + '</p>';
      return;
    }
    const items = r.items || [];
    window._histItems = items;
    if (!items.length) {
      box.innerHTML = '<p class="modal-note" style="text-align:center;">这个版本还没有历史备份。<br>点标签上的刷新按钮重新生成，上一版会自动存下来。</p>';
      return;
    }
    box.innerHTML = items.map(function (it, i) {
      const t = it.time.replace('_', ' ');
      const timeText = t.length >= 15
        ? t.slice(0, 4) + '-' + t.slice(4, 6) + '-' + t.slice(6, 8) + ' ' +
          t.slice(9, 11) + ':' + t.slice(11, 13) + ':' + t.slice(13, 15)
        : it.time;
      return '<div class="hist-item">' +
        '<div class="hist-main">' +
          '<div class="hist-time">' + escapeHtml(timeText) + ' · ' + it.length + ' 字</div>' +
          '<div class="hist-preview">' + escapeHtml(it.text.slice(0, 70)) + '</div>' +
        '</div>' +
        '<button class="hi-btn" data-i="' + i + '" onclick="restoreHistory(this.dataset.i)">恢复</button>' +
        '<button class="hi-btn" data-i="' + i + '" onclick="deleteHistory(this.dataset.i)">删除</button>' +
      '</div>';
    }).join('');
  }).catch(function (e) {
    box.innerHTML = '<p class="modal-note" style="text-align:center;color:var(--error);">读取异常：' +
      escapeHtml(String(e)) + '</p>';
  });
}


function restoreHistory(i) {
  const items = window._histItems || [];
  const it = items[parseInt(i, 10)];
  const version = window._histVersion;
  if (!it || !version) return;

  pywebview.api.restore_copy_history(_outputDir, version, it.filename).then(function (r) {
    if (!r || !r.success) {
      addLog((r && r.error) || '恢复失败', 'error');
      return;
    }
    // 更新界面上的当前版本
    const idx = (window._copies || []).findIndex(function (x) { return x.key === version; });
    if (idx >= 0) {
      window._copies[idx].text = r.text;
      window._copies[idx].banned = [];
      switchCopy(idx);
    }
    Modal.close('copyHistoryOverlay');
    addLog('已恢复到 ' + it.time + ' 的版本（' + r.length + ' 字）', 'success');
  }).catch(function (e) { addLog('恢复异常：' + e, 'error'); });
}


function deleteHistory(i) {
  const items = window._histItems || [];
  const it = items[parseInt(i, 10)];
  const version = window._histVersion;
  if (!it || !version) return;

  pywebview.api.delete_copy_history(_outputDir, version, it.filename).then(function (r) {
    if (!r || !r.success) {
      addLog((r && r.error) || '删除失败', 'error');
      return;
    }
    addLog('已删除一条历史备份', 'accent');
    loadCopyHistory(version);
  }).catch(function () {});
}



// ===== 提示词模板 =====
function loadPromptTemplates(key) {
  key = key || 'v3';
  const box = document.getElementById(key + 'TplChips');
  if (!box) return;
  pywebview.api.list_prompt_templates().then(function (r) {
    const items = (r && r.items) || [];
    window._promptTemplates = items;
    if (!items.length) {
      box.innerHTML = '<span class="cp-empty">还没有保存的模板，写完提示词可点「存为模板」</span>';
      return;
    }
    box.innerHTML = '<span class="cp-tip">常用模板：</span>' + items.map(function (it, i) {
      return '<span class="cp-chip" data-i="' + i + '" onclick="usePromptTemplate(this.dataset.i, \'' + key + '\')" title="' +
        escapeHtml(it.prompt) + '">' + escapeHtml(it.name) +
        '<span class="cp-del" data-name="' + escapeHtml(it.name) +
        '" onclick="event.stopPropagation();deletePromptTemplate(this.dataset.name)">×</span></span>';
    }).join('');
  }).catch(function () {});
}


function usePromptTemplate(idx, key) {
  key = key || 'v3';
  const items = window._promptTemplates || [];
  const it = items[parseInt(idx, 10)];
  if (!it) return;
  const inp = document.getElementById(key + 'CustomPrompt');
  if (inp) {
    inp.value = it.prompt;
    inp.focus();
  }
}


function savePromptTemplate(key) {
  key = key || 'v3';
  const inp = document.getElementById(key + 'CustomPrompt');
  const prompt = inp ? inp.value.trim() : '';
  if (!prompt) {
    addLog('先在输入框写下提示词，再点「存为模板」', 'warn');
    return;
  }
  window._pendingPrompt = prompt;
  window._pendingPromptKey = key;

  Modal.open({
    id: 'tplNameOverlay',
    icon: 'i-download',
    title: '保存为模板',
    desc: '给这个提示词起个名字，下次可以一键套用',
    body: '<input id="tplNameInput" class="modal-input" placeholder="例如：促销风" maxlength="20" />' +
          '<p class="modal-note">将保存：' + escapeHtml(prompt.slice(0, 60)) +
          (prompt.length > 60 ? '…' : '') + '</p>',
    actions: [
      { text: '取消', onclick: function () { Modal.close('tplNameOverlay'); } },
      { text: '保存', primary: true, onclick: doSavePromptTemplate },
    ],
  });
  setTimeout(function () {
    const el = document.getElementById('tplNameInput');
    if (el) el.focus();
  }, 200);
}


function doSavePromptTemplate() {
  const el = document.getElementById('tplNameInput');
  const name = el ? el.value.trim() : '';
  if (!name) {
    addLog('请填写模板名称', 'warn');
    return;
  }
  pywebview.api.save_prompt_template(name, window._pendingPrompt || '').then(function (r) {
    if (!r || !r.success) {
      addLog((r && r.error) || '保存失败', 'error');
      return;
    }
    Modal.close('tplNameOverlay');
    addLog('模板「' + name + '」已保存', 'success');
    loadPromptTemplates(window._pendingPromptKey || 'v3');
  }).catch(function (e) { addLog('保存异常：' + e, 'error'); });
}


function deletePromptTemplate(name) {
  pywebview.api.delete_prompt_template(name).then(function (r) {
    if (!r || !r.success) {
      addLog((r && r.error) || '删除失败', 'error');
      return;
    }
    addLog('模板「' + name + '」已删除', 'accent');
    loadPromptTemplates();
  }).catch(function () {});
}
