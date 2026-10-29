# -*- coding: utf-8 -*-
"""把 ui/ 下的源文件合并成单文件 gui_embed.html

为什么需要这一步：
pywebview 用 html= 加载时页面地址是 about:blank，浏览器无法引用外部
JS/CSS 文件（安全限制）。所以源码拆开便于维护，但运行时必须是单文件。

用法：python build_ui.py [--check]
  --check  只校验不写文件
"""
import io
import os
import sys

UI = 'ui'
OUT = 'gui_embed.html'

# 注入顺序必须与拆分前一致：函数声明会提升，但顶层立即执行的代码有先后依赖
INJECT_ORDER = ['style.css', 'base.js', 'llm.js', 'ui.js', 'queue.js', 'settings.js', 'dialogs.js', 'workflow.js']


def read(name):
    path = os.path.join(UI, name)
    if not os.path.exists(path):
        raise SystemExit('缺少源文件: ' + path)
    return io.open(path, encoding='utf-8').read().rstrip()


def build():
    tpl = read('index.html')
    for name in INJECT_ORDER:
        marker = '/* @inject %s */' % name
        if marker not in tpl:
            raise SystemExit('模板缺少注入点: ' + marker)
        tpl = tpl.replace(marker, read(name), 1)

    # 校验：所有注入点都应被替换
    leftover = [n for n in INJECT_ORDER if ('/* @inject %s */' % n) in tpl]
    if leftover:
        raise SystemExit('仍有未替换的注入点: %s' % ', '.join(leftover))

    return tpl


def sanity(text):
    """基本完整性检查"""
    problems = []
    if text.count('<script>') != text.count('</script>'):
        problems.append('script 标签不配对')
    if text.count('<style>') != text.count('</style>'):
        problems.append('style 标签不配对')
    if '</html>' not in text:
        problems.append('缺少 </html>')
    for must in ('function escapeHtml', 'const Modal = {', 'function queueAdd',
                 'function showLogModal', 'function runTool', '.modal-overlay'):
        if must not in text:
            problems.append('缺少关键片段: ' + must)
    return problems


def main():
    check_only = '--check' in sys.argv
    text = build()

    problems = sanity(text)
    if problems:
        print('完整性检查失败：')
        for p in problems:
            print('  -', p)
        return 1

    if check_only:
        print('校验通过（未写入）')
        return 0

    io.open(OUT, 'w', encoding='utf-8', newline='\n').write(text)
    print('已生成 %s' % OUT)
    print('  总行数 : %d' % text.count('\n'))
    print('  大小   : %.1f KB' % (len(text.encode('utf-8')) / 1024))
    for name in INJECT_ORDER:
        print('  含 %-14s %d 行' % (name, read(name).count('\n') + 1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
