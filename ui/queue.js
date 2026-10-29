/* 批量队列：入队、轮询、列表渲染 */
// ===== 批量队列 =====
// 串行执行，界面每 1.5 秒轮询一次状态；离开该 tab 时停止轮询省资源。
let _queueTimer = null;

function startQueuePolling() {
  if (_queueTimer) return;
  _queueTimer = setInterval(refreshQueue, 1500);
}

function stopQueuePolling() {
  if (_queueTimer) { clearInterval(_queueTimer); _queueTimer = null; }
}

function queueAdd() {
  const ta = document.getElementById('queueText');
  const text = ta ? ta.value : '';
  if (!text.trim()) { addLog('请先粘贴链接', 'warn'); return; }
  pywebview.api.queue_add(text).then(function (r) {
    if (!r || !r.success) { addLog((r && r.error) || '入队失败', 'error'); return; }
    let msg = '已加入 ' + r.added + ' 条';
    if (r.skipped) msg += '，跳过 ' + r.skipped + ' 条（重复或非链接）';
    msg += '，队列共 ' + r.total + ' 条';
    addLog(msg, 'success');
    if (ta) ta.value = '';
    refreshQueue();
  }).catch(function (e) { addLog('入队异常：' + e, 'error'); });
}

function queueStart() {
  const maxEl = document.getElementById('searchMax');
  const maxImgs = maxEl ? (parseInt(maxEl.value, 10) || 15) : 15;
  pywebview.api.queue_start(maxImgs).then(function (r) {
    if (!r || !r.success) { addLog((r && r.error) || '启动失败', 'error'); return; }
    addLog('批量处理已开始：串行执行，每条之间自动间隔几秒', 'accent');
    startQueuePolling();
  }).catch(function (e) { addLog('启动异常：' + e, 'error'); });
}

function queueStop() {
  pywebview.api.queue_stop().then(function () {
    addLog('已请求停止：当前这条跑完后不再开始新的', 'warn');
  }).catch(function () {});
}

function queueClear() {
  pywebview.api.queue_clear().then(function () { refreshQueue(); }).catch(function () {});
}

function refreshQueue() {
  pywebview.api.queue_status().then(function (s) {
    if (!s || !s.success) return;
    renderQueue(s);
    if (s.active) startQueuePolling();
    else stopQueuePolling();
  }).catch(function () {});
}

const QUEUE_ICON = {
  pending: '#i-link',
  running: '#i-loader',
  done: '#i-check',
  failed: '#i-x'
};
const QUEUE_LABEL = {
  pending: '排队中',
  running: '处理中',
  done: '已完成',
  failed: '失败'
};

function renderQueue(s) {
  const sum = document.getElementById('queueSummary');
  if (sum) {
    if (!s.total) {
      sum.textContent = '队列为空，先粘贴链接再点「加入队列」';
    } else {
      const finished = (s.done || 0) + (s.failed || 0);
      const pct = Math.round(finished / s.total * 100);
      let stats = '<span>共 ' + s.total + ' 条</span>';
      stats += '<span>已处理 ' + finished + '/' + s.total + '</span>';
      if (s.done) stats += '<span class="qs-ok">成功 ' + s.done + '</span>';
      if (s.failed) stats += '<span class="qs-fail">失败 ' + s.failed + '</span>';
      if (s.running) stats += '<span class="qs-run">进行中 ' + s.running + '</span>';
      if (s.pending) stats += '<span>等待 ' + s.pending + '</span>';
      if (s.single_running) stats += '<span class="qs-run">单条任务占用中</span>';
      sum.innerHTML =
        '<div class="queue-progress"><div class="queue-progress-bar" style="width:' + pct + '%"></div></div>' +
        '<div class="queue-stats">' + stats + '</div>';
    }
  }

  const list = document.getElementById('queueList');
  if (!list) return;
  if (!s.total) { list.innerHTML = ''; return; }

  list.innerHTML = (s.tasks || []).map(function (t) {
    const st = t.status || 'pending';
    let sub;
    if (st === 'done') {
      sub = (t.title || '') + (t.elapsed ? ' · ' + t.elapsed + 's' : '');
    } else if (st === 'failed') {
      sub = (t.stage ? t.stage + '：' : '') + (t.error || '未知错误');
    } else if (st === 'running') {
      sub = t.stage || '处理中…';
    } else {
      sub = t.url;
    }
    const titleText = t.title || QUEUE_LABEL[st] || t.url || '';
    const iconCls = st === 'running' ? ' spin-ico' : '';
    const openBtn = (st === 'done' && t.output_dir)
      ? '<button class="qi-btn" data-dir="' + escapeHtml(t.output_dir) + '" onclick="queueOpen(this.dataset.dir)">打开</button>'
      : '';
    return '<div class="queue-item ' + st + '">' +
      '<span class="qi-ico"><svg class="ico' + iconCls + '"><use href="' + (QUEUE_ICON[st] || '#i-link') + '"/></svg></span>' +
      '<div class="qi-main">' +
        '<div class="qi-title">' + escapeHtml(titleText) + '</div>' +
        '<div class="qi-sub">' + escapeHtml(sub) + '</div>' +
      '</div>' + openBtn +
    '</div>';
  }).join('');
}

function queueOpen(dir) {
  pywebview.api.queue_open_output(dir).then(function (r) {
    if (!r || !r.success) addLog((r && r.error) || '打开目录失败', 'error');
  }).catch(function () {});
}

