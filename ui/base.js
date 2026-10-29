/* 基础：HTML 转义、背景装饰（星空/雪花） */
// HTML 转义：所有来自后端/第三方（闲鱼标题、卖家昵称、商品描述、异常信息）
// 的文本在拼入 innerHTML 前必须过这里，否则卖家昵称可注入脚本，
// 配合暴露给 JS 的 pywebview.api.open_file 可执行本机任意程序。
function escapeHtml(s) {
  if (s === null || s === undefined) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// 星空
const starsContainer = document.getElementById('stars');
for (let i = 0; i < 80; i++) {
  const star = document.createElement('div');
  star.className = 'star';
  star.style.left = Math.random() * 100 + '%';
  star.style.top = Math.random() * 55 + '%';
  star.style.animationDelay = Math.random() * 3 + 's';
  star.style.animationDuration = (2 + Math.random() * 3) + 's';
  starsContainer.appendChild(star);
}

// 雪花
const snowContainer = document.getElementById('snowflakes');
for (let i = 0; i < 30; i++) {
  const flake = document.createElement('div');
  flake.className = 'snowflake';
  flake.textContent = Math.random() > 0.5 ? '' : '';
  flake.style.left = Math.random() * 100 + '%';
  flake.style.animationDuration = (6 + Math.random() * 10) + 's';
  flake.style.animationDelay = Math.random() * 12 + 's';
  flake.style.fontSize = (10 + Math.random() * 12) + 'px';
  flake.style.opacity = 0.4 + Math.random() * 0.5;
  snowContainer.appendChild(flake);
}

document.getElementById('urlInput').addEventListener('keydown', e => {
  if (e.key === 'Enter') runTool();
});
