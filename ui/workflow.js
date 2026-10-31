/* 主流程：链接处理、图片与文案渲染、标签切换、更新检查 */
let _outputDir = null;
let _copiesData = null;

function switchTab(idx) {
  document.querySelectorAll('.tab-btn').forEach((b, i) => b.classList.toggle('active', i === idx));
  document.querySelectorAll('.tab-pane').forEach((p, i) => p.classList.toggle('active', i === idx));
  // 批量 tab：进入时立即刷新并在运行中开启轮询；离开时停掉，省资源
  if (idx === 6) {
    refreshQueue();
  } else {
    stopQueuePolling();
  }

  // 补充图 tab：第一次进来要把搜图区渲染出来。
  // 之前只有「跑完商品」或「点搜索按钮」才填 pane4，
  // 用户直接点这个 tab 看到的是空白一片。
  if (idx === 4) {
    const pane = document.getElementById('pane4');
    if (pane && !pane.querySelector('.ms-box')) {
      pane.innerHTML = renderSearchImages([]);
    }
  }
}

function addLog(msg, type) {
  const box = document.getElementById('logBox');
  const line = document.createElement('div');
  line.className = 'log-line' + (type ? ' ' + type : '');
  line.textContent = msg;
  box.appendChild(line);
  box.scrollTop = box.scrollHeight;
}
function clearLog() { document.getElementById('logBox').innerHTML = ''; }
function setStatus(msg, state) {
  document.getElementById('statusText').textContent = msg;
  document.getElementById('statusDot').className = 'status-dot' + (state ? ' ' + state : '');
}
function setProgress(pct) { document.getElementById('progressBar').style.width = pct + '%'; }
function setBtnLoading(loading) {
  const btn = document.getElementById('runBtn');
  btn.classList.toggle('loading', loading);
  btn.disabled = loading;
  btn.querySelector('.btn-text').textContent = loading ? '运行中...' : '开始';
}

function runTool() {
  const url = document.getElementById('urlInput').value.trim();
  if (!url) {
    setStatus('请输入链接！', 'error');
    addLog('还没填链接，把闲鱼商品链接粘贴到上面的输入框', 'warn');
    document.getElementById('urlInput').focus();
    return;
  }

  // 没有 Key 就先拦住，别让用户白等一轮
  if (_keyConfigured === false) {
    setStatus('请先配置 API Key', 'error');
    addLog('还没有配置 API Key，先填一下再开始', 'error');
    showKeyModal(true);
    return;
  }

  // 简单链接验证
  if (!url.match(/https?:\/\/[\w\.-]+/i)) {
    setStatus('链接格式不正确，请粘贴闲鱼分享链接', 'error');
    addLog('链接格式不正确', 'error');
    return;
  }

  // 补充图数量改到「补充图」页里按来源配置，主流程用默认值
  const searchMax = 15;

  clearLog();
  addLog('开始处理，和小新小白一起漫步吧~', 'accent');
  setStatus('正在启动浏览器...', 'running');
  setProgress(5);
  setBtnLoading(true);

  // 进度模拟（实际进度由各阶段回调驱动）
  let fakeProgress = 5;
  const progressTimer = setInterval(() => {
    if (fakeProgress < 90) {
      fakeProgress += 1;
      setProgress(fakeProgress);
      if (fakeProgress === 15) setStatus('解析闲鱼链接...', 'running');
      if (fakeProgress === 30) setStatus('下载商品图片...', 'running');
      if (fakeProgress === 50) setStatus('去水印 + 生成文案...', 'running');
      if (fakeProgress === 80) setStatus('整理结果...', 'running');
    }
  }, 800);

  for (let i = 0; i < 6; i++) {
    document.getElementById('pane' + i).innerHTML = '<div class="empty"><span class="emoji spinning"></span><p>处理中，请稍候...</p></div>';
  }

  pywebview.api.run_tool(url, searchMax).then(result => {
    clearInterval(progressTimer);
    setBtnLoading(false);
    if (result && result.success) {
      setProgress(100);
      addLog('全流程完成！耗时 ' + result.elapsed + '秒', 'success');
      setStatus('完成！耗时 ' + result.elapsed + '秒', 'done');
      displayResult(result);
    } else {
      const errMsg = (result && result.error) ? result.error : '未知错误，请检查链接是否有效';
      addLog('处理失败: ' + errMsg, 'error');
      setStatus('失败: ' + errMsg.substring(0, 30), 'error');
      setProgress(0);
    }
  }).catch(err => {
    clearInterval(progressTimer);
    setBtnLoading(false);
    const errMsg = String(err).substring(0, 100);
    addLog('错误: ' + errMsg, 'error');
    setStatus('运行出错', 'error');
    setProgress(0);
  });
}

