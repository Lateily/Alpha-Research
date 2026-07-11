"""Tushare connectivity sanity check.

Tests:
1. Token is loaded from env
2. Free-tier API (stock_basic) works
3. Tier-120 API (daily for 300308.SZ) works
4. Tier-6000 API (moneyflow_hsgt) works — useful for USP layer

Usage:
    export TUSHARE_TOKEN='...'
    python3 scripts/test_tushare.py
"""
import os
import sys

# --- Test 0: token presence ---
token = os.environ.get('TUSHARE_TOKEN', '')
if not token:
    print('FAIL [TEST 0] TUSHARE_TOKEN not in env')
    print('  Fix: source ~/.zshrc, or restart terminal')
    sys.exit(1)
print(f'PASS [TEST 0] token loaded (len={len(token)}, head={token[:6]})')

# --- Test 1: import tushare ---
try:
    import tushare as ts
    print(f'PASS [TEST 1] tushare imported (version {ts.__version__})')
except ImportError:
    print('FAIL [TEST 1] tushare not installed')
    print('  Fix: pip3 install tushare')
    sys.exit(1)

ts.set_token(token)
pro = ts.pro_api()

# --- Test 2: stock_basic (free, 0 points) ---
try:
    df = pro.stock_basic(exchange='', list_status='L',
                         fields='ts_code,name,area,industry')
    print(f'PASS [TEST 2] stock_basic — {len(df)} stocks listed')
    print(df.head(3).to_string(index=False))
except Exception as e:
    print(f'FAIL [TEST 2] stock_basic: {e}')
    sys.exit(1)

# --- Test 3: daily for 300308.SZ (120 points minimum) ---
try:
    df = pro.daily(ts_code='300308.SZ',
                   start_date='20260420',
                   end_date='20260430')
    if len(df) == 0:
        print('WARN [TEST 3] daily returned 0 rows (date range may be off)')
    else:
        print(f'PASS [TEST 3] daily 300308.SZ — {len(df)} rows')
        print(df.head(3).to_string(index=False))
except Exception as e:
    print(f'FAIL [TEST 3] daily: {e}')

# --- Test 4: moneyflow_hsgt — 北向资金 (6000 points tier) ---
print()
print('--- Tier-6000 USP API check ---')
try:
    df = pro.moneyflow_hsgt(start_date='20260420', end_date='20260430')
    if len(df) == 0:
        print('WARN [TEST 4] moneyflow_hsgt returned 0 rows')
    else:
        print(f'PASS [TEST 4] moneyflow_hsgt — {len(df)} rows')
        print(df.head(3).to_string(index=False))
        print()
        print('🎉 6000 积分已到账。USP 北向资金数据可用。')
except Exception as e:
    msg = str(e)
    if 'permission' in msg.lower() or '权限' in msg or '积分' in msg:
        print('PENDING [TEST 4] moneyflow_hsgt — tier 6000 not yet active')
        print(f'  Reason: {msg}')
        print('  Status: 充值审核进行中（通常 24h 内到账）')
        print('  Action: 明天再跑一次 — python3 scripts/test_tushare.py')
    else:
        print(f'FAIL [TEST 4] moneyflow_hsgt: {msg}')
