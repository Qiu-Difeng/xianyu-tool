/* 模型配置：API Key 表单、预设联动、保存与测试 */

// === API Key 配置 ===
let _keyConfigured = null;   // null=未知 / true / false

function updateKeyBtn(status) {
  const btn = document.getElementById('keyBtn');
  const txt = document.getElementById('keyBtnText');
  if (!btn || !txt) return;
  if (status && status.configured) {
    txt.textContent = 'Key 已配置';
    btn.style.color = 'var(--success)';
    btn.title = 'API Key 已配置，点击可修改';
  } else {
    txt.textContent = 'Key 未配置';
    btn.style.color = 'var(--warn)';
    btn.title = '点击填写 API Key';
  }
}

let _llmInfo = null;   // 后端返回的配置与预设

function showKeyModal(fromStartup) {
  // 骨架交给 Modal 工厂 + .modal-* 样式类，
  // 这里只保留 Key 配置特有的字段，不再内联一大段 style
  const body = `
    <div class="modal-field">
      <div class="modal-label">服务商</div>
      <select id="keyPreset" class="modal-select" onchange="onPresetChange()"></select>
      <div id="keyPresetHint" class="modal-note"></div>
    </div>

    <div class="modal-field">
      <div class="modal-label">API Key <span id="keyApplyLink" class="modal-link" onclick="openKeyPage()">去申请 →</span></div>
      <input type="password" id="keyInput" class="modal-input mono" placeholder="在这里粘贴 API Key" />
    </div>

    <div class="modal-row">
      <label class="modal-check"><input type="checkbox" id="keyShow" onclick="toggleKeyVisible()" />显示明文</label>
      <label class="modal-check"><input type="checkbox" id="keyAdvanced" onclick="toggleAdvanced()" />高级：文本/视觉分开配</label>
    </div>

    <div id="keyAdvancedArea" class="modal-section" style="display:none;">
      <div class="modal-section-title"><svg class="ico"><use href="#i-pen"/></svg>文本模型（写文案）</div>
      <div class="modal-grid2" style="margin-bottom:8px;">
        <input type="text" id="textBaseUrl" class="modal-input mono" placeholder="API 地址" />
        <input type="text" id="textModel" class="modal-input mono" placeholder="模型名" />
      </div>
      <input type="password" id="textKey" class="modal-input mono" placeholder="独立 Key（留空则用上面的 Key）" style="margin-bottom:8px;" />
      <button class="modal-btn" id="testTextBtn" onclick="testModel('text')" style="padding:6px 14px;font-size:12px;">测试文本模型</button>

      <div class="modal-section-title" style="margin-top:14px;"><svg class="ico"><use href="#i-image"/></svg>视觉模型（去水印，必须支持图片）</div>
      <div class="modal-grid2" style="margin-bottom:8px;">
        <input type="text" id="visionBaseUrl" class="modal-input mono" placeholder="API 地址" />
        <input type="text" id="visionModel" class="modal-input mono" placeholder="模型名" />
      </div>
      <input type="password" id="visionKey" class="modal-input mono" placeholder="独立 Key（留空则用上面的 Key）" style="margin-bottom:8px;" />
      <button class="modal-btn" id="testVisionBtn" onclick="testModel('vision')" style="padding:6px 14px;font-size:12px;">测试视觉模型</button>

      <p class="modal-note">提示：DeepSeek 等纯文本服务不能做视觉模型，去水印需另外配一个支持图片的（如智谱 glm-4v-flash、魔搭 Qwen2-VL）。地址末尾不要带斜杠。</p>
    </div>

    <p id="keyHint" class="modal-hint"></p>
  `;

  Modal.open({
    id: 'keyOverlay',
    icon: 'i-key',
    title: '配置大模型',
    desc: '本工具不内置 Key，需要填你自己的',
    body: body,
    wide: true,
    actions: [
      { text: '稍后配置', onclick: () => Modal.close('keyOverlay') },
      { text: '保存并验证', primary: true, id: 'keySaveBtn', onclick: saveKey },
    ],
    footer: '配置只存在本机，不会上传 · <span class="modal-link" onclick="showConfigExport()">备份配置</span> · <span class="modal-link" onclick="showConfigImport()">恢复配置</span>',
  });

  loadLlmConfig(fromStartup);
}

