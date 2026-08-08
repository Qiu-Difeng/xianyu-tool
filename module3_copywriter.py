# -*- coding: utf-8 -*-
"""闲鱼文案三版本生成模块 v3

后处理：违禁词替换 + 精确emoji去除（不误伤中文）
"""
import json
import re
import os
from zhipuai import ZhipuAI

API_KEY = os.environ.get("ZHIPUAI_API_KEY", "在此填入你的智谱API Key")
CLIENT = ZhipuAI(api_key=API_KEY) if API_KEY and "在此填入" not in API_KEY else None
MODEL = "glm-4-flash"

# ============================================================
# V1 词典
# ============================================================
SYNONYM_DICT = {
    "入手": ["拿下", "购入"],
    "发货": ["寄出", "发出"],
    "宝贝": ["好物", "好东西"],
    "亲们": ["大家", "朋友们"],
    "闲置": ["多余", "用不上了"],
    "九成新": ["95新", "近全新"],
    "八成新": ["85新", "良好成色"],
    "便宜": ["实惠", "划算"],
    "推荐": ["力荐", "值得入"],
    "好用": ["实用", "便捷"],
    "包邮": ["包邮寄", "免邮"],
    "热销": ["热卖", "畅销"],
    "限时": ["限量", "限时特惠"],
    "清仓": ["甩卖", "尾货清"],
    "低价": ["实惠价", "超低价"],
    "因为": ["由于"],
    "所以": ["因此"],
    "但是": ["不过"],
    "而且": ["并且"],
    "非常": ["特别", "超"],
    "赶紧": ["抓紧", "速来"],
    "哈": ["呀", "哦"],
    "啦": ["咯", "啰"],
}
NO_REPLACE = {"安全门", "过载保护", "USB", "插线板", "插孔", "插座", "排插", "充电"}

BANNED_WORDS = [
    "第一", "顶级", "极品", "绝版", "万能", "全能",
    "超结实", "性价比拉满", "低于出厂价", "白菜价",
    "国家级", "世界级", "最佳", "最优", "最低价",
    "100%正品", "绝对", "永久", "永不",
    "包治百病", "疗效", "减肥",
    "加微信", "加V", "加我", "私聊", "私聊",
    "假一赔十", "如假包换",
    "超级好", "超快", "最重",
]

# 单字违禁词：需要上下文判断，以下搭配属于正常用法不算违禁
BANNED_SINGLE = {
    "最": ["最后", "最先", "最新", "最终", "最多", "最少", "最初", "近来"],  # "最"+这些字不算违禁
}

# ============================================================
# 后处理
# ============================================================
POST_REPLACE = {
    "白菜价": "实惠价",
    "超级": "特别",
    "简直就是": "算是",
    "快人一步": "效率高",
    "亲们": "朋友们",
    "快来抢购": "想要的抓紧",
    "抢购": "入手",
    "数量有限": "量不多",
    "最佳": "很好",
    "最低": "很底",
    "绝对": "肯定",
    "私聊": "私信",
    "加微信": "联系",
    "加V": "联系",
    "加我": "联系",
}

def remove_emoji(text):
    """精确去除emoji——只用安全的Unicode块，不碰中文"""
    # 只匹配明确的emoji范围，不包含CJK区域
    emoji_ranges = [
        '\U0001F600-\U0001F64F',  # emoticons
        '\U0001F680-\U0001F6FF',  # transport
        '\U0001F1E0-\U0001F1FF',  # flags
        '\U00002700-\U000027BF',  # dingbats (注意: 2702-27B0)
        '\U0001F900-\U0001F9FF',  # supplemental symbols
        '\U0001FA00-\U0001FA6F',  # chess symbols
        '\U00002600-\U000026FF',  # misc symbols (☀☁ etc)
        '\U0001F300-\U0001F5FF',  # misc symbols & pictographs
    ]
    pattern = '[' + ''.join(emoji_ranges) + ']+'
    return re.sub(pattern, '', text, flags=re.UNICODE)

