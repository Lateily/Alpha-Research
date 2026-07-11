#!/usr/bin/env python3
"""
Enrich public/data/universe_a.json with `industry` field from Tushare.

Reads existing universe_a.json (~5800 A-share stocks), calls
pro.stock_basic() to get industry classification for each, writes back.

Adds:
  industry        — Tushare's classification (e.g. "光器件", "新能源整车")
  industry_l1     — derived top-level (e.g. "电子", "汽车") — heuristic mapping

Run: python3 scripts/enrich_universe_industry.py
Re-run safe (idempotent — overwrites enriched fields).

Usage prerequisites: TUSHARE_TOKEN env var with Tushare 6000-tier active.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent.parent / "public" / "data"

# Heuristic L1 mapping from Tushare industry strings.
# (Tushare's industry field uses 二级 sometimes; this maps to coarser L1.)
L1_MAP = {
    # Tech / Electronics / Semi
    "半导体": "电子", "光器件": "电子", "电子元件": "电子", "消费电子": "电子",
    "面板": "电子", "印制电路板": "电子", "光学光电子": "电子",
    "通信设备": "电子", "通信运营": "通信", "通信服务": "通信",
    "计算机应用": "计算机", "计算机设备": "计算机", "软件开发": "计算机",
    "互联网传媒": "互联网",
    # Energy / Materials
    "煤炭开采": "能源", "石油加工": "能源", "石油开采": "能源", "天然气": "能源",
    "电力": "公用事业", "燃气": "公用事业", "水务": "公用事业", "环保工程": "环保",
    "钢铁": "材料", "工业金属": "材料", "贵金属": "材料", "化学原料": "材料",
    "塑料": "材料", "化学制品": "材料", "建筑材料": "材料", "玻璃": "材料",
    # Auto / NEV
    "汽车整车": "汽车", "汽车零部件": "汽车", "汽车服务": "汽车",
    "电池": "新能源", "光伏": "新能源", "风电": "新能源",
    # Healthcare / Biotech
    "化学制药": "医药", "中药": "医药", "生物制品": "医药",
    "医疗器械": "医药", "医疗服务": "医药", "医药商业": "医药",
    # Consumer / Brand
    "白酒": "消费", "啤酒": "消费", "软饮料": "消费", "食品加工": "消费",
    "饲料": "消费", "调味发酵品": "消费", "肉制品": "消费",
    "纺织制造": "消费", "服装家纺": "消费", "饰品": "消费",
    "家电": "消费", "白色家电": "消费", "厨卫电器": "消费", "黑色家电": "消费",
    "百货零售": "消费", "专业零售": "消费", "超市": "消费",
    "酒店餐饮": "消费", "旅游": "消费",
    "教育": "服务", "出版": "服务", "影视": "服务",
    # Finance
    "银行": "金融", "证券": "金融", "保险": "金融", "多元金融": "金融",
    # Real estate
    "房地产开发": "地产", "园区开发": "地产",
    # Industrials / Capital goods
    "工程机械": "工业", "通用设备": "工业", "专用设备": "工业", "自动化设备": "工业",
    "电气设备": "工业", "电源设备": "工业", "电网设备": "工业",
    "国防军工": "国防",
    "航空运输": "交运", "航运港口": "交运", "公路铁路": "交运", "物流": "交运",
    # Building / Construction
    "房屋建设": "建筑", "基础建设": "建筑", "装饰装修": "建筑", "建筑装饰": "建筑",
    "园林工程": "建筑", "工程咨询": "建筑",
    # Agriculture
    "种植业": "农业", "养殖业": "农业", "农产品加工": "农业",
}

DEFAULT_L1 = "其他"


def _classify_l1(industry):
    """Map Tushare industry → coarser L1 bucket."""
    if not industry:
        return DEFAULT_L1
    return L1_MAP.get(industry, DEFAULT_L1)


def main():
    token = os.environ.get("TUSHARE_TOKEN", "")
    if not token:
        print("ERROR: TUSHARE_TOKEN not in env", file=sys.stderr)
        return 1

    try:
        import tushare as ts
    except ImportError:
        print("ERROR: tushare not installed (pip3 install tushare)", file=sys.stderr)
        return 1

    ts.set_token(token)
    pro = ts.pro_api()

    # 1. Load universe_a.json
    universe_path = OUTPUT_DIR / "universe_a.json"
    if not universe_path.exists():
        print(f"ERROR: {universe_path} not found", file=sys.stderr)
        return 1

    with open(universe_path, encoding="utf-8") as f:
        universe = json.load(f)

    stocks = universe.get("stocks", [])
    print(f"Loaded {len(stocks)} A-share stocks from universe_a.json")

    # 2. Fetch stock_basic from Tushare (single call returns ~5800 rows)
    print("Fetching stock_basic from Tushare 6000 tier...")
    try:
        basic = pro.stock_basic(
            exchange='',
            list_status='L',
            fields='ts_code,name,industry,area,market'
        )
    except Exception as e:
        print(f"ERROR: Tushare stock_basic failed: {e}", file=sys.stderr)
        return 1

    print(f"Got {len(basic)} stocks from Tushare stock_basic")

    # Build lookup: ts_code → industry
    industry_map = {}
    for _, row in basic.iterrows():
        industry_map[row['ts_code']] = {
            'industry': row['industry'] or '',
            'area': row['area'] or '',
            'market': row['market'] or '',
        }

    # 3. Enrich universe stocks
    enriched = 0
    missed = 0
    industry_counts = {}
    l1_counts = {}

    for stock in stocks:
        ts_code = stock.get('ticker', '')  # universe uses .SZ/.SH suffix already
        info = industry_map.get(ts_code)
        if info:
            stock['industry'] = info['industry']
            stock['industry_l1'] = _classify_l1(info['industry'])
            stock['area'] = info['area']
            stock['exchange_market'] = info['market']  # 主板/创业板/科创板/北交所
            enriched += 1
            industry_counts[info['industry']] = industry_counts.get(info['industry'], 0) + 1
            l1_counts[stock['industry_l1']] = l1_counts.get(stock['industry_l1'], 0) + 1
        else:
            stock['industry'] = ''
            stock['industry_l1'] = DEFAULT_L1
            missed += 1

    print(f"\n=== Enrichment results ===")
    print(f"Enriched: {enriched} / {len(stocks)} ({enriched/len(stocks)*100:.1f}%)")
    print(f"Missed (no Tushare match): {missed}")
    print()
    print(f"Top 10 industries by stock count:")
    for ind, n in sorted(industry_counts.items(), key=lambda x: -x[1])[:10]:
        print(f"  {ind:12s}  {n}")
    print()
    print(f"L1 distribution:")
    for l1, n in sorted(l1_counts.items(), key=lambda x: -x[1]):
        print(f"  {l1:8s}  {n}")

    # 4. Update _meta + write back
    universe['_meta']['industry_enriched_at'] = datetime.now(timezone.utc).isoformat()
    universe['_meta']['industry_enrichment_source'] = 'Tushare 6000-tier stock_basic'
    universe['_meta']['industry_l1_classifier'] = 'scripts/enrich_universe_industry.py L1_MAP heuristic'

    with open(universe_path, 'w', encoding='utf-8') as f:
        json.dump(universe, f, ensure_ascii=False, indent=2)

    print(f"\nWrote enriched data → {universe_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
