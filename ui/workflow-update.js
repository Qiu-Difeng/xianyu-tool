/**
 * update —— 从 workflow.js 拆出来的一块
 *
 * 函数实现原样搬过来，没改逻辑。全局状态（_outputDir 等）还在 workflow.js，
 * 这里只是在函数体内引用，调用时已经定义，不受加载顺序影响。
 */


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
