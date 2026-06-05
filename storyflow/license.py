"""License 验证与管理"""
import hashlib
import hmac
import json
import time
import requests
from storyflow.config import LICENSE_SECRET, LICENSE_VERIFY_URL, LICENSE_SIGN_URL
from storyflow.storage import load_json, save_json, LICENSE_FILE, get_daily_gen_count, get_remaining_platform_tokens

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

PRO_ONLY_TYPES = {'romance', 'custom'}
CODE_TO_TIER = {'STD': 'standard', 'PRO': 'professional'}


def sign_key(key_data: str) -> str:
    return hmac.new(LICENSE_SECRET, key_data.encode('utf-8'), hashlib.sha256).hexdigest()[:24]


def verify_license_cloud(license_key: str) -> dict:
    """通过 Worker 云端验证 License Key（防本地篡改）"""
    if not LICENSE_VERIFY_URL:
        return None
    try:
        resp = requests.post(
            f"{LICENSE_VERIFY_URL}/api/v1/license/verify",
            json={'key': license_key},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get('valid'):
                return {'valid': True, 'tier': data['tier'], 'info': TIER_FEATURES.get(data['tier'], TIER_FEATURES['free'])}
            return {'valid': False, 'error': data.get('error', 'Key 无效')}
    except requests.exceptions.RequestException:
        pass
    return None


def verify_license(license_key: str) -> dict:
    try:
        parts = license_key.upper().split('-')
        if len(parts) != 4 or parts[0] != 'SF':
            return {'valid': False, 'error': '格式错误，正确格式: SF-XXX-XXXX-XXXX'}
        _, tier_code, random_part, signature = parts
        if tier_code not in CODE_TO_TIER:
            return {'valid': False, 'error': '无效的版本类型'}
        tier = CODE_TO_TIER[tier_code]
        expected_sig = sign_key(f"{tier}-{random_part}")
        if not hmac.compare_digest(signature, expected_sig.upper()):
            return {'valid': False, 'error': '签名验证失败，Key 无效'}
        return {'valid': True, 'tier': tier, 'info': TIER_FEATURES[tier]}
    except Exception as e:
        return {'valid': False, 'error': str(e)}


def get_current_license() -> dict:
    saved = load_json(LICENSE_FILE, {})
    if not saved.get('key'):
        return {'tier': 'free', 'info': TIER_FEATURES['free']}
    # 优先云端验证
    cloud_result = verify_license_cloud(saved['key'])
    if cloud_result is not None:
        if cloud_result.get('valid'):
            return {'tier': cloud_result['tier'], 'info': cloud_result['info'], 'key': saved['key']}
        # 云端明确返回无效，回退免费
        return {'tier': 'free', 'info': TIER_FEATURES['free']}
    # 云端不可达时回退本地验证
    result = verify_license(saved['key'])
    if result.get('valid'):
        return {'tier': result['tier'], 'info': result['info'], 'key': saved['key']}
    return {'tier': 'free', 'info': TIER_FEATURES['free']}


def get_license_token_id():
    saved = load_json(LICENSE_FILE, {})
    key = saved.get('key', 'free')
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def get_remaining_tokens(lic: dict) -> int:
    total = lic['info'].get('platform_api_tokens', 0)
    if total == 0:
        return 0
    lid = get_license_token_id()
    return get_remaining_platform_tokens(lid, total)


def generate_license_key(tier: str) -> str:
    import uuid
    tier_code = 'STD' if tier == 'standard' else 'PRO'
    random_part = str(uuid.uuid4()).replace('-', '')[:12].upper()
    key_data = f"{tier}-{random_part}"
    sig = sign_key(key_data)
    return f"SF-{tier_code}-{random_part}-{sig.upper()}"


def activate_license(key: str) -> dict:
    result = verify_license(key)
    if not result.get('valid'):
        return {'ok': False, 'error': result.get('error', '无效的 Key')}
    save_json(LICENSE_FILE, {'key': key, 'activated_at': time.time(), 'tier': result['tier']})
    return {
        'ok': True,
        'tier': result['tier'],
        'info': result['info'],
        'message': f"已激活 {result['info']['name']}！"
    }


def deactivate_license():
    save_json(LICENSE_FILE, {})


def get_features():
    lic = get_current_license()
    info = dict(lic['info'])
    if info.get('platform_api_tokens', 0) > 0:
        remaining = get_remaining_tokens(lic)
        info['platform_tokens_remaining'] = remaining
        info['platform_tokens_total'] = lic['info']['platform_api_tokens']
    return {'tier': lic['tier'], 'features': info}
