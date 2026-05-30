#!/usr/bin/env python3
"""
StoryFlow License Key 生成器

用法:
  python generate_key.py standard          # 生成1个标准版 Key
  python generate_key.py professional     # 生成1个专业版 Key
  python generate_key.py standard --count 100   # 批量生成100个标准版 Key
  python generate_key.py verify SF-STD-XXXX  # 验证 Key

定价:
  标准版 (standard): ¥69 买断
  专业版 (professional): ¥199 买断
"""

import hashlib
import hmac
import sys
import uuid

# 必须与 server.py 中的 _LICENSE_SECRET 一致
LICENSE_SECRET = b'storyflow-license-secret-2026'

TIER_MAP = {
    'standard': 'STD',
    'professional': 'PRO',
}

def sign_key(key_data: str) -> str:
    """HMAC-SHA256 签名，取前24位"""
    return hmac.new(LICENSE_SECRET, key_data.encode('utf-8'), hashlib.sha256).hexdigest()[:24]

def generate_key(tier: str) -> str:
    """生成 License Key"""
    if tier not in TIER_MAP:
        print(f"❌ 无效的版本类型: {tier}")
        print(f"   可选: {', '.join(TIER_MAP.keys())}")
        sys.exit(1)

    tier_code = TIER_MAP[tier]
    random_part = uuid.uuid4().hex[:12].upper()
    signature = sign_key(f"{tier}-{random_part}")

    key = f"SF-{tier_code}-{random_part}-{signature.upper()}"
    return key

def verify_key(key: str) -> dict:
    """验证 License Key"""
    code_to_tier = {v: k for k, v in TIER_MAP.items()}

    parts = key.strip().upper().split('-')
    if len(parts) != 4 or parts[0] != 'SF':
        return {'valid': False, 'error': '格式错误'}

    _, tier_code, random_part, signature = parts

    if tier_code not in code_to_tier:
        return {'valid': False, 'error': f'无效的版本代码: {tier_code}'}

    tier = code_to_tier[tier_code]
    expected_sig = sign_key(f"{tier}-{random_part}")

    if not hmac.compare_digest(signature, expected_sig.upper()):
        return {'valid': False, 'error': '签名验证失败'}

    tier_names = {'standard': '标准版', 'professional': '专业版'}
    return {'valid': True, 'tier': tier, 'name': tier_names.get(tier, tier)}

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    command = sys.argv[1].lower()

    # 解析 --count 参数
    count = 1
    for i, arg in enumerate(sys.argv):
        if arg == '--count' and i + 1 < len(sys.argv):
            try:
                count = int(sys.argv[i + 1])
            except ValueError:
                print(f"❌ --count 必须是数字")
                sys.exit(1)

    if command == 'verify' and len(sys.argv) >= 3:
        result = verify_key(sys.argv[2])
        if result['valid']:
            print(f"✅ 有效 — {result['name']} ({result['tier']})")
        else:
            print(f"❌ 无效 — {result['error']}")
    elif command in TIER_MAP:
        tier_names = {'standard': '标准版 (¥69)', 'professional': '专业版 (¥199)'}
        for i in range(count):
            key = generate_key(command)
            print(f"{key}")
        # 自验证最后一条
        if count == 1:
            print()
            result = verify_key(key)
            print(f"   验证: {'✅ 通过' if result['valid'] else '❌ 失败'}")
    else:
        print(f"❌ 未知命令: {command}")
        print(f"   可用: {', '.join(TIER_MAP.keys())}, verify")
        sys.exit(1)

if __name__ == '__main__':
    main()
