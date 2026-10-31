# -*- coding: utf-8 -*-
"""闲鱼文案三版本生成模块 v3

后处理：违禁词替换 + 精确emoji去除（不误伤中文）

模型调用统一走 llm_provider，支持智谱 / DeepSeek / 魔搭 / 任意 OpenAI 兼容接口。
"""
import json
import os
import re
import time

import llm_provider

# 默认模型名（配置里没填时用这个）
MODEL = llm_provider.DEFAULT_TEXT_MODEL

# ============================================================
# 兼容层：保留旧接口，内部改为走 llm_provider
# 优先级：用户配置(%LOCALAPPDATA%\XianyuTool\api_config.json)
#        → 环境变量 ZHIPUAI_API_KEY → 程序同目录 api_config.json（开发用）
# 配置文件不打进安装包，避免分发时泄露开发者自己的 key
# ============================================================
def _user_config_dir():
    return llm_provider.user_config_dir()


def resolve_api_key():
    """兼容旧接口：返回（文本模型 key, 来源说明）"""
    cfg = llm_provider.load_config()
    key = cfg['text']['api_key']
    if not key:
        return '', '未配置'
    path = llm_provider.config_path()
    source = path if os.path.exists(path) else '环境变量 ZHIPUAI_API_KEY'
    return key, source


API_KEY, API_KEY_SOURCE = resolve_api_key()


def get_model_name():
    """当前文本模型名，供界面显示"""
    return llm_provider.get_llm('text').model

# ============================================================
# V1 词典
# ============================================================
SYNONYM_DICT = {
    # —— 动作类 ——
    '入手': ['拿下', '购入', '收了'],
    '发货': ['寄出', '发出', '走快递'],
    '出售': ['转出', '让出', '出掉'],
    '处理': ['清掉', '出掉', '腾地方'],
    '联系': ['私聊', '找我', '滴滴我'],
    '私聊': ['私信', '单独聊', '找我聊'],
    '议价': ['商量价', '谈价', '价格可聊'],
    '砍价': ['还价', '讲讲价'],
    '拍下': ['下单', '拍走', '直接拍'],

    # —— 称呼类 ——
    '宝贝': ['好物', '这件', '东西'],
    '亲们': ['大家', '朋友们', '各位'],
    '买家': ['需要的朋友', '有缘人'],
    '卖家': ['我', '本人'],

    # —— 成色类 ——
    '全新': ['崭新', '未拆封', '全新未用'],
    '二手': ['用过', '非全新', '别人用过'],
    '九成新': ['95新', '近全新', '成色很好'],
    '八成新': ['85新', '良好成色', '有使用痕迹'],
    '七成新': ['75新', '成色一般', '有明显使用痕迹'],

    # —— 价格类 ——
    '便宜': ['实惠', '划算', '不贵'],
    '低价': ['实惠价', '优惠价', '好价'],
    '价格': ['价钱', '售价'],
    '免费': ['不收费', '白送'],
    '包邮': ['免邮', '包邮寄', '邮费我出'],
    '自提': ['自取', '上门取', '当面拿'],

    # —— 描述类 ——
    '好用': ['实用', '便捷', '顺手'],
    '好看': ['耐看', '颜值可以'],
    '结实': ['耐用', '扎实', '抗造'],
    '质量': ['品质', '做工'],
    '正品': ['原装', '正牌', '官方货'],
    '原装': ['原厂', '原配'],
    '实拍': ['实物图', '真图', '自己拍的'],
    '现货': ['有货', '现成', '随时发'],

    # —— 营销类 ——
    '推荐': ['力荐', '值得入', '可以看看'],
    '热销': ['热卖', '畅销', '卖得好'],
    '限时': ['限量', '限时特惠', '短期'],
    '清仓': ['清库存', '清货', '腾仓'],
    '促销': ['活动', '优惠'],
    '秒杀': ['抢购', '手快有'],

    # —— 连词/副词 ——
    '因为': ['由于', '考虑到'],
    '所以': ['因此', '于是'],
    '但是': ['不过', '只是'],
    '而且': ['并且', '同时'],
    '非常': ['特别', '十分', '相当'],
    '赶紧': ['抓紧', '速来', '尽快'],
    '真的': ['确实', '实在'],
    '比较': ['相对', '还算'],
    '稍微': ['略微', '有一点'],

    # —— 交易场景 ——
    '需要': ['想要', '有需求'],
    '有意': ['感兴趣', '看得上'],
    '确认': ['核实', '看清楚'],
    '售后': ['后续服务', '保修'],
    '赠品': ['送的', '附带'],
    '配件': ['附件', '零件'],
    '运费': ['邮费', '快递费'],
    '包装': ['包材', '外包装'],

    # —— 时间类 ——
    '马上': ['立刻', '这就'],
    '最近': ['近来', '这段时间'],
    '平时': ['平常', '一般'],
}
# 该集合曾用于"保护特定词不被同义词替换"，但其词条与 SYNONYM_DICT 的键没有交集，
# 判断永远为假，属于死逻辑，已移除。

