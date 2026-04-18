#!/usr/bin/env python3
"""
scripts/swing_signals.py — Deterministic swing trading signal generator
Reads  public/data/ohlc_*.json
Writes public/data/signals_{id}.json

Signal types:
  GOLDEN_CROSS    — MA20 crossed above MA60 within last 5 bars
  DEATH_CROSS     — MA20 crossed below MA60 within last 5 bars
  RSI_OVERSOLD    — RSI(14) < 30
  RSI_OVERBOUGHT  — RSI(14) > 70
  RSI_RECOVERING  — RSI rising from <40 back toward neutral
  VOLUME_BREAKOUT — Volume > 2× MA20 AND price ≥ +2%
  VOLUME_SELLOFF  — Volume > 2× MA20 AND price ≤ -2%
  MA20_BOUNCE     — Price bounced off MA20 support (within 3%)
  MA60_BOUNCE     — Price bounced off MA60 major support (within 3%)

Zone values: BULLISH | BEARISH | NEUTRAL | OVERSOLD | OVERBOUGHT
"""

import json
import glob
import os
from datetime import datetime, timezone

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'public', 'data')


# ── Math helpers ──────────────────────────────────────────────────────────────

def sma(series, n):
    """Simple moving average — list same length as input, None where < n values."""
    result = [None] * len(series)
    for i in range(n - 1, len(series)):
        result[i] = sum(series[i - n + 1:i + 1]) / n
    return result


def rsi(closes, period=14):
    """
    Wilder's RSI — list same length as closes.
    Result[i] is the RSI using closes[0..i].
    First valid value at index = period.
    """
    result = [None] * len(closes)
    if len(closes) < period + 1:
        return result

    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains   = [max(c, 0.0) for c in changes]
    losses  = [abs(min(c, 0.0)) for c in changes]

    # Seed: simple average over first period
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    def _rsi_from(ag, al):
        if al == 0:
            return 100.0
        return 100.0 - 100.0 / (1.0 + ag / al)

    result[period] = _rsi_from(avg_gain, avg_loss)

    for i in range(period, len(changes)):
        avg_gain = (avg_gain * (period - 1) + gains[i])  / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        result[i + 1] = _rsi_from(avg_gain, avg_loss)

    return result


# ── Signal engine ─────────────────────────────────────────────────────────────

