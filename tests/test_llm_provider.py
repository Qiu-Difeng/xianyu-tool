# -*- coding: utf-8 -*-
"""大模型调用模块测试

这个模块之前零测试，但它决定了「文案能不能生成」。
重点测：配置解析、key 脱敏、没有 key 时的行为、错误处理。

不访问网络（不真调 API）。
"""
import json
import os

import pytest

import llm_provider as lp


# ---------------- _normalize_section ----------------

def test_normalize_section_fills_defaults():
    """空配置要补上默认模型"""
    sec = lp._normalize_section({}, 'glm-4-flash', '')
    assert sec.get('model') == 'glm-4-flash'


def test_normalize_section_keeps_given_model():
    sec = lp._normalize_section({'model': 'glm-4-plus'}, 'glm-4-flash', '')
    assert sec['model'] == 'glm-4-plus'


def test_normalize_section_falls_back_key():
    """section 里没 key 时，用 legacy 的 key 兜底"""
    sec = lp._normalize_section({}, 'glm-4-flash', 'sk-legacy-123')
    assert sec.get('api_key') == 'sk-legacy-123'


def test_normalize_section_keeps_own_key():
    """section 自己有 key 时不能被 legacy 覆盖"""
    sec = lp._normalize_section({'api_key': 'sk-own'}, 'glm-4-flash', 'sk-legacy')
    assert sec['api_key'] == 'sk-own'


def test_normalize_section_none_input():
    """传 None 也不能崩"""
    sec = lp._normalize_section(None, 'glm-4-flash', 'sk-x')
    assert isinstance(sec, dict)


# ---------------- mask_key ----------------

def test_mask_key_hides_middle():
    """key 要脱敏，不能明文显示"""
    masked = lp.mask_key('sk-1234567890abcdef')
    assert '1234567890' not in masked
    assert masked != 'sk-1234567890abcdef'


def test_mask_key_empty():
    """空 key 返回空字符串，不能崩"""
    assert lp.mask_key('') == ''


def test_mask_key_none():
    assert lp.mask_key(None) == ''


def test_mask_key_short():
    """太短的 key 也不能露出全部"""
    masked = lp.mask_key('abc')
    assert 'abc' not in masked or masked == '***'


# ---------------- load_config ----------------

def test_load_config_returns_dict_when_missing(tmp_path, monkeypatch):
    """配置文件不存在时返回带默认结构的 dict，不能抛异常"""
    monkeypatch.setattr(lp, 'config_path', lambda: str(tmp_path / 'nope.json'))
    cfg = lp.load_config()
    assert isinstance(cfg, dict)
    assert 'text' in cfg or 'vision' in cfg


def test_load_config_reads_file(tmp_path, monkeypatch):
    p = tmp_path / 'api_config.json'
    p.write_text(json.dumps({
        'text': {'api_key': 'sk-a', 'model': 'glm-4-flash'},
        'vision': {'api_key': 'sk-b', 'model': 'glm-4v-flash'},
    }), encoding='utf-8')
    monkeypatch.setattr(lp, 'config_path', lambda: str(p))
    cfg = lp.load_config()
    assert cfg['text']['api_key'] == 'sk-a'
    assert cfg['vision']['model'] == 'glm-4v-flash'


def test_load_config_broken_json(tmp_path, monkeypatch):
    """JSON 坏掉时返回默认结构，不能崩"""
    p = tmp_path / 'api_config.json'
    p.write_text('{ not valid json', encoding='utf-8')
    monkeypatch.setattr(lp, 'config_path', lambda: str(p))
    cfg = lp.load_config()
    assert isinstance(cfg, dict)


# ---------------- LLM.available ----------------

def test_llm_available_false_without_key(tmp_path, monkeypatch):
    """没配 key 时 available() 必须是 False"""
    p = tmp_path / 'api_config.json'
    p.write_text(json.dumps({'text': {'api_key': '', 'model': 'glm-4-flash'}}),
                 encoding='utf-8')
    monkeypatch.setattr(lp, 'config_path', lambda: str(p))
    llm = lp.LLM('text', {'api_key': '', 'model': 'glm-4-flash', 'base_url': 'http://x'})
    assert llm.available() is False


def test_llm_available_true_with_key():
    llm = lp.LLM('text', {'api_key': 'sk-test', 'model': 'glm-4-flash',
                          'base_url': 'http://x'})
    assert llm.available() is True


def test_llm_describe_hides_key():
    """describe() 是给界面显示的，不能带出完整 key"""
    llm = lp.LLM('text', {'api_key': 'sk-1234567890abcdef', 'model': 'glm-4-flash',
                          'base_url': 'http://x'})
    d = llm.describe()
    assert '1234567890' not in str(d)


# ---------------- LLM.chat 无网络时的行为 ----------------

def test_llm_chat_without_key_raises():
    """没 key 调 chat 要抛 LLMError，不能静默失败"""
    llm = lp.LLM('text', {'api_key': '', 'model': 'glm-4-flash', 'base_url': 'http://x'})
    with pytest.raises(lp.LLMError):
        llm.chat([{'role': 'user', 'content': 'hi'}])


def test_llm_error_is_runtime_error():
    """LLMError 继承 RuntimeError，方便上层统一 catch"""
    assert issubclass(lp.LLMError, RuntimeError)


# ---------------- get_llm ----------------

def test_get_llm_returns_object():
    """get_llm 必须返回可用对象，即使没配 key"""
    llm = lp.get_llm('text')
    assert llm is not None
    assert hasattr(llm, 'available')
    assert hasattr(llm, 'chat')


def test_get_llm_vision_kind():
    llm = lp.get_llm('vision')
    assert llm is not None
    assert llm.kind == 'vision'
