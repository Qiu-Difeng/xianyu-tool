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
  if (!url) { setStatus('请输入链接！', 'error'); return; }

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

  const searchMax = parseInt(document.getElementById('searchMax').value) || 15;

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
  // 补充图
  document.getElementById('pane4').innerHTML = '<div class="empty"><span class="emoji"><svg class="ico"><use href="#i-search"/></svg></span><p>点击下方按钮搜索补充图</p>' +
    '<button class="btn-refresh" id="searchSupplementBtn" onclick="searchSupplementImages()" style="margin-top:12px;"><svg class="ico"><use href="#i-search"/></svg> 搜索补充图</button></div>';
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
    html += '<div class="img-card" style="animation-delay:' + (i * 0.06) + 's"><img src="' + escapeHtml(src) + '" loading="lazy" /></div>';
  });
  return html + '</div>';
}

function renderSearchImages(imgs) {
  // 外框（搜图按钮 + 结果区）+ 图片区，两块分开，
  // 刷新图片时只替换 #searchImgArea，不动按钮和结果
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
    html += '<div class="img-card" style="animation-delay:' + (i * 0.06) + 's"><img src="' + escapeHtml(src) + '" loading="lazy" /></div>';
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
  // V3自定义提示词区域
  html += '<div class="custom-prompt-area">';
  html += '<div class="cp-label"><svg class="ico"><use href="#i-info"/></svg> V3 自定义提示词（可选，不填则默认重写）</div>';
  html += '<div class="cp-row">';
  html += '<input type="text" id="v3CustomPrompt" class="cp-input" placeholder="例如：突出性价比，加上使用场景，语气活泼一点" />';
  html += '<button class="btn-refresh cp-btn" onclick="savePromptTemplate()"><svg class="ico"><use href="#i-download"/></svg> 存为模板</button>';
  html += '<button class="btn-refresh cp-btn" onclick="v3CustomRewrite()"><svg class="ico"><use href="#i-refresh"/></svg> 按提示词重写</button>';
  html += '</div>';
  html += '<div id="v3TplChips" class="cp-chips"></div>';
  html += '</div>';
  // 模板列表异步填充（每次渲染文案都会重建这块）
  setTimeout(loadPromptTemplates, 80);
  window._copies = data.versions;
  setTimeout(() => { switchCopy(0); }, 50);
  return html;
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
  if (!window._copies) return;
  const text = window._copies[idx].text;
  const title = window._copies[idx].label;
  // 用clipboard API
  navigator.clipboard.writeText(text).then(() => {
    addLog('已复制 ' + title + ' (' + text.length + '字)', 'success');
  }).catch(() => {
    // fallback
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    addLog('已复制 ' + title, 'success');
  });
}

function v3CustomRewrite() {
  if (!_outputDir || !window._copies) return;
  const prompt = document.getElementById('v3CustomPrompt').value.trim();
  if (!prompt) {
    setStatus('请输入自定义提示词', 'error');
    return;
  }
  addLog('V3按自定义提示词重写...', 'accent');
  pywebview.api.regenerate_copy(_outputDir, 'v3', prompt).then(r => {
    if (r.success) {
      window._copies[2].text = r.text;
      window._copies[2].banned = r.banned;
      switchCopy(2);
      addLog('V3自定义重写完成 (' + r.text.length + '字)', 'success');
    } else {
      addLog('V3重写失败: ' + r.error, 'error');
    }
  });
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
  if (!_outputDir) { setStatus('请先采集商品', 'error'); return; }
  const maxImg = parseInt(document.getElementById('searchMax').value) || 15;
  const btn = document.getElementById('searchSupplementBtn');
  if (btn) { btn.classList.add('loading'); btn.disabled = true; }
  addLog('开始搜索补充图（最多' + maxImg + '张）...', 'accent');

  pywebview.api.refresh_search(_outputDir, maxImg).then(r => {
    if (btn) { btn.classList.remove('loading'); btn.disabled = false; }
    if (r.success) {
      addLog('搜到 ' + r.count + ' 张补充图', 'success');
      pywebview.api.get_images(_outputDir, 'search').then(imgs => {
        document.getElementById('pane4').innerHTML = renderSearchImages(imgs);
      });
    } else {
      addLog('搜索失败: ' + r.error, 'error');
    }
  });
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
function loadPromptTemplates() {
  const box = document.getElementById('v3TplChips');
  if (!box) return;
  pywebview.api.list_prompt_templates().then(function (r) {
    const items = (r && r.items) || [];
    window._promptTemplates = items;
    if (!items.length) {
      box.innerHTML = '<span class="cp-empty">还没有保存的模板，写完提示词可点「存为模板」</span>';
      return;
    }
    box.innerHTML = '<span class="cp-tip">常用模板：</span>' + items.map(function (it, i) {
      return '<span class="cp-chip" data-i="' + i + '" onclick="usePromptTemplate(this.dataset.i)" title="' +
        escapeHtml(it.prompt) + '">' + escapeHtml(it.name) +
        '<span class="cp-del" data-name="' + escapeHtml(it.name) +
        '" onclick="event.stopPropagation();deletePromptTemplate(this.dataset.name)">×</span></span>';
    }).join('');
  }).catch(function () {});
}

function usePromptTemplate(idx) {
  const items = window._promptTemplates || [];
  const it = items[parseInt(idx, 10)];
  if (!it) return;
  const inp = document.getElementById('v3CustomPrompt');
  if (inp) {
    inp.value = it.prompt;
    inp.focus();
  }
}

function savePromptTemplate() {
  const inp = document.getElementById('v3CustomPrompt');
  const prompt = inp ? inp.value.trim() : '';
  if (!prompt) {
    addLog('先在输入框写下提示词，再点「存为模板」', 'warn');
    return;
  }
  window._pendingPrompt = prompt;

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
    loadPromptTemplates();
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

function msBoxHtml() {
  return '<div class="ms-box">' +
    '<div class="ms-head">' +
      '<div><b>多源聚合搜图</b>' +
        '<span class="ms-hint">从百度识图、百度图片多个来源收集同款图，某个源失败不影响其他</span></div>' +
      '<button class="btn-refresh ms-btn" id="msBtn" onclick="collectMultiSource()">' +
        '<svg class="ico"><use href="#i-search"/></svg> 开始搜图</button>' +
    '</div>' +
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
  if (box) {
    box.innerHTML = '<p class="modal-note" style="text-align:center;">正在逐个来源搜索，大约需要 20-30 秒…</p>';
  }
  addLog('开始多源搜图（识图 + 关键词，约 25 秒）', 'accent');

  pywebview.api.collect_extra_images(_outputDir, 15).then(function (r) {
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
