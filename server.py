"""
AI Novel Writing Platform - Backend Server
Port: 8505
"""
# ========== 启动检查：缺依赖直接提示 ==========
import sys

_missing = []
try:
    from flask import Flask, request, jsonify, send_from_directory
except ImportError:
    _missing.append('flask')

try:
    import flask_cors
except ImportError:
    _missing.append('flask-cors')

try:
    import requests
except ImportError:
    _missing.append('requests')

if _missing:
    print("\n" + "="*50)
    print("❌ 缺少依赖：", ', '.join(_missing))
    print("请在终端运行：")
    print(f"  {sys.executable} -m pip install " + ' '.join(_missing))
    print("="*50 + "\n")
    sys.exit(1)

# ========== 正式导入 ==========
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import json
import os
import hashlib
import hmac
import requests
import threading
import time
import uuid
import re as _re
from pathlib import Path

app = Flask(__name__, static_folder='static')
CORS(app)

# ========== 数据存储 ==========
DATA_DIR = Path(__file__).parent / 'data'
DATA_DIR.mkdir(exist_ok=True)
PROJECTS_FILE = DATA_DIR / 'projects.json'
PRESETS_FILE = DATA_DIR / 'presets.json'
CUSTOM_TEMPLATES_FILE = DATA_DIR / 'custom_templates.json'

# ========== License 机制 ==========
# 加载本地 .env（不上传 GitHub）
_env_file = Path(__file__).parent / '.env'
if _env_file.exists():
    with open(_env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())
# 签名密钥（生产环境应从环境变量读取，此处为演示用）
_LICENSE_SECRET = b'storyflow-license-secret-2026'

# ========== 平台 API（付费用户可选） ==========
# 从二进制文件读取（肉眼不可读）
_plat_key_file = Path(__file__).parent / 'platform_api.dat'
if _plat_key_file.exists():
    xor_key = b'StoryFlow' * 10
    with open(_plat_key_file, 'rb') as f:
        raw = f.read()
    PLATFORM_API_KEY = ''.join(chr(b ^ xor_key[i % len(xor_key)]) for i, b in enumerate(raw))
else:
    PLATFORM_API_KEY = ''
PLATFORM_API_MODEL = os.environ.get('SF_PLATFORM_MODEL', 'deepseek-v4-flash')
LICENSE_FILE = DATA_DIR / 'license.json'

# ========== 功能分级定义 ==========
TIER_FEATURES = {
    'free': {
        'name': '免费版',
        'max_flows': 1,
        'max_daily_generations': 3,
        'export_formats': ['txt'],
        'writing_styles': ['literary', 'colloquial'],
        'anti_ai_level': 'basic',
        'max_template_calls': 3,
        'template_types': ['genre'],
    },
    'standard': {
        'name': '标准版',
        'max_flows': 5,
        'max_daily_generations': 50,
        'export_formats': ['txt', 'pdf'],
        'writing_styles': ['literary', 'colloquial', 'hardcore', 'poetic'],
        'anti_ai_level': 'full',
        'platform_api': True,
        'platform_api_tokens': 1000000,
        'max_template_calls': 50,
        'template_types': ['genre', 'outline'],
    },
    'professional': {
        'name': '专业版',
        'max_flows': 999,
        'max_daily_generations': 999,
        'export_formats': ['txt', 'pdf', 'epub', 'docx'],
        'writing_styles': ['literary', 'colloquial', 'hardcore', 'poetic', 'custom'],
        'anti_ai_level': 'custom',
        'platform_api': True,
        'platform_api_tokens': 5000000,
        'max_template_calls': 999,
        'template_types': ['genre', 'world', 'protagonist', 'outline', 'conflict', 'style', 'setting_detail', 'romance', 'chapter', 'characters', 'pov', 'custom'],
    },
}

def _sign_key(key_data: str) -> str:
    """HMAC-SHA256 签名"""
    return hmac.new(_LICENSE_SECRET, key_data.encode('utf-8'), hashlib.sha256).hexdigest()[:24]

def _verify_license(license_key: str) -> dict:
    """验证 License Key，返回 {valid, tier, info}"""
    try:
        # Key 格式: SF-{tier_code}-{random}-{signature}
        # tier_code: STD=standard, PRO=professional
        parts = license_key.upper().split('-')
        if len(parts) != 4 or parts[0] != 'SF':
            return {'valid': False, 'error': '格式错误，正确格式: SF-XXX-XXXX-XXXX'}
        
        _, tier_code, random_part, signature = parts
        
        # 简码映射
        CODE_TO_TIER = {'STD': 'standard', 'PRO': 'professional'}
        if tier_code not in CODE_TO_TIER:
            return {'valid': False, 'error': '无效的版本类型'}
        
        tier = CODE_TO_TIER[tier_code]
        
        # 验证签名（签名时用 tier 全名 + random）
        expected_sig = _sign_key(f"{tier}-{random_part}")
        if not hmac.compare_digest(signature, expected_sig.upper()):
            return {'valid': False, 'error': '签名验证失败，Key 无效'}
        
        return {
            'valid': True,
            'tier': tier,
            'info': TIER_FEATURES[tier]
        }
    except Exception as e:
        return {'valid': False, 'error': str(e)}

def _get_current_license() -> dict:
    """获取当前激活的 License 信息"""
    saved = load_json(LICENSE_FILE, {})
    if not saved.get('key'):
        return {'tier': 'free', 'info': TIER_FEATURES['free']}
    
    result = _verify_license(saved['key'])
    if result.get('valid'):
        return {'tier': result['tier'], 'info': result['info'], 'key': saved['key']}
    
    # Key 失效，回退到免费版
    return {'tier': 'free', 'info': TIER_FEATURES['free']}

def _get_daily_gen_count() -> int:
    """获取今日生成次数"""
    today = time.strftime('%Y-%m-%d')
    count_file = DATA_DIR / f'gen_count_{today}.json'
    data = load_json(count_file, {'count': 0})
    return data.get('count', 0)

def _increment_daily_gen_count():
    """增加今日生成次数"""
    today = time.strftime('%Y-%m-%d')
    count_file = DATA_DIR / f'gen_count_{today}.json'
    data = load_json(count_file, {'count': 0})
    data['count'] = data.get('count', 0) + 1
    save_json(count_file, data)

# ========== 平台 API Token 追踪 ==========
TOKEN_USAGE_FILE = DATA_DIR / 'platform_tokens.json'

def _get_platform_token_usage():
    return load_json(TOKEN_USAGE_FILE, {})

def _get_license_token_id():
    saved = load_json(LICENSE_FILE, {})
    key = saved.get('key', 'free')
    return hashlib.sha256(key.encode()).hexdigest()[:16]

def _get_remaining_platform_tokens():
    lic = _get_current_license()
    total = lic['info'].get('platform_api_tokens', 0)
    if total == 0:
        return 0
    usage = _get_platform_token_usage()
    lid = _get_license_token_id()
    used = usage.get(lid, 0)
    return max(0, total - used)

def _consume_platform_tokens(n):
    usage = _get_platform_token_usage()
    lid = _get_license_token_id()
    usage[lid] = usage.get(lid, 0) + n
    save_json(TOKEN_USAGE_FILE, usage)