def compute_signals(ticker, bars):
    """
    bars: list of {date, open, high, low, close, volume} sorted oldest→newest.
    Returns signals dict or None if insufficient data.
    """
    if len(bars) < 20:
        return None

    closes  = [b['close']  for b in bars]
    volumes = [b['volume'] for b in bars]
    dates   = [b['date']   for b in bars]
    n       = len(bars)

    # ── Indicator arrays ───────────────────────────────────────────────────
    ma5_arr   = sma(closes, 5)
    ma20_arr  = sma(closes, 20)
    ma60_arr  = sma(closes, 60)
    rsi14_arr = rsi(closes, 14)
    vma20_arr = sma(volumes, 20)

    def at(arr, offset=0):
        idx = n - 1 - offset
        return arr[idx] if 0 <= idx < len(arr) else None

    price   = closes[-1]
    ma5     = at(ma5_arr)
    ma20    = at(ma20_arr)
    ma60    = at(ma60_arr)
    rsi_val = at(rsi14_arr)
    vma20   = at(vma20_arr)
    vol_now = volumes[-1]

    # ── Price-change helpers ───────────────────────────────────────────────
    def pct_chg(n_bars):
        if n > n_bars:
            p0 = bars[-(n_bars + 1)]['close']
            return round((price - p0) / p0 * 100, 2) if p0 else None
        return None

    # ── Signals list ──────────────────────────────────────────────────────
    sigs = []

    # 1. Golden / Death Cross (MA20 vs MA60 within last CROSS_WINDOW bars)
    CROSS_WINDOW = 5
    if ma20 is not None and ma60 is not None:
        for k in range(1, min(CROSS_WINDOW + 1, n)):
            pm20 = ma20_arr[n - 1 - k]
            pm60 = ma60_arr[n - 1 - k]
            if pm20 is None or pm60 is None:
                continue
            if pm20 <= pm60 and ma20 > ma60:
                sigs.append({
                    'type': 'GOLDEN_CROSS', 'strength': 'strong',
                    'date': dates[-1], 'bullish': True,
                    'description': {
                        'e': f'MA20 ({ma20:.1f}) crossed above MA60 ({ma60:.1f}) — bullish trend shift',
                        'z': f'MA20({ma20:.1f})上穿MA60({ma60:.1f})金叉看涨',
                    }
                })
                break
            if pm20 >= pm60 and ma20 < ma60:
                sigs.append({
                    'type': 'DEATH_CROSS', 'strength': 'strong',
                    'date': dates[-1], 'bullish': False,
                    'description': {
                        'e': f'MA20 ({ma20:.1f}) crossed below MA60 ({ma60:.1f}) — bearish trend shift',
                        'z': f'MA20({ma20:.1f})下穿MA60({ma60:.1f})死叉看跌',
                    }
                })
                break

    # 2. RSI zones
    if rsi_val is not None:
        rsi_prev = at(rsi14_arr, 1)
        if rsi_val < 30:
            sigs.append({
                'type': 'RSI_OVERSOLD',
                'strength': 'strong' if rsi_val < 20 else 'moderate',
                'date': dates[-1], 'bullish': True,
                'description': {
                    'e': f'RSI(14) = {rsi_val:.1f} — oversold, watch for reversal',
                    'z': f'RSI(14)={rsi_val:.1f}，超卖，关注反转信号',
                }
            })
        elif rsi_val > 70:
            sigs.append({
                'type': 'RSI_OVERBOUGHT',
                'strength': 'strong' if rsi_val > 80 else 'moderate',
                'date': dates[-1], 'bullish': False,
                'description': {
                    'e': f'RSI(14) = {rsi_val:.1f} — overbought, watch for exhaustion',
                    'z': f'RSI(14)={rsi_val:.1f}，超买，注意回调风险',
                }
            })
        elif (rsi_prev is not None
              and rsi_prev < 40
              and rsi_val > rsi_prev
              and rsi_val < 55):
            sigs.append({
                'type': 'RSI_RECOVERING', 'strength': 'moderate',
                'date': dates[-1], 'bullish': True,
                'description': {
                    'e': f'RSI recovering {rsi_prev:.1f}→{rsi_val:.1f} — momentum rebuilding',
                    'z': f'RSI从{rsi_prev:.1f}回升至{rsi_val:.1f}，动能修复',
                }
            })

    # 3. Volume breakout / selloff
    if vma20 is not None and vma20 > 0:
        vol_ratio = vol_now / vma20
        if vol_ratio >= 2.0 and n >= 2:
            p1d_chg = (price - closes[-2]) / closes[-2] * 100 if closes[-2] else 0
            if p1d_chg >= 2.0:
                sigs.append({
                    'type': 'VOLUME_BREAKOUT',
                    'strength': 'strong' if vol_ratio >= 3.0 else 'moderate',
                    'date': dates[-1], 'bullish': True,
                    'description': {
                        'e': f'Volume {vol_ratio:.1f}× avg, price +{p1d_chg:.1f}% — buying surge',
                        'z': f'成交量{vol_ratio:.1f}倍均量，股价+{p1d_chg:.1f}%，放量上攻',
                    }
                })
            elif p1d_chg <= -2.0:
                sigs.append({
                    'type': 'VOLUME_SELLOFF',
                    'strength': 'strong' if vol_ratio >= 3.0 else 'moderate',
                    'date': dates[-1], 'bullish': False,
                    'description': {
                        'e': f'Volume {vol_ratio:.1f}× avg, price {p1d_chg:.1f}% — distribution',
                        'z': f'成交量{vol_ratio:.1f}倍均量，股价{p1d_chg:.1f}%，放量下跌',
                    }
                })

    # 4. MA20 bounce — price hovered near MA20 yesterday, closed above today
    if n >= 3 and ma20 is not None:
        prev_close = closes[-2]
        prev_ma20  = ma20_arr[n - 2]
        if (prev_ma20 is not None
                and abs(prev_close - prev_ma20) / prev_ma20 < 0.03
                and price > prev_ma20
                and price > prev_close):
            sigs.append({
                'type': 'MA20_BOUNCE', 'strength': 'moderate',
                'date': dates[-1], 'bullish': True,
                'description': {
                    'e': f'Price bounced off MA20 ({prev_ma20:.1f}) — near-term support held',
                    'z': f'股价从MA20({prev_ma20:.1f})附近反弹，短期支撑有效',
                }
            })

    # 5. MA60 bounce — price hovered near MA60 yesterday, closed above today
    if n >= 3 and ma60 is not None:
        prev_close = closes[-2]
        prev_ma60  = ma60_arr[n - 2]
        if (prev_ma60 is not None
                and abs(prev_close - prev_ma60) / prev_ma60 < 0.03
                and price > prev_ma60
                and price > prev_close):
            sigs.append({
                'type': 'MA60_BOUNCE', 'strength': 'strong',
                'date': dates[-1], 'bullish': True,
                'description': {
                    'e': f'Price bounced off MA60 ({prev_ma60:.1f}) — major support held',
                    'z': f'股价从MA60({prev_ma60:.1f})附近反弹，主要支撑有效',
                }
            })

    # ── Zone classification ───────────────────────────────────────────────
    if rsi_val is not None and rsi_val < 30:
        zone = 'OVERSOLD'
    elif rsi_val is not None and rsi_val > 70:
        zone = 'OVERBOUGHT'
    elif (ma20 is not None and ma60 is not None
          and ma20 > ma60 and price > ma20):
        zone = 'BULLISH'
    elif (ma20 is not None and ma60 is not None
          and ma20 < ma60 and price < ma20):
        zone = 'BEARISH'
    else:
        zone = 'NEUTRAL'

    # ── Entry / exit zones ────────────────────────────────────────────────
    bullish = [s for s in sigs if s['bullish']]
    bearish = [s for s in sigs if not s['bullish']]

    entry_types = {'RSI_OVERSOLD', 'RSI_RECOVERING', 'GOLDEN_CROSS',
                   'MA20_BOUNCE', 'MA60_BOUNCE', 'VOLUME_BREAKOUT'}
    exit_types  = {'RSI_OVERBOUGHT', 'DEATH_CROSS', 'VOLUME_SELLOFF'}

    entry_zone = zone == 'OVERSOLD' or any(s['type'] in entry_types for s in bullish)
    exit_zone  = zone == 'OVERBOUGHT' or any(s['type'] in exit_types for s in bearish)

    # ── Vol ratio ─────────────────────────────────────────────────────────
    vol_ratio_val = round(vol_now / vma20, 2) if (vma20 and vma20 > 0) else None

    return {
        'ticker':       ticker,
        'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'price':        price,
        'zone':         zone,
        'entry_zone':   entry_zone,
        'exit_zone':    exit_zone,
        'signals':      sigs,
        'signal_count': {
            'bullish': len(bullish),
            'bearish': len(bearish),
            'total':   len(sigs),
        },
        'indicators': {
            'ma5':           round(ma5,  2) if ma5  is not None else None,
            'ma20':          round(ma20, 2) if ma20 is not None else None,
            'ma60':          round(ma60, 2) if ma60 is not None else None,
            'rsi14':         round(rsi_val, 1) if rsi_val is not None else None,
            'vol_ma20':      round(vma20)      if vma20   is not None else None,
            'vol_ratio':     vol_ratio_val,
            'price_vs_ma20': round((price - ma20) / ma20 * 100, 2) if ma20 else None,
            'price_vs_ma60': round((price - ma60) / ma60 * 100, 2) if ma60 else None,
            'change_1d':     pct_chg(1),
            'change_5d':     pct_chg(5),
            'change_20d':    pct_chg(20),
        },
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    pattern = os.path.join(DATA_DIR, 'ohlc_*.json')
    files   = sorted(glob.glob(pattern))

    if not files:
        print('[swing_signals] No ohlc_*.json files found — skipping.')
        return

    print(f'[swing_signals] Found {len(files)} OHLC file(s)')

    for fpath in files:
        fname   = os.path.basename(fpath)                   # e.g. ohlc_300308_SZ.json
        safe_id = fname[len('ohlc_'):-len('.json')]         # e.g. 300308_SZ

        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                raw = json.load(f)

            ticker = raw.get('ticker', safe_id.replace('_', '.'))
            bars   = raw.get('data', [])

            if not bars:
                print(f'  [skip] {fname} — empty data array')
                continue

            result = compute_signals(ticker, bars)
            if result is None:
                print(f'  [skip] {fname} — need ≥20 bars (have {len(bars)})')
                continue

            out_path = os.path.join(DATA_DIR, f'signals_{safe_id}.json')
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            z   = result['zone']
            sc  = result['signal_count']
            ind = result['indicators']
            rsi_s = f"RSI={ind['rsi14']}" if ind['rsi14'] else 'RSI=n/a'
            print(f'  ✓ {ticker:16s}  price={result["price"]:>8.2f}  zone={z:<11s}  '
                  f'{rsi_s}  signals={sc["bullish"]}↑/{sc["bearish"]}↓')

        except Exception as exc:
            print(f'  [error] {fname}: {exc}')

    print('[swing_signals] Complete.')


if __name__ == '__main__':
    main()