function displayResult(result) {
  _outputDir = result.output_dir;

  // 商品信息 + 耗时
  let html = '<div class="info-card">';
  const info = [
    ['标题', result.title],
    ['价格', '¥' + result.price],
    ['卖家', result.seller],
    ['商品ID', result.item_id],
    ['文案字数', result.desc_len + ' 字'],
  ];
  info.forEach(([label, value]) => {
    html += '<div class="info-row"><div class="label">' + escapeHtml(label) + '</div><div class="value">' + escapeHtml(value) + '</div></div>';
  });
  html += '</div>';
  if (result.desc) {
    html += '<div class="info-desc">' + escapeHtml(result.desc) + '</div>';
  }
  // 耗时面板
  if (result.timings) {
    const t = result.timings;
    // timings 里可能有非数字值（如文案超时写入的 "超时"），
    // 直接 Math.max 会得到 NaN，导致所有进度条宽度变成无效值
    const numeric = Object.values(t).filter(function (v) { return typeof v === 'number' && v > 0; });
    const maxT = numeric.length ? Math.max.apply(null, numeric) : 1;
    html += '<div class="timings"><h4><svg class="ico"><use href="#i-loader"/></svg> 各模块耗时</h4>';
    for (const [name, val] of Object.entries(t)) {
      const isNum = (typeof val === 'number');
      const pct = isNum ? Math.min(100, (val / maxT * 100)).toFixed(0) : 0;
      html += '<div class="timing-row"><span class="timing-name">' + escapeHtml(name) + '</span>' +
        '<div class="timing-bar"><div class="timing-bar-fill" style="width:' + pct + '%"></div></div>' +
        '<span class="timing-val">' + (isNum ? val + '秒' : escapeHtml(String(val))) + '</span></div>';
    }
    html += '</div>';
  }
  document.getElementById('pane0').innerHTML = html;

  // 原图
  pywebview.api.get_images(result.output_dir, 'original').then(imgs => {
    document.getElementById('pane1').innerHTML = renderImagesWithSave(imgs, 'original');
  });
  // 去水印
  pywebview.api.get_images(result.output_dir, 'clean').then(imgs => {
    document.getElementById('pane2').innerHTML = renderImagesWithSave(imgs, 'clean');
  });
  // 文案 - 先显示生成中，轮询检查状态
  document.getElementById('pane3').innerHTML = '<div class="empty"><span class="emoji spinning"><svg class="ico"><use href="#i-pen"/></svg></span><p>文案后台生成中，预计30-60秒...</p></div>';
  startCopyPolling(result.output_dir);
  // 补充图：直接用新版搜图区（带来源配置 + 按钮）。
  // 原来这里塞的是旧版空状态，一个孤零零的按钮挂在左边、提示还写着「点击下方按钮」，
  // 和新版 pane4 的布局对不上，看着别扭。
  document.getElementById('pane4').innerHTML = renderSearchImages([]);
  // 视频
  if (result.video_url) {
    document.getElementById('pane5').innerHTML = '<div class="empty"><span class="emoji"><svg class="ico"><use href="#i-video"/></svg></span><p>该商品有视频</p>' +
      '<button class="btn-refresh" onclick="downloadVideo()" style="margin-top:12px;"><svg class="ico"><use href="#i-download"/></svg> 保存视频</button></div>';
  } else {
    document.getElementById('pane5').innerHTML = '<div class="empty"><span class="emoji"><svg class="ico"><use href="#i-video"/></svg></span><p>该商品没有视频</p></div>';
  }
}

