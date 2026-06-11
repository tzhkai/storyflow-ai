"""
AI Novel Writing Platform - StoryFlow
端口: 8505
重构版：模块化结构，所有密钥从 .env 读取
"""
import sys
import json
import os
import time
import uuid
import re
import threading
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS

from storyflow.config import ACCESS_TOKEN, STATIC_DIR, PRICES, PLATFORM_API_KEY, PLATFORM_API_MODEL, PAYMENT_NOTIFY_URL, PAYMENT_RETURN_URL
from storyflow.storage import load_json, save_json, PROJECTS_FILE, CUSTOM_TEMPLATES_FILE, get_daily_gen_count, increment_daily_gen_count, get_remaining_platform_tokens, consume_platform_tokens
from storyflow.license import TIER_FEATURES, verify_license, get_current_license, get_license_token_id, get_remaining_tokens, PRO_ONLY_TYPES, activate_license, deactivate_license, get_features
from storyflow.ai_service import call_llm, auto_continue, post_process_text, is_sentence_complete, extract_chapter_summary, ANTI_AI_PROMPT, STYLE_RULES
from storyflow.payment_service import create_order, handle_callback, check_order
from storyflow.export_service import generate_txt, generate_docx, generate_epub
from storyflow.presets_data import BUILTIN_PRESETS

app = Flask(__name__, static_folder=str(STATIC_DIR))
CORS(app)

NODE_TYPE_LABELS = {
    'genre': '题材设定', 'world': '世界观设定', 'protagonist': '主角设定',
    'outline': '故事大纲', 'conflict': '冲突设定', 'style': '写作风格',
    'setting_detail': '细节设定', 'romance': '情感关系', 'chapter': '章节设定',
    'characters': '角色设定', 'pov': '叙事视角', 'custom': '自定义模板',
}

def _node_type_label(t):
    return NODE_TYPE_LABELS.get(t, t)

# ========== API 认证 ==========
@app.before_request
def _check_api_auth():
    if ACCESS_TOKEN and request.path.startswith('/api/'):
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer ') or auth[7:] != ACCESS_TOKEN:
            return jsonify({'ok': False, 'error': '未授权，请提供有效的访问令牌'}), 401

# ========== License API ==========
@app.route('/api/license', methods=['GET'])
def get_license():
    lic = get_current_license()
    lic['daily_generations'] = get_daily_gen_count()
    return jsonify(lic)

@app.route('/api/license/activate', methods=['POST'])
def activate_license_api():
    data = request.json or {}
    order_id = data.get('order_id', '').strip()
    key = data.get('key', '').strip().upper()
    if order_id:
        import requests
        verify_url = 'https://api.knexio.xyz/api/v1/afdian/activate'
        try:
            r = requests.post(verify_url, json={'order_id': order_id}, timeout=10)
            rd = r.json()
            if rd.get('ok'):
                from storyflow.storage import save_json
                from storyflow.license import LICENSE_FILE
                save_json(LICENSE_FILE, {'key': order_id, 'activated_at': __import__('time').time(), 'tier': rd['tier']})
                return jsonify({'ok': True, 'tier': rd['tier'], 'info': rd['info'], 'message': f"已激活 {rd['info']['name']}！"})
            return jsonify({'ok': False, 'error': rd.get('error', '订单号无效')}), 400
        except Exception as e:
            return jsonify({'ok': False, 'error': f'验证服务不可达: {e}'}), 503
    if not key:
        return jsonify({'ok': False, 'error': '请输入 License Key 或订单号'}), 400
    result = activate_license(key)
    if not result.get('ok'):
        return jsonify(result), 400
    return jsonify(result)

@app.route('/api/license/deactivate', methods=['POST'])
def deactivate_license_api():
    deactivate_license()
    return jsonify({'ok': True, 'message': '已退回免费版'})

@app.route('/api/license/features', methods=['GET'])
def get_features_api():
    return jsonify(get_features())

# ========== 项目管理 ==========
@app.route('/api/projects', methods=['GET'])
def get_projects():
    return jsonify(load_json(PROJECTS_FILE, []))

