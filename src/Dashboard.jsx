import { useState, useEffect, useRef } from "react";
import React from "react";
import { Search, SearchX, TrendingUp, TrendingDown, Minus, ChevronDown, BarChart3, Flame, Sparkles,
         Shield, Zap, Globe, Eye, Target, Filter, Radio, Crosshair,
         AlertCircle, CheckCircle, ArrowUpRight, ArrowDownRight,
         Database, RefreshCw, Layers, BookOpen, Info, Calendar,
         Sun, Moon, ChevronLeft, ChevronRight, Circle,
         Wifi, WifiOff } from "lucide-react";
import { PieChart as RechartsPie, Pie, Cell, BarChart, Bar, ComposedChart, LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";

/* ── DATA BASE URL ──────────────────────────────────────────────────────────── */
// On GitHub Pages (or any non-localhost host), fetch data files directly from the
// raw GitHub repo so market_data.json is always fresh the moment fetch-data.yml
// pushes — no redeploy needed.  Local dev continues to use the Vite dev server.
const DATA_BASE = (typeof window !== 'undefined' && window.location.hostname !== 'localhost')
  ? 'https://raw.githubusercontent.com/Lateily/Alpha-Research/main/public/'
  : (import.meta.env.BASE_URL || '/');

/* ── THEME ─────────────────────────────────────────────────────────────────── */
/* ══════════════════════════════════════════════════════════════════
   MODERN SAAS THEME  (ref: clean dashboard, white cards + blue page)
   Light = default  |  Dark = navy
═══════════════════════════════════════════════════════════════════ */
const LIGHT = {
  blue:   '#3A6FD8',   // primary blue — buttons, accents, active states
  gold:   '#D08000',   // amber warning
  green:  '#1E9C5A',   // success / up
  red:    '#D94040',   // danger / down
  dark:   '#1C2B4A',   // primary text
  mid:    '#6B82A0',   // secondary text / icons
  bg:     '#E9EFF9',   // soft blue-grey page background
  card:   '#FFFFFF',   // white card surface
  border: '#DCE5F3',   // very subtle border
  soft:   '#F0F5FC',   // hover row / stripe / input bg
  orange: '#D06A00',   // Capital IQ accent orange
};
// Jason: Bloomberg Terminal palette — deep navy bg, sharp contrast, signature orange accent
const DARK = {
  blue:   '#4B9EFF',   // secondary action blue
  gold:   '#FFB800',   // amber warning / gold
  green:  '#00D97E',   // up tick / success
  red:    '#FF4757',   // down tick / danger
  dark:   '#E2EEF9',   // primary text — crisp blue-white
  mid:    '#4A6680',   // secondary text / muted labels
  bg:     '#050D1A',   // Bloomberg black-navy — deep background
  card:   '#091526',   // card surface
  border: '#102038',   // subtle structural border
  soft:   '#0D1E35',   // hover row / stripe
  orange: '#FF8C00',   // Bloomberg signature orange — active/accent
};

/* ── SHARED STYLE TOKENS ────────────────────────────────────────────────────── */
const MONO = "'JetBrains Mono','Courier New',monospace";
const SHADOW = '0 2px 12px rgba(50,90,160,0.10)';
const SHADOW_SM = '0 1px 4px rgba(50,90,160,0.08)';

function finiteNumber(v) {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function ma(values, period) {
  const out = Array(values?.length || 0).fill(null);
  if (!Array.isArray(values) || period <= 0) return out;
  let sum = 0;
  let valid = 0;
  for (let i = 0; i < values.length; i += 1) {
    const next = finiteNumber(values[i]);
    if (next != null) {
      sum += next;
      valid += 1;
    }
    if (i >= period) {
      const prev = finiteNumber(values[i - period]);
      if (prev != null) {
        sum -= prev;
        valid -= 1;
      }
    }
    if (i >= period - 1 && valid === period) out[i] = sum / period;
  }
  return out;
}

function ema(values, period) {
  const out = Array(values?.length || 0).fill(null);
  if (!Array.isArray(values) || period <= 0) return out;
  const alpha = 2 / (period + 1);
  let prev = null;
  for (let i = 0; i < values.length; i += 1) {
    const current = finiteNumber(values[i]);
    if (current == null) {
      prev = null;
      continue;
    }
    if (prev == null) {
      if (i < period - 1) continue;
      let sum = 0;
      let ok = true;
      for (let j = i - period + 1; j <= i; j += 1) {
        const n = finiteNumber(values[j]);
        if (n == null) {
          ok = false;
          break;
        }
        sum += n;
      }
      if (!ok) continue;
      prev = sum / period;
    } else {
      prev = current * alpha + prev * (1 - alpha);
    }
    out[i] = prev;
  }
  return out;
}

function bollinger(closes, period = 20, k = 2) {
  const mid = ma(closes, period);
  const upper = Array(closes?.length || 0).fill(null);
  const lower = Array(closes?.length || 0).fill(null);
  if (!Array.isArray(closes) || period <= 0) return { mid, upper, lower };
  for (let i = 0; i < closes.length; i += 1) {
    if (mid[i] == null) continue;
    let sumSq = 0;
    let ok = true;
    for (let j = i - period + 1; j <= i; j += 1) {
      const n = finiteNumber(closes[j]);
      if (n == null) {
        ok = false;
        break;
      }
      sumSq += (n - mid[i]) ** 2;
    }
    if (!ok) continue;
    const sd = Math.sqrt(sumSq / period);
    upper[i] = mid[i] + k * sd;
    lower[i] = mid[i] - k * sd;
  }
  return { mid, upper, lower };
}

function macd(closes, fast = 12, slow = 26, signal = 9) {
  const fastEma = ema(closes, fast);
  const slowEma = ema(closes, slow);
  const line = Array(closes?.length || 0).fill(null);
  for (let i = 0; i < line.length; i += 1) {
    if (fastEma[i] != null && slowEma[i] != null) line[i] = fastEma[i] - slowEma[i];
  }
  const sig = ema(line, signal);
  const hist = line.map((v, i) => (v != null && sig[i] != null ? v - sig[i] : null));
  return { line, signal: sig, hist };
}

function kdj(highs, lows, closes, period = 9) {
  const len = Array.isArray(closes) ? closes.length : 0;
  const k = Array(len).fill(null);
  const d = Array(len).fill(null);
  const j = Array(len).fill(null);
  if (!Array.isArray(highs) || !Array.isArray(lows) || !Array.isArray(closes) || period <= 0) return { k, d, j };
  let prevK = 50;
  let prevD = 50;
  for (let i = 0; i < len; i += 1) {
    if (i < period - 1) continue;
    let hi = -Infinity;
    let lo = Infinity;
    let ok = true;
    for (let x = i - period + 1; x <= i; x += 1) {
      const h = finiteNumber(highs[x]);
      const l = finiteNumber(lows[x]);
      if (h == null || l == null) {
        ok = false;
        break;
      }
      hi = Math.max(hi, h);
      lo = Math.min(lo, l);
    }
    const close = finiteNumber(closes[i]);
    if (!ok || close == null || !Number.isFinite(hi) || !Number.isFinite(lo)) {
      prevK = 50;
      prevD = 50;
      continue;
    }
    const rsv = hi === lo ? 50 : ((close - lo) / (hi - lo)) * 100;
    const nextK = (2 / 3) * prevK + (1 / 3) * rsv;
    const nextD = (2 / 3) * prevD + (1 / 3) * nextK;
    k[i] = nextK;
    d[i] = nextD;
    j[i] = 3 * nextK - 2 * nextD;
    prevK = nextK;
    prevD = nextD;
  }
  return { k, d, j };
}

function rsi(closes, period = 14) {
  const out = Array(closes?.length || 0).fill(null);
  if (!Array.isArray(closes) || period <= 0) return out;
  let avgGain = null;
  let avgLoss = null;
  const calcRsi = (gain, loss) => {
    if (loss === 0) return gain === 0 ? 50 : 100;
    return 100 - (100 / (1 + gain / loss));
  };
  for (let i = 1; i < closes.length; i += 1) {
    const current = finiteNumber(closes[i]);
    const previous = finiteNumber(closes[i - 1]);
    if (current == null || previous == null) {
      avgGain = null;
      avgLoss = null;
      continue;
    }
    if (avgGain == null || avgLoss == null) {
      if (i < period) continue;
      let gainSum = 0;
      let lossSum = 0;
      let ok = true;
      for (let j = i - period + 1; j <= i; j += 1) {
        const cur = finiteNumber(closes[j]);
        const prev = finiteNumber(closes[j - 1]);
        if (cur == null || prev == null) {
          ok = false;
          break;
        }
        const diff = cur - prev;
        gainSum += Math.max(diff, 0);
        lossSum += Math.max(-diff, 0);
      }
      if (!ok) continue;
      avgGain = gainSum / period;
      avgLoss = lossSum / period;
    } else {
      const diff = current - previous;
      avgGain = (avgGain * (period - 1) + Math.max(diff, 0)) / period;
      avgLoss = (avgLoss * (period - 1) + Math.max(-diff, 0)) / period;
    }
    out[i] = calcRsi(avgGain, avgLoss);
  }
  return out;
}

const S = {
  card:{ background:'none', borderRadius:12, marginBottom:12,
         overflow:'hidden', boxShadow:SHADOW },
  cardHd:{ padding:'12px 16px', cursor:'pointer', display:'flex',
           justifyContent:'space-between', alignItems:'center' },
  cardBd:{ padding:'12px 16px' },
  row:{ display:'flex', alignItems:'center', gap:8 },
  flex:{ display:'flex' },
  tag:(c)=>({ fontSize:9, fontWeight:600, padding:'3px 9px', borderRadius:20,
               background:`${c}14`, color:c }),
  mono:{ fontFamily:MONO },
  label:{ fontSize:10, color:'currentColor', fontWeight:600,
          opacity:0.55, letterSpacing:'0.02em' },
  val:{ fontSize:13, fontWeight:700, color:'currentColor', fontFamily:MONO },
  sec:{ fontSize:11, color:'currentColor', lineHeight:1.7 },
};

/* ── DATA ───────────────────────────────────────────────────────────────────── */
const MACRO = [
  { name:'CNY/USD', val:'7.24', chg:'-0.3%', trend:'stable', note:{e:'PBOC maintaining stability band',z:'央行维持稳定区间'} },
  { name:'CN 10Y', val:'2.31%', chg:'+4bp', trend:'up', note:{e:'Mild tightening signal, watch for RRR cut',z:'温和收紧信号，关注降准'} },
  { name:'PMI', val:'50.8', chg:'+0.3', trend:'up', note:{e:'Manufacturing expansion accelerating',z:'制造业扩张加速'} },
  { name:'US 10Y', val:'4.38%', chg:'+8bp', trend:'up', note:{e:'Higher for longer narrative intact',z:'长期高利率叙事持续'} },
  { name:'VIX', val:'16.2', chg:'-1.4', trend:'down', note:{e:'Risk appetite improving globally',z:'全球风险偏好改善'} },
];

const SECTOR_IND = [
  { sector:'AI Infra', indicators:[
    { name:{e:'Hyperscaler CapEx',z:'超大规模资本支出'}, signal:85, trend:'up', fresh:'2d', src:'MSFT/META Q1' },
    { name:{e:'800G/1.6T Orders',z:'800G/1.6T订单'}, signal:78, trend:'up', fresh:'1w', src:'LightCounting' },
    { name:{e:'GPU Shipments',z:'GPU出货量'}, signal:72, trend:'up', fresh:'3d', src:'NVIDIA channel' },
  ]},
  { sector:'HK Internet', indicators:[
    { name:{e:'Online Ad Spend',z:'在线广告支出'}, signal:68, trend:'up', fresh:'2w', src:'CTR Media' },
    { name:{e:'Gaming Licence Pace',z:'版号审批节奏'}, signal:55, trend:'stable', fresh:'1m', src:'NPPA' },
    { name:{e:'WeChat MAU Growth',z:'微信MAU增长'}, signal:62, trend:'stable', fresh:'1q', src:'Tencent IR' },
  ]},
  { sector:'Biotech', indicators:[
    { name:{e:'NMPA Approvals',z:'NMPA审批'}, signal:70, trend:'up', fresh:'1w', src:'NMPA.gov' },
    { name:{e:'BTK Inhibitor Scripts',z:'BTK抑制剂处方量'}, signal:76, trend:'up', fresh:'2w', src:'IQVIA' },
    { name:{e:'IRA Negotiation Status',z:'IRA谈判进展'}, signal:40, trend:'down', fresh:'1m', src:'CMS.gov' },
  ]},
  { sector:'EV/Auto', indicators:[
    { name:{e:'NEV Monthly Sales',z:'新能源月销量'}, signal:74, trend:'up', fresh:'5d', src:'CPCA' },
    { name:{e:'Battery Material Price',z:'电池材料价格'}, signal:52, trend:'stable', fresh:'1w', src:'SMM' },
    { name:{e:'EU Tariff Risk',z:'欧盟关税风险'}, signal:35, trend:'down', fresh:'2w', src:'EU Commission' },
  ]},
];

const PORTFOLIO = {
  netExposure: '82%', grossExposure: '100%', positions: 5, regimeAlign: 87,
  sectors: [
    { name:'AI Infra', pct:25 },
    { name:'Platform', pct:20 },
    { name:'Gaming', pct:15 },
    { name:'Biotech', pct:22 },
    { name:'EV/Auto', pct:18 },
  ],
};

const STOCKS = {
  '300308.SZ': {
    name:'中际旭创', en:'Innolight', sector:'AI Infra', dir:'LONG', vp:79, price:'¥138.50', mktcap:'¥184B',
    pulse:{ e:'800G/1.6T demand peak. SiPh ramp inflection. Hyperscaler orders accelerating.', z:'800G/1.6T需求旺盛，硅光放量拐点，超大规模订单加速。' },
    biz:{
      problem:{ e:'AI GPUs need >100Gbps per port; copper fails beyond 3m.', z:'AI GPU每端口需100Gbps+，铜线3米外衰减失效。' },
      mechanism:{ e:'Innolight converts electrical→optical (EO), transmits via fiber, back (OE). SiPh integrates EO/OE on-chip, cutting power 40%.', z:'光电转换+硅光一体集成，降低功耗40%。' },
      moneyFlow:{ e:'Hyperscalers pay ¥1,100–2,200/transceiver × millions of ports × 3–5yr cycle. Top 3 = ~60% rev.', z:'超大规模客户每收发器¥1,100–2,200×百万端口。' }
    },
    variant:{
      marketBelieves:{ e:'1.6T volume 2H 2026, SiPh gross margin 38%.', z:'1.6T 2026下半年放量，硅光毛利38%。' },
      weBelieve:{ e:'1.6T qualifies Q2 2025; GM reaches 42% as SiPh mix hits 60%.', z:'1.6T Q2 2025认证，毛利42%。' },
      mechanism:{ e:'SiPh eliminates connectors; ByteDance/MSFT dual-source validation underway.', z:'硅光消除连接器，字节/微软双供认证中。' },
      rightIf:{ e:'Q2 2025 revenue >¥4.2B and SiPh guidance raised.', z:'Q2营收>¥42亿。' },
      wrongIf:{ e:'1.6T qualification slips to Q4 2025 OR hyperscaler CapEx cut >20%.', z:'认证推迟或资本支出削减>20%。' }
    },
    catalysts:[
      { e:'1.6T SiPh customer qualification (ByteDance/MSFT)', z:'1.6T硅光客户认证（字节/微软）', t:'Q2 2025', date:'2025-06-15', imp:'HIGH' },
      { e:'Q1 2025 earnings — SiPh mix > 50%', z:'Q1财报硅光占比>50%', t:'Apr 2025', date:'2025-04-30', imp:'HIGH' },
      { e:'State Grid power infra AI order', z:'国家电网AI电力基建订单', t:'2025', date:'2025-08-01', imp:'MED' },
    ],
    decomp:{ expectation_gap:{s:72,e:'Consensus underprices 1.6T speed',z:'共识低估1.6T进度'}, fundamental_acc:{s:80,e:'SiPh GM expansion accelerating',z:'硅光毛利快速扩张'}, narrative_shift:{s:65,e:'AI infra proxy re-rating',z:'AI基础设施重估'}, low_coverage:{s:55,e:'Limited sell-side SiPh model depth',z:'卖方硅光建模不足'}, catalyst_prox:{s:85,e:'Q2 qual event imminent',z:'Q2认证事件临近'} },
    risks:[{ e:'1.6T qualification delay beyond Q3 2025', z:'1.6T认证推迟至Q3+', p:'LOW', imp:'HIGH' },{ e:'Hyperscaler CapEx cut (recessionary)', z:'超大规模资本支出削减', p:'LOW', imp:'HIGH' },{ e:'SiPh yield ramp slower than guided', z:'硅光良率爬坡慢于指引', p:'MED', imp:'MED' }],
    pricing:{level:'LOW',crowd:{e:'Limited hedge fund positioning; sell-side models do not yet incorporate SiPh margin expansion',z:'对冲基金持仓有限；卖方模型尚未纳入硅光利润率扩张'}},
    nextActions:[{e:'Verify Q2 SiPh mix from channel checks',z:'通过渠道检查验证Q2硅光占比'},{e:'Cross-check 1.6T timeline vs NVIDIA roadmap',z:'交叉验证1.6T时间线与NVIDIA路线图'},{e:'Monitor ByteDance capex guidance update',z:'监控字节跳动资本支出指引更新'}],
    fin:{ rev:'¥16.8B', revGr:'+47%', gm:'39%', pe:28, ev_ebitda:18, fcf:'¥2.1B' },
    peerAvg:{ pe:32, ev_ebitda:22, gm:'35%' },
  },
  '700.HK': {
    name:'腾讯控股', en:'Tencent', sector:'Platform', dir:'LONG', vp:64, price:'HK$392', mktcap:'HK$3.8T',
    pulse:{ e:'WeChat AI monetisation underpriced. Buyback acceleration. State Council digital support.', z:'微信AI变现被低估。回购加速。国务院数字经济支持。' },
    biz:{
      problem:{ e:'Digital attention fragmented; advertisers need reach, developers need distribution.', z:'数字注意力碎片化。' },
      mechanism:{ e:'WeChat closed-loop (communication+payments+mini-apps). Switching cost = 1.3B social graph + payment history.', z:'微信闭环生态，切换成本=13亿用户社交图谱+支付记录。' },
      moneyFlow:{ e:'Advertisers pay HK$55–90 CPM. Gaming: 30% take on HK$200B. WePay: 0.6% per merchant txn.', z:'广告CPM 55–90港元，游戏抽成30%，支付0.6%。' }
    },
    variant:{
      marketBelieves:{ e:'AI investment is a drag; gaming recovery capped at 10%; buyback is price floor only.', z:'AI是拖累；游戏复苏封顶10%；回购只是底价。' },
      weBelieve:{ e:'Weixin AI (keyboard+search+mini-app) lifts ARPU 15–20% by 2026; gaming recovers 18%+ driven by overseas.', z:'微信AI将ARPU提升15-20%；游戏海外驱动18%+。' },
      mechanism:{ e:'AI features deployed to 1.3B users with zero marginal distribution cost.', z:'AI特性部署至13亿用户。' },
      rightIf:{ e:'2025 online ads >HK$120B; Weixin AI MAU >200M.', z:'2025在线广告>1200亿港元。' },
      wrongIf:{ e:'Regulatory cap on gaming minors extended OR macro consumption weakens sharply.', z:'游戏监管扩大或消费急剧恶化。' }
    },
    catalysts:[{ e:'Weixin AI feature launch metrics (MAU/ARPU)', z:'微信AI功能上线数据', t:'Q2 2025', date:'2025-06-30', imp:'HIGH' },{ e:'Q4 2024 earnings — gaming international', z:'Q4财报海外游戏', t:'Mar 2025', date:'2025-03-31', imp:'MED' }],
    decomp:{ expectation_gap:{s:68,e:'AI monetisation not in consensus',z:'AI变现未入共识'}, fundamental_acc:{s:70,e:'Gaming + ads dual recovery',z:'游戏+广告双复苏'}, narrative_shift:{s:75,e:'State endorsement changes narrative',z:'国家背书改变叙事'}, low_coverage:{s:40,e:'Well-covered stock',z:'覆盖充分'}, catalyst_prox:{s:60,e:'AI launch timing uncertain',z:'AI上线时机不确定'} },
    risks:[{ e:'Regulatory re-tightening on gaming', z:'游戏监管重新收紧', p:'MED', imp:'HIGH' },{ e:'Macro consumption weakness', z:'宏观消费疲软', p:'MED', imp:'MED' }],
    pricing:{level:'MID',crowd:{e:'Consensus has partial AI narrative but underestimates ARPU uplift magnitude',z:'共识部分反映AI叙事但低估ARPU提升幅度'}},
    nextActions:[{e:'Track Weixin AI feature rollout metrics',z:'跟踪微信AI功能推出数据'},{e:'Compare Q1 ad revenue vs consensus',z:'对比Q1广告收入与市场共识'},{e:'Monitor gaming regulatory signals',z:'监控游戏监管信号'}],
    fin:{ rev:'HK$660B', revGr:'+8%', gm:'52%', pe:16, ev_ebitda:12, fcf:'HK$180B' },
    peerAvg:{ pe:18, ev_ebitda:14, gm:'48%' },
  },
  '9999.HK': {
    name:'网易', en:'NetEase', sector:'Gaming', dir:'LONG', vp:58, price:'HK$152', mktcap:'HK$207B',
    pulse:{ e:'Stable gaming IP monetisation undervalued. Japan market penetration accelerating.', z:'稳定游戏IP变现被低估。日本市场渗透加速。' },
    biz:{
      problem:{ e:'Gaming hits have short lifecycles; studios need durable IP revenue.', z:'游戏爆款生命周期短。' },
      mechanism:{ e:'NetEase builds franchise ecosystems (Fantasy Westward Journey 20yr). Deep in-game economy creates daily engagement loops.', z:'网易构建IP生态（梦幻西游20年），深度游戏经济创造日常留存。' },
      moneyFlow:{ e:'IAP (in-app purchase) at 30–40% GM; licensing fees from overseas publishers.', z:'应用内购30-40%毛利；海外授权费。' }
    },
    variant:{
      marketBelieves:{ e:'NetEase is ex-growth; Blizzard loss is permanent damage.', z:'网易增长停滞；暴雪流失永久损伤。' },
      weBelieve:{ e:'Japan market (Naraka, Marvel Rivals) adds ¥4B incremental revenue by 2026; Blizzard titles replaceable.', z:'日本市场(永劫/漫威对决)增量营收¥40亿。' },
      mechanism:{ e:'Japanese gaming market lacks domestic multiplayer competition.', z:'日本游戏市场缺少国内对手。' },
      rightIf:{ e:'Japan MAU >3M by Q3 2025.', z:'日本MAU>300万。' },
      wrongIf:{ e:'Marvel Rivals DAU drops below 2M.', z:'漫威对决DAU低于200万。' }
    },
    catalysts:[{ e:'Marvel Rivals Season 2 launch metrics', z:'漫威对决S2上线数据', t:'Q2 2025', date:'2025-05-15', imp:'HIGH' },{ e:'Japan revenue disclosure in Q1 results', z:'Q1财报日本营收披露', t:'May 2025', date:'2025-05-31', imp:'MED' }],
    decomp:{ expectation_gap:{s:62,e:'Japan TAM underestimated',z:'日本TAM被低估'}, fundamental_acc:{s:55,e:'IP economics improving',z:'IP经济学改善'}, narrative_shift:{s:50,e:'Post-Blizzard recovery narrative',z:'后暴雪复苏叙事'}, low_coverage:{s:45,e:'Moderate coverage',z:'覆盖适中'}, catalyst_prox:{s:65,e:'S2 launch imminent',z:'S2即将发布'} },
    risks:[{ e:'Marvel Rivals user retention falls', z:'漫威对决留存下降', p:'MED', imp:'HIGH' },{ e:'China gaming licence delays', z:'国内版号延迟', p:'LOW', imp:'MED' }],
    pricing:{level:'MID',crowd:{e:'Japan expansion partially recognized; Marvel Rivals success somewhat priced',z:'日本扩张部分被认可；漫威对决成功部分入价'}},
    nextActions:[{e:'Check Marvel Rivals S2 first-week DAU',z:'检查漫威对决S2首周DAU'},{e:'Verify Japan revenue in Q1 report',z:'在Q1财报中验证日本营收'},{e:'Track Steam concurrent user trends',z:'跟踪Steam同时在线趋势'}],
    fin:{ rev:'¥102B', revGr:'+7%', gm:'63%', pe:14, ev_ebitda:9, fcf:'¥28B' },
    peerAvg:{ pe:16, ev_ebitda:11, gm:'60%' },
  },
  '6160.HK': {
    name:'百济神州 (BeOne)', en:'BeOne Medicines (fka BeiGene)', sector:'Biotech', dir:'LONG', vp:65, price:'HK$1,440', mktcap:'HK$154B',
    pulse:{ e:'Sonrotoclax+Brukinsa combo (ZS) = potential best-in-class fixed-duration CLL regimen. CELESTIAL Ph3 uMRD data H2 2026. Pirtobrutinib long-term share threat underappreciated by bulls.', z:'泽布替尼+sonrotoclax联合(ZS)=潜在最佳固定疗程CLL方案。CELESTIAL三期uMRD数据2026下半年。多替布鲁替尼长期份额威胁被多头低估。' },
    biz:{
      problem:{ e:'CLL/MCL patients on single-agent BTK face indefinite treatment duration + acquired resistance. Need fixed-duration combos.', z:'单药BTK的CLL/MCL患者面临无限期治疗+获得性耐药，需要固定疗程联合方案。' },
      mechanism:{ e:'Brukinsa (zanubrutinib, 2nd-gen covalent BTK) + sonrotoclax (next-gen BCL2) = all-oral fixed-duration combo. ZS showed best-in-class uMRD rates in early data vs venetoclax+obinutuzumab.', z:'泽布替尼(二代共价BTK)+sonrotoclax(新一代BCL2)=全口服固定疗程。ZS的uMRD率在早期数据中优于维奈托克+奥比妥珠单抗。' },
      moneyFlow:{ e:'Brukinsa FY2025 $3.9B (+49%). $15K/patient/month US. ZS combo at premium pricing = $5-8B peak franchise. 60+ countries. Redomiciled to Switzerland (May 2025) as BeOne Medicines.', z:'泽布替尼2025全年39亿美元(+49%)。ZS联合方案峰值50-80亿美元。已迁册瑞士更名BeOne。' }
    },
    variant:{
      marketBelieves:{ e:'Brukinsa is a maturing single-product franchise; pirtobrutinib (Jaypirca) will capture 60% CLL BTK share by 2032; FY26 guidance miss ($6.2-6.4B vs $6.44B consensus) signals deceleration.', z:'泽布替尼是成熟单品；多替布鲁替尼将占2032年60% CLL BTK份额；FY26指引低于共识信号减速。' },
      weBelieve:{ e:'ZS combo creates a second growth curve worth $5-8B at peak, making Brukinsa single-agent share erosion irrelevant. CELESTIAL Phase 3 uMRD data in H2 2026 is the catalyst for re-rating from single-drug to platform.', z:'ZS联合方案创造第二增长曲线峰值50-80亿美元，使单药份额流失不重要。CELESTIAL三期数据是从单品到平台重估的催化剂。' },
      mechanism:{ e:'Fixed-duration ZS eliminates the indefinite-treatment economics that make pirtobrutinib competitive. Physicians prefer finite courses; ZS early data shows superior uMRD vs standard of care.', z:'固定疗程ZS消除无限期治疗经济学(多替布鲁替尼的竞争优势)。医生偏好限期疗程；ZS早期数据uMRD优于标准治疗。' },
      rightIf:{ e:'CELESTIAL Phase 3 uMRD rate >65% (vs ~55% for venetoclax+obinutuzumab historical) AND FY26 revenue exceeds $6.4B.', z:'CELESTIAL三期uMRD率>65%且FY26营收超64亿美元。' },
      wrongIf:{ e:'CELESTIAL uMRD data disappoints (<50%) OR pirtobrutinib Phase 3 1L CLL data shows superior PFS, undermining ZS rationale.', z:'CELESTIAL uMRD数据不及预期(<50%)或多替布鲁替尼1L CLL数据PFS更优。' }
    },
    catalysts:[
      { e:'CELESTIAL Phase 3 uMRD data (ZS vs VO in 1L CLL)', z:'CELESTIAL三期uMRD数据(ZS vs VO 一线CLL)', t:'H2 2026', date:'2026-09-15', imp:'HIGH' },
      { e:'Q1 2026 earnings (Apr 30) — Brukinsa quarterly run-rate trajectory', z:'Q1 2026财报(4月30日)——泽布替尼季度运营轨迹', t:'Apr 2026', date:'2026-04-30', imp:'HIGH' },
      { e:'BGB-16673 (BTK degrader) pivotal Phase 2 R/R CLL data', z:'BGB-16673(BTK降解剂)关键二期R/R CLL数据', t:'H2 2026', date:'2026-10-15', imp:'MED' },
      { e:'Sonrotoclax NDA/MAA filing for MCL (positive Ph2 topline)', z:'Sonrotoclax MCL适应症NDA/MAA申报(二期积极)', t:'2026', date:'2026-12-01', imp:'MED' },
    ],
    decomp:{ expectation_gap:{s:72,e:'Market models Brukinsa as single-drug franchise; ZS combo TAM not in consensus models',z:'市场将泽布替尼建模为单药；ZS联合TAM未入共识模型'}, fundamental_acc:{s:65,e:'Brukinsa Q4 2025 $1.1B (+38% QoQ sequential); revenue acceleration intact',z:'泽布替尼Q4 2025 11亿美元环比+38%；营收加速持续'}, narrative_shift:{s:68,e:'Redomiciliation to Switzerland signals platform ambition; 15 pipeline drugs + $4B cash',z:'迁册瑞士信号平台野心；15个管线药物+40亿现金'}, low_coverage:{s:45,e:'Well-covered but ZS combo modeling sparse among sell-side',z:'覆盖充分但卖方ZS联合建模稀缺'}, catalyst_prox:{s:70,e:'Q1 2026 earnings in 18 days; CELESTIAL data within 6 months',z:'Q1财报18天内；CELESTIAL数据6个月内'} },
    risks:[{ e:'CELESTIAL Phase 3 uMRD data misses expectations (<50%)', z:'CELESTIAL三期uMRD数据不及预期(<50%)', p:'MED', imp:'HIGH' },{ e:'Pirtobrutinib 1L CLL Phase 3 shows superior PFS, commoditizing covalent BTK class', z:'多替布鲁替尼1L CLL三期PFS更优，共价BTK类别商品化', p:'MED', imp:'HIGH' },{ e:'IRA price negotiation reduces US Brukinsa pricing >25%', z:'IRA价格谈判削减美国泽布替尼定价>25%', p:'MED', imp:'MED' },{ e:'Sonrotoclax safety signal in long-term follow-up', z:'Sonrotoclax长期随访安全性信号', p:'LOW', imp:'HIGH' }],
    pricing:{level:'MID',crowd:{e:'Stock at $185 vs avg analyst target $330 — 78% upside in consensus. Market pricing single-drug deceleration narrative; ZS combo optionality largely unpriced.',z:'股价$185 vs 分析师均值$330——78%上行空间。市场定价单品减速叙事；ZS联合期权价值未充分入价。'}},
    nextActions:[{e:'Model ZS combo peak revenue scenarios ($5B/$6.5B/$8B) with probability weights',z:'建模ZS联合峰值营收情景(50/65/80亿)及概率权重'},{e:'Track pirtobrutinib 1L CLL Phase 3 enrollment/timeline for competitive read-through',z:'跟踪多替布鲁替尼1L CLL三期入组/时间线'},{e:'Verify Q1 2026 Brukinsa geographic mix (US vs EU vs RoW) on Apr 30 call',z:'4月30日电话会验证Q1泽布替尼地理结构'},{e:'Monitor sonrotoclax MCL Phase 2 full dataset for filing timeline clarity',z:'监控sonrotoclax MCL二期完整数据评估申报时间线'}],
    fin:{ rev:'$3.9B', revGr:'+49%', gm:'84%', pe:38, ev_ebitda:28, fcf:'$0.3B' },
    peerAvg:{ pe:35, ev_ebitda:24, gm:'80%' },
  },
  '002594.SZ': {
    name:'比亚迪', en:'BYD', sector:'EV/Auto', dir:'LONG', vp:52, price:'¥298', mktcap:'¥866B',
    pulse:{ e:'Overseas EV infrastructure building. DM5 hybrid tech moat widening. EM exposure underestimated.', z:'海外EV基础设施布局。DM5混动技术护城河扩大。新兴市场敞口被低估。' },
    biz:{
      problem:{ e:'ICE vehicles face regulatory phase-out; consumers need affordable EVs with range anxiety solved.', z:'燃油车面临政策淘汰，消费者需要解决里程焦虑的平价电动车。' },
      mechanism:{ e:'BYD vertical integration (Blade battery + e-Platform 3.0 + in-house semiconductor). DM5 PHEV = 2,000km range.', z:'刀片电池+e平台3.0+自研芯片垂直整合。DM5混动续航2000公里。' },
      moneyFlow:{ e:'Vehicle sales at ¥120K–400K ASP × 3M+ units/yr. Battery supply to VW/Toyota. IGBT/SiC chip licensing.', z:'12-40万均价×300万+台/年+电池供应大众/丰田。' }
    },
    variant:{
      marketBelieves:{ e:'BYD is China-only; margin pressure from price war.', z:'比亚迪只在中国；价格战压缩利润。' },
      weBelieve:{ e:'EM export (Brazil/SEA/MENA) adds 400K units by 2026; DM5 enables premium pricing floors.', z:'新兴市场出口(巴西/东南亚/中东)增加40万台。' },
      mechanism:{ e:'Local assembly partnerships bypass tariffs; DM5 has no Western equivalent.', z:'本地化组装规避关税。' },
      rightIf:{ e:'2025 export >350K units.', z:'2025出口>35万台。' },
      wrongIf:{ e:'EU tariffs >35% AND Brazil imposes local content rules.', z:'欧盟关税>35%且巴西本地化要求。' }
    },
    catalysts:[{ e:'Brazil factory opening + local pricing', z:'巴西工厂开业+本地定价', t:'Q2 2025', date:'2025-06-01', imp:'MED' },{ e:'DM6 announcement (3rd-gen hybrid)', z:'DM6发布（第三代混动）', t:'H2 2025', date:'2025-09-30', imp:'MED' }],
    decomp:{ expectation_gap:{s:55,e:'EM volume undermodelled',z:'新兴市场产量建模不足'}, fundamental_acc:{s:60,e:'DM5 ASP holding up',z:'DM5均价维持'}, narrative_shift:{s:45,e:'Global EV leader narrative building',z:'全球EV领导者叙事构建'}, low_coverage:{s:35,e:'High coverage stock',z:'高覆盖股票'}, catalyst_prox:{s:50,e:'Brazil opening in weeks',z:'巴西工厂数周内开业'} },
    risks:[{ e:'EU/US tariff escalation on Chinese EVs', z:'欧美对中国EV加征关税', p:'HIGH', imp:'HIGH' },{ e:'China EV price war deepens margins', z:'中国EV价格战加剧', p:'MED', imp:'MED' }],
    pricing:{level:'HIGH',crowd:{e:'Well-followed stock; EM export thesis gaining traction in sell-side notes',z:'高关注度股票；新兴市场出口论点逐渐进入卖方报告'}},
    nextActions:[{e:'Track Brazil factory output ramp data',z:'跟踪巴西工厂产出爬坡数据'},{e:'Monitor EU tariff vote timeline',z:'监控欧盟关税投票时间线'},{e:'Check DM5 monthly sales vs DM-i cannibalization',z:'检查DM5月销量vs DM-i蚕食效应'}],
    fin:{ rev:'¥770B', revGr:'+28%', gm:'23%', pe:22, ev_ebitda:14, fcf:'¥38B' },
    peerAvg:{ pe:24, ev_ebitda:16, gm:'20%' },
  },
};

const SCANNER = {
  regime:{ status:'Permissive', e:'China policy in expansion mode. Risk-on for quality growth. A-share liquidity improving.', z:'中国政策扩张模式。优质成长风险偏好提升。A股流动性改善。' },
  date:{ e:'April 13, 2026 · Pre-Market', z:'2026年4月13日 · 盘前' },
  factors:[
    { name:'Momentum', val:68, t:'up' },{ name:'Value', val:44, t:'down' },
    { name:'Quality', val:72, t:'up' },{ name:'Sentiment', val:61, t:'up' },{ name:'AI Beta', val:84, t:'up' },
  ],
  funnel:[
    { s:'Universe', n:4800, r:'A+HK listed' },{ s:'Quant Filter', n:156, r:'PEG<1.5, ROE>12%' },
    { s:'Regime Gate', n:42, r:'Non-restrictive' },{ s:'VP Score', n:12, r:'VP>50' },{ s:'Deep Dive', n:5, r:'EV>0' },
  ],
};

const MACRO_ANCHORS = [
  { macro:'CNY/USD', stocks:['002594.SZ'], impact:'positive', weight:'medium',
    note:{e:'Weaker CNY benefits BYD export competitiveness',z:'人民币贬值利好比亚迪出口竞争力'} },
  { macro:'CN 10Y', stocks:['700.HK','9999.HK'], impact:'negative', weight:'low',
    note:{e:'Rising rates mildly pressure growth multiples',z:'利率上升温和压制成长股估值'} },
  { macro:'PMI', stocks:['300308.SZ'], impact:'positive', weight:'high',
    note:{e:'Manufacturing expansion drives optical component demand',z:'制造业扩张推动光器件需求'} },
  { macro:'US 10Y', stocks:['6160.HK'], impact:'negative', weight:'medium',
    note:{e:'Higher US rates pressure biotech DCF valuations',z:'美国利率上升压制生物科技DCF估值'} },
  { macro:'VIX', stocks:['700.HK','9999.HK','300308.SZ'], impact:'positive', weight:'medium',
    note:{e:'Lower VIX supports risk-on positioning in China tech',z:'VIX下降支持中国科技风险偏好'} },
];

const PEERS = [
  { pair:'Innolight vs Eoptolink', ticker:'300308 vs 603488', div:'VP 79 vs 45', corr:0.82, betaAdj:1.12, catalystDiv:{e:'1.6T qualification timing gap',z:'1.6T认证时间差'}, invalidation:{e:'Eoptolink closes SiPh gap within 2 quarters',z:'易飞光电2个季度内缩小硅光差距'}, e:'SiPh premium vs margin compression. Pair trade on qualification delta.', z:'硅光溢价vs利润率压缩。认证差异配对交易。' },
  { pair:'Tencent vs Alibaba', ticker:'700 vs 9988', div:'VP 64 vs 48', corr:0.75, betaAdj:0.95, catalystDiv:{e:'AI monetization timeline divergence',z:'AI变现时间线分化'}, invalidation:{e:'BABA restructuring unlocks >20% re-rating',z:'阿里重组触发>20%重估'}, e:'WeChat AI vs restructuring overhang. Long TENCENT / short BABA.', z:'微信AI vs 重组阴影。做多腾讯/做空阿里。' },
];

/* ── VISUALIZATION COMPONENTS ─────────────────────────────────────────────── */

const CatalystTimeline = ({ catalysts, lk, C }) => {
  if (!catalysts || catalysts.length === 0) return null;
  const sorted = [...catalysts].sort((a,b) => new Date(a.date) - new Date(b.date));
  const lkk = lk || 'e';
  return (
    <div style={{position:'relative', paddingLeft:20}}>
      {/* Vertical rail */}
      <div style={{position:'absolute', left:6, top:6, bottom:6,
                   width:1, background:C.border}}></div>
      {sorted.map((cat, i) => {
        const color = cat.imp === 'HIGH' ? C.green : cat.imp === 'MED' ? C.gold : C.mid;
        const dateStr = cat.date
          ? new Date(cat.date).toLocaleDateString('en-US', {month:'short', year:'2-digit'})
          : cat.t || '';
        return (
          <div key={i} style={{position:'relative', marginBottom:i < sorted.length-1 ? 14 : 0}}>
            {/* Dot */}
            <div style={{
              position:'absolute', left:-17, top:3,
              width:8, height:8, borderRadius:'50%',
              background:color,
              boxShadow:`0 0 0 2px ${C.bg}, 0 0 0 3px ${color}40`,
            }}></div>
            <div style={{display:'flex', alignItems:'center', gap:6, marginBottom:3}}>
              <span style={{...S.tag(color), fontSize:8}}>{cat.imp}</span>
              <span style={{fontSize:9, color:C.mid, fontFamily:MONO}}>{dateStr}</span>
            </div>
            <div style={{fontSize:11, color:C.dark, lineHeight:1.55}}>{cat[lkk]}</div>
          </div>
        );
      })}
    </div>
  );
};

const RiskHeatMap = ({ risks, lk, C }) => {
  if (!risks || risks.length === 0) return null;
  const lkk = lk || 'e';
  const levels = ['HIGH','MED','LOW'];
  const cellColor = (p, imp) => {
    const score = (p==='HIGH'?3:p==='MED'?2:1) * (imp==='HIGH'?3:imp==='MED'?2:1);
    return score >= 6 ? C.red : score >= 3 ? C.gold : C.green;
  };
  const risksByCell = {};
  risks.forEach(r => {
    const k = `${r.p}_${r.imp}`;
    (risksByCell[k] = risksByCell[k] || []).push(r);
  });
  return (
    <div>
      {/* Header row */}
      <div style={{display:'grid', gridTemplateColumns:'52px repeat(3,1fr)', gap:2, marginBottom:2}}>
        <div style={{fontSize:8, color:C.mid, textAlign:'center', paddingBottom:3, fontWeight:700}}>P＼Impact</div>
        {['HIGH','MED','LOW'].map(imp => (
          <div key={imp} style={{fontSize:8, color:C.mid, textAlign:'center', fontWeight:700, letterSpacing:'0.04em'}}>{imp}</div>
        ))}
      </div>
      {/* 3×3 grid */}
      {levels.map(p => (
        <div key={p} style={{display:'grid', gridTemplateColumns:'52px repeat(3,1fr)', gap:2, marginBottom:2}}>
          <div style={{fontSize:8, color:C.mid, display:'flex', alignItems:'center',
                       justifyContent:'flex-end', paddingRight:6, fontWeight:700, letterSpacing:'0.04em'}}>{p}</div>
          {levels.map(imp => {
            const color = cellColor(p, imp);
            const cellRisks = risksByCell[`${p}_${imp}`] || [];
            return (
              <div key={imp} style={{
                background:`${color}0D`, border:`1px solid ${color}25`, borderRadius:3,
                padding:'5px 7px', minHeight:44,
              }}>
                {cellRisks.length === 0
                  ? <div style={{fontSize:8, color:`${color}40`, textAlign:'center', marginTop:6}}>—</div>
                  : cellRisks.map((r, i) => (
                    <div key={i} style={{fontSize:9, color:color, lineHeight:1.4, marginBottom:i<cellRisks.length-1?3:0}}>
                      {r[lkk]}
                    </div>
                  ))
                }
              </div>
            );
          })}
        </div>
      ))}
      <div style={{display:'flex', justifyContent:'space-between', marginTop:4}}>
        <span style={{fontSize:8, color:C.mid, opacity:0.6}}>← lower risk</span>
        <span style={{fontSize:8, color:C.mid, opacity:0.6}}>higher risk →</span>
      </div>
    </div>
  );
};

const FinCompare = ({ fin, peerAvg, C }) => {
  if (!fin || !peerAvg) return null;

  const parse = v => { const n = typeof v==='number'?v:parseFloat(v); return isNaN(n)?null:n; };
  const metrics = [
    {label:'P/E', stock:parse(fin.pe), peer:parse(peerAvg.pe), unit:''},
    {label:'EV/EBITDA', stock:parse(fin.ev_ebitda), peer:parse(peerAvg.ev_ebitda), unit:''},
    {label:'Gross Margin', stock:parse(fin.gm), peer:parse(peerAvg.gm), unit:'%'},
  ];

  return (
    <div style={{display:'grid', gridTemplateColumns:'repeat(3, 1fr)', gap:12, marginBottom:14}}>
      {metrics.map((m,i) => {
        const stockVal = m.stock;
        const peerVal = m.peer;
        const maxVal = Math.max(stockVal || 0, peerVal || 0) * 1.1 || 1;
        const stockW = stockVal != null ? (stockVal/maxVal)*100 : 0;
        const peerW = peerVal != null ? (peerVal/maxVal)*100 : 0;

        return (
          <div key={i} style={{padding:10, background:C.soft, borderRadius:6}}>
            <div style={{fontSize:11, fontWeight:600, color:C.dark, marginBottom:8}}>{m.label}</div>
            <div style={{marginBottom:6}}>
              <div style={{display:'flex', alignItems:'center', gap:4, marginBottom:4}}>
                <div style={{fontSize:9, color:C.mid, width:30}}>Stock</div>
                <div style={{flex:1, height:6, background:C.border, borderRadius:3, overflow:'hidden'}}>
                  <div style={{height:'100%', background:C.blue, width:`${stockW}%`}}></div>
                </div>
                <div style={{fontSize:10, fontWeight:600, color:C.dark, width:40, textAlign:'right'}}>{stockVal!=null?stockVal.toFixed(1):'N/M'}{stockVal!=null?m.unit:''}</div>
              </div>
              <div style={{display:'flex', alignItems:'center', gap:4}}>
                <div style={{fontSize:9, color:C.mid, width:30}}>Peer</div>
                <div style={{flex:1, height:6, background:C.border, borderRadius:3, overflow:'hidden'}}>
                  <div style={{height:'100%', background:C.gold, width:`${peerW}%`}}></div>
                </div>
                <div style={{fontSize:10, fontWeight:600, color:C.dark, width:40, textAlign:'right'}}>{peerVal!=null?peerVal.toFixed(1):'N/M'}{peerVal!=null?m.unit:''}</div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
};

/* ── MINI COMPONENTS ─────────────────────────────────────────────────────── */
const Tag = ({ text, c, C }) => <span style={S.tag(c)}>{text}</span>;
const EQR = ({ lvl, C }) => {
  const c = lvl==='HIGH'?C.green : lvl==='MED-HIGH'?C.blue : lvl==='MED'?C.gold : C.red;
  return <span style={{...S.tag(c), fontSize:9}}>EQR: {lvl}</span>;
};
const TI = ({ t, C }) => t==='up' ? <TrendingUp size={13} style={{color:C.green}} />
                   : t==='down' ? <TrendingDown size={13} style={{color:C.red}} />
                   : <Minus size={13} style={{color:C.mid}} />;
const Pill = ({ n, label, c, C }) => (
  <div style={{textAlign:'center', padding:'12px 16px', background:C.card,
               borderRadius:10, boxShadow:SHADOW_SM, border:`1px solid ${C.border}`}}>
    <div style={{fontSize:22, fontWeight:700, color:c, fontFamily:MONO}}>{n}</div>
    <div style={{fontSize:10, color:C.mid, marginTop:3}}>{label}</div>
  </div>
);

// Jason: Bloomberg/CIQ-style Card — terminal aesthetic with accent left-bar on header
const Card = ({ title, sub, open, onToggle, children, C }) => (
  <div style={{
    background: C.card,
    borderRadius: 10,
    marginBottom: 12,
    overflow: 'hidden',
    boxShadow: SHADOW,
    border: `1px solid ${C.border}`,
  }}>
    <div style={{
      ...S.cardHd,
      borderBottom: open !== false ? `1px solid ${C.border}` : 'none',
      cursor: onToggle ? 'pointer' : 'default',
      // Bloomberg: subtle left accent bar on card headers
      borderLeft: `3px solid ${C.orange || C.blue}`,
      paddingLeft: 13,
    }} onClick={onToggle}>
      <div>
        <div style={{fontSize:12, fontWeight:700, color:C.dark, letterSpacing:'0.01em',
                     textTransform:'uppercase', fontFamily:MONO}}>{title}</div>
        {sub && <div style={{fontSize:9, color:C.mid, marginTop:3, fontWeight:400,
                             letterSpacing:'0.01em', textTransform:'none',
                             fontFamily:"'Inter',system-ui,sans-serif"}}>{sub}</div>}
      </div>
      {onToggle && (
        <ChevronDown size={14} style={{
          color:C.mid, flexShrink:0,
          transform:open?'rotate(180deg)':'',
          transition:'transform .2s',
        }}/>
      )}
    </div>
    {open !== false && (
      <div style={{...S.cardBd, color:C.dark}}>{children}</div>
    )}
  </div>
);

// Jason: Bloomberg-style VPRing — orange for high-conviction, gradient track, grade label
const VPRing = ({ score, sz=90, C }) => {
  const r = sz * 0.40, circ = 2 * Math.PI * r, cx = sz / 2;
  // Bloomberg conviction colors: high = orange/green, mid = gold, low = red
  const c = score >= 75 ? (C.orange || C.green) : score >= 55 ? C.gold : score >= 40 ? C.mid : C.red;
  const filled = (score / 100) * circ;
  const label = score >= 75 ? 'HIGH' : score >= 55 ? 'MED' : 'LOW';
  return (
    <svg width={sz} height={sz} style={{flexShrink:0}}>
      {/* Track (dimmed) */}
      <circle cx={cx} cy={cx} r={r} fill="none" stroke={`${c}18`} strokeWidth={sz*0.07}/>
      {/* Background track */}
      <circle cx={cx} cy={cx} r={r} fill="none" stroke={`${c}10`} strokeWidth={sz*0.07}
        strokeDasharray={`${circ} 0`}/>
      {/* Progress arc */}
      <circle cx={cx} cy={cx} r={r} fill="none" stroke={c} strokeWidth={sz*0.07}
        strokeDasharray={`${filled} ${circ - filled}`}
        strokeLinecap="round"
        style={{transform:'rotate(-90deg)', transformOrigin:`${cx}px ${cx}px`,
                transition:'stroke-dasharray 0.6s cubic-bezier(.4,0,.2,1)',
                filter: score >= 75 ? `drop-shadow(0 0 ${sz*0.05}px ${c}80)` : 'none'}}/>
      {/* Score number */}
      <text x={cx} y={cx - sz*0.04} textAnchor="middle" dominantBaseline="middle"
        style={{fontSize:sz*0.28, fontWeight:900, fill:c, fontFamily:MONO}}>{score}</text>
      {/* Grade label */}
      <text x={cx} y={cx + sz*0.26} textAnchor="middle"
        style={{fontSize:sz*0.12, fontWeight:800, fill:c, opacity:0.85, fontFamily:MONO,
                letterSpacing:'0.08em', textTransform:'uppercase'}}>{label}</text>
    </svg>
  );
};

/* ── SCANNER TAB ────────────────────────────────────────────────────────── */
/* ── MACRO STRESS TEST COMPONENTS ────────────────────────────────────── */
function _returnColor(r, C) {
  if (r == null) return C.mid;
  if (r >=  0.03) return C.green;
  if (r <= -0.10) return C.red;
  if (r <  -0.04) return C.gold;
  return C.mid;
}

function _scenColor(colorKey, C) {
  const map = {
    danger:  { bg: `${C.red}15`,  text: C.red  },
    success: { bg: `${C.green}15`,text: C.green },
    warning: { bg: `${C.gold}15`, text: C.gold  },
    info:    { bg: `${C.blue}15`, text: C.blue  },
  };
  return map[colorKey] || map.info;
}

function _fmtPct(n, digits=1) {
  if (n == null) return '—';
  return `${n >= 0 ? '+' : ''}${(n * 100).toFixed(digits)}%`;
}

function FactorBar({ label, value, maxAbs=0.15, C }) {
  const width = Math.min(Math.abs(value || 0) / maxAbs * 100, 100);
  const color = (value || 0) >= 0 ? C.green : C.red;
  return (
    <div style={{display:'flex', alignItems:'center', gap:8, marginBottom:5}}>
      <span style={{width:70, fontSize:10, color:C.mid, flexShrink:0}}>{label}</span>
      <div style={{flex:1, height:5, background:`${C.border}`, borderRadius:3, overflow:'hidden', position:'relative'}}>
        <div style={{
          position:'absolute', height:'100%', width:`${width}%`,
          background:color, borderRadius:3,
          left: (value||0) >= 0 ? 0 : 'auto',
          right: (value||0) < 0  ? 0 : 'auto',
        }}></div>
      </div>
      <span style={{width:48, fontSize:10, textAlign:'right', color:_returnColor(value,C), flexShrink:0, fontFamily:'monospace'}}>
        {_fmtPct(value)}
      </span>
    </div>
  );
}

function MacroStressTest({ stressData, L, C }) {
  const [activeScenario, setActiveScenario] = useState(null);
  const [expandedStock,  setExpandedStock]  = useState(null);

  if (!stressData?.scenarios) return (
    <div style={{padding:'14px 16px', background:`${C.gold}08`, border:`1px solid ${C.gold}25`, borderRadius:8, fontSize:11, color:C.mid}}>
      {L('Stress test data not yet generated — run fetch_data.py','压力测试数据未生成，请运行 fetch_data.py')}
    </div>
  );

  const scenarioKeys = Object.keys(stressData.scenarios);
  const active = activeScenario ?? scenarioKeys[0];
  const scen   = stressData.scenarios[active];
  const tickers = stressData.portfolio_weights ? Object.keys(stressData.portfolio_weights) : [];

  return (
    <div>
      {/* Header row */}
      <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:12}}>
        <div style={{fontSize:12, fontWeight:700, color:C.dark}}>{L('Macro Stress Test','宏观压力测试')}</div>
        <div style={{fontSize:11, color:C.mid}}>
          {L('Expected return: ','预期收益: ')}
          <span style={{color:_returnColor(stressData.expected_portfolio_return, C), fontWeight:700}}>
            {_fmtPct(stressData.expected_portfolio_return)}
          </span>
        </div>
      </div>

      {/* Scenario tabs */}
      <div style={{display:'flex', gap:6, marginBottom:12, flexWrap:'wrap'}}>
        {scenarioKeys.map(key => {
          const s   = stressData.scenarios[key];
          const cfg = _scenColor(s.color, C);
          const isActive = key === active;
          return (
            <button key={key}
              onClick={() => { setActiveScenario(key); setExpandedStock(null); }}
              style={{
                padding:'5px 12px', fontSize:11, borderRadius:20, cursor:'pointer',
                border: isActive ? `1.5px solid ${cfg.text}` : `1px solid ${C.border}`,
                background: isActive ? cfg.bg : 'transparent',
                color: isActive ? cfg.text : C.mid,
              }}
            >
              {s.name}
              <span style={{marginLeft:5, opacity:0.65}}>
                {(s.probability * 100).toFixed(0)}%
              </span>
            </button>
          );
        })}
      </div>

      {/* Scenario description + shock values */}
      <div style={{padding:'10px 14px', background:C.soft, borderRadius:8, marginBottom:12}}>
        <div style={{fontSize:11, color:C.mid, marginBottom:8, lineHeight:1.6}}>{scen.description}</div>
        <div style={{display:'flex', gap:18, flexWrap:'wrap'}}>
          {[
            {label:'CNY/USD', val:scen.shocks.cny_usd,  mult:100, unit:'%',   positiveIsGood:true  },
            {label:'CN 10Y',  val:scen.shocks.cn_10y,   mult:100, unit:'bp',  positiveIsGood:false },
            {label:'US 10Y',  val:scen.shocks.us_10y,   mult:100, unit:'bp',  positiveIsGood:false },
            {label:'VIX',     val:scen.shocks.vix,      mult:1,   unit:'pts', positiveIsGood:false },
          ].map(({label, val, mult, unit, positiveIsGood}) => {
            const isPos  = val >= 0;
            const color  = (positiveIsGood ? isPos : !isPos) ? C.green : C.red;
            return (
              <div key={label}>
                <div style={{fontSize:9, color:C.mid, fontWeight:600}}>{label}</div>
                <div style={{fontSize:14, fontWeight:700, color, fontFamily:'monospace', marginTop:2}}>
                  {val >= 0 ? '+' : ''}{(val * mult).toFixed(1)}{unit}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Portfolio NAV impact — prominent */}
      <div style={{
        padding:'12px 18px', marginBottom:12,
        background:C.card, border:`1px solid ${C.border}`, borderRadius:10,
        display:'flex', justifyContent:'space-between', alignItems:'center',
      }}>
        <div style={{fontSize:12, color:C.mid}}>{L('Portfolio NAV impact','组合净值影响')}</div>
        <div style={{fontSize:28, fontWeight:800, color:_returnColor(scen.portfolio_return, C), fontFamily:'monospace'}}>
          {_fmtPct(scen.portfolio_return, 1)}
        </div>
      </div>

      {/* Per-stock breakdown */}
      <div style={{display:'flex', flexDirection:'column', gap:6}}>
        {tickers.map(ticker => {
          const imp    = scen.stock_impacts?.[ticker];
          const weight = stressData.portfolio_weights?.[ticker];
          if (!imp) return null;
          const isOpen  = expandedStock === ticker;
          const factors = imp.factors || {};
          return (
            <div key={ticker} style={{background:C.card, border:`1px solid ${C.border}`, borderRadius:8, overflow:'hidden'}}>
              {/* Collapsed row */}
              <div onClick={() => setExpandedStock(isOpen ? null : ticker)}
                style={{display:'flex', alignItems:'center', padding:'10px 14px', cursor:'pointer', gap:12}}>
                <span style={{fontFamily:'monospace', fontSize:11, color:C.mid, width:88, flexShrink:0}}>{ticker}</span>
                <span style={{fontSize:12, flex:1, color:C.dark}}>{imp.name}</span>
                <span style={{fontSize:10, color:C.mid}}>{((weight||0)*100).toFixed(0)}%</span>
                <span style={{fontSize:16, fontWeight:700, minWidth:60, textAlign:'right',
                              color:_returnColor(imp.total_return, C), fontFamily:'monospace'}}>
                  {_fmtPct(imp.total_return)}
                </span>
                <span style={{fontSize:10, color:C.mid, marginLeft:4}}>{isOpen ? '▲' : '▼'}</span>
              </div>

              {/* Expanded factor bars */}
              {isOpen && (
                <div style={{padding:'0 14px 12px', borderTop:`1px solid ${C.border}`}}>
                  <div style={{marginTop:10}}>
                    <FactorBar label="CNY/USD"  value={factors.cny_usd} C={C}/>
                    <FactorBar label="CN 10Y"   value={factors.cn_10y}  C={C}/>
                    <FactorBar label="US 10Y"   value={factors.us_10y}  C={C}/>
                    <FactorBar label="VIX"      value={factors.vix}     C={C}/>
                    {factors.sector_override !== 0 && (
                      <FactorBar label="Sector"  value={factors.sector_override} C={C}/>
                    )}
                  </div>
                  <div style={{marginTop:8, fontSize:10, color:C.mid}}>
                    {L('Weighted NAV impact: ','加权净值影响: ')}
                    <span style={{color:_returnColor(imp.total_return * (weight||0), C), fontWeight:700}}>
                      {_fmtPct(imp.total_return * (weight||0))}
                    </span>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* All-scenarios matrix */}
      <div style={{marginTop:16}}>
        <div style={{fontSize:9, fontWeight:700, color:C.mid, letterSpacing:'0.06em', textTransform:'uppercase', marginBottom:8}}>
          {L('All scenarios — portfolio return','全场景 — 组合收益')}
        </div>
        <div style={{display:'grid', gridTemplateColumns:`repeat(${scenarioKeys.length}, 1fr)`, gap:6}}>
          {scenarioKeys.map(key => {
            const s   = stressData.scenarios[key];
            const cfg = _scenColor(s.color, C);
            const isActive = key === active;
            return (
              <div key={key} onClick={() => setActiveScenario(key)}
                style={{
                  padding:'8px 6px', borderRadius:8, cursor:'pointer', textAlign:'center',
                  background: isActive ? cfg.bg : C.soft,
                  border: isActive ? `1px solid ${cfg.text}` : `1px solid ${C.border}`,
                }}
              >
                <div style={{fontSize:9, color:C.mid, marginBottom:4}}>
                  {s.name.split(' ')[0]}
                </div>
                <div style={{fontSize:15, fontWeight:700, color:_returnColor(s.portfolio_return, C), fontFamily:'monospace'}}>
                  {_fmtPct(s.portfolio_return, 1)}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div style={{marginTop:10, fontSize:9, color:C.mid, lineHeight:1.5}}>
        ⚠ {L('Sensitivities are first-principles estimates, not historical regressions. Recalibrate after 60+ days of live data.',
             '敏感度系数为基本面逻辑估算，非历史回归。积累60天以上真实数据后应重新校准。')}
      </div>
    </div>
  );
}

/* ── HELPERS ─────────────────────────────────────────────────────────────── */
function timeAgo(isoStr) {
  const diff = Math.floor((Date.now() - new Date(isoStr)) / 1000);
  if (diff < 60)  return `${diff}s`;
  if (diff < 3600) return `${Math.floor(diff/60)}m`;
  if (diff < 86400) return `${Math.floor(diff/3600)}h`;
  return `${Math.floor(diff/86400)}d`;
}

/* ── NEWS PANEL ──────────────────────────────────────────────────────────── */
const SOURCE_STYLE = {
  'Financial Times':        { short:'FT',      bg:'#FFF1E5', color:'#C9400A' },
  'Wall Street Journal':    { short:'WSJ',     bg:'#1A1A1A', color:'#fff'    },
  'Bloomberg':              { short:'BBG',     bg:'#1A1A1A', color:'#FF6F0F' },
  'Reuters':                { short:'Reuters', bg:'#FF6F0F', color:'#fff'    },
  'CNBC':                   { short:'CNBC',    bg:'#0F0F0F', color:'#FFD700' },
  'The Economist':          { short:'Econ',    bg:'#E3120B', color:'#fff'    },
  'South China Morning Post':{ short:'SCMP',   bg:'#003366', color:'#fff'    },
  'Caixin Global':          { short:'Caixin',  bg:'#0066CC', color:'#fff'    },
  'Nikkei Asia':            { short:'Nikkei',  bg:'#D82B2B', color:'#fff'    },
  'MarketWatch':            { short:'MW',      bg:'#16C784', color:'#fff'    },
};

function SourceBadge({ source, C }) {
  const style = SOURCE_STYLE[source] || { short: source?.split(' ')[0] || '?', bg: C.mid, color:'#fff' };
  return (
    <span style={{
      fontSize:8, fontWeight:700, padding:'1px 5px', borderRadius:3,
      background: style.bg, color: style.color, flexShrink:0,
      letterSpacing:'0.03em',
    }}>{style.short}</span>
  );
}

/* ── PRICE CHART ─────────────────────────────────────────────────────────── */

// Normalize any ticker to Yahoo Finance 4-digit HK format
function toYahooTicker(ticker) {
  if (!ticker) return ticker;
  if (ticker.endsWith('.HK')) {
    const code    = ticker.slice(0, -3);           // strip ".HK"
    const digits  = code.replace(/^0+/, '') || '0'; // remove leading zeros
    return digits.padStart(4, '0') + '.HK';        // pad to 4 digits
  }
  return ticker;
}

const API_BASE = 'https://equity-research-ten.vercel.app';
const RANGES   = ['1d', '5d', '1mo', '3mo', '1y'];
const RANGE_LABELS = { '1d':'1D', '5d':'5D', '1mo':'1M', '3mo':'3M', '1y':'1Y' };
const INTERVALS = ['1m', '5m', '15m', '30m', '60m', '1d', '1w', '1mo'];
const INTERVAL_LABELS = { '1m':'1分', '5m':'5分', '15m':'15分', '30m':'30分', '60m':'60分', '1d':'日', '1w':'周', '1mo':'月' };
const MINUTE_INTERVALS = new Set(['1m', '5m', '15m', '30m', '60m']);

function PriceChart({ ticker, C, L, lk }) {
  const [range,    setRange]    = useState('1mo');
  const [chartData, setChart]   = useState(null);
  const [meta,     setMeta]     = useState(null);
  const [loading,  setLoading]  = useState(false);
  const [error,    setError]    = useState(null);
  const [lastFetch,setLastFetch]= useState(null);
  const [interval, setIntervalState] = useState('1d');
  const [viewMode, setViewMode] = useState('kline'); // 'kline' | 'fenshi'
  const [tierLocked, setTierLocked] = useState(null);
  const [indicators, setIndicators] = useState({ ma5: true, ma10: true, ma20: true, ma60: false, boll: true, macd: true, kdj: false, rsi: false });
  const [subplotLayout, setSubplotLayout] = useState(() => {
    try {
      const saved = localStorage.getItem('kline_subplot_layout');
      return saved === 'tabs' ? 'tabs' : 'stack';
    } catch { return 'stack'; }
  });
  const [volumeConvention, setVolumeConvention] = useState(() => {
    try {
      const saved = localStorage.getItem('kline_volume_convention');
      return saved === 'us' ? 'us' : 'cn';
    } catch { return 'cn'; }
  });
  const [activeSubplotTab, setActiveSubplotTab] = useState('macd');
  const timerRef = useRef(null);

  const yTicker = toYahooTicker(ticker);
  const toggleInd = (key) => setIndicators(prev => ({ ...prev, [key]: !prev[key] }));

  const fetchChart = async (rng = range, iv = interval) => {
    if (!yTicker) return;
    setLoading(true); setError(null);
    try {
      const res  = await fetch(`${API_BASE}/api/price-chart?ticker=${encodeURIComponent(yTicker)}&range=${rng}&interval=${iv}`);
      const data = await res.json();
      if (!res.ok || !data.success) throw new Error(data.error || 'Fetch failed');
      if (data._status === 'tier_locked') {
        setTierLocked({
          need_tier: data._need_tier,
          attempted_endpoint: data._attempted_endpoint,
          msg: data._tushare_msg,
        });
        setChart([]);
        setMeta(prev => prev || {
          current:      data.current,
          change_pct:   data.change_pct,
          day_high:     data.day_high,
          day_low:      data.day_low,
          volume:       data.volume,
          prev_close:   data.prev_close,
          currency:     data.currency,
          market_state: data.market_state,
          name:         data.name,
          exchange:     data.exchange,
        });
      } else {
        setTierLocked(null);
        setChart(data.data || []);
        setMeta({
          current:      data.current,
          change_pct:   data.change_pct,
          day_high:     data.day_high,
          day_low:      data.day_low,
          volume:       data.volume,
          prev_close:   data.prev_close,
          currency:     data.currency,
          market_state: data.market_state,
          name:         data.name,
          exchange:     data.exchange,
        });
      }
      setLastFetch(new Date());
    } catch (e) {
      setError(e.message);
      setTierLocked(null);
    } finally {
      setLoading(false);
    }
  };

  // Fetch on ticker/range/interval change
  useEffect(() => {
    fetchChart(range, interval);
    if (timerRef.current) clearInterval(timerRef.current);
    if (MINUTE_INTERVALS.has(interval)) {
      const refreshMs = interval === '1m' ? 30000 : 60000;
      timerRef.current = setInterval(() => fetchChart(range, interval), refreshMs);
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [ticker, range, interval]); // eslint-disable-line

  useEffect(() => {
    try { localStorage.setItem('kline_subplot_layout', subplotLayout); } catch {}
  }, [subplotLayout]);

  useEffect(() => {
    try { localStorage.setItem('kline_volume_convention', volumeConvention); } catch {}
  }, [volumeConvention]);

  const ind = React.useMemo(() => {
    if (!chartData || chartData.length === 0) return null;
    const closes = chartData.map(d => d.close);
    const highs  = chartData.map(d => d.high);
    const lows   = chartData.map(d => d.low);
    return {
      ma5: ma(closes, 5),
      ma10: ma(closes, 10),
      ma20: ma(closes, 20),
      ma60: ma(closes, 60),
      boll: bollinger(closes, 20, 2),
      macd: macd(closes, 12, 26, 9),
      kdj: kdj(highs, lows, closes, 9),
      rsi: rsi(closes, 14),
    };
  }, [chartData]);

  const chartDataWithInd = React.useMemo(() => {
    if (!chartData || !ind) return chartData || [];
    return chartData.map((d, i) => ({
      ...d,
      ma5: ind.ma5[i],
      ma10: ind.ma10[i],
      ma20: ind.ma20[i],
      ma60: ind.ma60[i],
      bollUpper: ind.boll.upper[i],
      bollMid: ind.boll.mid[i],
      bollLower: ind.boll.lower[i],
      macdLine: ind.macd.line[i],
      macdSignal: ind.macd.signal[i],
      macdHist: ind.macd.hist[i],
      kdjK: ind.kdj.k[i],
      kdjD: ind.kdj.d[i],
      kdjJ: ind.kdj.j[i],
      rsi: ind.rsi[i],
    }));
  }, [chartData, ind]);

  const avgLine = React.useMemo(() => {
    if (!chartData || chartData.length === 0) return [];
    let sum = 0, count = 0;
    return chartData.map(d => {
      if (d.close == null) return null;
      sum += d.close; count += 1;
      return sum / count;
    });
  }, [chartData]);

  const chartDataWithFenshi = React.useMemo(() => {
    if (!chartData || chartData.length === 0) return [];
    let prevClose = meta?.prev_close;
    return chartData.map((d, i) => {
      const ref = i === 0 ? prevClose : chartData[i-1].close;
      const upTick = d.close != null && ref != null ? d.close >= ref : null;
      return { ...d, avgPrice: avgLine[i], upTick };
    });
  }, [chartData, avgLine, meta]);

  // Derived chart metrics
  const prices   = (chartData || []).map(d => d.close);
  const minPrice = prices.length ? Math.min(...prices) : 0;
  const maxPrice = prices.length ? Math.max(...prices) : 0;
  const priceRange = maxPrice - minPrice;
  const domainLo = +(minPrice - priceRange * 0.05).toFixed(4);
  const domainHi = +(maxPrice + priceRange * 0.05).toFixed(4);

  const isUp  = (meta?.change_pct ?? 0) >= 0;
  const lineC = isUp ? C.green : C.red;
  const volumeUpColor = volumeConvention === 'cn' ? C.red : C.green;
  const volumeDownColor = volumeConvention === 'cn' ? C.green : C.red;
  const ccy   = meta?.currency === 'HKD' ? 'HK$' : meta?.currency === 'CNY' ? '¥' : (meta?.currency || '');

  // X-axis time formatter
  const fmtX = (ts) => {
    const d = new Date(ts);
    if (range === '1d')  return d.toLocaleTimeString('en-US', { hour:'2-digit', minute:'2-digit', hour12:false });
    if (range === '5d')  return d.toLocaleDateString('en-US', { weekday:'short' }) + ' ' + d.toLocaleTimeString('en-US', { hour:'2-digit', minute:'2-digit', hour12:false });
    if (range === '1y')  return d.toLocaleDateString('en-US', { month:'short', year:'2-digit' });
    return d.toLocaleDateString('en-US', { month:'short', day:'numeric' });
  };

  const fmtVol = (v) => {
    if (v == null) return '—';
    if (v >= 1e8)  return (v/1e8).toFixed(1)  + '亿';
    if (v >= 1e6)  return (v/1e6).toFixed(1)  + 'M';
    if (v >= 1e4)  return (v/1e4).toFixed(1)  + 'w';
    return v.toLocaleString();
  };

  const MACDSubplot = ({ data }) => (
    <ResponsiveContainer width='100%' height={70}>
      <ComposedChart data={data} margin={{top:0, right:16, bottom:4, left:4}}>
        <YAxis tick={{fontSize:8, fill:C.mid}} axisLine={false} tickLine={false} width={50}/>
        <XAxis dataKey='time' hide/>
        <ReferenceLine y={0} stroke={C.mid} strokeDasharray='3 3' strokeWidth={1}/>
        <Bar dataKey='macdHist' isAnimationActive={false}
          shape={(props) => {
            if (props.height == null || props.width == null) return null;
            const fill = props.payload.macdHist >= 0 ? C.green : C.red;
            return <rect x={props.x} y={props.y} width={props.width} height={props.height} fill={fill} opacity={0.6}/>;
          }}/>
        <Line type='monotone' dataKey='macdLine'   stroke={C.blue} strokeWidth={1} dot={false} isAnimationActive={false} connectNulls={false}/>
        <Line type='monotone' dataKey='macdSignal' stroke={C.gold} strokeWidth={1} dot={false} isAnimationActive={false} connectNulls={false}/>
        <Tooltip contentStyle={{background:C.card, border:`1px solid ${C.border}`, borderRadius:6, fontSize:10}}
          formatter={(val, name) => [val != null ? Number(val).toFixed(3) : '—', `MACD ${name.replace('macd','')}`]}/>
      </ComposedChart>
    </ResponsiveContainer>
  );

  const KDJSubplot = ({ data }) => (
    <ResponsiveContainer width='100%' height={70}>
      <LineChart data={data} margin={{top:0, right:16, bottom:4, left:4}}>
        <YAxis tick={{fontSize:8, fill:C.mid}} axisLine={false} tickLine={false} width={50} domain={[0, 100]}/>
        <XAxis dataKey='time' hide/>
        <ReferenceLine y={50} stroke={C.mid} strokeDasharray='3 3' strokeWidth={1}/>
        <Line type='monotone' dataKey='kdjK' stroke={C.blue} strokeWidth={1} dot={false} isAnimationActive={false} connectNulls={false} name='K'/>
        <Line type='monotone' dataKey='kdjD' stroke={C.gold} strokeWidth={1} dot={false} isAnimationActive={false} connectNulls={false} name='D'/>
        <Line type='monotone' dataKey='kdjJ' stroke={C.red}  strokeWidth={1} dot={false} isAnimationActive={false} connectNulls={false} name='J'/>
        <Tooltip contentStyle={{background:C.card, border:`1px solid ${C.border}`, borderRadius:6, fontSize:10}}
          formatter={(val, name) => [val != null ? Number(val).toFixed(2) : '—', `KDJ-${name}`]}/>
      </LineChart>
    </ResponsiveContainer>
  );

  const RSISubplot = ({ data }) => (
    <ResponsiveContainer width='100%' height={70}>
      <LineChart data={data} margin={{top:0, right:16, bottom:4, left:4}}>
        <YAxis tick={{fontSize:8, fill:C.mid}} axisLine={false} tickLine={false} width={50} domain={[0, 100]}/>
        <XAxis dataKey='time' hide/>
        <ReferenceLine y={70} stroke={C.red} strokeDasharray='3 3' strokeWidth={1}/>
        <ReferenceLine y={30} stroke={C.green} strokeDasharray='3 3' strokeWidth={1}/>
        <Line type='monotone' dataKey='rsi' stroke={C.blue} strokeWidth={1.5} dot={false} isAnimationActive={false} connectNulls={false}/>
        <Tooltip contentStyle={{background:C.card, border:`1px solid ${C.border}`, borderRadius:6, fontSize:10}}
          formatter={(val) => [val != null ? Number(val).toFixed(2) : '—', 'RSI(14)']}/>
      </LineChart>
    </ResponsiveContainer>
  );

  return (
    <div style={{ background: C.card, borderRadius: 10, border: `1px solid ${C.border}`, overflow:'hidden', marginBottom: 12 }}>
      {/* Header */}
      <div style={{ padding: '12px 16px 8px', borderBottom: `1px solid ${C.border}` }}>
        <div style={{ display:'flex', alignItems:'flex-start', justifyContent:'space-between', gap:12 }}>
          {/* Price block */}
          <div>
            {meta ? (
              <>
                <div style={{ display:'flex', alignItems:'baseline', gap:8 }}>
                  <span style={{ fontSize:22, fontWeight:800, color:C.dark, fontFamily:'JetBrains Mono,monospace' }}>
                    {ccy}{meta.current != null ? meta.current.toFixed(meta.current >= 100 ? 2 : 3) : '—'}
                  </span>
                  <span style={{ fontSize:13, fontWeight:700, color: isUp ? C.green : C.red }}>
                    {meta.change_pct != null ? `${isUp?'+':''}${meta.change_pct.toFixed(2)}%` : '—'}
                  </span>
                  {/* Market state badge */}
                  {meta.market_state && meta.market_state !== 'REGULAR' && (
                    <span style={{ fontSize:8, padding:'2px 6px', borderRadius:4, background:`${C.gold}20`, color:C.gold, fontWeight:700 }}>
                      {meta.market_state === 'CLOSED' ? L('CLOSED','已收盘') : meta.market_state}
                    </span>
                  )}
                </div>
                <div style={{ display:'flex', gap:14, marginTop:4 }}>
                  {[
                    { label:'H', val: meta.day_high  != null ? `${ccy}${meta.day_high.toFixed(2)}`  : '—' },
                    { label:'L', val: meta.day_low   != null ? `${ccy}${meta.day_low.toFixed(2)}`   : '—' },
                    { label:L('Vol','量'), val: fmtVol(meta.volume) },
                    { label:L('Prev','昨收'), val: meta.prev_close != null ? `${ccy}${meta.prev_close.toFixed(2)}` : '—' },
                  ].map(({ label, val }) => (
                    <div key={label}>
                      <span style={{ fontSize:9, color:C.mid }}>{label} </span>
                      <span style={{ fontSize:10, fontWeight:700, color:C.dark, fontFamily:'JetBrains Mono,monospace' }}>{val}</span>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <div style={{ fontSize:11, color:C.mid }}>
                {loading ? L('Loading…','加载中…') : error ? L('Price unavailable','无法获取价格') : ''}
              </div>
            )}
          </div>

          {/* Range selector + refresh */}
          <div style={{ display:'flex', flexDirection:'column', alignItems:'flex-end', gap:6 }}>
            <div style={{display:'flex', gap:6, flexWrap:'wrap', justifyContent:'flex-end', alignItems:'center'}}>
              <button onClick={() => {
                if (viewMode === 'fenshi') { setViewMode('kline'); }
                else { setViewMode('fenshi'); setIntervalState('1m'); setRange('1d'); }
              }} style={{
                padding:'2px 10px', fontSize:9, fontWeight:700, border:`1px solid ${viewMode === 'fenshi' ? C.red : C.border}`,
                borderRadius:4, cursor:'pointer',
                background: viewMode === 'fenshi' ? C.red : 'transparent',
                color: viewMode === 'fenshi' ? '#fff' : C.mid,
                marginRight:8,
              }}>{L('Intraday','分时')}</button>
              {INTERVALS.map(iv => (
                <button key={iv} onClick={() => { setIntervalState(iv); if (viewMode !== 'kline') setViewMode('kline'); }} style={{
                  padding:'2px 8px', fontSize:9, fontWeight:600, border:'none',
                  borderRadius:4, cursor:'pointer',
                  background: interval === iv ? C.gold : C.soft,
                  color:      interval === iv ? '#fff'   : C.mid,
                  transition:'all .15s',
                }}>
                  {INTERVAL_LABELS[iv]}
                </button>
              ))}
            </div>
            <div style={{ display:'flex', gap:3 }}>
              {RANGES.map(r => (
                <button key={r} onClick={() => { setRange(r); if (viewMode !== 'kline') setViewMode('kline'); }} style={{
                  padding:'3px 9px', fontSize:10, fontWeight:700, border:'none',
                  borderRadius:5, cursor:'pointer',
                  background: range === r ? C.blue : C.soft,
                  color:      range === r ? '#fff'  : C.mid,
                  transition:'all .15s',
                }}>
                  {RANGE_LABELS[r]}
                </button>
              ))}
              <button onClick={() => fetchChart(range)} disabled={loading} title={L('Refresh','刷新')} style={{
                padding:'3px 7px', fontSize:10, border:'none', borderRadius:5,
                background: C.soft, color: C.mid, cursor: loading ? 'default' : 'pointer',
              }}>
                {loading ? '…' : '↻'}
              </button>
            </div>
            {lastFetch && (
              <span style={{ fontSize:8, color:C.mid }}>
                {L('Updated','更新') + ' ' + lastFetch.toLocaleTimeString('en-US', { hour:'2-digit', minute:'2-digit' })}
                {MINUTE_INTERVALS.has(interval) && <span style={{ color:C.green }}> · {L('auto','自动')}</span>}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Chart */}
      <div style={{ padding:'8px 0 0' }}>
        {error && !chartData && (
          <div style={{ textAlign:'center', padding:'28px 0', fontSize:11, color:C.mid }}>
            {error}
          </div>
        )}
        {tierLocked && (
          <div style={{ padding:'14px 16px', marginBottom:8, borderRadius:8, background:`${C.gold}14`, border:`1px solid ${C.gold}`, color:C.dark, fontSize:11, lineHeight:1.6 }}>
            <div style={{ fontWeight:700, marginBottom:4, color:C.gold }}>
              {L('🔒 Upgrade required','🔒 需升级套餐')}
            </div>
            <div>
              {L(`This ${INTERVAL_LABELS[interval]} interval requires Tushare ${tierLocked.need_tier}-tier (currently 6000-tier).`,
                 `当前 ${INTERVAL_LABELS[interval]} 周期需要 Tushare ${tierLocked.need_tier} 积分套餐 (当前 6000 积分)。`)}
            </div>
            {tierLocked.msg && (
              <div style={{ marginTop:6, fontSize:10, color:C.mid, fontFamily:MONO }}>
                <span>API: {tierLocked.attempted_endpoint || '?'}</span>
                <span style={{ marginLeft:10 }}>Msg: {tierLocked.msg}</span>
              </div>
            )}
          </div>
        )}
        {!tierLocked && !error && chartData && chartData.length === 0 && !loading && (
          <div style={{ textAlign:'center', padding:'28px 0', fontSize:11, color:C.mid }}>
            {L('No chart data for this range','该时间段暂无数据')}
          </div>
        )}
        {!chartData && loading && (
          <div style={{ height:180, display:'flex', alignItems:'center', justifyContent:'center', color:C.mid, fontSize:11 }}>
            {L('Loading chart…','图表加载中…')}
          </div>
        )}
        {viewMode === 'kline' && chartDataWithInd && chartDataWithInd.length > 0 && (
          <div style={{display:'flex', flexWrap:'wrap', gap:4, padding:'6px 0', borderBottom:`1px solid ${C.border}`, marginBottom:6, fontSize:9}}>
            {[
              { key:'ma5',  label:'MA5',  color:C.gold },
              { key:'ma10', label:'MA10', color:C.blue },
              { key:'ma20', label:'MA20', color:C.green },
              { key:'ma60', label:'MA60', color:C.red },
              { key:'boll', label:'BOLL', color:C.dark },
              { key:'macd', label:'MACD', color:C.blue },
              { key:'kdj',  label:'KDJ',  color:C.gold },
              { key:'rsi',  label:'RSI',  color:C.blue },
            ].map(({key, label, color}) => (
              <button key={key} onClick={() => toggleInd(key)} style={{
                padding:'2px 8px', fontSize:9, fontWeight:600, border:`1px solid ${indicators[key] ? color : C.border}`,
                borderRadius:4, cursor:'pointer',
                background: indicators[key] ? `${color}14` : 'transparent',
                color: indicators[key] ? color : C.mid,
                transition:'all .15s',
              }}>{label}</button>
            ))}
            <div style={{borderLeft:`1px solid ${C.border}`, height:14, alignSelf:'center', margin:'0 4px'}}></div>
            <button onClick={() => setSubplotLayout(prev => prev === 'stack' ? 'tabs' : 'stack')} style={{
              padding:'2px 8px', fontSize:9, fontWeight:600, border:`1px solid ${C.border}`,
              borderRadius:4, cursor:'pointer', background:'transparent', color:C.mid,
            }} title={subplotLayout === 'stack' ? L('Switch to tab layout','切换为标签页布局') : L('Switch to stack layout','切换为堆叠布局')}>
              {subplotLayout === 'stack' ? '⊞ ' + L('Tabs','标签') : '☰ ' + L('Stack','堆叠')}
            </button>
            <button onClick={() => setVolumeConvention(prev => prev === 'cn' ? 'us' : 'cn')} style={{
              padding:'2px 8px', fontSize:9, fontWeight:600, border:`1px solid ${C.border}`,
              borderRadius:4, cursor:'pointer', background:'transparent', color:C.mid,
            }} title={volumeConvention === 'cn' ? L('Switch to Western color (green=up)','切换为美式涨绿跌红') : L('Switch to Chinese color (red=up)','切换为中式红涨绿跌')}>
              {volumeConvention === 'cn' ? '红涨' : 'GR↑'}
            </button>
          </div>
        )}
        {viewMode === 'fenshi' && chartDataWithFenshi.length > 0 && (
          <ResponsiveContainer width='100%' height={180}>
            <LineChart data={chartDataWithFenshi} margin={{top:4, right:16, bottom:0, left:4}}>
              <XAxis dataKey='time' tickFormatter={fmtX} tick={{fontSize:9, fill:C.mid}} axisLine={false} tickLine={false} interval='preserveStartEnd' minTickGap={50}/>
              <YAxis tick={{fontSize:9, fill:C.mid}} axisLine={false} tickLine={false} width={50} domain={['dataMin', 'dataMax']}
                tickFormatter={v => `${ccy}${v >= 1000 ? (v/1000).toFixed(1)+'k' : v.toFixed(v>=100?0:2)}`}/>
              {meta?.prev_close && <ReferenceLine y={meta.prev_close} stroke={C.mid} strokeDasharray='3 3' strokeWidth={1}/>}
              <Line type='monotone' dataKey='close' stroke={C.dark} strokeWidth={1.5} dot={false} isAnimationActive={false} name={L('Price','价')}/>
              <Line type='monotone' dataKey='avgPrice' stroke={C.gold} strokeWidth={1} dot={false} isAnimationActive={false} name={L('Avg','均')}/>
              <Tooltip contentStyle={{background:C.card, border:`1px solid ${C.border}`, borderRadius:6, fontSize:11}}
                labelFormatter={ts => new Date(ts).toLocaleTimeString('zh-CN', {hour:'2-digit', minute:'2-digit'})}
                formatter={(val) => [val != null ? `${ccy}${Number(val).toFixed(2)}` : '—']}/>
            </LineChart>
          </ResponsiveContainer>
        )}
        {viewMode === 'kline' && !error && chartDataWithInd && chartDataWithInd.length > 0 && (
          <ResponsiveContainer width='100%' height={180}>
            <LineChart data={chartDataWithInd} margin={{ top:4, right:16, bottom:0, left:4 }}>
              <defs>
                <linearGradient id={`grad_${ticker.replace(/\./g,'_')}`} x1='0' y1='0' x2='0' y2='1'>
                  <stop offset='5%'  stopColor={lineC} stopOpacity={0.25}/>
                  <stop offset='95%' stopColor={lineC} stopOpacity={0}/>
                </linearGradient>
              </defs>
              <XAxis
                dataKey='time'
                tickFormatter={fmtX}
                tick={{ fontSize:9, fill:C.mid }}
                axisLine={false} tickLine={false}
                interval='preserveStartEnd'
                minTickGap={50}
              />
              <YAxis
                domain={[domainLo, domainHi]}
                tick={{ fontSize:9, fill:C.mid }}
                axisLine={false} tickLine={false}
                width={50}
                tickFormatter={v => `${ccy}${v >= 1000 ? (v/1000).toFixed(1)+'k' : v.toFixed(v>=100?0:2)}`}
              />
              <Tooltip
                contentStyle={{ background:C.card, border:`1px solid ${C.border}`, borderRadius:6, fontSize:11 }}
                labelFormatter={ts => new Date(ts).toLocaleString('en-US', { month:'short', day:'numeric', hour:'2-digit', minute:'2-digit' })}
                formatter={(val, name) => [`${ccy}${Number(val).toFixed(4)}`, L('Price','价格')]}
              />
              <ReferenceLine y={meta?.prev_close} stroke={C.mid} strokeDasharray='3 3' strokeWidth={1}/>
              {indicators.ma5 && <Line type='monotone' dataKey='ma5' stroke={C.gold} strokeWidth={1} dot={false} isAnimationActive={false} connectNulls={false}/>}
              {indicators.ma10 && <Line type='monotone' dataKey='ma10' stroke={C.blue} strokeWidth={1} dot={false} isAnimationActive={false} connectNulls={false}/>}
              {indicators.ma20 && <Line type='monotone' dataKey='ma20' stroke={C.green} strokeWidth={1} dot={false} isAnimationActive={false} connectNulls={false}/>}
              {indicators.ma60 && <Line type='monotone' dataKey='ma60' stroke={C.red} strokeWidth={1} dot={false} isAnimationActive={false} connectNulls={false}/>}
              {indicators.boll && (<>
                <Line type='monotone' dataKey='bollUpper' stroke={C.mid} strokeWidth={1} strokeDasharray='3 3' dot={false} isAnimationActive={false} connectNulls={false}/>
                <Line type='monotone' dataKey='bollMid'   stroke={C.dark} strokeWidth={1} dot={false} isAnimationActive={false} connectNulls={false}/>
                <Line type='monotone' dataKey='bollLower' stroke={C.mid} strokeWidth={1} strokeDasharray='3 3' dot={false} isAnimationActive={false} connectNulls={false}/>
              </>)}
              <Line
                type='monotone' dataKey='close'
                stroke={lineC} strokeWidth={1.5}
                dot={false} activeDot={{ r:3, fill:lineC }}
              />
            </LineChart>
          </ResponsiveContainer>
        )}

        {/* Volume bar strip */}
        {chartDataWithInd && chartDataWithInd.length > 0 && (
          <ResponsiveContainer width='100%' height={40}>
            <BarChart data={viewMode === 'fenshi' ? chartDataWithFenshi : chartDataWithInd} margin={{ top:0, right:16, bottom:4, left:4 }}>
              {/* K-line mode uses overall lineC; 分时 mode uses tick-by-tick convention. */}
              {viewMode === 'fenshi'
                ? <Bar dataKey='volume' isAnimationActive={false} shape={(props) => {
                    if (props.height == null || props.width == null) return null;
                    const fill = props.payload.upTick === null ? C.mid : props.payload.upTick ? volumeUpColor : volumeDownColor;
                    return <rect x={props.x} y={props.y} width={props.width} height={props.height} fill={fill} opacity={0.5}/>;
                  }}/>
                : <Bar dataKey='volume' fill={lineC} opacity={0.35} radius={0}/>
              }
              <YAxis hide domain={['auto','auto']}/>
              <XAxis dataKey='time' hide/>
            </BarChart>
          </ResponsiveContainer>
        )}
        {viewMode === 'kline' && chartDataWithInd && chartDataWithInd.length > 0 && (
          subplotLayout === 'stack' ? (
            <>
              {indicators.macd && <MACDSubplot data={chartDataWithInd}/>}
              {indicators.kdj  && <KDJSubplot data={chartDataWithInd}/>}
              {indicators.rsi  && <RSISubplot data={chartDataWithInd}/>}
            </>
          ) : (
            (() => {
              const enabledTabs = [
                indicators.macd && {key:'macd', label:'MACD'},
                indicators.kdj  && {key:'kdj',  label:'KDJ'},
                indicators.rsi  && {key:'rsi',  label:'RSI'},
              ].filter(Boolean);
              if (enabledTabs.length === 0) return null;
              const fallbackTab = enabledTabs[0].key;
              const currentTab = enabledTabs.some(t => t.key === activeSubplotTab) ? activeSubplotTab : fallbackTab;
              return (
                <>
                  <div style={{display:'flex', gap:4, padding:'4px 0', borderTop:`1px solid ${C.border}`, fontSize:9}}>
                    {enabledTabs.map(t => (
                      <button key={t.key} onClick={() => setActiveSubplotTab(t.key)} style={{
                        padding:'2px 10px', fontSize:9, fontWeight:600,
                        border:`1px solid ${currentTab === t.key ? C.blue : C.border}`,
                        borderRadius:4, cursor:'pointer',
                        background: currentTab === t.key ? `${C.blue}14` : 'transparent',
                        color: currentTab === t.key ? C.blue : C.mid,
                      }}>{t.label}</button>
                    ))}
                  </div>
                  {currentTab === 'macd' && <MACDSubplot data={chartDataWithInd}/>}
                  {currentTab === 'kdj'  && <KDJSubplot data={chartDataWithInd}/>}
                  {currentTab === 'rsi'  && <RSISubplot data={chartDataWithInd}/>}
                </>
              );
            })()
          )
        )}
      </div>
    </div>
  );
}

function ArticleRow({ a, onOpenArticle, accent, C, L, lk, translation }) {
  const [hov, setHov] = useState(false);

  // Display logic: Chinese mode → show translated title; English mode → show original
  const showChinese   = lk === 'z';
  const isTranslating = showChinese && translation?.loading;
  const zhTitle       = showChinese && translation?.zh;
  const displayTitle  = zhTitle || a.title;

  return (
    <div
      onClick={() => onOpenArticle(a)}
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      style={{
        padding:'9px 12px', borderRadius:6, cursor:'pointer',
        background: hov ? `${C.blue}0D` : 'transparent',
        borderLeft:`2px solid ${accent}`,
        transition:'background .1s',
      }}
    >
      <div style={{...S.row, justifyContent:'space-between', gap:8, alignItems:'flex-start'}}>
        <div style={{flex:1, minWidth:0}}>
          {/* Tag + source row */}
          <div style={{...S.row, gap:5, marginBottom:4, flexWrap:'wrap'}}>
            {a.tag && (
              <span style={{
                fontSize:8, fontWeight:700, letterSpacing:'0.04em',
                color: accent === '#D08000' ? '#92600C' : '#fff',
                background: accent, padding:'1px 6px', borderRadius:3, flexShrink:0,
              }}>{a.tag || a.label}</span>
            )}
            {a.ticker && a.category === 'PORTFOLIO' && (
              <span style={{
                fontSize:8, color:C.blue, background:`${C.blue}15`,
                padding:'1px 5px', borderRadius:3, flexShrink:0,
                fontFamily:"'JetBrains Mono','Courier New',monospace",
              }}>{a.ticker}</span>
            )}
            <SourceBadge source={a.source} C={C}/>
          </div>

          {/* Title — Chinese or English depending on lk */}
          {isTranslating ? (
            <div style={{fontSize:11.5, fontWeight:600, color:C.mid, lineHeight:1.4, fontStyle:'italic'}}>
              翻译中…
            </div>
          ) : (
            <div style={{
              fontSize:11.5, fontWeight:600,
              color: zhTitle ? C.blue : C.dark,
              lineHeight:1.4,
              overflow:'hidden', textOverflow:'ellipsis',
              display:'-webkit-box', WebkitLineClamp:2, WebkitBoxOrient:'vertical',
            }}>{displayTitle}</div>
          )}

          {/* Time */}
          <div style={{marginTop:4}}>
            <span style={{fontSize:9, color:C.mid}}>
              {timeAgo(a.published_at)} {L('ago','')}
            </span>
          </div>
        </div>

        <span style={{
          flexShrink:0, fontSize:9, color:C.blue, fontWeight:700,
          padding:'3px 8px', border:`1px solid ${C.blue}40`,
          borderRadius:5, whiteSpace:'nowrap', alignSelf:'center',
        }}>{L('Ask →','问 →')}</span>
      </div>
    </div>
  );
}

function NewsPanel({ macroArticles, portfolioArticles, loading, lastFetched, onOpenArticle, L, lk, C }) {
  const [newsTab,      setNewsTab]      = useState('macro');
  // translations cache: { [articleId]: { zh: string|null, loading: bool } }
  const [translations, setTranslations] = useState({});
  const translationsRef = useRef(translations);
  translationsRef.current = translations;

  const API_BASE = 'https://equity-research-ten.vercel.app';

  const translateArticle = async (article) => {
    const id = article.id;
    if (translationsRef.current[id]?.zh || translationsRef.current[id]?.loading) return;
    setTranslations(p => ({ ...p, [id]: { zh: null, loading: true } }));
    try {
      const context = article.ticker
        ? `${article.ticker}${article.tag ? ' · ' + article.tag : ''}`
        : article.tag || '';
      const res = await fetch(`${API_BASE}/api/translate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: article.title, context }),
      });
      const data = await res.json();
      setTranslations(p => ({ ...p, [id]: { zh: data.translated || article.title, loading: false } }));
    } catch {
      setTranslations(p => ({ ...p, [id]: { zh: null, loading: false } }));
    }
  };

  // Auto-translate all visible articles when in Chinese mode
  // Fires on: language switch to 'z', tab switch (while in 'z'), new articles arriving
  useEffect(() => {
    if (lk !== 'z') return;
    const list = newsTab === 'macro' ? macroArticles : portfolioArticles;
    // Stagger requests slightly to avoid hammering the API
    list.forEach((a, i) => {
      setTimeout(() => translateArticle(a), i * 80);
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lk, newsTab, macroArticles.length, portfolioArticles.length]);

  const macroAccent = (tag) => ({
    'FED':'#8B5CF6', 'CHINA-MACRO':'#EF4444', 'GEO':'#F59E0B',
    'MARKETS':'#3A6FD8', 'COMMODITIES':'#D08000', 'HK-A':'#10B981', 'TRADE':'#6366F1',
  })[tag] || '#6B82A0';

  const portfolioAccent = (ticker) => ({
    '700.HK':'#3A6FD8', '9999.HK':'#7B6BA5', '002594.SZ':'#1E9C5A',
    '6160.HK':'#D94040', '300308.SZ':'#D08000',
    'AI-INFRA':'#0EA5E9', 'BIOTECH':'#EC4899', 'EV-SECTOR':'#22C55E',
  })[ticker] || '#6B82A0';

  const activeList = newsTab === 'macro' ? macroArticles : portfolioArticles;

  // Count how many translations are done vs pending (for status indicator in Chinese mode)
  const zhDone    = lk === 'z' ? activeList.filter(a => translations[a.id]?.zh).length : 0;
  const zhPending = lk === 'z' ? activeList.filter(a => translations[a.id]?.loading).length : 0;

  return (
    <div>
      {/* Status bar */}
      <div style={{...S.row, justifyContent:'space-between', marginBottom:10}}>
        <div style={{...S.row, gap:6}}>
          <span style={{
            width:7, height:7, borderRadius:'50%', display:'inline-block',
            background: loading ? C.gold : C.green,
            boxShadow: loading ? 'none' : `0 0 0 3px ${C.green}35`,
          }}/>
          <span style={{fontSize:10, fontWeight:700, color: loading ? C.gold : C.green}}>
            {loading ? L('FETCHING','获取中') : L('LIVE','实时')}
          </span>
          {lastFetched && !loading && (
            <span style={{fontSize:9, color:C.mid}}>{lastFetched.toLocaleTimeString()}</span>
          )}
        </div>
        <div style={{...S.row, gap:8}}>
          {/* Chinese mode: show translation progress */}
          {lk === 'z' && (
            <span style={{fontSize:9, color: zhPending > 0 ? C.gold : C.mid}}>
              {zhPending > 0
                ? `正在翻译 ${zhPending} 条…`
                : `${zhDone}/${activeList.length} 条已翻译`
              }
            </span>
          )}
          <span style={{fontSize:9, color:C.mid}}>
            {L('FT · WSJ · Bloomberg · Reuters · CNBC','金融时报·华尔街日报·彭博·路透·CNBC')}
          </span>
        </div>
      </div>

      {/* Tab switcher */}
      <div style={{...S.row, gap:2, marginBottom:10, background:C.soft, borderRadius:8, padding:3}}>
        {[
          { id:'macro',     icon:'🌍', en:`Macro  ${macroArticles.length}`,     zh:`宏观  ${macroArticles.length}` },
          { id:'portfolio', icon:'📊', en:`Portfolio Radar  ${portfolioArticles.length}`, zh:`持仓雷达  ${portfolioArticles.length}` },
        ].map(tab => (
          <button key={tab.id} onClick={() => setNewsTab(tab.id)} style={{
            flex:1, padding:'6px 8px', border:'none', borderRadius:6, cursor:'pointer',
            background: newsTab === tab.id ? C.card : 'transparent',
            color: newsTab === tab.id ? C.dark : C.mid,
            fontSize:11, fontWeight: newsTab === tab.id ? 700 : 500,
            boxShadow: newsTab === tab.id ? '0 1px 4px rgba(50,90,160,0.12)' : 'none',
            transition:'all .15s',
          }}>{tab.icon} {lk === 'z' ? tab.zh : tab.en}</button>
        ))}
      </div>

      {/* Article list */}
      {activeList.length === 0 && !loading && (
        <div style={{textAlign:'center', padding:'20px 0', color:C.mid, fontSize:11}}>
          {L('Loading on mount — check back shortly.','启动时加载，请稍候。')}
        </div>
      )}

      <div style={{display:'flex', flexDirection:'column', gap:2, maxHeight:500, overflowY:'auto'}}>
        {activeList.map(a => (
          <ArticleRow
            key={a.id} a={a} onOpenArticle={onOpenArticle}
            accent={newsTab === 'macro' ? macroAccent(a.tag) : portfolioAccent(a.ticker)}
            C={C} L={L} lk={lk}
            translation={translations[a.id]}
          />
        ))}
      </div>
    </div>
  );
}

/* ── ARTICLE CHAT ────────────────────────────────────────────────────────── */
function ArticleChat({ article, messages, input, loading, onInputChange, onSend, onClose, L, lk, C }) {
  const bottomRef = useRef(null);

  useEffect(() => {
    if (bottomRef.current) bottomRef.current.scrollIntoView({ behavior:'smooth' });
  }, [messages]);

  const handleKey = e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); onSend(); } };

  return (
    <div style={{
      position:'fixed', top:0, right:0, bottom:0, width:400,
      background:C.card, borderLeft:`1px solid ${C.border}`,
      display:'flex', flexDirection:'column', zIndex:1000,
      boxShadow:'-4px 0 24px rgba(50,90,160,0.15)',
    }}>
      {/* Header */}
      <div style={{
        padding:'14px 16px', borderBottom:`1px solid ${C.border}`,
        background:C.dark, color:'#fff', flexShrink:0,
      }}>
        <div style={{...S.row, justifyContent:'space-between', marginBottom:6}}>
          <span style={{fontSize:11, fontWeight:700, letterSpacing:'0.04em'}}>
            {L('Article Analysis','文章分析')}
          </span>
          <button
            onClick={onClose}
            style={{background:'transparent', border:'none', color:'rgba(255,255,255,0.7)',
                    cursor:'pointer', fontSize:16, lineHeight:1, padding:'0 2px'}}
          >✕</button>
        </div>
        <div style={{
          fontSize:9, fontWeight:700,
          color: article.ticker === 'HSI' || article.ticker === 'CHINA' ? '#FFC947' : '#7EB8FF',
          fontFamily:"'JetBrains Mono','Courier New',monospace",
          marginBottom:4,
        }}>{article.ticker} · {article.source} · {timeAgo(article.published_at)} {L('ago','前')}</div>
        <div style={{fontSize:12, fontWeight:600, color:'rgba(255,255,255,0.92)', lineHeight:1.4}}>
          {article.title}
        </div>
      </div>

      {/* Messages */}
      <div style={{flex:1, overflowY:'auto', padding:'12px 14px', display:'flex', flexDirection:'column', gap:10}}>
        {messages.map((msg, i) => (
          <div key={i} style={{
            display:'flex', justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
          }}>
            <div style={{
              maxWidth:'88%', padding:'9px 13px', borderRadius:10,
              background: msg.role === 'user'
                ? C.blue
                : msg.loading ? C.soft : `${C.blue}0D`,
              color: msg.role === 'user' ? '#fff' : C.dark,
              fontSize:12, lineHeight:1.6,
              borderBottomRightRadius: msg.role === 'user' ? 3 : 10,
              borderBottomLeftRadius: msg.role === 'user' ? 10 : 3,
            }}>
              {msg.loading
                ? <span style={{color:C.mid, fontSize:11}}>{L('Analysing…','分析中…')}</span>
                : msg.content}
            </div>
          </div>
        ))}
        <div ref={bottomRef}></div>
      </div>

      {/* Input */}
      <div style={{
        padding:'10px 12px', borderTop:`1px solid ${C.border}`,
        background:C.soft, flexShrink:0,
      }}>
        <div style={{...S.row, gap:8}}>
          <textarea
            value={input}
            onChange={e => onInputChange(e.target.value)}
            onKeyDown={handleKey}
            placeholder={L('Ask about this article… (Enter to send)','就这篇文章提问…（Enter发送）')}
            rows={2}
            style={{
              flex:1, resize:'none', padding:'8px 10px',
              border:`1px solid ${C.border}`, borderRadius:7,
              fontSize:11, fontFamily:'inherit', color:C.dark,
              background:C.card, outline:'none', lineHeight:1.5,
            }}
          />
          <button
            onClick={onSend}
            disabled={loading || !input.trim()}
            style={{
              padding:'8px 14px', borderRadius:7, border:'none',
              background: loading || !input.trim() ? C.mid : C.blue,
              color:'#fff', fontSize:11, fontWeight:700,
              cursor: loading || !input.trim() ? 'not-allowed' : 'pointer',
              flexShrink:0, alignSelf:'flex-end',
            }}
          >{loading ? '…' : L('Send','发送')}</button>
        </div>
        <div style={{fontSize:9, color:C.mid, marginTop:5}}>
          {L('Responding as buy-side analyst · A/H equity focus','以买方分析师视角回复 · 聚焦A/H股')}
        </div>
      </div>
    </div>
  );
}

function RegimePanel({ regimeData, L, lk, C }) {
  if (!regimeData) return (
    <div style={{padding:'14px 0', textAlign:'center', fontSize:11, color:C.mid}}>
      {L('Loading regime data…','政体数据加载中…')}
    </div>
  );

  const regimeColor = r =>
    r === 'PERMISSIVE'   ? C.green :
    r === 'RESTRICTIVE'  ? C.red   : C.gold;

  const regimeLabel = (r, lk) => {
    if (lk === 'z') return r === 'PERMISSIVE' ? '宽松' : r === 'RESTRICTIVE' ? '收紧' : '中性';
    return r;
  };

  return (
    <div style={{display:'grid', gridTemplateColumns:'repeat(3, 1fr)', gap:10}}>
      {regimeData.sectors.map(sector => (
        <div key={sector.id} style={{
          padding:'12px 14px',
          background: C.soft,
          borderRadius:10,
          borderLeft:`3px solid ${regimeColor(sector.regime)}`,
        }}>
          <div style={{...S.row, justifyContent:'space-between', marginBottom:6}}>
            <span style={{fontSize:11, fontWeight:700, color:C.dark}}>
              {lk === 'z' ? sector.name_zh : sector.name_en}
            </span>
            <span style={{
              fontSize:9, fontWeight:700, letterSpacing:'0.04em',
              color:'#fff', background:regimeColor(sector.regime),
              padding:'2px 7px', borderRadius:4,
            }}>
              {regimeLabel(sector.regime, lk)}
            </span>
          </div>
          <div style={{fontSize:9.5, color:C.mid, lineHeight:1.5}}>
            {lk === 'z' ? sector.rationale_zh : sector.rationale_en}
          </div>
          {sector.tickers.length > 0 && (
            <div style={{...S.row, gap:4, marginTop:7, flexWrap:'wrap'}}>
              {sector.tickers.map(t => (
                <span key={t} style={{
                  fontSize:9, color:C.blue, background:C.card,
                  border:`1px solid ${C.border}`, borderRadius:4, padding:'1px 6px',
                  fontFamily:"'JetBrains Mono','Courier New',monospace",
                }}>{t}</span>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function ExclusiveInsight({ macroInsight, insightLoading, onGenerateInsight, L, lk, C }) {
  const [countdown, setCountdown] = useState(30 * 60);

  // Count down to next auto-refresh
  useEffect(() => {
    if (!macroInsight) return;
    setCountdown(30 * 60);
    const timer = setInterval(() => setCountdown(p => p > 0 ? p - 1 : 30 * 60), 1000);
    return () => clearInterval(timer);
  }, [macroInsight]);

  const fmtCountdown = s => {
    const m = Math.floor(s / 60), sec = s % 60;
    return `${m}:${String(sec).padStart(2,'0')}`;
  };

  const confidenceColor = c =>
    c === 'HIGH' ? C.green : c === 'LOW' ? C.red : C.gold;

  // Pick the right language field
  const t = (ins, field) => lk === 'z'
    ? (ins[`${field}_zh`] || ins[`${field}_en`] || '')
    : (ins[`${field}_en`] || ins[field] || '');  // fallback to old non-bilingual field

  return (
    <div>
      <div style={{...S.row, justifyContent:'space-between', marginBottom:12}}>
        <div style={{fontSize:11, color:C.mid, lineHeight:1.6}}>
          {L('AI-generated non-consensus interpretation · auto-refreshes every 30 min',
             'AI生成非共识解读 · 每30分钟自动刷新')}
          {macroInsight && !insightLoading && (
            <span style={{marginLeft:8, fontSize:9, color:C.mid}}>
              ({L('next in','下次刷新')} {fmtCountdown(countdown)})
            </span>
          )}
        </div>
        <button
          onClick={onGenerateInsight}
          disabled={insightLoading}
          style={{
            padding:'7px 16px', borderRadius:7, border:'none',
            cursor: insightLoading ? 'not-allowed' : 'pointer',
            background: insightLoading ? C.mid : C.blue, color:'#fff',
            fontSize:11, fontWeight:700, letterSpacing:'0.03em',
            opacity: insightLoading ? 0.7 : 1, transition:'all .15s', flexShrink:0,
          }}
        >
          {insightLoading ? L('Generating…','生成中…') : L('⚡ Refresh','⚡ 立即刷新')}
        </button>
      </div>

      {insightLoading && (
        <div style={{textAlign:'center', padding:'20px 0', color:C.mid, fontSize:11}}>
          {L('Generating insight…','正在生成洞察…')}
        </div>
      )}

      {macroInsight && !insightLoading && (() => {
        const ins = macroInsight.insight || {};
        return (
          <div style={{display:'flex', flexDirection:'column', gap:10}}>
            {/* Header: confidence + horizon + timestamp */}
            <div style={{...S.row, gap:8, flexWrap:'wrap'}}>
              <span style={{
                fontSize:9, fontWeight:700, color:'#fff',
                background:confidenceColor(ins.confidence),
                padding:'2px 9px', borderRadius:4, letterSpacing:'0.05em',
              }}>{ins.confidence} {lk==='z'?'置信度':'CONFIDENCE'}</span>
              <span style={{...S.tag(C.blue), fontSize:9}}>⏱ {ins.horizon}</span>
              {macroInsight.generated_at && (
                <span style={{fontSize:9, color:C.mid, marginLeft:'auto'}}>
                  {L('Generated at','生成于')} {new Date(macroInsight.generated_at).toLocaleTimeString()}
                </span>
              )}
            </div>

            {/* Market Reads */}
            <div style={{padding:'10px 14px', background:C.soft, borderRadius:8, borderLeft:`3px solid ${C.mid}`}}>
              <div style={{fontSize:9, fontWeight:700, color:C.mid, textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:5}}>
                {L('Market Reads','市场共识解读')}
              </div>
              <div style={{fontSize:12, color:C.dark, lineHeight:1.6}}>{t(ins,'market_reads')}</div>
            </div>

            {/* We Think */}
            <div style={{padding:'10px 14px', background:`${C.blue}12`, borderRadius:8, borderLeft:`3px solid ${C.blue}`}}>
              <div style={{fontSize:9, fontWeight:700, color:C.blue, textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:5}}>
                {L('We Think (Non-Consensus)','我们的判断（非共识）')}
              </div>
              <div style={{fontSize:12, color:C.dark, lineHeight:1.6, fontWeight:600}}>{t(ins,'we_think')}</div>
            </div>

            {/* Mechanism */}
            {t(ins,'mechanism') && (
              <div style={{padding:'10px 14px', background:C.soft, borderRadius:8}}>
                <div style={{fontSize:9, fontWeight:700, color:C.mid, textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:5}}>
                  {L('Mechanism','传导机制')}
                </div>
                <div style={{fontSize:11.5, color:C.dark, lineHeight:1.7}}>{t(ins,'mechanism')}</div>
              </div>
            )}

            {/* Implication */}
            {t(ins,'implication') && (
              <div style={{padding:'10px 14px', background:`${C.green}10`, borderRadius:8, borderLeft:`3px solid ${C.green}`}}>
                <div style={{fontSize:9, fontWeight:700, color:C.green, textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:5}}>
                  {L('Portfolio Implication','持仓含义')}
                </div>
                <div style={{fontSize:11.5, color:C.dark, lineHeight:1.6}}>{t(ins,'implication')}</div>
              </div>
            )}

            {/* Watch For */}
            {t(ins,'watch_for') && (
              <div style={{padding:'10px 14px', background:`${C.gold}12`, borderRadius:8, borderLeft:`3px solid ${C.gold}`}}>
                <div style={{fontSize:9, fontWeight:700, color:C.gold, textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:5}}>
                  {L('Watch For (5–10 days)','监控信号（5-10交易日）')}
                </div>
                <div style={{fontSize:11.5, color:C.dark, lineHeight:1.6, fontWeight:600}}>{t(ins,'watch_for')}</div>
              </div>
            )}
          </div>
        );
      })()}

      {!macroInsight && !insightLoading && (
        <div style={{textAlign:'center', padding:'24px 0', color:C.mid, fontSize:11}}>
          {L('Loading insight…','洞察加载中…')}
        </div>
      )}
    </div>
  );
}

// ── SwingSignal ───────────────────────────────────────────────────────────────
// Shared component — used in Scanner (summary row) and Research (detail card).
// `signals` = one ticker's signals_*.json object (or null/undefined if loading).
// `mode`    = 'compact' (Scanner row) | 'detail' (Research card)

const ZONE_STYLE = (zone, C) => {
  const map = {
    BULLISH:    { bg:`${C.green}18`, color:C.green,   label:{e:'Bullish',   z:'看涨'} },
    BEARISH:    { bg:`${C.red}18`,   color:C.red,     label:{e:'Bearish',   z:'看跌'} },
    OVERBOUGHT: { bg:`${C.gold}18`,  color:C.gold,    label:{e:'Overbought',z:'超买'} },
    OVERSOLD:   { bg:`${C.blue}18`,  color:C.blue,    label:{e:'Oversold',  z:'超卖'} },
    NEUTRAL:    { bg:`${C.mid}14`,   color:C.mid,     label:{e:'Neutral',   z:'中性'} },
  };
  return map[zone] || map.NEUTRAL;
};

const SIGNAL_COLOR = (sig, C) => sig.bullish ? C.green : C.red;
const SIGNAL_ICON  = (sig) => sig.bullish ? '↑' : '↓';
const STRENGTH_OPACITY = { strong:1, moderate:0.75 };

function SwingSignalBadge({ zone, C, lk }) {
  const style = ZONE_STYLE(zone, C);
  return (
    <span style={{
      fontSize:9, fontWeight:700, padding:'2px 7px',
      borderRadius:20, background:style.bg, color:style.color,
      letterSpacing:'0.02em', whiteSpace:'nowrap',
    }}>
      {style.label[lk] || style.label.e}
    </span>
  );
}

function SwingSignalCompact({ signals, C, lk }) {
  // One-liner summary for Scanner table rows
  if (!signals) return <span style={{fontSize:9, color:C.mid}}>—</span>;
  const sc = signals.signal_count;
  const zone = signals.zone;
  const zs   = ZONE_STYLE(zone, C);
  const ind  = signals.indicators;
  const entry = signals.entry_zone;
  const exit  = signals.exit_zone;
  const topSig = signals.signals[0];

  return (
    <div style={{display:'flex', alignItems:'center', gap:6, flexWrap:'wrap'}}>
      <SwingSignalBadge zone={zone} C={C} lk={lk}/>
      {sc.total > 0 && (
        <span style={{fontSize:9, fontFamily:'JetBrains Mono,monospace'}}>
          {sc.bullish > 0 && <span style={{color:C.green}}>{sc.bullish}↑</span>}
          {sc.bullish > 0 && sc.bearish > 0 && <span style={{color:C.mid}}> </span>}
          {sc.bearish > 0 && <span style={{color:C.red}}>{sc.bearish}↓</span>}
        </span>
      )}
      {entry && !exit && <span style={{fontSize:8, color:C.green, fontWeight:600}}>ENTRY</span>}
      {exit  && !entry && <span style={{fontSize:8, color:C.red,   fontWeight:600}}>EXIT</span>}
      {entry && exit   && <span style={{fontSize:8, color:C.gold,  fontWeight:600}}>⚠ WATCH</span>}
      {/* MACD direction dot */}
      {ind.macd_dif != null && ind.macd_dea != null && (
        <span style={{fontSize:9, color:C.mid, fontFamily:'JetBrains Mono,monospace'}}>
          MACD <span style={{color: ind.macd_dif > ind.macd_dea ? C.green : C.red}}>
            {ind.macd_dif > ind.macd_dea ? '▲' : '▼'}
          </span>
        </span>
      )}
      {/* KDJ J extreme */}
      {ind.kdj_j != null && (ind.kdj_j > 100 || ind.kdj_j < 0) && (
        <span style={{fontSize:9, fontWeight:700,
          color: ind.kdj_j > 100 ? C.red : C.green}}>
          J={ind.kdj_j.toFixed(0)}
        </span>
      )}
      {topSig && (
        <span style={{fontSize:9, color:C.mid, flex:1, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>
          {topSig.description[lk] || topSig.description.e}
        </span>
      )}
    </div>
  );
}

function SwingSignalDetail({ signals, C, L, lk }) {
  // Full detail card for Research tab
  if (!signals) return (
    <div style={{padding:'12px 0', color:C.mid, fontSize:11}}>
      {L('No swing signal data — run fetch-data workflow','暂无摆动信号数据，请运行fetch-data工作流')}
    </div>
  );

  const { zone, entry_zone, exit_zone, signals: sigs, signal_count: sc, indicators: ind, price, generated_at } = signals;
  const zs = ZONE_STYLE(zone, C);

  return (
    <div>
      {/* Header: zone + entry/exit badges + generated date */}
      <div style={{display:'flex', alignItems:'center', gap:8, marginBottom:12, flexWrap:'wrap'}}>
        <SwingSignalBadge zone={zone} C={C} lk={lk}/>
        {entry_zone && (
          <span style={{fontSize:9, fontWeight:700, padding:'2px 7px', borderRadius:20,
            background:`${C.green}18`, color:C.green}}>
            {L('Entry Zone ✓','入场区 ✓')}
          </span>
        )}
        {exit_zone && (
          <span style={{fontSize:9, fontWeight:700, padding:'2px 7px', borderRadius:20,
            background:`${C.red}18`, color:C.red}}>
            {L('Exit Zone ⚠','退场区 ⚠')}
          </span>
        )}
        <span style={{fontSize:9, color:C.mid, marginLeft:'auto'}}>
          {L('as of','截至')} {generated_at}
        </span>
      </div>

      {/* Indicator grid — Row 1: MA / RSI / Volume */}
      <div style={{display:'grid', gridTemplateColumns:'repeat(4, 1fr)', gap:8, marginBottom:6}}>
        {[
          { label:'MA20',          val: ind.ma20  != null ? ind.ma20.toFixed(1)  : '—' },
          { label:'MA60',          val: ind.ma60  != null ? ind.ma60.toFixed(1)  : '—' },
          { label:'RSI(14)',       val: ind.rsi14 != null ? ind.rsi14.toFixed(1) : '—',
            color: ind.rsi14 > 70 ? C.red : ind.rsi14 < 30 ? C.green : C.dark },
          { label:L('Vol Ratio','量比'), val: ind.vol_ratio != null ? `${ind.vol_ratio.toFixed(2)}×` : '—',
            color: ind.vol_ratio >= 2 ? C.green : ind.vol_ratio < 0.5 ? C.red : C.dark },
          { label:L('vs MA20','偏MA20'), val: ind.price_vs_ma20 != null ? `${ind.price_vs_ma20>0?'+':''}${ind.price_vs_ma20.toFixed(1)}%` : '—',
            color: ind.price_vs_ma20 > 0 ? C.green : C.red },
          { label:L('vs MA60','偏MA60'), val: ind.price_vs_ma60 != null ? `${ind.price_vs_ma60>0?'+':''}${ind.price_vs_ma60.toFixed(1)}%` : '—',
            color: ind.price_vs_ma60 > 0 ? C.green : C.red },
          { label:L('1D Chg','1日'), val: ind.change_1d  != null ? `${ind.change_1d>0?'+':''}${ind.change_1d.toFixed(2)}%`  : '—',
            color: ind.change_1d  > 0 ? C.green : C.red },
          { label:L('5D Chg','5日'), val: ind.change_5d  != null ? `${ind.change_5d>0?'+':''}${ind.change_5d.toFixed(2)}%`  : '—',
            color: ind.change_5d  > 0 ? C.green : C.red },
        ].map(({ label, val, color }) => (
          <div key={label} style={{background:C.soft, borderRadius:8, padding:'8px 10px'}}>
            <div style={{fontSize:9, color:C.mid, fontWeight:600, marginBottom:3}}>{label}</div>
            <div style={{fontSize:12, fontWeight:700, fontFamily:'JetBrains Mono,monospace',
                         color: color || C.dark}}>{val}</div>
          </div>
        ))}
      </div>

      {/* Indicator grid — Row 2: MACD / Bollinger / KDJ */}
      <div style={{display:'grid', gridTemplateColumns:'repeat(4, 1fr)', gap:8, marginBottom:12}}>
        {[
          { label:'MACD DIF',
            val: ind.macd_dif != null ? ind.macd_dif.toFixed(3) : '—',
            color: ind.macd_dif != null ? (ind.macd_dif > (ind.macd_dea || 0) ? C.green : C.red) : C.dark,
          },
          { label:'MACD DEA',
            val: ind.macd_dea != null ? ind.macd_dea.toFixed(3) : '—',
            color: C.dark,
          },
          { label:L('MACD Hist','MACD柱'),
            val: ind.macd_hist != null ? (ind.macd_hist > 0 ? '+' : '') + ind.macd_hist.toFixed(3) : '—',
            color: ind.macd_hist != null ? (ind.macd_hist > 0 ? C.green : C.red) : C.dark,
          },
          { label:L('BB Width','布林宽度'),
            val: ind.bb_bandwidth != null ? `${ind.bb_bandwidth.toFixed(1)}%` : '—',
            color: ind.bb_bandwidth != null && ind.bb_bandwidth < 5 ? C.gold : C.dark,
          },
          { label:'BB Upper',
            val: ind.bb_upper != null ? ind.bb_upper.toFixed(1) : '—',
            color: C.red,
          },
          { label:'BB Lower',
            val: ind.bb_lower != null ? ind.bb_lower.toFixed(1) : '—',
            color: C.green,
          },
          { label:'KDJ K/D',
            val: ind.kdj_k != null && ind.kdj_d != null
              ? `${ind.kdj_k.toFixed(0)}/${ind.kdj_d.toFixed(0)}` : '—',
            color: ind.kdj_k != null && ind.kdj_d != null
              ? (ind.kdj_k > ind.kdj_d ? C.green : C.red) : C.dark,
          },
          { label:'KDJ J',
            val: ind.kdj_j != null ? ind.kdj_j.toFixed(1) : '—',
            color: ind.kdj_j != null ? (ind.kdj_j > 100 ? C.red : ind.kdj_j < 0 ? C.green : C.dark) : C.dark,
          },
        ].map(({ label, val, color }) => (
          <div key={label} style={{background:C.soft, borderRadius:8, padding:'8px 10px'}}>
            <div style={{fontSize:9, color:C.mid, fontWeight:600, marginBottom:3}}>{label}</div>
            <div style={{fontSize:12, fontWeight:700, fontFamily:'JetBrains Mono,monospace',
                         color: color || C.dark}}>{val}</div>
          </div>
        ))}
      </div>

      {/* Signal list */}
      {sigs.length === 0 ? (
        <div style={{fontSize:11, color:C.mid, padding:'8px 0'}}>
          {L('No active signals — market is quiet','暂无信号，市场处于静默期')}
        </div>
      ) : (
        <div>
          {sigs.map((sig, i) => {
            const col = SIGNAL_COLOR(sig, C);
            const opc = STRENGTH_OPACITY[sig.strength] || 0.8;
            return (
              <div key={i} style={{display:'flex', alignItems:'flex-start', gap:8, padding:'7px 0',
                borderBottom: i < sigs.length-1 ? `1px solid ${C.border}` : 'none',
                opacity: opc}}>
                {/* Strength bar */}
                <div style={{width:3, borderRadius:3, alignSelf:'stretch', minHeight:24,
                  background: col, flexShrink:0}}></div>
                <div style={{flex:1}}>
                  <div style={{display:'flex', alignItems:'center', gap:6, marginBottom:2}}>
                    <span style={{fontSize:10, fontWeight:700, color:col}}>
                      {SIGNAL_ICON(sig)} {sig.type.replace(/_/g,' ')}
                    </span>
                    <span style={{fontSize:8, color:C.mid, textTransform:'uppercase',
                      padding:'1px 5px', background:C.soft, borderRadius:8}}>
                      {sig.strength}
                    </span>
                  </div>
                  <div style={{fontSize:11, color:C.mid, lineHeight:1.5}}>
                    {sig.description[lk] || sig.description.e}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Scanner({ L, lk, open, toggle, C, stressData, regimeData, macroInsight, insightLoading, onGenerateInsight, newsMacro, newsPortfolio, newsLoading, newsLastFetched, onOpenArticle, liveData, universeA, universeHK, signalsData, vpScores }) {
  const colors = [C.blue, C.gold, C.green, C.red, C.blue];
  const sectorColors = [C.blue, '#7B6BA5', C.gold, C.green, C.red];

  // ── Live data derivation ────────────────────────────────────────────────
  // VP Score seed values (fallback only — overridden by vp_snapshot.json + localStorage)
  const FOCUS_SEED = [
    { id:'300308.SZ', name:'Innolight', sector:'AI Infra',  vp:79 },
    { id:'700.HK',    name:'Tencent',   sector:'Internet',  vp:65 },
    { id:'9999.HK',   name:'NetEase',   sector:'Gaming',    vp:58 },
    { id:'6160.HK',   name:'BeiGene',   sector:'Biotech',   vp:65 },
    { id:'002594.SZ', name:'BYD',       sector:'EV/Auto',   vp:61 },
  ];
  // FOCUS uses live VP scores: localStorage (most recent DeepResearch) > vp_snapshot.json > seed
  const FOCUS = FOCUS_SEED.map(f => {
    const lsKey = `ar_research_${f.id}`;
    let lsVp = null;
    try {
      const ls = JSON.parse(localStorage.getItem(lsKey) || '{}');
      lsVp = ls?.current?.vp ?? null;
    } catch { lsVp = null; }
    const snapVp = vpScores?.[f.id] ?? null;
    return { ...f, vp: lsVp ?? snapVp ?? f.vp };
  });
  const yahoo    = liveData?.yahoo    || {};
  const akshare  = liveData?.akshare  || {};
  const fetchedAt = liveData?._meta?.fetched_at;
  const dataAgeH  = fetchedAt ? Math.round((Date.now() - new Date(fetchedAt)) / 3600000) : null;
  const dataFresh = dataAgeH !== null && dataAgeH < 30;

  // Derive live factor scores from actual technical / fundamental data
  const liveFactors = (() => {
    const vals = FOCUS.map(t => yahoo[t.id]).filter(Boolean);
    if (!vals.length) return SCANNER.factors;
    const avgChg  = vals.reduce((s,v) => s + (v.price?.change_pct || 0), 0) / vals.length;
    const avgRsi  = vals.reduce((s,v) => s + (v.technical?.rsi_14  || 50), 0) / vals.length;
    const avgRoe  = vals.reduce((s,v) => s + (v.fundamentals?.roe  ||  0), 0) / vals.length;
    const peVals  = vals.map(v => v.fundamentals?.pe_forward).filter(p => p && p > 0);
    const avgPe   = peVals.length ? peVals.reduce((s,p) => s+p,0)/peVals.length : 25;
    const inno    = yahoo['300308.SZ'];
    const momentum  = Math.max(5, Math.min(95, 50 + avgChg * 8));
    const value     = Math.max(5, Math.min(95, 85 - avgPe));
    const quality   = Math.max(5, Math.min(95, avgRoe * 130));
    const sentiment = Math.max(5, Math.min(95, avgRsi));
    const aiBeta    = inno ? Math.max(5, Math.min(95, (inno.technical?.rsi_14 || 60) * 1.12)) : 75;
    return [
      { name:'Momentum', val:Math.round(momentum),  t: momentum>50?'up':'down' },
      { name:'Value',    val:Math.round(value),     t: value>50?'up':'down' },
      { name:'Quality',  val:Math.round(quality),   t: quality>60?'up':'stable' },
      { name:'Sentiment',val:Math.round(sentiment), t: sentiment>55?'up':'down' },
      { name:'AI Beta',  val:Math.round(aiBeta),    t: aiBeta>65?'up':'stable' },
    ];
  })();

  // Live universe counts for funnel
  const liveUniverse = (universeA?.stocks?.length||0) + (universeHK?.stocks?.length||0);
  const liveFunnel = liveUniverse > 0 ? [
    { s:'Universe',    n: liveUniverse.toLocaleString(), r:'A+HK listed' },
    ...SCANNER.funnel.slice(1),
  ] : SCANNER.funnel;

  // Jason: Market Pulse ticker items — macro + portfolio indicators
  const PULSE_ITEMS = [
    ...MACRO.map(m => ({
      key: m.name,
      val: m.val,
      chg: m.chg,
      up: m.trend === 'up',
      dn: m.trend === 'down',
    })),
    { key:'PORTFOLIO', val:'5 POS', chg:'82% NET', up:true, dn:false },
    { key:'REGIME',    val:regimeData?.regime_label || 'RISK-ON', chg:'', up:true, dn:false },
  ];

  return (
    <div>
      {/* Jason: Bloomberg Market Pulse Ticker Bar ─────────────────────── */}
      <div style={{
        background: C.card,
        border: `1px solid ${C.border}`,
        borderRadius: 8,
        marginBottom: 12,
        overflow: 'hidden',
        height: 32,
        display: 'flex',
        alignItems: 'center',
      }}>
        {/* MARKET label */}
        <div style={{
          padding: '0 12px',
          borderRight: `1px solid ${C.border}`,
          height: '100%',
          display: 'flex', alignItems: 'center',
          background: C.orange ? `${C.orange}18` : `${C.blue}18`,
          flexShrink: 0,
        }}>
          <span style={{
            fontSize: 9, fontWeight: 800, fontFamily: MONO,
            color: C.orange || C.blue, letterSpacing: '0.1em',
          }}>MARKET</span>
        </div>

        {/* Scrolling ticker */}
        <div style={{flex:1, overflow:'hidden', position:'relative'}}>
          <div className="ar-ticker-track" style={{
            display: 'flex', alignItems: 'center', gap: 0,
            animation: 'ticker-scroll 40s linear infinite',
            width: 'max-content',
          }}>
            {/* Duplicate items for seamless loop */}
            {[...PULSE_ITEMS, ...PULSE_ITEMS].map((item, i) => {
              const color = item.up ? C.green : item.dn ? C.red : C.mid;
              return (
                <div key={i} style={{
                  display: 'flex', alignItems: 'center', gap: 5,
                  padding: '0 20px',
                  borderRight: `1px solid ${C.border}`,
                  height: 32,
                  flexShrink: 0,
                }}>
                  <span style={{fontSize:9, color:C.mid, fontFamily:MONO,
                                letterSpacing:'0.05em', fontWeight:600}}>
                    {item.key}
                  </span>
                  <span style={{fontSize:11, fontWeight:700, fontFamily:MONO, color:C.dark}}>
                    {item.val}
                  </span>
                  {item.chg && (
                    <span style={{fontSize:9, fontWeight:600, fontFamily:MONO, color}}>
                      {item.chg}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Timestamp */}
        <div style={{
          padding: '0 12px',
          borderLeft: `1px solid ${C.border}`,
          flexShrink: 0,
          display: 'flex', alignItems: 'center', gap: 5,
        }}>
          <div style={{width:5, height:5, borderRadius:'50%',
            background: (liveData?._meta?.fetched_at &&
              Math.abs(Date.now()-new Date(liveData._meta.fetched_at))/3600000 < 30)
              ? C.green : C.gold,
            animation:'blink 2s ease-in-out infinite',
          }}></div>
          <span style={{fontSize:9, fontFamily:MONO, color:C.mid}}>
            {liveData?._meta?.fetched_at
              ? new Date(liveData._meta.fetched_at).toLocaleString('en-HK',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'})
              : L('AWAITING SYNC','等待同步')}
          </span>
        </div>
      </div>

      {/* ── Live Portfolio Snapshot ─────────────────────────────────────── */}
      <Card title={L('Live Portfolio Snapshot','持仓实时行情')} sub={L('Focus stocks · prices from last GitHub Actions sync','持仓股票 · 来自 GitHub Actions 定时抓取')} open={open.liveSnapshot !== false} onToggle={()=>toggle('liveSnapshot')} C={C}>
        {/* Freshness bar */}
        <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:12}}>
          <div style={{display:'flex', alignItems:'center', gap:6}}>
            {dataFresh
              ? <Wifi size={11} color={C.green}/>
              : <WifiOff size={11} color={C.gold}/>}
            <span style={{fontSize:10, color: dataFresh ? C.green : C.gold, fontFamily:'inherit'}}>
              {dataAgeH !== null
                ? `${L('Synced','已同步')} ${dataAgeH}h ${L('ago','前')} · ${new Date(fetchedAt).toLocaleDateString()}`
                : L('No live data — awaiting next GitHub Actions run','暂无实时数据，等待下一次同步')}
            </span>
          </div>
          <span style={{fontSize:9, color:C.mid}}>{L('Auto-sync: 08:30 & 16:30 HKT weekdays','自动同步: 工作日 08:30 & 16:30 港时')}</span>
        </div>

        {/* Jason: Bloomberg-style column headers with tabular alignment */}
        <div style={{display:'flex', padding:'5px 8px', borderBottom:`1px solid ${C.border}`,
                     marginBottom:2, background:C.soft, borderRadius:'6px 6px 0 0'}}>
          <span style={{flex:'1 1 130px', fontSize:8, color:C.mid, fontWeight:700,
                        letterSpacing:'0.08em', textTransform:'uppercase'}}>{L('STOCK','股票')}</span>
          <span style={{width:76, textAlign:'right', fontSize:8, color:C.mid, fontWeight:700,
                        letterSpacing:'0.08em', textTransform:'uppercase'}}>{L('PRICE','价格')}</span>
          <span style={{width:66, textAlign:'right', fontSize:8, color:C.mid, fontWeight:700,
                        letterSpacing:'0.08em', textTransform:'uppercase'}}>{L('CHG%','涨跌%')}</span>
          <span style={{width:54, textAlign:'right', fontSize:8, color:C.mid, fontWeight:700,
                        letterSpacing:'0.08em', textTransform:'uppercase'}}>VP</span>
          <span style={{width:50, textAlign:'right', fontSize:8, color:C.mid, fontWeight:700,
                        letterSpacing:'0.08em', textTransform:'uppercase'}}>RSI</span>
          <span style={{width:56, textAlign:'right', fontSize:8, color:C.mid, fontWeight:700,
                        letterSpacing:'0.08em', textTransform:'uppercase'}}>{L('VOL×','量比')}</span>
          <span style={{width:62, textAlign:'right', fontSize:8, color:C.mid, fontWeight:700,
                        letterSpacing:'0.08em', textTransform:'uppercase'}}>{L('SIGNAL','信号')}</span>
        </div>

        {FOCUS.map((tk, i) => {
          const d   = yahoo[tk.id];
          const px  = d?.price?.last;
          const chg = d?.price?.change_pct;
          const rsi = d?.technical?.rsi_14;
          const volR= d?.price?.volume_ratio;
          const isHK = tk.id.endsWith('.HK');
          const ccy  = isHK ? 'HK$' : '¥';
          const chgColor = chg > 0 ? C.green : chg < 0 ? C.red : C.mid;
          const rsiColor = rsi > 70 ? C.red : rsi < 30 ? C.green : C.mid;
          // Jason: Bloomberg-style dense stock row with VP mini-bar + signal badge
          const vpColor = tk.vp >= 70 ? C.green : tk.vp >= 50 ? C.gold : C.red;
          const sig = signalsData?.[tk.id];
          const sigLabel = sig?.swing_signal || sig?.overall_signal || null;
          const sigColor = sigLabel?.includes('BUY') ? C.green
                         : sigLabel?.includes('SELL')||sigLabel?.includes('EXIT') ? C.red : C.gold;
          return (
            <div key={i} style={{
              display:'flex', alignItems:'center', padding:'6px 8px',
              borderRadius: 6,
              borderBottom: i < FOCUS.length-1 ? `1px solid ${C.border}` : 'none',
              background: i % 2 === 0 ? 'transparent' : `${C.soft}80`,
              transition: 'background .12s',
              cursor: 'pointer',
            }}
              onMouseEnter={e=>e.currentTarget.style.background=C.soft}
              onMouseLeave={e=>e.currentTarget.style.background= i%2===0?'transparent':`${C.soft}80`}
            >
              {/* Stock name + ticker */}
              <div style={{flex:'1 1 130px'}}>
                <div style={{fontSize:11, fontWeight:700, color:C.dark}}>{tk.name}</div>
                <div style={{fontSize:9, color:C.mid, fontFamily:MONO}}>
                  {tk.id} · <span style={{color:C.orange||C.blue}}>{tk.sector}</span>
                </div>
              </div>

              {/* Price */}
              <div style={{width:76, textAlign:'right', fontSize:13, fontWeight:700,
                           color:C.dark, fontFamily:MONO, letterSpacing:'-0.01em'}}>
                {px != null ? `${ccy}${px >= 100 ? px.toFixed(0) : px.toFixed(2)}` : '—'}
              </div>

              {/* Change % — Bloomberg: styled pill */}
              <div style={{width:66, textAlign:'right'}}>
                {chg != null ? (
                  <span style={{
                    fontSize:10, fontWeight:700, fontFamily:MONO,
                    padding:'2px 6px', borderRadius:4,
                    background:`${chgColor}18`, color:chgColor,
                    display:'inline-block',
                  }}>
                    {chg>0?'+':''}{chg.toFixed(2)}%
                  </span>
                ) : <span style={{fontSize:10, color:C.mid}}>—</span>}
              </div>

              {/* VP Score + mini bar */}
              <div style={{width:54, textAlign:'right'}}>
                <div style={{fontSize:10, fontWeight:700, color:vpColor, fontFamily:MONO}}>{tk.vp}</div>
                <div style={{height:3, borderRadius:2, background:`${vpColor}20`, marginTop:2, overflow:'hidden'}}>
                  <div style={{height:'100%', width:`${tk.vp}%`, background:vpColor, borderRadius:2,
                               transition:'width 0.6s ease'}}></div>
                </div>
              </div>

              {/* RSI */}
              <div style={{width:50, textAlign:'right'}}>
                <span style={{fontSize:10, color:rsiColor, fontFamily:MONO, fontWeight:600}}>
                  {rsi != null ? rsi.toFixed(1) : '—'}
                </span>
              </div>

              {/* Volume ratio */}
              <div style={{width:56, textAlign:'right'}}>
                <span style={{fontSize:10, fontFamily:MONO,
                  color: volR > 1.5 ? C.green : volR < 0.5 ? C.red : C.mid}}>
                  {volR != null ? `${volR.toFixed(2)}×` : '—'}
                </span>
              </div>

              {/* Signal badge */}
              <div style={{width:62, textAlign:'right'}}>
                {sigLabel ? (
                  <span style={{
                    fontSize:8, fontWeight:800, fontFamily:MONO, letterSpacing:'0.04em',
                    padding:'2px 5px', borderRadius:3,
                    background:`${sigColor}18`, color:sigColor,
                    border:`1px solid ${sigColor}40`,
                    display:'inline-block',
                  }}>
                    {sigLabel.replace('_',' ').split(' ')[0]}
                  </span>
                ) : <span style={{fontSize:9, color:C.mid}}>—</span>}
              </div>
            </div>
          );
        })}
      </Card>

      {/* ── Swing Trading Signals ────────────────────────────────────────── */}
      <Card title={L('Swing Trading Signals','摆动交易信号')}
            sub={L('MA20/60 crossover · RSI(14) · Volume breakout — deterministic, rule-based','MA20/60交叉 · RSI(14) · 放量突破 — 确定性规则信号')}
            open={open.swingSignals !== false} onToggle={()=>toggle('swingSignals')} C={C}>
        {/* Column headers */}
        <div style={{display:'flex', alignItems:'center', padding:'4px 0',
          borderBottom:`1px solid ${C.border}`, marginBottom:4}}>
          <span style={{flex:'1 1 120px', fontSize:9, color:C.mid, fontWeight:600}}>{L('STOCK','股票')}</span>
          <span style={{width:90,  fontSize:9, color:C.mid, fontWeight:600}}>{L('ZONE','区域')}</span>
          <span style={{flex:'3 1 0', fontSize:9, color:C.mid, fontWeight:600}}>{L('SIGNALS','信号')}</span>
        </div>
        {FOCUS.map((tk, i) => {
          const sig = signalsData?.[tk.id];
          return (
            <div key={i} style={{display:'flex', alignItems:'center', padding:'8px 0',
              borderBottom: i < FOCUS.length-1 ? `1px solid ${C.border}` : 'none', gap:0}}>
              <div style={{flex:'1 1 120px'}}>
                <div style={{fontSize:11, fontWeight:700, color:C.dark}}>{tk.name}</div>
                <div style={{fontSize:9, color:C.mid}}>{tk.id}</div>
              </div>
              <div style={{width:90}}>
                {sig ? <SwingSignalBadge zone={sig.zone} C={C} lk={lk}/> : <span style={{fontSize:9, color:C.mid}}>—</span>}
              </div>
              <div style={{flex:'3 1 0'}}>
                <SwingSignalCompact signals={sig} C={C} lk={lk}/>
              </div>
            </div>
          );
        })}
        {!signalsData || Object.keys(signalsData).length === 0 ? (
          <div style={{fontSize:10, color:C.mid, padding:'8px 0', textAlign:'center'}}>
            {L('Signal data not yet available — will appear after next GitHub Actions run','信号数据暂不可用，下次工作流运行后显示')}
          </div>
        ) : null}
      </Card>

      {/* ── Capital Flow Intelligence ─────────────────────────────────── */}
      {(akshare.northbound || akshare.southbound) && (
        <Card title={L('Capital Flow Intelligence','资金流向')} sub={L('Northbound · Southbound · Dragon & Tiger','北向 · 南向 · 龙虎榜')} open={open.flowIntel !== false} onToggle={()=>toggle('flowIntel')} C={C}>
          <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:10, marginBottom: akshare.dragon_tiger?.length ? 12 : 0}}>
            {[
              { label: L('Northbound 北向','北向资金'), data: akshare.northbound, dir:'N' },
              { label: L('Southbound 南向','南向资金'), data: akshare.southbound, dir:'S' },
            ].map(({label, data, dir}) => {
              if (!data || !data.latest_net_flow) return (
                <div key={dir} style={{padding:12, background:C.soft, borderRadius:8}}>
                  <div style={{fontSize:10, color:C.mid, fontWeight:600, marginBottom:6}}>{label}</div>
                  <div style={{fontSize:10, color:C.mid}}>{L('No data','暂无数据')}</div>
                </div>
              );
              const isInflow = data.trend === 'inflow';
              const fmtBn = v => {
                if (v == null) return '—';
                const bn = Math.abs(v) / 1e8;
                return `${v >= 0 ? '+' : '-'}¥${bn.toFixed(1)}亿`;
              };
              return (
                <div key={dir} style={{padding:12, background:C.soft, borderRadius:8}}>
                  <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:8}}>
                    <span style={{fontSize:10, color:C.mid, fontWeight:600}}>{label}</span>
                    <span style={{fontSize:9, fontWeight:700, padding:'2px 8px', borderRadius:10,
                      background: isInflow ? `${C.green}18` : `${C.red}18`,
                      color: isInflow ? C.green : C.red}}>
                      {isInflow ? '▲ INFLOW' : '▼ OUTFLOW'}
                    </span>
                  </div>
                  <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:6}}>
                    <div>
                      <div style={{fontSize:9, color:C.mid}}>{L('Today','今日')}</div>
                      <div style={{fontSize:12, fontWeight:700, color: (data.latest_net_flow||0)>=0?C.green:C.red, fontFamily:'JetBrains Mono,monospace'}}>
                        {fmtBn(data.latest_net_flow)}
                      </div>
                    </div>
                    <div>
                      <div style={{fontSize:9, color:C.mid}}>{L('5-Day','5日累计')}</div>
                      <div style={{fontSize:12, fontWeight:700, color: (data['5d_cumulative']||0)>=0?C.green:C.red, fontFamily:'JetBrains Mono,monospace'}}>
                        {fmtBn(data['5d_cumulative'])}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Dragon & Tiger focus entries */}
          {(() => {
            const dtEntries = (akshare.dragon_tiger || []).filter(e => e.focus);
            if (!dtEntries.length) return null;
            return (
              <div>
                <div style={{fontSize:10, color:C.mid, fontWeight:600, marginBottom:6}}>
                  {L('Dragon & Tiger Board — Focus Stocks','龙虎榜 — 持仓股票')}
                </div>
                {dtEntries.slice(0,5).map((e,i) => (
                  <div key={i} style={{display:'flex', alignItems:'center', justifyContent:'space-between',
                    padding:'6px 0', borderBottom: i < dtEntries.length-1 ? `1px solid ${C.border}` : 'none'}}>
                    <div>
                      <span style={{fontSize:11, fontWeight:600, color:C.dark}}>{e.name}</span>
                      <span style={{fontSize:9, color:C.mid, marginLeft:6}}>{e.date} · {e.reason}</span>
                    </div>
                    <span style={{fontSize:11, fontWeight:700, color:(e.net_amt||0)>=0?C.green:C.red, fontFamily:'JetBrains Mono,monospace'}}>
                      {e.net_amt != null ? `${e.net_amt>=0?'+':''}${(e.net_amt/1e8).toFixed(2)}亿` : '—'}
                    </span>
                  </div>
                ))}
              </div>
            );
          })()}
        </Card>
      )}

      <Card title={L('Market News Intelligence','市场新闻情报')} sub={L('Live feed · Click any article to analyse & chat · auto-refreshes every 3 min','实时新闻 · 点击文章进行分析问答 · 每3分钟自动刷新')} open={open.newsPanel} onToggle={()=>toggle('newsPanel')} C={C}>
        <NewsPanel
          macroArticles={newsMacro}
          portfolioArticles={newsPortfolio}
          loading={newsLoading}
          lastFetched={newsLastFetched}
          onOpenArticle={onOpenArticle}
          L={L} lk={lk} C={C}
        />
      </Card>

      <Card title={L('Sector Regime Classification','板块政体分类')} sub={L('PERMISSIVE · NEUTRAL · RESTRICTIVE — manually curated, updated on policy shifts','宽松·中性·收紧 — 人工维护，重大政策变动后更新')} open={open.regime} onToggle={()=>toggle('regime')} C={C}>
        <RegimePanel regimeData={regimeData} L={L} lk={lk} C={C}/>
      </Card>

      <Card title={L('Exclusive Insight','独家洞察')} sub={L('Non-consensus macro interpretation · AI-generated · Not investment advice','非共识宏观解读 · AI生成 · 非投资建议')} open={open.exclusiveInsight} onToggle={()=>toggle('exclusiveInsight')} C={C}>
        <ExclusiveInsight
          macroInsight={macroInsight}
          insightLoading={insightLoading}
          onGenerateInsight={onGenerateInsight}
          L={L}
          lk={lk}
          C={C}
        />
      </Card>

      <Card title={L('Macro Dashboard','宏观仪表盘')} open={open.macro} onToggle={()=>toggle('macro')} C={C}>
        <div style={{display:'grid', gridTemplateColumns:'repeat(5, 1fr)', gap:10, marginBottom:14}}>
          {MACRO.map((m,i)=>(
            <div key={i} style={{padding:12, background:C.soft, borderRadius:8}}>
              <div style={{fontSize:10, color:C.mid, fontWeight:600}}>{m.name}</div>
              <div style={{fontSize:13, fontWeight:700, color:C.dark, marginTop:4}}>{m.val}</div>
              <div style={{...S.row, gap:3, marginTop:4}}><TI t={m.trend} C={C}/><span style={{fontSize:9, color:C.mid}}>{m.chg}</span></div>
            </div>
          ))}
        </div>
        <div style={{fontSize:11, color:C.mid, lineHeight:1.6}}>{MACRO[0].note[lk]}</div>
      </Card>

      <Card title={L('Factor Momentum','因子动量')} sub={liveData ? L('Derived from live market data','从实时市场数据计算') : L('Static estimates','静态估算')} open={open.factors} onToggle={()=>toggle('factors')} C={C}>
        <div style={{height:220}}>
          <ResponsiveContainer width='100%' height='100%'>
            <BarChart data={liveFactors}>
              <XAxis dataKey='name' tick={{fontSize:11}} />
              <YAxis tick={{fontSize:10}} domain={[0,100]} />
              <Tooltip contentStyle={{background:C.card, border:`1px solid ${C.border}`, borderRadius:6}} />
              <Bar dataKey='val' fill={C.blue} radius={[4,4,0,0]}>
                {liveFactors.map((f,i)=>(
                  <Cell key={i} fill={f.val>60?C.green: f.val>40?C.gold:C.red} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <Card title={L('Screening Funnel','筛选漏斗')} sub={liveUniverse > 0 ? L('Live universe count','实时股票池') : L('Static estimates','静态估算')} open={open.funnel} onToggle={()=>toggle('funnel')} C={C}>
        {liveFunnel.map((f,i)=>(
          <div key={i} style={{...S.row, marginBottom:i<liveFunnel.length-1?10:0, justifyContent:'space-between'}}>
            <div><div style={{fontSize:11, fontWeight:600, color:C.dark}}>{f.s}</div><div style={{fontSize:9, color:C.mid}}>{f.r}</div></div>
            <div style={{fontSize:13, fontWeight:700, color: i===0 ? C.blue : i===liveFunnel.length-1 ? C.green : C.blue}}>{f.n}</div>
          </div>
        ))}
      </Card>

      <Card title={L('AI Portfolio Impact','AI投资组合影响')} open={open.macroImpact} onToggle={()=>toggle('macroImpact')} C={C}>
        {MACRO_ANCHORS.map((a,i)=>(
          <div key={i} style={{padding:10, marginBottom:10, background:C.soft, borderRadius:8}}>
            <div style={{...S.row, gap:8, marginBottom:6}}>
              <span style={{fontSize:11, fontWeight:700, color:C.dark}}>{a.macro}</span>
              <span style={{...S.tag(a.impact==='positive'?C.green:a.impact==='negative'?C.red:C.gold), fontSize:9}}>
                {a.impact===('positive')?'⬆':a.impact==='negative'?'⬇':'→'}
              </span>
              <span style={{...S.tag(C.blue), fontSize:9}}>{a.weight}</span>
            </div>
            <div style={{...S.row, gap:6, marginBottom:6, flexWrap:'wrap'}}>
              {a.stocks.map((s,j)=>(
                <div key={j} style={{fontSize:9, fontWeight:600, padding:'2px 8px', background:C.blue, color:'#fff', borderRadius:4, cursor:'pointer', opacity:0.8}}>
                  {s}
                </div>
              ))}
            </div>
            <div style={{fontSize:10, color:C.mid, lineHeight:1.5}}>{a.note[lk]}</div>
          </div>
        ))}
      </Card>

      <Card title={L('Macro Stress Test','宏观压力测试')} sub={L('Factor sensitivity · 4 scenarios','因子敏感度 · 4场景')} open={open.macroImpact} onToggle={()=>toggle('macroImpact')} C={C}>
        <MacroStressTest stressData={stressData} L={L} C={C}/>
      </Card>
    </div>
  );
}

/* ── SCREENER TAB ────────────────────────────────────────────────────────── */
function HeroCard({ title, icon, accent, rows, onSeeAll, onRowClick, L, C, hide=false }) {
  if (hide) return null;

  const shownRows = rows.slice(0, 5);

  return (
    <div style={{borderRadius:12, boxShadow:SHADOW_SM, border:`1px solid ${C.border}`,
                 background:C.card, borderLeft:`3px solid ${accent}`,
                 padding:'10px 12px', height:210, display:'flex', flexDirection:'column'}}>
      <div style={{display:'flex', alignItems:'center', gap:6, fontSize:11,
                   fontWeight:700, color:C.dark, marginBottom:6, height:20}}>
        {icon}<span>{title}</span>
      </div>
      <div style={{flex:1, display:'flex', flexDirection:'column', gap:1}}>
        {shownRows.length === 0
          ? <div style={{fontSize:10, color:C.mid, padding:'4px 4px'}}>{'— no data —'}</div>
          : shownRows.map((row, i) => (
              <div key={`${row.ticker || row.name || 'row'}-${i}`}
                onClick={() => onRowClick(row.ticker ? row : null)}
                style={{display:'flex', justifyContent:'space-between', alignItems:'baseline',
                        padding:'4px 4px', fontSize:11, cursor:'pointer', borderRadius:4}}
                onMouseEnter={e=>e.currentTarget.style.background=`${C.blue}0D`}
                onMouseLeave={e=>e.currentTarget.style.background='transparent'}>
                <span style={{color:C.dark, fontWeight:600, overflow:'hidden',
                              textOverflow:'ellipsis', whiteSpace:'nowrap', maxWidth:'70%', minWidth:0}}>
                  {row.name}
                </span>
                <span style={{fontFamily:MONO, fontWeight:700, color:accent, whiteSpace:'nowrap'}}>
                  {row.value}
                </span>
              </div>
            ))
        }
      </div>
      <div onClick={onSeeAll}
           style={{fontSize:10, color:C.mid, cursor:'pointer', textAlign:'right',
                   marginTop:6, padding:'2px 4px'}}
           onMouseEnter={e=>e.currentTarget.style.color=C.blue}
           onMouseLeave={e=>e.currentTarget.style.color=C.mid}>
        {L('See all →','全部 →')}
      </div>
    </div>
  );
}

function FilterPill({ text, onRemove, C }) {
  return (
    <span style={{display:'inline-flex', alignItems:'center', gap:4, padding:'3px 4px 3px 9px', borderRadius:11, background:`${C.blue}14`, color:C.blue, fontSize:11, fontWeight:600}}>
      {text}
      <span onClick={onRemove} style={{cursor:'pointer', padding:'0 5px', color:C.blue, fontSize:13, lineHeight:1, opacity:0.65}} onMouseEnter={e=>e.currentTarget.style.opacity='1'} onMouseLeave={e=>e.currentTarget.style.opacity='0.65'}>×</span>
    </span>
  );
}

function Screener({ L, lk, stocks: stocksMap, onSelect, C, liveData, universeA, universeHK }) {
  const PAGE_SIZE = 100;
  const POLL_MS   = 3000;

  const [page,       setPage]       = useState(0);
  const [sortBy,     setSortBy]     = useState('pct');
  const [sortDir,    setSortDir]    = useState('desc');
  const [mktFilter,  setMktFilter]  = useState('all');   // all | A | HK
  const [dirFilter,  setDirFilter]  = useState('all');   // all | up | dn | lu | ld
  const [searchQ,    setSearchQ]    = useState('');
  // Phase 1 universe browser: industry + PE + 涨跌幅 range filters (KR-B)
  const [industry,   setIndustry]   = useState('');      // '' = all industries
  const [peMin,      setPeMin]      = useState('');
  const [peMax,      setPeMax]      = useState('');
  const [pctMin,     setPctMin]     = useState('');      // 涨跌幅 lower bound (incl)
  const [pctMax,     setPctMax]     = useState('');      // 涨跌幅 upper bound (incl)
  const [liveQuotes, setLiveQuotes] = useState({});      // emKey → quote obj
  const [polling,    setPolling]    = useState(true);
  const [advancedExpanded, setAdvancedExpanded] = useState(false);
  const [capitalFlow, setCapitalFlow] = useState(null);
  const pollRef  = useRef(null);
  const codesRef = useRef([]);

  /* ── master list ─────────────────────────────────────────────────────────── */
  const masterList = React.useMemo(() => {
    const arr = [];
    if (universeA?.stocks)  arr.push(...universeA.stocks.map(s => ({...s, market:'A'})));
    if (universeHK?.stocks) arr.push(...universeHK.stocks.map(s => ({...s, market:'HK'})));
    return arr;
  }, [universeA, universeHK]);

  /* ── industries by stock count (descending, for filter dropdown) ─────────── */
  const industries = React.useMemo(() => {
    const counts = {};
    for (const s of masterList) {
      const ind = s.industry;
      if (ind && ind.trim()) counts[ind] = (counts[ind] || 0) + 1;
    }
    return Object.entries(counts).sort((a, b) => b[1] - a[1]);
  }, [masterList]);

  const advancedActiveCount = React.useMemo(() => [!!industry, (peMin !== '' || peMax !== ''), (pctMin !== '' || pctMax !== '')].filter(Boolean).length, [industry, peMin, peMax, pctMin, pctMax]);

  const toEMCode = s => {
    if (!s?.code) return null;
    if (s.exchange === 'SH') return `1.${s.code}`;
    if (s.exchange === 'HK') return `116.${s.code.padStart(5,'0')}`;
    return `0.${s.code}`;  // SZ / BJ
  };

  /* ── effective price (live wins over static) ─────────────────────────────── */
  const getEff = s => {
    const key = toEMCode(s);
    const lv  = key ? liveQuotes[key] : null;
    return lv
      ? { price:lv.price, pct:lv.change_pct, amt:lv.change_amt, vol:lv.volume, turn:lv.turnover, pe:lv.pe, live:true }
      : { price:s.price,  pct:s.change_pct,  amt:s.change_amt,  vol:s.volume,  turn:s.turnover,  pe:s.pe,  live:false };
  };

  /* ── market summary stats ────────────────────────────────────────────────── */
  const stats = React.useMemo(() => {
    let up=0, dn=0, fl=0, lu=0, ld=0;
    for (const s of masterList) {
      const pct = s.change_pct;
      if (pct == null) continue;
      if      (pct >= 9.9)  lu++;
      else if (pct > 0)     up++;
      else if (pct <= -9.9) ld++;
      else if (pct < 0)     dn++;
      else                  fl++;
    }
    return { up, dn, fl, lu, ld, total: masterList.length };
  }, [masterList]);

  const topMovers = React.useMemo(() => (
    masterList.map(s => ({s, eff: getEff(s)}))
      .filter(({eff}) => eff.pct != null)
      .sort((a,b) => b.eff.pct - a.eff.pct)
      .slice(0,5)
  ), [masterList, liveQuotes]);

  const topAlpha = React.useMemo(() => (
    masterList.filter(s => typeof s.alpha_score === 'number')
      .map(s => ({s, eff: getEff(s)}))
      .sort((a,b) => (b.s.alpha_score||0) - (a.s.alpha_score||0))
      .slice(0,5)
  ), [masterList, liveQuotes]);

  const topVolume = React.useMemo(() => (
    masterList.map(s => ({s, eff: getEff(s)}))
      .filter(({eff}) => eff.vol != null)
      .sort((a,b) => (b.eff.vol||0) - (a.eff.vol||0))
      .slice(0,5)
  ), [masterList, liveQuotes]);

  /* ── filter + sort ───────────────────────────────────────────────────────── */
  const filtered = React.useMemo(() => {
    let arr = masterList;
    if (mktFilter !== 'all') arr = arr.filter(s => s.market === mktFilter);
    if (searchQ.trim()) {
      const q = searchQ.toLowerCase();
      // Search now also matches industry text
      arr = arr.filter(s =>
        s.name?.toLowerCase().includes(q) ||
        s.code?.includes(q) ||
        s.ticker?.toLowerCase().includes(q) ||
        s.industry?.toLowerCase().includes(q)
      );
    }
    if (dirFilter === 'up') arr = arr.filter(s => (s.change_pct ?? 0) > 0);
    if (dirFilter === 'dn') arr = arr.filter(s => (s.change_pct ?? 0) < 0);
    if (dirFilter === 'lu') arr = arr.filter(s => (s.change_pct ?? 0) >= 9.9);
    if (dirFilter === 'ld') arr = arr.filter(s => (s.change_pct ?? 0) <= -9.9);
    // Phase 1 universe browser filters (KR-B)
    if (industry) arr = arr.filter(s => s.industry === industry);
    const peMinN = parseFloat(peMin);
    if (!isNaN(peMinN)) arr = arr.filter(s => s.pe != null && s.pe > 0 && s.pe >= peMinN);
    const peMaxN = parseFloat(peMax);
    if (!isNaN(peMaxN)) arr = arr.filter(s => s.pe != null && s.pe > 0 && s.pe <= peMaxN);
    const pctMinN = parseFloat(pctMin);
    if (!isNaN(pctMinN)) arr = arr.filter(s => (s.change_pct ?? -999) >= pctMinN);
    const pctMaxN = parseFloat(pctMax);
    if (!isNaN(pctMaxN)) arr = arr.filter(s => (s.change_pct ?? 999) <= pctMaxN);

    return [...arr].sort((a, b) => {
      const ea = getEff(a), eb = getEff(b);
      let va, vb;
      if      (sortBy==='pct')    { va=ea.pct;          vb=eb.pct; }
      else if (sortBy==='px')     { va=ea.price;        vb=eb.price; }
      else if (sortBy==='vol')    { va=ea.vol;          vb=eb.vol; }
      else if (sortBy==='turn')   { va=ea.turn;         vb=eb.turn; }
      else if (sortBy==='mktcap') { va=a.market_cap;    vb=b.market_cap; }
      else if (sortBy==='pe')     { va=ea.pe;           vb=eb.pe; }
      else if (sortBy==='alpha')  { va=a.alpha_score;   vb=b.alpha_score; }
      else                        { va=ea.pct;          vb=eb.pct; }
      if (va == null) return 1;
      if (vb == null) return -1;
      return sortDir==='desc' ? vb - va : va - vb;
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [masterList, mktFilter, searchQ, dirFilter, sortBy, sortDir, liveQuotes,
      industry, peMin, peMax, pctMin, pctMax]);

  const totalPages = Math.ceil(filtered.length / PAGE_SIZE);
  const visible    = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  // reset to page 0 on filter change
  useEffect(() => { setPage(0); }, [mktFilter, dirFilter, searchQ, industry, peMin, peMax, pctMin, pctMax]);

  useEffect(() => { if (advancedActiveCount > 0) setAdvancedExpanded(true); }, [advancedActiveCount]);

  useEffect(() => {
    fetch('data/capital_flow.json')
      .then(r => r.json())
      .then(d => {
        if (d?._status === 'endpoint_unavailable') console.warn('[capital-flow] endpoint unavailable');
        setCapitalFlow(d);
      })
      .catch(() => {
        console.warn('[capital-flow] capital_flow.json fetch failed');
        setCapitalFlow({ _status: 'fetch_failed' });
      });
  }, []);

  /* ── live quote polling — only visible stocks ────────────────────────────── */
  // 2026-05-02 Phase 3 audit fix: previous deps [page, filtered.length, polling]
  // missed cases where filter changes but result count is coincidentally identical
  // (e.g., switching industries with same count) — codesRef stayed stale, polling
  // fetched wrong tickers. Use string signature of visible codes so any actual
  // ticker change triggers re-poll. React's === on strings compares by value.
  const visibleCodesSig = visible.map(toEMCode).filter(Boolean).join(',');

  useEffect(() => {
    codesRef.current = visibleCodesSig ? visibleCodesSig.split(',') : [];

    const doPoll = async () => {
      if (!codesRef.current.length || !polling) return;
      try {
        const base = import.meta.env.VITE_API_BASE || 'https://equity-research-ten.vercel.app';
        const r = await fetch(`${base}/api/live-quotes?codes=${codesRef.current.join(',')}`);
        if (!r.ok) return;
        const d = await r.json();
        if (d.quotes?.length) {
          setLiveQuotes(prev => {
            const next = {...prev};
            for (const q of d.quotes) next[q.em_key] = q;
            return next;
          });
        }
      } catch {}
    };

    doPoll();
    clearInterval(pollRef.current);
    if (polling) pollRef.current = setInterval(doPoll, POLL_MS);
    return () => clearInterval(pollRef.current);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visibleCodesSig, polling]);

  /* ── helpers ─────────────────────────────────────────────────────────────── */
  const formatVolumeShort = vol => {
    if (vol == null) return '—';
    if (vol >= 1e8) return `${(vol/1e8).toFixed(1)}亿`;
    if (vol >= 1e4) return `${Math.round(vol/1e4)}万`;
    return String(Math.round(vol));
  };

  const formatFlowYuan = (yuan) => {
    if (yuan == null || isNaN(yuan)) return '—';
    const sign = yuan >= 0 ? '+' : '−';
    const abs = Math.abs(yuan);
    if (abs >= 1e8) return `${sign}${(abs/1e8).toFixed(1)}亿`;
    if (abs >= 1e4) return `${sign}${Math.round(abs/1e4)}万`;
    return `${sign}${Math.round(abs)}`;
  };

  const fmtVol = n => {
    if (n == null) return '—';
    if (n >= 1e8) return `${(n/1e8).toFixed(1)}亿`;
    if (n >= 1e4) return `${(n/1e4).toFixed(1)}万`;
    return String(Math.round(n));
  };

  const ColHd = ({ field, label, align='right' }) => (
    <div style={{textAlign:align, cursor:'pointer', userSelect:'none', whiteSpace:'nowrap',
                 color: sortBy===field ? C.blue : 'inherit', fontWeight: sortBy===field ? 700 : 600}}
         onClick={() => { if (sortBy===field) setSortDir(d=>d==='desc'?'asc':'desc'); else { setSortBy(field); setSortDir('desc'); } }}>
      {label}{sortBy===field ? (sortDir==='desc'?'↓':'↑') : ''}
    </div>
  );

  const FBtn = ({ val, stateVal, setter, color, children }) => (
    <button onClick={()=>setter(val)} style={{
      fontSize:10, padding:'3px 9px', borderRadius:16,
      border:`1px solid ${val===stateVal ? (color||C.blue) : C.border}`,
      background: val===stateVal ? `${color||C.blue}1A` : 'transparent',
      color: val===stateVal ? (color||C.blue) : C.mid,
      fontWeight: val===stateVal ? 700 : 400, cursor:'pointer',
    }}>{children}</button>
  );

  const liveCount = Object.keys(liveQuotes).length;
  const hasAlphaScores = masterList.some(s => s.alpha_score != null && s.alpha_score > 0);
  const COLS = hasAlphaScores
    ? '32px 1fr 80px 80px 80px 80px 46px 10px'   // with α column
    : '32px 1fr 80px 80px 80px 80px 10px';        // without (scores not yet generated)

  /* ── empty state ─────────────────────────────────────────────────────────── */
  if (!universeA && !universeHK) return (
    <div>
      {/* loading skeleton — card chrome consistent with rendered table */}
      <div style={{background:C.card, border:`1px solid ${C.border}`, borderRadius:10, overflow:'hidden', marginBottom:10}}>
        {/* header row (placeholder) */}
        <div style={{display:'grid', gridTemplateColumns:COLS, gap:8, padding:'8px 12px', borderBottom:`1px solid ${C.border}`, background:C.soft, fontSize:9, color:C.mid, fontWeight:600, letterSpacing:'0.04em'}}>
          <span/><span>{L('Loading…','加载中…')}</span><span/><span/><span/><span/>{hasAlphaScores && <span/>}<span/>
        </div>
        {/* 6 skeleton rows */}
        {Array.from({length:6}).map((_, i) => (
          <div key={i} style={{display:'grid', gridTemplateColumns:COLS, gap:8, padding:'8px 12px', borderBottom: i < 5 ? `1px solid ${C.border}` : 'none', alignItems:'center', background: i%2===0 ? 'transparent' : C.soft}}>
            {Array.from({length: hasAlphaScores ? 8 : 7}).map((__, j) => (
              <div key={j} style={{height:14, background:C.soft, borderRadius:3, animation:'pulse 1.5s ease-in-out infinite', animationDelay: `${(i*0.1) + (j*0.05)}s`, opacity:0.6}}></div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );

  return (
    <div>
      {/* ── SLIM LIVE PULSE BAR ───────────────────────────────────────────── */}
      <div style={{background:C.card, border:`1px solid ${C.border}`, borderRadius:10,
                   padding:'6px 16px', marginBottom:8, height:32, display:'flex',
                   alignItems:'center', gap:14, flexWrap:'wrap', fontSize:11}}>
        <div style={{fontSize:11, color: polling ? C.green : C.mid,
                     display:'flex', alignItems:'center', gap:5, whiteSpace:'nowrap'}}>
          {polling
            ? <span style={{width:6,height:6,borderRadius:'50%',background:C.green,display:'inline-block'}}/>
            : <WifiOff size={11}/>
          }
          <span>
            {polling ? L('Live','实时') : L('Paused','暂停中')} · {liveCount} {L('refreshed','只已刷新')} · {stats.total.toLocaleString()} {L('stocks','只')}
          </span>
        </div>
        <div style={{display:'flex', gap:10, flexWrap:'wrap', alignItems:'center'}}>
          {[
            { val:'lu', label:L('Limit↑','涨停'), count:stats.lu,  clr:'#EF4444' },
            { val:'up', label:L('Up','上涨'),      count:stats.up,  clr:C.green },
            { val:'',   label:L('Flat','平家'),    count:stats.fl,  clr:C.mid },
            { val:'dn', label:L('Down','下跌'),    count:stats.dn,  clr:C.red },
            { val:'ld', label:L('Limit↓','跌停'), count:stats.ld,  clr:'#9333EA' },
          ].map(({val, label, count, clr}) => (
            <span key={val||'fl'} onClick={()=>val&&setDirFilter(val===dirFilter?'all':val)}
                  style={{cursor:val?'pointer':'default', display:'flex', gap:4, alignItems:'baseline'}}>
              <span style={{fontSize:10, fontWeight:700, color:clr, fontFamily:MONO}}>{count}</span>
              <span style={{fontSize:9, fontWeight:400, color:C.mid}}>{label}</span>
            </span>
          ))}
        </div>
        <div style={{marginLeft:'auto', display:'flex', alignItems:'center', gap:8}}>
          <button onClick={()=>setPolling(p=>!p)} style={{
            fontSize:10, padding:'2px 8px', borderRadius:10,
            border:`1px solid ${C.border}`, background:'transparent', color:C.mid, cursor:'pointer',
          }}>
            {polling ? <>⏸ {L('Pause','暂停')}</> : <>▶ {L('Resume','恢复')}</>}
          </button>
        </div>
      </div>

      {/* ── HERO STANDOUTS ────────────────────────────────────────────────── */}
      <div style={{display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:10, marginBottom:10}}>
        <HeroCard
          title={L('Today Top 5 Movers','今日涨幅 Top 5')}
          icon={<Flame size={14}/>}
          accent={C.red}
          rows={topMovers.map(({s,eff}) => ({
            name: s.name,
            ticker: s.ticker,
            value: eff.pct != null ? `${eff.pct >= 0 ? '+' : ''}${eff.pct.toFixed(2)}%` : '—',
          }))}
          onSeeAll={() => { setSortBy('pct'); setSortDir('desc'); }}
          onRowClick={s => { if (s?.ticker) onSelect(s.ticker); }}
          L={L}
          C={C}
        />
        <HeroCard
          title={L('α Leaders Top 5','α-龙头 Top 5')}
          icon={<Sparkles size={14}/>}
          accent={C.gold}
          rows={topAlpha.map(({s}) => ({
            name: s.name,
            ticker: s.ticker,
            value: `α ${s.alpha_score}`,
          }))}
          onSeeAll={() => { setSortBy('alpha'); setSortDir('desc'); }}
          onRowClick={s => { if (s?.ticker) onSelect(s.ticker); }}
          L={L}
          C={C}
          hide={!hasAlphaScores}
        />
        <HeroCard
          title={L('Top 5 by Volume','量爆 Top 5')}
          icon={<BarChart3 size={14}/>}
          accent={C.blue}
          rows={topVolume.map(({s,eff}) => ({
            name: s.name,
            ticker: s.ticker,
            value: formatVolumeShort(eff.vol),
          }))}
          onSeeAll={() => { setSortBy('vol'); setSortDir('desc'); }}
          onRowClick={s => { if (s?.ticker) onSelect(s.ticker); }}
          L={L}
          C={C}
        />
      </div>

      {capitalFlow && capitalFlow._status !== 'fetch_failed' && capitalFlow._status !== 'endpoint_unavailable' && (
        <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:10, marginBottom:10}}>
          <HeroCard
            title={L('Hot Concepts (Net Flow)','今日热门概念 Top 5')}
            icon={<Flame size={14}/>}
            accent={C.red}
            rows={(capitalFlow.hot_concepts || []).slice(0, 5).map(c => ({
              name: c.name,
              ticker: c.ts_code,
              value: formatFlowYuan(c.net_inflow_yuan),
            }))}
            onSeeAll={() => {}}
            onRowClick={() => {}}
            L={L}
            C={C}
            hide={!capitalFlow.hot_concepts || capitalFlow.hot_concepts.length === 0}
          />
          <HeroCard
            title={L('Hot Industries (Net Flow)','今日行业资金流向 Top 5')}
            icon={<BarChart3 size={14}/>}
            accent={C.red}
            rows={(capitalFlow.hot_industries || []).slice(0, 5).map(i => ({
              name: i.name,
              ticker: i.ts_code,
              value: formatFlowYuan(i.net_inflow_yuan),
            }))}
            onSeeAll={() => {}}
            onRowClick={() => {}}
            L={L}
            C={C}
            hide={!capitalFlow.hot_industries || capitalFlow.hot_industries.length === 0}
          />
        </div>
      )}

      {/* ── PRIMARY FILTER ROW ─────────────────────────────────────────────── */}
      <div style={{background:C.card, border:`1px solid ${C.border}`, borderRadius:10, padding:'10px 14px', marginBottom:8, display:'flex', gap:8, flexWrap:'wrap', alignItems:'center'}}>
        {/* Search */}
        <div style={{position:'relative'}}>
          <Search size={11} style={{position:'absolute', left:8, top:'50%', transform:'translateY(-50%)', color:C.mid}}/>
          <input value={searchQ} onChange={e=>setSearchQ(e.target.value)}
            placeholder={L('Name / Code…','名称/代码…')}
            style={{paddingLeft:24, paddingRight:8, height:28, width:160, fontSize:11,
                    background:C.soft, border:`1px solid ${C.border}`, borderRadius:6,
                    color:C.dark, outline:'none'}}/>
        </div>
        {/* Market */}
        <div style={{display:'flex', gap:4}}>
          <FBtn val='all' stateVal={mktFilter} setter={setMktFilter}>{L('All','全部')}</FBtn>
          <FBtn val='A'   stateVal={mktFilter} setter={setMktFilter}>A股</FBtn>
          <FBtn val='HK'  stateVal={mktFilter} setter={setMktFilter}>港股</FBtn>
        </div>
        {/* Direction */}
        <div style={{display:'flex', gap:4}}>
          <FBtn val='all' stateVal={dirFilter} setter={setDirFilter}>{L('All','全部')}</FBtn>
          <FBtn val='lu'  stateVal={dirFilter} setter={setDirFilter} color='#EF4444'>{L('↑Limit','涨停')}</FBtn>
          <FBtn val='up'  stateVal={dirFilter} setter={setDirFilter} color={C.green}>{L('Up','上涨')}</FBtn>
          <FBtn val='dn'  stateVal={dirFilter} setter={setDirFilter} color={C.red}>{L('Down','下跌')}</FBtn>
          <FBtn val='ld'  stateVal={dirFilter} setter={setDirFilter} color='#9333EA'>{L('↓Limit','跌停')}</FBtn>
        </div>
        {/* Alpha sort shortcut */}
        {hasAlphaScores && (
          <div style={{display:'flex', gap:4}}>
            <FBtn val='alpha' stateVal={sortBy} setter={v=>{setSortBy(v);setSortDir('desc');}} color={C.gold}>
              α {L('Top','排名')}
            </FBtn>
          </div>
        )}

        <button style={{height:24, fontSize:11, padding:'0 10px', borderRadius:6, background: advancedActiveCount > 0 ? `${C.blue}14` : 'transparent', border:`1px solid ${advancedActiveCount > 0 ? C.blue : C.border}`, color: advancedActiveCount > 0 ? C.blue : C.mid, cursor:'pointer', fontWeight: advancedActiveCount > 0 ? 700 : 400, display:'flex', alignItems:'center', gap:4, whiteSpace:'nowrap'}}
          onClick={() => setAdvancedExpanded(v => !v)}>
          {advancedExpanded || advancedActiveCount > 0 ? '▲' : '▼'} {L('Advanced','高级')}{advancedActiveCount > 0 && ` (${advancedActiveCount})`}
        </button>

        <div style={{marginLeft:'auto', fontSize:10, color:C.mid}}>
          {filtered.length.toLocaleString()} {L('stocks','只')}
          {totalPages > 1 && ` · P${page+1}/${totalPages}`}
        </div>
      </div>

      {/* ── ADVANCED FILTER ROW ────────────────────────────────────────────── */}
      {advancedExpanded && (
      <div style={{background:C.card, border:`1px solid ${C.border}`, borderTop:`1px dashed ${C.border}`, borderRadius:10, padding:'8px 14px', marginBottom:8, display:'flex', gap:14, flexWrap:'wrap', alignItems:'center'}}>
        {/* Industry filter (Phase 1 universe browser KR-B) */}
        {industries.length > 0 && (
          <select value={industry} onChange={e=>setIndustry(e.target.value)}
            style={{height:24, fontSize:10, padding:'0 6px',
                    background:industry?`${C.blue}1A`:C.soft,
                    border:`1px solid ${industry?C.blue:C.border}`, borderRadius:6,
                    color:industry?C.blue:C.dark, cursor:'pointer', outline:'none',
                    fontWeight:industry?700:400, maxWidth:180}}>
            <option value="">{L('All industries','全行业')}</option>
            {industries.slice(0, 100).map(([ind, n]) => (
              <option key={ind} value={ind}>{ind} ({n})</option>
            ))}
          </select>
        )}

        {/* PE range */}
        <div style={{display:'flex', alignItems:'center', gap:3}}>
          <span style={{fontSize:10, color:C.mid}}>PE</span>
          <input value={peMin} onChange={e=>setPeMin(e.target.value)} type="number"
            placeholder="min" step="any"
            style={{width:48, height:24, fontSize:10, padding:'0 4px',
                    background:C.soft, border:`1px solid ${C.border}`, borderRadius:5,
                    color:C.dark, outline:'none', textAlign:'center'}}/>
          <span style={{fontSize:10, color:C.mid}}>-</span>
          <input value={peMax} onChange={e=>setPeMax(e.target.value)} type="number"
            placeholder="max" step="any"
            style={{width:48, height:24, fontSize:10, padding:'0 4px',
                    background:C.soft, border:`1px solid ${C.border}`, borderRadius:5,
                    color:C.dark, outline:'none', textAlign:'center'}}/>
        </div>

        {/* 涨跌幅 range */}
        <div style={{display:'flex', alignItems:'center', gap:3}}>
          <span style={{fontSize:10, color:C.mid}}>Δ%</span>
          <input value={pctMin} onChange={e=>setPctMin(e.target.value)} type="number"
            placeholder="min" step="any"
            style={{width:48, height:24, fontSize:10, padding:'0 4px',
                    background:C.soft, border:`1px solid ${C.border}`, borderRadius:5,
                    color:C.dark, outline:'none', textAlign:'center'}}/>
          <span style={{fontSize:10, color:C.mid}}>-</span>
          <input value={pctMax} onChange={e=>setPctMax(e.target.value)} type="number"
            placeholder="max" step="any"
            style={{width:48, height:24, fontSize:10, padding:'0 4px',
                    background:C.soft, border:`1px solid ${C.border}`, borderRadius:5,
                    color:C.dark, outline:'none', textAlign:'center'}}/>
        </div>
      </div>
      )}

      {/* ── ACTIVE FILTER PILLS ────────────────────────────────────────────── */}
      {(searchQ || advancedActiveCount > 0) && (
        <div style={{display:'flex', gap:6, padding:'6px 14px', marginBottom:8, alignItems:'center', flexWrap:'wrap', fontSize:11}}>
          <span style={{fontSize:10, color:C.mid, fontWeight:600}}>{L('Filtering:','正在筛选:')}</span>
          {searchQ && (
            <FilterPill text={`${L('Search:','搜索:')} ${searchQ}`} onRemove={() => setSearchQ('')} C={C}/>
          )}
          {industry && (
            <FilterPill text={`${L('Industry','行业')}: ${industry}`} onRemove={() => setIndustry('')} C={C}/>
          )}
          {(peMin !== '' || peMax !== '') && (
            <FilterPill text={`PE: ${peMin || '?'}–${peMax || '?'}`} onRemove={() => { setPeMin(''); setPeMax(''); }} C={C}/>
          )}
          {(pctMin !== '' || pctMax !== '') && (
            <FilterPill text={`Δ%: ${pctMin || '?'}–${pctMax || '?'}`} onRemove={() => { setPctMin(''); setPctMax(''); }} C={C}/>
          )}
          <button style={{height:22, fontSize:10, padding:'0 8px', borderRadius:11, background:'transparent', border:`1px solid ${C.border}`, color:C.mid, cursor:'pointer', marginLeft:4}}
            onClick={() => { setSearchQ(''); setIndustry(''); setPeMin(''); setPeMax(''); setPctMin(''); setPctMax(''); }}>
            {L('Clear all','清除全部')}
          </button>
        </div>
      )}

      {/* ── TABLE ──────────────────────────────────────────────────────────── */}
      <div style={{background:C.card, border:`1px solid ${C.border}`, borderRadius:10, overflow:'hidden', marginBottom:10}}>
        {/* header row */}
        <div style={{display:'grid', gridTemplateColumns:COLS, gap:'0 6px',
                     padding:'7px 12px', background:C.soft, borderBottom:`1px solid ${C.border}`,
                     fontSize:10, color:C.mid}}>
          <div style={{color:C.mid}}>#</div>
          <div style={{color:C.mid}}>{L('Name · Code','名称 · 代码')}</div>
          <ColHd field='px'     label={L('Price','价格')}/>
          <ColHd field='pct'    label={L('Chg%','涨跌%')}/>
          <ColHd field='vol'    label={L('Volume','量')}/>
          <ColHd field='turn'   label={L('Turnover','额')}/>
          {hasAlphaScores && <ColHd field='alpha' label='α'/>}
          <div></div>
        </div>

        {visible.length === 0
          ? <div style={{textAlign:'center', padding:'40px 20px', color:C.mid}}>
              <SearchX size={32} style={{marginBottom:10, color:C.mid}}/>
              <div style={{fontSize:14, color:C.dark, fontWeight:600, marginBottom:14}}>
                {L('No stocks match the current filters','没有股票匹配当前筛选')}
              </div>
              <button onClick={() => { setSearchQ(''); setIndustry(''); setPeMin(''); setPeMax(''); setPctMin(''); setPctMax(''); }}
                style={{padding:'8px 18px', fontSize:12, borderRadius:6, background:'transparent', border:`1px solid ${C.blue}`, color:C.blue, cursor:'pointer', fontWeight:600}}>
                {L('Clear all filters →','清除所有筛选 →')}
              </button>
            </div>
          : visible.map((s, i) => {
              const eff  = getEff(s);
              const pct  = eff.pct;
              const clr  = pct == null ? C.mid : pct > 0 ? C.green : pct < 0 ? C.red : C.mid;
              const isLU = pct != null && pct >= 9.9;
              const isLD = pct != null && pct <= -9.9;
              const rank = page * PAGE_SIZE + i + 1;
              const oddBg = i%2===0 ? 'transparent' : C.soft;
              const accent = isLU ? C.red
                : isLD ? '#9333EA'
                : (typeof s.alpha_score === 'number' && s.alpha_score >= 65) ? C.gold
                : 'transparent';

              return (
                <div key={s.ticker}
                  onClick={() => onSelect(s.ticker)}
                  style={{display:'grid', gridTemplateColumns:COLS, gap:'0 6px',
                          padding:'6px 12px 6px 8px',
                          borderBottom:`1px solid ${C.border}`,
                          borderLeft:`4px solid ${accent}`,
                          cursor:'pointer', background:oddBg, transition:'background .1s'}}
                  onMouseEnter={e=>e.currentTarget.style.background=`${C.blue}0D`}
                  onMouseLeave={e=>e.currentTarget.style.background=oddBg}>

                  {/* rank */}
                  <div style={{fontSize:10, color:C.mid, alignSelf:'center'}}>{rank}</div>

                  {/* name + code */}
                  <div style={{alignSelf:'center', minWidth:0}}>
                    <div style={{display:'flex', alignItems:'baseline', gap:6, minWidth:0}}>
                      <div style={{fontSize:11, fontWeight:600, color:C.dark,
                                   overflow:'hidden', textOverflow:'ellipsis',
                                   whiteSpace:'nowrap', flex:1, minWidth:0}}>
                        {s.name}
                      </div>
                      {s.industry && (
                        <span onClick={e=>{e.stopPropagation(); setIndustry(s.industry);}}
                          style={{...S.tag(C.blue), cursor:'pointer', flexShrink:0,
                                  whiteSpace:'nowrap'}}
                          title={L(`Filter by ${s.industry}`,`按"${s.industry}"过滤`)}
                          onMouseEnter={e=>e.currentTarget.style.background=`${C.blue}24`}
                          onMouseLeave={e=>e.currentTarget.style.background=`${C.blue}14`}>
                          {s.industry}
                        </span>
                      )}
                    </div>
                    <div style={{fontSize:9, color:C.mid, fontFamily:MONO,
                                 display:'flex', gap:4, alignItems:'baseline'}}>
                      <span>{s.code}</span>
                      <span style={{opacity:0.6}}>{s.market==='HK'?'港':s.exchange}</span>
                    </div>
                  </div>

                  {/* price */}
                  <div style={{textAlign:'right', alignSelf:'center', fontFamily:MONO,
                               fontSize:11, fontWeight:600, color:clr}}>
                    {eff.price != null ? eff.price.toFixed(eff.price < 10 ? 3 : 2) : '—'}
                  </div>

                  {/* chg% */}
                  <div style={{textAlign:'right', alignSelf:'center', fontFamily:MONO,
                               fontSize:11, fontWeight:700, color:clr}}>
                    {pct != null ? `${pct>0?'+':''}${pct.toFixed(2)}%` : '—'}
                  </div>

                  {/* volume */}
                  <div style={{textAlign:'right', alignSelf:'center', fontSize:10, color:C.mid, fontFamily:MONO}}>
                    {fmtVol(eff.vol)}
                  </div>

                  {/* turnover */}
                  <div style={{textAlign:'right', alignSelf:'center', fontSize:10, color:C.mid, fontFamily:MONO}}>
                    {fmtVol(eff.turn)}
                  </div>

                  {/* α score (Barra-lite) */}
                  {hasAlphaScores && (() => {
                    const sc = s.alpha_score;
                    const scClr = sc == null || sc === 0 ? C.mid
                      : sc >= 65 ? C.green
                      : sc >= 50 ? C.blue
                      : sc >= 35 ? C.mid
                      : C.red;
                    return (
                      <div style={{textAlign:'right', alignSelf:'center', fontSize:10,
                                   fontFamily:MONO, fontWeight:700, color:scClr}}>
                        {sc != null && sc > 0 ? sc.toFixed(0) : '—'}
                      </div>
                    );
                  })()}

                  {/* live dot */}
                  <div style={{alignSelf:'center', textAlign:'center'}}>
                    {eff.live && <span style={{width:5, height:5, borderRadius:'50%',
                                              background:C.green, display:'inline-block'}}/>}
                  </div>
                </div>
              );
            })
        }
      </div>

      {/* ── PAGINATION ─────────────────────────────────────────────────────── */}
      {totalPages > 1 && (
        <div style={{display:'flex', alignItems:'center', justifyContent:'center', gap:8, paddingBottom:8}}>
          <button onClick={()=>setPage(p=>Math.max(0,p-1))} disabled={page===0}
            style={{padding:'4px 12px', borderRadius:6, border:`1px solid ${C.border}`,
                    background:'transparent', color:page===0?C.mid:C.dark,
                    cursor:page===0?'default':'pointer', fontSize:11, display:'flex', alignItems:'center', gap:2}}>
            <ChevronLeft size={12}/> {L('Prev','上页')}
          </button>
          <span style={{fontSize:11, color:C.mid}}>
            {(page*PAGE_SIZE+1).toLocaleString()}–{Math.min((page+1)*PAGE_SIZE, filtered.length).toLocaleString()}
            {' '}{L('of','/共')}{' '}{filtered.length.toLocaleString()}
          </span>
          <button onClick={()=>setPage(p=>Math.min(totalPages-1,p+1))} disabled={page===totalPages-1}
            style={{padding:'4px 12px', borderRadius:6, border:`1px solid ${C.border}`,
                    background:'transparent', color:page===totalPages-1?C.mid:C.dark,
                    cursor:page===totalPages-1?'default':'pointer', fontSize:11, display:'flex', alignItems:'center', gap:2}}>
            {L('Next','下页')} <ChevronRight size={12}/>
          </button>
        </div>
      )}
    </div>
  );
}

/* ── RESEARCH TAB ────────────────────────────────────────────────────────── */
function Research({ L, lk, ticker, stocks: stocksMap, open, toggle, C, liveData, eqrData, rdcfData, pulse, pulseLoading, onRunPulse, signalsData, scissorsData, liData, egapScores }) {
  const [tushareData, setTushareData] = useState({});
  const [chipData, setChipData] = useState({});
  const [consensusData, setConsensusData] = useState({});
  const [lhbData, setLhbData] = useState({});
  useEffect(() => {
    if (!ticker) return;
    const base = DATA_BASE;
    const fetchJson = (path) => fetch(base + path)
      .then(r => r.ok ? r.json() : null)
      .catch(() => null);
    const lhbFetches = fetchJson('data/watchlist.json')
      .then(wl => {
        const watchlistTickers = Object.keys(wl?.tickers || {});
        const targets = [...new Set([ticker, ...watchlistTickers].filter(Boolean))];
        return Promise.all(targets.map(t =>
          fetchJson(`data/lhb/${t}.json`).then(data => ({ ticker: t, data }))
        ));
      })
      .catch(() => Promise.all([
        fetchJson(`data/lhb/${ticker}.json`).then(data => ({ ticker, data }))
      ]));
    Promise.all([
      fetchJson(`data/tushare/${ticker}.json`),
      fetchJson(`data/chip_distribution/${ticker}.json`),
      fetchJson(`data/consensus_forecast/${ticker}.json`),
      lhbFetches,
    ]).then(([tushare, chip, consensus, lhbArr]) => {
      setTushareData(prev => ({ ...prev, [ticker]: tushare }));
      setChipData(prev => ({ ...prev, [ticker]: chip }));
      setConsensusData(prev => ({ ...prev, [ticker]: consensus }));
      const lhbDataMap = { [ticker]: null };
      (lhbArr || []).forEach(({ ticker: tk, data }) => { if (data) lhbDataMap[tk] = data; });
      setLhbData(prev => ({ ...prev, ...lhbDataMap }));
    });
  }, [ticker]);

  const allS = stocksMap || STOCKS;
  if (!ticker || !allS[ticker]) return <div style={{color:C.mid}}>{L('Select a stock','选择股票')}</div>;
  const s = allS[ticker];
  const eqr      = eqrData?.[ticker]  || null;
  const rdcf     = rdcfData?.[ticker] || null;
  const scissors = scissorsData?.[ticker] || null;
  // Deep Research stocks have no live data files — only AI-generated fields
  const isDynamic = !STOCKS[ticker] && !!allS[ticker];

  const decompData = Object.entries(s.decomp).map(([k,v])=>({name:k.replace(/_/g,' '), value:v.s}));
  const sectorIdx = PORTFOLIO.sectors.findIndex(sc=>sc.name===s.sector);
  const sectorColor = sectorIdx>=0 ? [C.blue,'#7B6BA5',C.gold,C.green,C.red][sectorIdx] : C.mid;

  // ── Live data helpers ──────────────────────────────────────────────────────
  const live   = liveData?.yahoo?.[ticker];
  const livePx = live?.price;
  const liveFn = live?.fundamentals;
  const isHK   = ticker.endsWith('.HK');
  const curr   = isHK ? 'HK$' : '¥';

  const fmtPrice = livePx?.last != null
    ? `${curr}${livePx.last.toFixed(2)}`
    : s.price;

  const fmtChg = livePx?.change_pct != null
    ? livePx.change_pct
    : null;

  const fmtMktCap = (() => {
    const mc = liveFn?.market_cap;
    if (!mc) return s.mktcap;
    const b = mc / 1e9;
    return b >= 1000 ? `${curr}${(mc/1e12).toFixed(2)}T` : `${curr}${b.toFixed(1)}B`;
  })();

  const liveFin = {
    rev:      liveFn?.revenue      ? `${curr}${(liveFn.revenue/1e9).toFixed(1)}B`       : s.fin?.rev,
    revGr:    liveFn?.revenue_growth != null ? `${liveFn.revenue_growth>0?'+':''}${(liveFn.revenue_growth*100).toFixed(0)}%` : s.fin?.revGr,
    gm:       liveFn?.gross_margin != null   ? `${(liveFn.gross_margin*100).toFixed(1)}%` : s.fin?.gm,
    pe:       liveFn?.pe_trailing  ?? s.fin?.pe,
    ev_ebitda:liveFn?.ev_ebitda    ?? s.fin?.ev_ebitda,
    fcf:      liveFn?.free_cash_flow != null ? `${curr}${(liveFn.free_cash_flow/1e9).toFixed(1)}B` : s.fin?.fcf,
  };
  const expandedStock = ticker;

  const peakAnalysis = (peakPrice, currentPrice, L) => {
    if (!peakPrice || !currentPrice) return '';
    if (peakPrice > currentPrice) return L(`Peak ${peakPrice.toFixed(2)} above current — likely resistance`, `峰值 ${peakPrice.toFixed(2)} 在现价之上 — 压力位`);
    if (peakPrice < currentPrice) return L(`Peak ${peakPrice.toFixed(2)} below current — likely support`, `峰值 ${peakPrice.toFixed(2)} 在现价之下 — 支撑位`);
    return L('Peak at current price', '峰值在现价附近');
  };

  const formatRevenue = (yuan) => {
    const n = finiteNumber(yuan);
    if (n == null) return '—';
    const abs = Math.abs(n);
    const sign = n < 0 ? '−' : '';
    if (abs >= 1e8) return `${sign}${(abs/1e8).toFixed(1)}亿`;
    if (abs >= 1e4) return `${sign}${Math.round(abs/1e4)}万`;
    return `${sign}${Math.round(abs)}`;
  };

  const formatLhbAmount = (yuan) => {
    const n = finiteNumber(yuan);
    if (n == null) return '—';
    const sign = n >= 0 ? '+' : '−';
    const abs = Math.abs(n);
    if (abs >= 1e8) return `${sign}${(abs/1e8).toFixed(1)}亿`;
    if (abs >= 1e4) return `${sign}${Math.round(abs/1e4)}万`;
    return `${sign}${Math.round(abs)}`;
  };

  const TushareDataCard = ({ data, ticker }) => {
    const cardStyle = {
      borderRadius:12,
      boxShadow:SHADOW_SM,
      border:`1px solid ${C.border}`,
      background:C.card,
      padding:12,
      marginBottom:8,
    };
    if (!data) {
      return (
        <div style={{...cardStyle, color:C.mid, fontSize:11}}>
          Loading Tushare data...
        </div>
      );
    }
    if (data._status === 'skipped') {
      return (
        <div style={{...cardStyle}}>
          <div style={{fontSize:11, fontWeight:600, color:C.dark}}>Tushare 6000 数据</div>
          <div style={{fontSize:10, color:C.mid, marginTop:6}}>
            Tushare 6000 数据 — 仅 A 股 (HK ticker placeholder)
          </div>
        </div>
      );
    }
    if (data._status === 'failed') {
      return (
        <div style={{...cardStyle}}>
          <div style={{fontSize:11, fontWeight:600, color:C.dark}}>Tushare 6000 数据</div>
          <div style={{fontSize:10, color:C.red, marginTop:6}}>
            {data._error || 'Tushare data unavailable'}
          </div>
        </div>
      );
    }

    const dailyBasic = data.data?.daily_basic?.rows?.[0] || null;
    const daily = data.data?.daily?.rows?.[0] || null;
    const pe = dailyBasic?.pe != null ? Number(dailyBasic.pe).toFixed(1) : '—';
    const pb = dailyBasic?.pb != null ? Number(dailyBasic.pb).toFixed(1) : '—';
    const turnover = dailyBasic?.turnover_rate != null ? Number(dailyBasic.turnover_rate).toFixed(2) + '%' : '—';
    const close = daily?.close != null ? Number(daily.close).toFixed(2) : '—';
    const change = daily?.change != null ? Number(daily.change).toFixed(2) : '—';
    const changeColor = Number(daily?.change || 0) >= 0 ? C.green : C.red;

    return (
      <div style={cardStyle}>
        <div style={{display:'flex', justifyContent:'space-between', alignItems:'flex-start', gap:10, marginBottom:10}}>
          <div>
            <div style={{fontSize:11, fontWeight:600, color:C.dark}}>Tushare 6000 数据</div>
            <div style={{fontSize:9, color:C.mid}}>refreshed at {data.fetched_at}</div>
          </div>
          <div style={{fontSize:9, color:C.mid, fontFamily:MONO}}>{ticker}</div>
        </div>
        <div style={{display:'grid', gridTemplateColumns:'repeat(3, 1fr)', gap:8, marginBottom:10}}>
          {[
            ['PE', pe],
            ['PB', pb],
            ['换手率', turnover],
          ].map(([label, value]) => (
            <div key={label} style={{padding:8, background:C.soft, borderRadius:6}}>
              <div style={{fontSize:9, color:C.mid, marginBottom:3}}>{label}</div>
              <div style={{fontSize:13, color:C.dark, fontWeight:700, fontFamily:MONO}}>{value}</div>
            </div>
          ))}
        </div>
        <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', padding:'8px 0', borderTop:`1px solid ${C.border}`}}>
          <div style={{fontSize:10, color:C.mid}}>Latest close</div>
          <div style={{fontSize:12, color:C.dark, fontWeight:700, fontFamily:MONO}}>
            {close}
            <span style={{marginLeft:8, color:changeColor}}>{change}</span>
          </div>
        </div>
        {data.data?.forecast?._status === 'tier_locked' && (
          <div style={{fontSize:10, color:C.gold, marginTop:8}}>
            业绩预告 🔒 升级 Tushare 10000 解锁
          </div>
        )}
        <div style={{fontSize:9, color:C.mid, marginTop:8}}>
          Tushare 6000 数据完整度: {data.completeness_pct ?? 0}%
        </div>
      </div>
    );
  };

  const ChipDistributionCard = ({ data, ticker, currentPrice }) => {
    if (!data) return null;
    if (data._status === 'skipped') return null;
    if (data._status === 'endpoint_unavailable' || data._status === 'tier_locked') {
      return (
        <div style={{padding:'8px 12px', background:C.card, border:`1px solid ${C.border}`, borderRadius:8, marginBottom:10, fontSize:10, color:C.mid}}>
          筹码分布 数据暂时不可用
        </div>
      );
    }
    if (data._status !== 'ok' || !Array.isArray(data.chips) || data.chips.length === 0) return null;

    const maxPercent = data.chips.reduce((m, c) => Math.max(m, c.percent || 0), 0);
    const peakChip = data.chips.find(c => c.percent === maxPercent);
    const maxPriceLevel = peakChip?.price;
    const chipsSorted = [...data.chips].sort((a, b) => (a.price || 0) - (b.price || 0));
    const normalizePrice = v => {
      if (v?.last != null) return finiteNumber(v.last);
      const direct = finiteNumber(v);
      if (direct != null) return direct;
      if (typeof v === 'string') return finiteNumber(v.replace(/[^\d.-]/g, ''));
      return null;
    };
    const currentPriceValue = normalizePrice(currentPrice);
    const peakPriceValue = finiteNumber(maxPriceLevel);

    return (
      <div style={{padding:'10px 14px', background:C.card, border:`1px solid ${C.border}`, borderRadius:10, marginBottom:10}}>
        <div style={{fontSize:11, fontWeight:700, color:C.dark, marginBottom:6, display:'flex', justifyContent:'space-between'}}>
          <span>{L('Chip Distribution','筹码分布')} <span style={{fontSize:9, color:C.mid, fontWeight:400}}>· {data.trade_date}</span></span>
          <span style={{fontSize:9, color:C.mid}}>{L('Peak as resistance/support','峰值=压力位/支撑位')}</span>
        </div>
        <ResponsiveContainer width='100%' height={120}>
          <BarChart data={chipsSorted} margin={{top:4, right:8, bottom:0, left:4}}>
            <XAxis dataKey='price' tick={{fontSize:8, fill:C.mid}} axisLine={false} tickLine={false} interval='preserveStartEnd' tickFormatter={v => Number(v).toFixed(1)}/>
            <YAxis tick={{fontSize:8, fill:C.mid}} axisLine={false} tickLine={false} width={28} tickFormatter={v => `${v}%`}/>
            {currentPriceValue && <ReferenceLine x={currentPriceValue} stroke={C.dark} strokeDasharray='3 3' strokeWidth={1} label={{value:'当前', fontSize:8, fill:C.dark, position:'top'}}/>}
            <Bar dataKey='percent' isAnimationActive={false} shape={(props) => {
              const isPeak = props.payload.percent === maxPercent;
              const fill = isPeak ? C.red : C.gold;
              return <rect x={props.x} y={props.y} width={props.width} height={props.height} fill={fill} opacity={isPeak ? 0.85 : 0.55}/>;
            }}/>
            <Tooltip contentStyle={{background:C.card, border:`1px solid ${C.border}`, borderRadius:6, fontSize:10}}
              formatter={(val, name) => [val != null ? `${Number(val).toFixed(2)}%` : '—', L('Concentration','集中度')]}
              labelFormatter={p => `¥${Number(p).toFixed(2)}`}/>
          </BarChart>
        </ResponsiveContainer>
        <div style={{fontSize:9, color:C.mid, marginTop:4}}>
          {peakAnalysis(peakPriceValue, currentPriceValue, L)}
        </div>
      </div>
    );
  };

  const ConsensusForecastCard = ({ data, ticker }) => {
    if (!data) return null;
    if (data._status === 'skipped') return null;
    if (data._status === 'endpoint_unavailable' || data._status === 'tier_locked' || data._status === 'fetch_failed') {
      return (
        <div style={{padding:'8px 12px', background:C.card, border:`1px solid ${C.border}`, borderRadius:8, marginBottom:10, fontSize:10, color:C.mid}}>
          盈利预测 数据暂时不可用
        </div>
      );
    }
    const forecasts = Array.isArray(data.forecasts)
      ? [...data.forecasts].sort((a, b) => String(b.end_date || '').localeCompare(String(a.end_date || '')))
      : [];
    if (data._status !== 'ok' || forecasts.length === 0) return null;

    return (
      <div style={{padding:'10px 14px', background:C.card, border:`1px solid ${C.border}`, borderRadius:10, marginBottom:10}}>
        <div style={{fontSize:11, fontWeight:700, color:C.dark, marginBottom:6, display:'flex', justifyContent:'space-between'}}>
          <span>{L('Analyst Consensus','分析师一致预期')} <span style={{fontSize:9, color:C.mid, fontWeight:400}}>· {data.api_used || data.fetched_at?.slice(0,10)}</span></span>
          <span style={{fontSize:9, color:C.mid}}>{L('Source: Tushare 15k tier','数据源：Tushare 15000 顶配')}</span>
        </div>
        <div style={{display:'grid', gridTemplateColumns:'1fr 1fr 1fr 1fr 0.5fr', gap:6, fontSize:10, padding:'4px 0', borderBottom:`1px solid ${C.border}`, color:C.mid, fontWeight:600}}>
          <span>{L('Period','报告期')}</span>
          <span style={{textAlign:'right'}}>EPS</span>
          <span style={{textAlign:'right'}}>{L('Revenue','营收')}</span>
          <span style={{textAlign:'right'}}>{L('Net Profit','净利润')}</span>
          <span style={{textAlign:'right'}}>{L('Brokers','机构')}</span>
        </div>
        {forecasts.slice(0, 4).map((f, i) => (
          <div key={i} style={{display:'grid', gridTemplateColumns:'1fr 1fr 1fr 1fr 0.5fr', gap:6, fontSize:10, padding:'4px 0', borderBottom: i < Math.min(3, forecasts.length-1) ? `1px dashed ${C.border}` : 'none', color:C.dark}}>
            <span style={{fontFamily:MONO, color:C.mid}}>{f.end_date || '—'}</span>
            <span style={{textAlign:'right', fontFamily:MONO, fontWeight:600}}>{f.eps != null ? Number(f.eps).toFixed(2) : '—'}</span>
            <span style={{textAlign:'right', fontFamily:MONO}}>{f.revenue != null ? formatRevenue(f.revenue) : '—'}</span>
            <span style={{textAlign:'right', fontFamily:MONO}}>{f.net_profit != null ? formatRevenue(f.net_profit) : '—'}</span>
            <span style={{textAlign:'right', fontFamily:MONO, color:C.gold}}>{f.broker_count || '—'}</span>
          </div>
        ))}
      </div>
    );
  };

  const LHBCard = ({ data, ticker }) => {
    if (!data || data._status === 'skipped') return null;
    if (data._status !== 'ok') {
      return (
        <div style={{padding:'4px 8px', background:C.soft, border:`1px solid ${C.border}`, borderRadius:6, marginBottom:10, fontSize:10, color:C.mid, whiteSpace:'nowrap'}}>
          龙虎榜 数据暂时不可用
        </div>
      );
    }

    const summary = data.summary || {};
    const totalAppearances = Number(summary.total_appearances || 0);
    const appearances = Array.isArray(data.appearances) ? data.appearances : [];
    if (totalAppearances === 0) {
      return (
        <div style={{fontSize:10, color:C.mid, padding:'2px 2px 8px', marginBottom:8}}>
          过去30天未上龙虎榜
        </div>
      );
    }

    return (
      <div style={{padding:'10px 14px', background:C.card, border:`1px solid ${C.border}`, borderRadius:10, marginBottom:10, borderLeft:`3px solid ${C.gold}`}}>
        <div style={{fontSize:11, fontWeight:700, color:C.dark, marginBottom:6, display:'flex', justifyContent:'space-between'}}>
          <span>{L('龙虎榜 30-day','龙虎榜 30天')} <span style={{fontSize:9, color:C.mid, fontWeight:400}}>· {summary.total_appearances}{L(' appearances',' 次上榜')}</span></span>
          <span style={{fontSize:9, color:C.gold}}>{L('Top: ','主因: ')}{summary.top_reason || '—'}</span>
        </div>
        <div style={{fontSize:10, color:C.mid, marginBottom:6}}>
          {L('Total net flow','累计净额')}:{' '}
          <span style={{fontFamily:MONO, color: summary.total_net_amount >= 0 ? C.red : C.green, fontWeight:600}}>
            {formatLhbAmount(summary.total_net_amount)}
          </span>
          {' · '}
          {L('Last','最近')}: <span style={{fontFamily:MONO}}>{summary.last_appearance_date || '—'}</span>
        </div>
        <div style={{fontSize:10}}>
          {appearances.slice(0, 3).map((a, i) => (
            <div key={i} style={{display:'grid', gridTemplateColumns:'80px 1fr 100px', gap:8, padding:'3px 0', color:C.dark, alignItems:'baseline'}}>
              <span style={{fontFamily:MONO, color:C.mid, fontSize:9}}>{a.trade_date || '—'}</span>
              <span style={{overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', fontSize:10}}>{a.reason || '—'}</span>
              <span style={{textAlign:'right', fontFamily:MONO, color: (a.net_amount || 0) >= 0 ? C.red : C.green, fontSize:10, fontWeight:600}}>{formatLhbAmount(a.net_amount)}</span>
            </div>
          ))}
        </div>
      </div>
    );
  };

  return (
    <div>
      {/* Live price chart — auto-refreshes on 1D range */}
      <PriceChart ticker={ticker} C={C} L={L} lk={lk}/>

      {/* Daily Pulse — auto-runs once per day, shows at top of Research view */}
      <PulseCard pulse={pulse} loading={pulseLoading} ticker={ticker} onRunPulse={onRunPulse} L={L} lk={lk} C={C}/>

      {/* Swing Trading Signals */}
      <Card title={L('Swing Trading Signals','摆动交易信号')}
            sub={L('Deterministic MA/RSI/Volume signals · Updated daily','确定性MA/RSI/量能信号 · 每日更新')}
            open={open['swingDetail_' + ticker] !== false}
            onToggle={() => toggle('swingDetail_' + ticker)} C={C}>
        <SwingSignalDetail signals={signalsData?.[ticker]} C={C} L={L} lk={lk}/>
      </Card>

      <Card title={`${ticker} · ${s.name}`} sub={`${s.en} · VP ${s.vp}`} open={true} C={C}>
        <div style={{display:'grid', gridTemplateColumns:'repeat(3, 1fr)', gap:12, marginBottom:14}}>
          <div>
            <div style={S.label}>Price</div>
            <div style={S.val}>{fmtPrice}</div>
            {fmtChg != null && (
              <div style={{fontSize:10, fontWeight:600, marginTop:2,
                           color: fmtChg > 0 ? C.green : fmtChg < 0 ? C.red : C.mid}}>
                {fmtChg > 0 ? '+' : ''}{fmtChg.toFixed(2)}%
              </div>
            )}
            {livePx && <div style={{fontSize:8, color:C.mid, marginTop:1}}>live</div>}
          </div>
          <div>
            <div style={S.label}>Market Cap</div>
            <div style={S.val}>{fmtMktCap}</div>
            {liveFn?.market_cap && <div style={{fontSize:8, color:C.mid, marginTop:1}}>live</div>}
          </div>
          <div>
            <div style={S.label}>Direction</div>
            <div style={{...S.val, color:s.dir==='LONG'?C.green:s.dir==='SHORT'?C.red:C.mid}}>{s.dir}</div>
          </div>
        </div>
        {/* EQR overall badge */}
        <div style={{display:'flex', alignItems:'center', gap:8, flexWrap:'wrap'}}>
          <EQR lvl={eqr ? eqr.overall : '…'} C={C}/>
          {eqr && <span style={{fontSize:9, color:C.mid}}>{L('Research quality auto-rated · updated ','研究质量自动评级 · 更新于 ')}{eqr.generated_at?.slice(0,10)}</span>}
          {!eqr && <span style={{fontSize:9, color:C.mid}}>{L('Run fetch_data.py to generate EQR ratings','运行 fetch_data.py 以生成EQR评级')}</span>}
        </div>
      </Card>

      <Card title={L('Business Model','商业模式')} open={open.biz} onToggle={()=>toggle('biz')} C={C}>
        <div style={{display:'grid', gridTemplateColumns:'repeat(3, 1fr)', gap:12}}>
          <div style={{padding:12, borderLeft:`4px solid ${C.red}`, background:`${C.red}08`, borderRadius:6}}>
            <div style={{...S.row, gap:6, marginBottom:8}}>
              <AlertCircle size={14} style={{color:C.red, flexShrink:0}}/>
              <div style={{fontSize:11, fontWeight:700, color:C.dark}}>Problem</div>
            </div>
            <div style={{fontSize:10, color:C.dark, lineHeight:1.6}}>{s.biz.problem[lk]}</div>
          </div>

          <div style={{padding:12, borderLeft:`4px solid ${C.blue}`, background:`${C.blue}08`, borderRadius:6}}>
            <div style={{...S.row, gap:6, marginBottom:8}}>
              <Zap size={14} style={{color:C.blue, flexShrink:0}}/>
              <div style={{fontSize:11, fontWeight:700, color:C.dark}}>Mechanism</div>
            </div>
            <div style={{fontSize:10, color:C.dark, lineHeight:1.6}}>{s.biz.mechanism[lk]}</div>
          </div>

          <div style={{padding:12, borderLeft:`4px solid ${C.green}`, background:`${C.green}08`, borderRadius:6}}>
            <div style={{...S.row, gap:6, marginBottom:8}}>
              <ArrowUpRight size={14} style={{color:C.green, flexShrink:0}}/>
              <div style={{fontSize:11, fontWeight:700, color:C.dark}}>Money Flow</div>
            </div>
            <div style={{fontSize:10, color:C.dark, lineHeight:1.6}}>{s.biz.moneyFlow[lk]}</div>
          </div>
        </div>
      </Card>

      <Card title={L('Variant Thesis','变体论点')} open={open.variant} onToggle={()=>toggle('variant')} C={C}>
        <div style={{display:'grid', gridTemplateColumns:'repeat(2, 1fr)', gap:12, marginBottom:14}}>
          <div style={{padding:12, background:`${C.red}10`, borderRadius:6, borderLeft:`3px solid ${C.red}`}}>
            <div style={{...S.row, gap:6, marginBottom:6}}>
              <Eye size={13} style={{color:C.red}}/>
              <div style={{fontSize:11, fontWeight:700, color:C.dark}}>Market Believes</div>
            </div>
            <div style={{fontSize:10, color:C.dark, lineHeight:1.6}}>{s.variant.marketBelieves[lk]}</div>
          </div>

          <div style={{padding:12, background:`${C.green}10`, borderRadius:6, borderLeft:`3px solid ${C.green}`}}>
            <div style={{...S.row, gap:6, marginBottom:6}}>
              <Target size={13} style={{color:C.green}}/>
              <div style={{fontSize:11, fontWeight:700, color:C.dark}}>We Believe</div>
            </div>
            <div style={{fontSize:10, color:C.dark, lineHeight:1.6}}>{s.variant.weBelieve[lk]}</div>
          </div>
        </div>

        <div style={{padding:12, background:`${C.blue}10`, borderRadius:6, borderLeft:`3px solid ${C.blue}`, marginBottom:12}}>
          <div style={{...S.row, gap:6, marginBottom:6}}>
            <Zap size={13} style={{color:C.blue}}/>
            <div style={{fontSize:11, fontWeight:700, color:C.dark}}>Mechanism</div>
          </div>
          <div style={{fontSize:10, color:C.dark, lineHeight:1.6}}>{s.variant.mechanism[lk]}</div>
        </div>

        <div style={{display:'grid', gridTemplateColumns:'repeat(2, 1fr)', gap:12}}>
          <div style={{padding:12, borderLeft:`3px solid ${C.green}`, background:`${C.green}08`, borderRadius:6}}>
            <div style={{fontSize:11, fontWeight:700, color:C.green, marginBottom:6}}>✓ Right If</div>
            <div style={{fontSize:10, color:C.dark, lineHeight:1.6}}>{s.variant.rightIf[lk]}</div>
          </div>

          <div style={{padding:12, borderLeft:`3px solid ${C.red}`, background:`${C.red}08`, borderRadius:6}}>
            <div style={{fontSize:11, fontWeight:700, color:C.red, marginBottom:6}}>✗ Wrong If</div>
            <div style={{fontSize:10, color:C.dark, lineHeight:1.6}}>{s.variant.wrongIf[lk]}</div>
          </div>
        </div>
      </Card>

      <Card title={L('VP Decomposition','VP分解')} open={open.vp} onToggle={()=>toggle('vp')} C={C}>
        <div style={{height:200, marginBottom:14}}>
          <ResponsiveContainer width='100%' height='100%'>
            <BarChart data={decompData} layout='vertical'>
              <XAxis type='number' tick={{fontSize:10}} domain={[0,100]} />
              <YAxis dataKey='name' type='category' tick={{fontSize:9}} width={80} />
              <Tooltip contentStyle={{background:C.card, border:`1px solid ${C.border}`, borderRadius:6}} />
              <Bar dataKey='value' fill={C.blue} radius={[0,4,4,0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        {decompData.map((d,i)=>(
          <div key={i} style={{fontSize:10, marginBottom:6}}>
            <strong>{d.name}:</strong> <span style={{color:C.mid}}>{Object.values(s.decomp)[i][lk]}</span>
          </div>
        ))}
      </Card>

      <Card title={L('Catalysts','催化剂')} open={open.cats} onToggle={()=>toggle('cats')} C={C}>
        <CatalystTimeline catalysts={s.catalysts} lk={lk} C={C}/>
        {s.catalysts.map((c,i)=>(
          <div key={i} style={{marginBottom:10, paddingBottom:10, borderBottom:i<s.catalysts.length-1?`1px solid ${C.border}`:'none'}}>
            <div style={{...S.row, gap:8, marginBottom:4}}><span style={{fontSize:11, fontWeight:700, color:C.dark}}>{c[lk]}</span><Tag text={c.t} c={C.blue} C={C}/><Tag text={c.imp} c={c.imp==='HIGH'?C.green:C.gold} C={C}/></div>
          </div>
        ))}
      </Card>

      <Card title={L('Risks','风险')} open={open.risks} onToggle={()=>toggle('risks')} C={C}>
        <RiskHeatMap risks={s.risks} lk={lk} C={C}/>
        {s.risks.map((r,i)=>(
          <div key={i} style={{marginBottom:10, paddingBottom:10, borderBottom:i<s.risks.length-1?`1px solid ${C.border}`:'none'}}>
            <div style={{...S.row, gap:8, marginBottom:4}}><span style={{fontSize:11, fontWeight:700, color:C.dark}}>{r[lk]}</span><Tag text={r.p} c={r.p==='HIGH'?C.red:r.p==='MED'?C.gold:C.green} C={C}/></div>
          </div>
        ))}
      </Card>

      <Card title={L('Consensus Estimates','一致预期')} sub={L('Broker forecasts · Beat/miss · Revision momentum','券商预测·超预期记录·预期修正动量')} open={open.consensus} onToggle={()=>toggle('consensus')} C={C}>
        <ConsensusPanel ticker={ticker} liveData={liveData} L={L} lk={lk} C={C}/>
      </Card>

      <Card title={L('Financials','财务')} open={open.fin} onToggle={()=>toggle('fin')} C={C}>
        <FinCompare fin={s.fin} peerAvg={s.peerAvg} C={C}/>
        <div style={{display:'grid', gridTemplateColumns:'repeat(3, 1fr)', gap:12, marginBottom: (s.income_statement || s.balance_sheet) ? 16 : 0}}>
          <div>
            <div style={S.label}>Revenue</div>
            <div style={S.val}>{liveFin.rev}</div>
            <div style={{fontSize:9, color:C.green, marginTop:2}}>{liveFin.revGr}</div>
          </div>
          <div>
            <div style={S.label}>FCF</div>
            <div style={S.val}>{liveFin.fcf}</div>
          </div>
          <div>
            <div style={S.label}>Gross Margin</div>
            <div style={S.val}>{liveFin.gm}</div>
          </div>
        </div>
        {/* Full IS/BS/Consensus from Deep Research */}
        <DeepResearchFinancials stock={s} L={L} lk={lk} C={C}/>
      </Card>

      {/* Tushare 6000 data — KR2b 2026-05-02 */}
      {expandedStock === ticker && <TushareDataCard data={tushareData[ticker]} ticker={ticker} />}
      <ChipDistributionCard data={chipData[ticker]} ticker={ticker} currentPrice={liveData?.yahoo?.[ticker]?.price ?? s.price}/>
      <ConsensusForecastCard data={consensusData[ticker]} ticker={ticker}/>
      <LHBCard data={lhbData[ticker]} ticker={ticker}/>

      {/* Live-data sections: only render for focus stocks */}
      {isDynamic ? (
        <div style={{padding:'12px 14px', background:C.soft, borderRadius:8,
                     border:`1px solid ${C.border}`, marginBottom:10, fontSize:11, color:C.mid}}>
          <div style={{fontWeight:600, color:C.dark, marginBottom:6}}>
            📊 {L('AI-generated financials are shown in the Financials card above.',
                   'AI生成的财务数据已显示在上方财务卡片中。')}
          </div>
          <div style={{lineHeight:1.7}}>
            {L('Live technical analysis, K-line charts, financial statements and company profile are only available for the 5 Focus Stocks (300308.SZ, 002594.SZ, 700.HK, 9999.HK, 6160.HK). To get live data for this stock, add it to FOCUS_TICKERS in fetch_data.py.',
               '实时技术分析、K线图、财务报表和公司概况仅支持5只Focus股票。如需此股票的实时数据，请将其加入 fetch_data.py 的 FOCUS_TICKERS。')}
          </div>
          {/* Still show AI technical posture */}
          {s.pricing && (
            <div style={{marginTop:10, paddingTop:10, borderTop:`1px solid ${C.border}`}}>
              <div style={{fontSize:9, fontWeight:700, color:C.gold, marginBottom:6}}>
                {L('AI Technical Posture','AI估算技术形态')}
              </div>
              <div style={{...S.row, gap:10, marginBottom:4}}>
                <span style={S.label}>{L('Valuation level','估值位置')}</span>
                <span style={{...S.tag(s.pricing.level==='LOW'?C.green:s.pricing.level==='HIGH'?C.red:C.gold)}}>
                  {s.pricing.level}
                </span>
              </div>
              <div style={{fontSize:10, color:C.mid, lineHeight:1.5}}>{s.pricing.crowd?.[lk]}</div>
            </div>
          )}
        </div>
      ) : (
        <>
          <Card title={L('Technical Analysis','技术分析')} open={open.ta} onToggle={()=>toggle('ta')} C={C}>
            <TechnicalAnalysis ticker={ticker} liveData={liveData} L={L} lk={lk} C={C}/>
          </Card>

          <Card title={L('K-Line Chart','K线图')} sub={L('90-day OHLC + Volume','90日K线+成交量')} open={open.kline} onToggle={()=>toggle('kline')} C={C}>
            <CandlestickChart ticker={ticker} L={L} lk={lk} C={C}/>
          </Card>

          <Card title={L('Financial Statements','财务报表')} sub={L('IS / BS / CF','利润表/资产负债表/现金流量表')} open={open.statements} onToggle={()=>toggle('statements')} C={C}>
            <FinancialStatements ticker={ticker} L={L} lk={lk} C={C}/>
          </Card>

          <Card title={L('Company Profile','公司概况')} sub={L('Sector, fundamentals, external links','行业、基本面、外部链接')} open={open.company} onToggle={()=>toggle('company')} C={C}>
            <CompanyInfoPanel ticker={ticker} liveData={liveData} L={L} lk={lk} C={C}/>
          </Card>
        </>
      )}

      {/* EQR Detail Card */}
      {eqr && (
        <Card title={L('Research Quality (EQR)','研究质量评级 (EQR)')} sub={L('Auto-generated · degrades with data age','自动生成 · 随数据老化自动降级')} open={open.variant} onToggle={()=>toggle('variant')} C={C}>
          {/* Section grid */}
          <div style={{display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(160px, 1fr))', gap:8, marginBottom:14}}>
            {Object.values(eqr.sections || {}).map((sec, i) => {
              const c = sec.rating==='HIGH' ? C.green : sec.rating==='MED-HIGH' ? C.blue : sec.rating==='MED' ? C.gold : C.red;
              return (
                <div key={i} style={{padding:'10px 12px', background:`${c}08`, border:`1px solid ${c}30`, borderRadius:7}}>
                  <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:4}}>
                    <div style={{fontSize:10, fontWeight:700, color:C.dark}}>{sec.label}</div>
                    <span style={{...S.tag(c), fontSize:8}}>{sec.rating}</span>
                  </div>
                  <div style={{fontSize:9, color:C.mid, lineHeight:1.5}}>{sec.source}</div>
                  {sec.data_age_days < 999 && (
                    <div style={{fontSize:8, color: sec.data_age_days > 90 ? C.gold : C.mid, marginTop:3}}>
                      {sec.data_age_days}d {L('old','天前')}
                      {sec.data_age_days > 90 ? ' ⚠️' : ''}
                    </div>
                  )}
                  {sec.note && <div style={{fontSize:8, color:C.gold, marginTop:3, lineHeight:1.4}}>{sec.note}</div>}
                </div>
              );
            })}
          </div>

          {/* AI Limitations */}
          <div style={{padding:'10px 14px', background:`${C.gold}08`, border:`1px solid ${C.gold}25`, borderRadius:7}}>
            <div style={{fontSize:10, fontWeight:700, color:C.gold, marginBottom:8, letterSpacing:'0.04em'}}>
              ⚠ {L('AI LIMITATIONS — read before acting','AI局限性 — 行动前必读')}
            </div>
            {(eqr.ai_limitations || []).map((lim, i) => (
              <div key={i} style={{display:'flex', gap:8, marginBottom:5}}>
                <span style={{color:C.mid, flexShrink:0, fontSize:10}}>—</span>
                <span style={{fontSize:10, color:C.dark, lineHeight:1.5}}>{lim}</span>
              </div>
            ))}
            <div style={{fontSize:9, color:C.mid, marginTop:8, borderTop:`1px solid ${C.border}`, paddingTop:6}}>
              {L('Generated: ','生成时间: ')}{eqr.generated_at ? new Date(eqr.generated_at).toLocaleString() : '—'}
            </div>
          </div>
        </Card>
      )}

      {/* Profit Scissors / Financial Levers Card */}
      <LeadingIndicatorCard liData={liData} ticker={ticker} L={L} C={C} open={open} toggle={toggle}/>
      <ProfitScissors scissors={scissors} L={L} C={C} open={open} toggle={toggle}/>

      {/* Reverse DCF Card */}
      <ReverseDCF rdcf={rdcf} L={L} C={C} open={open} toggle={toggle} egapScore={egapScores?.[ticker]}/>

      {/* Multi-Agent Debate */}
      <Card
        title={L('Multi-Agent Debate','多模型辩论')}
        sub={L('Gemini Bull · GPT-4o Bear · Claude Forensic → CIO Synthesis',
               'Gemini 做多 · GPT-4o 做空 · Claude 取证 → 首席综合判断')}
        open={open.debate !== false}
        onToggle={()=>toggle('debate')}
        C={C}
      >
        <DebatePanel ticker={ticker} company={s.name} C={C} L={L} lk={lk}/>
      </Card>

      <Card title={L('Next Actions','下一步行动')} open={open.actions} onToggle={()=>toggle('actions')} C={C}>
        {s.nextActions.map((a,i)=>(
          <div key={i} style={{marginBottom:8, fontSize:11, color:C.dark}}>• {a[lk]}</div>
        ))}
      </Card>
    </div>
  );
}

/* ── TRACKER TAB ────────────────────────────────────────────────────────── */
function Tracker({ L, stocks: stocksMap, C, predictions }) {
  const stocks = Object.entries(stocksMap || STOCKS).slice(0,3).map(([tk,s])=>({...s, ticker:tk}));
  return (
    <div>
      <Card title={L('Key Metrics Tracker','关键指标追踪')} open={true} C={C}>
        <div style={{overflowX:'auto'}}>
          <table style={{width:'100%', fontSize:11, borderCollapse:'collapse'}}>
            <thead><tr style={{borderBottom:`1px solid ${C.border}`}}>
              <th style={{textAlign:'left', padding:8, fontWeight:700, color:C.dark}}>Ticker</th>
              <th style={{textAlign:'left', padding:8, fontWeight:700, color:C.dark}}>Revenue</th>
              <th style={{textAlign:'left', padding:8, fontWeight:700, color:C.dark}}>Growth</th>
              <th style={{textAlign:'left', padding:8, fontWeight:700, color:C.dark}}>GM%</th>
            </tr></thead>
            <tbody>
              {stocks.map((s,i)=>(
                <tr key={i} style={{borderBottom:`1px solid ${C.border}`}}>
                  <td style={{padding:8, color:C.dark, fontWeight:600}}>{s.ticker}</td>
                  <td style={{padding:8, color:C.dark}}>{s.fin?.rev}</td>
                  <td style={{padding:8, color:C.green}}>{s.fin?.revGr}</td>
                  <td style={{padding:8, color:C.dark}}>{s.fin?.gm}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title={L('Prediction Log','预测记录')} sub={L('Variant views with explicit verification & falsification conditions','带验证/证伪条件的变体观点追踪')} open={true} C={C}>
        <PredictionLog predictions={predictions || []} L={L} C={C}/>
      </Card>
    </div>
  );
}

/* ── PREDICTION LOG ──────────────────────────────────────────────────────── */
function DetailRow({ label, value, color, C }) {
  if (!value) return null;
  return (
    <div style={{marginBottom:10}}>
      <div style={{fontSize:9, fontWeight:700, color:C.mid, textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:2}}>{label}</div>
      <div style={{fontSize:11, color: color || C.dark, lineHeight:1.6}}>{value}</div>
    </div>
  );
}

function PredictionLog({ predictions, L, C }) {
  const [expanded, setExpanded] = useState(null);

  const resolved  = predictions.filter(p => p.status === 'VERIFIED' || p.status === 'FALSIFIED');
  const hits      = resolved.filter(p => p.status === 'VERIFIED').length;
  const hitRatePct = resolved.length > 0 ? Math.round(hits / resolved.length * 100) : null;
  const openCount  = predictions.filter(p => p.status === 'OPEN').length;

  const statusStyle = (status) => {
    if (status === 'VERIFIED')     return { bg: C.green,  color: '#fff' };
    if (status === 'FALSIFIED')    return { bg: C.red,    color: '#fff' };
    if (status === 'EXPIRED')      return { bg: C.mid,    color: '#fff' };
    if (status === 'INCONCLUSIVE') return { bg: C.gold,   color: '#fff' };
    return { bg: C.blue, color: '#fff' }; // OPEN
  };

  const statusLabel = (status) => ({
    OPEN: 'Open', VERIFIED: 'Verified ✓', FALSIFIED: 'Falsified ✗',
    EXPIRED: 'Expired', INCONCLUSIVE: 'Inconclusive',
  }[status] || status);

  const daysLeft = (targetDate) => {
    const diff = new Date(targetDate) - new Date();
    return Math.ceil(diff / 86400000);
  };

  return (
    <div style={{marginTop:16}}>
      {/* Header */}
      <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:12}}>
        <div>
          <span style={{fontSize:13, fontWeight:700, color:C.dark}}>{L('Prediction Log','预测记录')}</span>
          <span style={{fontSize:10, color:C.mid, marginLeft:8}}>{openCount} {L('open','进行中')} · {predictions.length} {L('total','总计')}</span>
        </div>
        {hitRatePct !== null ? (
          <div style={{textAlign:'right'}}>
            <span style={{fontSize:18, fontWeight:800, fontFamily:'monospace', color: hitRatePct >= 60 ? C.green : C.red}}>{hitRatePct}%</span>
            <span style={{fontSize:9, color:C.mid, marginLeft:4}}>{L('hit rate','胜率')} ({hits}/{resolved.length} {L('resolved','已结')})</span>
          </div>
        ) : (
          <span style={{fontSize:10, color:C.mid}}>{L('No resolved predictions yet','暂无已结案预测')}</span>
        )}
      </div>

      {/* Cards */}
      {predictions.map(pred => {
        const ss    = statusStyle(pred.status);
        const days  = daysLeft(pred.target_date);
        const isExp = expanded === pred.id;
        const confColor = pred.confidence >= 70 ? C.green : pred.confidence >= 50 ? C.gold : C.red;

        return (
          <div key={pred.id} onClick={() => setExpanded(isExp ? null : pred.id)}
            style={{marginBottom:8, padding:'12px 14px', background:C.card, border:`1px solid ${C.border}`,
                    borderRadius:8, cursor:'pointer', transition:'border-color .15s',
                    borderLeftWidth:3, borderLeftColor: ss.bg}}>

            {/* Row 1: ticker + status + confidence */}
            <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:6}}>
              <div style={{display:'flex', alignItems:'center', gap:8}}>
                <span style={{fontFamily:'monospace', fontSize:11, fontWeight:700, color:C.dark}}>{pred.ticker}</span>
                <span style={{fontSize:9, fontWeight:700, padding:'2px 7px', borderRadius:10, background:ss.bg, color:ss.color}}>{statusLabel(pred.status)}</span>
                {pred.status === 'OPEN' && (
                  <span style={{fontSize:9, color: days < 30 ? C.gold : C.mid}}>
                    {days > 0 ? `${days}d ${L('left','剩余')}` : `${Math.abs(days)}d ${L('overdue','逾期')}`}
                  </span>
                )}
              </div>
              <div style={{display:'flex', alignItems:'center', gap:6}}>
                <div style={{width:40, height:3, background:C.soft, borderRadius:2, overflow:'hidden'}}>
                  <div style={{height:'100%', width:`${pred.confidence}%`, background:confColor, borderRadius:2}}></div>
                </div>
                <span style={{fontSize:10, color:C.mid, fontFamily:'monospace'}}>{pred.confidence}%</span>
              </div>
            </div>

            {/* Row 2: We Believe */}
            <div style={{fontSize:11, color:C.dark, lineHeight:1.6}}>{pred.we_believe}</div>

            {/* Expanded */}
            {isExp && (
              <div style={{marginTop:12, paddingTop:12, borderTop:`1px solid ${C.border}`}}>
                <DetailRow label={L('Market Believes','市场认为')} value={pred.market_believes} color={C.mid} C={C}/>
                <DetailRow label={L('Mechanism','机制')} value={pred.mechanism} C={C}/>
                <DetailRow label={L('Verified if','验证条件')} value={pred.verification_condition} color={C.green} C={C}/>
                <DetailRow label={L('Falsified if','证伪条件')} value={pred.falsification_condition} color={C.red} C={C}/>
                {pred.actual_outcome && <DetailRow label={L('Outcome','结果')} value={pred.actual_outcome} color={C.gold} C={C}/>}
                {pred.notes && <div style={{fontSize:10, color:C.mid, fontStyle:'italic', marginTop:4, lineHeight:1.5}}>{pred.notes}</div>}
                <div style={{fontSize:9, color:C.mid, marginTop:8}}>
                  {L('Created','创建于')} {pred.created_at} · {L('Target','目标日期')} {pred.target_date}
                  {pred.resolved_at && ` · ${L('Resolved','结案于')} ${pred.resolved_at}`}
                </div>
              </div>
            )}
          </div>
        );
      })}

      {predictions.length === 0 && (
        <div style={{padding:20, textAlign:'center', color:C.mid, fontSize:11}}>
          {L('No predictions yet. Edit public/data/prediction_log.json to add entries.','暂无预测记录。编辑 public/data/prediction_log.json 添加记录。')}
        </div>
      )}
    </div>
  );
}

/* ── TRADING DESK TAB ────────────────────────────────────────────────────── */
function TradingDesk({ L, lk, C }) {
  const [decision,  setDecision]  = useState(null);
  const [sizing,    setSizing]    = useState(null);
  const [quality,   setQuality]   = useState(null);
  const [snapshots, setSnapshots] = useState([]);
  const [fragility, setFragility] = useState({});  // KR3: { ticker: fragility_data }
  const [personaOverlay, setPersonaOverlay] = useState(null);  // KR4: AHF-3 persona overlay (single file, all tickers)
  const [multiMethodValuation, setMultiMethodValuation] = useState(null);  // AHF-2 KR4: triangulated signal across FCF DCF + EV/EBITDA + EBO
  const [tushareMarket, setTushareMarket] = useState(null);
  const [tushareData, setTushareData] = useState({});
  const [chipData, setChipData] = useState({});
  const [consensusData, setConsensusData] = useState({});
  const [loading,   setLoading]   = useState(true);
  const MONO = "'JetBrains Mono','Fira Code',monospace";

  useEffect(() => {
    const base = DATA_BASE;

    // Fetch watchlist first (single source of truth per CLAUDE.md), then
    // fan out fragility fetches per-ticker. Adding a 6th ticker to
    // watchlist.json auto-renders its pill on next dashboard load — no
    // Dashboard.jsx edit needed. Trade-off: 1 extra small fetch upfront
    // vs hardcoded list. SOT compliance wins.
    fetch(base + 'data/watchlist.json')
      .then(r => r.ok ? r.json() : null)
      .catch(() => null)
      .then(wl => {
        const tickers = Object.keys(wl?.tickers || {});
        const fragilityFetches = tickers.map(t => {
          const safe = t.replace('.', '_');
          return fetch(base + `data/fragility_${safe}.json`)
            .then(r => r.ok ? r.json() : null)
            .catch(() => null)
            .then(d => ({ ticker: t, data: d }));
        });
        const tushareFetches = tickers.map(t =>
          fetch(base + `data/tushare/${t}.json`)
            .then(r => r.ok ? r.json() : null)
            .catch(() => null)
            .then(d => ({ ticker: t, data: d }))
        );
        const chipDistributionFetches = tickers.map(t =>
          fetch(base + `data/chip_distribution/${t}.json`)
            .then(r => r.ok ? r.json() : null)
            .then(d => ({ ticker: t, data: d }))
            .catch(() => ({ ticker: t, data: null }))
        );
        const consensusForecastFetches = tickers.map(t =>
          fetch(base + `data/consensus_forecast/${t}.json`)
            .then(r => r.ok ? r.json() : null)
            .then(d => ({ ticker: t, data: d }))
            .catch(() => ({ ticker: t, data: null }))
        );

        return Promise.all([
          fetch(base + 'data/daily_decision.json').then(r => r.ok ? r.json() : null).catch(() => null),
          fetch(base + 'data/position_sizing.json').then(r => r.ok ? r.json() : null).catch(() => null),
          fetch(base + 'data/signal_quality.json').then(r => r.ok ? r.json() : null).catch(() => null),
          fetch(base + 'data/snapshots.json').then(r => r.ok ? r.json() : null).catch(() => null),
          Promise.all(fragilityFetches),
          // KR4: AHF-3 persona overlay (single file, internal ticker enumeration).
          // Adding a 6th watchlist ticker does NOT require an extra fetch here —
          // persona_overlay.json regenerates with all current tickers each pipeline run.
          fetch(base + 'data/persona_overlay.json').then(r => r.ok ? r.json() : null).catch(() => null),
          // AHF-2 KR4: multi-method valuation triangulation (single file,
          // internal ticker enumeration, output of scripts/multi_method_valuation.py).
          fetch(base + 'data/multi_method_valuation.json').then(r => r.ok ? r.json() : null).catch(() => null),
          fetch(base + 'data/tushare_market.json').then(r => r.ok ? r.json() : null).catch(() => null),
          Promise.all(tushareFetches),
          Promise.all(chipDistributionFetches),
          Promise.all(consensusForecastFetches),
        ]);
      })
      .then(([dd, sz, sq, sn, fragArr, personas, mmv, tushareMarket, tushareDataArr, chipDataArr, consensusDataArr] = [null, null, null, null, [], null, null, null, [], [], []]) => {
        setDecision(dd);
        setSizing(sz);
        setQuality(sq);
        setSnapshots(sn?.snapshots || []);
        const fragMap = {};
        (fragArr || []).forEach(({ ticker, data }) => { if (data) fragMap[ticker] = data; });
        setFragility(fragMap);
        setPersonaOverlay(personas);
        setMultiMethodValuation(mmv);
        setTushareMarket(tushareMarket);
        const tushareDataMap = {};
        (tushareDataArr || []).forEach(({ ticker, data }) => { if (data) tushareDataMap[ticker] = data; });
        setTushareData(tushareDataMap);
        const chipDataMap = {};
        (chipDataArr || []).forEach(({ ticker, data }) => { if (data) chipDataMap[ticker] = data; });
        setChipData(chipDataMap);
        const consensusDataMap = {};
        (consensusDataArr || []).forEach(({ ticker, data }) => { if (data) consensusDataMap[ticker] = data; });
        setConsensusData(consensusDataMap);
        setLoading(false);
      });
  }, []);

  if (loading) return (
    <div style={{display:'flex', alignItems:'center', justifyContent:'center',
                 height:300, color:C.mid, fontSize:13}}>
      Loading decision engine…
    </div>
  );
  if (!decision) return (
    <div style={{display:'flex', alignItems:'center', justifyContent:'center',
                 height:300, flexDirection:'column', gap:8}}>
      <div style={{fontSize:13, color:C.mid}}>No decision data yet</div>
      <div style={{fontSize:11, color:C.mid, opacity:0.7}}>
        Run GitHub Actions to generate daily_decision.json
      </div>
    </div>
  );

  const ACTION_COLOR = {
    EXIT: '#ef4444', TRIM: '#f97316', REVIEW_TRIM: '#f59e0b',
    REVIEW_STOP: '#ef4444', ADD: '#10b981', HOLD: '#22c55e',
    BUY_WATCH: '#3b82f6', WATCH: '#6b7280', NEUTRAL: '#6b7280',
  };
  const ACTION_LABEL_ZH = {
    EXIT: '离场', TRIM: '减仓', REVIEW_TRIM: '考虑减仓',
    REVIEW_STOP: '复核止损', ADD: '可加仓', HOLD: '持有',
    BUY_WATCH: '关注建仓', WATCH: '观望', NEUTRAL: '中性',
  };
  const ACTION_ICON = {
    EXIT: '🚨', TRIM: '⬇️', REVIEW_TRIM: '💰', REVIEW_STOP: '🔴',
    ADD: '📈', HOLD: '✅', BUY_WATCH: '🎯', WATCH: '👁️',
  };

  const held        = decision.decisions?.held       || [];
  const watch       = decision.decisions?.watchlist  || [];
  const risks       = decision.portfolio_risk        || [];
  const regimes     = decision.regime_summary        || [];
  const wrongifs    = decision.wrongif_alerts        || [];
  const brief       = lk === 'z' ? decision.brief_z : decision.brief_e;
  const sizingMap   = {};
  (sizing?.sizing || []).forEach(s => { sizingMap[s.ticker] = s; });

  // KR3: small inline fragility pill — composite + band, color-coded by band.
  // Uses CLAUDE.md design system colors only (frozen palette).
  // Title attribute exposes the 5-component breakdown for hover.
  const FragilityPill = ({ frag }) => {
    if (!frag || frag.composite == null) return null;
    const band = frag.band || 'INSUFFICIENT_DATA';
    const colorByBand = {
      FRAGILE:           { bg: `${C.red}15`,   fg: C.red   },
      MODERATE:          { bg: `${C.gold}15`,  fg: C.gold  },
      ROBUST:            { bg: `${C.green}15`, fg: C.green },
      ANTIFRAGILE:       { bg: `${C.blue}15`,  fg: C.blue  },
      INSUFFICIENT_DATA: { bg: `${C.mid}15`,   fg: C.mid   },
    }[band] || { bg: `${C.mid}15`, fg: C.mid };
    const comps = frag.components || {};
    const f6 = frag.f6_concentration;
    const f6Render = !!(f6 && f6.score != null);
    // F6 pill always-on at current 5-ticker scale; consider conditional
    // rendering (e.g., score >= 40) once watchlist scales beyond ~10 names.
    // Threshold tints: <40 green / 40-69 gold / >=70 red. Visually subordinate
    // to composite pill (smaller padding, fontSize, alpha) so action badges
    // remain primary signal — KR2 review (i)(ii)(iii) decisions.
    const f6Color = f6Render
      ? (f6.score < 40 ? C.green : f6.score < 70 ? C.gold : C.red)
      : null;
    const f6Rationale = f6Render
      ? (lk === 'z' ? (f6.rationale_z || '') : (f6.rationale_e || ''))
      : '';
    const f6Tooltip = f6Render
      ? `F6 concentration: ${f6.score}\n${f6Rationale}\n\n[unvalidated intuition] — separate from financial fragility composite.`
      : '';
    const tooltip = [
      `Fragility composite: ${frag.composite} (${band})`,
      `F1 leverage:          ${comps.F1_leverage ?? '—'}`,
      `F2 liquidity-survival:${comps.F2_liquidity_survival ?? '—'} (${frag.f2_method || '?'})`,
      `F3 tail risk:         ${comps.F3_tail_risk ?? '—'}`,
      `F4 vol regime:        ${comps.F4_vol_regime ?? '—'}`,
      `F5 max drawdown:      ${comps.F5_max_drawdown ?? '—'}`,
      f6Render ? `F6 concentration:    ${f6.score} (separate dim, NOT in composite)` : '',
      frag.biotech_mode ? '[biotech-mode F2]' : '',
      '',
      'Composite measures FINANCIAL fragility (leverage/liquidity/tails/vol/drawdown).',
      'F6 measures BUSINESS-MODEL concentration (single-asset/customer/segment) — MANUAL seed.',
      'Read both together: high F6 + low composite still implies elevated overall tail risk.',
      '[unvalidated intuition] thresholds.',
    ].filter(Boolean).join('\n');
    return (
      <span style={{display:'inline-flex', gap:3, alignItems:'center'}}>
        <span
          title={tooltip}
          style={{
            fontFamily: MONO, fontSize:9, fontWeight:700,
            padding:'2px 6px', borderRadius:3,
            background: colorByBand.bg, color: colorByBand.fg,
            letterSpacing:0.3, cursor:'help',
          }}
        >
          ⚠ {frag.composite}
        </span>
        {f6Render && (
          <span
            title={f6Tooltip}
            style={{
              fontFamily: MONO, fontSize:8, fontWeight:700,
              padding:'1px 5px', borderRadius:3,
              background: `${f6Color}12`, color: f6Color,
              letterSpacing:0.3, cursor:'help',
            }}
          >
            F6 {f6.score}
          </span>
        )}
      </span>
    );
  };

  // ─────────────────────────────────────────────────────────────────────
  // KR4: AHF-3 persona overlay surfacing
  //
  // Renders Buffett / Burry / Damodaran score badges per ticker (3 small
  // adjacent badges, each with its own tooltip). Not actionable —
  // cross-check across named investor frameworks. Visually subordinate to
  // F6 pill which is subordinate to composite pill (matches actionability
  // ranking: financial-risk > concentration-risk > framework-cross-check).
  //
  // Four null-state paths (per KR4 decomp adversarial review observation ii):
  //   1. overlay === null            → cluster returns null (loading, pre-fetch)
  //   2. overlay.personas[t] missing → cluster returns null (ticker not in file)
  //   3. block.error truthy          → renders "Persona —" placeholder
  //   4. full data                   → renders 3 PersonaBadge components
  //
  // Criterion `name` field (e.g. "ROE > 15%") stays English-only by design —
  // formula-like, locale-independent. Only verdict text + degraded-state
  // error description respect lk='z' i18n.
  // ─────────────────────────────────────────────────────────────────────
  const PERSONA_ERROR_DESCRIPTIONS = {
    rdcf_missing:         { e: 'DCF model not yet generated',  z: 'DCF模型尚未生成' },
    fundamentals_missing: { e: 'Live data unavailable',         z: '实时数据不可用' },
    fin_data_missing:     { e: 'Financial statements missing',  z: '财务报表缺失' },
    market_data_stale:    { e: 'Market data is stale',          z: '市场数据已过期' },
    market_data_missing:  { e: 'Market data unavailable',       z: '市场数据不可用' },
  };

  const PersonaBadge = ({ label, persona }) => {
    if (!persona || persona.score == null) return null;
    const ratio = persona.max ? persona.score / persona.max : 0;
    // Threshold boundary semantics (KR4 decomp P3-v): inclusive on upper side.
    //   ratio >= 0.7 → green, ratio >= 0.3 → gold, otherwise red.
    const color = ratio >= 0.7 ? C.green : ratio >= 0.3 ? C.gold : C.red;
    const verdict = lk === 'z' ? (persona.verdict_z || '') : (persona.verdict_e || '');
    // Per-criterion line: minimal parenthetical (NOT padEnd columns) — browser
    // title attribute uses proportional fonts so column alignment misrenders.
    // KR7: format-aware actual rendering. Backward-compat: fall back to "ratio"
    // (raw numeric .toFixed(3)) when format field is absent — handles stale
    // gh-pages persona_overlay.json deployed before KR7's schema extension.
    const fmtActual = (v, format) => {
      if (v == null) return '—';
      if (typeof v !== 'number') return String(v);
      if (format === 'percent') return `${(v * 100).toFixed(1)}%`;
      // ratio / absolute / undefined → raw numeric
      return v.toFixed(3);
    };
    const lines = (persona.criteria || []).map(c => {
      const mark = c.passed === true ? '✓' : c.passed === false ? '✗' : '—';
      const actStr = fmtActual(c.actual, c.format);
      return `${mark} ${c.name} (actual ${actStr})`;
    });
    const tooltip = [
      `${label} ${persona.score}/${persona.max}` + (verdict ? ` — ${verdict}` : ''),
      ...lines,
      '',
      '[unvalidated intuition] thresholds. Cross-check, NOT authority.',
    ].join('\n');
    return (
      <span
        title={tooltip}
        style={{
          fontFamily: MONO, fontSize: 7, fontWeight: 700,
          padding: '1px 4px', borderRadius: 3,
          background: `${color}12`, color,
          letterSpacing: 0.3, cursor: 'help',
        }}
      >
        {label} {persona.score}/{persona.max}
      </span>
    );
  };

  const PersonaCluster = ({ overlay, ticker }) => {
    // Path 1: pre-fetch loading state — cluster silent (data hasn't arrived).
    if (!overlay) return null;
    const block = (overlay.personas || {})[ticker];
    // Path 2: ticker entirely missing from file (e.g. future watchlist
    // addition not yet computed) — cluster silent.
    if (!block) return null;
    // Path 3: typed graceful-degradation error — render single placeholder
    // badge with translated error description. Visually distinct from
    // "loading" and from "full data."
    if (block.error) {
      const desc = PERSONA_ERROR_DESCRIPTIONS[block.error]
        || { e: block.error, z: block.error };
      const tooltip = [
        'Persona overlay unavailable',
        lk === 'z' ? desc.z : desc.e,
        '',
        '[unvalidated intuition] cross-check, NOT authority.',
      ].join('\n');
      return (
        <span style={{display:'inline-flex', gap:3, alignItems:'center'}}>
          <span
            title={tooltip}
            style={{
              fontFamily: MONO, fontSize: 7, fontWeight: 700,
              padding: '1px 4px', borderRadius: 3,
              background: `${C.mid}10`, color: C.mid,
              letterSpacing: 0.3, cursor: 'help',
            }}
          >
            Persona —
          </span>
        </span>
      );
    }
    // Path 4: full data — render 3 separate badges with 3 separate tooltips.
    return (
      <span style={{display:'inline-flex', gap:3, alignItems:'center'}}>
        <PersonaBadge label="Buf" persona={block.buffett} />
        <PersonaBadge label="Bur" persona={block.burry} />
        <PersonaBadge label="Dam" persona={block.damodaran} />
      </span>
    );
  };

  // ─────────────────────────────────────────────────────────────────────
  // AHF-2 KR4: TriangulatedBadge — surfaces median-of-3 valuation signal
  //
  // Renders compact arrow notation (TRI ↓/↑/=/—) matching sibling badge
  // pattern (no colon, like F6 + persona). Color-coded per signal:
  //   OVERPRICED      → red    (↓ down arrow)
  //   UNDERPRICED     → green  (↑ up arrow)
  //   FAIRLY_VALUED   → gold   (= equals)
  //   INSUFFICIENT_DATA → grey (— em dash)
  //
  // Hover tooltip shows per-method signals, skip reasons (translated via
  // TRI_SKIP_DESCRIPTIONS map), and KR3 rationale text (i18n via lk).
  //
  // Visual subordination (smallest in hierarchy):
  //   composite (alpha 15) > F6 (12) > persona (12) > TRI (10)
  // Triangulated signal is SYNTHESIS across other lenses — context, not
  // actionable trigger. Smaller alpha keeps actionable signals primary.
  //
  // Four null-state paths (matching KR3 PersonaCluster pattern):
  //   1. overlay null            → cluster silent (loading, pre-fetch)
  //   2. ticker missing in file  → cluster silent (e.g. new watchlist add)
  //   3. INSUFFICIENT_DATA       → "TRI —" badge (all 3 methods skipped)
  //   4. full data               → arrow notation badge
  // ─────────────────────────────────────────────────────────────────────
  const TRI_SKIP_DESCRIPTIONS = {
    // Method 1 (FCF DCF) skip codes
    'rdcf_missing':                 { e: 'rdcf JSON not yet generated',  z: 'rdcf JSON尚未生成' },
    'rdcf_no_signal':               { e: 'rdcf signal field absent',     z: 'rdcf signal字段缺失' },
    // Method 2 (EV/EBITDA) skip codes
    'ev_ebitda_file_missing':       { e: 'EV/EBITDA module not run',     z: 'EV/EBITDA模块未运行' },
    'ev_ebitda_ticker_missing':     { e: 'Ticker missing from output',   z: '股票从输出中缺失' },
    'ev_ebitda_biotech_fallback':   { e: 'Inapplicable to biotech',      z: '不适用于生物科技' },
    'ev_ebitda_fundamentals_missing': { e: 'Live data unavailable',      z: '实时数据不可用' },
    'ev_ebitda_ebitda_missing':     { e: 'EBITDA not derivable',         z: 'EBITDA无法推导' },
    'ev_ebitda_ev_data_missing':    { e: 'Market cap missing',           z: '市值数据缺失' },
    // Method 3 (EBO) skip codes
    'ri_file_missing':              { e: 'Residual Income module not run', z: 'Residual Income 模块未运行' },
    'ri_ticker_missing':            { e: 'Ticker missing from output',   z: '股票从输出中缺失' },
    'ri_biotech_fallback':          { e: 'Inapplicable to biotech',      z: '不适用于生物科技' },
    'ri_hyper_growth_ebo_unstable': { e: 'P/B too high (hyper-growth)',  z: 'P/B过高（超高成长）' },
  };

  // Skip-code lookup with fallback chain: known map → rdcf_error:* prefix
  // → raw code (for unknown / future codes). Bilingual via lk.
  const lookupSkipDesc = (code) => {
    if (!code) return '';
    const desc = TRI_SKIP_DESCRIPTIONS[code];
    if (desc) return lk === 'z' ? desc.z : desc.e;
    if (code.startsWith('rdcf_error:')) {
      const errCode = code.slice('rdcf_error:'.length);
      return lk === 'z' ? `rdcf错误: ${errCode}` : `rdcf error: ${errCode}`;
    }
    return code;  // fallback: raw code
  };

  const TriangulatedBadge = ({ overlay, ticker }) => {
    // Path 1: pre-fetch loading
    if (!overlay) return null;
    // Path 2: ticker missing entirely from file
    const block = (overlay.tickers || {})[ticker];
    if (!block) return null;

    const sig = block.triangulated_signal;
    const mc = block.methods_count || 0;
    const isBio = block.is_biotech_fallback;
    const isPartial = block.is_partial;

    // Color mapping per signal
    const color = sig === 'OVERPRICED'    ? C.red
                : sig === 'UNDERPRICED'   ? C.green
                : sig === 'FAIRLY_VALUED' ? C.gold
                : C.mid;  // INSUFFICIENT_DATA → grey

    // Arrow notation (no colon, sibling-pattern parity)
    const arrow = sig === 'OVERPRICED'    ? '↓'
                : sig === 'UNDERPRICED'   ? '↑'
                : sig === 'FAIRLY_VALUED' ? '='
                : '—';  // INSUFFICIENT_DATA

    // Per-method signal lines with skip translation
    const ms = block.method_signals || {};
    const fmtMethodLine = (label, methodBlock) => {
      if (!methodBlock) return `${label}: —`;
      if (methodBlock.skip_reason) {
        return `${label}: skipped (${lookupSkipDesc(methodBlock.skip_reason)})`;
      }
      return `${label}: ${methodBlock.signal || '—'}`;
    };

    const flagSuffix = isBio ? '  [biotech_fallback]'
                     : isPartial ? '  [partial]'
                     : '';
    const rationale = lk === 'z' ? (block.rationale_z || '') : (block.rationale_e || '');

    const tooltip = [
      `TRI ${arrow} (${sig})  ·  n=${mc} methods${flagSuffix}`,
      '─────────────────────────────────────────────',
      fmtMethodLine('M1 (FCF DCF)', ms.FCF_DCF),
      fmtMethodLine('M2 (EV/EBITDA)', ms.EV_EBITDA),
      fmtMethodLine('M3 (Residual Income)', ms.Residual_Income_EBO),
      '',
      rationale,
      '',
      '[unvalidated intuition] tie-break + per-method thresholds.',
      'NOT folded into VP composite.',
    ].filter(Boolean).join('\n');

    return (
      <span title={tooltip} style={{
        fontFamily: MONO,
        fontSize: 7,
        fontWeight: 700,
        padding: '1px 4px',
        borderRadius: 3,
        background: `${color}10`,  // alpha 10 — smallest in hierarchy
        color,
        letterSpacing: 0.3,
        cursor: 'help',
      }}>
        TRI {arrow}
      </span>
    );
  };

  const HSGTBadge = ({ marketData, ticker }) => {
    if (!marketData) return null;
    if (!marketData.data?.moneyflow_hsgt?.rows) return null;

    const badgeStyle = color => ({
      fontFamily: MONO,
      fontSize: 7,
      fontWeight: 700,
      padding: '1px 4px',
      borderRadius: 3,
      background: `${color}10`,
      color,
      letterSpacing: 0.3,
      cursor: 'help',
    });

    if (!ticker.endsWith('.SZ') && !ticker.endsWith('.SH')) {
      return (
        <span title="HSGT data N/A — A-share only" style={badgeStyle(C.mid)}>
          —
        </span>
      );
    }

    const flow = marketData.data.moneyflow_hsgt;
    if (flow._status !== 'ok') {
      return (
        <span title={`HSGT data unavailable — status: ${flow._status || 'unknown'}`} style={badgeStyle(C.mid)}>
          —
        </span>
      );
    }

    const rows = [...(flow.rows || [])]
      .sort((a, b) => String(b.trade_date || '').localeCompare(String(a.trade_date || '')))
      .slice(0, 5);
    const net5d = rows.reduce((sum, row) => sum + (parseFloat(row.north_money) || 0), 0);
    const color = net5d >= 50000 ? C.green
                : net5d <= -50000 ? C.red
                : C.mid;
    const arrow = net5d >= 50000 ? '↑↑'
                : net5d <= -50000 ? '↓↓'
                : net5d > 0 ? '↑'
                : net5d < 0 ? '↓'
                : '=';
    const tooltip = 'HSGT 5d net flow: ' + net5d.toFixed(0) + ' RMB万\n'
      + 'north_money sum (last 5 days)\n'
      + 'positive = foreign net buying via 沪深港通\n'
      + 'negative = foreign net selling\n'
      + '[USP-critical signal — feeds 中国双认知 layer]';

    return (
      <span title={tooltip} style={badgeStyle(color)}>
        HSGT {arrow}
      </span>
    );
  };

  const ScoreBadge = ({ score }) => {
    const col = score >= 20 ? '#10b981' : score <= -20 ? '#ef4444' : '#6b7280';
    return (
      <span style={{
        fontFamily: MONO, fontSize:11, fontWeight:700,
        padding:'2px 7px', borderRadius:4,
        background: col + '18', color: col,
      }}>
        {score > 0 ? '+' : ''}{score}
      </span>
    );
  };

  const ActionBadge = ({ action }) => {
    const col = ACTION_COLOR[action] || '#6b7280';
    const label = lk === 'z' ? (ACTION_LABEL_ZH[action] || action) : action;
    return (
      <span style={{
        fontSize:10, fontWeight:700, padding:'3px 8px', borderRadius:4,
        background: col + '18', color: col, letterSpacing:0.3,
      }}>
        {ACTION_ICON[action] || ''} {label}
      </span>
    );
  };

  return (
    <div style={{maxWidth:960, margin:'0 auto'}}>

      {/* ── Header brief ─────────────────────────────────────────────────── */}
      <div style={{
        background: C.card, border:`1px solid ${C.border}`, borderRadius:10,
        padding:'14px 18px', marginBottom:14,
        display:'flex', justifyContent:'space-between', alignItems:'center',
      }}>
        <div>
          <div style={{fontSize:11, color:C.mid, marginBottom:3}}>
            {lk==='z' ? '今日交易台' : 'Trading Desk'} · {decision.date || '—'}
          </div>
          <div style={{fontSize:13, fontWeight:600, color:C.dark}}>{brief}</div>
        </div>
        <div style={{display:'flex', gap:8, flexWrap:'wrap'}}>
          {regimes.map(r => {
            const col = r.regime === 'PERMISSIVE' ? '#10b981' : r.regime === 'RESTRICTIVE' ? '#ef4444' : '#6b7280';
            return (
              <span key={r.sector} style={{
                fontSize:9, fontWeight:700, padding:'3px 7px', borderRadius:4,
                background: col + '15', color: col,
              }}>
                {lk==='z' ? r.sector_zh : r.sector} {r.regime}
              </span>
            );
          })}
        </div>
      </div>

      {/* ── NAV equity curve ─────────────────────────────────────────────── */}
      {snapshots.length >= 2 && (() => {
        const navs    = snapshots.map(s => s.nav);
        const dates   = snapshots.map(s => s.date?.slice(5));   // MM-DD
        const first   = navs[0];
        const last    = navs[navs.length - 1];
        const pct     = ((last / first) - 1) * 100;
        const minNav  = Math.min(...navs) * 0.995;
        const maxNav  = Math.max(...navs) * 1.005;
        const w = 680, h = 54;
        const pts = navs.map((v, i) => {
          const x = (i / (navs.length - 1)) * w;
          const y = h - ((v - minNav) / (maxNav - minNav)) * h;
          return `${x},${y}`;
        }).join(' ');
        const col = pct >= 0 ? '#10b981' : '#ef4444';
        return (
          <div style={{
            background:C.card, border:`1px solid ${C.border}`, borderRadius:10,
            padding:'12px 16px', marginBottom:14,
          }}>
            <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:8}}>
              <div style={{fontSize:10, fontWeight:600, color:C.mid, textTransform:'uppercase', letterSpacing:0.5}}>
                {lk==='z' ? '净值曲线 (CNY)' : 'NAV Equity Curve (CNY)'}
              </div>
              <div style={{display:'flex', gap:16, alignItems:'center'}}>
                <span style={{fontFamily:MONO, fontSize:13, fontWeight:800, color:C.dark}}>
                  ¥{last.toLocaleString(undefined, {maximumFractionDigits:0})}
                </span>
                <span style={{
                  fontFamily:MONO, fontSize:11, fontWeight:700, color:col,
                  background:`${col}12`, padding:'2px 8px', borderRadius:4,
                }}>
                  {pct >= 0 ? '+' : ''}{pct.toFixed(1)}%
                </span>
                <span style={{fontSize:9, color:C.mid}}>
                  {lk==='z' ? '自' : 'since'} {snapshots[0].date}
                </span>
              </div>
            </div>
            <svg width="100%" viewBox={`0 0 ${w} ${h}`} style={{display:'block', overflow:'visible'}}>
              <defs>
                <linearGradient id="navGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={col} stopOpacity="0.25"/>
                  <stop offset="100%" stopColor={col} stopOpacity="0.02"/>
                </linearGradient>
              </defs>
              <polygon
                points={`0,${h} ${pts} ${w},${h}`}
                fill="url(#navGrad)"
              />
              <polyline points={pts} fill="none" stroke={col} strokeWidth="2" strokeLinejoin="round"/>
              {navs.map((v, i) => {
                const x = (i / (navs.length - 1)) * w;
                const y = h - ((v - minNav) / (maxNav - minNav)) * h;
                return <circle key={i} cx={x} cy={y} r="3" fill={col}/>;
              })}
            </svg>
            {/* Date labels */}
            <div style={{display:'flex', justifyContent:'space-between', marginTop:4}}>
              {dates.map((d, i) => (
                <span key={i} style={{fontSize:8, color:C.mid}}>{d}</span>
              ))}
            </div>
          </div>
        );
      })()}

      {/* ── Portfolio risk flags ─────────────────────────────────────────── */}
      {risks.some(f => f.includes('⚠️') || f.includes('🔴') || f.includes('💰')) && (
        <div style={{
          background:'#fef9c3', border:'1px solid #fde047', borderRadius:8,
          padding:'10px 14px', marginBottom:14,
        }}>
          <div style={{fontSize:10, fontWeight:700, color:'#a16207', marginBottom:6}}>
            {lk==='z' ? '⚠️ 风险提示' : '⚠️ Portfolio Risk Flags'}
          </div>
          {risks.filter(f => f.includes('⚠️') || f.includes('🔴') || f.includes('💰')).map((f,i) => (
            <div key={i} style={{fontSize:11, color:'#92400e', lineHeight:1.6}}>{f}</div>
          ))}
        </div>
      )}

      {/* ── wrongIf Monitor ─────────────────────────────────────────────── */}
      {wrongifs.length > 0 && (
        <div style={{marginBottom:14}}>
          <div style={{fontSize:11, fontWeight:600, color:C.mid, marginBottom:8,
                       textTransform:'uppercase', letterSpacing:0.5}}>
            {lk==='z' ? '⚡ wrongIf 监控' : '⚡ wrongIf Monitor'} ({wrongifs.length})
          </div>
          {wrongifs.map((w, i) => {
            const isTriggered = w.status === 'TRIGGERED';
            const bg    = isTriggered ? '#fef2f2' : '#f8faff';
            const border= isTriggered ? '#fca5a5' : C.border;
            const col   = isTriggered ? '#dc2626' : C.mid;
            const icon  = isTriggered ? '🚨' : '👁️';
            return (
              <div key={i} style={{
                background: bg, border:`1px solid ${border}`, borderRadius:8,
                padding:'10px 14px', marginBottom:6,
              }}>
                <div style={{display:'flex', justifyContent:'space-between', alignItems:'flex-start', marginBottom:4}}>
                  <div style={{display:'flex', gap:8, alignItems:'center'}}>
                    <span style={{fontSize:10, fontFamily:MONO, fontWeight:700, color:C.dark}}>{w.ticker}</span>
                    <span style={{
                      fontSize:9, fontWeight:700, padding:'2px 6px', borderRadius:3,
                      background: isTriggered ? '#dc262620' : `${C.mid}15`,
                      color: isTriggered ? '#dc2626' : C.mid,
                    }}>{icon} {w.status}</span>
                  </div>
                  {w.actual != null && (
                    <span style={{fontSize:9, fontFamily:MONO, color:col}}>
                      actual: {typeof w.actual === 'number' ? w.actual.toFixed(1) : w.actual}
                      {w.threshold != null ? ` / threshold: ${w.threshold}` : ''}
                    </span>
                  )}
                </div>
                <div style={{fontSize:10, color:C.mid, marginBottom:3, fontStyle:'italic'}}>
                  wrongIf: {lk==='z' ? (w.wrongIf_z||w.wrongIf_e) : w.wrongIf_e}
                </div>
                <div style={{fontSize:11, color:col}}>
                  {lk==='z' ? w.note_z : w.note_e}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ── Held positions ───────────────────────────────────────────────── */}
      {held.length > 0 && (
        <div style={{marginBottom:14}}>
          <div style={{fontSize:11, fontWeight:600, color:C.mid, marginBottom:8, textTransform:'uppercase', letterSpacing:0.5}}>
            {lk==='z' ? '当前持仓' : 'Held Positions'} ({held.length})
          </div>
          {held.map(d => (
            <div key={d.ticker} style={{
              background: C.card, border:`1px solid ${C.border}`, borderRadius:10,
              padding:'14px 16px', marginBottom:8,
              borderLeft: `3px solid ${ACTION_COLOR[d.action] || C.border}`,
            }}>
              <div style={{display:'flex', justifyContent:'space-between', alignItems:'flex-start', marginBottom:8}}>
                <div style={{display:'flex', alignItems:'center', gap:10}}>
                  <span style={{fontFamily:MONO, fontSize:12, fontWeight:700, color:C.dark}}>{d.ticker}</span>
                  <ActionBadge action={d.action} />
                  <ScoreBadge score={d.confluence} />
                </div>
                <div style={{display:'flex', gap:12, fontSize:11, alignItems:'center'}}>
                  {d.pnl_pct != null && (
                    <span style={{color: d.pnl_pct >= 0 ? '#10b981' : '#ef4444', fontWeight:700, fontFamily:MONO}}>
                      {d.pnl_pct > 0 ? '+' : ''}{d.pnl_pct}%
                    </span>
                  )}
                  {d.vp_score != null && (
                    <span style={{color:C.mid, fontSize:10}}>VP {d.vp_score}</span>
                  )}
                  <FragilityPill frag={fragility[d.ticker]} />
                  <PersonaCluster overlay={personaOverlay} ticker={d.ticker} />
                  <TriangulatedBadge overlay={multiMethodValuation} ticker={d.ticker} />
                  <HSGTBadge marketData={tushareMarket} ticker={d.ticker} />
                  {d.holding_days != null && (
                    <span style={{color:C.mid, fontSize:10}}>{d.holding_days}d</span>
                  )}
                </div>
              </div>
              <div style={{fontSize:11, color:C.mid, lineHeight:1.7}}>
                {lk==='z' ? d.reason_z : d.reason_e}
              </div>
              {d.exit_trigger && (
                <div style={{
                  marginTop:8, fontSize:10, color:'#92400e',
                  background:'#fef3c7', padding:'4px 8px', borderRadius:4,
                  fontFamily:MONO,
                }}>
                  ⚡ {lk==='z' ? '离场条件：' : 'Exit trigger: '}{d.exit_trigger}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* ── Watchlist / BUY_WATCH ────────────────────────────────────────── */}
      {watch.length > 0 && (
        <div style={{marginBottom:14}}>
          <div style={{fontSize:11, fontWeight:600, color:C.mid, marginBottom:8, textTransform:'uppercase', letterSpacing:0.5}}>
            {lk==='z' ? '候选宇宙' : 'Universe Watchlist'} ({watch.length})
          </div>
          {watch.map(d => {
            const isBuyWatch = d.action === 'BUY_WATCH';
            // Use sizing from decision object (injected by daily_decision.py) or sizingMap fallback
            const sz = d.sizing || sizingMap[d.ticker] || null;
            return (
              <div key={d.ticker} style={{
                background: isBuyWatch ? `${C.blue}06` : C.card,
                border: `1px solid ${isBuyWatch ? C.blue + '40' : C.border}`,
                borderRadius:10, padding:'12px 16px', marginBottom:6,
              }}>
                <div style={{display:'flex', justifyContent:'space-between', alignItems:'flex-start', marginBottom: isBuyWatch ? 8 : 0}}>
                  <div style={{display:'flex', alignItems:'center', gap:10}}>
                    <span style={{fontFamily:MONO, fontSize:12, fontWeight:700, color:C.dark}}>{d.ticker}</span>
                    <ActionBadge action={d.action} />
                    <ScoreBadge score={d.confluence} />
                    {d.vp_score != null && (
                      <span style={{fontSize:10, color:C.mid}}>VP {d.vp_score}</span>
                    )}
                    <FragilityPill frag={fragility[d.ticker]} />
                    <PersonaCluster overlay={personaOverlay} ticker={d.ticker} />
                    <TriangulatedBadge overlay={multiMethodValuation} ticker={d.ticker} />
                    <HSGTBadge marketData={tushareMarket} ticker={d.ticker} />
                  </div>
                  <div style={{fontSize:11, color:C.mid, maxWidth:340, textAlign:'right', lineHeight:1.5}}>
                    {lk==='z' ? d.reason_z : d.reason_e}
                  </div>
                </div>
                {/* Position sizing card — only for BUY_WATCH */}
                {isBuyWatch && sz && (
                  <div style={{
                    display:'flex', gap:12, flexWrap:'wrap', alignItems:'center',
                    padding:'8px 10px', background:C.soft, borderRadius:6,
                    border:`1px solid ${C.blue}25`,
                  }}>
                    <div style={{display:'flex', flexDirection:'column', gap:1}}>
                      <div style={{fontSize:9, color:C.mid, fontWeight:600, textTransform:'uppercase'}}>
                        {lk==='z' ? '建议仓位' : 'Suggested Size'}
                      </div>
                      <div style={{fontSize:16, fontWeight:800, color:C.blue, fontFamily:MONO}}>
                        {sz.recommended_pct}%
                      </div>
                    </div>
                    <div style={{display:'flex', flexDirection:'column', gap:1}}>
                      <div style={{fontSize:9, color:C.mid, fontWeight:600, textTransform:'uppercase'}}>
                        {lk==='z' ? '金额' : 'Value'}
                      </div>
                      <div style={{fontSize:12, fontWeight:700, color:C.dark, fontFamily:MONO}}>
                        ¥{(sz.recommended_value||0).toLocaleString(undefined,{maximumFractionDigits:0})}
                      </div>
                    </div>
                    <div style={{display:'flex', flexDirection:'column', gap:1}}>
                      <div style={{fontSize:9, color:C.mid, fontWeight:600, textTransform:'uppercase'}}>
                        {lk==='z' ? 'ATR止损' : 'ATR Stop'}
                      </div>
                      <div style={{fontSize:12, fontWeight:700, color:C.gold, fontFamily:MONO}}>
                        {sz.stop_distance_pct}%
                      </div>
                    </div>
                    <div style={{
                      marginLeft:'auto', fontSize:9, fontWeight:700, padding:'3px 8px',
                      borderRadius:4,
                      background: sz.conviction_tier === 'HIGH CONVICTION' ? `${C.green}18`
                                : sz.conviction_tier === 'MEDIUM CONVICTION' ? `${C.blue}18`
                                : `${C.mid}18`,
                      color: sz.conviction_tier === 'HIGH CONVICTION' ? C.green
                           : sz.conviction_tier === 'MEDIUM CONVICTION' ? C.blue
                           : C.mid,
                    }}>
                      {lk==='z' ? (sz.conviction_tier_zh || sz.conviction_tier) : sz.conviction_tier}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* ── Signal Quality (feedback loop) ──────────────────────────────── */}
      {quality && quality.by_signal && quality.by_signal.length > 0 && (
        <div style={{marginBottom:14}}>
          <div style={{fontSize:11, fontWeight:600, color:C.mid, marginBottom:8,
                       textTransform:'uppercase', letterSpacing:0.5}}>
            {lk==='z' ? '📈 信号质量反馈' : '📈 Signal Quality Feedback'}
            <span style={{fontSize:9, fontWeight:400, marginLeft:8, opacity:0.7}}>
              {quality.portfolio_summary?.open_positions} {lk==='z' ? '个持仓' : 'positions'} ·{' '}
              {quality.portfolio_summary?.overall_win_rate}% {lk==='z' ? '胜率' : 'win rate'}
            </span>
          </div>

          {/* Insights row */}
          {quality.insights?.length > 0 && (
            <div style={{
              padding:'10px 14px', background:`${C.blue}06`,
              border:`1px solid ${C.blue}20`, borderRadius:8, marginBottom:10,
            }}>
              {quality.insights.map((ins, i) => (
                <div key={i} style={{fontSize:11, color:C.dark, lineHeight:1.7}}>
                  💡 {ins}
                </div>
              ))}
            </div>
          )}

          {/* Signal performance table */}
          <div style={{overflowX:'auto', borderRadius:8, border:`1px solid ${C.border}`}}>
            <table style={{width:'100%', fontSize:10, borderCollapse:'collapse'}}>
              <thead>
                <tr style={{background:C.soft}}>
                  {[
                    lk==='z' ? '信号类型' : 'Signal',
                    lk==='z' ? '出现' : 'Count',
                    lk==='z' ? '胜率' : 'Win%',
                    lk==='z' ? '均盈亏' : 'Avg P&L',
                    lk==='z' ? '最优' : 'Best',
                    lk==='z' ? '最差' : 'Worst',
                    lk==='z' ? '涉及标的' : 'Tickers',
                  ].map((h, i) => (
                    <th key={i} style={{
                      padding:'7px 10px', textAlign: i < 2 ? 'left' : 'right',
                      color:C.mid, fontWeight:600, borderBottom:`1px solid ${C.border}`,
                      fontSize:9, letterSpacing:'0.04em',
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {quality.by_signal.map((s, i) => {
                  const wr   = s.win_rate;
                  const wrCol= wr >= 60 ? C.green : wr >= 40 ? C.gold : C.red;
                  const pnlCol = s.avg_pnl >= 0 ? C.green : C.red;
                  return (
                    <tr key={i} style={{borderBottom:`1px solid ${C.border}`,
                                        background: i%2===0 ? 'transparent' : C.soft+'80'}}>
                      <td style={{padding:'7px 10px', fontFamily:MONO, fontWeight:700,
                                  color:C.dark, fontSize:10}}>{s.signal}</td>
                      <td style={{padding:'7px 10px', textAlign:'right', color:C.mid}}>{s.count}</td>
                      <td style={{padding:'7px 10px', textAlign:'right'}}>
                        <span style={{
                          fontWeight:700, fontFamily:MONO, color:wrCol,
                          background:`${wrCol}12`, padding:'2px 6px', borderRadius:3,
                        }}>{wr}%</span>
                      </td>
                      <td style={{padding:'7px 10px', textAlign:'right', fontFamily:MONO,
                                  fontWeight:700, color:pnlCol}}>
                        {s.avg_pnl > 0 ? '+' : ''}{s.avg_pnl}%
                      </td>
                      <td style={{padding:'7px 10px', textAlign:'right', fontFamily:MONO,
                                  color:C.green, fontSize:9}}>
                        {s.best_pnl != null ? `+${s.best_pnl}%` : '—'}
                      </td>
                      <td style={{padding:'7px 10px', textAlign:'right', fontFamily:MONO,
                                  color:C.red, fontSize:9}}>
                        {s.worst_pnl != null ? `${s.worst_pnl}%` : '—'}
                      </td>
                      <td style={{padding:'7px 10px', textAlign:'right', color:C.mid, fontSize:9}}>
                        {(s.tickers||[]).join(', ')}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* VP bucket summary */}
          {quality.vp_buckets?.length > 0 && (
            <div style={{display:'flex', gap:8, marginTop:10, flexWrap:'wrap'}}>
              {quality.vp_buckets.map((b, i) => {
                const col = b.win_rate >= 60 ? C.green : b.win_rate >= 40 ? C.gold : C.red;
                return (
                  <div key={i} style={{
                    flex:1, minWidth:100, padding:'10px 12px',
                    background:C.card, border:`1px solid ${C.border}`, borderRadius:8,
                  }}>
                    <div style={{fontSize:9, color:C.mid, fontWeight:600, marginBottom:4}}>
                      {b.bucket}
                    </div>
                    <div style={{fontSize:16, fontWeight:800, color:col, fontFamily:MONO}}>
                      {b.win_rate}%
                    </div>
                    <div style={{fontSize:9, color:C.mid}}>
                      {b.count} {lk==='z' ? '笔' : 'trades'} · avg {b.avg_pnl > 0 ? '+' : ''}{b.avg_pnl}%
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* ── Footer ───────────────────────────────────────────────────────── */}
      <div style={{fontSize:10, color:C.mid, textAlign:'center', marginTop:8}}>
        {lk==='z'
          ? '数据由 signal_confluence.py + daily_decision.py + signal_quality.py 生成 · 仅证据，不构成投资建议'
          : 'Generated by signal_confluence.py + daily_decision.py + signal_quality.py · Evidence only, no investment conclusions'}
      </div>
    </div>
  );
}

/* ── WATCHLIST TAB ────────────────────────────────────────────────────────── */
function Watchlist({ L, stocks: stocksMap, C }) {
  const stocks = Object.entries(stocksMap || STOCKS).map(([tk,s])=>({...s, ticker:tk}));
  const sectorData = PORTFOLIO.sectors.map((sec,i)=>({name:sec.name, value:sec.pct, fill:[C.blue,'#7B6BA5',C.gold,C.green,C.red][i]}));

  return (
    <div>
      <Card title={L('Portfolio Sectors','投资组合行业')} open={true} C={C}>
        <div style={{height:250, display:'flex', justifyContent:'center'}}>
          <ResponsiveContainer width='100%' height='100%'>
            <RechartsPie>
              <Pie data={sectorData} cx='50%' cy='50%' innerRadius={50} outerRadius={80} dataKey='value' label={({name,value})=>`${name} ${value}%`} labelLine={false} fontSize={10}>
                {sectorData.map((e,i)=><Cell key={i} fill={e.fill} />)}
              </Pie>
              <Tooltip contentStyle={{background:C.card, border:`1px solid ${C.border}`, borderRadius:6, fontSize:11}} />
            </RechartsPie>
          </ResponsiveContainer>
        </div>
      </Card>

      <Card title={L('Positions','持仓')} open={true} C={C}>
        {stocks.map((s,i)=>(
          <div key={i} style={{marginBottom:10, paddingBottom:10, borderBottom:i<stocks.length-1?`1px solid ${C.border}`:'none'}}>
            <div style={{...S.row, justifyContent:'space-between'}}>
              <div><div style={{fontSize:11, fontWeight:700, color:C.dark}}>{s.ticker}</div><div style={{fontSize:9, color:C.mid}}>{s.sector}</div></div>
              <div style={{textAlign:'right'}}><div style={{fontSize:11, fontWeight:700, color:C.dark}}>VP {s.vp}</div></div>
            </div>
          </div>
        ))}
      </Card>
    </div>
  );
}

/* ── SYSTEM TAB ────────────────────────────────────────────────────────── */
function SystemTab({ L, C }) {
  const layers = [
    { l:'L0', n:L('Data Ingestion + Calendar','数据摄取+日历'), status:'live' },
    { l:'L1', n:L('Security Master','标的主数据'), status:'live' },
    { l:'L2', n:L('Daily Screening Engine','每日筛选引擎'), status:'integrated' },
    { l:'L3', n:L('LLM Research Builder','LLM研究构建'), status:'integrated' },
    { l:'L4', n:L('VP Score + Watchlist','VP评分+关注列表'), status:'integrated' },
  ];
  const layerColors = [C.mid, C.gold, C.blue, C.red, C.green];
  return (
    <div>
      <div style={{...S.row, marginBottom:14}}>
        <Layers size={14} style={{color:C.mid}}/>
        <span style={{fontSize:10, fontWeight:700, letterSpacing:'.1em', color:C.mid}}>{L('5-LAYER ARCHITECTURE','五层架构')}</span>
      </div>
      {layers.map((l,i)=>(
        <div key={i} style={{...S.card, padding:12, borderLeftColor:layerColors[i], borderLeftWidth:4, borderColor:C.border, background:C.card, marginBottom:12}}>
          <div style={{...S.row, justifyContent:'space-between'}}>
            <div style={{...S.row, gap:8}}>
              <span style={{fontFamily:'monospace', fontWeight:800, color:layerColors[i]}}>{l.l}</span>
              <span style={{fontSize:12, fontWeight:600, color:C.dark}}>{l.n}</span>
            </div>
            <Tag text={l.status} c={l.status==='live'?C.green:C.blue} C={C}/>
          </div>
        </div>
      ))}
      <div style={{marginTop:14, padding:12, background:C.soft, borderRadius:8, fontSize:10, color:C.mid, lineHeight:1.8}}>
        <div><strong>VP Formula:</strong> 30% Expectation Gap + 25% Fundamental Acc + 20% Narrative Shift + 15% Low Coverage + 10% Catalyst Proximity</div>
        <div><strong>EV Formula:</strong> (P_win × Upside) − (P_loss × Downside)</div>
        <div><strong>Alpha Engines:</strong> A=Earnings Surprise · B=Multiple Expansion · C=Capital Revaluation</div>
      </div>
    </div>
  );
}

/* ── DEEP RESEARCH PANEL ─────────────────────────────────────────────────── */
function DeepResearchPanel({ L, lk, onComplete, C, universeStocks, enrichmentData }) {
  const [query, setQuery]           = useState('');
  const [drTicker, setDrTicker]     = useState('');
  const [drCompany, setDrCompany]   = useState('');   // resolved company name
  const [suggestions, setSuggestions] = useState([]);
  const [showSug, setShowSug]       = useState(false);
  const [drDir, setDrDir]           = useState('NEUTRAL');
  const [drContext, setDrContext]   = useState('');
  const [loading, setLoading]       = useState(false);
  const [error, setError]           = useState(null);
  const [progress, setProgress]     = useState(0);
  const [lastResearchMeta, setLastResearchMeta] = useState(null); // { consensus_source, pass1_search_results, enrichment_used, tavily_enabled }

  /* ── fuzzy search ── */
  const searchStocks = (q) => {
    setQuery(q);
    if (!q || q.length < 1) { setSuggestions([]); setShowSug(false); return; }
    const qn = q.toLowerCase().replace(/[.\s]/g, '');

    // Focus stocks always at top if they match
    const focusKeys = Object.keys(STOCKS);
    const focusMatches = focusKeys
      .filter(tk => {
        const s = STOCKS[tk];
        return tk.toLowerCase().replace(/\./g,'').includes(qn)
          || s.name.includes(q) || s.en.toLowerCase().includes(q.toLowerCase());
      })
      .map(tk => ({ ticker: tk, name: STOCKS[tk].name, en: STOCKS[tk].en, isFocus: true }));

    // Universe search
    const univMatches = (universeStocks || [])
      .filter(s => {
        const tkn = (s.ticker || '').toLowerCase().replace(/\./g,'');
        const nm  = s.name || '';
        const code = (s.code || '').toLowerCase();
        return tkn.includes(qn) || nm.includes(q) || code.includes(qn);
      })
      .slice(0, 10)
      .map(s => ({ ticker: s.ticker, name: s.name, en: s.name, exchange: s.exchange }));

    // Merge, deduplicate
    const seen = new Set(focusMatches.map(s => s.ticker));
    const merged = [
      ...focusMatches,
      ...univMatches.filter(s => !seen.has(s.ticker)),
    ].slice(0, 10);

    setSuggestions(merged);
    setShowSug(merged.length > 0);
  };

  const selectStock = (s) => {
    setDrTicker(s.ticker);
    setDrCompany(s.name || '');
    setQuery(`${s.name}  ${s.ticker}`);
    setSuggestions([]);
    setShowSug(false);
  };

  const handleQueryChange = (val) => {
    setDrTicker('');   // clear resolved ticker until user picks
    setDrCompany('');
    searchStocks(val);
  };

  /* If query looks exactly like a ticker, use it directly */
  const resolvedTicker = drTicker || (
    /^[A-Z0-9]{4,9}\.(SZ|SH|HK|US)$/i.test(query.trim()) ? query.trim().toUpperCase() : ''
  );

  const runResearch = async () => {
    const tk = resolvedTicker.trim();
    if (!tk) return;
    setLoading(true); setError(null); setProgress(10);

    // Two-pass generation: Pass 1 ~10s (consensus), Pass 2 ~20s (full research)
    // Progress ticks are spread over ~30s total
    const steps = [
      {p:12},{p:25},{p:40},{p:55},{p:70},{p:82},{p:90},
    ];
    let stepIdx = 0;
    const timer = setInterval(() => {
      if (stepIdx < steps.length) { setProgress(steps[stepIdx].p); stepIdx++; }
    }, 4000);

    // ── Build enrichment context from Dashboard state ──────────────────────
    // Collect the four real-time signals before the API call fires.
    // None of this requires new endpoints — everything is already in Dashboard state.
    let enrichment_context = null;
    if (enrichmentData) {
      const { liveData, newsPortfolio, regimeData, predictions } = enrichmentData;

      // 1. Live price signal
      const liveYahoo = liveData?.yahoo?.[tk];
      const livePrice = liveYahoo?.price?.last;
      const liveChangePct = liveYahoo?.price?.change_pct;

      // 2. Recent news (ticker-specific, last 5 days)
      const fiveDaysAgo = Date.now() - 5 * 24 * 3600 * 1000;
      const recentNews = (newsPortfolio || [])
        .filter(a => a.ticker === tk && new Date(a.published_at).getTime() > fiveDaysAgo)
        .slice(0, 6)
        .map(a => ({ title: a.title, source: a.source, published_at: a.published_at, summary: a.summary }));

      // 3. Sector regime — match ticker to sector via tickers[] array
      let sectorRegime = null;
      if (regimeData?.sectors) {
        const sector = regimeData.sectors.find(s => (s.tickers || []).includes(tk));
        if (sector) sectorRegime = sector.regime; // PERMISSIVE | NEUTRAL | RESTRICTIVE
      }

      // 4. Prior predictions for this ticker
      const priorPredictions = (predictions || [])
        .filter(p => p.ticker === tk)
        .map(p => ({ prediction: p.thesis || p.prediction, outcome: p.status, date: p.date, reason: p.notes }));

      // 5. Live fundamentals from yfinance (PE, PB, ROE, analyst targets, 52W range)
      //    These override AI training memory in the Pass 2 prompt via buildFundamentalsBlock()
      let liveFundamentals = null;
      if (liveYahoo) {
        const f = liveYahoo.fundamentals || {};
        const a = liveYahoo.analyst     || {};
        const p = liveYahoo.price       || {};
        const candidate = {
          pe_trailing:       f.pe_trailing       ?? null,
          pe_forward:        f.pe_forward        ?? null,
          ev_ebitda:         f.ev_ebitda         ?? null,
          gross_margin:      f.gross_margin      ?? null,
          operating_margin:  f.operating_margin  ?? null,
          roe:               f.roe               ?? null,
          revenue_growth:    f.revenue_growth    ?? null,
          target_mean:       a.target_mean       ?? null,
          target_low:        a.target_low        ?? null,
          target_high:       a.target_high       ?? null,
          num_analysts:      a.num_analysts      ?? null,
          low_52w:           p.low_52w           ?? null,
          high_52w:          p.high_52w          ?? null,
        };
        // Only include if at least one valuation or quality metric is present
        const hasData = Object.values(candidate).some(v => v != null);
        if (hasData) liveFundamentals = candidate;
      }

      // Only pass enrichment if we have at least one signal
      if (livePrice || recentNews.length > 0 || sectorRegime || priorPredictions.length > 0 || liveFundamentals) {
        enrichment_context = {
          live_price: livePrice ? `${livePrice.toFixed(2)}` : null,
          live_change_pct: liveChangePct ?? null,
          recent_news: recentNews,
          sector_regime: sectorRegime,
          prior_predictions: priorPredictions,
          fundamentals: liveFundamentals,
        };
      }
    }

    // GitHub Pages → always use stable Vercel URL (hardcoded, immune to stale secrets)
    // Vercel itself → relative /api (same origin, no CORS)
    const isGHPages = typeof window !== 'undefined' && window.location.hostname.endsWith('github.io');
    const apiBase   = isGHPages ? 'https://equity-research-ten.vercel.app' : '';
    const endpoint  = `${apiBase}/api/research`;

    try {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ticker: tk,
          company: drCompany || undefined,
          direction: drDir,
          context: drContext || undefined,
          enrichment_context: enrichment_context || undefined,
        }),
      });
      clearInterval(timer);
      const text = await res.text();
      let json;
      try { json = JSON.parse(text); }
      catch {
        // Show exact response for diagnosis
        throw new Error(`[${res.status}] ${endpoint}\nResponse: ${text.slice(0,200)}`);
      }
      if (!res.ok) throw new Error(json.error || `HTTP ${res.status}`);
      setProgress(100);
      // Store metadata about how this research was generated
      setLastResearchMeta({
        consensus_source:   json.consensus_source,
        sources_used:       json.sources_used || [],
        eastmoney_count:    json.eastmoney_count    || 0,
        tonghuashun_count:  json.tonghuashun_count  || 0,
        tavily_count:       json.tavily_count       || 0,
        enrichment_used:    json.enrichment_used,
        fundamentals_used:  json.fundamentals_used,
        tavily_enabled:     json.tavily_enabled,
        views_count:        (json.consensus_views || []).length,
      });
      onComplete(tk, json.data);
    } catch (err) {
      clearInterval(timer);
      setError(err.message);
      setProgress(0);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{background:C.card, border:`1px solid ${C.border}`, borderRadius:10, padding:20, maxWidth:520}}>
      <div style={{...S.row, gap:8, marginBottom:16}}>
        <Crosshair size={16} style={{color:C.blue}}/>
        <div style={{fontSize:14, fontWeight:700, color:C.dark}}>{L('Deep Research','深度研究')}</div>
        <span style={{fontSize:9, padding:'2px 6px', background:`${C.blue}15`, color:C.blue, borderRadius:3, fontWeight:700}}>AI</span>
      </div>
      <div style={{fontSize:10, color:C.mid, marginBottom:12, lineHeight:1.6}}>
        {L('Search by name or code — Chinese, English, or ticker. Claude AI runs a two-pass analysis (consensus enumeration → differentiated research) in ~30 seconds. Live price, sector regime, and recent news are injected automatically.',
           '输入公司名称（中/英文）或股票代码均可搜索。Claude AI 两阶段生成：先枚举卖方共识，再产出差异化研究，约30秒完成。实时价格、板块政体和最新新闻自动注入。')}
      </div>

      {/* Data source status row */}
      <div style={{display:'flex', gap:5, marginBottom:16, flexWrap:'wrap'}}>
        {lastResearchMeta ? (
          lastResearchMeta.consensus_source === 'live' ? (
            <>
              {lastResearchMeta.eastmoney_count > 0 && (
                <span style={{fontSize:9, padding:'2px 7px', borderRadius:3, fontWeight:700, background:`${C.green}18`, color:C.green}}>
                  📑 {L(`Eastmoney · ${lastResearchMeta.eastmoney_count} reports`, `东方财富 · ${lastResearchMeta.eastmoney_count}篇`)}
                </span>
              )}
              {lastResearchMeta.tonghuashun_count > 0 && (
                <span style={{fontSize:9, padding:'2px 7px', borderRadius:3, fontWeight:700, background:`${C.green}18`, color:C.green}}>
                  📑 {L(`Tonghuashun · ${lastResearchMeta.tonghuashun_count} reports`, `同花顺 · ${lastResearchMeta.tonghuashun_count}篇`)}
                </span>
              )}
              {lastResearchMeta.tavily_count > 0 && (
                <span style={{fontSize:9, padding:'2px 7px', borderRadius:3, fontWeight:700, background:`${C.green}18`, color:C.green}}>
                  🌐 {L(`Intl search · ${lastResearchMeta.tavily_count} results`, `国际搜索 · ${lastResearchMeta.tavily_count}条`)}
                </span>
              )}
            </>
          ) : (
            <span style={{fontSize:9, padding:'2px 7px', borderRadius:3, fontWeight:700, background:`${C.gold}18`, color:C.gold}}>
              🧠 {L('AI knowledge · no live data (东方财富+同花顺+Tavily returned empty)', 'AI知识兜底 · 三路来源均未返回数据')}
            </span>
          )
        ) : (
          <span style={{fontSize:9, padding:'2px 7px', borderRadius:3, fontWeight:700, background:`${C.blue}12`, color:C.blue}}>
            {L('东方财富 + 同花顺 + Intl search → Pass 2 full research', '东方财富 + 同花顺 + 国际搜索 → 完整研究')}
          </span>
        )}
        {lastResearchMeta?.enrichment_used && (
          <span style={{fontSize:9, padding:'2px 7px', borderRadius:3, fontWeight:700, background:`${C.blue}12`, color:C.blue}}>
            📡 {L('Price + news + regime injected', '实时价格+新闻+政体已注入')}
          </span>
        )}
        {lastResearchMeta?.fundamentals_used && (
          <span style={{fontSize:9, padding:'2px 7px', borderRadius:3, fontWeight:700, background:`${C.green}12`, color:C.green}}>
            📊 {L('Live fundamentals injected (PE/ROE/targets)', '实时基本面已注入 (PE/ROE/目标价)')}
          </span>
        )}
      </div>

      {/* ── Fuzzy stock search ── */}
      <div style={{marginBottom:12, position:'relative'}}>
        <div style={{fontSize:10, fontWeight:600, color:C.mid, marginBottom:4}}>
          {L('Stock','股票')} *
          {resolvedTicker && (
            <span style={{marginLeft:8, display:'inline-flex', alignItems:'center', gap:6,
                          background:`${C.blue}12`, border:`1px solid ${C.blue}30`,
                          borderRadius:5, padding:'1px 8px'}}>
              <span style={{color:C.blue, fontFamily:'monospace', fontSize:11}}>{resolvedTicker}</span>
              {drCompany && <span style={{color:C.dark, fontSize:11}}>· {drCompany}</span>}
            </span>
          )}
        </div>
        <input
          value={query}
          onChange={e => handleQueryChange(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter' && !loading) { setShowSug(false); runResearch(); }
            if (e.key === 'Escape') setShowSug(false);
          }}
          onBlur={() => setTimeout(() => setShowSug(false), 150)}
          onFocus={() => suggestions.length > 0 && setShowSug(true)}
          placeholder={L('潮宏基 / Chow Tai Fook / 3600.HK / 300308','潮宏基 / 中际旭创 / 3600.HK / 300308')}
          disabled={loading}
          style={{width:'100%', padding:'9px 11px', border:`1.5px solid ${resolvedTicker ? C.blue : C.border}`,
                  borderRadius:6, fontSize:12, background:C.soft, color:C.dark, outline:'none',
                  boxSizing:'border-box'}}
        />

        {/* Dropdown */}
        {showSug && suggestions.length > 0 && (
          <div style={{
            position:'absolute', top:'100%', left:0, right:0, zIndex:999,
            background:C.card, border:`1px solid ${C.border}`, borderRadius:7,
            boxShadow:'0 6px 24px rgba(0,0,0,0.18)', maxHeight:280, overflowY:'auto', marginTop:3,
          }}>
            {suggestions.map((s, i) => (
              <div key={i}
                onMouseDown={() => selectStock(s)}
                style={{
                  display:'flex', alignItems:'center', justifyContent:'space-between',
                  padding:'9px 12px', cursor:'pointer', borderBottom:i<suggestions.length-1?`1px solid ${C.border}`:'none',
                  background: s.isFocus ? `${C.blue}08` : 'transparent',
                  transition:'background .1s',
                }}
                onMouseEnter={e => e.currentTarget.style.background = `${C.blue}12`}
                onMouseLeave={e => e.currentTarget.style.background = s.isFocus ? `${C.blue}08` : 'transparent'}
              >
                <div>
                  <span style={{fontSize:12, fontWeight:700, color:C.dark}}>{s.name}</span>
                  {s.isFocus && <span style={{marginLeft:5, fontSize:9, color:C.blue, fontWeight:600}}>★ focus</span>}
                  {s.en && s.en !== s.name && (
                    <span style={{marginLeft:6, fontSize:10, color:C.mid}}>{s.en}</span>
                  )}
                </div>
                <span style={{fontSize:10, fontFamily:'monospace', color:C.blue, flexShrink:0, marginLeft:10}}>
                  {s.ticker}
                </span>
              </div>
            ))}
            <div style={{padding:'6px 12px', fontSize:9, color:C.mid, borderTop:`1px solid ${C.border}`}}>
              {L('↵ Enter to search · click to select','↵ 回车搜索 · 点击选中')}
            </div>
          </div>
        )}
      </div>

      <div style={{marginBottom:12}}>
        <div style={{fontSize:10, fontWeight:600, color:C.mid, marginBottom:4}}>{L('Direction Bias','方向偏好')}</div>
        <div style={{display:'flex', gap:4}}>
          {['LONG','NEUTRAL','SHORT'].map(d=>(
            <button key={d} onClick={()=>setDrDir(d)} disabled={loading} style={{
              flex:1, padding:'6px 0', border:`1px solid ${drDir===d?(d==='LONG'?C.green:d==='SHORT'?C.red:C.blue):C.border}`,
              background:drDir===d?`${d==='LONG'?C.green:d==='SHORT'?C.red:C.blue}15`:'transparent',
              color:drDir===d?(d==='LONG'?C.green:d==='SHORT'?C.red:C.blue):C.mid,
              borderRadius:5, cursor:'pointer', fontSize:10, fontWeight:700, transition:'all .15s',
            }}>{d}</button>
          ))}
        </div>
      </div>

      <div style={{marginBottom:16}}>
        <div style={{fontSize:10, fontWeight:600, color:C.mid, marginBottom:4}}>{L('Context (optional)','研究背景（选填）')}</div>
        <textarea value={drContext} onChange={e=>setDrContext(e.target.value)}
          placeholder={L('What prompted this research? e.g. "Earnings beat, want to check if thesis holds"','什么触发了这次研究？如"财报超预期，想检验论点"')}
          disabled={loading} rows={2}
          style={{width:'100%', padding:'8px 10px', border:`1px solid ${C.border}`, borderRadius:6, fontSize:11, background:C.soft, color:C.dark, outline:'none', resize:'vertical', fontFamily:'inherit'}}/>
      </div>

      {loading && (
        <div style={{marginBottom:14}}>
          <div style={{height:4, background:C.soft, borderRadius:2, overflow:'hidden', marginBottom:6}}>
            <div style={{height:'100%', background:C.blue, borderRadius:2, width:`${progress}%`, transition:'width .5s'}}></div>
          </div>
          <div style={{fontSize:10, color:C.blue, fontWeight:600, textAlign:'center'}}>
            {progress < 20 ? L('Connecting to Claude...','连接Claude...') :
             progress < 40 ? L('Analyzing macro context...','分析宏观背景...') :
             progress < 60 ? L('Building business model...','构建商业模式...') :
             progress < 80 ? L('Mapping catalysts & risks...','映射催化剂与风险...') :
             progress < 100 ? L('Scoring VP decomposition...','计算VP分解评分...') :
             L('Complete!','完成！')}
          </div>
        </div>
      )}

      {error && (
        <div style={{marginBottom:14, padding:10, background:`${C.red}10`, border:`1px solid ${C.red}30`, borderRadius:6}}>
          <div style={{fontSize:11, color:C.red, fontWeight:600, marginBottom:4}}>{L('Error','错误')}</div>
          <div style={{fontSize:10, color:C.dark, lineHeight:1.5}}>{error}</div>
        </div>
      )}

      <button onClick={runResearch} disabled={loading || !resolvedTicker} style={{
        width:'100%', padding:'10px 0', border:'none', borderRadius:6, cursor:loading?'wait':'pointer',
        background:loading?C.soft:resolvedTicker?C.blue:C.soft,
        color:loading||!resolvedTicker?C.mid:'#fff', fontSize:12, fontWeight:700,
        transition:'all .2s',
      }}>
        {loading
          ? L('Generating Report...','生成报告中...')
          : resolvedTicker
            ? `${L('Generate Research','生成研究')} · ${resolvedTicker}`
            : L('Search and select a stock above','请先搜索并选择股票')}
      </button>

      <div style={{fontSize:9, color:C.mid, marginTop:10, textAlign:'center', lineHeight:1.4}}>
        {L('Powered by Claude Sonnet · Evidence only, no investment conclusions',
           'Claude Sonnet驱动 · 仅提供证据，不提供投资结论')}
      </div>
    </div>
  );
}

/* ── TECHNICAL ANALYSIS COMPONENT ───────────────────────────────────────── */
const TechnicalAnalysis = ({ ticker, liveData, L, lk, C }) => {
  const yd = liveData?.yahoo?.[ticker];
  if (!yd || yd.error) return (
    <div style={{padding:16, textAlign:'center', color:C.mid, fontSize:12}}>
      <WifiOff size={16} style={{marginBottom:6}}/><br/>
      {L('No live data available. Run the data fetcher or push to GitHub to enable automated updates.',
         '暂无实时数据。运行数据脚本或推送至GitHub以启用自动更新。')}
    </div>
  );

  const p = yd.price || {};
  const t = yd.technical || {};
  const f = yd.fundamentals || {};
  const a = yd.analyst || {};
  const nb = liveData?.akshare?.northbound;
  const isAShare = yd.meta?.exchange === 'SZ' || yd.meta?.exchange === 'SH';

  const fmt = (v, suffix='') => v != null ? (typeof v === 'number' ? v.toLocaleString() + suffix : v + suffix) : '—';
  const fmtPct = v => v != null ? (v * 100).toFixed(1) + '%' : '—';
  const rsiColor = t.rsi_14 > 70 ? C.red : t.rsi_14 < 30 ? C.green : C.blue;
  const chgColor = p.change_pct > 0 ? C.green : p.change_pct < 0 ? C.red : C.mid;

  // SMA trend bar component
  const SmaBar = ({ label, val, above }) => (
    <div style={{display:'flex', alignItems:'center', gap:8, marginBottom:4}}>
      <span style={{fontSize:10, color:C.mid, width:52}}>{label}</span>
      <span style={{fontSize:11, fontFamily:'monospace', fontWeight:700, color:C.dark}}>{fmt(val)}</span>
      {above != null && (
        <span style={{...S.tag(above ? C.green : C.red), fontSize:9}}>
          {above ? (lk==='e'?'ABOVE':'上方') : (lk==='e'?'BELOW':'下方')}
        </span>
      )}
    </div>
  );

  return (
    <div>
      {/* Price Action Header */}
      <div style={{display:'flex', gap:12, flexWrap:'wrap', marginBottom:14}}>
        <div style={{flex:'1 1 160px', padding:12, background:`${C.blue}08`, borderRadius:8, border:`1px solid ${C.blue}20`}}>
          <div style={{fontSize:10, color:C.mid, marginBottom:4}}>{L('Last Price','最新价')}</div>
          <div style={{fontSize:22, fontWeight:800, color:chgColor, fontFamily:'monospace'}}>
            {yd.meta?.currency === 'CNY' ? '¥' : 'HK$'}{fmt(p.last)}
          </div>
          <div style={{fontSize:11, color:chgColor, fontWeight:600}}>
            {p.change_pct > 0 ? '+' : ''}{fmt(p.change_pct, '%')}
          </div>
        </div>
        <div style={{flex:'1 1 160px', padding:12, background:`${C.soft}`, borderRadius:8, border:`1px solid ${C.border}`}}>
          <div style={{fontSize:10, color:C.mid, marginBottom:4}}>{L('52W Range','52周区间')}</div>
          <div style={{fontSize:13, fontWeight:700, fontFamily:'monospace', color:C.dark}}>
            {fmt(p.low_52w)} — {fmt(p.high_52w)}
          </div>
          <div style={{marginTop:6, height:6, background:`${C.border}`, borderRadius:3, position:'relative'}}>
            {p.low_52w && p.high_52w && p.last && (
              <div style={{
                position:'absolute', left:`${Math.min(100,Math.max(0,(p.last-p.low_52w)/(p.high_52w-p.low_52w)*100))}%`,
                top:-2, width:10, height:10, borderRadius:5, background:C.blue, transform:'translateX(-5px)'
              }}></div>
            )}
          </div>
        </div>
        <div style={{flex:'1 1 120px', padding:12, background:`${C.soft}`, borderRadius:8, border:`1px solid ${C.border}`}}>
          <div style={{fontSize:10, color:C.mid, marginBottom:4}}>{L('Volume Ratio','量比')}</div>
          <div style={{fontSize:18, fontWeight:800, fontFamily:'monospace', color: p.volume_ratio > 1.5 ? C.gold : p.volume_ratio > 1 ? C.green : C.mid}}>
            {fmt(p.volume_ratio, 'x')}
          </div>
          <div style={{fontSize:9, color:C.mid}}>{L('vs 20d avg','vs 20日均量')}</div>
        </div>
      </div>

      {/* Technical Indicators Grid */}
      <div style={{display:'flex', gap:12, flexWrap:'wrap', marginBottom:14}}>
        {/* Moving Averages */}
        <div style={{flex:'1 1 180px', padding:12, background:C.soft, borderRadius:8, border:`1px solid ${C.border}`}}>
          <div style={{fontSize:11, fontWeight:700, color:C.dark, marginBottom:8}}>{L('Moving Averages','均线')}</div>
          <SmaBar label="SMA 20" val={t.sma_20} above={t.above_sma_20}/>
          <SmaBar label="SMA 50" val={t.sma_50} above={t.above_sma_50}/>
          <SmaBar label="SMA 200" val={t.sma_200} above={t.above_sma_200}/>
        </div>

        {/* RSI */}
        <div style={{flex:'1 1 120px', padding:12, background:C.soft, borderRadius:8, border:`1px solid ${C.border}`, textAlign:'center'}}>
          <div style={{fontSize:11, fontWeight:700, color:C.dark, marginBottom:8}}>RSI (14)</div>
          <div style={{fontSize:28, fontWeight:800, fontFamily:'monospace', color:rsiColor}}>{fmt(t.rsi_14)}</div>
          <div style={{marginTop:6, height:6, background:C.border, borderRadius:3, position:'relative'}}>
            <div style={{position:'absolute', left:0, width:'30%', height:'100%', background:`${C.green}40`, borderRadius:'3px 0 0 3px'}}></div>
            <div style={{position:'absolute', right:0, width:'30%', height:'100%', background:`${C.red}40`, borderRadius:'0 3px 3px 0'}}></div>
            {t.rsi_14 && <div style={{position:'absolute', left:`${t.rsi_14}%`, top:-2, width:10, height:10, borderRadius:5, background:rsiColor, transform:'translateX(-5px)'}}></div>}
          </div>
          <div style={{display:'flex', justifyContent:'space-between', fontSize:8, color:C.mid, marginTop:2}}>
            <span>{L('Oversold','超卖')}</span><span>{L('Overbought','超买')}</span>
          </div>
        </div>

        {/* Analyst Consensus */}
        <div style={{flex:'1 1 160px', padding:12, background:C.soft, borderRadius:8, border:`1px solid ${C.border}`}}>
          <div style={{fontSize:11, fontWeight:700, color:C.dark, marginBottom:8}}>{L('Analyst Targets','分析师目标价')}</div>
          {a.target_mean && (
            <div>
              <div style={{display:'flex', justifyContent:'space-between', marginBottom:4}}>
                <span style={{fontSize:10, color:C.mid}}>{L('Mean','均值')}</span>
                <span style={{fontSize:12, fontWeight:700, fontFamily:'monospace', color:C.dark}}>{fmt(a.target_mean)}</span>
              </div>
              <div style={{display:'flex', justifyContent:'space-between', marginBottom:4}}>
                <span style={{fontSize:10, color:C.mid}}>{L('Range','区间')}</span>
                <span style={{fontSize:10, fontFamily:'monospace', color:C.mid}}>{fmt(a.target_low)} — {fmt(a.target_high)}</span>
              </div>
              {p.last && a.target_mean && (
                <div style={{display:'flex', justifyContent:'space-between', marginTop:6}}>
                  <span style={{fontSize:10, color:C.mid}}>{L('Upside','上行空间')}</span>
                  <span style={{...S.tag(((a.target_mean-p.last)/p.last) > 0 ? C.green : C.red), fontSize:10, fontWeight:700}}>
                    {(((a.target_mean-p.last)/p.last)*100).toFixed(1)}%
                  </span>
                </div>
              )}
              <div style={{fontSize:9, color:C.mid, marginTop:4}}>{fmt(a.num_analysts)} {L('analysts','位分析师')}</div>
            </div>
          )}
        </div>
      </div>

      {/* Live Fundamentals Override */}
      <div style={{padding:12, background:C.soft, borderRadius:8, border:`1px solid ${C.border}`, marginBottom:14}}>
        <div style={{fontSize:11, fontWeight:700, color:C.dark, marginBottom:8}}>{L('Live Fundamentals','实时基本面')}</div>
        <div style={{display:'flex', gap:16, flexWrap:'wrap'}}>
          {[
            {label:'P/E (TTM)', val: f.pe_trailing},
            {label:'P/E (Fwd)', val: f.pe_forward},
            {label:'EV/EBITDA', val: f.ev_ebitda},
            {label:L('Gross Margin','毛利率'), val: f.gross_margin, pct:true},
            {label:L('Op Margin','营业利润率'), val: f.operating_margin, pct:true},
            {label:'ROE', val: f.roe, pct:true},
            {label:L('Rev Growth','营收增速'), val: f.revenue_growth, pct:true},
          ].map((item,i) => (
            <div key={i} style={{minWidth:80}}>
              <div style={{fontSize:9, color:C.mid}}>{item.label}</div>
              <div style={{fontSize:12, fontWeight:700, fontFamily:'monospace', color:C.dark}}>
                {item.pct ? fmtPct(item.val) : fmt(item.val != null ? +item.val.toFixed(1) : null)}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Northbound Flow (A-share only) */}
      {isAShare && nb && !nb.error && (
        <div style={{padding:12, background:`${nb.trend === 'inflow' ? C.green : C.red}08`, borderRadius:8, border:`1px solid ${nb.trend === 'inflow' ? C.green : C.red}25`, marginBottom:14}}>
          <div style={{fontSize:11, fontWeight:700, color:C.dark, marginBottom:8, display:'flex', alignItems:'center', gap:6}}>
            <Globe size={13}/> {L('Northbound Flow (沪深港通)','北向资金(沪深港通)')}
            <span style={{...S.tag(nb.trend === 'inflow' ? C.green : C.red), fontSize:9}}>
              {nb.trend === 'inflow' ? L('NET INFLOW','净流入') : L('NET OUTFLOW','净流出')}
            </span>
          </div>
          <div style={{display:'flex', gap:16, flexWrap:'wrap'}}>
            <div>
              <div style={{fontSize:9, color:C.mid}}>{L('Latest Daily','最新日度')}</div>
              <div style={{fontSize:13, fontWeight:700, fontFamily:'monospace', color: nb.latest_net_flow > 0 ? C.green : C.red}}>
                {(nb.latest_net_flow / 1e8).toFixed(1)}{L('B CNY','亿元')}
              </div>
            </div>
            <div>
              <div style={{fontSize:9, color:C.mid}}>{L('5D Cumulative','5日累计')}</div>
              <div style={{fontSize:13, fontWeight:700, fontFamily:'monospace', color: nb['5d_cumulative'] > 0 ? C.green : C.red}}>
                {(nb['5d_cumulative'] / 1e8).toFixed(1)}{L('B CNY','亿元')}
              </div>
            </div>
            <div>
              <div style={{fontSize:9, color:C.mid}}>{L('20D Cumulative','20日累计')}</div>
              <div style={{fontSize:13, fontWeight:700, fontFamily:'monospace', color: nb['20d_cumulative'] > 0 ? C.green : C.red}}>
                {(nb['20d_cumulative'] / 1e8).toFixed(1)}{L('B CNY','亿元')}
              </div>
            </div>
          </div>
          <div style={{fontSize:9, color:C.mid, marginTop:6}}>
            {L('Key A-share alpha signal. Persistent northbound inflow historically correlates with 2-4 week price momentum.',
               'A股关键alpha信号。持续北向净流入历史上与2-4周价格动量正相关。')}
          </div>
        </div>
      )}

      {/* AI Limitation */}
      <div style={{fontSize:9, color:C.mid, padding:'8px 0', borderTop:`1px solid ${C.border}`}}>
        <AlertCircle size={10} style={{verticalAlign:'middle', marginRight:4}}/>
        {L('Technical indicators computed from daily close data. RSI/SMA may lag intraday moves. Northbound flow is T+1. Volume data excludes dark pool.',
           '技术指标基于日收盘数据计算。RSI/SMA可能滞后于盘中波动。北向资金为T+1。成交量数据不含暗池。')}
      </div>
    </div>
  );
};

/* ── CONSENSUS PANEL ─────────────────────────────────────────────────── */
const ConsensusPanel = ({ ticker, liveData, L, lk, C }) => {
  const cons = liveData?.consensus?.[ticker];
  const yd   = liveData?.yahoo?.[ticker];
  if (!cons) return (
    <div style={{padding:14, textAlign:'center', color:C.mid, fontSize:11}}>
      <Database size={14} style={{marginBottom:4}}/><br/>
      {L('No consensus data. Run python3 scripts/fetch_data.py to generate.',
         '暂无一致预期数据。运行 python3 scripts/fetch_data.py 以生成。')}
    </div>
  );

  const lastPrice = yd?.price?.last;
  const fmt = v => v != null ? (+v).toLocaleString(undefined, {maximumFractionDigits:2}) : '—';
  const fmtB = v => { if (!v) return '—'; const a=Math.abs(v); return (a>=1e9?(a/1e9).toFixed(2)+'B':a>=1e6?(a/1e6).toFixed(1)+'M':fmt(v)); };

  // Compute upside/downside vs current price
  const targetMedian = cons.target_median;
  const upside = (targetMedian && lastPrice) ? ((targetMedian / lastPrice - 1) * 100).toFixed(1) : null;
  const upsideColor = upside > 0 ? C.green : upside < 0 ? C.red : C.mid;

  // EPS revision trend (momentum)
  const epsTrend = cons.eps_trend;
  const revisionMomentum = epsTrend ? (() => {
    const periods = Object.values(epsTrend);
    if (!periods.length) return null;
    const p = periods[0];
    const curr = p?.current, ago90 = p?.['90d_ago'];
    if (curr && ago90 && ago90 !== 0) return ((curr - ago90) / Math.abs(ago90) * 100).toFixed(1);
    return null;
  })() : null;

  return (
    <div>
      {/* Headline consensus vs price */}
      <div style={{display:'flex', gap:12, flexWrap:'wrap', marginBottom:14}}>
        {targetMedian && (
          <div style={{flex:'1 1 140px', padding:12, background:`${upsideColor}08`, borderRadius:8, border:`1px solid ${upsideColor}25`}}>
            <div style={{fontSize:10, color:C.mid}}>{L('Consensus Target','一致目标价')}</div>
            <div style={{fontSize:22, fontWeight:800, fontFamily:'monospace', color:C.dark}}>{fmt(targetMedian)}</div>
            {upside && <div style={{fontSize:12, fontWeight:700, color:upsideColor}}>{upside > 0 ? '+' : ''}{upside}% {L('upside','上行空间')}</div>}
            <div style={{fontSize:9, color:C.mid}}>{cons.num_analysts || '?'} {L('analysts','位分析师')} · {cons.target_low && cons.target_high ? fmt(cons.target_low) + ' – ' + fmt(cons.target_high) : ''}</div>
          </div>
        )}
        {revisionMomentum && (
          <div style={{flex:'1 1 120px', padding:12, background:C.soft, borderRadius:8, border:`1px solid ${C.border}`}}>
            <div style={{fontSize:10, color:C.mid}}>{L('EPS Revision (90d)','EPS修正(90日)')}</div>
            <div style={{fontSize:20, fontWeight:800, fontFamily:'monospace', color: revisionMomentum > 0 ? C.green : C.red}}>
              {revisionMomentum > 0 ? '+' : ''}{revisionMomentum}%
            </div>
            <div style={{fontSize:9, color:C.mid}}>{L('Estimate momentum','预期动量')}</div>
          </div>
        )}
        {cons.fy1_profit_median && (
          <div style={{flex:'1 1 120px', padding:12, background:C.soft, borderRadius:8, border:`1px solid ${C.border}`}}>
            <div style={{fontSize:10, color:C.mid}}>{L('FY+1 Profit Consensus','FY+1净利润共识')}</div>
            <div style={{fontSize:16, fontWeight:800, fontFamily:'monospace', color:C.dark}}>{fmtB(cons.fy1_profit_median)}</div>
            <div style={{fontSize:9, color:C.mid}}>{L('Median of brokers','券商中位数')}</div>
          </div>
        )}
      </div>

      {/* Beat/Miss History */}
      {cons.beat_miss_history && cons.beat_miss_history.length > 0 && (
        <div style={{marginBottom:14}}>
          <div style={{fontSize:11, fontWeight:700, color:C.dark, marginBottom:8}}>{L('Historical Beat/Miss','历史超预期/不及预期')}</div>
          <div style={{overflowX:'auto'}}>
            <table style={{width:'100%', fontSize:10, borderCollapse:'collapse', minWidth:350}}>
              <thead><tr style={{background:C.soft}}>
                <th style={{textAlign:'left', padding:'6px 8px', color:C.mid, borderBottom:`1px solid ${C.border}`}}>{L('Date','日期')}</th>
                <th style={{textAlign:'right', padding:'6px 8px', color:C.mid, borderBottom:`1px solid ${C.border}`}}>{L('Estimate','预期EPS')}</th>
                <th style={{textAlign:'right', padding:'6px 8px', color:C.mid, borderBottom:`1px solid ${C.border}`}}>{L('Actual','实际EPS')}</th>
                <th style={{textAlign:'right', padding:'6px 8px', color:C.mid, borderBottom:`1px solid ${C.border}`}}>{L('Surprise%','超预期%')}</th>
              </tr></thead>
              <tbody>
                {cons.beat_miss_history.map((h, i) => {
                  const sp = h.surprise_pct || 0;
                  const sc = sp > 0 ? C.green : sp < 0 ? C.red : C.mid;
                  return (
                    <tr key={i} style={{borderBottom:`1px solid ${C.border}`}}>
                      <td style={{padding:'6px 8px', color:C.dark}}>{h.date?.slice(0,10)}</td>
                      <td style={{padding:'6px 8px', textAlign:'right', fontFamily:'monospace', color:C.mid}}>{fmt(h.eps_estimate)}</td>
                      <td style={{padding:'6px 8px', textAlign:'right', fontFamily:'monospace', color:C.dark, fontWeight:700}}>{fmt(h.eps_actual)}</td>
                      <td style={{padding:'6px 8px', textAlign:'right', fontFamily:'monospace', fontWeight:700, color:sc}}>
                        {sp > 0 ? '+' : ''}{(sp * 100).toFixed(1)}%
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Variant perception gap */}
      {targetMedian && lastPrice && (
        <div style={{padding:10, background:`${C.blue}08`, borderRadius:6, border:`1px solid ${C.blue}20`, fontSize:10, color:C.mid, lineHeight:1.6}}>
          <strong style={{color:C.dark}}>{L('Variant Lens:','变体视角：')}</strong>{' '}
          {L('Consensus target implies','一致预期目标价隐含')} {upside > 0 ? '+' : ''}{upside}% {L('upside from current price.','的上行空间。')}
          {' '}{L('Your VP thesis should explain why the market is either wrong on the target OR wrong on the timing.',
                    '你的VP论点应解释市场在目标价还是时间线上存在错误认知。')}
        </div>
      )}
      <div style={{fontSize:8, color:C.mid, marginTop:6}}>
        {L('Source: ','来源：')}{cons.source === 'yfinance' ? 'Yahoo Finance (yfinance)' : 'AKShare / EastMoney'}.
        {' '}{L('Estimates subject to revision. Not investment advice.','预测数据可能随时修正。非投资建议。')}
      </div>
    </div>
  );
};

/* ── FLOW PANEL (Northbound + Southbound + Dragon & Tiger + Margin) ──────── */
const FlowPanel = ({ liveData, L, lk, C }) => {
  const [apiData,  setApiData]  = useState(null);   // live from api/capital-flow
  const [apiErr,   setApiErr]   = useState(false);
  const [apiLoading, setApiLoading] = useState(true);
  const [staticData, setStaticData] = useState(null); // fallback: flow_data.json

  // ── 1. Try live Vercel API ──────────────────────────────────────────────
  useEffect(() => {
    const API_BASE = import.meta.env.VITE_API_BASE || 'https://equity-research-ten.vercel.app';
    fetch(`${API_BASE}/api/capital-flow`)
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(d => { setApiData(d); setApiLoading(false); })
      .catch(() => { setApiErr(true); setApiLoading(false); });
  }, []);

  // ── 2. Static fallback (flow_data.json committed by local run) ─────────
  useEffect(() => {
    const base = DATA_BASE;
    fetch(base + 'data/flow_data.json')
      .then(r => { if (!r.ok) throw new Error(); return r.json(); })
      .then(d => setStaticData(d))
      .catch(() => {});
  }, []);

  // Merge: live API wins; fall back to akshare in liveData; then static JSON
  const nb     = (apiData?.available && apiData?.northbound) || liveData?.akshare?.northbound || staticData?.northbound || {};
  const sb     = (apiData?.available && apiData?.southbound) || liveData?.akshare?.southbound || staticData?.southbound || {};
  const dt     = staticData?.dragon_tiger || liveData?.akshare?.dragon_tiger || [];
  const margin = staticData?.margin || liveData?.akshare?.margin || {};
  const hist   = apiData?.history || [];
  const dataSource = apiData?.source || (staticData ? 'flow_data.json' : null);

  const FlowCard = ({ title, data, icon }) => {
    if (!data || Object.keys(data).length === 0) return null;
    const nf = data.latest_net_flow || 0;
    const isIn = nf > 0;
    const color = isIn ? C.green : C.red;
    return (
      <div style={{flex:'1 1 180px', padding:14, background:`${color}08`, borderRadius:8, border:`1px solid ${color}25`}}>
        <div style={{...S.row, gap:6, marginBottom:8}}>
          <span style={{fontSize:13}}>{icon}</span>
          <div style={{fontSize:11, fontWeight:700, color:C.dark}}>{title}</div>
          <span style={{...S.tag(color), fontSize:9}}>{isIn ? L('INFLOW','流入') : L('OUTFLOW','流出')}</span>
        </div>
        <div style={{fontSize:22, fontWeight:800, fontFamily:'monospace', color}}>
          {nf >= 0 ? '+' : ''}{(nf / 1e8).toFixed(1)}{L('亿','B')}
        </div>
        <div style={{fontSize:9, color:C.mid, marginTop:4}}>
          5D: {((data['5d_cumulative'] || 0) / 1e8).toFixed(1)}{L('亿','B')} |
          20D: {((data['20d_cumulative'] || 0) / 1e8).toFixed(1)}{L('亿','B')}
        </div>
        <div style={{fontSize:8, color:C.mid}}>{data.updated || ''}</div>
      </div>
    );
  };

  return (
    <div>
      {/* Flow Cards */}
      <div style={{display:'flex', gap:12, flexWrap:'wrap', marginBottom:16}}>
        <FlowCard title={L('Northbound (北向)','北向资金')} data={nb} icon="↑"/>
        <FlowCard title={L('Southbound (南向)','南向资金')} data={sb} icon="↓"/>
      </div>

      {/* Dragon & Tiger Board */}
      {dt.length > 0 && (
        <div style={{marginBottom:14}}>
          <div style={{fontSize:11, fontWeight:700, color:C.dark, marginBottom:8}}>
            🐉 {L('Dragon & Tiger Board (龙虎榜)','龙虎榜')}
            <span style={{fontSize:9, color:C.mid, marginLeft:6}}>{L('Last 5 trading days','最近5个交易日')}</span>
          </div>
          <div style={{overflowX:'auto', borderRadius:6, border:`1px solid ${C.border}`}}>
            <table style={{width:'100%', fontSize:10, borderCollapse:'collapse'}}>
              <thead><tr style={{background:C.soft}}>
                <th style={{textAlign:'left', padding:'6px 10px', color:C.mid, borderBottom:`1px solid ${C.border}`}}>{L('Stock','股票')}</th>
                <th style={{textAlign:'left', padding:'6px 10px', color:C.mid, borderBottom:`1px solid ${C.border}`}}>{L('Date','日期')}</th>
                <th style={{textAlign:'left', padding:'6px 10px', color:C.mid, borderBottom:`1px solid ${C.border}`}}>{L('Reason','原因')}</th>
                <th style={{textAlign:'right', padding:'6px 10px', color:C.mid, borderBottom:`1px solid ${C.border}`}}>{L('Net Amt','净额')}</th>
              </tr></thead>
              <tbody>
                {dt.slice(0, 10).map((e, i) => {
                  const net = e.net_amt || 0;
                  return (
                    <tr key={i} style={{borderBottom:`1px solid ${C.border}`, background: e.focus ? `${C.blue}05` : 'transparent'}}>
                      <td style={{padding:'6px 10px', fontWeight: e.focus ? 700 : 400, color:C.dark}}>
                        {e.name} {e.focus && <span style={{...S.tag(C.blue), fontSize:7, marginLeft:3}}>VP</span>}
                      </td>
                      <td style={{padding:'6px 10px', color:C.mid, fontFamily:'monospace'}}>{e.date}</td>
                      <td style={{padding:'6px 10px', color:C.mid, maxWidth:120, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{e.reason}</td>
                      <td style={{padding:'6px 10px', textAlign:'right', fontFamily:'monospace', fontWeight:700, color: net >= 0 ? C.green : C.red}}>
                        {(net/1e8).toFixed(2)}{L('亿','B')}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Margin Financing */}
      {Object.keys(margin).length > 0 && (
        <div>
          <div style={{fontSize:11, fontWeight:700, color:C.dark, marginBottom:8}}>
            {L('Margin Financing (融资融券)','融资融券')}
          </div>
          <div style={{display:'flex', gap:10, flexWrap:'wrap'}}>
            {Object.entries(margin).map(([tk, m]) => (
              <div key={tk} style={{padding:10, background:C.soft, borderRadius:6, border:`1px solid ${C.border}`, minWidth:140}}>
                <div style={{fontSize:10, fontWeight:700, color:C.dark, marginBottom:4}}>{tk}</div>
                <div style={{fontSize:9, color:C.mid}}>{L('Balance','余额')}: <span style={{color:C.gold, fontWeight:600}}>{m.balance_buy ? (m.balance_buy/1e8).toFixed(1)+'亿' : '—'}</span></div>
                <div style={{fontSize:9, color:C.mid}}>{L('Today Buy','今日买入')}: <span style={{color:C.green, fontWeight:600}}>{m.buy_today ? (m.buy_today/1e8).toFixed(2)+'亿' : '—'}</span></div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 20-day flow history bar chart */}
      {hist.length > 0 && (
        <div style={{marginBottom:14}}>
          <div style={{fontSize:11, fontWeight:700, color:C.dark, marginBottom:8}}>
            {L('20-Day Flow History (亿 CNY)','20日资金流向(亿元)')}
            {dataSource && <span style={{fontSize:9, color:C.mid, marginLeft:6, fontWeight:400}}>{dataSource}</span>}
          </div>
          <div style={{height:90}}>
            <ResponsiveContainer width='100%' height='100%'>
              <BarChart data={[...hist].reverse()} barGap={1}>
                <XAxis dataKey='date' tick={{fontSize:7}} tickFormatter={d=>d.slice(5)} interval='preserveStartEnd'/>
                <YAxis tick={{fontSize:7}} width={28} tickFormatter={v=>`${v}亿`}/>
                <Tooltip
                  contentStyle={{background:C.card, border:`1px solid ${C.border}`, borderRadius:6, fontSize:9}}
                  formatter={(v,n)=>[`${v}亿`, n==='north_net'?'北向':'南向']}
                  labelFormatter={l=>l}
                />
                <ReferenceLine y={0} stroke={C.border}/>
                <Bar dataKey='north_net' name='north_net' radius={[2,2,0,0]}
                  fill={C.blue} opacity={0.85}
                  // color each bar based on sign
                  label={false}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Error / loading state */}
      {apiLoading && !apiData && (
        <div style={{padding:'12px 16px', background:C.soft, borderRadius:8, fontSize:11, color:C.mid}}>
          {L('Fetching live flow data…','正在获取实时资金流向…')}
        </div>
      )}

      {(!nb.latest_net_flow && !sb.latest_net_flow && dt.length === 0 && !apiLoading) && (
        <div style={{padding:'16px 20px', background:`${C.gold}08`, border:`1px solid ${C.gold}25`, borderRadius:8, fontSize:11, color:C.mid, lineHeight:1.7}}>
          <div style={{...S.row, gap:6, marginBottom:6}}>
            <WifiOff size={13} style={{color:C.gold, flexShrink:0}}/>
            <span style={{fontWeight:700, color:C.gold}}>{L('Flow data unavailable','资金流向数据暂不可用')}</span>
          </div>
          <div>{L(
            'Capital flow API attempted but Eastmoney HSGT endpoints may be geo-restricted from Vercel. No local flow_data.json found either.',
            '已尝试调用东方财富 HSGT API，但该接口可能对 Vercel 节点也有地域限制。本地 flow_data.json 也未找到。'
          )}</div>
          <div style={{marginTop:6, color:C.blue, fontSize:10}}>
            {L(
              'Fix: run  python scripts/fetch_data.py  locally and push the generated flow_data.json.',
              '解决方案：本地运行 python scripts/fetch_data.py，将生成的 flow_data.json 推送至 GitHub。'
            )}
          </div>
        </div>
      )}
    </div>
  );
};

/* ── EARNINGS CALENDAR ───────────────────────────────────────────────── */
const EarningsCalendar = ({ L, lk, C }) => {
  const [calData, setCalData] = useState(null);
  useEffect(() => {
    const base = DATA_BASE;
    fetch(base + 'data/earnings_calendar.json')
      .then(r => { if (!r.ok) throw new Error(); return r.json(); })
      .then(d => setCalData(d))
      .catch(() => setCalData(null));
  }, []);

  if (!calData) return (
    <div style={{padding:16, textAlign:'center', color:C.mid, fontSize:11}}>
      <Calendar size={14} style={{marginBottom:4}}/><br/>
      {L('No earnings calendar data. Run python3 scripts/fetch_data.py.',
         '暂无财报日历。运行 python3 scripts/fetch_data.py。')}
    </div>
  );

  const entries = calData.entries || [];
  const focus   = entries.filter(e => e.focus);
  const all     = entries.slice(0, 20);

  const typeColor = (t) => {
    if (['预增','续盈','扭亏'].includes(t)) return C.green;
    if (['预减','续亏','首亏'].includes(t)) return C.red;
    return C.gold;
  };

  const renderTable = (rows, title) => rows.length === 0 ? null : (
    <div style={{marginBottom:14}}>
      <div style={{fontSize:11, fontWeight:700, color:C.dark, marginBottom:8}}>{title}</div>
      <div style={{overflowX:'auto', borderRadius:6, border:`1px solid ${C.border}`}}>
        <table style={{width:'100%', fontSize:10, borderCollapse:'collapse'}}>
          <thead><tr style={{background:C.soft}}>
            <th style={{textAlign:'left', padding:'6px 8px', color:C.mid, borderBottom:`1px solid ${C.border}`}}>{L('Stock','股票')}</th>
            <th style={{textAlign:'left', padding:'6px 8px', color:C.mid, borderBottom:`1px solid ${C.border}`}}>{L('Period','报告期')}</th>
            <th style={{textAlign:'left', padding:'6px 8px', color:C.mid, borderBottom:`1px solid ${C.border}`}}>{L('Type','类型')}</th>
            <th style={{textAlign:'right', padding:'6px 8px', color:C.mid, borderBottom:`1px solid ${C.border}`}}>{L('Profit Chg Range','利润变动区间')}</th>
          </tr></thead>
          <tbody>
            {rows.map((e, i) => (
              <tr key={i} style={{borderBottom:`1px solid ${C.border}`}}>
                <td style={{padding:'6px 8px', fontWeight:700, color:C.dark}}>{e.name} <span style={{fontSize:8, color:C.mid}}>{e.ticker}</span></td>
                <td style={{padding:'6px 8px', color:C.mid}}>{e.period}</td>
                <td style={{padding:'6px 8px'}}><span style={{...S.tag(typeColor(e.type)), fontSize:9}}>{e.type}</span></td>
                <td style={{padding:'6px 8px', textAlign:'right', fontFamily:'monospace', color:typeColor(e.type), fontWeight:700}}>
                  {e.change_low != null ? `${e.change_low > 0 ? '+' : ''}${e.change_low?.toFixed(0)}%` : '—'}
                  {' ~ '}
                  {e.change_high != null ? `${e.change_high > 0 ? '+' : ''}${e.change_high?.toFixed(0)}%` : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );

  return (
    <div>
      {renderTable(focus, '🎯 ' + L('Focus Position Earnings','持仓股业绩预告'))}
      {renderTable(all.filter(e => !e.focus), L('Market Earnings Pre-Announcements','全市场业绩预告（最新20条）'))}
      {entries.length === 0 && (
        <div style={{padding:16, textAlign:'center', color:C.mid, fontSize:11}}>
          {L('No announcements found.','暂无业绩预告。')}
        </div>
      )}
      <div style={{fontSize:8, color:C.mid, marginTop:6}}>
        {L('Source: AKShare / EastMoney 业绩预告 (stock_yjyg_em). Updates daily via GitHub Actions.',
           '数据来源：AKShare / 东方财富业绩预告。每日通过GitHub Actions自动更新。')}
      </div>
    </div>
  );
};

/* ── PAPER TRADING TAB ───────────────────────────────────────────────── */
function PaperTrading({ L, lk, C }) {
  const [positions, setPositions] = useState(null);
  const [analytics, setAnalytics] = useState(null);
  const [snapshots, setSnapshots] = useState([]);
  const [showAddTrade, setShowAddTrade] = useState(false);
  const [newTrade, setNewTrade] = useState({ ticker:'', name:'', market:'SZ', side:'BUY', quantity:'', price:'', sector_sw:'', notes:'' });

  useEffect(() => {
    const base = DATA_BASE;
    fetch(base + 'data/positions.json').then(r=>r.ok?r.json():null).then(d=>setPositions(d)).catch(()=>{});
    fetch(base + 'data/analytics.json').then(r=>r.ok?r.json():null).then(d=>setAnalytics(d)).catch(()=>{});
    fetch(base + 'data/snapshots.json').then(r=>r.ok?r.json():null).then(d=>setSnapshots(d?.snapshots||[])).catch(()=>{});
  }, []);

  const pos = positions?.positions || [];
  const summary = positions?.summary || {};
  const pnl = summary.total_pnl || 0;
  const pnlPct = summary.total_pnl_pct || 0;
  const pnlColor = pnl >= 0 ? C.green : C.red;

  const handleAddTrade = async () => {
    // Fetch latest confluence data for signal attribution
    let signalAttribution = null;
    try {
      const confResp = await fetch(DATA_BASE + 'data/confluence.json');
      if (confResp.ok) {
        const confData = await confResp.json();
        const confEntry = (confData.scores || []).find(s => s.ticker === newTrade.ticker);
        if (confEntry) {
          signalAttribution = {
            confluence_score:      confEntry.score,
            action:                confEntry.action,
            contributing_signals:  (confEntry.contributing_signals || []).slice(0, 6),
            captured_at:           new Date().toISOString(),
          };
        }
      }
    } catch (e) { /* attribution is best-effort, don't block trade */ }

    // Also try to capture VP score and wrongIf from vp_snapshot
    let vpAtEntry = null, wrongIfAtEntry = null;
    try {
      const vpResp = await fetch(DATA_BASE + 'data/vp_snapshot.json');
      if (vpResp.ok) {
        const vpData = await vpResp.json();
        const vpEntry = (vpData.snapshots || []).find(s => s.ticker === newTrade.ticker);
        if (vpEntry) {
          vpAtEntry      = vpEntry.vp_score;
          wrongIfAtEntry = vpEntry.wrongIf_e || null;
        }
      }
    } catch (e) {}

    // Also check localStorage for most recent DeepResearch VP
    try {
      const lsRaw = localStorage.getItem(`ar_research_${newTrade.ticker}`);
      if (lsRaw) {
        const lsData = JSON.parse(lsRaw);
        if (lsData?.current?.vp != null) vpAtEntry = lsData.current.vp;
        if (lsData?.current?.wrongIf) wrongIfAtEntry = lsData.current.wrongIf;
      }
    } catch (e) {}

    // Save new trade to localStorage for manual sync
    const trades = JSON.parse(localStorage.getItem('ar_pending_trades') || '[]');
    const tradeRecord = {
      ...newTrade,
      id:       't' + Date.now(),
      date:     new Date().toISOString().slice(0, 10),
      quantity: +newTrade.quantity,
      price:    +newTrade.price,
      // Signal attribution — closed-loop record of what triggered this entry
      signal_attribution: signalAttribution,
      vp_at_entry:        vpAtEntry,
      wrongIf_at_entry:   wrongIfAtEntry,
    };
    trades.push(tradeRecord);
    localStorage.setItem('ar_pending_trades', JSON.stringify(trades));
    setShowAddTrade(false);
    setNewTrade({ ticker:'', name:'', market:'SZ', side:'BUY', quantity:'', price:'', sector_sw:'', notes:'' });

    const attrNote = signalAttribution
      ? `\n\n📊 Signal Attribution captured:\n  Score: ${signalAttribution.confluence_score}\n  Signals: ${(signalAttribution.contributing_signals || []).map(s=>s.name||s).join(', ')}`
      : '';
    alert(L(
      `Trade saved locally.${attrNote}\n\nTo persist: copy trades from localStorage to public/data/trades.json and re-run python3 scripts/paper_trading.py`,
      `交易已保存到本地存储。${attrNote ? '\n\n信号归因已记录' : ''}\n\n要持久化：将交易复制到 public/data/trades.json 并重新运行 python3 scripts/paper_trading.py`
    ));
  };

  return (
    <div>
      {/* Portfolio Header */}
      <div style={{display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(140px, 1fr))', gap:12, marginBottom:16}}>
        <div style={{padding:14, background:C.card, border:`1px solid ${C.border}`, borderRadius:8}}>
          <div style={{fontSize:10, color:C.mid}}>{L('Portfolio Value','投资组合市值')}</div>
          <div style={{fontSize:20, fontWeight:800, fontFamily:'monospace', color:C.dark}}>{(summary.total_value||0).toLocaleString(undefined,{maximumFractionDigits:0})}</div>
        </div>
        <div style={{padding:14, background:`${pnlColor}08`, border:`1px solid ${pnlColor}25`, borderRadius:8}}>
          <div style={{fontSize:10, color:C.mid}}>{L('Total P&L','总浮盈亏')}</div>
          <div style={{fontSize:20, fontWeight:800, fontFamily:'monospace', color:pnlColor}}>
            {pnl >= 0 ? '+' : ''}{pnl.toLocaleString(undefined,{maximumFractionDigits:0})}
          </div>
          <div style={{fontSize:11, color:pnlColor, fontWeight:700}}>{pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(2)}%</div>
        </div>
        <div style={{padding:14, background:C.card, border:`1px solid ${C.border}`, borderRadius:8}}>
          <div style={{fontSize:10, color:C.mid}}>{L('Hit Rate','胜率')}</div>
          <div style={{fontSize:20, fontWeight:800, fontFamily:'monospace', color:C.blue}}>{analytics?.hit_rate_pct || 0}%</div>
        </div>
        <div style={{padding:14, background:C.card, border:`1px solid ${C.border}`, borderRadius:8}}>
          <div style={{fontSize:10, color:C.mid}}>{L('Positions','持仓数')}</div>
          <div style={{fontSize:20, fontWeight:800, fontFamily:'monospace', color:C.dark}}>{pos.length}</div>
        </div>
      </div>

      {/* Positions Table */}
      {pos.length > 0 ? (
        <div style={{marginBottom:16}}>
          <div style={{...S.row, justifyContent:'space-between', marginBottom:8}}>
            <div style={{fontSize:12, fontWeight:700, color:C.dark}}>{L('Open Positions','持仓明细')}</div>
            <button onClick={()=>setShowAddTrade(!showAddTrade)} style={{padding:'5px 12px', background:C.blue, color:'#fff', border:'none', borderRadius:5, cursor:'pointer', fontSize:10, fontWeight:700}}>
              + {L('Add Trade','录入交易')}
            </button>
          </div>
          <div style={{overflowX:'auto', borderRadius:6, border:`1px solid ${C.border}`}}>
            <table style={{width:'100%', fontSize:10, borderCollapse:'collapse'}}>
              <thead><tr style={{background:C.soft}}>
                {[L('Ticker','代码'), L('Name','名称'), L('Qty','数量'), L('Avg Cost','成本'), L('Price','现价'), 'P&L', 'P&L%', L('Weight','权重'), L('Days','持有天')].map((h,i) => (
                  <th key={i} style={{padding:'7px 8px', textAlign: i > 1 ? 'right' : 'left', color:C.mid, fontWeight:600, borderBottom:`1px solid ${C.border}`}}>{h}</th>
                ))}
              </tr></thead>
              <tbody>
                {pos.map((p, i) => {
                  const pc = p.pnl_pct >= 0 ? C.green : C.red;
                  return (
                    <tr key={i} style={{borderBottom:`1px solid ${C.border}`}}>
                      <td style={{padding:'7px 8px', fontFamily:'monospace', fontWeight:700, color:C.dark}}>{p.ticker}</td>
                      <td style={{padding:'7px 8px', color:C.dark}}>{p.name}</td>
                      <td style={{padding:'7px 8px', textAlign:'right', fontFamily:'monospace', color:C.mid}}>{p.quantity.toLocaleString()}</td>
                      <td style={{padding:'7px 8px', textAlign:'right', fontFamily:'monospace', color:C.mid}}>{p.avg_cost?.toFixed(2)}</td>
                      <td style={{padding:'7px 8px', textAlign:'right', fontFamily:'monospace', fontWeight:700, color:C.dark}}>{p.current_price?.toFixed(2)}</td>
                      <td style={{padding:'7px 8px', textAlign:'right', fontFamily:'monospace', fontWeight:700, color:pc}}>{p.pnl_abs >= 0 ? '+' : ''}{p.pnl_abs?.toLocaleString(undefined,{maximumFractionDigits:0})}</td>
                      <td style={{padding:'7px 8px', textAlign:'right', fontFamily:'monospace', fontWeight:700, color:pc}}>{p.pnl_pct >= 0 ? '+' : ''}{p.pnl_pct?.toFixed(2)}%</td>
                      <td style={{padding:'7px 8px', textAlign:'right', color:C.mid}}>{p.weight_pct?.toFixed(1)}%</td>
                      <td style={{padding:'7px 8px', textAlign:'right', color:C.mid}}>{p.holding_days}d</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <div style={{padding:20, textAlign:'center', color:C.mid, marginBottom:16}}>
          <div style={{fontSize:12, marginBottom:8}}>{L('No positions yet. Add your first trade.','暂无持仓。录入你的第一笔交易。')}</div>
          <button onClick={()=>setShowAddTrade(true)} style={{padding:'8px 20px', background:C.blue, color:'#fff', border:'none', borderRadius:6, cursor:'pointer', fontSize:12, fontWeight:700}}>
            + {L('Add First Trade','录入第一笔交易')}
          </button>
        </div>
      )}

      {/* Add Trade Form */}
      {showAddTrade && (
        <div style={{padding:16, background:C.card, border:`1px solid ${C.border}`, borderRadius:8, marginBottom:16}}>
          <div style={{fontSize:12, fontWeight:700, color:C.dark, marginBottom:12}}>+ {L('New Trade','新建交易')}</div>
          <div style={{display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(140px, 1fr))', gap:8}}>
            {[
              {key:'ticker', label:'Ticker', ph:'300308.SZ'},
              {key:'name', label:L('Name','名称'), ph:'中际旭创'},
              {key:'quantity', label:L('Qty','数量'), ph:'100'},
              {key:'price', label:L('Price','价格'), ph:'734.65'},
              {key:'sector_sw', label:L('Sector','行业'), ph:'电子'},
            ].map(({key, label, ph}) => (
              <div key={key}>
                <div style={{fontSize:9, color:C.mid, marginBottom:3}}>{label}</div>
                <input value={newTrade[key]} onChange={e=>setNewTrade(p=>({...p,[key]:e.target.value}))}
                  placeholder={ph} style={{width:'100%', padding:'6px 8px', border:`1px solid ${C.border}`, borderRadius:4, fontSize:11, background:C.soft, color:C.dark, outline:'none'}}/>
              </div>
            ))}
            <div>
              <div style={{fontSize:9, color:C.mid, marginBottom:3}}>{L('Side','方向')}</div>
              <div style={{display:'flex', gap:4}}>
                {['BUY','SELL'].map(s => (
                  <button key={s} onClick={()=>setNewTrade(p=>({...p,side:s}))} style={{flex:1, padding:'6px 0', border:`1px solid ${newTrade.side===s?(s==='BUY'?C.green:C.red):C.border}`, background:newTrade.side===s?`${s==='BUY'?C.green:C.red}15`:'transparent', color:newTrade.side===s?(s==='BUY'?C.green:C.red):C.mid, borderRadius:4, cursor:'pointer', fontSize:10, fontWeight:700}}>{s}</button>
                ))}
              </div>
            </div>
            <div>
              <div style={{fontSize:9, color:C.mid, marginBottom:3}}>Market</div>
              <div style={{display:'flex', gap:3}}>
                {['SZ','SH','HK'].map(m => (
                  <button key={m} onClick={()=>setNewTrade(p=>({...p,market:m}))} style={{flex:1, padding:'5px 0', border:`1px solid ${newTrade.market===m?C.blue:C.border}`, background:newTrade.market===m?`${C.blue}15`:'transparent', color:newTrade.market===m?C.blue:C.mid, borderRadius:4, cursor:'pointer', fontSize:9, fontWeight:700}}>{m}</button>
                ))}
              </div>
            </div>
          </div>
          <div style={{marginTop:8}}>
            <div style={{fontSize:9, color:C.mid, marginBottom:3}}>{L('Notes','备注')}</div>
            <input value={newTrade.notes} onChange={e=>setNewTrade(p=>({...p,notes:e.target.value}))}
              placeholder={L('VP thesis, catalyst rationale...','VP论点、催化剂理由...')}
              style={{width:'100%', padding:'6px 8px', border:`1px solid ${C.border}`, borderRadius:4, fontSize:11, background:C.soft, color:C.dark, outline:'none'}}/>
          </div>
          <div style={{...S.row, gap:8, marginTop:12}}>
            <button onClick={handleAddTrade} disabled={!newTrade.ticker||!newTrade.quantity||!newTrade.price} style={{padding:'7px 16px', background:C.green, color:'#fff', border:'none', borderRadius:5, cursor:'pointer', fontSize:11, fontWeight:700, opacity:(!newTrade.ticker||!newTrade.quantity||!newTrade.price)?0.5:1}}>
              {L('Save Trade','保存交易')}
            </button>
            <button onClick={()=>setShowAddTrade(false)} style={{padding:'7px 12px', background:'transparent', border:`1px solid ${C.border}`, color:C.mid, borderRadius:5, cursor:'pointer', fontSize:11}}>
              {L('Cancel','取消')}
            </button>
          </div>
        </div>
      )}

      {/* Sector allocation */}
      {analytics?.sector_weights && Object.keys(analytics.sector_weights).length > 0 && (
        <div style={{padding:14, background:C.card, border:`1px solid ${C.border}`, borderRadius:8, marginBottom:14}}>
          <div style={{fontSize:11, fontWeight:700, color:C.dark, marginBottom:10}}>{L('Sector Allocation','行业配置')}</div>
          <div style={{display:'flex', gap:8, flexWrap:'wrap'}}>
            {Object.entries(analytics.sector_weights).map(([s, w], i) => (
              <div key={i} style={{padding:'6px 10px', background:C.soft, borderRadius:4}}>
                <span style={{fontSize:10, color:C.dark, fontWeight:600}}>{s}</span>
                <span style={{fontSize:10, color:C.blue, fontWeight:700, marginLeft:6}}>{w?.toFixed(1)}%</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Instructions box */}
      <div style={{padding:12, background:`${C.gold}08`, border:`1px solid ${C.gold}25`, borderRadius:6, fontSize:10, color:C.mid, lineHeight:1.7}}>
        <div style={{fontWeight:700, color:C.dark, marginBottom:4}}>{L('How paper trading works:','虚拟盘说明：')}</div>
        <div>1. {L('Add trades via the form above (saved to localStorage).','通过上方表单录入交易（保存至本地存储）。')}</div>
        <div>2. {L('Copy localStorage trades to public/data/trades.json in your repo.','将本地存储交易复制到仓库中的 public/data/trades.json。')}</div>
        <div>3. {L('GitHub Actions computes P&L daily and updates positions.json.','GitHub Actions 每日计算浮盈亏并更新 positions.json。')}</div>
        <div>4. {L('Run python3 scripts/paper_trading.py locally for instant updates.','本地运行 python3 scripts/paper_trading.py 即时更新。')}</div>
      </div>
    </div>
  );
}

/* ── CANDLESTICK CHART (SVG K-line + Volume) ──────────────────────────── */
const CandlestickChart = ({ ticker, L, lk, C }) => {
  const [ohlc, setOhlc] = useState(null);
  const [loading, setLoading] = useState(true);
  const [hover, setHover] = useState(null);

  useEffect(() => {
    setLoading(true); setOhlc(null); setHover(null);
    const safeId = ticker.replace('.', '_');
    const base = DATA_BASE;
    fetch(base + `data/ohlc_${safeId}.json`)
      .then(r => { if (!r.ok) throw new Error(); return r.json(); })
      .then(d => { setOhlc(d.data || []); setLoading(false); })
      .catch(() => { setOhlc(null); setLoading(false); });
  }, [ticker]);

  if (loading) return <div style={{padding:20, textAlign:'center', color:C.mid, fontSize:11}}>Loading K-line data...</div>;
  if (!ohlc || ohlc.length === 0) return (
    <div style={{padding:16, textAlign:'center', color:C.mid, fontSize:11}}>
      <WifiOff size={14} style={{marginBottom:4}}/><br/>
      {L('No OHLC data. Run python3 scripts/fetch_data.py to generate candlestick data.',
         '暂无K线数据。运行 python3 scripts/fetch_data.py 以生成K线数据。')}
    </div>
  );

  const W = 700, H = 340, padL = 8, padR = 58, padT = 20, padB = 50;
  const chartW = W - padL - padR;
  const priceH = (H - padT - padB) * 0.72;
  const volH = (H - padT - padB) * 0.22;
  const volTop = padT + priceH + (H - padT - padB) * 0.06;

  const data = ohlc.slice(-60); // last 60 candles
  const n = data.length;
  const candleW = Math.max(2, (chartW / n) * 0.7);
  const gap = (chartW / n) * 0.3;

  // Compute 5MA and 20MA
  const ma = (period) => data.map((_, i) => {
    if (i < period - 1) return null;
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += data[j].close;
    return sum / period;
  });
  const ma5 = ma(5);
  const ma20 = ma(20);

  const prices = data.flatMap(d => [d.high, d.low]);
  const minP = Math.min(...prices);
  const maxP = Math.max(...prices);
  const pRange = maxP - minP || 1;
  const maxVol = Math.max(...data.map(d => d.volume)) || 1;

  const xOf = i => padL + (i + 0.5) * (chartW / n);
  const yOf = p => padT + priceH - ((p - minP) / pRange) * priceH;
  const vOf = v => volTop + volH - (v / maxVol) * volH;

  // Price grid lines
  const gridLines = 5;
  const gridPrices = Array.from({length: gridLines}, (_, i) => minP + (pRange / (gridLines - 1)) * i);

  // MA line path builder
  const maPath = (vals) => {
    const pts = vals.map((v, i) => v != null ? `${xOf(i)},${yOf(v)}` : null).filter(Boolean);
    return pts.length > 1 ? 'M' + pts.join('L') : '';
  };

  const hd = hover != null ? data[hover] : null;

  return (
    <div style={{position:'relative'}}>
      {/* Hover tooltip */}
      {hd && (
        <div style={{position:'absolute', top:0, right:0, padding:'6px 10px', background:C.card, border:`1px solid ${C.border}`, borderRadius:6, fontSize:10, zIndex:5, fontFamily:'monospace', lineHeight:1.6}}>
          <div style={{fontWeight:700, color:C.dark, marginBottom:2}}>{hd.date}</div>
          <div>O: <span style={{color:C.dark, fontWeight:600}}>{hd.open.toFixed(2)}</span></div>
          <div>H: <span style={{color:C.green, fontWeight:600}}>{hd.high.toFixed(2)}</span></div>
          <div>L: <span style={{color:C.red, fontWeight:600}}>{hd.low.toFixed(2)}</span></div>
          <div>C: <span style={{color:hd.close >= hd.open ? C.green : C.red, fontWeight:600}}>{hd.close.toFixed(2)}</span></div>
          <div>Vol: <span style={{color:C.mid}}>{(hd.volume/1e6).toFixed(1)}M</span></div>
        </div>
      )}
      <svg width={W} height={H} style={{display:'block', maxWidth:'100%'}}
        onMouseLeave={()=>setHover(null)}>
        {/* Price grid */}
        {gridPrices.map((p, i) => (
          <g key={i}>
            <line x1={padL} y1={yOf(p)} x2={W-padR} y2={yOf(p)} stroke={C.border} strokeDasharray="3,3" strokeWidth={0.5}/>
            <text x={W-padR+4} y={yOf(p)+3} fontSize={9} fill={C.mid} fontFamily="monospace">{p.toFixed(1)}</text>
          </g>
        ))}

        {/* Volume bars */}
        {data.map((d, i) => {
          const up = d.close >= d.open;
          return (
            <rect key={'v'+i} x={xOf(i) - candleW/2} y={vOf(d.volume)} width={candleW}
              height={volTop + volH - vOf(d.volume)}
              fill={up ? C.green : C.red} opacity={hover === i ? 0.6 : 0.25}/>
          );
        })}

        {/* MA lines */}
        <path d={maPath(ma5)} fill="none" stroke={C.gold} strokeWidth={1.2} opacity={0.8}/>
        <path d={maPath(ma20)} fill="none" stroke={C.blue} strokeWidth={1.2} opacity={0.8}/>

        {/* Candlesticks */}
        {data.map((d, i) => {
          const up = d.close >= d.open;
          const color = up ? C.green : C.red;
          const bodyTop = yOf(Math.max(d.open, d.close));
          const bodyBot = yOf(Math.min(d.open, d.close));
          const bodyH = Math.max(1, bodyBot - bodyTop);
          return (
            <g key={i} onMouseEnter={()=>setHover(i)} style={{cursor:'crosshair'}}>
              {/* Hit area */}
              <rect x={xOf(i) - chartW/n/2} y={padT} width={chartW/n} height={priceH + volH + 20} fill="transparent"/>
              {/* Wick */}
              <line x1={xOf(i)} y1={yOf(d.high)} x2={xOf(i)} y2={yOf(d.low)} stroke={color} strokeWidth={1}/>
              {/* Body */}
              <rect x={xOf(i) - candleW/2} y={bodyTop} width={candleW} height={bodyH}
                fill={up ? 'transparent' : color} stroke={color} strokeWidth={1} rx={0.5}/>
            </g>
          );
        })}

        {/* Date labels */}
        {data.filter((_, i) => i % Math.max(1, Math.floor(n/6)) === 0).map((d, i, arr) => {
          const idx = data.indexOf(d);
          return (
            <text key={i} x={xOf(idx)} y={H - 8} textAnchor="middle" fontSize={8} fill={C.mid} fontFamily="monospace">
              {d.date.slice(5)}
            </text>
          );
        })}

        {/* MA legend */}
        <line x1={padL} y1={H-22} x2={padL+16} y2={H-22} stroke={C.gold} strokeWidth={1.5}/>
        <text x={padL+20} y={H-19} fontSize={8} fill={C.gold}>MA5</text>
        <line x1={padL+50} y1={H-22} x2={padL+66} y2={H-22} stroke={C.blue} strokeWidth={1.5}/>
        <text x={padL+70} y={H-19} fontSize={8} fill={C.blue}>MA20</text>

        {/* Hover crosshair */}
        {hover != null && (
          <line x1={xOf(hover)} y1={padT} x2={xOf(hover)} y2={volTop+volH} stroke={C.mid} strokeWidth={0.5} strokeDasharray="2,2"/>
        )}
      </svg>
    </div>
  );
};

/* ── FINANCIAL STATEMENTS (BS/IS/CF tabbed view) ─────────────────────── */
const FinancialStatements = ({ ticker, L, lk, C }) => {
  const [fin, setFin] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('income_statement');

  useEffect(() => {
    setLoading(true); setFin(null);
    const safeId = ticker.replace('.', '_');
    const base = DATA_BASE;
    fetch(base + `data/fin_${safeId}.json`)
      .then(r => { if (!r.ok) throw new Error(); return r.json(); })
      .then(d => { setFin(d); setLoading(false); })
      .catch(() => { setFin(null); setLoading(false); });
  }, [ticker]);

  if (loading) return <div style={{padding:20, textAlign:'center', color:C.mid, fontSize:11}}>Loading financial data...</div>;
  if (!fin) return (
    <div style={{padding:16, textAlign:'center', color:C.mid, fontSize:11}}>
      <Database size={14} style={{marginBottom:4}}/><br/>
      {L('No financial statement data. Run python3 scripts/fetch_data.py to generate.',
         '暂无财报数据。运行 python3 scripts/fetch_data.py 以生成。')}
    </div>
  );

  const tabs = [
    { id: 'income_statement', label: L('Income Statement', '利润表'), icon: '📊' },
    { id: 'balance_sheet', label: L('Balance Sheet', '资产负债表'), icon: '📋' },
    { id: 'cash_flow', label: L('Cash Flow', '现金流量表'), icon: '💰' },
  ];

  const stmtData = fin[activeTab];
  if (!stmtData || Object.keys(stmtData).length === 0) return (
    <div>
      <div style={{display:'flex', gap:4, marginBottom:12}}>
        {tabs.map(t => (
          <button key={t.id} onClick={() => setActiveTab(t.id)} style={{
            padding:'6px 12px', border:`1px solid ${activeTab===t.id ? C.blue : C.border}`,
            background: activeTab===t.id ? `${C.blue}15` : 'transparent',
            color: activeTab===t.id ? C.blue : C.mid, borderRadius:5, cursor:'pointer',
            fontSize:10, fontWeight:600, transition:'all .15s',
          }}>{t.label}</button>
        ))}
      </div>
      <div style={{padding:16, textAlign:'center', color:C.mid, fontSize:11}}>
        {L('No data for this statement','该报表暂无数据')}
      </div>
    </div>
  );

  // periods sorted chronologically (most recent first)
  const periods = Object.keys(stmtData).sort((a,b) => new Date(b) - new Date(a)).slice(0, 4);
  // All line items across all periods
  const allItems = new Set();
  periods.forEach(p => Object.keys(stmtData[p]).forEach(k => allItems.add(k)));

  // Key items to highlight per statement type
  const keyItems = {
    income_statement: ['Total Revenue', 'Gross Profit', 'Operating Income', 'Net Income', 'EBITDA', 'Basic EPS', 'Diluted EPS'],
    balance_sheet: ['Total Assets', 'Total Liabilities Net Minority Interest', 'Stockholders Equity', 'Total Debt', 'Cash And Cash Equivalents', 'Net Tangible Assets'],
    cash_flow: ['Operating Cash Flow', 'Capital Expenditure', 'Free Cash Flow', 'Investing Cash Flow', 'Financing Cash Flow'],
  };
  const highlights = new Set(keyItems[activeTab] || []);

  // Format number
  const fmtNum = v => {
    if (v == null || isNaN(v)) return '—';
    const abs = Math.abs(v);
    const sign = v < 0 ? '-' : '';
    if (abs >= 1e12) return sign + (abs/1e12).toFixed(2) + 'T';
    if (abs >= 1e9) return sign + (abs/1e9).toFixed(2) + 'B';
    if (abs >= 1e6) return sign + (abs/1e6).toFixed(1) + 'M';
    if (abs >= 1e3) return sign + (abs/1e3).toFixed(1) + 'K';
    return sign + abs.toFixed(0);
  };

  // Sort items: key items first, then rest alphabetically
  const sortedItems = [...allItems].sort((a, b) => {
    const aKey = highlights.has(a);
    const bKey = highlights.has(b);
    if (aKey && !bKey) return -1;
    if (!aKey && bKey) return 1;
    return a.localeCompare(b);
  });

  return (
    <div>
      {/* Tab selector */}
      <div style={{display:'flex', gap:4, marginBottom:12}}>
        {tabs.map(t => (
          <button key={t.id} onClick={() => setActiveTab(t.id)} style={{
            padding:'6px 12px', border:`1px solid ${activeTab===t.id ? C.blue : C.border}`,
            background: activeTab===t.id ? `${C.blue}15` : 'transparent',
            color: activeTab===t.id ? C.blue : C.mid, borderRadius:5, cursor:'pointer',
            fontSize:10, fontWeight:600, transition:'all .15s',
          }}>{t.label}</button>
        ))}
      </div>

      {/* Statement table */}
      <div style={{overflowX:'auto', borderRadius:6, border:`1px solid ${C.border}`}}>
        <table style={{width:'100%', fontSize:10, borderCollapse:'collapse', minWidth:400}}>
          <thead>
            <tr style={{background:C.soft}}>
              <th style={{textAlign:'left', padding:'8px 10px', fontWeight:700, color:C.dark, borderBottom:`1px solid ${C.border}`, position:'sticky', left:0, background:C.soft, minWidth:180}}>
                {L('Line Item','项目')}
              </th>
              {periods.map(p => (
                <th key={p} style={{textAlign:'right', padding:'8px 10px', fontWeight:700, color:C.dark, borderBottom:`1px solid ${C.border}`, minWidth:90}}>
                  {p.slice(0, 7)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sortedItems.map((item, i) => {
              const isKey = highlights.has(item);
              return (
                <tr key={i} style={{borderBottom:`1px solid ${C.border}`, background: isKey ? `${C.blue}05` : 'transparent'}}>
                  <td style={{padding:'6px 10px', fontWeight: isKey ? 700 : 400, color: isKey ? C.dark : C.mid, position:'sticky', left:0, background: isKey ? `${C.blue}08` : C.card, fontSize: isKey ? 10 : 9}}>
                    {item.replace(/([A-Z])/g, ' $1').trim()}
                  </td>
                  {periods.map(p => {
                    const val = stmtData[p]?.[item];
                    return (
                      <td key={p} style={{textAlign:'right', padding:'6px 10px', fontFamily:'monospace', fontWeight: isKey ? 700 : 400, color: val != null && val < 0 ? C.red : (isKey ? C.dark : C.mid)}}>
                        {fmtNum(val)}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div style={{fontSize:8, color:C.mid, marginTop:6, textAlign:'right'}}>
        {L('Source: Yahoo Finance. Figures in reporting currency. Key rows highlighted.',
           '数据来源：Yahoo Finance。金额以报告货币计。关键行已高亮。')}
      </div>
    </div>
  );
};

/* ── COMPANY INFO PANEL ──────────────────────────────────────────────── */
const CompanyInfoPanel = ({ ticker, liveData, L, lk, C }) => {
  const yd = liveData?.yahoo?.[ticker];
  if (!yd?.meta) return null;
  const m = yd.meta;
  const f = yd.fundamentals || {};

  const fmtBig = v => { if (!v) return '—'; if (v >= 1e12) return (v/1e12).toFixed(2)+'T'; if (v >= 1e9) return (v/1e9).toFixed(2)+'B'; if (v >= 1e6) return (v/1e6).toFixed(1)+'M'; return v.toLocaleString(); };

  const items = [
    { label: L('Sector','行业'), val: m.sector || '—' },
    { label: L('Industry','细分行业'), val: m.industry || '—' },
    { label: L('Market Cap','总市值'), val: fmtBig(f.market_cap) },
    { label: L('Enterprise Value','企业价值'), val: fmtBig(f.enterprise_value) },
    { label: L('Total Cash','总现金'), val: fmtBig(f.total_cash) },
    { label: L('Total Debt','总债务'), val: fmtBig(f.total_debt) },
    { label: L('Book Value/Share','每股净资产'), val: f.book_value != null ? f.book_value.toFixed(2) : '—' },
    { label: 'EBITDA', val: fmtBig(f.ebitda) },
    { label: L('Dividend Yield','股息率'), val: f.dividend_yield != null ? (f.dividend_yield).toFixed(2) + '%' : '—' },
    { label: 'D/E', val: f.debt_to_equity != null ? f.debt_to_equity.toFixed(1) : '—' },
    { label: 'P/S', val: f.ps_ratio != null ? f.ps_ratio.toFixed(2) : '—' },
    { label: 'EV/Revenue', val: f.ev_revenue != null ? f.ev_revenue.toFixed(2) : '—' },
    { label: 'ROA', val: f.roa != null ? (f.roa * 100).toFixed(1) + '%' : '—' },
    { label: L('Current Ratio','流动比率'), val: f.current_ratio != null ? f.current_ratio.toFixed(2) : '—' },
    { label: L('Quick Ratio','速动比率'), val: f.quick_ratio != null ? f.quick_ratio.toFixed(2) : '—' },
    { label: L('Earnings Growth','盈利增速'), val: f.earnings_growth != null ? (f.earnings_growth * 100).toFixed(1) + '%' : '—' },
  ];

  return (
    <div>
      {/* Company description */}
      {m.description && (
        <div style={{fontSize:10, color:C.mid, lineHeight:1.6, marginBottom:12, padding:10, background:C.soft, borderRadius:6}}>
          {m.description}
        </div>
      )}

      {/* Key data grid */}
      <div style={{display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(130px, 1fr))', gap:8}}>
        {items.filter(it => it.val !== '—').map((it, i) => (
          <div key={i} style={{padding:'6px 8px', background:C.soft, borderRadius:4}}>
            <div style={{fontSize:8, color:C.mid, marginBottom:2}}>{it.label}</div>
            <div style={{fontSize:11, fontWeight:700, fontFamily:'monospace', color:C.dark}}>{it.val}</div>
          </div>
        ))}
      </div>

      {/* External links */}
      <div style={{marginTop:10, display:'flex', gap:8, flexWrap:'wrap'}}>
        {m.website && (
          <a href={m.website} target="_blank" rel="noopener noreferrer" style={{fontSize:9, color:C.blue, textDecoration:'none', padding:'3px 8px', background:`${C.blue}10`, borderRadius:4}}>
            {L('Company Website','公司官网')} ↗
          </a>
        )}
        <a href={`https://finance.yahoo.com/quote/${ticker.replace('.HK', '.HK').replace('.SZ', '.SZ')}`} target="_blank" rel="noopener noreferrer" style={{fontSize:9, color:C.blue, textDecoration:'none', padding:'3px 8px', background:`${C.blue}10`, borderRadius:4}}>
          Yahoo Finance ↗
        </a>
        {(m.exchange === 'SZ' || m.exchange === 'SH') && (
          <a href={`https://www.eastmoney.com/`} target="_blank" rel="noopener noreferrer" style={{fontSize:9, color:C.blue, textDecoration:'none', padding:'3px 8px', background:`${C.blue}10`, borderRadius:4}}>
            {L('EastMoney','东方财富')} ↗
          </a>
        )}
        {m.exchange === 'HK' && (
          <a href={`https://www.hkex.com.hk/`} target="_blank" rel="noopener noreferrer" style={{fontSize:9, color:C.blue, textDecoration:'none', padding:'3px 8px', background:`${C.blue}10`, borderRadius:4}}>
            HKEX ↗
          </a>
        )}
      </div>
    </div>
  );
};

/* ── UNIVERSE STOCK VIEW (non-focus stocks from full market data) ─────── */
const UniverseStockView = ({ ticker, universeStocks, liveData, L, lk, C, onDeepResearch }) => {
  const stock = universeStocks.find(s => s.ticker === ticker);
  if (!stock) return <div style={{color:C.mid, padding:20, textAlign:'center'}}>{L('Stock not found in universe data','未在全市场数据中找到该股票')}</div>;

  const curr = stock.exchange === 'HK' ? 'HK$' : '¥';
  const fmt = v => v != null ? (typeof v === 'number' ? v.toLocaleString(undefined, {maximumFractionDigits:2}) : v) : '—';
  const fmtBig = v => { if (!v) return '—'; if (v >= 1e12) return (v/1e12).toFixed(2)+'T'; if (v >= 1e8) return (v/1e8).toFixed(1)+L('B','亿'); return fmt(v); };
  const chgColor = stock.change_pct > 0 ? C.green : stock.change_pct < 0 ? C.red : C.mid;

  return (
    <div>
      {/* Live price chart — works for any A/HK stock */}
      <PriceChart ticker={stock.ticker} C={C} L={L} lk={lk}/>

      {/* Header Card */}
      <div style={{...S.card, borderColor:C.border}}>
        <div style={{padding:16}}>
          <div style={{display:'flex', justifyContent:'space-between', alignItems:'flex-start', marginBottom:12}}>
            <div>
              <div style={{fontSize:18, fontWeight:800, color:C.dark}}>{stock.ticker} · {stock.name}</div>
              <div style={{fontSize:11, color:C.mid}}>{stock.exchange === 'HK' ? L('Hong Kong Exchange','港交所') : L('A-Share · ','A股 · ') + (stock.exchange === 'SH' ? L('Shanghai','上交所') : L('Shenzhen','深交所'))}</div>
            </div>
            <button onClick={()=>onDeepResearch(stock.ticker)} style={{padding:'8px 14px', background:C.green, color:'#fff', border:'none', borderRadius:6, cursor:'pointer', fontSize:11, fontWeight:700, display:'flex', alignItems:'center', gap:4}}>
              <Zap size={12}/>{L('Deep Research','深度研究')}
            </button>
          </div>

          {/* Price Header */}
          <div style={{display:'flex', gap:16, flexWrap:'wrap', marginBottom:14}}>
            <div style={{flex:'1 1 160px', padding:14, background:`${C.blue}08`, borderRadius:8, border:`1px solid ${C.blue}20`}}>
              <div style={{fontSize:10, color:C.mid}}>{L('Last Price','最新价')}</div>
              <div style={{fontSize:26, fontWeight:800, color:chgColor, fontFamily:'monospace'}}>{curr}{fmt(stock.price)}</div>
              <div style={{fontSize:12, color:chgColor, fontWeight:600}}>
                {stock.change_pct > 0 ? '+' : ''}{fmt(stock.change_pct)}% {stock.change_amt != null && ('(' + (stock.change_amt > 0 ? '+' : '') + fmt(stock.change_amt) + ')')}
              </div>
            </div>
            <div style={{flex:'1 1 100px', padding:14, background:C.soft, borderRadius:8, border:`1px solid ${C.border}`}}>
              <div style={{fontSize:10, color:C.mid}}>{L('Volume Ratio','量比')}</div>
              <div style={{fontSize:20, fontWeight:800, fontFamily:'monospace', color:stock.volume_ratio > 1.5 ? C.gold : stock.volume_ratio > 1 ? C.green : C.mid}}>{fmt(stock.volume_ratio)}x</div>
            </div>
            <div style={{flex:'1 1 100px', padding:14, background:C.soft, borderRadius:8, border:`1px solid ${C.border}`}}>
              <div style={{fontSize:10, color:C.mid}}>{L('Turnover Rate','换手率')}</div>
              <div style={{fontSize:20, fontWeight:800, fontFamily:'monospace', color:C.dark}}>{fmt(stock.turnover_rate)}%</div>
            </div>
          </div>

          {/* Price Range */}
          <div style={{display:'flex', gap:12, flexWrap:'wrap', marginBottom:14}}>
            <div style={{flex:'1 1 200px', padding:12, background:C.soft, borderRadius:8, border:`1px solid ${C.border}`}}>
              <div style={{fontSize:10, color:C.mid, marginBottom:6}}>{L("Today's Range",'今日区间')}</div>
              <div style={{display:'flex', justifyContent:'space-between', fontSize:12, fontWeight:700, fontFamily:'monospace', color:C.dark}}>
                <span>{fmt(stock.low)}</span><span>—</span><span>{fmt(stock.high)}</span>
              </div>
              <div style={{marginTop:6, height:6, background:C.border, borderRadius:3, position:'relative'}}>
                {stock.low && stock.high && stock.price && (
                  <div style={{position:'absolute', left:`${Math.min(100,Math.max(0,(stock.price-stock.low)/(stock.high-stock.low)*100))}%`, top:-2, width:10, height:10, borderRadius:5, background:C.blue, transform:'translateX(-5px)'}}></div>
                )}
              </div>
            </div>
            {stock.high_52w && stock.low_52w && (
              <div style={{flex:'1 1 200px', padding:12, background:C.soft, borderRadius:8, border:`1px solid ${C.border}`}}>
                <div style={{fontSize:10, color:C.mid, marginBottom:6}}>{L('52W Range','52周区间')}</div>
                <div style={{display:'flex', justifyContent:'space-between', fontSize:12, fontWeight:700, fontFamily:'monospace', color:C.dark}}>
                  <span>{fmt(stock.low_52w)}</span><span>—</span><span>{fmt(stock.high_52w)}</span>
                </div>
                <div style={{marginTop:6, height:6, background:C.border, borderRadius:3, position:'relative'}}>
                  <div style={{position:'absolute', left:`${Math.min(100,Math.max(0,(stock.price-stock.low_52w)/(stock.high_52w-stock.low_52w)*100))}%`, top:-2, width:10, height:10, borderRadius:5, background:C.blue, transform:'translateX(-5px)'}}></div>
                </div>
              </div>
            )}
          </div>

          {/* Fundamentals Grid */}
          <div style={{display:'flex', gap:16, flexWrap:'wrap', marginBottom:14}}>
            {[
              {label:L('Market Cap','总市值'), val:fmtBig(stock.market_cap)},
              {label:'P/E', val:fmt(stock.pe)},
              {label:'P/B', val:fmt(stock.pb)},
              {label:'ROE', val:stock.roe != null ? fmt(stock.roe)+'%' : '—'},
              {label:L('Gross Margin','毛利率'), val:stock.gross_margin != null ? fmt(stock.gross_margin)+'%' : '—'},
              {label:L('Rev Growth','营收增速'), val:stock.revenue_growth != null ? fmt(stock.revenue_growth)+'%' : '—'},
              {label:L('Profit Growth','利润增速'), val:stock.profit_growth != null ? fmt(stock.profit_growth)+'%' : '—'},
              {label:L('Volume','成交量'), val:fmtBig(stock.volume)},
              {label:L('Turnover','成交额'), val:fmtBig(stock.turnover)},
              {label:L('Amplitude','振幅'), val:stock.amplitude != null ? fmt(stock.amplitude)+'%' : '—'},
            ].map((item,i) => (
              <div key={i} style={{minWidth:85}}>
                <div style={{fontSize:9, color:C.mid}}>{item.label}</div>
                <div style={{fontSize:13, fontWeight:700, fontFamily:'monospace', color:C.dark}}>{item.val}</div>
              </div>
            ))}
          </div>

          {/* CTA */}
          <div style={{padding:14, background:`${C.green}08`, borderRadius:8, border:`1px solid ${C.green}25`, textAlign:'center'}}>
            <div style={{fontSize:12, color:C.dark, marginBottom:8}}>
              {L('This stock has market data only. Run Deep Research to generate a full buy-side pitch with VP Score, variant thesis, catalysts, and risk matrix.',
                 '该股票仅有行情数据。运行深度研究以生成完整的买方研究报告，包含VP评分、变体论点、催化剂和风险矩阵。')}
            </div>
            <button onClick={()=>onDeepResearch(stock.ticker)} style={{padding:'10px 24px', background:C.green, color:'#fff', border:'none', borderRadius:6, cursor:'pointer', fontSize:12, fontWeight:700, display:'inline-flex', alignItems:'center', gap:6}}>
              <Zap size={14}/>{L('Generate Full Analysis','生成完整分析')}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

/* ── MORNING REPORT PAGE ─────────────────────────────────────────────── */
function MorningReportPage({ L, lk, C, reportData, reportLoading, onGenerate, liveData, newsPortfolio, newsMacro, regimeData, predictions, allStocks }) {

  // ── helpers ──────────────────────────────────────────────────────────────
  const MOOD_COLOR   = { 'RISK-ON': C.green, NEUTRAL: C.mid,  'RISK-OFF': C.red };
  const STATUS_COLOR = { CLEAR: C.green,     WATCH: C.gold,   ACTION: '#f97316', ALERT: C.red };
  const URGENCY_COLOR= { HIGH: C.red,        MED: C.gold,     LOW: C.green };
  const IMPACT_COLOR = { HIGH: C.red,        MED: C.gold,     LOW: C.green };

  // ── trigger ───────────────────────────────────────────────────────────────
  const handleRun = () => {
    // Collect current portfolio state to pass to API
    const portfolio = Object.entries(allStocks || {}).map(([tk, s]) => {
      const lv    = liveData?.yahoo?.[tk];
      const price = lv?.price?.last;
      const chg   = lv?.price?.change_pct;
      let sectorRegime = null;
      if (regimeData?.sectors) {
        const sec = regimeData.sectors.find(se => (se.tickers||[]).includes(tk));
        if (sec) sectorRegime = sec.regime;
      }
      return {
        ticker: tk, company: s.en || s.name,
        vp: s.vp, dir: s.dir, sector: s.sector,
        current_price:    price  ?? null,
        price_change_pct: chg    ?? null,
        sector_regime:    sectorRegime,
        variant_brief:    s.variant?.weBelieve?.e || null,
      };
    });

    const today = new Date().toISOString().slice(0, 10);
    const recentMacro  = (newsMacro     || []).slice(0, 8).map(n=>({ title:n.title, source:n.source }));
    const recentPort   = (newsPortfolio || []).slice(0, 10).map(n=>({ title:n.title, source:n.source, ticker:n.ticker }));

    onGenerate({ date: today, portfolio, macro_news: recentMacro, portfolio_news: recentPort, regime_data: regimeData, predictions: (predictions||[]) });
  };

  // ── loading state ─────────────────────────────────────────────────────────
  if (reportLoading) return (
    <div style={{display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center', height:300, gap:16}}>
      <div style={{width:36, height:36, border:`3px solid ${C.border}`, borderTop:`3px solid ${C.blue}`, borderRadius:'50%', animation:'spin 0.8s linear infinite'}}></div>
      <div style={{fontSize:12, color:C.mid}}>{L('Generating morning brief…','正在生成早报…')}</div>
      <div style={{fontSize:10, color:C.mid}}>{L('~15 seconds','约15秒')}</div>
    </div>
  );

  // ── empty state ───────────────────────────────────────────────────────────
  if (!reportData) return (
    <div style={{display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center', height:'60vh', gap:20}}>
      <div style={{fontSize:40}}>🌅</div>
      <div style={{fontSize:16, fontWeight:700, color:C.dark}}>{L("Today's Morning Brief","今日早报")}</div>
      <div style={{fontSize:12, color:C.mid, textAlign:'center', maxWidth:340, lineHeight:1.7}}>
        {L('Claude analyzes overnight news, portfolio status, open predictions, and sector regimes to generate a 5-minute actionable brief.',
           'Claude 分析隔夜新闻、持仓状态、开放预测和板块政体，生成5分钟可操作早报。')}
      </div>
      <button onClick={handleRun} style={{
        padding:'12px 32px', background:C.blue, color:'#fff', border:'none', borderRadius:8,
        cursor:'pointer', fontSize:13, fontWeight:700, display:'flex', alignItems:'center', gap:8,
      }}>
        <Zap size={16}/> {L('Generate Morning Report','生成早报')}
      </button>
      <div style={{fontSize:10, color:C.mid}}>{L('~2500 tokens · 15 seconds','约2500 tokens · 15秒')}</div>
    </div>
  );

  // ── report view ───────────────────────────────────────────────────────────
  const r         = reportData;
  const moodColor = MOOD_COLOR[r.market_mood] || C.mid;

  return (
    <div style={{maxWidth:860, margin:'0 auto', paddingBottom:40}}>

      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div style={{background:'#1a1a2e', borderRadius:10, padding:'20px 24px', marginBottom:3}}>
        <div style={{display:'flex', alignItems:'flex-start', justifyContent:'space-between', gap:16}}>
          <div style={{flex:1}}>
            <div style={{fontSize:9, color:'#8b8fc7', fontWeight:700, letterSpacing:'0.1em', textTransform:'uppercase', marginBottom:6}}>
              AR Platform · {r.date || new Date().toISOString().slice(0,10)}
            </div>
            <div style={{fontSize:18, fontWeight:800, color:'#fff', lineHeight:1.3}}>
              {r.headline || L('Morning Brief','早报')}
            </div>
          </div>
          <div style={{display:'flex', flexDirection:'column', alignItems:'flex-end', gap:6, flexShrink:0}}>
            <span style={{fontSize:11, fontWeight:700, padding:'4px 12px', borderRadius:5, background:`${moodColor}25`, color:moodColor}}>
              {r.market_mood || 'NEUTRAL'}
            </span>
            <button onClick={handleRun} style={{fontSize:9, padding:'3px 10px', background:'rgba(255,255,255,0.08)', color:'rgba(255,255,255,0.5)', border:'1px solid rgba(255,255,255,0.12)', borderRadius:4, cursor:'pointer', fontWeight:600}}>
              {L('↺ Refresh','↺ 刷新')}
            </button>
          </div>
        </div>
      </div>

      {/* ── Macro Summary ──────────────────────────────────────────────── */}
      {r.macro_summary && (
        <div style={{background:C.card, border:`1px solid ${C.border}`, borderRadius:0, padding:'16px 24px', marginBottom:3}}>
          <div style={{fontSize:9, fontWeight:700, color:C.mid, letterSpacing:'0.08em', textTransform:'uppercase', marginBottom:10}}>
            📰 {L('Macro Overview','宏观概况')}
          </div>
          <div style={{fontSize:12, color:C.dark, lineHeight:1.8}}>{r.macro_summary[lk]}</div>
          {r.top_story && (
            <div style={{marginTop:12, padding:'10px 14px', background:`${C.blue}08`, borderLeft:`3px solid ${C.blue}`, borderRadius:'0 6px 6px 0'}}>
              <div style={{fontSize:10, fontWeight:700, color:C.blue, marginBottom:4}}>
                {r.top_story.source && <span style={{marginRight:6}}>[{r.top_story.source}]</span>}
                {r.top_story.title}
              </div>
              <div style={{fontSize:11, color:C.dark, lineHeight:1.6}}>{r.top_story[lk==='z'?'impact_z':'impact_e']}</div>
              {r.top_story.tickers_affected?.length > 0 && (
                <div style={{fontSize:10, color:C.mid, marginTop:4}}>
                  {L('Affects:','影响:')} {r.top_story.tickers_affected.map(t => (
                    <span key={t} style={{fontFamily:'monospace', fontWeight:700, color:C.dark, marginLeft:4}}>{t}</span>
                  ))}
                </div>
              )}
            </div>
          )}
          {r.regime_notes && r.regime_notes !== 'No regime changes today' && (
            <div style={{marginTop:10, fontSize:10, color:C.gold, padding:'6px 10px', background:`${C.gold}10`, borderRadius:4}}>
              ⚡ {r.regime_notes}
            </div>
          )}
        </div>
      )}

      {/* ── Portfolio Flags ────────────────────────────────────────────── */}
      {r.portfolio_flags?.length > 0 && (
        <div style={{background:C.card, border:`1px solid ${C.border}`, padding:'16px 24px', marginBottom:3}}>
          <div style={{fontSize:9, fontWeight:700, color:C.mid, letterSpacing:'0.08em', textTransform:'uppercase', marginBottom:12}}>
            📊 {L('Portfolio Status','持仓状态')}
          </div>
          <div style={{display:'flex', flexDirection:'column', gap:8}}>
            {r.portfolio_flags.map((f, i) => {
              const sc = STATUS_COLOR[f.status] || C.mid;
              return (
                <div key={i} style={{display:'flex', gap:12, alignItems:'flex-start', padding:'10px 12px', background:`${sc}08`, border:`1px solid ${sc}20`, borderRadius:6}}>
                  <div style={{flexShrink:0, display:'flex', flexDirection:'column', gap:4, minWidth:100}}>
                    <span style={{fontFamily:'monospace', fontSize:11, fontWeight:700, color:C.dark}}>{f.ticker}</span>
                    <span style={{fontSize:9, padding:'1px 7px', borderRadius:3, fontWeight:700, background:`${sc}18`, color:sc, display:'inline-block', textAlign:'center'}}>{f.status}</span>
                  </div>
                  <div style={{flex:1}}>
                    <div style={{fontSize:11, color:C.dark, lineHeight:1.6}}>{lk==='z' ? f.note_z : f.note_e}</div>
                    {f.action_required && (
                      <div style={{fontSize:9, color:C.red, fontWeight:700, marginTop:4}}>⚡ {L('Action required today','今日需要操作')}</div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Trade Ideas ────────────────────────────────────────────────── */}
      {r.trade_ideas?.length > 0 && (
        <div style={{background:C.card, border:`1px solid ${C.border}`, padding:'16px 24px', marginBottom:3}}>
          <div style={{fontSize:9, fontWeight:700, color:C.mid, letterSpacing:'0.08em', textTransform:'uppercase', marginBottom:12}}>
            💡 {L("Today's Trade Ideas","今日交易思路")}
          </div>
          <div style={{display:'flex', flexDirection:'column', gap:10}}>
            {r.trade_ideas.map((t, i) => {
              const uc = URGENCY_COLOR[t.urgency] || C.mid;
              return (
                <div key={i} style={{padding:'12px 14px', background:C.bg, border:`1px solid ${C.border}`, borderLeft:`3px solid ${uc}`, borderRadius:'0 6px 6px 0'}}>
                  <div style={{display:'flex', alignItems:'center', gap:8, marginBottom:6}}>
                    <span style={{fontFamily:'monospace', fontSize:12, fontWeight:700, color:C.dark}}>{t.ticker}</span>
                    <span style={{fontSize:9, padding:'1px 6px', borderRadius:3, fontWeight:700, background:`${uc}18`, color:uc}}>{t.urgency}</span>
                  </div>
                  <div style={{fontSize:12, color:C.dark, lineHeight:1.6, marginBottom:4}}>{lk==='z' ? t.idea_z : t.idea_e}</div>
                  {t.entry && <div style={{fontSize:10, color:C.blue, fontWeight:600}}>📍 {t.entry}</div>}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Event Radar + Prediction Updates (side by side) ────────────── */}
      <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:3, marginBottom:3}}>
        {r.event_radar?.length > 0 && (
          <div style={{background:C.card, border:`1px solid ${C.border}`, padding:'16px 20px'}}>
            <div style={{fontSize:9, fontWeight:700, color:C.mid, letterSpacing:'0.08em', textTransform:'uppercase', marginBottom:10}}>
              📅 {L('Event Radar','事件雷达')}
            </div>
            {r.event_radar.map((e, i) => {
              const ic = IMPACT_COLOR[e.impact] || C.mid;
              return (
                <div key={i} style={{display:'flex', gap:8, marginBottom:8, fontSize:11}}>
                  <span style={{color:C.mid, fontSize:9, whiteSpace:'nowrap', paddingTop:2}}>{e.date}</span>
                  <div style={{flex:1}}>
                    <div style={{color:C.dark, lineHeight:1.5}}>{e.event}</div>
                    {e.ticker && <span style={{fontFamily:'monospace', fontSize:9, color:C.mid}}>{e.ticker}</span>}
                  </div>
                  <span style={{fontSize:9, fontWeight:700, color:ic, flexShrink:0}}>{e.impact}</span>
                </div>
              );
            })}
          </div>
        )}
        {r.prediction_updates?.length > 0 && (
          <div style={{background:C.card, border:`1px solid ${C.border}`, padding:'16px 20px'}}>
            <div style={{fontSize:9, fontWeight:700, color:C.mid, letterSpacing:'0.08em', textTransform:'uppercase', marginBottom:10}}>
              🎯 {L('Prediction Updates','预测更新')}
            </div>
            {r.prediction_updates.map((p, i) => {
              const ac = { 'ON-TRACK':C.green, VERIFY:C.green, FALSIFY:C.red, MONITOR:C.gold }[p.action] || C.mid;
              return (
                <div key={i} style={{display:'flex', gap:8, alignItems:'flex-start', marginBottom:8}}>
                  <span style={{fontSize:9, padding:'2px 6px', borderRadius:3, fontWeight:700, background:`${ac}18`, color:ac, whiteSpace:'nowrap', flexShrink:0}}>{p.action}</span>
                  <div>
                    <span style={{fontFamily:'monospace', fontSize:10, fontWeight:700, color:C.dark}}>{p.ticker} </span>
                    <span style={{fontSize:10, color:C.mid, lineHeight:1.5}}>{p.reason}</span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* ── Footer ─────────────────────────────────────────────────────── */}
      <div style={{fontSize:9, color:C.mid, textAlign:'center', paddingTop:12}}>
        {r.generated_at && L(`Generated ${new Date(r.generated_at).toLocaleString('en-HK',{timeZone:'Asia/Hong_Kong',hour12:false})} HKT · ${r.tokens_used||'—'} tokens`,
                               `生成于 ${new Date(r.generated_at).toLocaleString('zh-CN',{timeZone:'Asia/Hong_Kong'})} HKT · ${r.tokens_used||'—'} tokens`)}
      </div>
    </div>
  );
}

/* ── TODAY'S PULSE CARD ───────────────────────────────────────────────── */
function PulseCard({ pulse, loading, ticker, onRunPulse, L, lk, C }) {
  const STATUS_COLOR = { INTACT:'#22c55e', WATCH:'#eab308', REVIEW:'#f97316', BROKEN:'#ef4444' };
  const RISK_COLOR   = { LOW:'#22c55e', MED:'#eab308', HIGH:'#ef4444' };
  const ENTRY_COLOR  = { VALID:'#22c55e', ADJUSTED:'#eab308', STALE:'#ef4444' };

  // Loading skeleton
  if (loading) return (
    <div style={{background:C.card, border:`1px solid ${C.border}`, borderRadius:8, padding:'12px 16px', marginBottom:12, display:'flex', alignItems:'center', gap:10}}>
      <div style={{width:8, height:8, borderRadius:'50%', background:C.blue, animation:'pulse 1.5s infinite'}}></div>
      <span style={{fontSize:10, color:C.mid}}>{L('Running daily pulse check…','正在运行每日脉冲检查…')}</span>
    </div>
  );

  // No pulse yet + has stored research → show trigger button
  if (!pulse) {
    const hasStored = (() => { try { return !!localStorage.getItem(`ar_research_${ticker}`); } catch { return false; } })();
    if (!hasStored) return null;
    return (
      <div style={{background:C.card, border:`1px solid ${C.border}`, borderRadius:8, padding:'10px 16px', marginBottom:12, display:'flex', alignItems:'center', justifyContent:'space-between'}}>
        <span style={{fontSize:10, color:C.mid}}>{L("Today's pulse not yet run","今日脉冲尚未运行")}</span>
        <button onClick={() => onRunPulse(ticker)} style={{fontSize:9, padding:'3px 10px', background:`${C.blue}15`, color:C.blue, border:`1px solid ${C.blue}30`, borderRadius:4, cursor:'pointer', fontWeight:700}}>
          {L('Run Pulse','运行脉冲')}
        </button>
      </div>
    );
  }

  const vColor = STATUS_COLOR[pulse.variant_status] || C.mid;
  const eColor = ENTRY_COLOR[pulse.entry_status]    || C.mid;
  const rColor = RISK_COLOR[pulse.headline_risk]    || C.mid;

  return (
    <div style={{background:C.card, border:`1.5px solid ${vColor}30`, borderRadius:8, padding:'12px 16px', marginBottom:12}}>
      {/* Header row */}
      <div style={{display:'flex', alignItems:'center', gap:8, marginBottom:10}}>
        <div style={{width:7, height:7, borderRadius:'50%', background:vColor, flexShrink:0}}></div>
        <span style={{fontSize:11, fontWeight:700, color:C.dark}}>{L("Today's Pulse","今日脉冲")}</span>
        <span style={{fontSize:9, color:C.mid, marginLeft:'auto'}}>{pulse.pulse_date}</span>
        {pulse.thesis_age_flag && (
          <span style={{fontSize:9, padding:'1px 6px', background:'#f9731620', color:'#f97316', borderRadius:3, fontWeight:700}}>
            ⚠ {L('>30d stale','>30天未更新')}
          </span>
        )}
        {pulse.large_move_flag && (
          <span style={{fontSize:9, padding:'1px 6px', background:'#ef444420', color:'#ef4444', borderRadius:3, fontWeight:700}}>
            ⚡ {L('>15% move','>15%价格变动')}
          </span>
        )}
      </div>

      {/* Three status pills */}
      <div style={{display:'flex', gap:8, marginBottom:10, flexWrap:'wrap'}}>
        <div style={{flex:1, minWidth:120, background:`${vColor}10`, border:`1px solid ${vColor}30`, borderRadius:6, padding:'6px 10px'}}>
          <div style={{fontSize:9, color:C.mid, marginBottom:2}}>{L('Variant','论点')}</div>
          <div style={{fontSize:10, fontWeight:700, color:vColor}}>{pulse.variant_status}</div>
          <div style={{fontSize:9, color:C.dark, marginTop:3, lineHeight:1.4}}>{pulse.variant_reason}</div>
        </div>
        <div style={{flex:1, minWidth:120, background:`${eColor}10`, border:`1px solid ${eColor}30`, borderRadius:6, padding:'6px 10px'}}>
          <div style={{fontSize:9, color:C.mid, marginBottom:2}}>{L('Entry','进场')}</div>
          <div style={{fontSize:10, fontWeight:700, color:eColor}}>{pulse.entry_status}</div>
          <div style={{fontSize:9, color:C.dark, marginTop:3, lineHeight:1.4}}>
            {pulse.entry_note}
            {pulse.adjusted_entry && <span style={{color:C.blue, fontWeight:700}}> → {pulse.adjusted_entry}</span>}
          </div>
        </div>
        <div style={{flex:1, minWidth:100, background:`${rColor}10`, border:`1px solid ${rColor}30`, borderRadius:6, padding:'6px 10px'}}>
          <div style={{fontSize:9, color:C.mid, marginBottom:2}}>{L('News Risk','新闻风险')}</div>
          <div style={{fontSize:10, fontWeight:700, color:rColor}}>{pulse.headline_risk}</div>
          <div style={{fontSize:9, color:C.dark, marginTop:3, lineHeight:1.4}}>{pulse.headline_note}</div>
        </div>
      </div>

      {/* Prediction updates (only if any flagged) */}
      {pulse.prediction_updates?.length > 0 && (
        <div style={{borderTop:`1px solid ${C.border}`, paddingTop:8}}>
          <div style={{fontSize:9, fontWeight:700, color:C.mid, marginBottom:6}}>{L('Prediction Updates','预测更新')}</div>
          {pulse.prediction_updates.map((u, i) => {
            const ac = u.action === 'VERIFY' ? C.green : u.action === 'FALSIFY' ? C.red : C.gold;
            return (
              <div key={i} style={{display:'flex', gap:8, alignItems:'flex-start', marginBottom:4}}>
                <span style={{fontSize:9, padding:'1px 6px', borderRadius:3, fontWeight:700, background:`${ac}15`, color:ac, flexShrink:0}}>{u.action}</span>
                <span style={{fontSize:9, color:C.dark, lineHeight:1.4}}>{u.reason}</span>
              </div>
            );
          })}
        </div>
      )}

      {/* Token cost footer */}
      <div style={{fontSize:8, color:C.mid, marginTop:6, display:'flex', gap:8}}>
        {pulse.tokens_used && <span>~{pulse.tokens_used} tokens</span>}
        <button onClick={() => onRunPulse(ticker)} style={{fontSize:8, padding:'1px 6px', background:'transparent', color:C.mid, border:`1px solid ${C.border}`, borderRadius:3, cursor:'pointer'}}>
          {L('Refresh','刷新')}
        </button>
      </div>
    </div>
  );
}

/* ── DEEP RESEARCH FINANCIALS ─────────────────────────────────────────── */
function DeepResearchFinancials({ stock, L, lk, C }) {
  const [tab, setTab] = useState('is');
  const is  = stock?.income_statement;
  const bs  = stock?.balance_sheet;
  const con = stock?.consensus;
  const ins = stock?.fin_insights || [];
  if (!is && !bs && !con) return null;

  const curr = is?.currency || bs?.currency || 'CNY';
  const unit = 'M';

  const fmtN = (n) => {
    if (n == null) return <span style={{color:C.mid}}>—</span>;
    const abs = Math.abs(n);
    const str = abs >= 10000 ? `${(n/1000).toFixed(1)}B` : abs >= 1000 ? `${(n/1000).toFixed(2)}B` : `${n.toFixed(0)}M`;
    return <span style={{color: n < 0 ? C.red : C.dark}}>{n < 0 ? str : str}</span>;
  };
  const fmtPct = (n) => {
    if (n == null) return <span style={{color:C.mid}}>—</span>;
    const pct = (n * 100).toFixed(1) + '%';
    return <span style={{color: n < 0 ? C.red : n > 0.25 ? C.green : C.dark}}>{pct}</span>;
  };
  const fmtGrowth = (n) => {
    if (n == null) return <span style={{color:C.mid}}>—</span>;
    const pct = (n >= 0 ? '+' : '') + (n * 100).toFixed(1) + '%';
    return <span style={{color: n > 0 ? C.green : C.red, fontWeight:600}}>{pct}</span>;
  };

  const thStyle = {padding:'7px 10px', fontSize:10, fontWeight:700, color:C.mid, textAlign:'right', borderBottom:`1px solid ${C.border}`, whiteSpace:'nowrap'};
  const tdStyle = {padding:'7px 10px', fontSize:11, textAlign:'right', borderBottom:`1px solid ${C.border}40`};
  const labelStyle = {padding:'7px 10px', fontSize:10, color:C.mid, borderBottom:`1px solid ${C.border}40`, whiteSpace:'nowrap'};
  const sectionStyle = {padding:'5px 10px', fontSize:9, fontWeight:700, color:C.mid, background:C.soft, letterSpacing:'0.05em', textTransform:'uppercase'};

  const periods = is?.periods || bs?.periods || [];

  return (
    <div>
      {/* Tab bar */}
      <div style={{display:'flex', gap:4, marginBottom:12, borderBottom:`1px solid ${C.border}`, paddingBottom:8}}>
        {[
          {id:'is',  label:L('Income Statement','利润表')},
          {id:'bs',  label:L('Balance Sheet','资产负债表')},
          {id:'con', label:L('Consensus','分析师共识')},
        ].filter(t => (t.id==='is'&&is)||(t.id==='bs'&&bs)||(t.id==='con'&&con)).map(t => (
          <button key={t.id} onClick={()=>setTab(t.id)} style={{
            padding:'5px 12px', fontSize:10, fontWeight:600, borderRadius:5, border:'none', cursor:'pointer',
            background: tab===t.id ? C.blue : 'transparent',
            color: tab===t.id ? '#fff' : C.mid,
          }}>{t.label}</button>
        ))}
      </div>

      {/* Income Statement */}
      {tab==='is' && is && (
        <div style={{overflowX:'auto'}}>
          <table style={{width:'100%', borderCollapse:'collapse', fontSize:11}}>
            <thead>
              <tr>
                <th style={{...thStyle, textAlign:'left', width:160}}>{curr} {unit}</th>
                {periods.map((p,i) => <th key={i} style={thStyle}>{p}</th>)}
              </tr>
            </thead>
            <tbody>
              <tr><td colSpan={periods.length+1} style={sectionStyle}>Revenue</td></tr>
              <tr>
                <td style={labelStyle}>{L('Revenue','营业收入')}</td>
                {is.revenue.map((v,i)=><td key={i} style={tdStyle}>{fmtN(v)}</td>)}
              </tr>
              <tr>
                <td style={{...labelStyle, paddingLeft:18}}>{L('YoY Growth','同比增长')}</td>
                {is.revenue_growth.map((v,i)=><td key={i} style={tdStyle}>{fmtGrowth(v)}</td>)}
              </tr>
              <tr><td colSpan={periods.length+1} style={sectionStyle}>Profitability</td></tr>
              <tr>
                <td style={labelStyle}>{L('Gross Profit','毛利润')}</td>
                {is.gross_profit.map((v,i)=><td key={i} style={tdStyle}>{fmtN(v)}</td>)}
              </tr>
              <tr>
                <td style={{...labelStyle, paddingLeft:18}}>{L('Gross Margin','毛利率')}</td>
                {is.gross_margin.map((v,i)=><td key={i} style={tdStyle}>{fmtPct(v)}</td>)}
              </tr>
              <tr>
                <td style={labelStyle}>{L('Operating Income','营业利润')}</td>
                {is.operating_income.map((v,i)=><td key={i} style={tdStyle}>{fmtN(v)}</td>)}
              </tr>
              <tr>
                <td style={{...labelStyle, paddingLeft:18}}>{L('Operating Margin','营业利润率')}</td>
                {is.operating_margin.map((v,i)=><td key={i} style={tdStyle}>{fmtPct(v)}</td>)}
              </tr>
              <tr>
                <td style={labelStyle}>{L('Net Income','净利润')}</td>
                {is.net_income.map((v,i)=><td key={i} style={tdStyle}>{fmtN(v)}</td>)}
              </tr>
              <tr>
                <td style={{...labelStyle, paddingLeft:18}}>{L('Net Margin','净利率')}</td>
                {is.net_margin.map((v,i)=><td key={i} style={tdStyle}>{fmtPct(v)}</td>)}
              </tr>
              {is.ebitda && <tr>
                <td style={labelStyle}>EBITDA</td>
                {is.ebitda.map((v,i)=><td key={i} style={tdStyle}>{fmtN(v)}</td>)}
              </tr>}
            </tbody>
          </table>
        </div>
      )}

      {/* Balance Sheet */}
      {tab==='bs' && bs && (
        <div style={{overflowX:'auto'}}>
          <table style={{width:'100%', borderCollapse:'collapse', fontSize:11}}>
            <thead>
              <tr>
                <th style={{...thStyle, textAlign:'left', width:160}}>{curr} {unit}</th>
                {(bs.periods||[]).map((p,i)=><th key={i} style={thStyle}>{p}</th>)}
              </tr>
            </thead>
            <tbody>
              <tr><td colSpan={(bs.periods||[]).length+1} style={sectionStyle}>Assets & Liabilities</td></tr>
              <tr><td style={labelStyle}>{L('Total Assets','总资产')}</td>{bs.total_assets.map((v,i)=><td key={i} style={tdStyle}>{fmtN(v)}</td>)}</tr>
              <tr><td style={labelStyle}>{L('Total Equity','股东权益')}</td>{bs.total_equity.map((v,i)=><td key={i} style={tdStyle}>{fmtN(v)}</td>)}</tr>
              <tr><td style={labelStyle}>{L('Total Debt','有息负债')}</td>{bs.total_debt.map((v,i)=><td key={i} style={tdStyle}>{fmtN(v)}</td>)}</tr>
              <tr><td style={labelStyle}>{L('Cash & Equivalents','货币资金')}</td>{bs.cash.map((v,i)=><td key={i} style={tdStyle}>{fmtN(v)}</td>)}</tr>
              <tr><td colSpan={(bs.periods||[]).length+1} style={sectionStyle}>Return & Leverage</td></tr>
              <tr>
                <td style={labelStyle}>{L('ROE','净资产收益率')}</td>
                {bs.roe.map((v,i)=><td key={i} style={tdStyle}>{fmtPct(v)}</td>)}
              </tr>
              <tr>
                <td style={labelStyle}>{L('Debt / Equity','资产负债率')}</td>
                {bs.debt_to_equity.map((v,i)=><td key={i} style={tdStyle}>{v!=null?<span style={{color:v>1?C.red:C.dark}}>{v.toFixed(2)}x</span>:<span style={{color:C.mid}}>—</span>}</td>)}
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {/* Consensus */}
      {tab==='con' && con && (
        <div>
          <div style={{display:'grid', gridTemplateColumns:'repeat(3, 1fr)', gap:10, marginBottom:14}}>
            <div style={{padding:12, background:C.soft, borderRadius:8}}>
              <div style={{fontSize:9, color:C.mid, fontWeight:700, marginBottom:4}}>{L('Consensus Rating','分析师评级')}</div>
              <div style={{fontSize:15, fontWeight:800, color:C.green}}>{con.rating}</div>
              <div style={{fontSize:9, color:C.mid, marginTop:2}}>{con.num_analysts} {L('analysts','位分析师')}</div>
            </div>
            <div style={{padding:12, background:C.soft, borderRadius:8}}>
              <div style={{fontSize:9, color:C.mid, fontWeight:700, marginBottom:4}}>{L('Target Price','目标价')}</div>
              <div style={{fontSize:15, fontWeight:800, color:C.dark}}>{con.target_price}</div>
              <div style={{fontSize:9, color:parseFloat(con.upside)>0?C.green:C.red, marginTop:2, fontWeight:600}}>{con.upside}</div>
            </div>
            <div style={{padding:12, background:C.soft, borderRadius:8}}>
              <div style={{fontSize:9, color:C.mid, fontWeight:700, marginBottom:4}}>{L('FY+1 Revenue Est.','FY+1营收预测')}</div>
              <div style={{fontSize:13, fontWeight:700, color:C.dark}}>{con.fy1_rev_est}</div>
              <div style={{fontSize:9, color:C.mid, marginTop:2}}>EPS: {con.fy1_eps_est}</div>
            </div>
          </div>
          {/* Rating distribution bar */}
          <div style={{marginBottom:10}}>
            <div style={{fontSize:9, color:C.mid, marginBottom:5, fontWeight:700}}>{L('Rating Distribution','评级分布')}</div>
            <div style={{display:'flex', height:8, borderRadius:4, overflow:'hidden', gap:1}}>
              <div style={{width:`${con.buy_pct||0}%`, background:C.green}}></div>
              <div style={{width:`${con.hold_pct||0}%`, background:C.gold}}></div>
              <div style={{width:`${con.sell_pct||0}%`, background:C.red}}></div>
            </div>
            <div style={{display:'flex', gap:12, marginTop:5}}>
              <span style={{fontSize:9, color:C.green}}>Buy {con.buy_pct}%</span>
              <span style={{fontSize:9, color:C.gold}}>Hold {con.hold_pct}%</span>
              <span style={{fontSize:9, color:C.red}}>Sell {con.sell_pct}%</span>
            </div>
          </div>
        </div>
      )}

      {/* Financial Insights */}
      {ins.length > 0 && (
        <div style={{marginTop:14, padding:'10px 14px', background:`${C.blue}08`, border:`1px solid ${C.blue}20`, borderRadius:7}}>
          <div style={{fontSize:9, fontWeight:700, color:C.blue, marginBottom:8, letterSpacing:'0.05em', textTransform:'uppercase'}}>
            {L('Financial Insights (AI-generated)','财务洞察（AI生成）')}
          </div>
          {ins.map((insight, i) => (
            <div key={i} style={{display:'flex', gap:8, marginBottom:6}}>
              <span style={{color:C.blue, flexShrink:0, fontSize:11}}>·</span>
              <span style={{fontSize:10, color:C.dark, lineHeight:1.6}}>{insight}</span>
            </div>
          ))}
          <div style={{fontSize:8, color:C.mid, marginTop:8, borderTop:`1px solid ${C.border}`, paddingTop:6}}>
            ⚠ {L('Figures are AI estimates from training data — verify against official filings before acting.',
                   '数据为AI基于训练知识的估算，采取行动前请与官方财报核对。')}
          </div>
        </div>
      )}
    </div>
  );
}

/* ── REVERSE DCF PANEL ────────────────────────────────────────────────── */
function MetricBox({ label, value, sub, color, C }) {
  const c = color || C.dark;
  return (
    <div style={{padding:'10px 14px', background:`${c}08`, border:`1px solid ${c}25`, borderRadius:7}}>
      <div style={{fontSize:9, fontWeight:700, color:C.mid, letterSpacing:'0.06em', marginBottom:4, textTransform:'uppercase'}}>{label}</div>
      <div style={{fontSize:16, fontWeight:800, color:c, fontFamily:'monospace'}}>{value}</div>
      {sub && <div style={{fontSize:9, color:C.mid, marginTop:3, lineHeight:1.4}}>{sub}</div>}
    </div>
  );
}

/* ── Profit Scissors / Financial Levers ────────────────────────────────────── */
// ── AI Infrastructure Leading Indicator Card ──────────────────────────────────
function LeadingIndicatorCard({ liData, ticker, L, C, open, toggle }) {
  // Only show for tickers with DIRECT upstream exposure to AI capex cycle
  const impl = liData?.stock_implications?.[ticker];
  if (!impl || impl.relevance !== 'DIRECT') return null;
  if (!liData?.composite_signal || liData.composite_signal === 'INSUFFICIENT_DATA') return null;

  const signal    = liData.composite_signal;
  const score     = liData.composite_score;
  const indicators = liData.indicators || {};
  const nvda      = indicators.nvda_revenue || {};
  const capex     = indicators.hyperscaler_capex || {};
  const tsmc      = indicators.tsmc_revenue || {};
  const momentum  = indicators.price_momentum || {};

  const SIGNAL_META = {
    STRONG_CAPEX_CYCLE: { label: L('Strong CapEx Cycle','强CapEx周期'), color: C.green,  icon: '🚀' },
    MODERATE:           { label: L('Moderate','温和'),                  color: C.gold,   icon: '→'  },
    WEAKENING:          { label: L('Weakening','减速'),                 color: C.red,    icon: '⚠️' },
  };
  const sm = SIGNAL_META[signal] || SIGNAL_META.MODERATE;

  const fmtQoQ = (v) => v == null ? '—' : (
    <span style={{color: v > 10 ? C.green : v > 0 ? C.gold : C.red, fontWeight:700}}>
      {v > 0 ? '+' : ''}{v.toFixed(1)}%
    </span>
  );

  const th = {padding:'5px 8px', fontSize:9, fontWeight:700, color:C.mid, textAlign:'right',
               borderBottom:`1px solid ${C.border}`};
  const td = {padding:'5px 8px', fontSize:10, textAlign:'right', borderBottom:`1px solid ${C.border}40`,
               fontFamily:"'JetBrains Mono','Courier New',monospace"};
  const tdL = {...td, textAlign:'left', fontWeight:600, color:C.dark};

  // Latest 2 quarters for each indicator
  const nvdaQ  = (nvda.quarters  || []).slice(0, 2);
  const tsmc0  = (tsmc.quarters  || []).slice(0, 1);

  return (
    <Card
      title={L('AI CapEx Cycle','AI资本开支周期')}
      sub={L('NVDA · Hyperscaler CapEx · TSMC — upstream demand for optical transceivers',
             'NVDA·超大规模CapEx·台积电 — 光模块上游需求指标')}
      open={open?.aiCapex !== false}
      onToggle={toggle ? () => toggle('aiCapex') : undefined}
      C={C}
    >
      {/* Signal badge */}
      <div style={{display:'flex', alignItems:'center', gap:10, marginBottom:14, padding:'10px 12px',
                   background:`${sm.color}12`, border:`1px solid ${sm.color}30`, borderRadius:7}}>
        <span style={{fontSize:20}}>{sm.icon}</span>
        <div style={{flex:1}}>
          <div style={{fontWeight:700, color:sm.color, fontSize:12}}>{sm.label}</div>
          <div style={{fontSize:9, color:C.mid, marginTop:1}}>
            {L('Composite score','综合评分')}: {score?.toFixed(0)}/100 ·{' '}
            {impl.rationale}
          </div>
        </div>
        <div style={{fontSize:9, color:C.mid, textAlign:'right'}}>
          {L('Lag','前置')}<br/>
          <span style={{color:C.dark, fontWeight:700}}>{impl.lag_months}M</span>
        </div>
      </div>

      {/* Data table */}
      <table style={{width:'100%', borderCollapse:'collapse', fontSize:11}}>
        <thead>
          <tr>
            <th style={{...th, textAlign:'left'}}>{L('Indicator','指标')}</th>
            <th style={th}>{L('Latest QoQ','最新QoQ')}</th>
            <th style={th}>{L('Prior QoQ','上季QoQ')}</th>
            <th style={th}>{L('Signal','信号')}</th>
          </tr>
        </thead>
        <tbody>
          {/* NVDA */}
          <tr>
            <td style={tdL}>NVIDIA Revenue</td>
            <td style={td}>{fmtQoQ(nvdaQ[0]?.qoq_pct)}</td>
            <td style={td}>{fmtQoQ(nvdaQ[1]?.qoq_pct)}</td>
            <td style={{...td, color: nvda.signal === 'ACCELERATING' ? C.green : nvda.signal === 'DECELERATING' ? C.red : C.gold}}>
              {nvda.signal || '—'}
            </td>
          </tr>
          {/* Hyperscaler CapEx */}
          <tr>
            <td style={tdL}>{L('Hyperscaler CapEx (4)','超大规模CapEx(4家)')}</td>
            <td style={td}>{fmtQoQ(capex.combined_capex_qoq_pct)}</td>
            <td style={{...td, color:C.mid}}>—</td>
            <td style={{...td, color: capex.signal === 'EXPANDING' ? C.green : capex.signal === 'CONTRACTING' ? C.red : C.gold}}>
              {capex.signal || '—'}
            </td>
          </tr>
          {/* TSMC */}
          <tr>
            <td style={tdL}>TSMC Revenue</td>
            <td style={td}>{fmtQoQ(tsmc0[0]?.qoq_pct)}</td>
            <td style={{...td, color:C.mid}}>—</td>
            <td style={{...td, color: tsmc.signal === 'STRONG' ? C.green : tsmc.signal === 'WEAK' ? C.red : C.gold}}>
              {tsmc.signal || '—'}
            </td>
          </tr>
          {/* Price momentum */}
          <tr>
            <td style={tdL}>{L('Hyperscaler Basket 3M','超大规模篮子3M')}</td>
            <td style={td}>{fmtQoQ(momentum.basket_return_3m_pct)}</td>
            <td style={{...td, color:C.mid}}>—</td>
            <td style={{...td, color: momentum.signal === 'BULLISH' ? C.green : momentum.signal === 'BEARISH' ? C.red : C.gold}}>
              {momentum.signal || '—'}
            </td>
          </tr>
        </tbody>
      </table>

      {/* CapEx breakdown mini row */}
      {capex.combined_capex_latest_bn && (
        <div style={{marginTop:10, padding:'8px 10px', background:C.soft, borderRadius:6,
                     fontSize:9, color:C.mid}}>
          {L('Combined CapEx (latest quarter)','合计CapEx(最新季度)')}: {' '}
          <span style={{color:C.dark, fontWeight:700}}>${capex.combined_capex_latest_bn?.toFixed(1)}B</span>
          {Object.entries(capex.components || {}).map(([tk, v]) => (
            <span key={tk} style={{marginLeft:8}}>
              {tk} <span style={{color: (v.latest_qoq||0) > 0 ? C.green : C.red}}>
                {(v.latest_qoq||0) > 0 ? '+' : ''}{(v.latest_qoq||0).toFixed(0)}%
              </span>
            </span>
          ))}
        </div>
      )}
    </Card>
  );
}

function ProfitScissors({ scissors, L, C, open, toggle }) {
  if (!scissors || scissors.error) return null;

  const { rows = [], verdict, summary } = scissors;
  if (!rows.length) return null;

  const VERDICT_META = {
    STRONG_POSITIVE_LEVERAGE: { label: L('Strong +Leverage','强正向杠杆'), color: C.green, icon: '↑↑' },
    POSITIVE_LEVERAGE:        { label: L('+Leverage','正向杠杆'),        color: C.green, icon: '↑'  },
    WEAK_LEVERAGE:            { label: L('Weak Leverage','弱杠杆'),      color: C.gold,  icon: '↗'  },
    NEAR_ZERO_LEVERAGE:       { label: L('Flat','近零杠杆'),             color: C.mid,   icon: '→'  },
    NEGATIVE_LEVERAGE:        { label: L('-Leverage','负向杠杆'),        color: C.red,   icon: '↓'  },
    INSUFFICIENT_DATA:        { label: L('Insufficient Data','数据不足'), color: C.mid,  icon: '?'  },
  };
  const vm = VERDICT_META[verdict] || VERDICT_META.INSUFFICIENT_DATA;

  const fmtRatio = (v) => v == null ? '—' : (
    <span style={{color: v >= 1.5 ? C.green : v >= 1.0 ? '#1e8c5a' : v >= 0.5 ? C.gold : C.red, fontWeight:700}}>
      {v.toFixed(2)}×
    </span>
  );
  const fmtGr = (v) => v == null ? <span style={{color:C.mid}}>—</span> : (
    <span style={{color: v > 0 ? C.green : C.red, fontWeight:600}}>{v > 0 ? '+' : ''}{v.toFixed(1)}%</span>
  );
  const fmtPp = (v) => v == null ? <span style={{color:C.mid}}>—</span> : (
    <span style={{color: v > 0 ? C.green : C.red}}>{v > 0 ? '+' : ''}{v.toFixed(1)}pp</span>
  );

  const th = {padding:'6px 10px', fontSize:9, fontWeight:700, color:C.mid, textAlign:'right',
               borderBottom:`1px solid ${C.border}`, whiteSpace:'nowrap'};
  const td = {padding:'6px 10px', fontSize:10, textAlign:'right', borderBottom:`1px solid ${C.border}40`, fontFamily:"'JetBrains Mono','Courier New',monospace"};
  const tdL = {...td, textAlign:'left', fontWeight:600, color:C.dark};

  return (
    <Card
      title={L('Financial Levers (Profit Scissors)','财务杠杆 (利润剪刀差)')}
      sub={L('NI/Rev ratio · GM trend · FCF quality','净利/营收比 · 毛利趋势 · FCF质量')}
      open={open?.scissors !== false}
      onToggle={toggle ? () => toggle('scissors') : undefined}
      C={C}
    >
      {/* Verdict badge */}
      <div style={{display:'flex', alignItems:'center', gap:10, marginBottom:14, padding:'10px 12px',
                   background:`${vm.color}10`, border:`1px solid ${vm.color}30`, borderRadius:7}}>
        <span style={{fontSize:18, lineHeight:1}}>{vm.icon}</span>
        <div>
          <div style={{fontWeight:700, color:vm.color, fontSize:12}}>{vm.label}</div>
          <div style={{fontSize:9, color:C.mid, marginTop:2}}>
            {summary?.latest_ni_rev_ratio != null && `NI/Rev ${summary.latest_ni_rev_ratio.toFixed(2)}× · `}
            {summary?.latest_gm_delta_pp != null && `GM ${summary.latest_gm_delta_pp > 0 ? '+' : ''}${summary.latest_gm_delta_pp.toFixed(1)}pp · `}
            {summary?.latest_rev_gr_pct  != null && `Rev ${summary.latest_rev_gr_pct > 0 ? '+' : ''}${summary.latest_rev_gr_pct.toFixed(1)}%`}
          </div>
        </div>
        <div style={{marginLeft:'auto', fontSize:9, color:C.mid, lineHeight:1.5}}>
          {L('NI/Rev > 1.0× = operating leverage · < 1.0× = margin compression',
             'NI/Rev > 1.0× = 正向经营杠杆 · < 1.0× = 利润增速跑输收入')}
        </div>
      </div>

      {/* Multi-year table */}
      <div style={{overflowX:'auto'}}>
        <table style={{width:'100%', borderCollapse:'collapse', fontSize:10}}>
          <thead>
            <tr>
              <th style={{...th, textAlign:'left'}}>Year</th>
              <th style={th}>Rev (B)</th>
              <th style={th}>Rev YoY</th>
              <th style={th}>NI (B)</th>
              <th style={th}>NI YoY</th>
              <th style={{...th, color: C.blue}}>NI/Rev</th>
              <th style={th}>GM%</th>
              <th style={{...th, color: C.blue}}>GM Δ</th>
              <th style={th}>FCF/NI</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} style={{background: i===0 ? `${C.blue}06` : 'transparent'}}>
                <td style={{...tdL, fontSize:10}}>{row.year}{i===0 ? ' ★' : ''}</td>
                <td style={td}>{row.rev_b ?? '—'}</td>
                <td style={td}>{fmtGr(row.rev_gr_pct)}</td>
                <td style={td}>{row.ni_b ?? '—'}</td>
                <td style={td}>{fmtGr(row.ni_gr_pct)}</td>
                <td style={{...td, fontWeight:700}}>{fmtRatio(row.ni_rev_ratio)}</td>
                <td style={td}>{row.gm_pct != null ? `${row.gm_pct}%` : '—'}</td>
                <td style={td}>{fmtPp(row.gm_delta_pp)}</td>
                <td style={td}>{row.fcf_ni_ratio != null ? `${row.fcf_ni_ratio.toFixed(2)}×` : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Legend */}
      <div style={{marginTop:10, fontSize:9, color:C.mid, lineHeight:1.7,
                   padding:'8px 10px', background:C.soft, borderRadius:5}}>
        {L('NI/Rev ratio = Net Income growth ÷ Revenue growth. Ratio ≥ 1.5× = strong positive operating leverage (Scissors spread widening). Ratio < 1.0× = negative leverage. FCF/NI ≥ 0.7× = high earnings quality.',
           'NI/Rev比 = 净利润增速÷营收增速。≥1.5×=强正向经营杠杆（剪刀差扩大）；<1.0×=负向杠杆。FCF/NI≥0.7×=高利润质量。')}
      </div>
    </Card>
  );
}

function ReverseDCF({ rdcf, L, C, open, toggle, egapScore }) {
  if (!rdcf) return null;
  // KR6: `egapScore` (canonical piecewise) replaces the deleted
  // rdcf.expectation_gap_score (tanh) field. Sourced from vp_snapshot.json
  // via the top-level Dashboard component → Research → ReverseDCF prop chain.
  // Single canonical owner is vp_engine.py per CLAUDE.md.
  const egapDisplay = egapScore != null ? egapScore : '—';

  const isA = rdcf.market === 'A' || rdcf.market === 'SH' || rdcf.market === 'SZ';
  const curr = isA ? '¥' : 'HK$';
  const err  = rdcf.error;

  const signalColor = rdcf.signal === 'UNDERPRICED' ? C.green
                    : rdcf.signal === 'OVERPRICED'  ? C.red
                    : C.gold;
  const signalLabel = rdcf.signal === 'UNDERPRICED' ? L('UNDERPRICED ↑','估值偏低 ↑')
                    : rdcf.signal === 'OVERPRICED'  ? L('OVERPRICED ↓','估值偏高 ↓')
                    : L('FAIRLY VALUED','合理估值');

  const fmtPct = v => v != null ? `${(v * 100).toFixed(1)}%` : '—';
  const fmtDelta = v => v != null ? `${v >= 0 ? '+' : ''}${(v * 100).toFixed(1)}pp` : '—';

  const isStdFcf    = rdcf.model_type === 'standard_fcf';
  const isBiotech   = rdcf.model_type === 'biotech_revenue';
  const impliedG    = isStdFcf ? rdcf.implied_fcf_growth : rdcf.implied_rev_growth;
  const ourG        = isStdFcf ? rdcf.our_fcf_growth     : rdcf.our_rev_growth;
  const gLabel      = isStdFcf ? L('FCF Growth','FCF增速') : L('Revenue Growth','营收增速');
  const baseLabel   = isStdFcf ? L('Base FCF','基准FCF') : L('Base Revenue','基准营收');
  const baseVal     = isStdFcf ? rdcf.fcf0 : rdcf.rev0;

  const fmtBig = v => {
    if (v == null) return '—';
    const abs = Math.abs(v);
    if (abs >= 1e12) return `${curr}${(v/1e12).toFixed(2)}T`;
    if (abs >= 1e9)  return `${curr}${(v/1e9).toFixed(1)}B`;
    if (abs >= 1e6)  return `${curr}${(v/1e6).toFixed(0)}M`;
    return `${curr}${v.toFixed(0)}`;
  };

  const w = rdcf.wacc_detail || {};

  return (
    <Card title={L('Reverse DCF · Expectation Gap','反向DCF · 市场预期差')}
          sub={L('What growth rate is the market pricing in?','市场定价隐含的增速是多少？')}
          open={open?.rdcf !== false} onToggle={toggle ? ()=>toggle('rdcf') : undefined} C={C}>

      {/* Error state */}
      {err && (
        <div style={{padding:'12px 14px', background:`${C.gold}10`, border:`1px solid ${C.gold}40`, borderRadius:7, fontSize:11}}>
          <div style={{color:C.gold, fontWeight:700, marginBottom:6}}>
            ⚠ {err === 'bisection_no_root'
              ? L('Hyper-growth stock — market implies >95% annual FCF growth','超高增速股票 — 市场隐含年FCF增速>95%')
              : L('RDCF unavailable: ','反向DCF不可用：') + err}
          </div>
          {err === 'bisection_no_root' && rdcf.bisect_debug && (
            <div style={{fontSize:9, color:C.mid, marginBottom:4}}>
              {L('Bisection bounds: obj(lo)=','二分法边界：obj(lo)=')}{(rdcf.bisect_debug.obj_lo/1e9).toFixed(0)}B
              {' · obj(hi)='}{(rdcf.bisect_debug.obj_hi/1e9).toFixed(0)}B
              {rdcf.bisect_debug.obj_hi < 0 && L(' — root above upper bound, implied g >200% p.a.',' — 根在上界之外，隐含增速>200%')}
            </div>
          )}
          {rdcf.wacc_detail && (
            <div style={{fontSize:9, color:C.mid}}>
              WACC {((rdcf.wacc_detail.wacc||0)*100).toFixed(1)}% · β {rdcf.wacc_detail.beta?.toFixed(2)}
              {' · '}{L('Data will correct after next fetch-data run','下次数据抓取后自动修正')}
            </div>
          )}
        </div>
      )}

      {!err && (
        <>
          {/* Signal banner */}
          <div style={{padding:'10px 16px', background:`${signalColor}12`, border:`1px solid ${signalColor}35`, borderRadius:7, marginBottom:14, display:'flex', alignItems:'center', justifyContent:'space-between'}}>
            <div style={{display:'flex', alignItems:'center', gap:8, flexWrap:'wrap'}}>
              <span style={{fontSize:13, fontWeight:800, color:signalColor, letterSpacing:'0.04em'}}>{signalLabel}</span>
              {rdcf.hyper_growth && (
                <span style={{fontSize:9, fontWeight:700, color:'#fff', background:C.gold, borderRadius:4, padding:'2px 6px', letterSpacing:'0.05em'}}>
                  {L('HYPER-GROWTH','超高增速')}
                </span>
              )}
              <span style={{fontSize:10, color:C.mid}}>
                {L('Gap Score: ','预期差得分: ')}<b style={{color:signalColor}}>{egapDisplay}</b>/100
              </span>
            </div>
            <div style={{fontSize:9, color:C.mid}}>{L('δ = our − implied','δ = 我们 − 市场')}: <b style={{color:signalColor}}>{fmtDelta(rdcf.delta)}</b></div>
          </div>

          {/* Core metrics */}
          <div style={{display:'grid', gridTemplateColumns:'repeat(3, 1fr)', gap:10, marginBottom:14}}>
            <MetricBox
              label={`${L('Market-Implied','市场隐含')} ${gLabel}`}
              value={fmtPct(impliedG)}
              sub={L('What market prices in','市场定价隐含')}
              color={C.mid} C={C}
            />
            <MetricBox
              label={`${L('Our View','我们预测')} ${gLabel}`}
              value={fmtPct(ourG)}
              sub={L('Our base case','我方基准预测')}
              color={ourG > impliedG ? C.green : C.red} C={C}
            />
            <MetricBox
              label={L('Expectation Gap (δ)','预期差 (δ)')}
              value={fmtDelta(rdcf.delta)}
              sub={`${L('Gap Score','预期差得分')}: ${egapDisplay}/100`}
              color={signalColor} C={C}
            />
          </div>

          {/* Secondary metrics */}
          <div style={{display:'grid', gridTemplateColumns:'repeat(4, 1fr)', gap:8, marginBottom:14}}>
            <MetricBox label={L('WACC','加权平均资本成本')} value={fmtPct(w.wacc)} sub={`β=${(w.beta||'—')}`} color={C.blue} C={C}/>
            <MetricBox label={baseLabel} value={fmtBig(baseVal)} sub={isStdFcf ? (rdcf.fcf_note || '') : `${L('Prof offset: ','盈利年差: ')}${rdcf.profitability_offset}yr`} color={C.mid} C={C}/>
            <MetricBox label={L('Market Cap','市值')} value={fmtBig(rdcf.market_cap)} sub="" color={C.mid} C={C}/>
            <MetricBox label={L('Net Debt','净债务')} value={fmtBig(rdcf.net_debt)} sub={rdcf.net_debt > 0 ? L('debt net','净负债') : L('net cash','净现金')} color={rdcf.net_debt > 0 ? C.red : C.green} C={C}/>
          </div>

          {/* WACC breakdown */}
          <div style={{padding:'8px 12px', background:`${C.blue}08`, border:`1px solid ${C.blue}20`, borderRadius:6, fontSize:10, color:C.mid}}>
            <b style={{color:C.blue}}>WACC</b> = rf {fmtPct(w.rf)} + β({(w.beta||'—')}) × ERP {fmtPct(w.erp)} = <b style={{color:C.blue}}>{fmtPct(w.wacc)}</b>
            <span style={{marginLeft:10, fontSize:9}}>({w.beta_source || '—'})</span>
          </div>

          {/* Model note */}
          <div style={{marginTop:8, fontSize:9, color:C.mid, lineHeight:1.6}}>
            {isBiotech && <span>🧬 {L('Biotech model: revenue CAGR → FCF via ','生物科技模型：营收CAGR → 终态FCF利润率 ')}{fmtPct(rdcf.terminal_fcf_margin)}</span>}
            {isStdFcf  && <span>📊 {L('Standard FCF model · 5Y horizon · terminal g = ','标准FCF模型 · 5年预测期 · 终态增速 ')}{fmtPct(w?.erp ? rdcf.market_cap : null) || '2.5%'}</span>}
            <span style={{float:'right', fontSize:8}}>{L('Generated: ','生成: ')}{rdcf.generated_at?.slice(0,10) || '—'}</span>
          </div>
        </>
      )}
    </Card>
  );
}

/* ── MULTI-AGENT DEBATE PANEL ─────────────────────────────────────────── */
function DebatePanel({ ticker, company, C, L, lk }) {
  const [loading, setLoading] = useState(false);
  const [result,  setResult]  = useState(null);
  const [error,   setError]   = useState(null);
  const [context, setContext] = useState('');

  const ROLE_CFG = {
    BULL:     { label:'Bull',     color:C.green, model:'Gemini 1.5 Pro',   icon:'⬆' },
    BEAR:     { label:'Bear',     color:C.red,   model:'GPT-4o',           icon:'⬇' },
    FORENSIC: { label:'Forensic', color:C.gold,  model:'Claude Sonnet',    icon:'🔍' },
  };

  const VERDICT_COLOR = (v, C) => {
    if (!v) return C.mid;
    if (['STRONG_BULL','BULL','CLEAN'].includes(v)) return C.green;
    if (['STRONG_BEAR','BEAR','RED_FLAG'].includes(v)) return C.red;
    if (v === 'CAUTION') return C.gold;
    return C.mid;
  };

  const runDebate = async () => {
    if (!ticker) return;
    setLoading(true); setError(null); setResult(null);
    const isGHPages = typeof window !== 'undefined' && window.location.hostname.endsWith('github.io');
    const base = isGHPages ? 'https://equity-research-ten.vercel.app' : '';
    try {
      const res = await fetch(`${base}/api/debate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticker, company, context: context || undefined }),
      });
      const text = await res.text();
      let json;
      try { json = JSON.parse(text); } catch { throw new Error(`[${res.status}] ${text.slice(0,200)}`); }
      if (!res.ok) throw new Error(json.error || `HTTP ${res.status}`);
      setResult(json);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const AnalystCard = ({ role, data }) => {
    const cfg = ROLE_CFG[role] || {};
    if (!data) return null;
    if (data.error) return (
      <div style={{flex:1, padding:14, background:C.soft, borderRadius:8, border:`1px solid ${C.border}`}}>
        <div style={{fontSize:10, fontWeight:700, color:cfg.color}}>{cfg.icon} {cfg.label} · {cfg.model}</div>
        <div style={{fontSize:10, color:C.red, marginTop:6}}>Failed: {data.error}</div>
      </div>
    );
    const vc = VERDICT_COLOR(data.verdict, C);
    return (
      <div style={{flex:1, background:C.card, borderRadius:10, border:`1px solid ${C.border}`,
                   boxShadow:SHADOW_SM, overflow:'hidden', minWidth:0}}>
        {/* Header */}
        <div style={{padding:'10px 14px', background:`${cfg.color}10`,
                     borderBottom:`1px solid ${C.border}`}}>
          <div style={{display:'flex', justifyContent:'space-between', alignItems:'center'}}>
            <div>
              <span style={{fontSize:13, fontWeight:700, color:cfg.color}}>{cfg.icon} {cfg.label}</span>
              <span style={{fontSize:9, color:C.mid, marginLeft:8}}>{cfg.model}</span>
            </div>
            <span style={{...S.tag(vc), fontSize:9}}>{data.verdict}</span>
          </div>
          <div style={{fontSize:11, color:C.dark, marginTop:6, lineHeight:1.5}}>{data.headline}</div>
        </div>
        {/* Arguments */}
        <div style={{padding:'10px 14px'}}>
          {(data.top_arguments||[]).map((a,i) => {
            const sc = a.strength==='HIGH' ? C.red : a.strength==='MED' ? C.gold : C.mid;
            return (
              <div key={i} style={{marginBottom:8, paddingBottom:8,
                                   borderBottom:i<(data.top_arguments.length-1)?`1px solid ${C.border}`:'none'}}>
                <div style={{display:'flex', gap:6, alignItems:'flex-start'}}>
                  <span style={{...S.tag(sc), fontSize:7, flexShrink:0, marginTop:1}}>{a.strength}</span>
                  <div>
                    <div style={{fontSize:11, fontWeight:600, color:C.dark}}>{a.point}</div>
                    <div style={{fontSize:9, color:C.mid, marginTop:2, lineHeight:1.4}}>{a.evidence}</div>
                  </div>
                </div>
              </div>
            );
          })}
          {data.key_number && (
            <div style={{padding:'6px 10px', background:`${cfg.color}08`, borderRadius:5,
                         fontSize:11, fontWeight:600, color:cfg.color, marginTop:4}}>
              📊 {data.key_number}
            </div>
          )}
          {data.killer_question && (
            <div style={{marginTop:8, fontSize:10, color:C.mid, fontStyle:'italic', lineHeight:1.5}}>
              ❓ {data.killer_question}
            </div>
          )}
        </div>
      </div>
    );
  };

  return (
    <div>
      {/* Trigger */}
      {!result && (
        <div style={{marginBottom:14}}>
          <div style={{fontSize:10, color:C.mid, marginBottom:6}}>
            {L('Research context (optional — same as Deep Research)','研究背景（选填）')}
          </div>
          <textarea value={context} onChange={e=>setContext(e.target.value)}
            placeholder={L('e.g. Q1 earnings beat, checking if thesis holds','如：Q1财报超预期，验证论点是否成立')}
            rows={2} disabled={loading}
            style={{width:'100%', padding:'7px 10px', border:`1px solid ${C.border}`, borderRadius:6,
                    fontSize:11, background:C.soft, color:C.dark, outline:'none',
                    resize:'none', fontFamily:'inherit', boxSizing:'border-box'}}/>
          <button onClick={runDebate} disabled={loading || !ticker} style={{
            marginTop:8, width:'100%', padding:'10px 0', border:'none', borderRadius:8,
            background: loading ? C.soft : `linear-gradient(135deg, ${C.green}, ${C.blue})`,
            color: loading ? C.mid : '#fff', fontSize:12, fontWeight:700,
            cursor: loading ? 'wait' : 'pointer',
          }}>
            {loading
              ? L('Running debate — 3 analysts working in parallel (~30s)…',
                  '辩论进行中 — 3个AI分析师并行工作（约30秒）…')
              : `${L('Start Debate','开始辩论')} · ${ticker}${company ? ` · ${company}` : ''}`}
          </button>
          {loading && (
            <div style={{marginTop:10, display:'flex', gap:8, justifyContent:'center',
                         fontSize:10, color:C.mid}}>
              <span style={{color:C.green}}>⬆ Gemini · Bull</span>
              <span style={{color:C.mid}}>·</span>
              <span style={{color:C.red}}>⬇ GPT-4o · Bear</span>
              <span style={{color:C.mid}}>·</span>
              <span style={{color:C.gold}}>🔍 Claude · Forensic</span>
            </div>
          )}
        </div>
      )}

      {error && (
        <div style={{padding:12, background:`${C.red}10`, border:`1px solid ${C.red}25`,
                     borderRadius:8, fontSize:11, color:C.red, marginBottom:12}}>
          {error}
        </div>
      )}

      {result && (
        <div>
          {/* Three analyst columns */}
          <div style={{display:'flex', gap:10, marginBottom:14, flexWrap:'wrap'}}>
            <AnalystCard role="BULL"     data={result.analysts?.bull}/>
            <AnalystCard role="BEAR"     data={result.analysts?.bear}/>
            <AnalystCard role="FORENSIC" data={result.analysts?.forensic}/>
          </div>

          {/* Synthesis */}
          {result.synthesis && (() => {
            const s = result.synthesis;
            const bc = s.balance==='BULL' ? C.green : s.balance==='BEAR' ? C.red : C.gold;
            return (
              <div style={{background:C.card, borderRadius:10, border:`2px solid ${bc}40`,
                           boxShadow:SHADOW, overflow:'hidden'}}>
                <div style={{padding:'12px 16px', background:`${bc}08`, borderBottom:`1px solid ${bc}30`,
                             display:'flex', justifyContent:'space-between', alignItems:'center'}}>
                  <span style={{fontSize:14, fontWeight:800, color:bc}}>
                    ⚖ {L('CIO Synthesis','首席投资官综合判断')} · {s.balance}
                  </span>
                  <span style={{fontSize:11, color:C.mid}}>
                    {L('Conviction','置信度')} {s.conviction}/100
                  </span>
                </div>
                <div style={{padding:'14px 16px'}}>
                  <p style={{fontSize:12, color:C.dark, lineHeight:1.7, marginBottom:12}}>{s.summary}</p>

                  <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:10, marginBottom:12}}>
                    {s.agreements?.length > 0 && (
                      <div>
                        <div style={{...S.label, color:C.green, marginBottom:6}}>
                          ✓ {L('All analysts agree','三方共识')}
                        </div>
                        {s.agreements.map((a,i) => (
                          <div key={i} style={{fontSize:10, color:C.dark, marginBottom:4,
                                               paddingLeft:10, borderLeft:`2px solid ${C.green}`}}>
                            {a}
                          </div>
                        ))}
                      </div>
                    )}
                    {s.disagreements?.length > 0 && (
                      <div>
                        <div style={{...S.label, color:C.red, marginBottom:6}}>
                          ✗ {L('Unresolved tensions','未解争议')}
                        </div>
                        {s.disagreements.map((d,i) => (
                          <div key={i} style={{fontSize:10, color:C.dark, marginBottom:4,
                                               paddingLeft:10, borderLeft:`2px solid ${C.red}`}}>
                            {d}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {s.decisive_factor && (
                    <div style={{padding:'10px 14px', background:`${bc}10`,
                                 border:`1px solid ${bc}30`, borderRadius:7, marginBottom:10}}>
                      <div style={{...S.label, color:bc, marginBottom:4}}>
                        🎯 {L('Decisive factor','决定性因素')}
                      </div>
                      <div style={{fontSize:11, color:C.dark, fontWeight:600}}>{s.decisive_factor}</div>
                    </div>
                  )}

                  {s.must_monitor?.length > 0 && (
                    <div>
                      <div style={{...S.label, color:C.mid, marginBottom:6}}>
                        📌 {L('Monitor in next 90 days','未来90天监控项')}
                      </div>
                      {s.must_monitor.map((m,i) => (
                        <div key={i} style={{fontSize:10, color:C.mid, marginBottom:3,
                                             display:'flex', gap:6}}>
                          <span style={{color:C.blue, flexShrink:0}}>→</span>{m}
                        </div>
                      ))}
                    </div>
                  )}

                  {s.action && (
                    <div style={{marginTop:12, padding:'10px 14px', background:C.soft,
                                 borderRadius:7, fontSize:11, color:C.dark, lineHeight:1.6,
                                 fontStyle:'italic'}}>
                      {s.action}
                    </div>
                  )}
                </div>
              </div>
            );
          })()}

          <button onClick={()=>{setResult(null);setError(null);}}
            style={{marginTop:10, padding:'6px 14px', border:`1px solid ${C.border}`,
                    background:'transparent', borderRadius:6, color:C.mid,
                    cursor:'pointer', fontSize:10}}>
            {L('Run new debate','重新辩论')}
          </button>
        </div>
      )}
    </div>
  );
}

/* ── BACKTEST PANEL ───────────────────────────────────────────────────── */
function BacktestPanel({ L, C }) {
  const [bt, setBt] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const base = DATA_BASE;
    fetch(base + 'data/backtest_results.json')
      .then(r => { if (!r.ok) throw new Error(); return r.json(); })
      .then(d => { setBt(d); setLoading(false); })
      .catch(() => { setBt(null); setLoading(false); });
  }, []);

  if (loading) return (
    <div style={{padding:32, textAlign:'center', color:C.mid, fontSize:12}}>
      Loading backtest results...
    </div>
  );

  if (!bt || bt.status === 'insufficient_data') {
    const reason = bt?.reason || 'no_data';
    const daysAvail = bt?.days_available ?? 0;
    const daysReq   = bt?.days_required ?? 60;
    return (
      <div style={{padding:24, textAlign:'center'}}>
        <div style={{fontSize:22, marginBottom:8}}>📊</div>
        <div style={{fontSize:13, fontWeight:700, color:C.dark, marginBottom:6}}>
          {L('Backtest: Insufficient History','回测：历史数据不足')}
        </div>
        <div style={{fontSize:11, color:C.mid, maxWidth:420, margin:'0 auto', lineHeight:1.7}}>
          {reason === 'no_ohlcv_data'
            ? L('No OHLCV files found in public/data/. Run fetch_data.py first.',
                '未找到 OHLCV 数据文件。请先运行 fetch_data.py。')
            : L(`${daysAvail} days of price history available — need ${daysReq}+ to begin backtesting. Keep running daily fetches.`,
                `当前价格历史 ${daysAvail} 天，需要 ${daysReq}+ 天才能开始回测。请继续每日抓取数据。`)}
        </div>
        <div style={{marginTop:16, padding:'10px 14px', background:`${C.blue}08`, border:`1px solid ${C.blue}25`, borderRadius:8, fontSize:10, color:C.mid, display:'inline-block', textAlign:'left'}}>
          <div style={{fontWeight:700, color:C.blue, marginBottom:4}}>{L('Config','配置')}</div>
          <div>VP threshold: <b>{bt?.config?.vp_threshold ?? 60}</b></div>
          <div>Forward window: <b>{bt?.config?.forward_days ?? 20} trading days</b></div>
          <div>Benchmark: <b>{bt?.config?.benchmark ?? 'CSI 300'}</b></div>
        </div>
      </div>
    );
  }

  const s     = bt.summary || {};
  const cfg   = bt.config  || {};
  const nav   = bt.nav_series || [];
  const log   = bt.period_log || [];

  const excess = (s.annualised_return_pct ?? 0) - (s.benchmark_return_pct ?? 0);
  const excessColor = excess >= 0 ? C.green : C.red;
  const alphaColor  = (s.alpha_annual_pct ?? 0) >= 0 ? C.green : C.red;

  const KPI = ({ label, val, sub, color }) => (
    <div style={{padding:'12px 14px', background:C.card, border:`1px solid ${C.border}`, borderRadius:8, minWidth:110}}>
      <div style={{fontSize:10, color:C.mid, marginBottom:3}}>{label}</div>
      <div style={{fontSize:18, fontWeight:800, fontFamily:'monospace', color: color || C.dark}}>{val}</div>
      {sub && <div style={{fontSize:9, color:C.mid, marginTop:2}}>{sub}</div>}
    </div>
  );

  // CI display
  const ciLo = s.bootstrap_ci_lo_pct ?? 0;
  const ciHi = s.bootstrap_ci_hi_pct ?? 0;
  const ciColor = ciLo > 0 ? C.green : ciHi < 0 ? C.red : C.gold;

  // NAV chart: format date for tooltip
  const navForChart = nav.map(d => ({
    ...d,
    dateShort: d.date?.slice(5), // "MM-DD"
  }));

  return (
    <div>
      {/* Header */}
      <div style={{marginBottom:14, display:'flex', justifyContent:'space-between', alignItems:'flex-start', flexWrap:'wrap', gap:8}}>
        <div>
          <div style={{fontSize:14, fontWeight:800, color:C.dark}}>{L('VP Score Strategy Backtest','VP评分策略回测')}</div>
          <div style={{fontSize:10, color:C.mid, marginTop:2}}>
            {L('Monthly rebalance · Equal-weight · VP ≥ ','月度调仓·等权·VP ≥ ')}<b>{cfg.vp_threshold}</b>
            {' · '}{L('Benchmark: ','基准: ')}<b>{cfg.benchmark}</b>
            {' · '}{L('Fwd window: ','前瞻窗口: ')}<b>{cfg.forward_days} {L('trading days','交易日')}</b>
            {' · '}{s.periods} {L('periods','期')}
            {' · '}{bt.as_of}
          </div>
        </div>
        <div style={{fontSize:9, color:C.mid, padding:'4px 8px', background:`${C.blue}08`, border:`1px solid ${C.blue}20`, borderRadius:5}}>
          {L('bootstrap CI 95%','自举置信区间 95%')}: [{ciLo >= 0 ? '+' : ''}{ciLo.toFixed(1)}%, {ciHi >= 0 ? '+' : ''}{ciHi.toFixed(1)}%]
          <span style={{marginLeft:6, width:8, height:8, borderRadius:'50%', background:ciColor, display:'inline-block', verticalAlign:'middle'}}/>
        </div>
      </div>

      {/* KPI grid */}
      <div style={{display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(120px, 1fr))', gap:10, marginBottom:16}}>
        <KPI label={L('Ann. Return (Port)','年化收益(组合)')} val={(s.annualised_return_pct ?? 0).toFixed(1) + '%'} color={(s.annualised_return_pct ?? 0) >= 0 ? C.green : C.red}/>
        <KPI label={L('Ann. Return (Bench)','年化收益(基准)')} val={(s.benchmark_return_pct ?? 0).toFixed(1) + '%'} color={C.mid}/>
        <KPI label={L('Excess Return','超额收益')} val={(excess >= 0 ? '+' : '') + excess.toFixed(1) + '%'} color={excessColor}/>
        <KPI label={L('Jensen Alpha (ann)','詹森阿尔法(年)')} val={(s.alpha_annual_pct >= 0 ? '+' : '') + (s.alpha_annual_pct ?? 0).toFixed(1) + '%'} color={alphaColor}/>
        <KPI label="Beta" val={(s.beta ?? 1).toFixed(2)} sub={L('vs benchmark','相对基准')}/>
        <KPI label={L('Sharpe (Port)','夏普率(组合)')} val={(s.sharpe_ratio ?? 0).toFixed(2)} color={(s.sharpe_ratio ?? 0) > 0.5 ? C.green : C.mid}/>
        <KPI label={L('Max Drawdown','最大回撤')} val={'-' + Math.abs(s.max_drawdown_pct ?? 0).toFixed(1) + '%'} color={C.red}/>
        <KPI label={L('Excess Hit Rate','超额胜率')} val={(s.hit_rate_pct ?? 0).toFixed(1) + '%'} color={(s.hit_rate_pct ?? 0) >= 50 ? C.green : C.red}/>
        <KPI label={L('Cumulative','累计收益')} val={(s.cumulative_return_pct >= 0 ? '+' : '') + (s.cumulative_return_pct ?? 0).toFixed(1) + '%'} color={(s.cumulative_return_pct ?? 0) >= 0 ? C.green : C.red}/>
      </div>

      {/* NAV Chart */}
      {navForChart.length > 1 && (
        <div style={{marginBottom:16, padding:14, background:C.card, border:`1px solid ${C.border}`, borderRadius:8}}>
          <div style={{fontSize:11, fontWeight:700, color:C.dark, marginBottom:10}}>
            {L('Cumulative NAV (inception = 1.00)','累计净值（起始 = 1.00）')}
          </div>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={navForChart} margin={{top:5, right:20, left:0, bottom:5}}>
              <XAxis dataKey="dateShort" tick={{fontSize:9, fill:C.mid}} tickLine={false} interval="preserveStartEnd"/>
              <YAxis tick={{fontSize:9, fill:C.mid}} tickLine={false} axisLine={false} tickFormatter={v => v.toFixed(2)} domain={['auto','auto']}/>
              <Tooltip
                contentStyle={{background:C.card, border:`1px solid ${C.border}`, borderRadius:6, fontSize:10}}
                formatter={(val, name) => [val.toFixed(4), name === 'portfolio' ? L('Portfolio','组合') : L('Benchmark','基准')]}
                labelFormatter={l => l}
              />
              <ReferenceLine y={1} stroke={C.mid} strokeDasharray="3 3" strokeWidth={1}/>
              <Line type="monotone" dataKey="portfolio" stroke={C.blue} strokeWidth={2} dot={false} name="portfolio"/>
              <Line type="monotone" dataKey="benchmark" stroke={C.mid}  strokeWidth={1.5} dot={false} name="benchmark" strokeDasharray="4 2"/>
            </LineChart>
          </ResponsiveContainer>
          <div style={{display:'flex', gap:16, fontSize:9, color:C.mid, justifyContent:'center', marginTop:4}}>
            <span><span style={{display:'inline-block', width:20, height:2, background:C.blue, verticalAlign:'middle', marginRight:4}}/>
              {`${L('Portfolio','组合')} (VP\u2265${cfg.vp_threshold})`}</span>
            <span><span style={{display:'inline-block', width:20, height:1, background:C.mid, verticalAlign:'middle', marginRight:4, borderTop:`1px dashed ${C.mid}`}}/>
              {cfg.benchmark}</span>
          </div>
        </div>
      )}

      {/* Period Log */}
      {log.length > 0 && (
        <div style={{marginBottom:16}}>
          <div style={{fontSize:11, fontWeight:700, color:C.dark, marginBottom:8}}>
            {L('Period Log (last 24 rebalances)','期间记录（最近24次调仓）')}
          </div>
          <div style={{overflowX:'auto', borderRadius:6, border:`1px solid ${C.border}`}}>
            <table style={{width:'100%', fontSize:10, borderCollapse:'collapse'}}>
              <thead><tr style={{background:C.soft}}>
                {[L('Date','日期'), L('Positions','持仓数'), L('Port Ret%','组合收益%'), L('Bench Ret%','基准收益%'), L('Excess%','超额%'), L('Cash','现金')].map((h,i) => (
                  <th key={i} style={{padding:'6px 10px', textAlign: i === 0 ? 'left' : 'right', color:C.mid, fontWeight:600, borderBottom:`1px solid ${C.border}`, fontSize:9}}>{h}</th>
                ))}
              </tr></thead>
              <tbody>
                {log.slice().reverse().map((p, i) => {
                  const ec = (p.excess_return ?? 0) >= 0 ? C.green : C.red;
                  const pc = (p.portfolio_return ?? 0) >= 0 ? C.green : C.red;
                  return (
                    <tr key={i} style={{borderBottom:`1px solid ${C.border}`, opacity: p.cash ? 0.6 : 1}}>
                      <td style={{padding:'6px 10px', fontFamily:'monospace', color:C.mid}}>{p.date}</td>
                      <td style={{padding:'6px 10px', textAlign:'right', fontFamily:'monospace', color:C.dark}}>{p.cash ? '—' : (p.num_positions ?? (p.selected?.length ?? 0))}</td>
                      <td style={{padding:'6px 10px', textAlign:'right', fontFamily:'monospace', fontWeight:700, color:pc}}>{p.cash ? '0.00' : (p.portfolio_return ?? 0).toFixed(2)}%</td>
                      <td style={{padding:'6px 10px', textAlign:'right', fontFamily:'monospace', color:C.mid}}>{(p.benchmark_return ?? 0).toFixed(2)}%</td>
                      <td style={{padding:'6px 10px', textAlign:'right', fontFamily:'monospace', fontWeight:700, color:ec}}>{p.cash ? '' : ((p.excess_return ?? 0) >= 0 ? '+' : '')}{(p.excess_return ?? 0).toFixed(2)}%</td>
                      <td style={{padding:'6px 10px', textAlign:'right', color:C.mid}}>{p.cash ? '✓' : ''}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Disclaimer */}
      <div style={{padding:'8px 12px', background:`${C.gold}08`, border:`1px solid ${C.gold}20`, borderRadius:6, fontSize:9, color:C.mid, lineHeight:1.6}}>
        ⚠️ {L(
          'Backtest uses point-in-time VP snapshots from vp_snapshot.json. ' +
          'Short history (< 1 year) means results lack statistical significance. ' +
          'Bootstrap CI reflects monthly excess-return variance only. ' +
          'Past signal performance does not imply future alpha.',
          '回测使用 vp_snapshot.json 中的时点 VP 快照。历史不足 1 年时结果缺乏统计显著性。' +
          '自举置信区间仅反映月度超额收益的方差。过去信号表现不代表未来超额收益。'
        )}
      </div>
    </div>
  );
}

/* ── DATA FRESHNESS BADGE ──────────────────────────────────────────────── */
const DataBadge = ({ liveData, C, L }) => {
  if (!liveData) return (
    <div style={{display:'flex', alignItems:'center', gap:4, fontSize:9, color:C.mid, padding:'3px 8px', borderRadius:4, background:`${C.red}10`, border:`1px solid ${C.red}30`}}>
      <WifiOff size={10}/> {L('Offline','离线')}
    </div>
  );
  const fetchedAt = liveData?._meta?.fetched_at;
  if (!fetchedAt) return null;
  const age = (Date.now() - new Date(fetchedAt).getTime()) / (1000*60*60);
  const stale = age > 24;
  const color = stale ? C.gold : C.green;
  const label = age < 1 ? L('Live','实时') : age < 24 ? Math.round(age) + L('h ago','小时前') : Math.round(age/24) + L('d ago','天前');
  return (
    <div style={{display:'flex', alignItems:'center', gap:4, fontSize:9, color, padding:'3px 8px', borderRadius:4, background:`${color}10`, border:`1px solid ${color}30`, cursor:'default'}}
         title={L('Data fetched: ','数据更新: ') + new Date(fetchedAt).toLocaleString()}>
      <Wifi size={10}/> {label}
    </div>
  );
};

/* ── DASHBOARD ────────────────────────────────────────────────────────────── */
/* ── Jason: Bloomberg-grade Global Styles ───────────────────────────────────
   Injects: custom scrollbars · @keyframes · tabular-nums · font loading
   Keep this component mounted at all times (rendered at root of Dashboard).
────────────────────────────────────────────────────────────────────────── */
const GlobalStyles = () => (
  <style>{`
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Inter:wght@400;500;600;700&display=swap');

    *, *::before, *::after { box-sizing: border-box; }
    body { margin: 0; padding: 0; }

    /* Bloomberg-style slim scrollbars */
    ::-webkit-scrollbar { width: 5px; height: 5px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: #1A3050; border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: #2A4570; }
    ::-webkit-scrollbar-corner { background: transparent; }

    /* Skeleton shimmer animation */
    @keyframes shimmer {
      0%   { background-position: 200% 0; }
      100% { background-position: -200% 0; }
    }

    /* Market pulse ticker scroll */
    @keyframes ticker-scroll {
      0%   { transform: translateX(0); }
      100% { transform: translateX(-50%); }
    }

    /* Status dot blink */
    @keyframes blink {
      0%, 100% { opacity: 1; }
      50%       { opacity: 0.3; }
    }

    /* Pulse — used by skeleton loaders + PulseCard dots */
    @keyframes pulse {
      0%, 100% { opacity: 1; }
      50%      { opacity: 0.35; }
    }

    /* Subtle fade-in for cards */
    @keyframes fadeUp {
      from { opacity: 0; transform: translateY(6px); }
      to   { opacity: 1; transform: translateY(0); }
    }

    /* Tabular numbers everywhere — critical for financial data alignment */
    .ar-num {
      font-variant-numeric: tabular-nums;
      font-feature-settings: "tnum";
      font-family: 'JetBrains Mono', 'Courier New', monospace;
    }

    /* Ticker bar — pause on hover */
    .ar-ticker-track:hover { animation-play-state: paused !important; }
  `}</style>
);

export default function Dashboard() {
  const [lang, setLang] = useState('en');
  const [dark, setDark] = useState(true); // Jason: Bloomberg default — dark mode
  const [tab, setTab] = useState('browse');  // 2026-05-02: 'browse' is the new entry point per Junyan's "first interface clean" brief
  const [ticker, setTicker] = useState(null);
  const [search, setSearch] = useState('');
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [open, setOpen] = useState({factors:true, funnel:true, pairs:false, macro:true, macroImpact:true, leading:true, biz:true, variant:true, vp:true, cats:true, risks:false, fin:false, consensus:true, ta:true, kline:true, statements:false, company:false, actions:true, rdcf:true, debate:false, regime:true, exclusiveInsight:true, newsPanel:true});
  const [dynamicStocks, setDynamicStocks] = useState({});
  const [showDeepResearch, setShowDeepResearch] = useState(false);
  const [liveData, setLiveData] = useState(null);
  const [universeA, setUniverseA] = useState(null);
  const [universeHK, setUniverseHK] = useState(null);
  const [eqrData, setEqrData]     = useState({});
  const [rdcfData, setRdcfData]   = useState({});
  const [stressData, setStressData] = useState(null);
  const [predictions, setPredictions] = useState([]);
  const [regimeData, setRegimeData] = useState(null);
  const [macroInsight, setMacroInsight] = useState(null);
  const [insightLoading, setInsightLoading] = useState(false);
  const [newsArticles, setNewsArticles] = useState([]);
  const [newsMacro, setNewsMacro] = useState([]);
  const [newsPortfolio, setNewsPortfolio] = useState([]);
  const [newsLoading, setNewsLoading] = useState(false);
  const [newsLastFetched, setNewsLastFetched] = useState(null);
  const [selectedArticle, setSelectedArticle] = useState(null);
  const [chatMessages, setChatMessages] = useState([]);
  const [chatInput, setChatInput] = useState('');
  // Pulse state: { [ticker]: { ...pulseResult } }
  const [pulseData, setPulseData] = useState({});
  const [pulseLoading, setPulseLoading] = useState({});
  // Morning report state
  const [morningReport, setMorningReport] = useState(() => {
    try {
      const today = new Date().toISOString().slice(0, 10);
      const cached = localStorage.getItem(`ar_morning_report_${today}`);
      return cached ? JSON.parse(cached) : null;
    } catch { return null; }
  });
  const [morningReportLoading, setMorningReportLoading] = useState(false);
  const [chatLoading, setChatLoading] = useState(false);
  const [vpScores, setVpScores] = useState({});   // { ticker: vp_score } from vp_snapshot.json
  // KR6: separate state for canonical piecewise expectation_gap from
  // vp_snapshot. Separate from vpScores to avoid migration risk on the
  // existing flat `{ticker: number}` shape used by Scanner. vp_engine.py
  // is the SINGLE owner of the delta→score piecewise mapping (per CLAUDE.md);
  // Dashboard reads results, never recomputes.
  const [egapScores, setEgapScores] = useState({});  // { ticker: expectation_gap }
  const [scissorsData, setScissorsData] = useState({});  // profit_scissors.json tickers dict
  const [liData, setLiData]             = useState({});  // leading_indicators.json
  // Jason: Live clock for Bloomberg-style terminal header
  const [nowTime, setNowTime] = useState(new Date());
  useEffect(() => {
    const t = setInterval(() => setNowTime(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  /* Fetch prediction log on mount */
  useEffect(() => {
    const base = DATA_BASE;
    fetch(base + 'data/prediction_log.json')
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d?.predictions) setPredictions(d.predictions); })
      .catch(() => {});
  }, []);

  /* Fetch EQR ratings on mount */
  useEffect(() => {
    const base = DATA_BASE;
    const ids = ['300308_SZ','700_HK','9999_HK','6160_HK','002594_SZ'];
    Promise.all(
      ids.map(id =>
        fetch(base + `data/eqr_${id}.json`)
          .then(r => r.ok ? r.json() : null)
          .catch(() => null)
      )
    ).then(results => {
      const map = {};
      ids.forEach((id, i) => {
        if (results[i]) {
          // Convert safe_id back to ticker: 300308_SZ → 300308.SZ
          const lastUnderscore = id.lastIndexOf('_');
          const ticker = id.slice(0, lastUnderscore) + '.' + id.slice(lastUnderscore + 1);
          map[ticker] = results[i];
        }
      });
      setEqrData(map);
    });
  }, []);

  /* Fetch Reverse DCF data on mount */
  useEffect(() => {
    const base = DATA_BASE;
    const ids = ['300308_SZ','700_HK','9999_HK','6160_HK','002594_SZ'];
    Promise.all(
      ids.map(id =>
        fetch(base + `data/rdcf_${id}.json`)
          .then(r => r.ok ? r.json() : null)
          .catch(() => null)
      )
    ).then(results => {
      const map = {};
      ids.forEach((id, i) => {
        if (results[i]) {
          const lastUnderscore = id.lastIndexOf('_');
          const ticker = id.slice(0, lastUnderscore) + '.' + id.slice(lastUnderscore + 1);
          map[ticker] = results[i];
        }
      });
      setRdcfData(map);
    });
  }, []);

  /* Fetch swing signals on mount */
  const [signalsData, setSignalsData] = useState({});
  useEffect(() => {
    const base = DATA_BASE;
    const ids = ['300308_SZ','700_HK','9999_HK','6160_HK','002594_SZ'];
    Promise.all(
      ids.map(id =>
        fetch(base + `data/signals_${id}.json`)
          .then(r => r.ok ? r.json() : null)
          .catch(() => null)
      )
    ).then(results => {
      const map = {};
      results.forEach(d => { if (d?.ticker) map[d.ticker] = d; });
      setSignalsData(map);
    });
  }, []);

  /* Fetch profit scissors data on mount */
  useEffect(() => {
    const base = DATA_BASE;
    fetch(base + 'data/profit_scissors.json')
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d?.tickers) setScissorsData(d.tickers); })
      .catch(() => {});
  }, []);

  /* Fetch AI infrastructure leading indicators on mount */
  useEffect(() => {
    const base = DATA_BASE;
    fetch(base + 'data/leading_indicators.json')
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setLiData(d); })
      .catch(() => {});
  }, []);

  /* Fetch macro stress test data on mount */
  useEffect(() => {
    const base = DATA_BASE;
    fetch(base + 'data/stress_test.json')
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setStressData(d); })
      .catch(() => {});
  }, []);

  /* Fetch sector regime config on mount, then auto-generate first insight */
  useEffect(() => {
    const base = DATA_BASE;
    fetch(base + 'data/regime_config.json')
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (!d) return;
        setRegimeData(d);
        // Auto-generate insight immediately after regime data loads
        setInsightLoading(true);
        const apiBase = 'https://equity-research-ten.vercel.app';
        fetch(`${apiBase}/api/macro`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ regime_data: d }),
        })
          .then(r => r.ok ? r.json() : Promise.reject(`API ${r.status}`))
          .then(data => { setMacroInsight(data); setInsightLoading(false); })
          .catch(err => {
            setMacroInsight({
              insight: {
                market_reads_en: `Auto-load error: ${err}`,
                market_reads_zh: `自动加载错误：${err}`,
                we_think_en:'', we_think_zh:'',
                mechanism_en:'', mechanism_zh:'',
                implication_en:'', implication_zh:'',
                watch_for_en:'', watch_for_zh:'',
                confidence:'LOW', horizon:'N/A',
              },
              generated_at: new Date().toISOString(),
            });
            setInsightLoading(false);
          });
      })
      .catch(() => {});
  }, []);

  /* Auto-refresh insight every 30 minutes */
  useEffect(() => {
    const INTERVAL_MS = 30 * 60 * 1000;
    const timer = setInterval(() => {
      setRegimeData(prev => {
        if (!prev) return prev;
        setInsightLoading(true);
        const apiBase = 'https://equity-research-ten.vercel.app';
        fetch(`${apiBase}/api/macro`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ regime_data: prev }),
        })
          .then(r => r.ok ? r.json() : Promise.reject(`API ${r.status}`))
          .then(data => { setMacroInsight(data); setInsightLoading(false); })
          .catch(() => setInsightLoading(false));
        return prev;
      });
    }, INTERVAL_MS);
    return () => clearInterval(timer);
  }, []);

  /* Fetch news on mount, then poll every 3 minutes */
  useEffect(() => {
    const apiBase = 'https://equity-research-ten.vercel.app';
    let prevIds = new Set();

    const fetchNews = (regime) => {
      setNewsLoading(true);
      fetch(`${apiBase}/api/news?_cb=${Date.now()}`)
        .then(r => r.ok ? r.json() : Promise.reject(r.status))
        .then(data => {
          const macro     = data.macro     || [];
          const portfolio = data.portfolio || [];
          const articles  = data.articles  || [...macro, ...portfolio];
          setNewsArticles(articles);
          setNewsMacro(macro);
          setNewsPortfolio(portfolio);
          setNewsLastFetched(new Date());
          setNewsLoading(false);

          // Detect truly new articles since last fetch
          const newArrivals = articles.filter(a => !prevIds.has(a.id));
          prevIds = new Set(articles.map(a => a.id));

          // If new articles arrived AND we have regime data, refresh insight
          if (newArrivals.length > 0 && regime) {
            const newsCtx = articles.slice(0, 5).map(a =>
              `[${a.ticker}] ${a.title} (${new Date(a.published_at).toLocaleTimeString()})`
            ).join('\n');
            setInsightLoading(true);
            fetch(`${apiBase}/api/macro`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                regime_data: regime,
                macro_snapshot: { recent_news: newsCtx, updated_at: new Date().toISOString() },
              }),
            })
              .then(r => r.ok ? r.json() : Promise.reject(r.status))
              .then(d => { setMacroInsight(d); setInsightLoading(false); })
              .catch(() => setInsightLoading(false));
          }
        })
        .catch(() => setNewsLoading(false));
    };

    // First fetch — wait for regimeData to be available
    const bootTimer = setTimeout(() => {
      setRegimeData(rd => { fetchNews(rd); return rd; });
    }, 1500);

    const pollTimer = setInterval(() => {
      setRegimeData(rd => { fetchNews(rd); return rd; });
    }, 60 * 1000);   // 1-minute poll

    return () => { clearTimeout(bootTimer); clearInterval(pollTimer); };
  }, []);

  /* Fetch live market data + universe on mount */
  useEffect(() => {
    const base = DATA_BASE;
    fetch(base + 'data/market_data.json')
      .then(r => { if (!r.ok) throw new Error('No data file'); return r.json(); })
      .then(d => setLiveData(d))
      .catch(() => setLiveData(null));
    fetch(base + 'data/universe_a.json')
      .then(r => { if (!r.ok) throw new Error('No file'); return r.json(); })
      .then(d => setUniverseA(d))
      .catch(() => setUniverseA(null));
    fetch(base + 'data/universe_hk.json')
      .then(r => { if (!r.ok) throw new Error('No file'); return r.json(); })
      .then(d => setUniverseHK(d))
      .catch(() => setUniverseHK(null));
    // VP Scores from vp_snapshot.json (written daily by fetch_data.py / GitHub Actions)
    fetch(base + 'data/vp_snapshot.json')
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (!d?.snapshots) return;
        const vpMap = {};
        const egapMap = {};
        d.snapshots.forEach(s => {
          if (!s.ticker) return;
          if (s.vp_score != null) vpMap[s.ticker] = s.vp_score;
          // KR6: capture canonical piecewise expectation_gap alongside VP.
          if (s.expectation_gap != null) egapMap[s.ticker] = s.expectation_gap;
        });
        setVpScores(vpMap);
        setEgapScores(egapMap);
      })
      .catch(() => {});
  }, []);

  const allStocks = { ...STOCKS, ...dynamicStocks };

  /* Build searchable universe index from A+HK data */
  const universeStocks = (() => {
    const arr = [];
    if (universeA?.stocks) arr.push(...universeA.stocks);
    if (universeHK?.stocks) arr.push(...universeHK.stocks);
    return arr;
  })();

  const C = dark ? DARK : LIGHT;
  const L = (e,z) => lang==='en' ? e : z;
  const lk = lang==='en' ? 'e' : 'z';
  const toggle = k => setOpen(p=>({...p,[k]:!p[k]}));

  const goStock = tk => { setTicker(tk); setTab('research'); setShowSuggestions(false); setShowDeepResearch(false); };

  const handleOpenArticle = (article) => {
    setSelectedArticle(article);
    // Reset chat and auto-load initial analysis
    setChatMessages([{ role: 'assistant', content: null, loading: true }]);
    setChatLoading(true);
    const apiBase = 'https://equity-research-ten.vercel.app';
    fetch(`${apiBase}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        article,
        history: [],
        regime_data: regimeData,
        is_auto_analysis: true,
      }),
    })
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(data => {
        setChatMessages([{ role: 'assistant', content: data.content }]);
        setChatLoading(false);
      })
      .catch(() => {
        setChatMessages([{ role: 'assistant', content: 'Failed to load analysis.' }]);
        setChatLoading(false);
      });
  };

  const handleChatSend = () => {
    const q = chatInput.trim();
    if (!q || chatLoading || !selectedArticle) return;
    const updated = [...chatMessages, { role: 'user', content: q }];
    setChatMessages([...updated, { role: 'assistant', content: null, loading: true }]);
    setChatInput('');
    setChatLoading(true);
    const apiBase = 'https://equity-research-ten.vercel.app';
    fetch(`${apiBase}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        article: selectedArticle,
        question: q,
        history: updated.filter(m => m.content),
        regime_data: regimeData,
      }),
    })
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(data => {
        setChatMessages(prev => {
          const msgs = prev.filter(m => !m.loading);
          return [...msgs, { role: 'assistant', content: data.content }];
        });
        setChatLoading(false);
      })
      .catch(() => {
        setChatMessages(prev => {
          const msgs = prev.filter(m => !m.loading);
          return [...msgs, { role: 'assistant', content: 'Error — please retry.' }];
        });
        setChatLoading(false);
      });
  };

  const handleDeepResearchComplete = (tk, data) => {
    setDynamicStocks(prev => ({ ...prev, [tk]: data }));
    // Update live VP score state so FOCUS cards refresh immediately without reload
    if (data?.vp != null) {
      setVpScores(prev => ({ ...prev, [tk]: data.vp }));
    }

    // Persist research to localStorage so pulse can read it across sessions
    // Schema: ar_research_{ticker} = { current, generated_at, price_at_research, vp_history }
    try {
      const liveYahoo   = liveData?.yahoo?.[tk];
      const currentPrice = liveYahoo?.price?.last ?? null;
      const storageKey   = `ar_research_${tk}`;
      const existing     = JSON.parse(localStorage.getItem(storageKey) || '{}');
      const now          = new Date().toISOString();

      const updated = {
        current:          data,
        generated_at:     now,
        price_at_research: currentPrice,
        previous:         existing.current  || null,
        prev_generated_at: existing.generated_at || null,
        thesis_state:     'ACTIVE',
        vp_history: [
          ...(existing.vp_history || []).slice(-9),          // keep last 9
          { date: now.slice(0, 10), vp: data.vp || 0 },
        ],
      };
      localStorage.setItem(storageKey, JSON.stringify(updated));
    } catch (e) {
      console.warn('localStorage write failed:', e.message);
    }

    goStock(tk);
  };

  // ── Morning Report ────────────────────────────────────────────────────────
  const handleGenerateMorningReport = async (payload) => {
    setMorningReportLoading(true);
    const isGHPages = typeof window !== 'undefined' && window.location.hostname.endsWith('github.io');
    const apiBase   = isGHPages ? 'https://equity-research-ten.vercel.app' : '';
    try {
      const res  = await fetch(`${apiBase}/api/morning-report`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      if (!json.success) throw new Error(json.error || 'API error');
      const report = json.report;
      setMorningReport(report);
      // Cache for today
      try {
        const today = new Date().toISOString().slice(0, 10);
        localStorage.setItem(`ar_morning_report_${today}`, JSON.stringify(report));
      } catch {}
    } catch (err) {
      console.error('[MorningReport]', err.message);
    } finally {
      setMorningReportLoading(false);
    }
  };

  // ── Research Pulse ────────────────────────────────────────────────────────
  // Runs for a ticker when research tab loads (once per day per ticker).
  // Reads stored research from localStorage, passes to api/research-pulse.
  const runPulse = async (tk) => {
    // Read stored research
    let stored;
    try {
      const raw = localStorage.getItem(`ar_research_${tk}`);
      if (!raw) return;                          // no stored research yet
      stored = JSON.parse(raw);
    } catch { return; }

    if (!stored?.current) return;

    // Only run once per day per ticker
    const todayKey = `ar_pulse_${tk}_${new Date().toISOString().slice(0, 10)}`;
    try {
      const cached = localStorage.getItem(todayKey);
      if (cached) {
        setPulseData(prev => ({ ...prev, [tk]: JSON.parse(cached) }));
        return;
      }
    } catch {}

    setPulseLoading(prev => ({ ...prev, [tk]: true }));

    try {
      const liveYahoo     = liveData?.yahoo?.[tk];
      const currentPrice  = liveYahoo?.price?.last ?? null;
      const priceAtRes    = stored.price_at_research ?? null;
      const priceChangePct = (currentPrice && priceAtRes)
        ? ((currentPrice - priceAtRes) / priceAtRes) * 100
        : null;
      const generatedAt   = stored.generated_at ? new Date(stored.generated_at) : null;
      const daysSince     = generatedAt
        ? Math.floor((Date.now() - generatedAt.getTime()) / 86400000)
        : null;

      // Recent news for this ticker (last 48h)
      const twoDaysAgo  = Date.now() - 2 * 24 * 3600 * 1000;
      const recentNews  = (newsPortfolio || [])
        .filter(a => a.ticker === tk && new Date(a.published_at).getTime() > twoDaysAgo)
        .slice(0, 5)
        .map(a => ({ title: a.title, source: a.source, published_at: a.published_at }));

      // Sector regime
      let sectorRegime = null;
      if (regimeData?.sectors) {
        const sector = regimeData.sectors.find(s => (s.tickers || []).includes(tk));
        if (sector) sectorRegime = sector.regime;
      }

      // Active predictions for this ticker (OPEN/PENDING only)
      const activePredictions = (predictions || [])
        .filter(p => p.ticker === tk && (!p.status || p.status === 'OPEN' || p.status === 'PENDING'))
        .map(p => ({ id: p.id, thesis: p.thesis || p.prediction, target: p.target, deadline: p.deadline }));

      const isGHPages = typeof window !== 'undefined' && window.location.hostname.endsWith('github.io');
      const apiBase   = isGHPages ? 'https://equity-research-ten.vercel.app' : '';

      const res = await fetch(`${apiBase}/api/research-pulse`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ticker: tk,
          company: stored.current?.en || stored.current?.name || tk,
          stored_research:      stored.current,
          current_price:        currentPrice,
          price_at_research:    priceAtRes,
          price_change_pct:     priceChangePct,
          days_since_research:  daysSince,
          recent_news:          recentNews,
          sector_regime:        sectorRegime,
          active_predictions:   activePredictions,
        }),
      });

      if (!res.ok) throw new Error(`Pulse API ${res.status}`);
      const pulse = await res.json();

      // Cache result for today
      try { localStorage.setItem(todayKey, JSON.stringify(pulse)); } catch {}

      setPulseData(prev => ({ ...prev, [tk]: pulse }));
    } catch (err) {
      console.warn(`[Pulse] ${tk}:`, err.message);
    } finally {
      setPulseLoading(prev => ({ ...prev, [tk]: false }));
    }
  };

  const handleGenerateInsight = async () => {
    if (insightLoading || !regimeData) return;
    setInsightLoading(true);
    setMacroInsight(null);
    try {
      const apiBase = 'https://equity-research-ten.vercel.app';
      const resp = await fetch(`${apiBase}/api/macro`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ regime_data: regimeData }),
      });
      if (!resp.ok) throw new Error(`API error ${resp.status}`);
      const data = await resp.json();
      setMacroInsight(data);
    } catch (err) {
      setMacroInsight({
        insight: {
          market_reads: `Error: ${err.message}`,
          we_think: 'Failed to reach macro API.',
          mechanism: '', implication: '', watch_for: '',
          confidence: 'LOW', horizon: 'N/A',
        },
        generated_at: new Date().toISOString(),
      });
    } finally {
      setInsightLoading(false);
    }
  };

  /* ── Full-market search engine ─────────────────────────────────────── */
  const fmtCap = v => { if(!v) return ''; if(v>=1e12) return (v/1e12).toFixed(1)+'T'; if(v>=1e8) return (v/1e8).toFixed(0)+'亿'; if(v>=1e4) return (v/1e4).toFixed(0)+'万'; return String(v); };

  const searchResults = (() => {
    const q = search.trim();
    if (!q) return [];
    const ql = q.toLowerCase();

    // Score function: lower = better match. Exact name match scores highest.
    const scoreMatch = (name, code, ticker) => {
      if (name === q) return 0;                              // exact name
      if (code === q || code === ql) return 1;               // exact code
      if (name.startsWith(q)) return 2;                      // name starts with
      if (code.startsWith(ql)) return 3;                     // code starts with
      if (ticker.toLowerCase().startsWith(ql)) return 4;     // ticker starts with
      if (name.includes(q)) return 5;                        // name contains
      if (code.includes(ql)) return 6;                       // code contains
      if (ticker.toLowerCase().includes(ql)) return 7;       // ticker contains
      return -1;                                             // no match
    };

    // Search focus stocks
    const focusResults = Object.entries(allStocks)
      .map(([tk,s]) => {
        const sc = scoreMatch(s.name, tk.split('.')[0].toLowerCase(), tk);
        const scEn = s.en ? (s.en.toLowerCase().includes(ql) ? 5 : -1) : -1;
        const best = sc >= 0 ? sc : scEn;
        return best >= 0 ? { ticker:tk, name:s.name, en:s.en, code:tk.split('.')[0],
          exchange: tk.includes('.HK') ? 'HK' : tk.includes('.SH') ? 'SH' : 'SZ',
          price:s.price, change_pct:null, pe: typeof s.fin?.pe === 'number' ? s.fin.pe : null,
          market_cap:null, vp:s.vp, source:'focus', _score:best } : null;
      }).filter(Boolean);

    // Search universe
    const uniResults = universeStocks
      .reduce((acc, s) => {
        if (acc.length >= 200) return acc; // early exit for perf
        const sc = scoreMatch(s.name, s.code, s.ticker);
        if (sc >= 0) acc.push({
          ticker:s.ticker, name:s.name, en:null, code:s.code,
          exchange:s.exchange, price:s.price, change_pct:s.change_pct,
          pe:s.pe, market_cap:s.market_cap, vp:null, source:'universe', _score:sc,
        });
        return acc;
      }, []);

    // Merge, deduplicate (focus wins), sort by score then market cap
    const seen = new Set(focusResults.map(r => r.code));
    const merged = [
      ...focusResults,
      ...uniResults.filter(r => !seen.has(r.code)),
    ];
    merged.sort((a,b) => {
      if (a._score !== b._score) return a._score - b._score;
      return (b.market_cap||0) - (a.market_cap||0); // bigger cap first
    });
    return merged.slice(0, 10);
  })();

  const handleSearch = () => {
    if (searchResults.length > 0) { goStock(searchResults[0].ticker); return; }
    if (search.trim()) { setShowDeepResearch(true); setTab('research'); }
  };

  // 2026-05-02 Phase 1 universe browser KR-C tab consolidation:
  // - Renamed 'screener' → 'browse' (now Phase 1 enriched with industry/PE/Δ% filters)
  // - DELETED 'watchlist' tab (duplicate of 'desk' which already shows watchlist 5)
  // - Tab visual ordering: Browse first (most-used entry point), Desk second (持仓中心)
  // - DEFERRED visual sidebar consolidation of scanner/flow/earnings/morning to Jason UI work
  const TABS = [
    { id:'browse',   label:L('Browse','浏览'),    icon:<Filter size={14}/> },
    { id:'desk',     label:L('Desk','交易台'),     icon:<Crosshair size={14}/> },
    { id:'research', label:L('Research','研究'),  icon:<BookOpen size={14}/> },
    { id:'scanner',  label:L('Scanner','扫描'),   icon:<Radio size={14}/> },
    { id:'flow',     label:L('Flows','资金流'),   icon:<Globe size={14}/> },
    { id:'earnings', label:L('Earnings','财报'),  icon:<Calendar size={14}/> },
    { id:'paper',    label:L('Portfolio','组合'),  icon:<BarChart3 size={14}/> },
    { id:'backtest', label:L('Backtest','回测'),   icon:<TrendingUp size={14}/> },
    { id:'morning',  label:L('Morning','早报'),    icon:<Zap size={14}/> },
    { id:'tracker',  label:L('Tracker','追踪'),   icon:<Target size={14}/> },
    { id:'system',   label:L('System','系统'),    icon:<Layers size={14}/> },
  ];

  return (
    <div style={{display:'flex', height:'100vh',
                 fontFamily:"'Inter','Noto Sans SC',system-ui,sans-serif",
                 background:C.bg, color:C.dark, overflow:'hidden'}}>
      <GlobalStyles />

      {/* ── SIDEBAR ─────────────────────────────────────────────────────── */}
      <div style={{
        width: collapsed ? 56 : 200,
        background: C.card,
        borderRight: `1px solid ${C.border}`,
        display:'flex', flexDirection:'column', flexShrink:0,
        transition:'width .25s cubic-bezier(.4,0,.2,1)', overflow:'hidden',
        boxShadow:'2px 0 8px rgba(50,90,160,0.06)',
        zIndex:10,
      }}>
        {/* Logo block */}
        <div style={{
          padding: collapsed ? '18px 0' : '18px 20px',
          borderBottom:`1px solid ${C.border}`,
          display:'flex', alignItems:'center',
          justifyContent: collapsed ? 'center' : 'flex-start',
          gap:10, minHeight:60,
        }}>
          {/* Jason: Bloomberg-style logo mark with orange accent */}
          <div style={{
            width:32, height:32, borderRadius:6,
            background: dark
              ? `linear-gradient(135deg, ${C.orange||'#FF8C00'}, #CC6600)`
              : `linear-gradient(135deg, ${C.blue}, #6B9FF8)`,
            display:'flex', alignItems:'center', justifyContent:'center',
            flexShrink:0, boxShadow: dark ? `0 0 12px ${C.orange||'#FF8C00'}30` : 'none',
          }}>
            <span style={{fontSize:13, fontWeight:900, color:'#fff', fontFamily:MONO,
                          letterSpacing:'-0.03em'}}>AR</span>
          </div>
          {!collapsed && (
            <div>
              <div style={{fontSize:12, fontWeight:700, color:C.dark, letterSpacing:'0.02em',
                           textTransform:'uppercase'}}>Alpha Research</div>
              <div style={{fontSize:9, color:C.orange||C.mid, marginTop:1, fontFamily:MONO,
                           letterSpacing:'0.05em'}}>TERMINAL v13</div>
            </div>
          )}
        </div>

        {/* Nav items */}
        <div style={{flex:1, padding:'8px 8px', overflowY:'auto', overflowX:'hidden'}}>
          {TABS.map(t => {
            const active = tab === t.id;
            return (
              <button key={t.id} onClick={()=>setTab(t.id)}
                title={collapsed ? t.label : ''}
                style={{
                  width:'100%', marginBottom:2,
                  padding: collapsed ? '9px 0' : '9px 12px',
                  display:'flex', alignItems:'center',
                  gap:10, border:'none', cursor:'pointer',
                  borderRadius: collapsed ? 8 : 6, textAlign:'left',
                  // Jason: Bloomberg orange left-border active indicator
                  background: active ? `${C.orange||C.blue}14` : 'transparent',
                  color: active ? (C.orange||C.blue) : C.mid,
                  fontSize:12, fontWeight: active ? 700 : 400,
                  transition:'all .15s',
                  justifyContent: collapsed ? 'center' : 'flex-start',
                  whiteSpace:'nowrap',
                  letterSpacing: active ? '0.01em' : 'normal',
                  // Inset box-shadow = no layout shift, Bloomberg-style left accent bar
                  boxShadow: (!collapsed && active)
                    ? `inset 3px 0 0 ${C.orange||C.blue}`
                    : 'none',
                }}
                onMouseEnter={e=>{ if(!active) e.currentTarget.style.background=C.soft; }}
                onMouseLeave={e=>{ if(!active) e.currentTarget.style.background='transparent'; }}
              >
                <span style={{
                  width:18, height:18, display:'flex', alignItems:'center',
                  justifyContent:'center', flexShrink:0,
                  color: active ? (C.orange||C.blue) : C.mid,
                }}>{t.icon}</span>
                {!collapsed && t.label}
              </button>
            );
          })}
        </div>

        {/* Footer */}
        <div style={{padding:'8px', borderTop:`1px solid ${C.border}`}}>
          {!collapsed && (
            <div style={{fontSize:9, color:C.mid, textAlign:'center',
                         padding:'4px 0 6px', lineHeight:1.5}}>
              {L('Evidence only · No investment conclusions',
                 '仅证据 · 不构成投资建议')}
            </div>
          )}
          <button onClick={()=>setCollapsed(!collapsed)} style={{
            width:'100%', padding:'6px', border:'none', borderRadius:6,
            background:'transparent', color:C.mid, cursor:'pointer',
            display:'flex', justifyContent:'center',
          }}>
            {collapsed ? <ChevronRight size={14}/> : <ChevronLeft size={14}/>}
          </button>
        </div>
      </div>

      {/* ── MAIN ────────────────────────────────────────────────────────── */}
      <div style={{flex:1, display:'flex', flexDirection:'column', overflow:'hidden'}}>

        {/* Jason: Bloomberg-style thin terminal status strip */}
        {dark && (
          <div style={{
            background: '#020912',
            borderBottom: `1px solid ${C.border}`,
            padding: '3px 20px',
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            flexShrink: 0, zIndex: 10,
          }}>
            <div style={{display:'flex', alignItems:'center', gap:16}}>
              <span style={{fontSize:9, fontFamily:MONO, color:C.orange||'#FF8C00',
                            fontWeight:700, letterSpacing:'0.08em'}}>
                AR ALPHA RESEARCH TERMINAL
              </span>
              <span style={{fontSize:9, fontFamily:MONO, color:C.mid, letterSpacing:'0.04em'}}>
                {nowTime.toLocaleDateString('en-HK', {weekday:'short', year:'numeric', month:'short', day:'numeric'})}
              </span>
            </div>
            <div style={{display:'flex', alignItems:'center', gap:12}}>
              {/* Market session indicator */}
              {(() => {
                const h = nowTime.getHours(), m = nowTime.getMinutes();
                const hkt = h; // assumes local = HKT; adjust if needed
                const isAHKOpen = hkt >= 9 && (hkt < 16 || (hkt === 16 && m === 0));
                const isSZOpen  = hkt >= 9 && (hkt < 15 || (hkt === 15 && m === 0));
                return (
                  <>
                    <div style={{display:'flex', alignItems:'center', gap:4}}>
                      <div style={{width:5, height:5, borderRadius:'50%',
                        background: isSZOpen ? '#00D97E' : C.mid,
                        animation: isSZOpen ? 'blink 2s ease-in-out infinite' : 'none',
                      }}></div>
                      <span style={{fontSize:9, fontFamily:MONO, color: isSZOpen ? '#00D97E' : C.mid}}>
                        A-SH {isSZOpen ? 'OPEN' : 'CLOSED'}
                      </span>
                    </div>
                    <div style={{display:'flex', alignItems:'center', gap:4}}>
                      <div style={{width:5, height:5, borderRadius:'50%',
                        background: isAHKOpen ? '#00D97E' : C.mid,
                        animation: isAHKOpen ? 'blink 2s ease-in-out infinite' : 'none',
                      }}></div>
                      <span style={{fontSize:9, fontFamily:MONO, color: isAHKOpen ? '#00D97E' : C.mid}}>
                        HK {isAHKOpen ? 'OPEN' : 'CLOSED'}
                      </span>
                    </div>
                  </>
                );
              })()}
              <span style={{fontSize:10, fontFamily:MONO, color:C.orange||'#FF8C00',
                            fontWeight:700, letterSpacing:'0.06em', minWidth:72, textAlign:'right'}}>
                {nowTime.toLocaleTimeString('en-HK', {hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:false})} HKT
              </span>
            </div>
          </div>
        )}

        {/* Topbar */}
        <div style={{
          background: C.card,
          borderBottom:`1px solid ${C.border}`,
          padding:'10px 20px',
          display:'flex', justifyContent:'space-between',
          alignItems:'center', gap:12,
          boxShadow: dark ? 'none' : '0 1px 6px rgba(50,90,160,0.07)',
          zIndex:9, flexShrink:0,
        }}>
          <div style={{position:'relative', display:'flex', gap:6, alignItems:'center', flex:1, maxWidth:480}}>
            <input value={search}
              onChange={e=>{setSearch(e.target.value); setShowSuggestions(true)}}
              onKeyDown={e=>{if(e.key==='Enter')handleSearch(); if(e.key==='Escape'){setShowSuggestions(false);}}}
              onFocus={e=>{if(search.trim()) setShowSuggestions(true); e.target.style.borderColor=C.blue;}}
              onBlur={e=>{setTimeout(()=>setShowSuggestions(false), 200); e.target.style.borderColor=C.border;}}
              placeholder={L('Search 10,000+ A+HK stocks by name or code…','搜索10,000+只A股港股，输入名称或代码…')}
              style={{flex:1, padding:'7px 14px', border:`1.5px solid ${C.border}`, borderRadius:8, fontSize:12, outline:'none', background:C.soft, color:C.dark, fontFamily:'inherit', transition:'border-color .15s'}}/>
            <button onClick={handleSearch} style={{padding:'7px 14px', background:C.blue, color:'#fff', border:'none', borderRadius:8, cursor:'pointer', fontSize:12, fontWeight:500}}>
              <Search size={14}/>
            </button>
            <button onClick={()=>{setShowDeepResearch(true); setTab('research');}} title={L('Deep Research','深度研究')} style={{padding:'7px 14px', background:`${C.green}15`, color:C.green, border:`1.5px solid ${C.green}40`, borderRadius:8, cursor:'pointer', fontSize:11, fontWeight:600, whiteSpace:'nowrap', display:'flex', alignItems:'center', gap:5}}>
              <Zap size={13}/>{L('Deep Research','深度研究')}
            </button>
            {showSuggestions && search.trim() && (
              <div style={{position:'absolute', top:'100%', left:0, right:60, marginTop:6, background:C.card, border:`1px solid ${C.border}`, borderRadius:12, maxHeight:420, overflowY:'auto', zIndex:20, boxShadow:'0 8px 40px rgba(50,90,160,0.18)'}}>
                {/* Header */}
                <div style={{padding:'6px 12px', fontSize:9, color:C.mid, borderBottom:`1px solid ${C.border}`, background:C.soft, display:'flex', justifyContent:'space-between', borderRadius:'8px 8px 0 0'}}>
                  <span>{universeStocks.length > 0 ? (universeStocks.length.toLocaleString() + L(' stocks loaded',' 只股票已加载')) : L('Focus stocks only','仅持仓股票')}</span>
                  <span>{searchResults.length > 0 ? searchResults.length + L(' matches',' 个匹配') : ''}</span>
                </div>
                {/* Column headers */}
                {searchResults.length > 0 && (
                  <div style={{display:'flex', padding:'4px 12px', fontSize:8, color:C.mid, borderBottom:`1px solid ${C.border}`, background:C.soft, gap:4}}>
                    <span style={{flex:'1 1 140px'}}>{L('Stock','股票')}</span>
                    <span style={{width:65, textAlign:'right'}}>{L('Price','价格')}</span>
                    <span style={{width:55, textAlign:'right'}}>{L('Chg%','涨跌%')}</span>
                    <span style={{width:50, textAlign:'right'}}>PE</span>
                    <span style={{width:60, textAlign:'right'}}>{L('Mkt Cap','市值')}</span>
                  </div>
                )}
                {/* Results */}
                {searchResults.map((s,i)=>{
                  const chgC = s.change_pct > 0 ? C.red : s.change_pct < 0 ? C.green : C.mid;
                  const curr = s.exchange === 'HK' ? 'HK$' : '¥';
                  return (
                    <div key={s.ticker+i} onClick={()=>goStock(s.ticker)}
                      style={{display:'flex', alignItems:'center', padding:'8px 12px', cursor:'pointer', gap:4,
                        borderBottom:i<searchResults.length-1?`1px solid ${C.border}`:'none',
                        transition:'background .1s', background:'transparent'}}
                      onMouseOver={e=>e.currentTarget.style.background=C.soft}
                      onMouseOut={e=>e.currentTarget.style.background='transparent'}>
                      {/* Name + Code */}
                      <div style={{flex:'1 1 140px', minWidth:0}}>
                        <div style={{display:'flex', alignItems:'center', gap:5}}>
                          <span style={{fontSize:12, fontWeight:700, color:C.dark, whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis'}}>{s.name}</span>
                          {s.source === 'focus' && <span style={{fontSize:7, fontWeight:800, color:C.blue, background:`${C.blue}15`, padding:'1px 4px', borderRadius:3, flexShrink:0}}>VP {s.vp}</span>}
                        </div>
                        <div style={{fontSize:9, color:C.mid, fontFamily:'monospace'}}>{s.code} · {s.exchange}</div>
                      </div>
                      {/* Price */}
                      <div style={{width:65, textAlign:'right', fontSize:11, fontWeight:700, fontFamily:'monospace', color:C.dark}}>
                        {s.price != null ? (typeof s.price === 'string' ? s.price : curr + s.price.toFixed(2)) : '—'}
                      </div>
                      {/* Change% */}
                      <div style={{width:55, textAlign:'right', fontSize:11, fontWeight:700, fontFamily:'monospace', color:chgC}}>
                        {s.change_pct != null ? (s.change_pct > 0 ? '+' : '') + s.change_pct.toFixed(2) + '%' : '—'}
                      </div>
                      {/* PE */}
                      <div style={{width:50, textAlign:'right', fontSize:10, fontFamily:'monospace', color:C.mid}}>
                        {s.pe != null ? s.pe.toFixed(1) : '—'}
                      </div>
                      {/* Market Cap */}
                      <div style={{width:60, textAlign:'right', fontSize:10, fontFamily:'monospace', color:C.mid}}>
                        {fmtCap(s.market_cap)}
                      </div>
                    </div>
                  );
                })}
                {searchResults.length === 0 && (
                  <div style={{padding:16, textAlign:'center'}}>
                    <div style={{fontSize:12, color:C.mid, marginBottom:8}}>{L('No matches found','未找到匹配项')}</div>
                    <button onClick={()=>{setShowDeepResearch(true); setTab('research'); setShowSuggestions(false);}}
                      style={{padding:'6px 14px', background:C.green, color:'#fff', border:'none', borderRadius:6, cursor:'pointer', fontSize:11, fontWeight:600}}>
                      {L('Deep Research this ticker','深度研究该代码')}
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
          <div style={{display:'flex', gap:8, alignItems:'center'}}>
            <DataBadge liveData={liveData} C={C} L={L}/>
            {/* Jason: Live clock in topbar — visible in light mode (dark mode has status strip) */}
            {!dark && (
              <div style={{
                padding:'5px 12px', border:`1px solid ${C.border}`,
                borderRadius:7, background:C.soft,
                display:'flex', alignItems:'center', gap:6,
              }}>
                <div style={{width:5, height:5, borderRadius:'50%', background:C.green,
                             animation:'blink 2s ease-in-out infinite'}}></div>
                <span style={{fontSize:11, fontFamily:MONO, color:C.dark, fontWeight:600,
                              letterSpacing:'0.04em'}}>
                  {nowTime.toLocaleTimeString('en-HK', {hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:false})} HKT
                </span>
              </div>
            )}
            <button onClick={()=>setDark(!dark)} style={{padding:'7px 9px', border:`1.5px solid ${C.border}`, background:'transparent', color:C.mid, cursor:'pointer', borderRadius:8, display:'flex', alignItems:'center', transition:'all .15s'}}
              onMouseEnter={e=>{e.currentTarget.style.background=C.soft;}}
              onMouseLeave={e=>{e.currentTarget.style.background='transparent';}}>
              {dark ? <Sun size={14}/> : <Moon size={14}/>}
            </button>
            <div style={{display:'flex', background:C.soft, borderRadius:8, padding:2, gap:1}}>
              {['en','zh'].map(l=>(
                <button key={l} onClick={()=>setLang(l)} style={{
                  padding:'5px 11px', border:'none',
                  background: lang===l ? (C.orange||C.blue) : 'transparent',
                  color: lang===l ? '#fff' : C.mid,
                  borderRadius:6, cursor:'pointer', fontSize:11, fontWeight:600,
                  transition:'all .15s',
                }}>{l==='en'?'EN':'中文'}</button>
              ))}
            </div>
          </div>
        </div>

        {/* Content area */}
        <div style={{flex:1, overflowY:'auto', padding:`14px 20px ${dark?'36px':'14px'} 20px`, background:C.bg}}>
          {tab==='desk'     && <TradingDesk L={L} lk={lk} C={C}/>}
          {tab==='scanner'  && <Scanner L={L} lk={lk} open={open} toggle={toggle} C={C} stressData={stressData} regimeData={regimeData} macroInsight={macroInsight} insightLoading={insightLoading} onGenerateInsight={handleGenerateInsight} newsMacro={newsMacro} newsPortfolio={newsPortfolio} newsLoading={newsLoading} newsLastFetched={newsLastFetched} onOpenArticle={handleOpenArticle} liveData={liveData} universeA={universeA} universeHK={universeHK} signalsData={signalsData} vpScores={vpScores}/>}
          {(tab==='browse' || tab==='screener') && <Screener L={L} lk={lk} stocks={allStocks} onSelect={goStock} C={C} liveData={liveData} universeA={universeA} universeHK={universeHK}/>}
          {tab==='flow'     && (
            <div>
              <Card title={L('Capital Flow Dashboard','资金流向仪表盘')} sub={L('Northbound · Southbound · Dragon & Tiger · Margin','北向·南向·龙虎榜·融资融券')} open={true} C={C}>
                <FlowPanel liveData={liveData} L={L} lk={lk} C={C}/>
              </Card>
            </div>
          )}
          {tab==='earnings' && (
            <div>
              <Card title={L('Earnings Calendar & Pre-Announcements','财报日历与业绩预告')} sub={L('A-share 业绩预告 · Focus positions highlighted','A股业绩预告·持仓股高亮')} open={true} C={C}>
                <EarningsCalendar L={L} lk={lk} C={C}/>
              </Card>
            </div>
          )}
          {tab==='paper'    && <PaperTrading L={L} lk={lk} C={C}/>}
          {tab==='backtest' && (
            <div>
              <Card title={L('VP Score Strategy Backtest','VP评分策略回测')} sub={L('Monthly rebalance · Equal-weight · vs CSI 300 / HSI · Bootstrap CI','月度调仓·等权·对比沪深300/恒指·自举置信区间')} open={true} C={C}>
                <BacktestPanel L={L} C={C}/>
              </Card>
            </div>
          )}
          {tab==='research' && (() => {
            const isFocus = ticker && allStocks[ticker];
            const isUniverse = ticker && !isFocus && universeStocks.find(s => s.ticker === ticker);
            // Auto-run pulse for any ticker that has stored research (once/day)
            // Use a deferred call to avoid blocking the render
            if (ticker && !pulseLoading[ticker] && !pulseData[ticker]) {
              setTimeout(() => runPulse(ticker), 800);
            }
            if (showDeepResearch || (!ticker && !isFocus)) return (
              <div>
                {isFocus && <div style={{marginBottom:16}}><Research L={L} lk={lk} ticker={ticker} stocks={allStocks} open={open} toggle={toggle} C={C} liveData={liveData} eqrData={eqrData} rdcfData={rdcfData} pulse={pulseData[ticker]} pulseLoading={!!pulseLoading[ticker]} onRunPulse={tk => { setPulseData(p=>({...p,[tk]:null})); runPulse(tk); }} signalsData={signalsData} scissorsData={scissorsData} liData={liData} egapScores={egapScores}/></div>}
                <DeepResearchPanel L={L} lk={lk} onComplete={handleDeepResearchComplete} C={C} universeStocks={universeStocks} enrichmentData={{ liveData, newsPortfolio, regimeData, predictions }}/>
              </div>
            );
            if (isFocus) return <Research L={L} lk={lk} ticker={ticker} stocks={allStocks} open={open} toggle={toggle} C={C} liveData={liveData} eqrData={eqrData} rdcfData={rdcfData} pulse={pulseData[ticker]} pulseLoading={!!pulseLoading[ticker]} onRunPulse={tk => { setPulseData(p=>({...p,[tk]:null})); runPulse(tk); }} signalsData={signalsData} scissorsData={scissorsData} liData={liData} egapScores={egapScores}/>;
            if (isUniverse) return <UniverseStockView ticker={ticker} universeStocks={universeStocks} liveData={liveData} L={L} lk={lk} C={C} onDeepResearch={(tk)=>{setSearch(tk); setShowDeepResearch(true);}}/>;
            return <DeepResearchPanel L={L} lk={lk} onComplete={handleDeepResearchComplete} C={C} universeStocks={universeStocks} enrichmentData={{ liveData, newsPortfolio, regimeData, predictions }}/>;
          })()}
          {tab==='morning'  && <MorningReportPage L={L} lk={lk} C={C} reportData={morningReport} reportLoading={morningReportLoading} onGenerate={handleGenerateMorningReport} liveData={liveData} newsPortfolio={newsPortfolio} newsMacro={newsMacro} regimeData={regimeData} predictions={predictions} allStocks={allStocks}/>}
          {tab==='tracker'  && <Tracker L={L} stocks={allStocks} C={C} predictions={predictions}/>}
          {/* 'watchlist' tab DELETED 2026-05-02 — duplicate of 'desk'. Watchlist 5 持仓 is shown in TradingDesk. */}
          {tab==='system'   && <SystemTab L={L} C={C}/>}
        </div>
      </div>

      {/* Jason: Bloomberg-style bottom statusbar */}
      {dark && (
        <div style={{
          position:'fixed', bottom:0, left: collapsed ? 56 : 200,
          right:0, height:22, zIndex:100,
          background:'#020912',
          borderTop:`1px solid ${C.border}`,
          display:'flex', alignItems:'center',
          padding:'0 16px', gap:20,
          transition:'left .25s cubic-bezier(.4,0,.2,1)',
        }}>
          <span style={{fontSize:8, fontFamily:MONO, color:C.orange||C.mid, fontWeight:700,
                        letterSpacing:'0.08em'}}>
            AR TERMINAL
          </span>
          <span style={{fontSize:8, fontFamily:MONO, color:C.mid, letterSpacing:'0.04em'}}>
            {L('Evidence-based · Not investment advice',
               '基于证据 · 不构成投资建议')}
          </span>
          <span style={{marginLeft:'auto', fontSize:8, fontFamily:MONO, color:C.mid}}>
            AUTO-SYNC 08:30 & 16:30 HKT
          </span>
          <span style={{fontSize:8, fontFamily:MONO, color:C.mid}}>
            FOCUS: 5 STOCKS · A+HK
          </span>
        </div>
      )}

      {/* Article Chat overlay — fixed right panel */}
      {selectedArticle && (
        <ArticleChat
          article={selectedArticle}
          messages={chatMessages}
          input={chatInput}
          loading={chatLoading}
          onInputChange={setChatInput}
          onSend={handleChatSend}
          onClose={() => { setSelectedArticle(null); setChatMessages([]); setChatInput(''); }}
          L={L} lk={lk} C={C}
        />
      )}
    </div>
  );
}