function renderImagesWithSave(imgs, subfolder) {
  if (!imgs || imgs.length === 0) return '<div class="empty"><span class="emoji"><svg class="ico"><use href="#i-image"/></svg></span><p>无图片</p></div>';
  let html = '<div class="img-toolbar"><span class="img-count">共 ' + imgs.length + ' 张</span>' +
    '<button class="btn-save" onclick="saveImages(\'' + subfolder + '\')"><svg class="ico"><use href="#i-download"/></svg> 保存到...</button></div>';
  html += '<div class="img-grid">';
  imgs.forEach((src, i) => {
    html += '<div class="img-card" style="animation-delay:' + (i * 0.06) + 's">' +
      '<img src="' + escapeHtml(src) + '" loading="lazy" />' +
      '</div>';
  });
  return html + '</div>';
}

function renderSearchImages(imgs) {
  return msBoxHtml() + '<div id="searchImgArea">' + searchImgAreaHtml(imgs) + '</div>';
}

function searchImgAreaHtml(imgs) {
  if (!imgs || imgs.length === 0) {
    return '<div class="empty"><span class="emoji"><svg class="ico"><use href="#i-search"/></svg></span><p>还没有补充图，点上面的「开始搜图」</p></div>';
  }
  let html = '<div class="search-toolbar"><span class="img-count">共 ' + imgs.length + ' 张补充图</span>' +
    '<button class="btn-save" onclick="saveImages(\'search\')"><svg class="ico"><use href="#i-download"/></svg> 保存到...</button>' +
    '<button class="btn-refresh" id="refreshSearchBtn" onclick="searchSupplementImages()"><span class="refresh-text"><svg class="ico"><use href="#i-refresh"/></svg> 重新搜索</span></button></div>';
  html += '<div class="img-grid">';
  imgs.forEach((src, i) => {
    html += '<div class="img-card" style="animation-delay:' + (i * 0.06) + 's">' +
      '<img src="' + escapeHtml(src) + '" loading="lazy" />' +
      '</div>';
  });
  return html + '</div>';
}

function saveImages(subfolder) {
  if (!_outputDir) return;
  pywebview.api.save_images(_outputDir, subfolder).then(r => {
    if (r.success) addLog('已保存 ' + r.saved + ' 个文件到所选目录', 'success');
    else if (r.error !== '已取消') addLog('保存失败: ' + r.error, 'error');
  });
}

let _copyPollTimer = null;
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


function downloadVideo() {
  if (!_outputDir) return;
  addLog('<svg class="ico"><use href="#i-download"/></svg> 正在下载视频...', 'accent');
  pywebview.api.download_video(_outputDir).then(r => {
    if (r.success) {
      addLog('视频已保存: ' + r.path, 'success');
    } else {
      if (r.error !== '已取消') addLog('视频下载失败: ' + r.error, 'error');
    }
  });
}

function searchSupplementImages() {
  // 统一走 collectMultiSource：来源和数量都由「多源聚合搜图」那块配置决定。
  // 原来这里自己读 cfg.baidu_keyword.num 和 cfg.jd.num，这两个源已经删了，
  // 一点「重新搜索」就抛 TypeError，按钮永远转圈。
  if (!_outputDir) { setStatus('请先采集商品', 'error'); return; }
  collectMultiSource();
}

// === 检查更新 ===
let _updateChecking = false;

