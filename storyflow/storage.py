"""数据持久化层：JSON 文件存储，支持原子写入"""
import json
import time
import threading
from pathlib import Path
from storyflow.config import DATA_DIR

_file_lock = threading.Lock()

DATA_DIR.mkdir(exist_ok=True)

PROJECTS_FILE = DATA_DIR / 'projects.json'
CUSTOM_TEMPLATES_FILE = DATA_DIR / 'custom_templates.json'
LICENSE_FILE = DATA_DIR / 'license.json'
PAYMENTS_FILE = DATA_DIR / 'payments.json'
TOKEN_USAGE_FILE = DATA_DIR / 'platform_tokens.json'


def load_json(path, default):
    with _file_lock:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding='utf-8'))
            except Exception:
                return default
        return default


def save_json(path, data):
    with _file_lock:
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(path)


def get_daily_gen_count() -> int:
    today = time.strftime('%Y-%m-%d')
    count_file = DATA_DIR / f'gen_count_{today}.json'
    data = load_json(count_file, {'count': 0})
    return data.get('count', 0)


def increment_daily_gen_count():
    today = time.strftime('%Y-%m-%d')
    count_file = DATA_DIR / f'gen_count_{today}.json'
    data = load_json(count_file, {'count': 0})
    data['count'] = data.get('count', 0) + 1
    save_json(count_file, data)


def get_template_daily_count() -> int:
    today = time.strftime('%Y-%m-%d')
    tc_file = DATA_DIR / f'template_count_{today}.json'
    data = load_json(tc_file, {'count': 0})
    return data.get('count', 0)


def increment_template_daily_count():
    today = time.strftime('%Y-%m-%d')
    tc_file = DATA_DIR / f'template_count_{today}.json'
    data = load_json(tc_file, {'count': 0})
    data['count'] = data.get('count', 0) + 1
    save_json(tc_file, data)


# ─── Platform Token 追踪 ───

def get_platform_token_usage():
    return load_json(TOKEN_USAGE_FILE, {})


def get_remaining_platform_tokens(license_key_hash: str, total: int) -> int:
    if total == 0:
        return 0
    usage = get_platform_token_usage()
    used = usage.get(license_key_hash, 0)
    return max(0, total - used)


def consume_platform_tokens(license_key_hash: str, n: int):
    usage = get_platform_token_usage()
    usage[license_key_hash] = usage.get(license_key_hash, 0) + n
    save_json(TOKEN_USAGE_FILE, usage)
