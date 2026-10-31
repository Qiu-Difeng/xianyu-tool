/**
 * multisource —— 从 workflow.js 拆出来的一块
 *
 * 函数实现原样搬过来，没改逻辑。全局状态（_outputDir 等）还在 workflow.js，
 * 这里只是在函数体内引用，调用时已经定义，不受加载顺序影响。
 */


function readMsCfg() {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem('msCfg') || '{}') || {}; } catch (e) { saved = {}; }
  const cfg = {};
  MS_SOURCES.forEach(function (s) {
    const item = saved[s.key] || {};
    cfg[s.key] = {
      on: item.on !== undefined ? !!item.on : true,
      num: Math.max(1, Math.min(50, parseInt(item.num, 10) || s.def)),
    };
  });
  return cfg;
}


function saveMsCfg() {
  const cfg = {};
  MS_SOURCES.forEach(function (s) {
    const cb = document.getElementById('src_' + s.key);
    const nm = document.getElementById('num_' + s.key);
    cfg[s.key] = {
      on: cb ? cb.checked : true,
      num: Math.max(1, Math.min(50, parseInt(nm ? nm.value : s.def, 10) || s.def)),
    };
  });
  try { localStorage.setItem('msCfg', JSON.stringify(cfg)); } catch (e) {}
  return cfg;
}


function msCfgHtml() {
  const cfg = readMsCfg();
  let html = '<div class="ms-cfg"><span class="ms-cfg-t">来源</span>';
  MS_SOURCES.forEach(function (s) {
    const c = cfg[s.key];
    html += '<label class="ms-cfg-item" title="' + escapeHtml(s.note) + '">' +
      '<input type="checkbox" id="src_' + s.key + '"' + (c.on ? ' checked' : '') +
      ' onchange="saveMsCfg()" /> ' + escapeHtml(s.label) +
      '</label>' +
      '<input type="number" class="ms-cfg-num" id="num_' + s.key + '" value="' + c.num +
      '" min="1" max="50" onchange="saveMsCfg()" />' +
      '<span class="ms-cfg-unit">张</span>';
  });
  html += '</div>';
  return html;
}


function msBoxHtml() {
  return '<div class="ms-box">' +
    '<div class="ms-head">' +
      '<div><b>多源聚合搜图</b>' +
        '<span class="ms-hint">勾选要用的来源，各自设抓多少张；某个源失败不影响其他</span></div>' +
      '<button class="btn-refresh ms-btn" id="msBtn" onclick="collectMultiSource()">' +
        '<svg class="ico"><use href="#i-search"/></svg> 开始搜图</button>' +
    '</div>' +
    msCfgHtml() +
    '<div id="msResult"></div>' +
  '</div>';
}


function collectMultiSource() {
  if (_msRunning) return;
  if (!_outputDir) {
    addLog('先处理一条商品链接，或者从历史记录里加载一个商品', 'warn');
    return;
  }

  _msRunning = true;
  const btn = document.getElementById('msBtn');
  const box = document.getElementById('msResult');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<svg class="ico spin-ico"><use href="#i-loader"/></svg> 搜索中…';
  }
  const cfg = saveMsCfg();
  const picked = MS_SOURCES.filter(function (s) { return cfg[s.key].on; });
  if (!picked.length) {
    _msRunning = false;
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = '<svg class="ico"><use href="#i-search"/></svg> 开始搜图';
    }
    addLog('至少勾选一个来源', 'warn');
    return;
  }

  const maxMap = {};
  MS_SOURCES.forEach(function (s) { maxMap[s.key] = cfg[s.key].num; });
  const totalWanted = picked.reduce(function (a, s) { return a + cfg[s.key].num; }, 0);
  const srcNames = picked.map(function (s) { return s.label; }).join(' + ');

  if (box) {
    box.innerHTML = '<p class="modal-note" style="text-align:center;">正在从 ' +
      escapeHtml(srcNames) + ' 搜索，目标 ' + totalWanted + ' 张，大约 20-40 秒…</p>';
  }
  addLog('开始搜图：' + srcNames + '，目标 ' + totalWanted + ' 张', 'accent');

  // 只剩百度识图，它按图片搜，不需要关键词
  pywebview.api.collect_extra_images(_outputDir, picked.map(function (s) { return s.key; }),
                                     maxMap, '')
    .then(function (r) {
    _msRunning = false;
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = '<svg class="ico"><use href="#i-search"/></svg> 重新搜图';
    }
    if (!r || !r.success) {
      const msg = (r && r.error) || '搜图失败';
      if (box) box.innerHTML = '<p class="modal-note" style="text-align:center;color:var(--error);">' + escapeHtml(msg) + '</p>';
      addLog('多源搜图失败：' + msg, 'error');
      return;
    }
    renderMsResult(r);
    // 只替换图片区，按钮和结果区保持原样
    pywebview.api.get_images(_outputDir, 'search').then(function (imgs) {
      const area = document.getElementById('searchImgArea');
      if (area) area.innerHTML = searchImgAreaHtml(imgs);
      addLog('补充图已刷新（' + (imgs ? imgs.length : 0) + ' 张）', 'success');
    });
  }).catch(function (e) {
    _msRunning = false;
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = '<svg class="ico"><use href="#i-search"/></svg> 开始搜图';
    }
    addLog('多源搜图异常：' + e, 'error');
  });
}


function renderMsResult(r) {
  const box = document.getElementById('msResult');
  if (!box) return;

  const ICON = { ok: 'i-check', empty: 'i-info', failed: 'i-error',
                 unavailable: 'i-alert', skipped: 'i-info' };
  const LABEL = { ok: '成功', empty: '没搜到', failed: '失败',
                  unavailable: '不可用', skipped: '已跳过' };

  let html = '<div class="ms-summary">' + escapeHtml(r.summary || '') + '</div>';
  html += '<div class="ms-sources">';
  (r.sources || []).forEach(function (s) {
    const st = s.status || 'failed';
    const cnt = (s.count !== undefined) ? s.count : (s.images || []).length;
    html += '<div class="ms-src ms-src-' + st + '">' +
      '<svg class="ico"><use href="#' + (ICON[st] || 'i-info') + '"/></svg>' +
      '<span class="ms-name">' + escapeHtml(s.name) + '</span>' +
      '<span class="ms-status">' + (LABEL[st] || st) + '</span>' +
      (cnt ? '<span class="ms-count">' + cnt + ' 张</span>' : '') +
      (s.cost ? '<span class="ms-cost">' + s.cost + 's</span>' : '') +
      '<span class="ms-msg">' + escapeHtml(s.message || '') + '</span>' +
      '</div>';
  });
  html += '</div>';
  box.innerHTML = html;
  addLog(r.summary || '搜图完成', r.total ? 'success' : 'warn');
}


function searchSupplementImages() {
  // 统一走 collectMultiSource：来源和数量都由「多源聚合搜图」那块配置决定。
  // 原来这里自己读 cfg.baidu_keyword.num 和 cfg.jd.num，这两个源已经删了，
  // 一点「重新搜索」就抛 TypeError，按钮永远转圈。
  if (!_outputDir) { setStatus('请先采集商品', 'error'); return; }
  collectMultiSource();
}