function checkUpdate(manual) {
  if (_updateChecking) return;
  _updateChecking = true;

  const btn = document.getElementById('updateBtn');
  const dot = document.getElementById('updateDot');
  const text = document.getElementById('updateBtnText');

  btn.classList.add('checking');
  dot.className = 'dot checking';
  text.textContent = '检查中...';

  pywebview.api.check_update().then(result => {
    btn.classList.remove('checking');
    _updateChecking = false;

    if (result.error) {
      dot.className = 'dot';
      text.textContent = '检查更新';
      if (manual) {
        showUpdateModal({error: result.error});
      }
      return;
    }

    if (result.has_update) {
      dot.className = 'dot has-update';
      text.textContent = '新版本 v' + result.latest_version;
      showUpdateModal(result);
    } else {
      dot.className = 'dot';
      text.textContent = '检查更新';
      if (manual) {
        showUpdateModal({no_update: true, current: result.current_version});
      }
    }
  }).catch(err => {
    btn.classList.remove('checking');
    _updateChecking = false;
    dot.className = 'dot';
    text.textContent = '检查更新';
    if (manual) {
      showUpdateModal({error: err.toString()});
    }
  });
}

// 启动时静默检查更新的回调
window._onSilentUpdateCheck = function(result) {
  if (result && result.has_update) {
    // 检查是否已跳过该版本
    if (isVersionSkipped(result.latest_version)) {
      return; // 用户已跳过此版本，不提示
    }
    const dot = document.getElementById('updateDot');
    const text = document.getElementById('updateBtnText');
    dot.className = 'dot has-update';
    text.textContent = '新版本 v' + result.latest_version;
    // 静默模式下只在日志区域显示提示，不弹窗
    addLog('发现新版本 v' + result.latest_version + '，点击右上角按钮查看详情', 'accent');
  }
};

// 下载进度回调
window._updateDownloadProgress = function(pct) {
  const bar = document.getElementById('updateDownloadBar');
  if (bar) {
    bar.style.width = pct + '%';
  }
  const text = document.getElementById('updateDownloadPct');
  if (text) {
    text.textContent = pct + '%';
  }
};

function showUpdateModal(info) {
  // 三种状态（出错 / 已最新 / 有新版）共用同一套工厂骨架
  if (info.error) {
    Modal.open({
      id: 'updateOverlay',
      icon: 'i-globe',
      title: '检查更新失败',
      desc: '网络连接失败，请稍后重试',
      body: '<p class="modal-note" style="text-align:center;">' + escapeHtml(info.error) + '</p>',
      actions: [{ text: '知道了', primary: true, onclick: () => Modal.close('updateOverlay') }],
    });
    return;
  }

  if (info.no_update) {
    Modal.open({
      id: 'updateOverlay',
      icon: 'i-check',
      title: '已是最新版本',
      desc: '当前版本 v' + escapeHtml(info.current || '1.0') + '，无需更新',
      actions: [{ text: '好的', primary: true, onclick: () => Modal.close('updateOverlay') }],
    });
    return;
  }

  const latest = String(info.latest_version || '');
  const notes = info.release_notes || '';
  const notesHtml = notes
    ? '<div class="code-box" style="margin-bottom:16px;max-height:150px;overflow-y:auto;">' +
      '<pre class="code-pre">' +
      escapeHtml(notes) + '</pre></div>'
    : '';

  const body =
    '<p class="modal-desc" style="color:var(--accent2);font-size:16px;font-weight:600;margin-bottom:4px;">v' + escapeHtml(latest) + '</p>' +
    '<p class="modal-desc" style="font-size:12px;margin-bottom:16px;">当前版本 v' + escapeHtml(info.current_version) + '</p>' +
    notesHtml +
    '<div id="updateDownloadArea" style="margin-bottom:16px;">' +
      '<div style="background:var(--panel-bg);border-radius:8px;height:8px;overflow:hidden;margin-bottom:6px;">' +
        '<div id="updateDownloadBar" style="height:100%;width:0%;border-radius:8px;background:var(--accent-grad);transition:width 0.3s ease;"></div>' +
      '</div>' +
      '<div style="display:flex;justify-content:space-between;font-size:11px;color:var(--text-dim);">' +
        '<span id="updateDownloadStatus">点击下方按钮开始下载</span>' +
        '<span id="updateDownloadPct">0%</span>' +
      '</div>' +
    '</div>';

  Modal.open({
    id: 'updateOverlay',
    icon: 'i-sparkle',
    title: '发现新版本',
    body: body,
    actions: [
      { text: '跳过此版本', onclick: () => skipUpdate(latest.replace(/[^0-9A-Za-z.]/g, '')) },
      { text: '稍后', onclick: () => Modal.close('updateOverlay') },
      { text: '<svg class="ico"><use href="#i-download"/></svg> 下载更新', primary: true, id: 'downloadUpdateBtn', onclick: downloadUpdate },
    ],
  });
}