BANNED_WORDS = [
    "第一", "顶级", "极品", "绝版", "万能", "全能",
    "超结实", "性价比拉满", "低于出厂价", "白菜价",
    "国家级", "世界级", "最佳", "最优", "最低价",
    "100%正品", "绝对", "永久", "永不",
    "包治百病", "疗效", "减肥",
    "加微信", "加V", "加我", "私聊",
    "假一赔十", "如假包换",
    "超级好", "超快", "最重",
]

# 单字违禁词：需要上下文判断，以下搭配属于正常用法不算违禁
BANNED_SINGLE = {
    # "最"+这些字属于正常表达，不算极限词
    # 注意：原列表把"近来"放进来了，但判断逻辑是取"最"后面紧跟的两个字，
    # 放"近来"永远匹配不到，应写"最近"。
    "最": ["最后", "最先", "最新", "最终", "最多", "最少", "最初", "最近"],
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
    "最低": "更实惠",
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
        # 变体选择符与零宽连接符必须一起删：像 ❤️ 是 U+2764 + U+FE0F，
        # 只删主体会在文案里留下不可见的 U+FE0F，粘贴到闲鱼后表现为乱码方块
        '\uFE0F',
        '\u200D',
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

def v1_dict_replace(text, choices=None, randomize=False, seed=None):
    """V1 词典替换

    参数：
      choices   {原词: 同义词下标}，指定某个词用第几个
      randomize True 时每个词随机选一个同义词（用户要的「每次不一样」）
      seed      随机种子，传同一个值结果可复现

    优先级：choices 里指定的 > randomize 随机 > 默认第 0 个

    返回 (替换后的文本, 替换明细列表)
    明细结构：[{original, new, count, options, index}, ...]
    index 是这次实际用的下标，前端下拉框按它回显。
    """
    import random as _random

    rng = _random.Random(seed)
    result = text
    changes = []

    # 按词在原文里出现的先后顺序处理，避免长短词互相干扰
    hits = [(k, v) for k, v in SYNONYM_DICT.items() if v and k in result]
    hits.sort(key=lambda kv: -len(kv[0]))

    for original, synonyms in hits:
        if original not in result:
            continue
        if choices and original in choices:
            try:
                idx = int(choices[original])
            except Exception:
                idx = 0
        elif randomize:
            idx = rng.randrange(len(synonyms))
        else:
            idx = 0
        idx = max(0, min(idx, len(synonyms) - 1))
        new_word = synonyms[idx]
        if new_word == original:
            continue
        count = result.count(original)
        result = result.replace(original, new_word)
        changes.append({
            'original': original,
            'new': new_word,
            'count': count,
            'options': list(synonyms),
            'index': idx,
        })

    # 明细按原文出现顺序排，前端显示更自然
    order = {c['original']: text.find(c['original']) for c in changes}
    changes.sort(key=lambda c: order.get(c['original'], 9999))
    return post_process(result), changes

def filter_banned(text):
    warnings = []
    for word in BANNED_WORDS:
        if word in text:
            warnings.append(word)
    # 单字违禁词做上下文检查
    for char, safe_words in BANNED_SINGLE.items():
        if char in text:
            # 逐个定位该字，看它后面紧跟的两个字是否属于安全搭配
            for m in re.finditer(char, text):
                pos = m.start()
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
1. 保持原文结构、卖点顺序、价格规格完全不变
2. 只调整措辞和语气（如"入手"→"拿下"，"赶紧"→"抓紧"）
3. 适当增删语气词，但不能改变核心意思
4. 换同义词但不要换核心卖点
5. 保持口语化闲鱼风格，像真人卖家发的
6. 禁止emoji
7. 不要加标题，只输出正文
8. 不要用"白菜价""超级""最"等违禁词
9. 输出纯文本，不要分段标题
10. 以下词语一律不得出现（出现即违规）：{banned}

原文：
{desc}
"""

V3_PROMPT = """你是闲鱼文案专家。请基于以下商品信息【完整重写】一篇全新文案：

规则：
1. 标题不动，只重写正文
2. 重新组织卖点顺序，用完全不同的表达方式
3. 加入使用场景描述（如"放办公室""宿舍用"）
4. 保持闲鱼风格：口语化、真诚、有吸引力，像朋友推荐
5. 200-400字
6. 禁止emoji
7. 不要用"白菜价""超级""最""第一""绝对"等违禁词
8. 不要喊"亲们""快来抢购"等话术
9. 输出纯文本，不要分段标题
10. 以下词语一律不得出现（出现即违规）：{banned}

商品标题：{title}
原文案（参考卖点，不要照抄）：
{desc}
"""

def call_glm(prompt, max_tokens=1200, temperature=0.7, timeout=60, retries=2):
    """调用文本模型

    实际请求、超时与退避重试都在 llm_provider.LLM.chat 里，
    这里只做配置校验。函数名保留是为了不动上层调用。
    """
    client = llm_provider.get_llm('text')
    if not client.available():
        raise RuntimeError(
            '未配置文本模型！请在程序右上角的 Key 设置里填写：\n'
            'API 地址、API Key、模型名\n'
            '配置文件位置：' + llm_provider.config_path()
        )
    return client.ask(
        prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
        retries=retries,
    )

def v2_ai_light_rewrite(title, desc, banned_str, temperature=0.7):
    # banned_str 之前只作为参数传进来，从未写进 prompt，
    # AI 根本不知道具体哪些词不能用，只能靠规则 8 里列的那几个
    prompt = V2_PROMPT.format(desc=desc, banned=banned_str)
    return post_process(call_glm(prompt, max_tokens=1200, temperature=temperature))

def v3_ai_full_rewrite(title, desc, banned_str, temperature=0.7):
    prompt = V3_PROMPT.format(title=title, desc=desc, banned=banned_str)
    return post_process(call_glm(prompt, max_tokens=1000, temperature=temperature))

def v2_ai_custom(title, desc, custom_prompt, temperature=0.7):
    """V2 自定义提示词微调

    和 V3 自定义的区别：V2 是「微调」，要求保留原文结构和信息点；
    V3 是「重写」，允许推翻重来。
    """
    full_prompt = f"""你是闲鱼文案专家。请在保留原文结构的前提下微调文案，并满足用户的额外要求。

用户要求：
{custom_prompt}

规则：
1. 标题不动，只调整正文
2. 保留原文的段落顺序和关键信息点，不要大改结构
3. 闲鱼风格：口语化、真诚
4. 禁止emoji
5. 不要用"白菜价""超级""最""第一""绝对"等违禁词
6. 以下词语一律不得出现（出现即违规）：{"、".join(BANNED_WORDS)}
7. 输出纯文本

商品标题：{title}
原文案：
{desc}
"""
    return post_process(call_glm(full_prompt, max_tokens=1200, temperature=temperature))


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
6. 以下词语一律不得出现（出现即违规）：{"、".join(BANNED_WORDS)}
7. 输出纯文本

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
    banned_str = "、".join(BANNED_WORDS)
    
    print(f"商品标题: {title}")
    print(f"原文案字数: {len(desc)}")
    print()
    
    # V1是本地词典替换，瞬间完成
    print("--- V1 词典替换 ---")
    # 首次生成也走随机，不然每次重跑结果都一样
    v1, v1_changes = v1_dict_replace(desc, randomize=True)
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
        # V1 改了哪些词，前端要显示出来（原词 -> 新词 + 所有可选同义词）
        "v1_changes": v1_changes,
        "banned_warnings": {"v1": v1_banned, "v2": v2_banned, "v3": v3_banned}
    }


def regenerate_v1(desc):
    """重新生成V1——用随机选同义词，每次结果不同"""
    result = desc
    for original, synonyms in SYNONYM_DICT.items():
        if original in result:
            # 随机选一个同义词
            pick = random.choice(synonyms)
            result = result.replace(original, pick)
    return post_process(result)


def regenerate_v2(title, desc, temperature=None):
    """重新生成V2——用不同temperature，每次结果不同"""
    if temperature is None:
        temperature = round(random.uniform(0.6, 0.95), 2)
    banned_str = "、".join(BANNED_WORDS)
    return post_process(v2_ai_light_rewrite(title, desc, banned_str, temperature=temperature))


def regenerate_v3(title, desc, temperature=None, custom_prompt=None):
    """重新生成V3——用不同temperature，每次结果不同；支持自定义提示词"""
    if temperature is None:
        temperature = round(random.uniform(0.6, 0.95), 2)
    banned_str = "、".join(BANNED_WORDS)
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
