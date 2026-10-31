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

let _copyPollTimer = null;

// === 检查更新 ===
let _updateChecking = false;

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

// 启动时自动检查更新（静默）
window.addEventListener('pywebviewready', () => {
  // Python端会在3秒后自动检查并通过_onSilentUpdateCheck回调通知
  // 这里不需要额外调用，Python端已经处理了
});


// ===== 多源聚合搜图（独立触发）=====
let _msRunning = false;

// 来源配置：勾选 + 每个源抓多少张
const MS_SOURCES = [
  { key: 'baidu_image', label: '百度识图', def: 15, note: '以图搜图，按图片找同款' },
];


// ===== 电商平台评价图：登录状态与登录 =====


// ===== 手动框选去水印 =====