function downloadUpdate() {
  const btn = document.getElementById('downloadUpdateBtn');
  const status = document.getElementById('updateDownloadStatus');
  btn.disabled = true;
  btn.textContent = '打开中...';
  status.textContent = '正在打开浏览器...';

  pywebview.api.download_update().then(result => {
    if (result.success) {
      status.textContent = '已打开浏览器下载';
      btn.innerHTML = '<svg class="ico"><use href="#i-check"/></svg> 已打开浏览器';

      // 替换弹窗内容为提示
      const overlay = document.getElementById('updateOverlay');
      if (overlay) {
        overlay.innerHTML = `
          <div style="background:var(--glass);border:1px solid var(--glass-border);border-radius:20px;padding:30px;max-width:440px;width:90%;box-shadow:var(--shadow);animation:fadeInUp 0.4s ease;text-align:center;">
            <div style="font-size:44px;margin-bottom:14px;"><svg class="ico"><use href="#i-globe"/></svg></div>
            <h2 style="color:var(--text);margin-bottom:8px;font-size:20px;">已打开浏览器</h2>
            <p style="color:var(--text-dim);font-size:13px;margin-bottom:8px;line-height:1.6;">浏览器正在下载安装包，下载完成后运行安装即可。</p>
            <p style="color:var(--accent2);font-size:12px;margin-bottom:20px;">安装前请先关闭当前程序</p>
            <button onclick="document.getElementById('updateOverlay').remove()" style="flex:1;padding:12px;border-radius:10px;border:1px solid var(--glass-border);background:transparent;color:var(--text-dim);font-size:14px;cursor:pointer;width:100%;">知道了</button>
          </div>
        `;
      }
    } else {
      status.textContent = '打开失败';
      btn.disabled = false;
      btn.innerHTML = '<svg class="ico"><use href="#i-download"/></svg> 重新尝试';
      status.style.color = 'var(--error)';
      status.textContent = '失败: ' + (result.error || '未知错误');
    }
  }).catch(err => {
    btn.disabled = false;
    btn.innerHTML = '<svg class="ico"><use href="#i-download"/></svg> 重新下载';
    status.style.color = 'var(--error)';
    status.textContent = '失败: ' + err.toString();
  });
}

function runInstaller(path) {
  pywebview.api.open_file(path).then(r => {
    if (r.success) {
      addLog('已启动安装程序，请关闭当前程序后继续安装', 'accent');
      document.getElementById('updateOverlay').remove();
    } else {
      addLog('启动安装程序失败: ' + r.error, 'error');
    }
  });
}

// 跳过此版本：记录到后端状态文件，不再提示
function skipUpdate(version) {
  patchUiState({ skip_version: version });
  addLog('已跳过 v' + version + '，下次有更新仍会提示', 'accent');
  const ov = document.getElementById('updateOverlay');
  if (ov) ov.remove();
}

// 检查是否已跳过该版本
function isVersionSkipped(version) {
  return _uiState.skip_version === version;
}

// 启动时自动检查更新（静默）
window.addEventListener('pywebviewready', () => {
  // Python端会在3秒后自动检查并通过_onSilentUpdateCheck回调通知
  // 这里不需要额外调用，Python端已经处理了
});


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


// ===== 多源聚合搜图（独立触发）=====
let _msRunning = false;

// 来源配置：勾选 + 每个源抓多少张
const MS_SOURCES = [
  { key: 'baidu_image', label: '百度识图', def: 15, note: '以图搜图，按图片找同款' },
];

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


// ===== 电商平台评价图：登录状态与登录 =====



// ===== 手动框选去水印 =====



