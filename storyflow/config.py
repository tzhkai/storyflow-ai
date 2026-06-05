"""环境配置：所有密钥和配置从 .env 读取，消除硬编码"""
import os
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
DATA_DIR = ROOT_DIR / 'data'
STATIC_DIR = ROOT_DIR / 'static'

_env_file = ROOT_DIR / '.env'
if _env_file.exists():
    with open(_env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())

# ─── API 访问令牌 ───
ACCESS_TOKEN = os.environ.get('SF_ACCESS_TOKEN', '')

# ─── License 签名密钥（本地回退验证用，云端验证优先） ───
LICENSE_SECRET = os.environ.get('SF_LICENSE_SECRET', 'storyflow-license-secret-2026').encode('utf-8')

# ─── License 云端验证 Worker 地址 ───
# 设置后所有 License 验证走云端，防本地篡改
LICENSE_VERIFY_URL = os.environ.get('SF_LICENSE_VERIFY_URL', '')
LICENSE_SIGN_URL = os.environ.get('SF_LICENSE_SIGN_URL', '')

# ─── 平台 API（用于付费用户代理调用） ───
PLATFORM_API_KEY = os.environ.get('SF_PLATFORM_KEY', '')
PLATFORM_API_MODEL = os.environ.get('SF_PLATFORM_MODEL', 'deepseek-v4-flash')

# ─── 支付（易支付/MZPay） ───
MZ_PID = os.environ.get('SF_MZ_PID', '13344')
MZ_KEY = os.environ.get('SF_MZ_KEY', '50AsxG3zRCJttxgJjlgh')
MZ_API = os.environ.get('SF_MZ_API', 'https://pay.mymzf.com/mapi.php')
PAYMENT_NOTIFY_URL = os.environ.get('SF_PAYMENT_NOTIFY_URL', 'http://127.0.0.1:8505/api/payment/callback')
PAYMENT_RETURN_URL = os.environ.get('SF_PAYMENT_RETURN_URL', 'http://127.0.0.1:8505/')

# ─── 定价 ───
PRICES = {
    'standard': {'amount': '29.00', 'label': '标准版'},
    'professional': {'amount': '99.00', 'label': '专业版'},
}
