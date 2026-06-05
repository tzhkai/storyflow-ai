"""AI 模型调用、反AI味处理"""
import re
import requests


def call_llm(config, messages, stream=False):
    """统一调用不同模型"""
    model_type = config.get('type', 'ollama')
    max_tokens = config.get('max_tokens', 4096)
    temperature = config.get('temperature', 0.8)
    top_p = config.get('top_p', 0.95)
    repeat_penalty = config.get('repeat_penalty', 1.1)
    frequency_penalty = config.get('frequency_penalty', 0.3)
    presence_penalty = config.get('presence_penalty', 0.3)
    num_ctx = config.get('num_ctx', 4096)

    if model_type == 'ollama':
        base_url = config.get('base_url', 'http://localhost:11434')
        model = config.get('model', 'qwen2.5:7b')
        payload = {
            'model': model, 'messages': messages, 'stream': False,
            'options': {
                'temperature': temperature, 'top_p': top_p,
                'repeat_penalty': repeat_penalty, 'num_predict': max_tokens,
                'num_ctx': num_ctx, 'frequency_penalty': frequency_penalty,
                'presence_penalty': presence_penalty,
            }
        }
        resp = requests.post(f'{base_url}/api/chat', json=payload, timeout=180).json()
        if 'error' in resp:
            raise ValueError(f"Ollama 错误: {resp['error']}")
        return resp['message']['content']

    elif model_type == 'lmstudio':
        base_url = config.get('base_url', 'http://localhost:11435')
        model = config.get('model', '')
        headers = {'Content-Type': 'application/json'}
        payload = {
            'model': model, 'messages': messages,
            'max_tokens': max_tokens, 'temperature': temperature, 'top_p': top_p,
            'repeat_penalty': repeat_penalty, 'frequency_penalty': frequency_penalty,
            'presence_penalty': presence_penalty,
        }
        resp = requests.post(f'{base_url}/v1/chat/completions', headers=headers, json=payload, timeout=180).json()
        if 'error' in resp:
            raise ValueError(f"LM Studio 错误: {resp['error'].get('message', resp['error'])}")
        return resp['choices'][0]['message']['content']

    elif model_type in ['openai', 'deepseek', 'tongyi', 'custom']:
        api_key = config.get('api_key', '')
        base_url = config.get('base_url', 'https://api.openai.com/v1')
        model = config.get('model', 'gpt-3.5-turbo')
        headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
        payload = {
            'model': model, 'messages': messages,
            'max_tokens': max_tokens, 'temperature': temperature, 'top_p': top_p,
            'frequency_penalty': frequency_penalty, 'presence_penalty': presence_penalty,
        }
        resp = requests.post(f'{base_url}/chat/completions', headers=headers, json=payload, timeout=180).json()
        if 'error' in resp:
            raise ValueError(f"API 错误: {resp['error'].get('message', resp['error'])}")
        if 'choices' not in resp:
            raise ValueError(f"API 返回异常: {resp.get('error', str(resp)[:200])}")
        return resp['choices'][0]['message']['content']

    raise ValueError(f'Unknown model type: {model_type}')


def is_sentence_complete(text):
    if not text or len(text) < 50:
        return False
    tail = text.strip()[-50:]
    complete_endings = ['。', '！', '？', '!', '?', '.', '"', '」', '…', '——', '~']
    for ending in complete_endings:
        if tail.rstrip().endswith(ending):
            return True
    if re.search(r'[\n\r]{2,}', tail[-10:]):
        return True
    return False


def extract_chapter_summary(text, max_len=300):
    lines = text.strip().split('\n')
    summary_lines = []
    char_count = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith('#') or len(line) < 5:
            if not line.startswith('#'):
                continue
        summary_lines.append(line)
        char_count += len(line)
        if char_count > max_len:
            break
    return ' '.join(summary_lines)[:max_len]


def auto_continue(model_config, messages, initial_result, max_retries=2):
    result = initial_result
    for attempt in range(max_retries):
        if is_sentence_complete(result):
            break
        last_part = result[-500:]
        continue_msg = {
            'role': 'user',
            'content': f'上文在这里中断了：\n"""\n{last_part}\n"""\n\n请从断点处精确继续，不要重复上文已有的内容，直接续写后续段落。只输出续写内容，不要加任何前缀说明。'
        }
        try:
            continuation = call_llm(model_config, messages + [continue_msg])
            result += continuation
        except Exception:
            break
    return result


# ─── 反 AI 味机制 ───