def post_process(text):
    """后处理：去emoji + 替换违禁词 + 清理空句"""
    text = remove_emoji(text)
    for old, new in POST_REPLACE.items():
        text = text.replace(old, new)
    text = re.sub(r'[！!。]?快来入手吧[，,]?', '', text)
    text = re.sub(r'方便快捷[！!]?', '', text)
    # 清理空句："直接充电，。" → "直接充电。"
    text = re.sub(r'，。', '。', text)      # "，。" → "。"
    text = re.sub(r'，。', '。', text)      # 再清一次（防嵌套）
    text = re.sub(r'[，,]\s*。', '。', text)  # "，。" → "。"
    text = re.sub(r'。{2,}', '。', text)      # 连续句号合并
    text = re.sub(r'\s+。', '。', text)       # 句号前空格
    # 清理"，"后面直接换行或结尾的情况
    text = re.sub(r'，\s*\n', '\n', text)
    text = re.sub(r'，\s*$', '', text)
    return text.strip()

def v1_dict_replace(text):
    result = text
    for original, synonyms in SYNONYM_DICT.items():
        if original in NO_REPLACE:
            continue
        if original in result:
            result = result.replace(original, synonyms[0])
    return post_process(result)

def filter_banned(text):
    warnings = []
    for word in BANNED_WORDS:
        if word in text:
            warnings.append(word)
    # 单字违禁词做上下文检查
    for char, safe_words in BANNED_SINGLE.items():
        if char in text:
            # 找出所有“最”的位置，检查后面一个字是否在安全列表里
            import re as _re
            for m in _re.finditer(char, text):
                pos = m.start()
                next_char = text[pos+1:pos+2] if pos+1 < len(text) else ""
                two_char = text[pos:pos+2]
                if two_char not in safe_words:
                    if char not in warnings:
                        warnings.append(char)
                    break
    return warnings

# ============================================================
# V2/V3 Prompt
# ============================================================
V2_PROMPT = """你是闲鱼文案改写专家。请对以下商品文案做【微调改写】：

规则：
1. 保持原文结构和卖点顺序不变
2. 只调整措辞、语气、连接词
3. 适当增删语气词
4. 换同义词但不要换核心卖点
5. 保持口语化闲鱼风格
6. 禁止emoji
7. 不要加标题，只输出正文
8. 不要用"白菜价""超级""最"等违禁词
9. 输出纯文本

原文：
{desc}
"""

V3_PROMPT = """你是闲鱼文案专家。请基于以下商品信息【完整重写】一篇全新文案：

规则：
1. 标题不动，只重写正文
2. 重新组织卖点顺序
3. 用完全不同的表达方式
4. 加入使用场景描述
5. 保持闲鱼风格：口语化、真诚、有吸引力
6. 200-400字
7. 禁止emoji
8. 不要用"白菜价""超级""最""第一""绝对"等违禁词
9. 不要喊"亲们""快来抢购"等话术
10. 输出纯文本

商品标题：{title}
原文案（参考卖点，不要照抄）：
{desc}
"""

def call_glm(prompt, max_tokens=1200, temperature=0.7):
    # 智谱API要求temperature最多2位小数
    temperature = round(temperature, 2)
    resp = CLIENT.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return resp.choices[0].message.content.strip()

def v2_ai_light_rewrite(title, desc, banned_str, temperature=0.7):
    prompt = V2_PROMPT.format(desc=desc)
    return post_process(call_glm(prompt, max_tokens=1200, temperature=temperature))

def v3_ai_full_rewrite(title, desc, banned_str, temperature=0.7):
    prompt = V3_PROMPT.format(title=title, desc=desc)
    return post_process(call_glm(prompt, max_tokens=1000, temperature=temperature))

def v3_ai_custom_rewrite(title, desc, custom_prompt, temperature=0.7):
    """V3自定义提示词重写"""
    full_prompt = f"""你是闲鱼文案专家。请根据以下要求重写商品文案：

用户要求：
{custom_prompt}

规则：
1. 标题不动，只重写正文
2. 保持闲鱼风格：口语化、真诚
3. 禁止emoji
4. 不要用"白菜价""超级""最""第一""绝对"等违禁词
5. 不要喊"亲们""快来抢购"等话术
6. 输出纯文本

商品标题：{title}
原文案（参考）：
{desc}
"""
    return post_process(call_glm(full_prompt, max_tokens=1000, temperature=temperature))

# ============================================================
# 主流程
# ============================================================
import random

