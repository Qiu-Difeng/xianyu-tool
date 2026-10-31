/* 历史记录：列出处理过的商品，可重新加载到界面查看
   数据来自 %TEMP%\xianyu_tool\output\{商品ID}\result.json */

function showHistoryModal() {
  Modal.open({
    id: 'historyOverlay',
    icon: 'i-grid',
    title: '历史记录',
    desc: '处理过的商品都保留在本机，可随时重新查看',
    wide: true,
    body: '<div id="historyList" class="history-list">' +
            '<p class="modal-note" style="text-align:center;">读取中…</p>' +
          '</div>',
    actions: [
      { text: '刷新', onclick: loadHistory },
      { text: '关闭', onclick: function () { Modal.close('historyOverlay'); } },
    ],
    footer: '结果保存在系统临时目录，清理临时文件时可能被删除',
  });
  loadHistory();
}

function loadHistory() {
  const box = document.getElementById('historyList');
  if (!box) return;
  pywebview.api.list_history(50).then(function (r) {
    if (!r || !r.success) {
      box.innerHTML = '<p class="modal-note" style="text-align:center;color:var(--error);">' +
        escapeHtml((r && r.error) || '读取失败') + '</p>';
      return;
    }
    if (!r.items || !r.items.length) {
      box.innerHTML = '<p class="modal-note" style="text-align:center;">还没有处理记录，先在上方粘贴链接跑一条</p>';
      return;
    }
    window._historyItems = r.items;
    box.innerHTML = r.items.map(function (it, i) {
      const meta = [
        it.price ? '¥' + it.price : '',
        it.images + ' 张图',
        it.has_copies ? '含文案' : '无文案',
        it.mtime_text,
      ].filter(Boolean).join(' · ');
      return '<div class="history-item">' +
        '<div class="hi-main">' +
          '<div class="hi-title">' + escapeHtml(it.title) + '</div>' +
          '<div class="hi-meta">' + escapeHtml(meta) + '</div>' +
        '</div>' +
        '<button class="hi-btn" data-i="' + i + '" onclick="loadHistoryItem(this.dataset.i)">加载</button>' +
        '<button class="hi-btn" data-dir="' + escapeHtml(it.output_dir) + '" onclick="openHistoryDir(this.dataset.dir)">目录</button>' +
        '<button class="hi-btn hi-btn-del" data-i="' + i + '" onclick="deleteHistoryItem(this.dataset.i)" title="删除这条记录">删</button>' +
      '</div>';
    }).join('');
  }).catch(function (e) {
    box.innerHTML = '<p class="modal-note" style="text-align:center;color:var(--error);">读取异常：' +
      escapeHtml(String(e)) + '</p>';
  });
}

function loadHistoryItem(idx) {
  const items = window._historyItems || [];
  const it = items[parseInt(idx, 10)];
  if (!it) return;

  _outputDir = it.output_dir;

  const pane0 = document.getElementById('pane0');
  if (pane0) {
    pane0.innerHTML =
      '<div class="info-card">' +
        '<div class="info-row"><span class="label">标题</span><span class="value">' + escapeHtml(it.title) + '</span></div>' +
        '<div class="info-row"><span class="label">价格</span><span class="value">' + escapeHtml(it.price || '-') + '</span></div>' +
        '<div class="info-row"><span class="label">卖家</span><span class="value">' + escapeHtml(it.seller || '-') + '</span></div>' +
        '<div class="info-row"><span class="label">商品ID</span><span class="value">' + escapeHtml(it.product_id) + '</span></div>' +
      '</div>' +
      '<div class="info-desc">' + escapeHtml(it.desc || '(无描述)') + '</div>';
  }

  pywebview.api.get_images(it.output_dir, 'original').then(function (imgs) {
    const p = document.getElementById('pane1');
    if (p) p.innerHTML = renderImagesWithSave(imgs, 'original');
  });
  pywebview.api.get_images(it.output_dir, 'clean').then(function (imgs) {
    const p = document.getElementById('pane2');
    if (p) p.innerHTML = renderImagesWithSave(imgs, 'clean');
  });
  pywebview.api.get_copies(it.output_dir).then(function (data) {
    const p = document.getElementById('pane3');
    if (p) p.innerHTML = renderCopies(data);
  });

  // 补充图：渲染搜图区（之前历史记录加载后这块是空白）
  const p4 = document.getElementById('pane4');
  if (p4) p4.innerHTML = renderSearchImages([]);

  // 视频：根据有没有 video_url 给提示（之前完全没渲染，点进去一片空白）
  const p5 = document.getElementById('pane5');
  if (p5) {
    p5.innerHTML = it.video_url
      ? '<div class="empty"><span class="emoji"><svg class="ico"><use href="#i-video"/></svg></span>' +
        '<p>该商品有视频</p><button class="btn-refresh" onclick="downloadVideo()" ' +
        'style="margin-top:12px;"><svg class="ico"><use href="#i-download"/></svg> 保存视频</button></div>'
      : '<div class="empty"><span class="emoji"><svg class="ico"><use href="#i-video"/></svg></span>' +
        '<p>该商品没有视频</p></div>';
  }

  Modal.close('historyOverlay');
  switchTab(0);
  addLog('已加载历史记录：' + it.title, 'accent');
}

function openHistoryDir(dir) {
  pywebview.api.queue_open_output(dir).then(function (r) {
    if (!r || !r.success) addLog((r && r.error) || '打开目录失败', 'error');
  }).catch(function () {});
}


// ===== 删除历史记录 =====
function deleteHistoryItem(i) {
  const items = window._historyItems || [];
  const it = items[parseInt(i, 10)];
  if (!it) return;

  Modal.open({
    id: 'delHistOverlay',
    icon: 'i-alert',
    keepOthers: true,      // 子弹窗：保留下面的历史列表，用户才知道在删哪条
    title: '删除这条记录？',
    desc: '商品图片、文案和结果文件会一起删掉，删了找不回来',
    body: '<p class="modal-note" style="text-align:center;">' + escapeHtml(it.title) +
          '<br><span style="font-size:11px;color:var(--text-faint);">' +
          escapeHtml(it.product_id) + ' · ' + it.images + ' 张图</span></p>',
    actions: [
      { text: '取消', onclick: function () { Modal.close('delHistOverlay'); } },
      { text: '确认删除', primary: true, onclick: function () { doDeleteHistory(it.output_dir, it.title); } },
    ],
  });
}

function doDeleteHistory(dir, title) {
  pywebview.api.delete_history_item(dir).then(function (r) {
    Modal.close('delHistOverlay');
    if (!r || !r.success) {
      addLog('删除失败：' + ((r && r.error) || '未知错误'), 'error');
      return;
    }
    addLog('已删除记录：' + title, 'accent');
    loadHistory();
  }).catch(function (e) {
    Modal.close('delHistOverlay');
    addLog('删除异常：' + e, 'error');
  });
}
