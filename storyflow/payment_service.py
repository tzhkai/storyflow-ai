"""支付集成（易支付/MZPay 协议）"""
import hashlib
import time
import uuid
import requests
from storyflow.config import MZ_PID, MZ_KEY, MZ_API, PAYMENT_NOTIFY_URL, PAYMENT_RETURN_URL
from storyflow.storage import load_json, save_json, PAYMENTS_FILE


def mz_sign(params: dict) -> str:
    keys = sorted(k for k in params if k not in ('sign', 'sign_type'))
    s = '&'.join([f"{k}={params[k]}" for k in keys])
    return hashlib.md5((s + MZ_KEY).encode()).hexdigest()


def mz_verify(params: dict) -> bool:
    sign = params.pop('sign', '')
    params.pop('sign_type', '')
    expected = mz_sign(params)
    return sign.lower() == expected.lower()


def load_payments() -> list:
    return load_json(PAYMENTS_FILE, [])


def save_payments(payments: list):
    save_json(PAYMENTS_FILE, payments)


def create_order(tier: str, pay_type: str) -> dict:
    from storyflow.config import PRICES
    if tier not in PRICES:
        return {'error': '无效的版本类型'}
    type_map = {'alipay': 'alipay', 'wxpay': 'wxpay', 'wechat': 'wxpay', 'native': 'wxpay'}
    if pay_type not in type_map:
        return {'error': '无效的支付方式'}

    price = PRICES[tier]['amount']
    label = PRICES[tier]['label']
    order_id = 'SF' + str(int(time.time())) + uuid.uuid4().hex[:8].upper()

    payments = load_payments()
    payments.append({
        'order_id': order_id, 'tier': tier, 'pay_type': pay_type,
        'amount': price, 'status': 'pending', 'key': None,
        'created_at': int(time.time()), 'paid_at': None,
    })
    save_payments(payments)

    params = {
        'pid': MZ_PID, 'type': type_map[pay_type],
        'out_trade_no': order_id,
        'notify_url': PAYMENT_NOTIFY_URL,
        'return_url': PAYMENT_RETURN_URL,
        'name': f'StoryFlow {label} License',
        'money': price, 'sitename': 'StoryFlow',
    }
    params['sign'] = mz_sign(params)
    params['sign_type'] = 'MD5'

    try:
        resp = requests.post(MZ_API, data=params, timeout=15).json()
        if resp.get('code') != 200:
            payments = [p for p in load_payments() if p['order_id'] != order_id]
            save_payments(payments)
            return {'error': f'支付平台错误: {resp.get("msg", "未知错误")}'}
        qr_url = resp.get('qrcode') or resp.get('code_url', '')
        return {
            'ok': True, 'order_id': order_id, 'amount': price,
            'tier': tier, 'pay_type': pay_type, 'qr_url': qr_url,
            'trade_no': resp.get('trade_no', ''),
        }
    except Exception as e:
        payments = [p for p in load_payments() if p['order_id'] != order_id]
        save_payments(payments)
        return {'error': f'请求支付失败: {str(e)}'}


def handle_callback(params: dict) -> str:
    from storyflow.license import generate_license_key
    if not mz_verify(params):
        return 'fail', 400
    out_trade_no = params.get('out_trade_no', '')
    trade_status = params.get('trade_status', '')
    if trade_status == 'TRADE_SUCCESS':
        payments = load_payments()
        for p in payments:
            if p['order_id'] == out_trade_no and p['status'] == 'pending':
                p['status'] = 'paid'
                p['paid_at'] = int(time.time())
                p['key'] = generate_license_key(p['tier'])
                save_payments(payments)
                return 'success', 200
    return 'success', 200


def check_order(order_id: str) -> dict:
    payments = load_payments()
    for p in payments:
        if p['order_id'] == order_id:
            if p['status'] == 'paid':
                return {'ok': True, 'status': 'paid', 'key': p['key'], 'tier': p['tier']}
            return {'ok': True, 'status': 'pending'}
    return {'error': '订单不存在'}