def load_json(path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except:
            return default
    return default

def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

# ========== License API ==========
@app.route('/api/license', methods=['GET'])
def get_license():
    """获取当前 License 状态"""
    lic = _get_current_license()
    daily_count = _get_daily_gen_count()
    lic['daily_generations'] = daily_count
    return jsonify(lic)

@app.route('/api/license/activate', methods=['POST'])
def activate_license():
    """激活 License Key"""
    data = request.json or {}
    key = data.get('key', '').strip().upper()
    
    if not key:
        return jsonify({'ok': False, 'error': '请输入 License Key'}), 400
    
    result = _verify_license(key)
    if not result.get('valid'):
        return jsonify({'ok': False, 'error': result.get('error', '无效的 Key')}), 400
    
    # 保存
    save_json(LICENSE_FILE, {'key': key, 'activated_at': time.time(), 'tier': result['tier']})
    
    return jsonify({
        'ok': True, 
        'tier': result['tier'], 
        'info': result['info'],
        'message': f"🎉 已激活 {result['info']['name']}！"
    })

@app.route('/api/license/deactivate', methods=['POST'])
def deactivate_license():
    """取消激活"""
    save_json(LICENSE_FILE, {})
    return jsonify({'ok': True, 'message': '已退回免费版'})

@app.route('/api/license/features', methods=['GET'])
def get_features():
    """获取功能权限列表（前端用来控制 UI 锁）"""
    lic = _get_current_license()
    info = dict(lic['info'])
    if info.get('platform_api_tokens', 0) > 0:
        remaining = _get_remaining_platform_tokens()
        info['platform_tokens_remaining'] = remaining
        info['platform_tokens_total'] = lic['info']['platform_api_tokens']
    return jsonify({
        'tier': lic['tier'],
        'features': info,
    })

# ========== 预设数据 ==========
BUILTIN_PRESETS = {
    "genre": {
        "name": "体裁设定",
        "icon": "📚",
        "color": "#6366f1",
        "presets": [
            {"id": "xianxia", "name": "仙侠修真", "desc": "修仙问道，飞升成仙", "tags": ["修炼", "丹药", "飞剑", "宗门"]},
            {"id": "xuanhuan", "name": "玄幻奇幻", "desc": "异世大陆，斗气与魔法", "tags": ["异能", "灵力", "神兽", "宝物"]},
            {"id": "wuxia", "name": "武侠江湖", "desc": "江湖恩怨，侠义精神", "tags": ["武功", "门派", "镖局", "江湖"]},
            {"id": "都市", "name": "都市异能", "desc": "现代都市中的超能力者", "tags": ["隐藏身份", "双面人生", "系统", "觉醒"]},
            {"id": "scifi", "name": "科幻星际", "desc": "星际征途，科技文明", "tags": ["飞船", "AI", "星际战争", "外星文明"]},
            {"id": "romance", "name": "言情爱情", "desc": "缠绵悱恻，情深义重", "tags": ["虐恋", "甜宠", "豪门", "重生"]},
            {"id": "history", "name": "历史穿越", "desc": "穿越历史，改变命运", "tags": ["穿越", "宫廷", "权谋", "历史"]},
            {"id": "horror", "name": "悬疑惊悚", "desc": "烧脑解谜，恐怖氛围", "tags": ["推理", "悬疑", "恐怖", "诡异"]},
            {"id": "game", "name": "游戏竞技", "desc": "虚拟世界，电竞热血", "tags": ["VR游戏", "网游", "电竞", "系统"]},
            {"id": "apocalypse", "name": "末世求生", "desc": "文明崩塌后的生存法则", "tags": ["丧尸", "变异", "求生", "基地"]},
            {"id": "campus", "name": "青春校园", "desc": "青春岁月，校园故事", "tags": ["学霸", "暗恋", "社团", "高考"]},
            {"id": "rebirth", "pro": True, "name": "重生逆袭", "desc": "重来一次，书写不同人生", "tags": ["重生", "逆袭", "打脸", "复仇"]},
            {"id": "farming", "name": "种田文", "desc": "悠然田园，慢生活", "tags": ["种地", "经营", "美食", "田园"]},
            {"id": "system", "name": "系统流", "desc": "拥有挂机系统，开挂人生", "tags": ["系统", "签到", "奖励", "升级"]},
            {"id": "infinite", "pro": True, "name": "无限流", "desc": "穿梭各类副本，生死考验", "tags": ["副本", "任务", "积分", "队伍"]},
            {"id": "female_lead", "pro": True, "name": "女频甜宠", "desc": "强强联合，宠溺无边", "tags": ["霸总", "甜宠", "腹黑", "婚后"]},
        ]
    },
    "world": {
        "name": "世界观设定",
        "icon": "🌍",
        "color": "#0ea5e9",
        "presets": [
            {"id": "w1", "name": "东方大陆", "desc": "以东方文化为基底，有修炼体系、宗门制度，大陆分为若干国家，灵气充沛", "tags": ["修炼", "宗门", "灵气", "大陆"]},
            {"id": "w2", "name": "西方魔幻世界", "desc": "中世纪风格，有精灵、矮人、龙族，魔法和剑术并存，有神明体系", "tags": ["魔法", "种族", "神明", "骑士"]},
            {"id": "w3", "name": "未来星际文明", "desc": "公元3000年，人类已经扩张至银河系，存在多个星际帝国和联邦", "tags": ["科技", "星际", "帝国", "联邦"]},
            {"id": "w4", "name": "现代地球", "desc": "与现实相同的当代地球，但暗中存在隐藏的超自然势力或异能者", "tags": ["现代", "隐藏力量", "双层世界", "都市"]},
            {"id": "w5", "name": "末世荒土", "desc": "文明崩塌后第五年，城市成为废墟，变异生物横行，幸存者建立据点", "tags": ["末世", "废土", "幸存", "变异"]},
            {"id": "w6", "name": "架空古代中国", "desc": "仿宋明时期的架空王朝，有宦官、皇权、江湖势力三方角力", "tags": ["架空", "宫廷", "江湖", "权谋"]},
            {"id": "w7", "pro": True, "name": "赛博朋克都市", "desc": "2087年巨型都市，企业统治一切，贫富极度分化，赛博改造人遍布街头", "tags": ["赛博", "企业", "黑客", "改造"]},
            {"id": "w8", "name": "诸天万界", "desc": "有无数位面，修士可以穿越不同世界，每个世界都有独特的法则", "tags": ["位面", "穿越", "法则", "无限"]},
            {"id": "w9", "name": "剑与魔法学院", "desc": "顶级魔法学院，各国天才汇聚，有派系纷争、禁术研究和古老预言", "tags": ["学院", "魔法", "天才", "预言"]},
            {"id": "w10", "pro": True, "name": "海洋世界", "desc": "地表90%是海洋，人类生活在岛屿或水下城市，神秘海域有远古神兽", "tags": ["海洋", "岛屿", "航海", "深海"]},
        ]
    },
    "protagonist": {
        "name": "主角设定",
        "icon": "🦸",
        "color": "#10b981",
        "presets": [
            {"id": "p1", "name": "废材逆袭型", "desc": "起点极低，被人看不起，因机缘觉醒，一步步登顶", "tags": ["废材", "觉醒", "逆袭", "天赋隐藏"]},
            {"id": "p2", "name": "天才少年型", "desc": "出身世家，天赋异禀，但要面对更强的敌人和更复杂的阴谋", "tags": ["天才", "世家", "少年", "压力"]},
            {"id": "p3", "name": "穿越者型", "desc": "从现代穿越，携带现代知识，在异世界凭借见识碾压众人", "tags": ["穿越", "现代知识", "降维打击", "适应"]},
            {"id": "p4", "name": "重生复仇型", "desc": "前世遭受背叛，重生后手握记忆，开始有条不紊的复仇计划", "tags": ["重生", "复仇", "记忆", "计划"]},
            {"id": "p5", "name": "被动卷入型", "desc": "原本普通，因一次意外被卷入更大的漩涡，被迫成长", "tags": ["普通人", "意外", "被迫", "成长"]},
            {"id": "p6", "pro": True, "name": "黑化大佬型", "desc": "表面普通，实则深藏不露，关键时刻展现真正实力，让人叹服", "tags": ["隐藏实力", "黑化", "大佬", "反差"]},
            {"id": "p7", "name": "系统加持型", "desc": "获得神秘系统或金手指，凭借系统指引一步步变强", "tags": ["系统", "金手指", "任务", "奖励"]},
            {"id": "p8", "name": "女强人型", "desc": "独立坚强的女性主角，在男权世界中用实力说话，收获爱情与事业", "tags": ["女强", "独立", "事业", "感情"]},
            {"id": "p9", "pro": True, "name": "腹黑谋士型", "desc": "智慧超群，布局深远，以谋略解决一切问题，却有难言之隐", "tags": ["谋略", "腹黑", "智慧", "秘密"]},
            {"id": "p10", "name": "冷酷杀手型", "desc": "前世是顶级杀手，此生重活，冷漠外表下隐藏着真实情感", "tags": ["杀手", "冷酷", "情感", "强大"]},
        ]
    },
    "outline": {
        "name": "故事大纲",
        "icon": "📋",
        "color": "#f59e0b",
        "presets": [
            {"id": "o1", "name": "英雄成长弧", "desc": "起点→磨难→觉醒→巅峰，标准英雄成长之路，每个阶段都有明确的冲突和成长", "tags": ["成长", "磨难", "觉醒", "巅峰"]},
            {"id": "o2", "name": "三幕式结构", "desc": "建立→对抗→解决，第一幕铺垫世界和人物，第二幕激化矛盾，第三幕大决战", "tags": ["三幕", "冲突", "解决", "经典"]},
            {"id": "o3", "name": "多线并行", "desc": "男女主各有独立故事线，命运交织，若干个关键节点相遇，最终汇聚", "tags": ["多线", "交织", "相遇", "汇聚"]},
            {"id": "o4", "name": "悬疑揭秘式", "desc": "开头抛出大谜团，中途不断给出线索，结局反转揭秘，环环相扣", "tags": ["悬疑", "谜团", "线索", "反转"]},
            {"id": "o5", "name": "打怪升级流", "desc": "主角不断面对更强的敌人，每次战胜都获得新的能力，层层递进", "tags": ["升级", "敌人", "能力", "层次"]},
            {"id": "o6", "name": "复仇计划式", "desc": "开局确立复仇目标，中途布局，最终完成复仇，过程中人性逐渐展现", "tags": ["复仇", "布局", "人性", "目标"]},
            {"id": "o7", "pro": True, "name": "权谋争斗式", "desc": "各方势力明争暗斗，主角在夹缝中生存成长，最终执掌大权", "tags": ["权谋", "势力", "博弈", "执掌"]},
            {"id": "o8", "name": "甜蜜爱情线", "desc": "两人从相遇到相爱，经历误会、分离、重聚，最终修成正果", "tags": ["爱情", "误会", "重聚", "甜蜜"]},
            {"id": "o9", "name": "末世求存式", "desc": "灾难降临，主角带领团队求生，建立根据地，逐渐反攻，重建文明", "tags": ["末世", "团队", "求生", "重建"]},
            {"id": "o10", "pro": True, "name": "全球危机式", "desc": "从个人危机扩展到全球威胁，主角被推上拯救世界的舞台", "tags": ["危机", "扩展", "拯救", "使命"]},
        ]
    },
    "conflict": {
        "name": "核心冲突",
        "icon": "⚔️",
        "color": "#ef4444",
        "presets": [
            {"id": "c1", "name": "强弱对立", "desc": "主角以弱胜强，不断突破自身极限，对抗看似无法超越的强大敌人", "tags": ["以弱胜强", "突破", "极限", "强敌"]},
            {"id": "c2", "name": "善恶博弈", "desc": "正义与邪恶势力的根本对立，主角坚守正道，在黑暗中寻找光明", "tags": ["善恶", "正义", "黑暗", "坚守"]},
            {"id": "c3", "name": "利益纠葛", "desc": "多方势力因利益产生冲突，没有绝对的善恶，只有不同的立场", "tags": ["利益", "立场", "多方", "博弈"]},
            {"id": "c4", "name": "身份秘密", "desc": "主角隐藏真实身份，一旦暴露将面临巨大危险，持续的伪装与真相的撕裂", "tags": ["身份", "隐藏", "暴露", "真相"]},
            {"id": "c5", "pro": True, "name": "命运对抗", "desc": "主角对抗既定命运或预言，证明命运可以被改变", "tags": ["命运", "预言", "反抗", "改变"]},
            {"id": "c6", "name": "内心挣扎", "desc": "主角在道德与欲望、理性与感性之间撕裂，最终完成内心的成长与和解", "tags": ["内心", "道德", "欲望", "和解"]},
            {"id": "c7", "name": "爱恨情仇", "desc": "爱与恨交织，背叛与忠诚共存，情感成为最强大的驱动力", "tags": ["爱恨", "背叛", "忠诚", "情感"]},
            {"id": "c8", "pro": True, "name": "文明冲突", "desc": "不同种族、文明、信仰之间的根本冲突，主角试图化解或利用", "tags": ["文明", "种族", "信仰", "冲突"]},
        ]
    },
    "style": {
        "name": "写作风格",
        "icon": "✍️",
        "color": "#8b5cf6",
        "presets": [
            {"id": "s1", "name": "爽文流畅", "desc": "节奏快，爽点密集，少废话，打脸情节多，读者代入感强，适合网文", "tags": ["爽文", "快节奏", "爽点", "打脸"]},
            {"id": "s2", "name": "细腻文学", "desc": "注重心理描写和环境描写，情感细腻，文字优美，适合严肃文学", "tags": ["细腻", "心理", "文学", "优美"]},
            {"id": "s3", "name": "幽默诙谐", "desc": "语言轻松幽默，多用梗和反差萌，读来轻松愉快，不沉重", "tags": ["幽默", "轻松", "反差", "梗"]},
            {"id": "s4", "name": "热血燃情", "desc": "战斗场面描写激烈，充满热血情怀，人物说话铿锵有力，燃起来", "tags": ["热血", "燃", "激烈", "豪情"]},
            {"id": "s5", "pro": True, "name": "悬疑烧脑", "desc": "信息量大，前后伏笔呼应，逻辑严密，读者需要认真思考", "tags": ["悬疑", "伏笔", "逻辑", "烧脑"]},
            {"id": "s6", "name": "温情治愈", "desc": "暖心故事，人性美好，注重人情味和生活细节，治愈系", "tags": ["温情", "治愈", "暖心", "细节"]},
            {"id": "s7", "pro": True, "name": "黑暗沉重", "desc": "世界观黑暗，人性阴暗面展露，主角经历苦难，充满宿命感", "tags": ["黑暗", "苦难", "宿命", "沉重"]},
            {"id": "s8", "pro": True, "name": "甜蜜宠溺", "desc": "甜甜的恋爱描写，大量宠溺情节，糖分超标，适合放松阅读", "tags": ["甜蜜", "宠溺", "糖分", "恋爱"]},
        ]
    },
    "chapter": {
        "name": "章节规划",
        "icon": "📖",
        "color": "#06b6d4",
        "presets": [
            {"id": "ch1", "name": "短篇（5-10章）", "desc": "精炼故事，每章2000-3000字，结构紧凑，适合完整短篇故事", "tags": ["短篇", "精炼", "紧凑"]},
            {"id": "ch2", "name": "中篇（20-50章）", "desc": "中等体量，每章3000-4000字，有完整的起承转合", "tags": ["中篇", "完整", "结构"]},
            {"id": "ch3", "name": "长篇（100+章）", "desc": "大体量网文，每章2000-3000字，多线发展，层层递进", "tags": ["长篇", "网文", "多线"]},
            {"id": "ch4", "name": "卷轴式（按卷划分）", "desc": "分为多个卷，每卷10-20章，每卷有独立小高潮，整体构成大故事", "tags": ["分卷", "高潮", "结构"]},
            {"id": "ch5", "name": "番外式", "desc": "主线+番外形式，番外补充细节和感情线，丰富世界观", "tags": ["番外", "补充", "感情线"]},
        ]
    },
    "pov": {
        "name": "叙事视角",
        "icon": "👁️",
        "color": "#f97316",
        "presets": [
            {"id": "pov1", "name": "第一人称主角视角", "desc": "以主角的「我」叙述，代入感最强，读者直接感受主角内心世界", "tags": ["第一人称", "代入", "内心"]},
            {"id": "pov2", "name": "第三人称有限视角", "desc": "「他/她」叙述，但仅限主角视角，既有客观叙述又有内心描写", "tags": ["第三人称", "有限", "平衡"]},
            {"id": "pov3", "name": "第三人称全知视角", "desc": "上帝视角，可以描述所有角色的内心和行动，适合多线叙事", "tags": ["全知", "上帝视角", "多线"]},
            {"id": "pov4", "name": "多视角切换", "desc": "按章节切换不同角色视角，让读者看到不同角色眼中的同一世界", "tags": ["多视角", "切换", "对比"]},
        ]
    },
    "setting_detail": {
        "name": "细节设定",
        "icon": "⚙️",
        "color": "#84cc16",
        "presets": [
            {"id": "sd1", "name": "等级体系", "desc": "建立清晰的实力等级体系，如：凡人→炼气→筑基→金丹→元婴→化神→合体→大乘", "tags": ["等级", "晋升", "体系"]},
            {"id": "sd2", "name": "势力格局", "desc": "划定世界中的主要势力，如：四大宗门、三国鼎立、七大家族等，势力间有明确的关系", "tags": ["势力", "格局", "关系"]},
            {"id": "sd3", "name": "特殊道具/神器", "desc": "设定推动情节的关键道具，如：上古神兵、天命令牌、神级功法等", "tags": ["神器", "道具", "功法"]},
            {"id": "sd4", "name": "配角关系网", "desc": "设计主角身边的重要配角：老师、伙伴、对手、恋人，及各自的弧光", "tags": ["配角", "关系", "弧光"]},
            {"id": "sd5", "name": "核心伏笔", "desc": "提前设置将在中后期揭示的重要伏笔，让故事有深度", "tags": ["伏笔", "悬念", "揭示"]},
            {"id": "sd6", "name": "独特设定", "desc": "建立这个世界独有的规则或设定，与众不同，让读者觉得新鲜", "tags": ["独特", "规则", "新鲜"]},
        ]
    },
    "characters": {
        "name": "角色设定",
        "icon": "🎭",
        "color": "#ec4899",
        "presets": [
            {"id": "cr1", "name": "导师/师傅型", "desc": "主角的引路人，拥有深厚的学识或实力，关键时刻给予指导和帮助，但有自己的秘密和局限性", "tags": ["导师", "秘密", "实力", "引路"]},
            {"id": "cr2", "name": "挚友/搭档型", "desc": "主角最信任的伙伴，性格互补，生死与共，为主角提供情感支撑和实际帮助", "tags": ["挚友", "互补", "信任", "并肩"]},
            {"id": "cr3", "name": "宿敌/反派型", "desc": "与主角势均力敌的对手，有自己的信念和动机，不单纯是恶的化身，推动主角不断突破", "tags": ["宿敌", "信念", "推动", "势均"]},
            {"id": "cr4", "name": "恋人/感情线型", "desc": "故事的感情核心，与主角产生深刻情感联结，其存在让主角的人性更加丰满", "tags": ["恋人", "情感", "羁绊", "柔软"]},
            {"id": "cr5", "name": "搞笑担当型", "desc": "活跃气氛的角色，在紧张情节中提供喘息空间，有时候会有意想不到的重要作用", "tags": ["搞笑", "调节", "反差", "意外"]},
            {"id": "cr6", "name": "神秘人/幕后型", "desc": "身份成谜，偶尔出现给予暗示或帮助，真实身份和目的在后期才揭晓", "tags": ["神秘", "幕后", "暗示", "揭晓"]},
            {"id": "cr7", "name": "团队伙伴型", "desc": "与主角同行的团队成员，各有所长，共同成长，体现团队合作和友谊", "tags": ["团队", "成长", "合作", "多元"]},
            {"id": "cr8", "name": "引路NPC型", "desc": "在特定场景出现的关键路人，提供重要信息或道具后可能不再出现，但影响深远", "tags": ["路人", "关键", "信息", "道具"]},
        ]
    },
    "romance": {
        "name": "情感关系",
        "icon": "💕",
        "color": "#ec4899",
        "_pro_only": True,
        "presets": [
            {"id": "bl1", "name": "男男之恋 (BL)", "desc": "两个男性之间的深刻情感故事，从相遇、试探到相爱，面对世俗与自我的双重考验", "tags": ["BL", "男男", "羁绊", "试探"]},
            {"id": "gl1", "name": "女女之恋 (GL)", "desc": "两位女性之间的细腻情感，柔情与坚定并存，突破社会期待寻找真实自我", "tags": ["GL", "女女", "细腻", "真实"]},
            {"id": "agediff1", "name": "姐弟恋", "desc": "年上女性与年下男性，成熟与活力的碰撞，年龄差带来的独特张力与理解", "tags": ["姐弟", "年龄差", "成熟", "活力"]},
            {"id": "agediff2", "name": "大叔萝莉", "desc": "年长男性与年轻女性，沧桑阅历与纯真活力的反差，温柔守护型感情", "tags": ["大叔", "萝莉", "守护", "反差"]},
            {"id": "office1", "name": "办公室恋情", "desc": "职场中悄然滋生的感情，克制与冲动之间，要面对职场规则和个人情感的平衡", "tags": ["职场", "克制", "暧昧", "规则"]},
            {"id": "campus1", "name": "校园暗恋", "desc": "青涩的校园时光，暗藏心底的悸动，从同桌到恋人，最纯粹的感情起点", "tags": ["校园", "暗恋", "青涩", "同桌"]},
            {"id": "forbidden1", "name": "禁忌之恋", "desc": "违背常规伦理的感情，明知不可为而为之，每一步都在道德的悬崖边行走", "tags": ["禁忌", "道德", "挣扎", "背德"]},
            {"id": "rebirth_love", "name": "重生追爱", "desc": "带着前世记忆重新开始，这一次要抓住错过的爱人，弥补所有遗憾", "tags": ["重生", "追爱", "弥补", "前世"]},
            {"id": "enemy_love", "name": "相爱相杀", "desc": "立场对立却深深吸引，在互相伤害中产生无法割舍的羁绊", "tags": ["宿敌", "对立", "羁绊", "纠缠"]},
            {"id": "heal_love", "name": "治愈系恋爱", "desc": "受过伤的灵魂相遇，互相疗愈，温柔而坚定地修复彼此的创口", "tags": ["治愈", "温柔", "修复", "疗伤"]},
            {"id": "bl_deep", "name": "男男之恋·深柜觉醒", "desc": "从未察觉自己的取向，直到遇见他。挣扎、否认、接受、勇敢", "tags": ["BL", "觉醒", "挣扎", "勇气"]},
            {"id": "bl_rival", "name": "男男之恋·强强对抗", "desc": "两个强势男性，从竞争对手到相爱相知", "tags": ["BL", "强强", "征服", "平等"]},
            {"id": "gl_slow", "name": "女女之恋·慢热升温", "desc": "从朋友到知己再到恋人，感情在日常相处中悄然生长", "tags": ["GL", "慢热", "细腻", "日常"]},
            {"id": "gl_brave", "name": "女女之恋·勇敢出柜", "desc": "面对家庭和社会压力下定决心公开关系", "tags": ["GL", "出柜", "勇气", "家人"]},
            {"id": "age_younger", "name": "年龄差·年下攻略", "desc": "年轻一方的主动追求，用热忱和纯真打破年龄壁垒", "tags": ["年下", "主动", "热忱", "纯真"]},
            {"id": "age_older", "name": "年龄差·大叔宠爱", "desc": "年长男性的温柔守护，用阅历和成熟包容对方", "tags": ["大叔", "守护", "成熟", "包容"]},
            {"id": "forb_office", "name": "禁忌之恋·办公室", "desc": "职场中的禁忌关系，每一次对视都是心动的冒险", "tags": ["职场", "地下", "刺激", "危险"]},
            {"id": "forb_enemy", "name": "禁忌之恋·宿敌相恋", "desc": "互相厮杀的敌人，在交锋中产生致命吸引力", "tags": ["宿敌", "致命", "背叛", "纠缠"]},
        ]
    }
}

# ========== 项目管理 ==========
@app.route('/api/projects', methods=['GET'])
def get_projects():
    projects = load_json(PROJECTS_FILE, [])
    return jsonify(projects)

@app.route('/api/projects', methods=['POST'])
def create_project():
    data = request.json

    # 检查 max_flows 限制
    lic = _get_current_license()
    max_flows = lic['info'].get('max_flows', 1)
    projects = load_json(PROJECTS_FILE, [])
    if len(projects) >= max_flows:
        return jsonify({
            'error': f'{"免费版" if lic["tier"] == "free" else "当前版本"}最多创建 {max_flows} 个项目，请删除旧项目或升级',
            'tier': lic['tier'],
            'max_flows': max_flows
        }), 403
    project = {
        'id': str(uuid.uuid4()),
        'name': data.get('name', '新小说项目'),
        'created': time.time(),
        'updated': time.time(),
        'nodes': data.get('nodes', []),
        'edges': data.get('edges', []),
        'settings': data.get('settings', {}),
        'output': data.get('output', '')
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
import time as _time

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
        'created': _time.time(),
        'nodes': data.get('nodes', []),
        'edges': data.get('edges', [])
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

# ========== 模型配置 ==========
@app.route('/api/models/test', methods=['POST'])
def test_model():
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

# ========== AI 调用核心 ==========
def call_llm(config, messages, stream=False):
    """统一调用不同模型，支持完整推理参数，返回生成的文本内容"""
    model_type = config.get('type', 'ollama')
    
    # 通用推理参数
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
            'model': model,
            'messages': messages,
            'stream': False,
            'options': {
                'temperature': temperature,
                'top_p': top_p,
                'repeat_penalty': repeat_penalty,
                'num_predict': max_tokens,
                'num_ctx': num_ctx,
                'frequency_penalty': frequency_penalty,
                'presence_penalty': presence_penalty,
            }
        }
        resp = requests.post(f'{base_url}/api/chat',
            json=payload, timeout=180)
        resp_json = resp.json()
        if 'error' in resp_json:
            raise ValueError(f"Ollama 错误: {resp_json['error']}")
        content = resp_json['message']['content']
        return content
    
    elif model_type == 'lmstudio':
        base_url = config.get('base_url', 'http://localhost:11435')
        model = config.get('model', '')
        headers = {'Content-Type': 'application/json'}
        payload = {
            'model': model,
            'messages': messages,
            'max_tokens': max_tokens,
            'temperature': temperature,
            'top_p': top_p,
            'repeat_penalty': repeat_penalty,
            'frequency_penalty': frequency_penalty,
            'presence_penalty': presence_penalty,
        }
        resp = requests.post(f'{base_url}/v1/chat/completions',
            headers=headers, json=payload, timeout=180)
        resp_json = resp.json()
        if 'error' in resp_json:
            err = resp_json['error']
            raise ValueError(f"LM Studio 错误: {err.get('message', err)}")
        content = resp_json['choices'][0]['message']['content']
        return content
    
    elif model_type in ['openai', 'deepseek', 'tongyi', 'custom']:
        api_key = config.get('api_key', '')
        base_url = config.get('base_url', 'https://api.openai.com/v1')
        model = config.get('model', 'gpt-3.5-turbo')
        print(f'[DEBUG] call_llm: type={model_type}, model={model}, key={api_key[:10] if api_key else "EMPTY"}..., url={base_url}', flush=True)
        headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
        payload = {
            'model': model,
            'messages': messages,
            'max_tokens': max_tokens,
            'temperature': temperature,
            'top_p': top_p,
            'frequency_penalty': frequency_penalty,
            'presence_penalty': presence_penalty,
        }
        resp = requests.post(f'{base_url}/chat/completions',
            headers=headers, json=payload, timeout=180)
        resp_json = resp.json()
        if 'error' in resp_json:
            err = resp_json['error']
            raise ValueError(f"API 错误 [{resp.status_code}]: {err.get('message', err)}")
        if 'choices' not in resp_json:
            raise ValueError(f"API 返回异常 [{resp.status_code}]: {resp.text[:200]}")
        content = resp_json['choices'][0]['message']['content']
        return content

    raise ValueError(f'Unknown model type: {model_type}')

# ========== AI 生成选项 ==========
@app.route('/api/ai/generate-options', methods=['POST'])
def generate_options():
    data = request.json
    node_type = data.get('node_type', '')
    context = data.get('context', {})
    mc = data.get('model_config', {})
    count = data.get('count', 4)

    # License 检查
    lic = _get_current_license()
    
    # Pro 专属模板检查
    PRO_ONLY_TYPES = {'romance', 'custom'}
    if node_type in PRO_ONLY_TYPES and lic['tier'] != 'professional':
        return jsonify({
            'ok': False,
            'error': '此模板仅专业版可用，请升级',
            'tier': lic['tier']
        }), 403
    
    max_templates = lic['info'].get('max_template_calls', 3)
    today = time.strftime('%Y-%m-%d')
    tc_file = DATA_DIR / f'template_count_{today}.json'
    tc_data = load_json(tc_file, {'count': 0})
    if tc_data['count'] >= max_templates:
        return jsonify({
            'ok': False,
            'error': f'{"免费版" if lic["tier"]=="free" else "当前版本"}每日模板生成为 {max_templates} 次，今日已用完',
            'tier': lic['tier']
        }), 403

    # 平台 API 注入
    use_platform = data.get('use_platform_api', False)
    if use_platform:
        if lic['tier'] == 'free':
            return jsonify({'ok': False, 'error': '平台 API 仅支持付费版本'}), 403
        remaining = _get_remaining_platform_tokens()
        if remaining <= 0:
            return jsonify({'ok': False, 'error': '平台 API Token 已用完'}), 403
        mc = {
            'type': 'deepseek',
            'api_key': PLATFORM_API_KEY,
            'base_url': 'https://api.deepseek.com/v1',
            'model': PLATFORM_API_MODEL,
        }
    
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

        # 平台 API Token 消耗
        if use_platform:
            _consume_platform_tokens(max(len(result), len(result)//3))

        # 记录模板调用次数
        tc_data['count'] += 1
        save_json(tc_file, tc_data)
        
        # 提取JSON
        json_match = _re.search(r'\[.*\]', result, _re.DOTALL)
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

# ========== AI 写作辅助函数 ==========
import re as _re

def _is_sentence_complete(text):
    """检测文本是否以完整句子结尾（防止小模型 token 限制导致半截输出）"""
    if not text or len(text) < 50:
        return False
    # 取最后 20 个非空白字符判断
    tail = text.strip()[-50:]
    # 完整句子结束符
    complete_endings = ['。', '！', '？', '!', '?', '.', '"', '」', '…', '——', '~']
    for ending in complete_endings:
        if tail.rstrip().endswith(ending):
            return True
    # 检查是否以换行+标题结尾（常见的小说章节结束模式）
    if _re.search(r'[\n\r]{2,}', tail[-10:]):
        return True
    return False

def _extract_chapter_summary(text, max_len=300):
    """从生成的章节中提取简短摘要"""
    lines = text.strip().split('\n')
    # 取前几段作为摘要骨架
    summary_lines = []
    char_count = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # 跳过大标题
        if line.startswith('#') or len(line) < 5:
            if not line.startswith('#'):
                continue
        summary_lines.append(line)
        char_count += len(line)
        if char_count > max_len:
            break
    return ' '.join(summary_lines)[:max_len]

def _auto_continue(model_config, messages, initial_result, max_retries=2):
    """自动续写：如果输出不完整，追加续写调用"""
    result = initial_result
    for attempt in range(max_retries):
        if _is_sentence_complete(result):
            break
        # 构建续写 prompt：带上最后一段上下文
        last_part = result[-500:]
        continue_msg = {
            'role': 'user',
            'content': f'上文在这里中断了：\n"""\n{last_part}\n"""\n\n请从断点处精确继续，不要重复上文已有的内容，直接续写后续段落。只输出续写内容，不要加任何前缀说明。'
        }
        try:
            continuation = call_llm(model_config, messages + [continue_msg])
            result += continuation
        except Exception:
            break  # 续写失败不阻塞主流程
    return result

# ========== 去AI味机制 ==========

# 1. 反AI味系统提示词
ANTI_AI_PROMPT = """⛔ 去AI味写作铁律（必须严格遵守）：

【禁用黑名单】以下词汇/句式一律禁止使用，哪怕你觉得用着顺手：
- 虚词堆叠：然而、不禁、宛如、仿佛、竟、却、隐隐、缓缓、微微、淡淡、轻轻、默默、静静、柔柔、悠悠、悄然、陡然、蓦然、陡地、忽地、蓦地
- 套话模板："这是一个..."、"那是一个..."、"在这个...中"、"他的眼中闪过一丝..."、"嘴角微微上扬"、"心中一动"、"不由得"、"不由自主"
- 形容词叠堆：不要连续使用两个以上的形容词修饰同一个名词
- 万能比喻：禁止用"如...一般"、"像...似的"超过1次/千字

【必须遵守】
1. 用具体感官细节代替抽象形容（写"他攥紧拳头，指甲掐进掌心"而非"他感到愤怒"）
2. 句式长短交替：短句3-8字用于节奏和动作，长句15-30字用于描写和叙述，禁止连续3句同长度
3. 人物对话要有口语感，每个人物有独特的说话习惯和口头禅，不用书面腔
4. 禁止每段开头用"XX的"、"在XX中"的固定模式，每段开头要有变化
5. 比喻和排比有节制：每千字不超过1个比喻，禁止连续排比超过3句
6. 叙事视角一致，不随意切换；用人物行动展现心理，少用"他感到/觉得/想"
7. 留白和省略：不要事无巨细全写出来，适当跳过过渡环节
8. 环境描写要融入人物行动中，不要独立成段纯写景
9. 时间推进要有节奏感，不能每段都是同样的时间尺度"""

# 不同写作风格的额外规则
STYLE_RULES = {
    'literary': """【文学写实模式】
- 克制、精准，每个词都有存在的必要
- 多用白描手法，少用修辞
- 细节要具体到品牌、型号、颜色、气味
- 对话简短有力，不说废话
- 善用省略号和破折号表示语流中断""",
    
    'colloquial': """【口语化模式】
- 叙述语言接近日常口语，可以略带方言感
- 允许使用口语化的语气词（嘛、呗、哎、哈）
- 句子结构简单直接，少用从句和长定语
- 对话要有大量语气词、省略、打断、重复等真实对话特征
- 用词要接地气，"他溜达"比"他缓步而行"好""",
    
    'hardcore': """【硬核简洁模式】
- 极简叙事，能用5个字说完的不用10个字
- 短句为主，平均句长不超过12字
- 砍掉所有不必要的形容词和副词
- 动词优先：用动作推进，不用心理描写
- 对话只写关键信息，寒暄和客套一律省略
- 场景转换要快，不要铺垫过渡""",
    
    'poetic': """【诗意浪漫模式】
- 可以使用更多修辞，但要有节制，每千字不超过2个比喻
- 修辞要有独创性，禁止用烂俗比喻（如"像花一样"、"如水般"）
- 注重韵律和节奏感，段落结尾的句子要有余韵
- 意象要连贯，同一场景的意象要有内在联系
- 情感要含蓄，通过意象暗示而非直白表达""",
}

# 2. 后处理：AI味清洗
# AI高频套话替换映射表
_AI_FILLER_MAP = {
    # 虚词替换
    '然而': '', '不禁': '', '宛如': '像', '仿佛': '像',
    '陡然': '突然', '蓦然': '突然', '陡地': '突然', '忽地': '突然', '蓦地': '突然',
    '悄然': '悄悄', '隐隐': '', '缓缓': '慢', '微微': '略',
    '淡淡地': '', '轻轻地': '', '默默地': '', '静静地': '',
    '柔柔地': '', '悠悠地': '',
    # 套话替换
    '嘴角微微上扬': '笑了笑', '嘴角上扬': '笑了',
    '心中一动': '', '不由得': '', '不由自主': '',
    '他的眼中闪过一丝': '他眼里', '她眼中闪过一丝': '她眼里',
    '一股XX的力量': '', '一股强大的力量': '',
    '仿佛整个世界都': '', '宛如置身于': '',
}

def _post_process_text(text, style='literary'):
    """后处理：清洗AI味，让文本更自然"""
    if not text:
        return text
    
    result = text
    
    # Phase 1: 替换AI高频套话
    for ai_phrase, replacement in _AI_FILLER_MAP.items():
        result = result.replace(ai_phrase, replacement)
    
    # Phase 2: 压缩连续重复的形容词模式（如"美丽的温柔的善良的"）
    result = _re.sub(r'([\u4e00-\u9fff]{2,4}的){3,}', lambda m: m.group(0)[:m.group(0).index('的', m.group(0).index('的') + 1) + 1], result)
    
    # Phase 3: 去除"他/她感到/觉得/想"的过度使用（连续出现3次以上时替换部分）
    feel_pattern = _re.compile(r'(他|她|它)(感到|觉得|心想)')
    feel_matches = list(feel_pattern.finditer(result))
    if len(feel_matches) >= 3:
        # 保留第1个和最后1个，中间的替换为行动描写提示
        for i, match in enumerate(feel_matches[1:-1], 1):
            # 只替换奇数位的，偶数位的保留
            if i % 2 == 1:
                result = result[:match.start()] + match.group(1) + '的动作暗示了这一点' + result[match.end():]
    
    # Phase 4: 口语化风格更激进地替换书面词
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
        }
        for formal, casual in colloquial_map.items():
            result = result.replace(formal, casual)
    
    # Phase 5: 清理替换后可能产生的多余空格和标点
    result = _re.sub(r'  +', ' ', result)  # 多余空格
    result = _re.sub(r'，，', '，', result)  # 连续逗号
    result = _re.sub(r'。。', '。', result)  # 连续句号
    
    return result

# ========== AI 写作执行 ==========
writing_tasks = {}

@app.route('/api/ai/write', methods=['POST'])
def start_writing():
    data = request.json or {}
    model_config = data.get('model_config', {})

    lic = _get_current_license()
    writing_style = data.get('writing_style', 'literary')

    # 写作风格权限检查
    allowed_styles = lic['info'].get('writing_styles', ['literary'])
    if writing_style not in allowed_styles:
        return jsonify({
            'error': f'当前版本不支持「{writing_style}」风格，请升级',
            'tier': lic['tier'],
            'allowed': allowed_styles
        }), 403

    # 平台 API 模式检查
    use_platform_api = data.get('use_platform_api', False)
    if use_platform_api:
        if lic['tier'] == 'free':
            return jsonify({
                'error': '平台 API 仅支持付费版本使用，请先升级',
                'tier': 'free'
            }), 403
        remaining = _get_remaining_platform_tokens()
        if remaining <= 0:
            return jsonify({
                'error': '平台 API Token 已用完，请使用自己的 Key 或升级',
                'tier': lic['tier']
            }), 403
        model_config = {
            'type': 'deepseek',
            'api_key': PLATFORM_API_KEY,
            'base_url': 'https://api.deepseek.com/v1',
            'model': PLATFORM_API_MODEL,
        }

    # 免费版每日生成次数检查
    daily_count = _get_daily_gen_count()
    max_gen = lic['info'].get('max_daily_generations', 3)
    if daily_count >= max_gen:
        return jsonify({
            'error': f'{"免费版" if lic["tier"] == "free" else "当前版本"}每日限{max_gen}次生成，今日已用完。',
            'tier': lic['tier'],
            'daily_count': daily_count,
            'max_daily': max_gen
        }), 403

    task_id = str(uuid.uuid4())

    writing_tasks[task_id] = {
        'status': 'pending',
        'progress': 0,
        'output': '',
        'error': None,
        'chapter_summaries': [],
    }

    def do_write():
        try:
            writing_tasks[task_id]['status'] = 'running'
            flow_config = data.get('flow', {})

            # 构建写作提示词
            genre = flow_config.get('genre', {}).get('selected', {})
            world = flow_config.get('world', {}).get('selected', {})
            protagonist = flow_config.get('protagonist', {}).get('selected', {})
            outline = flow_config.get('outline', {}).get('selected', {})
            conflict = flow_config.get('conflict', {}).get('selected', {})
            style = flow_config.get('style', {}).get('selected', {})
            chapter = flow_config.get('chapter', {}).get('selected', {})
            pov = flow_config.get('pov', {}).get('selected', {})
            setting_detail = flow_config.get('setting_detail', {}).get('selected', {})
            custom_notes = flow_config.get('custom_notes', '')

            writing_style = data.get('writing_style', 'literary')
            style_rules = STYLE_RULES.get(writing_style, STYLE_RULES['literary'])

            # 根据 anti_ai_level 决定去AI味强度
            anti_ai_level = lic['info']['anti_ai_level']
            if anti_ai_level == 'basic':
                anti_ai_text = """【去AI味要求（基础模式）】
- 避免使用最常见的AI套话（然而、不禁、宛如、仿佛）
- 保持文字自然，不要过度修饰
- 允许适量形容词，不要把每个句子都写得很华丽"""
            elif anti_ai_level == 'full':
                anti_ai_text = ANTI_AI_PROMPT
            elif anti_ai_level == 'custom':
                anti_ai_text = ANTI_AI_PROMPT + """

【自定义增强模式】
- 你可以根据用户提供的额外去AI味规则进行动态调整
- 对输出的文字进行多轮自检，确保达到出版级自然度"""

            system_prompt = f"""你是一位专业的小说作者，擅长各种题材的创作。
请根据用户提供的设定，创作出引人入胜的小说内容。

{anti_ai_text}

{style_rules}

核心要求：
1. 人物鲜活，对话自然有个性
2. 情节紧凑，有节奏感，每个场景都有推进
3. 充分展现世界观的独特性
4. 确保输出完整，不要中途截断
5. 绝不要写出"AI味"的文字——避免套话、虚词堆叠、形容词泛滥"""

            user_prompt = f"""请根据以下设定创作小说：

【体裁】{genre.get('name', '')}：{genre.get('desc', '')}
【世界观】{world.get('name', '')}：{world.get('desc', '')}
【主角】{protagonist.get('name', '')}：{protagonist.get('desc', '')}
【故事大纲】{outline.get('name', '')}：{outline.get('desc', '')}
【核心冲突】{conflict.get('name', '')}：{conflict.get('desc', '')}
【写作风格】{style.get('name', '')}：{style.get('desc', '')}
【章节规划】{chapter.get('name', '')}：{chapter.get('desc', '')}
【叙事视角】{pov.get('name', '')}：{pov.get('desc', '')}
【细节设定】{setting_detail.get('name', '')}：{setting_detail.get('desc', '')}
【补充说明】{custom_notes}

请先写出：
1. 小说标题（3个备选）
2. 内容简介（200字）
3. 完整章节内容（至少2000字，以「第一章」为章节标题）

按照以上格式输出。确保内容完整，不要写到一半中断。"""

            writing_tasks[task_id]['progress'] = 20

            messages = [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt}
            ]

            result = call_llm(model_config, messages)
            writing_tasks[task_id]['progress'] = 60

            # 自动续写：检测是否因 token 限制导致半截输出
            result = _auto_continue(model_config, messages, result)

            # 去AI味后处理
            result = _post_process_text(result, writing_style)

            writing_tasks[task_id]['output'] = result
            summary = _extract_chapter_summary(result)
            if summary:
                writing_tasks[task_id]['chapter_summaries'].append(summary)
            writing_tasks[task_id]['progress'] = 100
            if use_platform_api:
                output_len = len(result)
                est_tokens = max(output_len, output_len // 3)
                _consume_platform_tokens(est_tokens)

            writing_tasks[task_id]['status'] = 'done'

            # 增加今日生成计数
            _increment_daily_gen_count()

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
    
    # 继承原任务的章节摘要
    prev_summaries = []
    if task_id in writing_tasks:
        prev_summaries = writing_tasks[task_id].get('chapter_summaries', [])
    
    writing_tasks[task_id_new] = {
        'status': 'pending',
        'progress': 0,
        'output': '',
        'error': None,
        'chapter_summaries': list(prev_summaries),
    }
    
    def do_continue():
        try:
            # 平台 API 模式检查
            nonlocal_model_config = model_config
            _use_platform_api = data.get('use_platform_api', False)
            if _use_platform_api:
                lic_pre = _get_current_license()
                if lic_pre['tier'] == 'free':
                    writing_tasks[task_id_new]['status'] = 'error'
                    writing_tasks[task_id_new]['error'] = '平台 API 仅支持付费版本使用，请先升级'
                    return
                remaining = _get_remaining_platform_tokens()
                if remaining <= 0:
                    writing_tasks[task_id_new]['status'] = 'error'
                    writing_tasks[task_id_new]['error'] = '平台 API Token 已用完，请使用自己的 Key 或升级'
                    return
                nonlocal_model_config = {
                    'type': 'deepseek',
                    'api_key': PLATFORM_API_KEY,
                    'base_url': 'https://api.deepseek.com/v1',
                    'model': PLATFORM_API_MODEL,
                }

            # 写作风格权限检查
            lic_cont = _get_current_license()
            writing_style = data.get('writing_style', 'literary')
            allowed_styles = lic_cont['info'].get('writing_styles', ['literary'])
            if writing_style not in allowed_styles:
                writing_tasks[task_id_new]['status'] = 'error'
                writing_tasks[task_id_new]['error'] = f'当前版本不支持「{writing_style}」风格，请升级'
                return

            writing_tasks[task_id_new]['status'] = 'running'
            prev_content = data.get('prev_content', '')
            next_chapter_num = len(prev_summaries) + 1
            # 中文数字映射
            CN_NUMS = ['零','一','二','三','四','五','六','七','八','九','十',
                       '十一','十二','十三','十四','十五','十六','十七','十八','十九','二十']
            cn_num = CN_NUMS[next_chapter_num] if next_chapter_num < len(CN_NUMS) else str(next_chapter_num)
            
            instruction = data.get('instruction', '请继续写下一章')
            instruction = f"⚠️ CRITICAL: 你的输出必须以「第{cn_num}章」作为章节标题开头，使用中文数字格式。绝对不能写其他章节号。\n\n{instruction}"
            print(f'[DEBUG] continue: chapter={next_chapter_num}({cn_num}), summaries={len(prev_summaries)}', flush=True)
            style_rules = STYLE_RULES.get(writing_style, STYLE_RULES['literary'])

            # 根据 anti_ai_level 决定去AI味强度
            anti_ai_level = lic_cont['info']['anti_ai_level']
            if anti_ai_level == 'basic':
                anti_ai_text = """【去AI味要求（基础模式）】
- 避免使用最常见的AI套话
- 保持文字自然，不要过度修饰"""
            elif anti_ai_level == 'full':
                anti_ai_text = ANTI_AI_PROMPT
            elif anti_ai_level == 'custom':
                anti_ai_text = ANTI_AI_PROMPT + "\n\n【自定义增强模式】对输出进行多轮自检，确保出版级自然度"
            
            writing_tasks[task_id_new]['progress'] = 10
            
            # 用章节摘要替代原始全文上下文，大幅减少重复风险
            summary_text = ''
            for i, s in enumerate(prev_summaries):
                summary_text += f'第{i+1}章摘要：{s}\n'
            if not summary_text:
                summary_text = prev_content[-500:]  # 降级：取最后500字
            
            # 取上一章最后一段作为衔接
            last_paragraph = prev_content.strip()[-300:]
            
            anti_repeat_rules = """⛔ 防重复规则（必须严格遵守）：
1. 不要重复前面章节已出现过的场景、对话、情节
2. 每个新场景必须有实质性的情节推进
3. 人物的行动和对话要有新的信息量，不能是已有信息的变体
4. 如果感觉情节陷入循环，引入新的冲突元素或外部事件打破僵局
5. 新章节的每一段文字都要向前推进故事，不能原地打转"""

            messages = [
                {'role': 'system', 'content': f"""你是专业小说作者。请根据已有摘要继续创作。

{anti_ai_text}

{style_rules}

{anti_repeat_rules}
创作要求：
- 保持风格一致，情节自然衔接
- 每段都要推动故事向前发展
- 人物对话要体现人物性格的成长和变化
- 避免使用与前文相似的句式、比喻和描写
- 绝不要写出"AI味"的文字"""},
                {'role': 'user', 'content': f"""【已写章节摘要】
{summary_text}

【上一章结尾】
{last_paragraph}

---
{instruction}，请写出完整章节（至少1500字）。

注意：新章节必须有新的情节发展、新的场景或新的人物互动，绝不能重复前文内容。"""}
            ]
            
            writing_tasks[task_id_new]['progress'] = 30
            
            # 续写时加强重复惩罚
            anti_repeat_config = dict(nonlocal_model_config)
            anti_repeat_config['repeat_penalty'] = nonlocal_model_config.get('repeat_penalty', 1.1) + 0.15
            anti_repeat_config['frequency_penalty'] = nonlocal_model_config.get('frequency_penalty', 0.3) + 0.2
            anti_repeat_config['presence_penalty'] = nonlocal_model_config.get('presence_penalty', 0.3) + 0.2
            
            result = call_llm(anti_repeat_config, messages)
            writing_tasks[task_id_new]['progress'] = 70
            
            # 自动续写检测
            result = _auto_continue(anti_repeat_config, messages, result)
            
            # 去AI味后处理
            result = _post_process_text(result, writing_style)
            
            writing_tasks[task_id_new]['output'] = result
            # 记录本章摘要
            summary = _extract_chapter_summary(result)
            if summary:
                writing_tasks[task_id_new]['chapter_summaries'].append(summary)
            writing_tasks[task_id_new]['progress'] = 100
            writing_tasks[task_id_new]['status'] = 'done'
            
            if _use_platform_api:
                _consume_platform_tokens(max(len(result), len(result) // 3))

            # 增加今日生成计数
            _increment_daily_gen_count()
                
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



# ========== 导出验证（防绕过） ==========
@app.route('/api/export', methods=['POST'])
def export_content():
    """导出前检查版本权限，支持 txt/pdf/epub/docx"""
    data = request.json or {}
    format = data.get('format', 'txt')
    
    lic = _get_current_license()
    allowed = lic['info'].get('export_formats', ['txt'])
    
    if format not in allowed:
        return jsonify({
            'ok': False,
            'error': f'当前版本不支持导出为 {format.upper()}，请升级',
            'tier': lic['tier'],
            'allowed': allowed
        }), 403
    
    # 权限通过，返回文件内容（由前端触发下载）
    return jsonify({'ok': True, 'format': format})

# ========== 静态文件 ==========
@app.route('/')
def index():
    lic = _get_current_license()
    info = dict(lic['info'])
    if info.get('platform_api_tokens', 0) > 0:
        remaining = _get_remaining_platform_tokens()
        info['platform_tokens_remaining'] = remaining
        info['platform_tokens_total'] = lic['info']['platform_api_tokens']
    license_json = json.dumps({'tier': lic['tier'], 'features': info}, ensure_ascii=False)
    
    html_path = Path(__file__).parent / 'static' / 'index.html'
    with open(html_path, 'r', encoding='utf-8') as f:
        html = f.read()
    
    # 注入 License 到页面（避免异步 fetch 失败）
    inject = f'\n<script>window.__LICENSE__ = {license_json};</script>\n</head>'
    html = html.replace('</head>', inject, 1)
    
    from flask import Response
    resp = Response(html, mimetype='text/html')
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp

@app.route('/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

if __name__ == '__main__':
    print("🚀 AI小说写作平台启动中...")
    print("📡 访问地址: http://127.0.0.1:8505")
    app.run(host='127.0.0.1', port=8505, debug=True)