@app.route('/api/projects', methods=['POST'])
def create_project():
    data = request.json
    lic = get_current_license()
    max_flows = lic['info'].get('max_flows', 1)
    projects = load_json(PROJECTS_FILE, [])
    if len(projects) >= max_flows:
        return jsonify({
            'error': f'{"免费版" if lic["tier"] == "free" else "当前版本"}最多创建 {max_flows} 个项目，请删除旧项目或升级',
            'tier': lic['tier'], 'max_flows': max_flows
        }), 403
    project = {
        'id': str(uuid.uuid4()),
        'name': data.get('name', '新小说项目'),
        'created': time.time(), 'updated': time.time(),
        'nodes': data.get('nodes', []), 'edges': data.get('edges', []),
        'settings': data.get('settings', {}), 'output': data.get('output', '')
    }
    projects.append(project)
    save_json(PROJECTS_FILE, projects)
    return jsonify(project)

@app.route('/api/projects/<project_id>', methods=['GET'])
def get_project(project_id):
    projects = load_json(PROJECTS_FILE, [])
    for p in projects:
        if p['id'] == project_id:
            return jsonify(p)
    return jsonify({'error': 'not found'}), 404

@app.route('/api/projects/<project_id>', methods=['PUT'])
def update_project(project_id):
    data = request.json
    projects = load_json(PROJECTS_FILE, [])
    for p in projects:
        if p['id'] == project_id:
            p.update(data)
            p['updated'] = time.time()
            save_json(PROJECTS_FILE, projects)
            return jsonify(p)
    return jsonify({'error': 'not found'}), 404

@app.route('/api/projects/<project_id>', methods=['DELETE'])
def delete_project(project_id):
    projects = load_json(PROJECTS_FILE, [])
    projects = [p for p in projects if p['id'] != project_id]
    save_json(PROJECTS_FILE, projects)
    return jsonify({'ok': True})

# ========== 预设数据 ==========
@app.route('/api/presets', methods=['GET'])
def get_presets():
    return jsonify(BUILTIN_PRESETS)

@app.route('/api/presets/<category>', methods=['GET'])
def get_category_presets(category):
    if category in BUILTIN_PRESETS:
        return jsonify(BUILTIN_PRESETS[category])
    return jsonify({'error': 'not found'}), 404

# ========== 自定义模板 ==========
@app.route('/api/custom-templates', methods=['GET'])
def get_custom_templates():
    return jsonify(load_json(CUSTOM_TEMPLATES_FILE, []))

@app.route('/api/custom-templates', methods=['POST'])
def save_custom_template():
    data = request.json
    templates = load_json(CUSTOM_TEMPLATES_FILE, [])
    template = {
        'id': str(uuid.uuid4())[:8],
        'name': data.get('name', '未命名模板'),
        'created': time.time(),
        'nodes': data.get('nodes', []), 'edges': data.get('edges', [])
    }
    templates.append(template)
    save_json(CUSTOM_TEMPLATES_FILE, templates)
    return jsonify(template)

@app.route('/api/custom-templates/<template_id>', methods=['DELETE'])
def delete_custom_template(template_id):
    templates = load_json(CUSTOM_TEMPLATES_FILE, [])
    templates = [t for t in templates if t['id'] != template_id]
    save_json(CUSTOM_TEMPLATES_FILE, templates)
    return jsonify({'ok': True})

# ========== 模型配置测试 ==========
@app.route('/api/models/test', methods=['POST'])
def test_model():
    import requests
    data = request.json
    model_type = data.get('type', 'ollama')
    config = data.get('config', {})
    try:
        if model_type == 'ollama':
            base_url = config.get('base_url', 'http://localhost:11434')
            r = requests.get(f'{base_url}/api/tags', timeout=5)
            models = [m['name'] for m in r.json().get('models', [])]
            return jsonify({'ok': True, 'models': models})
        elif model_type == 'lmstudio':
            base_url = config.get('base_url', 'http://localhost:11435')
            r = requests.get(f'{base_url}/v1/models', timeout=5)
            models = [m['id'] for m in r.json().get('data', [])]
            return jsonify({'ok': True, 'models': models})
        elif model_type in ['openai', 'deepseek', 'tongyi', 'custom']:
            api_key = config.get('api_key', '')
            base_url = config.get('base_url', 'https://api.openai.com/v1')
            model = config.get('model', 'gpt-3.5-turbo')
            headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
            r = requests.post(f'{base_url}/chat/completions',
                headers=headers,
                json={'model': model, 'messages': [{'role': 'user', 'content': 'hi'}], 'max_tokens': 5},
                timeout=10)
            if r.status_code == 200:
                return jsonify({'ok': True, 'models': [model]})
            else:
                return jsonify({'ok': False, 'error': r.text}), 400
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 400