function loadLlmConfig(fromStartup) {
  pywebview.api.get_llm_config().then(info => {
    _llmInfo = info;
    if (!info || !info.success) {
      setKeyHint('读取配置失败：' + (info && info.error || '未知'), 'error');
      return;
    }

    // 填充服务商下拉
    const sel = document.getElementById('keyPreset');
    sel.innerHTML = '';
    Object.keys(info.presets).forEach(k => {
      const p = info.presets[k];
      const opt = document.createElement('option');
      opt.value = k;
      opt.textContent = p.label;
      sel.appendChild(opt);
    });

    // 判断当前该选哪个预设
    const cur = info.text.provider || 'zhipu';
    sel.value = Object.prototype.hasOwnProperty.call(info.presets, cur) ? cur : 'custom';

    // 已配置的 key 回填（显示在输入框，方便直接保存）
    if (info.text.api_key) {
      document.getElementById('keyInput').value = info.text.api_key;
    }
    applyPresetValues(sel.value, info);

    if (fromStartup) {
      setKeyHint('首次使用需要配置，填好 Key 即可开始处理商品', 'warn');
    }
  }).catch(e => setKeyHint('读取配置异常：' + e, 'error'));
}

function applyPresetValues(presetKey, info) {
  info = info || _llmInfo;
  if (!info) return;
  const p = info.presets[presetKey];
  if (!p) return;

  const hintEl = document.getElementById('keyPresetHint');
  if (hintEl) hintEl.textContent = p.hint || '';

  const linkEl = document.getElementById('keyApplyLink');
  if (linkEl) linkEl.style.display = p.apply_url ? 'inline' : 'none';

  // 只在对应用户还没手填时覆盖，避免把已保存的自定义值冲掉
  const tb = document.getElementById('textBaseUrl');
  const tm = document.getElementById('textModel');
  const vb = document.getElementById('visionBaseUrl');
  const vm = document.getElementById('visionModel');

  if (presetKey === 'custom') {
    if (!tb.value) tb.value = info.text.base_url || '';
    if (!tm.value) tm.value = info.text.model || '';
    if (!vb.value) vb.value = info.vision.base_url || '';
    if (!vm.value) vm.value = info.vision.model || '';
  } else {
    if (tb) tb.value = p.base_url;
    if (tm) tm.value = p.text_model;
    if (vb) vb.value = p.base_url;
    if (vm) vm.value = p.vision_model;
  }
}

function onPresetChange() {
  const sel = document.getElementById('keyPreset');
  applyPresetValues(sel.value);
}

function toggleAdvanced() {
  const cb = document.getElementById('keyAdvanced');
  const area = document.getElementById('keyAdvancedArea');
  if (!cb || !area) return;
  area.style.display = cb.checked ? 'block' : 'none';
  if (cb.checked) {
    // 用当前选中的预设填充，而不是用已保存的旧配置，
    // 否则用户先选 DeepSeek 再勾"高级"，输入框会被旧值冲掉
    const sel = document.getElementById('keyPreset');
    applyPresetValues(sel ? sel.value : 'zhipu');
  }
}

function setKeyHint(msg, level) {
  const el = document.getElementById('keyHint');
  if (!el) return;
  el.textContent = msg;
  el.style.color = level === 'error' ? 'var(--error)'
    : level === 'success' ? 'var(--success)'
    : level === 'warn' ? 'var(--warn)'
    : 'var(--text-dim)';
}

function hideKeyModal() {
  const ov = document.getElementById('keyOverlay');
  if (ov) ov.remove();
}

function toggleKeyVisible() {
  const cb = document.getElementById('keyShow');
  const inp = document.getElementById('keyInput');
  if (cb && inp) inp.type = cb.checked ? 'text' : 'password';
}

function openKeyPage() {
  const sel = document.getElementById('keyPreset');
  const key = sel ? sel.value : 'zhipu';
  const p = (_llmInfo && _llmInfo.presets) ? _llmInfo.presets[key] : null;
  pywebview.api.open_url((p && p.apply_url) || 'https://open.bigmodel.cn/');
}

// 从界面收集某一类模型的配置
function collectSection(kind, fallbackKey) {
  const presetEl = document.getElementById('keyPreset');
  const preset = presetEl ? presetEl.value : 'zhipu';
  if (kind === 'text') {
    return {
      provider: preset,
      base_url: (document.getElementById('textBaseUrl').value || '').trim(),
      model: (document.getElementById('textModel').value || '').trim(),
      api_key: (document.getElementById('textKey').value || '').trim() || fallbackKey,
    };
  }
  return {
    provider: preset,
    base_url: (document.getElementById('visionBaseUrl').value || '').trim(),
    model: (document.getElementById('visionModel').value || '').trim(),
    api_key: (document.getElementById('visionKey').value || '').trim() || fallbackKey,
  };
}

// 把当前界面上的配置组装成 text / vision 两组
function buildSections() {
  const key = (document.getElementById('keyInput').value || '').trim();
  const advEl = document.getElementById('keyAdvanced');
  const adv = advEl && advEl.checked;
  const presetEl = document.getElementById('keyPreset');
  const preset = presetEl ? presetEl.value : 'zhipu';

  if (adv) {
    return { key: key, text: collectSection('text', key), vision: collectSection('vision', key), adv: true };
  }

  const p = (_llmInfo && _llmInfo.presets) ? _llmInfo.presets[preset] : null;
  if (!p) return { key: key, text: null, vision: null, adv: false };

  const text = { provider: preset, base_url: p.base_url, model: p.text_model, api_key: key };
  let vision;
  if (p.vision_ok && p.vision_model) {
    vision = { provider: preset, base_url: p.base_url, model: p.vision_model, api_key: key };
  } else {
    // 该服务没有视觉能力（如 DeepSeek），视觉留空，去水印会提示未配置
    vision = { provider: 'zhipu', base_url: '', model: '', api_key: '' };
  }
  return { key: key, text: text, vision: vision, adv: false };
}