def generate_versions(title, desc):
    banned_str = ", ".join(BANNED_WORDS[:15])
    
    print(f"商品标题: {title}")
    print(f"原文案字数: {len(desc)}")
    print()
    
    # V1是本地词典替换，瞬间完成
    print("--- V1 词典替换 ---")
    v1 = v1_dict_replace(desc)
    v1_banned = filter_banned(v1)
    print(f"V1完成 ({len(v1)}字) 违禁词: {v1_banned if v1_banned else '无'}")
    
    # V2和V3是AI调用，改成并行执行（用线程池）
    print("--- V2 AI微调 + V3 AI重写（并行） ---")
    from concurrent.futures import ThreadPoolExecutor
    
    def _do_v2():
        text = v2_ai_light_rewrite(title, desc, banned_str)
        banned = filter_banned(text)
        return text, banned
    
    def _do_v3():
        text = v3_ai_full_rewrite(title, desc, banned_str)
        banned = filter_banned(text)
        return text, banned
    
    with ThreadPoolExecutor(max_workers=2) as executor:
        f_v2 = executor.submit(_do_v2)
        f_v3 = executor.submit(_do_v3)
        v2, v2_banned = f_v2.result()
        v3, v3_banned = f_v3.result()
    
    print(f"V2完成 ({len(v2)}字) 违禁词: {v2_banned if v2_banned else '无'}")
    print(f"V3完成 ({len(v3)}字) 违禁词: {v3_banned if v3_banned else '无'}")
    print()
    
    return {
        "title": title,
        "original": desc,
        "v1": v1,
        "v2": v2,
        "v3": v3,
        "banned_warnings": {"v1": v1_banned, "v2": v2_banned, "v3": v3_banned}
    }


def regenerate_v1(desc):
    """重新生成V1——用随机选同义词，每次结果不同"""
    result = desc
    for original, synonyms in SYNONYM_DICT.items():
        if original in NO_REPLACE:
            continue
        if original in result:
            # 随机选一个同义词
            pick = random.choice(synonyms)
            result = result.replace(original, pick)
    return post_process(result)


def regenerate_v2(title, desc, temperature=None):
    """重新生成V2——用不同temperature，每次结果不同"""
    if temperature is None:
        temperature = round(random.uniform(0.6, 0.95), 2)
    banned_str = "、".join(BANNED_WORDS[:15])
    return post_process(v2_ai_light_rewrite(title, desc, banned_str, temperature=temperature))


def regenerate_v3(title, desc, temperature=None, custom_prompt=None):
    """重新生成V3——用不同temperature，每次结果不同；支持自定义提示词"""
    if temperature is None:
        temperature = round(random.uniform(0.6, 0.95), 2)
    banned_str = "、".join(BANNED_WORDS[:15])
    if custom_prompt:
        return post_process(v3_ai_custom_rewrite(title, desc, custom_prompt, temperature=temperature))
    return post_process(v3_ai_full_rewrite(title, desc, banned_str, temperature=temperature))

# ============================================================
# 测试
# ============================================================
if __name__ == "__main__":
    test_title = "USB插线板 多孔位带USB充电 插座排插 办公室宿舍宿舍神器"
    test_desc = """全新未拆封！USB插线板，多孔位设计，带USB充电口，手机直接充，不用充电头啦～

办公室宿舍必备神器！多个插孔同时用，电脑手机台灯打印机都能插。

USB口充电快，跟原装充电头差不多速度。
白色简约设计，放哪都好看。
线长1.8米，够长够用。
带安全门，不怕小孩戳。
过载保护，放心用。

闲置出全新，自己买多了。白菜价出了，要的赶紧入手哈。
包邮发货，直接寄到家。"""
    
    print("=" * 60)
    print("闲鱼文案三版本生成 v3（修复emoji正则）")
    print("=" * 60)
    print()
    
    result = generate_versions(test_title, test_desc)
    
    print("=" * 60)
    print(f"【标题】（不动）: {result['title']}")
    print()
    print("【原文案】:")
    print(result["original"])
    print("-" * 40)
    print("【V1 词典替换】:")
    print(result["v1"])
    print("-" * 40)
    print("【V2 AI微调】:")
    print(result["v2"])
    print("-" * 40)
    print("【V3 AI完整重写】:")
    print(result["v3"])
    print("=" * 60)
    
    output_dir = "test_copies"
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, "v1_词典替换.txt"), "w", encoding="utf-8") as f:
        f.write(f"标题：{result['title']}\n\n{result['v1']}")
    with open(os.path.join(output_dir, "v2_AI微调.txt"), "w", encoding="utf-8") as f:
        f.write(f"标题：{result['title']}\n\n{result['v2']}")
    with open(os.path.join(output_dir, "v3_AI重写.txt"), "w", encoding="utf-8") as f:
        f.write(f"标题：{result['title']}\n\n{result['v3']}")
    with open(os.path.join(output_dir, "全部版本.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 三版本已保存到 {output_dir}/")
