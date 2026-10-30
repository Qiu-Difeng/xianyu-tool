# -*- coding: utf-8 -*-
"""pytest 公共配置：把项目根加进 sys.path，避免测试里到处写路径"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