ANTI_AI_PROMPT = """⛔ 去AI味写作铁律（必须严格遵守）：

【禁用黑名单】以下词汇/句式一律禁止使用：
- 虚词堆叠：然而、不禁、宛如、仿佛、竟、却、隐隐、缓缓、微微、淡淡、轻轻、默默、静静、柔柔、悠悠、悄然、陡然、蓦然、陡地、忽地、蓦地
- 套话模板："这是一个..."、"那是一个..."、"他的眼中闪过一丝..."、"嘴角微微上扬"、"心中一动"、"不由得"、"不由自主"
- 形容词叠堆：不要连续使用两个以上的形容词修饰同一个名词
- 万能比喻：禁止用"如...一般"、"像...似的"超过1次/千字

【必须遵守】
1. 用具体感官细节代替抽象形容
2. 句式长短交替：短句3-8字用于节奏，长句15-30字用于描写
3. 人物对话要有口语感，每个人物有独特的说话习惯
4. 禁止每段开头用"XX的"、"在XX中"的固定模式
5. 比喻和排比有节制：每千字不超过1个比喻
6. 叙事视角一致，不随意切换
7. 留白和省略：不要事无巨细全写出来
8. 环境描写要融入人物行动中
9. 时间推进要有节奏感"""

STYLE_RULES = {
    'literary': """【文学写实模式】
- 克制、精准，每个词都有存在的必要
- 多用白描手法，少用修辞
- 细节要具体到品牌、型号、颜色、气味
- 对话简短有力，不说废话""",

    'colloquial': """【口语化模式】
- 叙述语言接近日常口语，可以略带方言感
- 允许使用口语化的语气词（嘛、呗、哎、哈）
- 句子结构简单直接，少用从句和长定语
- 对话要有大量语气词、省略、打断、重复等真实对话特征""",

    'hardcore': """【硬核简洁模式】
- 极简叙事，能用5个字说完的不用10个字
- 短句为主，平均句长不超过12字
- 砍掉所有不必要的形容词和副词
- 动词优先：用动作推进，不用心理描写""",

    'poetic': """【诗意浪漫模式】
- 可以使用更多修辞，但要有节制，每千字不超过2个比喻
- 修辞要有独创性，禁止用烂俗比喻
- 注重韵律和节奏感，段落结尾的句子要有余韵
- 意象要连贯，同一场景的意象要有内在联系""",
}

_AI_FILLER_MAP = {
    '然而': '', '不禁': '', '宛如': '像', '仿佛': '像',
    '陡然': '突然', '蓦然': '突然', '陡地': '突然', '忽地': '突然', '蓦地': '突然',
    '悄然': '悄悄', '隐隐': '', '缓缓': '慢', '微微': '略',
    '淡淡地': '', '轻轻地': '', '默默地': '', '静静地': '',
    '柔柔地': '', '悠悠地': '',
    '嘴角微微上扬': '笑了笑', '嘴角上扬': '笑了',
    '心中一动': '', '不由得': '', '不由自主': '',
    '他的眼中闪过一丝': '他眼里', '她眼中闪过一丝': '她眼里',
    '一股XX的力量': '', '一股强大的力量': '',
    '仿佛整个世界都': '', '宛如置身于': '',
}


def post_process_text(text, style='literary'):
    if not text:
        return text
    result = text
    for ai_phrase, replacement in _AI_FILLER_MAP.items():
        result = result.replace(ai_phrase, replacement)
    result = re.sub(r'([\u4e00-\u9fff]{2,4}的){3,}',
                    lambda m: m.group(0)[:m.group(0).index('的', m.group(0).index('的') + 1) + 1], result)
    feel_pattern = re.compile(r'(他|她|它)(感到|觉得|心想)')
    feel_matches = list(feel_pattern.finditer(result))
    if len(feel_matches) >= 3:
        for i, match in enumerate(feel_matches[1:-1], 1):
            if i % 2 == 1:
                result = result[:match.start()] + match.group(1) + '的动作暗示了这一点' + result[match.end():]
    if style == 'colloquial':
        colloquial_map = {
            '缓缓': '慢慢', '悄然': '悄悄', '凝视': '盯着看',
            '注视': '看着', '沉思': '想', '叹息': '叹气',
            '漫步': '溜达', '审视': '打量', '凝望': '望着',
            '伫立': '站', '伫足': '停下', '驻足': '停下',
            '疾步': '快步', '疾驰': '飞奔', '蜿蜒': '弯弯绕绕',
            '磅礴': '很大', '恢弘': '很大气', '肃穆': '严肃',
            '缱绻': '亲密', '萦绕': '绕着', '徜徉': '逛',
            '踌躇': '犹豫', '蹒跚': '摇摇晃晃', '踱步': '来回走',
            '凝视': '盯着', '呢喃': '小声说', '啜泣': '抽泣',
            '莞尔': '笑了笑', '抿唇': '闭嘴', '蹙眉': '皱眉',
        }
        for formal, casual in colloquial_map.items():
            result = result.replace(formal, casual)
    result = re.sub(r'  +', ' ', result)
    result = re.sub(r'，，', '，', result)
    result = re.sub(r'。。', '。', result)
    return result
