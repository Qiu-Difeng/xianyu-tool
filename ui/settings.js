/* 配置备份与恢复 */
// ===== 配置备份 / 恢复 =====
// 换电脑或重装时不用重新配 Key 与模型：导出成一段 JSON，粘贴回去即可。
function showConfigExport() {
  Modal.open({
    id: 'exportOverlay',
    icon: 'i-download',
    title: '备份配置',
    desc: '复制下面的内容保存好，换电脑时可粘贴恢复',
    wide: true,
    body:
      '<div class="warn-box">' +
        '<p class="warn-text">' +
        '<svg class="ico"><use href="#i-alert"/></svg> 内容包含你的 API Key，请勿发给他人或公开分享</p>' +
      '</div>' +
      '<textarea id="exportText" class="modal-input mono modal-textarea-lg" readonly></textarea>',
    actions: [
      { text: '<svg class="ico"><use href="#i-copy"/></svg> 复制配置', primary: true, id: 'copyCfgBtn', onclick: copyConfig },
      { text: '关闭', onclick: () => Modal.close('exportOverlay') },
    ],
  });

  pywebview.api.export_config().then(function (r) {
    const ta = document.getElementById('exportText');
    if (!ta) return;
    if (!r || !r.success) {
      ta.value = '导出失败：' + ((r && r.error) || '未知错误');
      return;
    }
    ta.value = r.json;
    window._exportJson = r.json;
  }).catch(function (e) {
    const ta = document.getElementById('exportText');
    if (ta) ta.value = '导出异常：' + e;
  });
}

function copyConfig() {
  const text = window._exportJson || '';
  if (!text) { addLog('配置还没生成完，请稍候', 'warn'); return; }
  if (navigator.clipboard) {
    navigator.clipboard.writeText(text).then(function () {
      addLog('配置已复制，请妥善保存', 'success');
    }).catch(function () {
      addLog('复制失败，请手动全选文本框内容', 'error');
    });
  }
}

function showConfigImport() {
  Modal.open({
    id: 'importOverlay',
    icon: 'i-refresh',
    title: '恢复配置',
    desc: '把之前备份的内容粘贴进来',
    wide: true,
    body:
      '<textarea id="importText" class="modal-input mono modal-textarea-lg" placeholder="在这里粘贴备份的 JSON 内容"></textarea>' +
      '<p id="importHint" class="modal-hint"></p>',
    actions: [
      { text: '取消', onclick: () => Modal.close('importOverlay') },
      { text: '恢复配置', primary: true, id: 'importBtn', onclick: doImportConfig },
    ],
    footer: '恢复后立即生效，不需要重启',
  });
}

function doImportConfig() {
  const ta = document.getElementById('importText');
  const btn = document.getElementById('importBtn');
  const text = ta ? ta.value.trim() : '';
  if (!text) { setHint('importHint', '请先粘贴配置内容', 'error'); return; }

  btn.disabled = true;
  btn.textContent = '导入中…';
  setHint('importHint', '正在导入…');

  pywebview.api.import_config(text).then(function (r) {
    btn.disabled = false;
    btn.textContent = '恢复配置';
    if (!r || !r.success) {
      setHint('importHint', (r && r.error) || '导入失败', 'error');
      return;
    }
    setHint('importHint', '配置已恢复并生效', 'success');
    addLog('配置已从备份恢复', 'success');
    _keyConfigured = true;
    updateKeyBtn({ configured: true });
    setTimeout(function () { Modal.close('importOverlay'); }, 1400);
  }).catch(function (e) {
    btn.disabled = false;
    btn.textContent = '恢复配置';
    setHint('importHint', '导入异常：' + e, 'error');
  });
}

