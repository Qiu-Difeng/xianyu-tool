/**
 * image —— 从 workflow.js 拆出来的一块
 *
 * 函数实现原样搬过来，没改逻辑。全局状态（_outputDir 等）还在 workflow.js，
 * 这里只是在函数体内引用，调用时已经定义，不受加载顺序影响。
 */


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