# ========== AI 生成选项 ==========
@app.route('/api/ai/generate-options', methods=['POST'])
def generate_options():
    data = request.json
    node_type = data.get('node_type', '')
    context = data.get('context', {})
    mc = data.get('model_config', {})
    count = data.get('count', 4)
    lic = get_current_license()

    if node_type in PRO_ONLY_TYPES and lic['tier'] != 'professional':
        return jsonify({'ok': False, 'error': '此模板仅专业版可用，请升级', 'tier': lic['tier']}), 403

    allowed_templates = lic['info'].get('template_types', ['genre'])
    if node_type not in allowed_templates:
        return jsonify({'ok': False, 'error': f'当前版本不支持「{_node_type_label(node_type)}」模板，请升级', 'tier': lic['tier']}), 403

    max_templates = lic['info'].get('max_template_calls', 3)
    from storyflow.storage import get_template_daily_count, increment_template_daily_count
    if get_template_daily_count() >= max_templates:
        return jsonify({'ok': False, 'error': f'{"免费版" if lic["tier"]=="free" else "当前版本"}每日模板生成为 {max_templates} 次，今日已用完', 'tier': lic['tier']}), 403

    use_platform = data.get('use_platform_api', False)
    if use_platform:
        if lic['tier'] == 'free':
            return jsonify({'ok': False, 'error': '平台 API 仅支持付费版本'}), 403
        remaining = get_remaining_tokens(lic)
        if remaining <= 0:
            return jsonify({'ok': False, 'error': '平台 API Token 已用完'}), 403
        mc = {'type': 'deepseek', 'api_key': 'proxy', 'base_url': 'https://api.knexio.xyz/api/v1', 'model': PLATFORM_API_MODEL}

    prompts = {
        'genre': f"请为一部小说生成{count}个独特的体裁/类型设定方向，以JSON数组返回，每个包含：name(名称), desc(50字描述), tags(3个关键词数组)。只返回JSON，不要其他文字。",
        'world': f"基于体裁：{context.get('genre','')}\n请生成{count}个独特的世界观设定，JSON数组，每个包含：name, desc(80字), tags(4个关键词)。只返回JSON。",
        'protagonist': f"基于世界观：{context.get('world','')}\n请生成{count}个有特色的主角人物设定，JSON数组，每个包含：name, desc(80字), tags(4个关键词)。只返回JSON。",
        'outline': f"基于体裁{context.get('genre','')}和主角{context.get('protagonist','')}\n请生成{count}个故事大纲方向，JSON数组，每个包含：name, desc(100字), tags(4个关键词)。只返回JSON。",
        'conflict': f"基于大纲：{context.get('outline','')}\n请生成{count}个核心冲突设定，JSON数组，每个包含：name, desc(80字), tags(4个关键词)。只返回JSON。",
        'style': f"为{context.get('genre','')}体裁推荐{count}种写作风格，JSON数组，每个包含：name, desc(60字), tags(3个关键词)。只返回JSON。",
        'setting_detail': f"基于以上设定，生成{count}个重要的细节设定，JSON数组，每个包含：name, desc(100字), tags(4个关键词)。只返回JSON。",
        'romance': f"基于体裁{context.get('genre','')}和主角{context.get('protagonist','')}，生成{count}个独特的情感关系设定（BL/GL/姐弟恋/禁忌等），JSON数组，每个包含：name, desc(80字), tags(4个关键词)。只返回JSON。",
    }

    try:
        messages = [
            {'role': 'system', 'content': '你是一个专业的小说创作顾问，熟悉各种类型小说的创作要素。请按用户要求生成创意选项，只返回有效JSON，不要多余文字。'},
            {'role': 'user', 'content': prompts.get(node_type, f"为小说的{node_type}节点生成{count}个预设选项，JSON数组返回，每个含name/desc/tags字段。只返回JSON。")}
        ]
        result = call_llm(mc, messages)
        if use_platform:
            consume_platform_tokens(get_license_token_id(), max(len(result), len(result)//3))
        increment_template_daily_count()
        json_match = re.search(r'\[.*\]', result, re.DOTALL)
        if json_match:
            options = json.loads(json_match.group())
            for i, opt in enumerate(options):
                opt['id'] = f'ai_{node_type}_{i}_{int(time.time())}'
                opt['ai_generated'] = True
            return jsonify({'ok': True, 'options': options})
        else:
            return jsonify({'ok': False, 'error': '无法解析AI返回的JSON', 'raw': result})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

# ========== AI 写作执行 ==========
writing_tasks = {}

def _cleanup_writing_tasks(interval=300):
    while True:
        time.sleep(interval)
        now = time.time()
        expired = [tid for tid, t in writing_tasks.items()
                   if t.get('status') in ('done', 'error') and now - t.get('_ts', 0) > 3600]
        for tid in expired:
            writing_tasks.pop(tid, None)

threading.Thread(target=_cleanup_writing_tasks, daemon=True).start()

@app.route('/api/ai/write', methods=['POST'])
def start_writing():
    data = request.json or {}
    model_config = data.get('model_config', {})
    lic = get_current_license()
    writing_style = data.get('writing_style', 'literary')

    allowed_styles = lic['info'].get('writing_styles', ['literary'])
    if writing_style not in allowed_styles:
        return jsonify({'error': f'当前版本不支持「{writing_style}」风格，请升级', 'tier': lic['tier'], 'allowed': allowed_styles}), 403

    use_platform_api = data.get('use_platform_api', False)
    if use_platform_api:
        if lic['tier'] == 'free':
            return jsonify({'error': '平台 API 仅支持付费版本使用，请先升级', 'tier': 'free'}), 403
        remaining = get_remaining_tokens(lic)
        if remaining <= 0:
            return jsonify({'error': '平台 API Token 已用完，请使用自己的 Key 或升级', 'tier': lic['tier']}), 403
        model_config = {'type': 'deepseek', 'api_key': 'proxy', 'base_url': 'https://api.knexio.xyz/api/v1', 'model': PLATFORM_API_MODEL}

    daily_count = get_daily_gen_count()
    max_gen = lic['info'].get('max_daily_generations', 3)
    if daily_count >= max_gen:
        return jsonify({'error': f'{"免费版" if lic["tier"] == "free" else "当前版本"}每日限{max_gen}次生成，今日已用完。', 'tier': lic['tier'], 'daily_count': daily_count, 'max_daily': max_gen}), 403

    task_id = str(uuid.uuid4())
    writing_tasks[task_id] = {'status': 'pending', 'progress': 0, 'output': '', 'error': None, 'chapter_summaries': [], '_ts': time.time()}

    def do_write():
        try:
            writing_tasks[task_id]['status'] = 'running'
            flow_config = data.get('flow', {})

            NODE_LABELS = {
                'genre':'体裁', 'world':'世界观', 'protagonist':'主角', 'outline':'故事大纲',
                'conflict':'核心冲突', 'style':'写作风格', 'chapter':'章节规划', 'pov':'叙事视角',
                'setting_detail':'细节设定', 'romance':'情感关系', 'characters':'角色设定',
                'custom':'自定义设定',
            }

            flow_parts = []
            char_name_parts = []
            wc = 2500
            cc = 30
            custom_notes = flow_config.get('custom_notes', '')
            for key, node_data in flow_config.items():
                if key == 'custom_notes':
                    continue
                sel = node_data.get('selected', {})
                label = NODE_LABELS.get(key, key)
                if sel and sel.get('name'):
                    flow_parts.append(f"【{label}】{sel['name']}：{sel.get('desc','')}")
                elif sel and sel.get('desc'):
                    flow_parts.append(f"【{label}】{sel.get('desc','')}")
                if node_data.get('char_name'):
                    cn = node_data['char_name']
                    cr = node_data.get('char_role', '')
                    cd = node_data.get('char_desc', '')
                    detail = '，'.join(filter(None, [cr, cd]))
                    name_for_label = sel.get('name', key) if sel else key
                    char_name_parts.append(f"【{name_for_label}姓名】{cn}{f'（{detail}）' if detail else ''}")
                if node_data.get('word_count'):
                    wc = node_data['word_count']
                if node_data.get('chapter_count'):
                    cc = node_data['chapter_count']

            flow_text = '\n'.join(flow_parts) if flow_parts else ''
            char_name_text = '\n'.join(char_name_parts) if char_name_parts else ''
            custom_prompt = data.get('custom_prompt', '')
            writing_style = data.get('writing_style', 'literary')
            style_rules = STYLE_RULES.get(writing_style, STYLE_RULES['literary'])

            anti_ai_level = lic['info']['anti_ai_level']
            if anti_ai_level == 'basic':
                anti_ai_text = """【去AI味要求（基础模式）】
- 避免使用最常见的AI套话（然而、不禁、宛如、仿佛）
- 保持文字自然，不要过度修饰
- 允许适量形容词，不要把每个句子都写得很华丽"""
            elif anti_ai_level == 'full':
                anti_ai_text = ANTI_AI_PROMPT
            elif anti_ai_level == 'custom':
                anti_ai_text = ANTI_AI_PROMPT + "\n\n【自定义增强模式】\n- 你可以根据用户提供的额外去AI味规则进行动态调整\n- 对输出的文字进行多轮自检，确保达到出版级自然度"

            system_prompt = f"""你是一位专业的小说作者，擅长各种题材的创作。
请根据用户提供的设定，创作出引人入胜的小说内容。

{anti_ai_text}

{style_rules}

⚠️ 以下规则必须严格遵守：
1. ⛔ 人物姓名必须严格使用设定中给出的名字，不得自行更改或创造新名字
2. ⛔ 保持角色设定的一致性（性格、背景、关系），从头到尾不能变
3. ⛔ 情节推进要有逻辑，不能出现设定外的突兀事件或与主线无关的任务
4. ⛔ 每章字数控制在设定范围内，章节之间长度不能相差太大
5. ⛔ 避免在每一章重复相同的描述和句式（如反复出现特定词汇）
6. 人物对话要自然有个性，情节紧凑有节奏感
7. 章节标题格式必须为「第X章」（X为中文数字），不得使用其他格式
8. 确保输出完整，不要中途截断
9. 绝不要写出"AI味"的文字——避免套话、虚词堆叠、形容词泛滥"""

            if custom_prompt:
                system_prompt += f"\n\n【用户自定义约束规则】(以下为附加约束，如有与上述规则冲突，以上述规则为准)\n{custom_prompt}\n"

            user_prompt = f"""请根据以下设定创作小说：

{flow_text}

【字数设定】每章约{wc}字，共{cc}章
{char_name_text if char_name_text else ''}
【补充说明】{custom_notes}

⚠️ 人物姓名必须严格遵守，不得自行更改或创造新名字。设定中的人物必须使用指定姓名。
{char_name_text if char_name_text else '使用设定中默认的角色名'}

请先写出：
1. 小说标题（3个备选）
2. 内容简介（200字）
3. 完整章节内容（至少2000字，以「第一章」为章节标题）

按照以上格式输出。确保内容完整，不要写到一半中断。"""

            writing_tasks[task_id]['progress'] = 20
            messages = [{'role': 'system', 'content': system_prompt}, {'role': 'user', 'content': user_prompt}]
            result = call_llm(model_config, messages)
            writing_tasks[task_id]['progress'] = 60
            result = auto_continue(model_config, messages, result)
            result = post_process_text(result, writing_style)
            writing_tasks[task_id]['output'] = result
            summary = extract_chapter_summary(result)
            if summary:
                writing_tasks[task_id]['chapter_summaries'].append(summary)
            writing_tasks[task_id]['progress'] = 100
            if use_platform_api:
                output_len = len(result)
                consume_platform_tokens(get_license_token_id(), max(output_len, output_len // 3))
            writing_tasks[task_id]['status'] = 'done'
            increment_daily_gen_count()
        except Exception as e:
            writing_tasks[task_id]['status'] = 'error'
            writing_tasks[task_id]['error'] = str(e)

    t = threading.Thread(target=do_write)
    t.daemon = True
    t.start()
    return jsonify({'task_id': task_id})

@app.route('/api/ai/write/<task_id>', methods=['GET'])
def get_writing_task(task_id):
    if task_id not in writing_tasks:
        return jsonify({'error': 'not found'}), 404
    return jsonify(writing_tasks[task_id])

@app.route('/api/ai/write/<task_id>/continue', methods=['POST'])
def continue_writing(task_id):
    data = request.json or {}
    model_config = data.get('model_config', {})
    task_id_new = str(uuid.uuid4())

    prev_summaries = []
    if task_id in writing_tasks:
        prev_summaries = writing_tasks[task_id].get('chapter_summaries', [])

    writing_tasks[task_id_new] = {'status': 'pending', 'progress': 0, 'output': '', 'error': None, 'chapter_summaries': list(prev_summaries), '_ts': time.time()}

    def do_continue():
        try:
            nonlocal_model_config = model_config
            _use_platform_api = data.get('use_platform_api', False)
            if _use_platform_api:
                lic_pre = get_current_license()
                if lic_pre['tier'] == 'free':
                    writing_tasks[task_id_new]['status'] = 'error'
                    writing_tasks[task_id_new]['error'] = '平台 API 仅支持付费版本使用，请先升级'
                    return
                remaining = get_remaining_tokens(lic_pre)
                if remaining <= 0:
                    writing_tasks[task_id_new]['status'] = 'error'
                    writing_tasks[task_id_new]['error'] = '平台 API Token 已用完，请使用自己的 Key 或升级'
                    return
                nonlocal_model_config = {'type': 'deepseek', 'api_key': 'proxy', 'base_url': 'https://api.knexio.xyz/api/v1', 'model': PLATFORM_API_MODEL}

            lic_cont = get_current_license()
            writing_style = data.get('writing_style', 'literary')
            allowed_styles = lic_cont['info'].get('writing_styles', ['literary'])
            if writing_style not in allowed_styles:
                writing_tasks[task_id_new]['status'] = 'error'
                writing_tasks[task_id_new]['error'] = f'当前版本不支持「{writing_style}」风格，请升级'
                return

            writing_tasks[task_id_new]['status'] = 'running'
            prev_content = data.get('prev_content', '')
            next_chapter_num = data.get('chapter_num', len(prev_summaries) + 1)
            CN_NUMS = ['零','一','二','三','四','五','六','七','八','九','十',
                       '十一','十二','十三','十四','十五','十六','十七','十八','十九','二十']
            cn_num = CN_NUMS[next_chapter_num] if next_chapter_num < len(CN_NUMS) else str(next_chapter_num)

            instruction = data.get('instruction', '请继续写下一章')
            custom_prompt_cont = data.get('custom_prompt', '')
            custom_prompt_block = f"\n\n【用户自定义约束规则】(以下为附加约束，如有与上述规则冲突，以上述规则为准)\n{custom_prompt_cont}\n" if custom_prompt_cont else ""
            instruction = f"⚠️ CRITICAL: 你的输出必须以「第{cn_num}章」作为章节标题开头，使用中文数字格式。绝对不能写其他章节号。\n\n{instruction}"
            total_ch = data.get('total_chapters', 0)
            if total_ch > 0 and next_chapter_num >= total_ch:
                instruction += '\n\n⚠️ 这是小说的最后一章，必须完整收尾所有主要故事线和人物关系，给出一个合理的结局。不能留坑，不能突然中断。确保故事有一个完整的收束。'

            style_rules = STYLE_RULES.get(writing_style, STYLE_RULES['literary'])
            anti_ai_level = lic_cont['info']['anti_ai_level']
            if anti_ai_level == 'basic':
                anti_ai_text = "【去AI味要求（基础模式）】\n- 避免使用最常见的AI套话\n- 保持文字自然，不要过度修饰"
            elif anti_ai_level == 'full':
                anti_ai_text = ANTI_AI_PROMPT
            elif anti_ai_level == 'custom':
                anti_ai_text = ANTI_AI_PROMPT + "\n\n【自定义增强模式】对输出进行多轮自检，确保出版级自然度"

            writing_tasks[task_id_new]['progress'] = 10
            summary_text = ''
            for i, s in enumerate(prev_summaries):
                summary_text += f'第{i+1}章摘要：{s}\n'
            if not summary_text:
                summary_text = prev_content[-500:]

            last_paragraph = prev_content.strip()[-300:]

            anti_repeat_rules = """⛔ 防重复规则（必须严格遵守）：
1. 不要重复前面章节已出现过的场景、对话、情节
2. 每个新场景必须有实质性的情节推进
3. 人物的行动和对话要有新的信息量，不能是已有信息的变体
4. 避免反复使用相同的描述词汇
5. 如果感觉情节陷入循环，引入新的冲突元素或外部事件打破僵局
6. 新章节的每一段文字都要向前推进故事，不能原地打转"""

            flow_config = data.get('flow', {})
            flow_parts = []
            wc_keys = [('genre','体裁'),('world','世界观'),('protagonist','主角'),('outline','大纲'),('conflict','冲突'),('style','风格'),('pov','视角'),('setting_detail','细节'),('romance','情感'),('characters','角色')]
            for key, label in wc_keys:
                sel = flow_config.get(key, {}).get('selected', {})
                if sel and sel.get('name'):
                    flow_parts.append(f"【{label}】{sel['name']}：{sel.get('desc','')}")
                cn = flow_config.get(key, {}).get('char_name')
                if cn:
                    cr = flow_config.get(key, {}).get('char_role', '')
                    flow_parts.append(f"【{label}姓名】{cn}{f'（{cr}）' if cr else ''}")
            chap_cfg = flow_config.get('chapter', {})
            chap_sel = chap_cfg.get('selected', {})
            if chap_sel and chap_sel.get('name'):
                flow_parts.append(f"【章节】{chap_sel['name']}：{chap_sel.get('desc','')}")
            wc = chap_cfg.get('word_count', 2500)
            cc = chap_cfg.get('chapter_count', 30)
            flow_parts.append(f"【字数】每章约{wc}字，共{cc}章")
            flow_text = '\n'.join(flow_parts) if flow_parts else ''

            messages = [
                {'role': 'system', 'content': f"""你是专业小说作者。请根据已有摘要继续创作下一章。

{anti_ai_text}

{style_rules}

{anti_repeat_rules}
⚠️ 绝对规则（必须遵守）：
- 当前要写的是「第{cn_num}章」，你的输出必须以「第{cn_num}章」作为章节标题开头
- 严禁输出其他章节号，严禁从「第一章」重新开始
- 保持风格一致，情节自然衔接
- 人物姓名必须保持与已有章节一致，不得自行改名
- 每段都要推动故事向前发展
- 人物对话要体现人物性格的成长和变化
- 避免使用与前文相似的句式、比喻和描写
- 每章字数不要相差太大，保持均匀
- 绝不要写出"AI味"的文字{custom_prompt_block}"""},
                {'role': 'user', 'content': f"""【当前作品设定】
{flow_text if flow_text else '沿用初始设定'}

【已写章节摘要】
{summary_text}

【上一章结尾】
{last_paragraph}

---
{instruction}，请写出完整章节（至少1500字）。

注意：新章节必须有新的情节发展、新的场景或新的人物互动，绝不能重复前文内容。"""}
            ]

            writing_tasks[task_id_new]['progress'] = 30
            anti_repeat_config = dict(nonlocal_model_config)
            anti_repeat_config['repeat_penalty'] = nonlocal_model_config.get('repeat_penalty', 1.1) + 0.15
            anti_repeat_config['frequency_penalty'] = nonlocal_model_config.get('frequency_penalty', 0.3) + 0.2
            anti_repeat_config['presence_penalty'] = nonlocal_model_config.get('presence_penalty', 0.3) + 0.2

            result = call_llm(anti_repeat_config, messages)
            writing_tasks[task_id_new]['progress'] = 70
            result = auto_continue(anti_repeat_config, messages, result)
            result = post_process_text(result, writing_style)
            writing_tasks[task_id_new]['output'] = result

            if not result or not result.strip():
                writing_tasks[task_id_new]['status'] = 'error'
                writing_tasks[task_id_new]['error'] = 'AI 返回内容为空，请重试'
                writing_tasks[task_id_new]['progress'] = 0
                return

            summary = extract_chapter_summary(result)
            if summary:
                writing_tasks[task_id_new]['chapter_summaries'].append(summary)
            writing_tasks[task_id_new]['progress'] = 100
            writing_tasks[task_id_new]['status'] = 'done'

            if _use_platform_api:
                consume_platform_tokens(get_license_token_id(), max(len(result), len(result) // 3))
            increment_daily_gen_count()
        except Exception as e:
            import traceback
            print(f'[ERROR] continue_writing failed: {e}', flush=True)
            traceback.print_exc()
            writing_tasks[task_id_new]['status'] = 'error'
            writing_tasks[task_id_new]['error'] = str(e)

    t = threading.Thread(target=do_continue)
    t.daemon = True
    t.start()
    return jsonify({'task_id': task_id_new})

# ========== 导出 ==========
@app.route('/api/export', methods=['POST'])
def export_content():
    data = request.json or {}
    fmt = data.get('format', 'txt')
    lic = get_current_license()
    allowed = lic['info'].get('export_formats', ['txt'])
    if fmt not in allowed:
        return jsonify({'ok': False, 'error': f'当前版本不支持导出为 {fmt.upper()}，请升级', 'tier': lic['tier'], 'allowed': allowed}), 403
    return jsonify({'ok': True, 'format': fmt})

@app.route('/api/export2', methods=['POST'])
def export_file():
    from flask import Response
    data = request.json
    text = data.get('text', '')
    fmt = data.get('format', 'txt')
    title = data.get('title', '小说')
    if not text.strip():
        return jsonify({'error': '内容为空'}), 400

    lic = get_current_license()
    allowed = lic['info'].get('export_formats', ['txt'])
    if fmt not in allowed:
        return jsonify({'error': f'当前版本不支持导出为 {fmt.upper()}，请升级'}), 403

    if fmt == 'txt':
        content, mimetype, safe_title = generate_txt(text, title)
        return Response(content, mimetype=mimetype, headers={'Content-Disposition': f"attachment; filename*=UTF-8''{safe_title}"})
    elif fmt == 'docx':
        content, mimetype, safe_title = generate_docx(text, title)
        return Response(content, mimetype=mimetype, headers={'Content-Disposition': f"attachment; filename*=UTF-8''{safe_title}"})
    elif fmt == 'epub':
        content, mimetype, safe_title = generate_epub(text, title)
        return Response(content, mimetype=mimetype, headers={'Content-Disposition': f"attachment; filename*=UTF-8''{safe_title}"})
    return jsonify({'error': f'不支持的格式: {fmt}'}), 400

# ========== 支付 ==========
@app.route('/api/payment/create-order', methods=['POST'])
def api_create_payment_order():
    data = request.json or {}
    tier = data.get('tier', 'standard')
    pay_type = data.get('pay_type', 'alipay')
    result = create_order(tier, pay_type)
    if 'error' in result:
        return jsonify(result), 400 if 'ok' not in result else 500
    return jsonify(result)

@app.route('/api/payment/callback', methods=['POST'])
def api_payment_callback():
    result, status = handle_callback(dict(request.form))
    return result, status

@app.route('/api/payment/check-order', methods=['POST'])
def api_check_payment_order():
    data = request.json or {}
    order_id = data.get('order_id', '')
    if not order_id:
        return jsonify({'error': '缺少订单号'}), 400
    result = check_order(order_id)
    if 'error' in result:
        return jsonify(result), 404
    return jsonify(result)

@app.route('/api/payment/prices', methods=['GET'])
def api_payment_prices():
    from storyflow.config import PRICES
    return jsonify({'ok': True, 'prices': {tier: info for tier, info in PRICES.items()}})

# ========== 首页 ==========
@app.route('/')
def index():
    from storyflow.config import PRICES
    lic = get_current_license()
    info = dict(lic['info'])
    if info.get('platform_api_tokens', 0) > 0:
        remaining = get_remaining_tokens(lic)
        info['platform_tokens_remaining'] = remaining
        info['platform_tokens_total'] = lic['info']['platform_api_tokens']
    license_json = json.dumps({'tier': lic['tier'], 'features': info}, ensure_ascii=False)
    html_path = Path(__file__).parent / 'static' / 'index.html'
    with open(html_path, 'r', encoding='utf-8') as f:
        html = f.read()
    inject = f'\n<script>window.__LICENSE__ = {license_json};</script>\n</head>'
    html = html.replace('</head>', inject, 1)
    resp = Response(html, mimetype='text/html')
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp

@app.route('/<path:filename>')
def static_files(filename):
    return send_from_directory(str(STATIC_DIR), filename)

if __name__ == '__main__':
    print("AI小说写作平台启动中...", flush=True)
    print("访问地址: http://127.0.0.1:8505", flush=True)
    print("提示: 所有密钥和配置均从 .env 文件读取", flush=True)
    app.run(host='127.0.0.1', port=8505, threaded=True)
