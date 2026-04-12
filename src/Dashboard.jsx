import { useState } from "react";
import { Search, TrendingUp, TrendingDown, Minus, ChevronDown, BarChart3,
         Shield, Zap, Globe, Eye, Target, Filter, Radio, Crosshair,
         AlertCircle, CheckCircle, ArrowUpRight, ArrowDownRight,
         Database, RefreshCw, Layers, BookOpen, Info, Calendar,
         Sun, Moon, ChevronLeft, ChevronRight, Circle } from "lucide-react";
import { PieChart as RechartsPie, Pie, Cell, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";

/* ── THEME ─────────────────────────────────────────────────────────────────── */
const DARK = { blue:'#5BA0E0', gold:'#D4B878', green:'#4CAF7A', red:'#E06060',
               dark:'#E8E8E8', mid:'#8899AA', bg:'#0D1117', card:'#161B22', border:'#30363D', soft:'#21262D' };
const LIGHT = { blue:'#4A90D9', gold:'#BFA76A', green:'#3D8B6E', red:'#C25450',
                dark:'#2C3E50', mid:'#7F8C8D', bg:'#FAFAF7', card:'#fff', border:'#E8E2D4', soft:'#F5F3ED' };

const S = {
  card:{ background:'none', border:'1px solid currentColor', borderRadius:10, marginBottom:14, overflow:'hidden' },
  cardHd:{ padding:'13px 16px', cursor:'pointer', display:'flex', justifyContent:'space-between',
           alignItems:'center', borderBottom:'1px solid currentColor' },
  cardBd:{ padding:'13px 16px' },
  row:{ display:'flex', alignItems:'center', gap:8 },
  flex:{ display:'flex' },
  tag:(c)=>({ fontSize:10, fontWeight:700, padding:'3px 8px', borderRadius:3,
               background:`${c}18`, color:c, border:`1px solid ${c}30` }),
  mono:{ fontFamily:'monospace' },
  label:{ fontSize:11, color:'currentColor', fontWeight:600, opacity:0.7 },
  val:{ fontSize:13, fontWeight:700, color:'currentColor' },
  sec:{ fontSize:12, color:'currentColor', lineHeight:1.7 },
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
    eqr:{ overall:'MED-HIGH', biz:'HIGH', variant:'MED', catalysts:'HIGH', risks:'MED' },
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
    eqr:{ overall:'MED-HIGH', biz:'HIGH', variant:'MED-HIGH', catalysts:'MED', risks:'MED' },
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
    eqr:{ overall:'MED', biz:'MED-HIGH', variant:'MED', catalysts:'MED', risks:'MED' },
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
    name:'百济神州', en:'BeiGene', sector:'Biotech', dir:'LONG', vp:71, price:'HK$108', mktcap:'HK$149B',
    eqr:{ overall:'MED-HIGH', biz:'MED-HIGH', variant:'MED', catalysts:'HIGH', risks:'MED' },
    pulse:{ e:'Brukinsa EU market share curve faster than US models. Profitability pull-forward likely Q3 2026.', z:'泽布替尼欧盟份额爬坡快于美国模型。盈利时间线可能提前至Q3 2026。' },
    biz:{
      problem:{ e:'CLL/MCL patients need BTK inhibitors with better cardiac safety than ibrutinib.', z:'CLL/MCL患者需要比伊布替尼心脏安全性更好的BTK抑制剂。' },
      mechanism:{ e:'Brukinsa (zanubrutinib) = 2nd-gen BTK inhibitor, >99% occupancy, ALPINE trial proved superiority.', z:'泽布替尼=第二代BTK抑制剂，ALPINE试验证明优越性。' },
      moneyFlow:{ e:'$15,000/patient/month US. 40+ country ex-China rollout. Royalties from BMS partnership.', z:'美国每患者每月1.5万美元，40+国家推广。' }
    },
    variant:{
      marketBelieves:{ e:'EU 2L CLL share = 32%; profitability Q4 2026.', z:'欧盟2L CLL份额32%；Q4 2026盈利。' },
      weBelieve:{ e:'EU share reaches 40% by end 2025 driven by faster EU oncologist adoption; profitability Q3 2026.', z:'欧盟份额40%，Q3盈利提前。' },
      mechanism:{ e:'French/German prescriber data shows +28% QoQ scripts Q4 2025.', z:'法国/德国医生处方数据显示增长。' },
      rightIf:{ e:'Q2 2025 EU revenue >$380M.', z:'Q2欧盟营收>3.8亿美元。' },
      wrongIf:{ e:'IRA negotiation cuts US price >30%.', z:'IRA谈判削价>30%。' }
    },
    catalysts:[{ e:'Q1 2025 EU revenue disclosure', z:'Q1欧盟营收披露', t:'May 2025', date:'2025-05-30', imp:'HIGH' },{ e:'GAAP profitability announcement', z:'GAAP盈利公告', t:'Q3 2026', date:'2026-08-15', imp:'HIGH' }],
    decomp:{ expectation_gap:{s:74,e:'EU adoption speed mismodelled',z:'欧盟采纳速度建模错误'}, fundamental_acc:{s:68,e:'Revenue ramp non-linear',z:'营收爬坡非线性'}, narrative_shift:{s:60,e:'Profitability inflection re-rates stock',z:'盈利拐点重估股价'}, low_coverage:{s:50,e:'Good coverage but EU undermodelled',z:'覆盖尚可但欧盟建模不足'}, catalyst_prox:{s:80,e:'Q1 results in 4 weeks',z:'Q1财报4周内'} },
    risks:[{ e:'IRA Brukinsa price negotiation', z:'IRA泽布替尼价格谈判', p:'MED', imp:'HIGH' },{ e:'PD-1 combo Phase III futility', z:'PD-1联合Phase III无效', p:'LOW', imp:'MED' }],
    pricing:{level:'LOW',crowd:{e:'EU adoption speed not in sell-side models; profitability timing mispriced',z:'欧盟采纳速度未入卖方模型；盈利时间线定价错误'}},
    nextActions:[{e:'Monitor Q2 EU Brukinsa prescription data (IQVIA)',z:'监控Q2欧盟泽布替尼处方数据（IQVIA）'},{e:'Track IRA negotiation milestones',z:'跟踪IRA谈判里程碑'},{e:'Verify profitability timeline in Q1 call',z:'在Q1电话会验证盈利时间线'}],
    fin:{ rev:'$3.2B', revGr:'+63%', gm:'85%', pe:'NM', ev_ebitda:'NM', fcf:'-$0.4B' },
    peerAvg:{ pe:'NM', ev_ebitda:24, gm:'80%' },
  },
  '002594.SZ': {
    name:'比亚迪', en:'BYD', sector:'EV/Auto', dir:'LONG', vp:52, price:'¥298', mktcap:'¥866B',
    eqr:{ overall:'MED', biz:'HIGH', variant:'MED', catalysts:'MED', risks:'MED' },
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
  date:{ e:'April 12, 2025 · Pre-Market', z:'2025年4月12日 · 盘前' },
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

const CatalystTimeline = ({ catalysts, C }) => {
  if (!catalysts || catalysts.length === 0) return null;

  const sortedCats = [...catalysts].sort((a,b) => new Date(a.date) - new Date(b.date));
  const minDate = new Date(sortedCats[0].date);
  const maxDate = new Date(sortedCats[sortedCats.length-1].date);
  const endDate = new Date(maxDate.getTime() + 30*24*60*60*1000);

  const svgW = 580, svgH = 80;
  const margin = 40, axisY = 50;
  const plotW = svgW - 2*margin;

  const getX = (d) => {
    const range = endDate - minDate;
    const offset = new Date(d) - minDate;
    return margin + (offset/range) * plotW;
  };

  const startX = getX(minDate);
  const endX = getX(endDate);

  return (
    <svg width={svgW} height={svgH} style={{marginBottom:14}}>
      <line x1={startX} y1={axisY} x2={endX} y2={axisY} stroke={C.border} strokeWidth="2"/>
      {sortedCats.map((cat,i) => {
        const x = getX(cat.date);
        const color = cat.imp === 'HIGH' ? C.green : C.gold;
        return (
          <g key={i}>
            <circle cx={x} cy={axisY} r="5" fill={color}/>
            <text x={x} y={axisY+20} textAnchor="middle" fontSize="9" fill={C.mid} fontFamily="monospace">
              {new Date(cat.date).toLocaleDateString('en-US', {month:'short', day:'numeric'})}
            </text>
          </g>
        );
      })}
    </svg>
  );
};

const RiskHeatMap = ({ risks, C }) => {
  if (!risks || risks.length === 0) return null;

  const svgW = 280, svgH = 200;
  const quadrants = [
    {x:10, y:10, p:'HIGH', imp:'HIGH', label:'Critical'},
    {x:105, y:10, p:'HIGH', imp:'MED', label:'Monitor'},
    {x:200, y:10, p:'HIGH', imp:'LOW', label:'Watch'},
    {x:10, y:95, p:'MED', imp:'HIGH', label:'High'},
    {x:105, y:95, p:'MED', imp:'MED', label:'Med'},
    {x:200, y:95, p:'MED', imp:'LOW', label:'Low'},
    {x:10, y:180, p:'LOW', imp:'HIGH', label:'Track'},
    {x:105, y:180, p:'LOW', imp:'MED', label:'Minor'},
    {x:200, y:180, p:'LOW', imp:'LOW', label:'Ignore'},
  ];

  const getColor = (p,imp) => {
    if(p==='HIGH' && imp==='HIGH') return C.red;
    if((p==='HIGH'||imp==='HIGH')) return C.gold;
    return C.green;
  };

  const riskMap = {};
  risks.forEach(r => {
    const key = `${r.p}_${r.imp}`;
    riskMap[key] = (riskMap[key] || 0) + 1;
  });

  return (
    <svg width={svgW} height={svgH} style={{marginBottom:14, border:`1px solid ${C.border}`, borderRadius:6, padding:10}}>
      {quadrants.map((q,i) => {
        const key = `${q.p}_${q.imp}`;
        const count = riskMap[key] || 0;
        const color = getColor(q.p, q.imp);
        return (
          <g key={i}>
            <rect x={q.x} y={q.y} width="80" height="75" fill={color} opacity="0.1" stroke={color} strokeWidth="1" rx="4"/>
            <text x={q.x+40} y={q.y+35} textAnchor="middle" fontSize="11" fontWeight="600" fill={color}>{q.label}</text>
            {count > 0 && <circle cx={q.x+70} cy={q.y+8} r="8" fill={color}/>}
            {count > 0 && <text x={q.x+70} y={q.y+12} textAnchor="middle" fontSize="10" fontWeight="700" fill="#fff">{count}</text>}
          </g>
        );
      })}
      <text x={140} y={svgH-5} textAnchor="middle" fontSize="9" fill={C.mid}>Probability →</text>
    </svg>
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
                  <div style={{height:'100%', background:C.blue, width:`${stockW}%`}}/>
                </div>
                <div style={{fontSize:10, fontWeight:600, color:C.dark, width:40, textAlign:'right'}}>{stockVal!=null?stockVal.toFixed(1):'N/M'}{stockVal!=null?m.unit:''}</div>
              </div>
              <div style={{display:'flex', alignItems:'center', gap:4}}>
                <div style={{fontSize:9, color:C.mid, width:30}}>Peer</div>
                <div style={{flex:1, height:6, background:C.border, borderRadius:3, overflow:'hidden'}}>
                  <div style={{height:'100%', background:C.gold, width:`${peerW}%`}}/>
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
  <div style={{textAlign:'center', padding:'8px 12px', background:`${c}10`, borderRadius:8}}>
    <div style={{fontSize:20, fontWeight:700, color:c}}>{n}</div>
    <div style={{fontSize:10, color:C.mid}}>{label}</div>
  </div>
);

const Card = ({ title, sub, open, onToggle, children, C }) => (
  <div style={{...S.card, borderColor:C.border, background:C.card}}>
    <div style={{...S.cardHd, borderColor:C.border, color:C.dark}} onClick={onToggle}>
      <div>
        <div style={{fontSize:13, fontWeight:600, color:C.dark}}>{title}</div>
        {sub && <div style={{fontSize:10, color:C.mid, marginTop:1}}>{sub}</div>}
      </div>
      <ChevronDown size={15} style={{color:C.mid, transform:open?'rotate(180deg)':'', transition:'transform .2s', flexShrink:0}} />
    </div>
    {open && <div style={{...S.cardBd, color:C.dark}}>{children}</div>}
  </div>
);

const VPRing = ({ score, sz=90, C }) => {
  const r=sz*.42, circ=2*Math.PI*r, cx=sz/2;
  const c = score>=75?C.green : score>=55?C.blue : score>=40?C.gold : C.red;
  return (
    <svg width={sz} height={sz}>
      <circle cx={cx} cy={cx} r={r} fill="none" stroke={C.border} strokeWidth="7"/>
      <circle cx={cx} cy={cx} r={r} fill="none" stroke={c} strokeWidth="7"
        strokeDasharray={circ} strokeDashoffset={circ-(score/100)*circ}
        strokeLinecap="round" style={{transform:'rotate(-90deg)', transformOrigin:`${cx}px ${cx}px`}}/>
      <text x={cx} y={cx} textAnchor="middle" dominantBaseline="central"
        style={{fontSize:sz*.28, fontWeight:700, fill:C.dark}}>{score}</text>
    </svg>
  );
};

/* ── SCANNER TAB ────────────────────────────────────────────────────────── */
function Scanner({ L, lk, open, toggle, C }) {
  const colors = [C.blue, C.gold, C.green, C.red, C.blue];
  const sectorColors = [C.blue, '#7B6BA5', C.gold, C.green, C.red];

  return (
    <div>
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

      <Card title={L('Factor Momentum','因子动量')} open={open.factors} onToggle={()=>toggle('factors')} C={C}>
        <div style={{height:220}}>
          <ResponsiveContainer width='100%' height='100%'>
            <BarChart data={SCANNER.factors}>
              <XAxis dataKey='name' tick={{fontSize:11}} />
              <YAxis tick={{fontSize:10}} domain={[0,100]} />
              <Tooltip contentStyle={{background:C.card, border:`1px solid ${C.border}`, borderRadius:6}} />
              <Bar dataKey='val' fill={C.blue} radius={[4,4,0,0]}>
                {SCANNER.factors.map((f,i)=>(
                  <Cell key={i} fill={f.val>60?C.green: f.val>40?C.gold:C.red} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <Card title={L('Screening Funnel','筛选漏斗')} open={open.funnel} onToggle={()=>toggle('funnel')} C={C}>
        {SCANNER.funnel.map((f,i)=>(
          <div key={i} style={{...S.row, marginBottom:i<SCANNER.funnel.length-1?10:0, justifyContent:'space-between'}}>
            <div><div style={{fontSize:11, fontWeight:600, color:C.dark}}>{f.s}</div><div style={{fontSize:9, color:C.mid}}>{f.r}</div></div>
            <div style={{fontSize:13, fontWeight:700, color:C.blue}}>{f.n}</div>
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
    </div>
  );
}

/* ── SCREENER TAB ────────────────────────────────────────────────────────── */
function Screener({ L, lk, stocks: stocksMap, onSelect, C }) {
  const stocks = Object.entries(stocksMap || STOCKS).map(([tk,s])=>({...s, ticker:tk})).sort((a,b)=>b.vp-a.vp);
  return (
    <div>
      <div style={{display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(280px, 1fr))', gap:14}}>
        {stocks.map((s,i)=>(
          <div key={i} style={{background:C.card, border:`1px solid ${C.border}`, borderRadius:10, padding:14, cursor:'pointer', transition:'all .2s', opacity:0.85}} onClick={()=>onSelect(s.ticker)}>
            <div style={{...S.row, justifyContent:'space-between', marginBottom:8}}>
              <div><div style={{fontSize:12, fontWeight:700, color:C.dark}}>{s.ticker}</div><div style={{fontSize:10, color:C.mid}}>{s.name}/{s.en}</div></div>
              <VPRing score={s.vp} sz={48} C={C}/>
            </div>
            <div style={{fontSize:12, fontWeight:600, color:C.dark, marginBottom:6}}>{s.price}</div>
            <div style={{fontSize:10, color:C.mid, lineHeight:1.5}}>{s.pulse[lk]}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── RESEARCH TAB ────────────────────────────────────────────────────────── */
function Research({ L, lk, ticker, stocks: stocksMap, open, toggle, C }) {
  const allS = stocksMap || STOCKS;
  if (!ticker || !allS[ticker]) return <div style={{color:C.mid}}>{L('Select a stock','选择股票')}</div>;
  const s = allS[ticker];

  const decompData = Object.entries(s.decomp).map(([k,v])=>({name:k.replace(/_/g,' '), value:v.s}));
  const sectorIdx = PORTFOLIO.sectors.findIndex(sc=>sc.name===s.sector);
  const sectorColor = sectorIdx>=0 ? [C.blue,'#7B6BA5',C.gold,C.green,C.red][sectorIdx] : C.mid;

  return (
    <div>
      <Card title={`${ticker} · ${s.name}`} sub={`${s.en} · VP ${s.vp}`} open={true} C={C}>
        <div style={{display:'grid', gridTemplateColumns:'repeat(3, 1fr)', gap:12, marginBottom:14}}>
          <div><div style={S.label}>Price</div><div style={S.val}>{s.price}</div></div>
          <div><div style={S.label}>Market Cap</div><div style={S.val}>{s.mktcap}</div></div>
          <div><div style={S.label}>Direction</div><div style={{...S.val, color:C.green}}>{s.dir}</div></div>
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
        <CatalystTimeline catalysts={s.catalysts} C={C}/>
        {s.catalysts.map((c,i)=>(
          <div key={i} style={{marginBottom:10, paddingBottom:10, borderBottom:i<s.catalysts.length-1?`1px solid ${C.border}`:'none'}}>
            <div style={{...S.row, gap:8, marginBottom:4}}><span style={{fontSize:11, fontWeight:700, color:C.dark}}>{c[lk]}</span><Tag text={c.t} c={C.blue} C={C}/><Tag text={c.imp} c={c.imp==='HIGH'?C.green:C.gold} C={C}/></div>
          </div>
        ))}
      </Card>

      <Card title={L('Risks','风险')} open={open.risks} onToggle={()=>toggle('risks')} C={C}>
        <RiskHeatMap risks={s.risks} C={C}/>
        {s.risks.map((r,i)=>(
          <div key={i} style={{marginBottom:10, paddingBottom:10, borderBottom:i<s.risks.length-1?`1px solid ${C.border}`:'none'}}>
            <div style={{...S.row, gap:8, marginBottom:4}}><span style={{fontSize:11, fontWeight:700, color:C.dark}}>{r[lk]}</span><Tag text={r.p} c={r.p==='HIGH'?C.red:r.p==='MED'?C.gold:C.green} C={C}/></div>
          </div>
        ))}
      </Card>

      <Card title={L('Financials','财务')} open={open.fin} onToggle={()=>toggle('fin')} C={C}>
        <FinCompare fin={s.fin} peerAvg={s.peerAvg} C={C}/>
        <div style={{display:'grid', gridTemplateColumns:'repeat(3, 1fr)', gap:12}}>
          <div>
            <div style={S.label}>Revenue</div>
            <div style={S.val}>{s.fin.rev}</div>
            <div style={{fontSize:9, color:C.green, marginTop:2}}>{s.fin.revGr}</div>
          </div>
          <div>
            <div style={S.label}>FCF</div>
            <div style={S.val}>{s.fin.fcf}</div>
          </div>
          <div>
            <div style={S.label}>Gross Margin</div>
            <div style={S.val}>{s.fin.gm}</div>
          </div>
        </div>
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
function Tracker({ L, stocks: stocksMap, C }) {
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
                  <td style={{padding:8, color:C.dark}}>{s.fin.rev}</td>
                  <td style={{padding:8, color:C.green}}>{s.fin.revGr}</td>
                  <td style={{padding:8, color:C.dark}}>{s.fin.gm}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
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
function DeepResearchPanel({ L, lk, onComplete, C }) {
  const [drTicker, setDrTicker] = useState('');
  const [drDir, setDrDir] = useState('NEUTRAL');
  const [drContext, setDrContext] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [progress, setProgress] = useState(0);

  const runResearch = async () => {
    if (!drTicker.trim()) return;
    setLoading(true); setError(null); setProgress(10);

    const steps = [
      {p:15, t:L('Analyzing macro context...','分析宏观背景...')},
      {p:30, t:L('Building business model...','构建商业模式...')},
      {p:50, t:L('Identifying variant perception...','识别变体认知...')},
      {p:70, t:L('Mapping catalysts & risks...','映射催化剂与风险...')},
      {p:85, t:L('Scoring VP decomposition...','计算VP分解评分...')},
    ];
    let stepIdx = 0;
    const timer = setInterval(() => {
      if (stepIdx < steps.length) { setProgress(steps[stepIdx].p); stepIdx++; }
    }, 3000);

    try {
      const res = await fetch('/api/research', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticker: drTicker.trim(), direction: drDir, context: drContext || undefined }),
      });
      clearInterval(timer);
      const json = await res.json();
      if (!res.ok) throw new Error(json.error || 'Request failed');
      setProgress(100);
      onComplete(drTicker.trim(), json.data);
    } catch (err) {
      clearInterval(timer);
      setError(err.message);
      setProgress(0);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{background:C.card, border:`1px solid ${C.border}`, borderRadius:10, padding:20, maxWidth:480}}>
      <div style={{...S.row, gap:8, marginBottom:16}}>
        <Crosshair size={16} style={{color:C.blue}}/>
        <div style={{fontSize:14, fontWeight:700, color:C.dark}}>{L('Deep Research','深度研究')}</div>
        <span style={{fontSize:9, padding:'2px 6px', background:`${C.blue}15`, color:C.blue, borderRadius:3, fontWeight:700}}>AI</span>
      </div>
      <div style={{fontSize:10, color:C.mid, marginBottom:16, lineHeight:1.6}}>
        {L('Enter any ticker to generate a full buy-side research report powered by Claude AI. The 6-stage workflow produces institutional-grade analysis in ~15 seconds.',
           '输入任意股票代码，由Claude AI驱动生成完整的买方研究报告。6阶段工作流约15秒生成机构级分析。')}
      </div>

      <div style={{marginBottom:12}}>
        <div style={{fontSize:10, fontWeight:600, color:C.mid, marginBottom:4}}>{L('Ticker','代码')} *</div>
        <input value={drTicker} onChange={e=>setDrTicker(e.target.value.toUpperCase())}
          onKeyDown={e=>e.key==='Enter'&&!loading&&runResearch()}
          placeholder={L('e.g. NVDA, 688981.SH, 9888.HK','如 NVDA, 688981.SH, 9888.HK')}
          disabled={loading}
          style={{width:'100%', padding:'8px 10px', border:`1px solid ${C.border}`, borderRadius:6, fontSize:12, background:C.soft, color:C.dark, outline:'none'}}/>
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
            <div style={{height:'100%', background:C.blue, borderRadius:2, width:`${progress}%`, transition:'width .5s'}}/>
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

      <button onClick={runResearch} disabled={loading || !drTicker.trim()} style={{
        width:'100%', padding:'10px 0', border:'none', borderRadius:6, cursor:loading?'wait':'pointer',
        background:loading?C.soft:C.blue, color:loading?C.mid:'#fff', fontSize:12, fontWeight:700,
        transition:'all .2s', opacity:!drTicker.trim()?0.5:1,
      }}>
        {loading ? L('Generating Report...','生成报告中...') : L('Generate Buy-Side Research','生成买方研究报告')}
      </button>

      <div style={{fontSize:9, color:C.mid, marginTop:10, textAlign:'center', lineHeight:1.4}}>
        {L('Powered by Claude Sonnet · Evidence only, no investment conclusions',
           'Claude Sonnet驱动 · 仅提供证据，不提供投资结论')}
      </div>
    </div>
  );
}

/* ── DASHBOARD ────────────────────────────────────────────────────────────── */
export default function Dashboard() {
  const [lang, setLang] = useState('en');
  const [dark, setDark] = useState(true);
  const [tab, setTab] = useState('scanner');
  const [ticker, setTicker] = useState(null);
  const [search, setSearch] = useState('');
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [open, setOpen] = useState({factors:true, funnel:true, pairs:false, macro:true, macroImpact:true, leading:true, biz:true, variant:true, vp:true, cats:true, risks:false, fin:false, ta:false, actions:true});
  const [dynamicStocks, setDynamicStocks] = useState({});
  const [showDeepResearch, setShowDeepResearch] = useState(false);

  const allStocks = { ...STOCKS, ...dynamicStocks };

  const C = dark ? DARK : LIGHT;
  const L = (e,z) => lang==='en' ? e : z;
  const lk = lang==='en' ? 'e' : 'z';
  const toggle = k => setOpen(p=>({...p,[k]:!p[k]}));

  const goStock = tk => { setTicker(tk); setTab('research'); setShowSuggestions(false); setShowDeepResearch(false); };

  const handleDeepResearchComplete = (tk, data) => {
    setDynamicStocks(prev => ({ ...prev, [tk]: data }));
    goStock(tk);
  };

  const handleSearch = () => {
    const q = search.toLowerCase().trim();
    const found = Object.entries(allStocks).find(([tk,s]) =>
      tk.toLowerCase().includes(q) || s.name.toLowerCase().includes(q) || s.en.toLowerCase().includes(q)
    );
    if (found) goStock(found[0]);
    else { setShowDeepResearch(true); setTab('research'); }
  };

  const searchResults = search.trim() ?
    Object.entries(allStocks)
      .filter(([tk,s]) =>
        tk.toLowerCase().includes(search.toLowerCase()) ||
        s.name.toLowerCase().includes(search.toLowerCase()) ||
        s.en.toLowerCase().includes(search.toLowerCase())
      )
      .slice(0, 5)
      .map(([tk,s]) => ({...s, ticker:tk}))
    : Object.entries(allStocks).slice(0, 5).map(([tk,s]) => ({...s, ticker:tk}));

  const TABS = [
    { id:'scanner',  label:L('Scanner','扫描'),   icon:<Radio size={14}/> },
    { id:'screener', label:L('Screener','筛选'),  icon:<Filter size={14}/> },
    { id:'research', label:L('Research','研究'),  icon:<Crosshair size={14}/> },
    { id:'tracker',  label:L('Tracker','追踪'),   icon:<Target size={14}/> },
    { id:'watchlist',label:L('Watchlist','关注'), icon:<Eye size={14}/> },
    { id:'system',   label:L('System','系统'),    icon:<Layers size={14}/> },
  ];

  return (
    <div style={{display:'flex', height:'100vh', fontFamily:'Inter,"Noto Sans SC",system-ui,sans-serif', background:C.bg, color:C.dark, overflow:'hidden'}}>
      {/* Sidebar */}
      <div style={{width:collapsed?48:170, background:C.card, borderRight:`1px solid ${C.border}`, display:'flex', flexDirection:'column', flexShrink:0, transition:'width .3s', overflow:'hidden'}}>
        <div style={{padding:collapsed?'14px 10px':'14px 14px 10px', borderBottom:`1px solid ${C.border}`, whiteSpace:'nowrap'}}>
          <div style={{fontSize:collapsed?16:22, fontWeight:800, color:C.blue, letterSpacing:collapsed?0:'-.02em'}}>AR</div>
          {!collapsed && <div style={{fontSize:8, color:C.mid, letterSpacing:'.1em', marginTop:1}}>ALPHA RESEARCH v9.0</div>}
        </div>
        <div style={{flex:1, paddingTop:4, overflow:'hidden'}}>
          {TABS.map(t=>(
            <button key={t.id} onClick={()=>setTab(t.id)} title={collapsed?t.label:''} style={{
              width:'100%', padding:'9px 12px', display:'flex', alignItems:'center', gap:8,
              border:'none', background:tab===t.id?`${C.blue}10`:'transparent', cursor:'pointer',
              color:tab===t.id?C.blue:C.mid, fontSize:12, fontWeight:tab===t.id?700:400,
              borderLeft:`3px solid ${tab===t.id?C.blue:'transparent'}`, textAlign:'left',
              transition:'all .15s', whiteSpace:'nowrap', justifyContent:collapsed?'center':'flex-start',
            }}>
              {t.icon}{!collapsed && <span>{t.label}</span>}
            </button>
          ))}
        </div>
        <div style={{padding:'10px 12px', borderTop:`1px solid ${C.border}`, fontSize:9, color:C.mid, textAlign:'center', whiteSpace:'nowrap'}}>
          {!collapsed && L('Evidence only.','仅证据。')}
        </div>
        <button onClick={()=>setCollapsed(!collapsed)} title={collapsed?'Expand':'Collapse'} style={{width:'100%', padding:'8px', border:'none', background:'transparent', color:C.mid, cursor:'pointer', display:'flex', justifyContent:'center', borderTop:`1px solid ${C.border}`}}>
          {collapsed ? <ChevronRight size={14}/> : <ChevronLeft size={14}/>}
        </button>
      </div>

      {/* Main */}
      <div style={{flex:1, display:'flex', flexDirection:'column', overflow:'hidden'}}>
        {/* Topbar */}
        <div style={{background:C.card, borderBottom:`1px solid ${C.border}`, padding:'8px 16px', display:'flex', justifyContent:'space-between', alignItems:'center', gap:12}}>
          <div style={{position:'relative', display:'flex', gap:6, alignItems:'center', flex:1, maxWidth:380}}>
            <input value={search}
              onChange={e=>{setSearch(e.target.value); setShowSuggestions(true)}}
              onKeyDown={e=>e.key==='Enter'&&handleSearch()}
              onFocus={()=>setShowSuggestions(true)}
              onBlur={()=>setTimeout(()=>setShowSuggestions(false), 200)}
              placeholder={L('Search ticker / name…','搜索代码/名称…')}
              style={{flex:1, padding:'5px 10px', border:`1px solid ${C.border}`, borderRadius:6, fontSize:12, outline:'none', background:C.soft, color:C.dark}}/>
            <button onClick={handleSearch} style={{padding:'5px 10px', background:C.blue, color:'#fff', border:'none', borderRadius:6, cursor:'pointer', fontSize:12}}>
              <Search size={13}/>
            </button>
            <button onClick={()=>{setShowDeepResearch(true); setTab('research');}} title={L('Deep Research','深度研究')} style={{padding:'5px 10px', background:`${C.green}15`, color:C.green, border:`1px solid ${C.green}40`, borderRadius:6, cursor:'pointer', fontSize:10, fontWeight:700, whiteSpace:'nowrap', display:'flex', alignItems:'center', gap:4}}>
              <Zap size={12}/>{L('Deep','深度')}
            </button>
            {showSuggestions && (
              <div style={{position:'absolute', top:'100%', left:0, right:0, marginTop:4, background:C.card, border:`1px solid ${C.border}`, borderRadius:6, maxHeight:240, overflowY:'auto', zIndex:10}}>
                {searchResults.map((s,i)=>(
                  <div key={i} onClick={()=>goStock(s.ticker)} style={{padding:10, cursor:'pointer', borderBottom:i<searchResults.length-1?`1px solid ${C.border}`:'none', transition:'background .15s', background:'transparent'}} onMouseOver={e=>e.target.style.background=C.soft} onMouseOut={e=>e.target.style.background='transparent'}>
                    <div style={{fontSize:11, fontWeight:700, color:C.dark}}>{s.ticker} · {s.name}</div>
                    <div style={{fontSize:9, color:C.mid}}>{s.en} · VP {s.vp}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div style={{display:'flex', gap:8, alignItems:'center'}}>
            <button onClick={()=>setDark(!dark)} title={dark?'Light mode':'Dark mode'} style={{padding:'5px 8px', border:`1px solid ${C.border}`, background:'transparent', color:C.mid, cursor:'pointer', borderRadius:6, display:'flex', alignItems:'center'}}>
              {dark ? <Sun size={14}/> : <Moon size={14}/>}
            </button>
            <div style={{display:'flex', gap:3, background:C.soft, padding:2, borderRadius:5}}>
              {['en','zh'].map(l=>(
                <button key={l} onClick={()=>setLang(l)} style={{
                  padding:'3px 10px', border:'none', background:lang===l?C.blue:'transparent',
                  color:lang===l?'#fff':C.mid, borderRadius:4, cursor:'pointer', fontSize:10, fontWeight:700, transition:'all .15s',
                }}>{l==='en'?'EN':'中文'}</button>
              ))}
            </div>
          </div>
        </div>

        {/* Content */}
        <div style={{flex:1, overflowY:'auto', padding:16}}>
          {tab==='scanner'  && <Scanner L={L} lk={lk} open={open} toggle={toggle} C={C}/>}
          {tab==='screener' && <Screener L={L} lk={lk} stocks={allStocks} onSelect={goStock} C={C}/>}
          {tab==='research' && (
            (!ticker || !allStocks[ticker] || showDeepResearch) ? (
              <div>
                {ticker && allStocks[ticker] && <div style={{marginBottom:16}}><Research L={L} lk={lk} ticker={ticker} stocks={allStocks} open={open} toggle={toggle} C={C}/></div>}
                <DeepResearchPanel L={L} lk={lk} onComplete={handleDeepResearchComplete} C={C}/>
              </div>
            ) : <Research L={L} lk={lk} ticker={ticker} stocks={allStocks} open={open} toggle={toggle} C={C}/>
          )}
          {tab==='tracker'  && <Tracker L={L} stocks={allStocks} C={C}/>}
          {tab==='watchlist'&& <Watchlist L={L} stocks={allStocks} C={C}/>}
          {tab==='system'   && <SystemTab L={L} C={C}/>}
        </div>
      </div>
    </div>
  );
}