function saveKey() {
  const btn = document.getElementById('keySaveBtn');
  const built = buildSections();

  if (!built.key) {
    setKeyHint('请先粘贴 API Key', 'error');
    return;
  }
  if (!built.text) {
    setKeyHint('配置异常，请关闭重开', 'error');
    return;
  }
  if (built.adv && !built.vision.model) {
    setKeyHint('视觉模型缺模型名。去水印必须要一个支持图片的模型', 'error');
    return;
  }

  btn.disabled = true;
  btn.textContent = '保存中…';
  setKeyHint('正在保存…');

  pywebview.api.save_llm_config(built.text, built.vision).then(r => {
    if (!r.success) {
      setKeyHint(r.error || '保存失败', 'error');
      btn.disabled = false;
      btn.textContent = '保存并验证';
      return;
    }

    setKeyHint('已保存，正在验证文本模型…');
    pywebview.api.test_llm('text').then(t => {
      if (!t.success) {
        _keyConfigured = true;
        updateKeyBtn({ configured: true });
        btn.disabled = false;
        btn.textContent = '保存并验证';
        setKeyHint('已保存，但文本模型验证失败：' + (t.error || ''), 'warn');
        return;
      }
      if (!r.vision_ready) {
        finishSave(true, '视觉模型未配置，去水印功能不可用');
        return;
      }
      setKeyHint('文本模型 <svg class="ico"><use href="#i-check"/></svg>，正在验证视觉模型…', 'success');
      pywebview.api.test_llm('vision').then(v => {
        finishSave(v.success, v.success ? '' : (v.error || ''));
      }).catch(e => finishSave(false, String(e)));
    }).catch(e => {
      btn.disabled = false;
      btn.textContent = '保存并验证';
      setKeyHint('验证异常：' + e, 'warn');
    });
  }).catch(e => {
    btn.disabled = false;
    btn.textContent = '保存并验证';
    setKeyHint('保存异常：' + e, 'error');
  });
}

function finishSave(visionOk, visionMsg) {
  const btn = document.getElementById('keySaveBtn');
  if (btn) {
    btn.disabled = false;
    btn.textContent = '保存并验证';
  }
  _keyConfigured = true;
  updateKeyBtn({ configured: true });

  if (visionOk) {
    setKeyHint('<svg class="ico"><use href="#i-check"/></svg> 全部验证通过，可以开始用了', 'success');
  } else {
    setKeyHint('文本模型可用；' + (visionMsg || '视觉模型未通过验证') + '（去水印会不可用）', 'warn');
  }
  addLog('大模型配置已保存', 'success');
  setTimeout(() => {
    hideKeyModal();
    if (!guideSeenBefore()) showGuide();
  }, 1100);
}

// 单独测试某一类模型（先用当前界面值静默保存，再测）
function testModel(kind) {
  const btnId = kind === 'text' ? 'testTextBtn' : 'testVisionBtn';
  const btn = document.getElementById(btnId);
  const built = buildSections();
  if (!built.key) {
    setKeyHint('请先填 API Key', 'error');
    return;
  }
  if (!built.text) return;

  const oldText = btn.textContent;
  btn.disabled = true;
  btn.textContent = '测试中…';
  setKeyHint('正在保存当前配置…');

  pywebview.api.save_llm_config(built.text, built.vision).then(r => {
    if (!r.success) {
      btn.disabled = false;
      btn.textContent = oldText;
      setKeyHint(r.error || '保存失败', 'error');
      return;
    }
    setKeyHint('配置已保存，正在测试…');
    pywebview.api.test_llm(kind).then(t => {
      btn.disabled = false;
      btn.textContent = oldText;
      if (t.success) {
        setKeyHint((kind === 'text' ? '文本' : '视觉') + '模型 <svg class="ico"><use href="#i-check"/></svg> 回复：' + (t.reply || '正常'), 'success');
      } else {
        setKeyHint((kind === 'text' ? '文本' : '视觉') + '模型 <svg class="ico"><use href="#i-x"/></svg> ' + (t.error || '失败'), 'error');
      }
    }).catch(e => {
      btn.disabled = false;
      btn.textContent = oldText;
      setKeyHint('测试异常：' + e, 'error');
    });
  }).catch(e => {
    btn.disabled = false;
    btn.textContent = oldText;
    setKeyHint('保存异常：' + e, 'error');
  });
}

