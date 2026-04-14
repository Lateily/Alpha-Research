import { useState, useEffect } from "react";
import { Search, TrendingUp, TrendingDown, Minus, ChevronDown, BarChart3,
         Shield, Zap, Globe, Eye, Target, Filter, Radio, Crosshair,
         AlertCircle, CheckCircle, ArrowUpRight, ArrowDownRight,
         Database, RefreshCw, Layers, BookOpen, Info, Calendar,
         Sun, Moon, ChevronLeft, ChevronRight, Circle,
         Wifi, WifiOff } from "lucide-react";
import { PieChart as RechartsPie, Pie, Cell, BarChart, Bar, LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";

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
function Research({ L, lk, ticker, stocks: stocksMap, open, toggle, C, liveData, eqrData, rdcfData }) {
  const allS = stocksMap || STOCKS;
  if (!ticker || !allS[ticker]) return <div style={{color:C.mid}}>{L('Select a stock','选择股票')}</div>;
  const s = allS[ticker];
  const eqr  = eqrData?.[ticker]  || null;
  const rdcf = rdcfData?.[ticker] || null;

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

      <Card title={L('Consensus Estimates','一致预期')} sub={L('Broker forecasts · Beat/miss · Revision momentum','券商预测·超预期记录·预期修正动量')} open={open.consensus} onToggle={()=>toggle('consensus')} C={C}>
        <ConsensusPanel ticker={ticker} liveData={liveData} L={L} lk={lk} C={C}/>
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

      {/* Reverse DCF Card */}
      <ReverseDCF rdcf={rdcf} L={L} C={C} open={open} toggle={toggle}/>

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
                  <td style={{padding:8, color:C.dark}}>{s.fin.rev}</td>
                  <td style={{padding:8, color:C.green}}>{s.fin.revGr}</td>
                  <td style={{padding:8, color:C.dark}}>{s.fin.gm}</td>
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
                  <div style={{height:'100%', width:`${pred.confidence}%`, background:confColor, borderRadius:2}}/>
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
              }}/>
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
            <div style={{position:'absolute', left:0, width:'30%', height:'100%', background:`${C.green}40`, borderRadius:'3px 0 0 3px'}}/>
            <div style={{position:'absolute', right:0, width:'30%', height:'100%', background:`${C.red}40`, borderRadius:'0 3px 3px 0'}}/>
            {t.rsi_14 && <div style={{position:'absolute', left:`${t.rsi_14}%`, top:-2, width:10, height:10, borderRadius:5, background:rsiColor, transform:'translateX(-5px)'}}/>}
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

/* ── FLOW PANEL (Southbound + Dragon & Tiger + Margin) ───────────────── */
const FlowPanel = ({ liveData, L, lk, C }) => {
  const [flowData, setFlowData] = useState(null);
  useEffect(() => {
    const base = import.meta.env.BASE_URL || '/';
    fetch(base + 'data/flow_data.json')
      .then(r => { if (!r.ok) throw new Error(); return r.json(); })
      .then(d => setFlowData(d))
      .catch(() => setFlowData(null));
  }, []);

  const nb = liveData?.akshare?.northbound || flowData?.northbound || {};
  const sb = flowData?.southbound || liveData?.akshare?.southbound || {};
  const dt = flowData?.dragon_tiger || liveData?.akshare?.dragon_tiger || [];
  const margin = flowData?.margin || liveData?.akshare?.margin || {};

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

      {(!nb.latest_net_flow && !sb.latest_net_flow && dt.length === 0) && (
        <div style={{padding:20, textAlign:'center', color:C.mid, fontSize:11}}>
          <WifiOff size={14} style={{marginBottom:4}}/><br/>
          {L('No flow data. Run python3 scripts/fetch_data.py to fetch southbound + Dragon & Tiger data.',
             '暂无资金流向数据。运行 python3 scripts/fetch_data.py 以获取南向+龙虎榜数据。')}
        </div>
      )}
    </div>
  );
};

/* ── EARNINGS CALENDAR ───────────────────────────────────────────────── */
const EarningsCalendar = ({ L, lk, C }) => {
  const [calData, setCalData] = useState(null);
  useEffect(() => {
    const base = import.meta.env.BASE_URL || '/';
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
    const base = import.meta.env.BASE_URL || '/';
    fetch(base + 'data/positions.json').then(r=>r.ok?r.json():null).then(d=>setPositions(d)).catch(()=>{});
    fetch(base + 'data/analytics.json').then(r=>r.ok?r.json():null).then(d=>setAnalytics(d)).catch(()=>{});
    fetch(base + 'data/snapshots.json').then(r=>r.ok?r.json():null).then(d=>setSnapshots(d?.snapshots||[])).catch(()=>{});
  }, []);

  const pos = positions?.positions || [];
  const summary = positions?.summary || {};
  const pnl = summary.total_pnl || 0;
  const pnlPct = summary.total_pnl_pct || 0;
  const pnlColor = pnl >= 0 ? C.green : C.red;

  const handleAddTrade = () => {
    // Save new trade to localStorage for manual sync
    const trades = JSON.parse(localStorage.getItem('ar_pending_trades') || '[]');
    trades.push({ ...newTrade, id: 't' + Date.now(), date: new Date().toISOString().slice(0,10), quantity: +newTrade.quantity, price: +newTrade.price });
    localStorage.setItem('ar_pending_trades', JSON.stringify(trades));
    setShowAddTrade(false);
    setNewTrade({ ticker:'', name:'', market:'SZ', side:'BUY', quantity:'', price:'', sector_sw:'', notes:'' });
    alert(L('Trade saved locally. To persist: copy trades from localStorage to public/data/trades.json and re-run python3 scripts/paper_trading.py',
            '交易已保存到本地存储。要持久化：将交易复制到 public/data/trades.json 并重新运行 python3 scripts/paper_trading.py'));
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
    const base = import.meta.env.BASE_URL || '/';
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
    const base = import.meta.env.BASE_URL || '/';
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
                  <div style={{position:'absolute', left:`${Math.min(100,Math.max(0,(stock.price-stock.low)/(stock.high-stock.low)*100))}%`, top:-2, width:10, height:10, borderRadius:5, background:C.blue, transform:'translateX(-5px)'}}/>
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
                  <div style={{position:'absolute', left:`${Math.min(100,Math.max(0,(stock.price-stock.low_52w)/(stock.high_52w-stock.low_52w)*100))}%`, top:-2, width:10, height:10, borderRadius:5, background:C.blue, transform:'translateX(-5px)'}}/>
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

function ReverseDCF({ rdcf, L, C, open, toggle }) {
  if (!rdcf) return null;

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
        <div style={{padding:'12px 14px', background:`${C.red}10`, border:`1px solid ${C.red}30`, borderRadius:7, color:C.red, fontSize:11}}>
          ⚠ {L('RDCF unavailable: ','反向DCF不可用：')}{err}
          <div style={{fontSize:9, color:C.mid, marginTop:4}}>
            {L('Run fetch_data.py to generate data','运行 fetch_data.py 生成数据')}
          </div>
        </div>
      )}

      {!err && (
        <>
          {/* Signal banner */}
          <div style={{padding:'10px 16px', background:`${signalColor}12`, border:`1px solid ${signalColor}35`, borderRadius:7, marginBottom:14, display:'flex', alignItems:'center', justifyContent:'space-between'}}>
            <div>
              <span style={{fontSize:13, fontWeight:800, color:signalColor, letterSpacing:'0.04em'}}>{signalLabel}</span>
              <span style={{fontSize:10, color:C.mid, marginLeft:10}}>
                {L('Gap Score: ','预期差得分: ')}<b style={{color:signalColor}}>{rdcf.expectation_gap_score}</b>/100
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
              sub={`${L('Gap Score','预期差得分')}: ${rdcf.expectation_gap_score}/100`}
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

/* ── BACKTEST PANEL ───────────────────────────────────────────────────── */
function BacktestPanel({ L, C }) {
  const [bt, setBt] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const base = import.meta.env.BASE_URL || '/';
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
export default function Dashboard() {
  const [lang, setLang] = useState('en');
  const [dark, setDark] = useState(true);
  const [tab, setTab] = useState('scanner');
  const [ticker, setTicker] = useState(null);
  const [search, setSearch] = useState('');
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [open, setOpen] = useState({factors:true, funnel:true, pairs:false, macro:true, macroImpact:true, leading:true, biz:true, variant:true, vp:true, cats:true, risks:false, fin:false, consensus:true, ta:true, kline:true, statements:false, company:false, actions:true, rdcf:true});
  const [dynamicStocks, setDynamicStocks] = useState({});
  const [showDeepResearch, setShowDeepResearch] = useState(false);
  const [liveData, setLiveData] = useState(null);
  const [universeA, setUniverseA] = useState(null);
  const [universeHK, setUniverseHK] = useState(null);
  const [eqrData, setEqrData]   = useState({});
  const [rdcfData, setRdcfData] = useState({});
  const [predictions, setPredictions] = useState([]);

  /* Fetch prediction log on mount */
  useEffect(() => {
    const base = import.meta.env.BASE_URL || '/';
    fetch(base + 'data/prediction_log.json')
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d?.predictions) setPredictions(d.predictions); })
      .catch(() => {});
  }, []);

  /* Fetch EQR ratings on mount */
  useEffect(() => {
    const base = import.meta.env.BASE_URL || '/';
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
    const base = import.meta.env.BASE_URL || '/';
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

  /* Fetch live market data + universe on mount */
  useEffect(() => {
    const base = import.meta.env.BASE_URL || '/';
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

  const handleDeepResearchComplete = (tk, data) => {
    setDynamicStocks(prev => ({ ...prev, [tk]: data }));
    goStock(tk);
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

  const TABS = [
    { id:'scanner',  label:L('Scanner','扫描'),   icon:<Radio size={14}/> },
    { id:'screener', label:L('Screener','筛选'),  icon:<Filter size={14}/> },
    { id:'research', label:L('Research','研究'),  icon:<Crosshair size={14}/> },
    { id:'flow',     label:L('Flows','资金流'),   icon:<Globe size={14}/> },
    { id:'earnings', label:L('Earnings','财报'),  icon:<Calendar size={14}/> },
    { id:'paper',    label:L('Portfolio','组合'),  icon:<BarChart3 size={14}/> },
    { id:'backtest', label:L('Backtest','回测'),   icon:<TrendingUp size={14}/> },
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
          {!collapsed && <div style={{fontSize:8, color:C.mid, letterSpacing:'.1em', marginTop:1}}>ALPHA RESEARCH v13.0</div>}
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
          <div style={{position:'relative', display:'flex', gap:6, alignItems:'center', flex:1, maxWidth:480}}>
            <input value={search}
              onChange={e=>{setSearch(e.target.value); setShowSuggestions(true)}}
              onKeyDown={e=>{if(e.key==='Enter')handleSearch(); if(e.key==='Escape'){setShowSuggestions(false);}}}
              onFocus={()=>{if(search.trim()) setShowSuggestions(true);}}
              onBlur={()=>setTimeout(()=>setShowSuggestions(false), 200)}
              placeholder={L('Search 10,000+ A+HK stocks by name or code…','搜索10,000+只A股港股，输入名称或代码…')}
              style={{flex:1, padding:'6px 12px', border:`1px solid ${C.border}`, borderRadius:6, fontSize:12, outline:'none', background:C.soft, color:C.dark}}/>
            <button onClick={handleSearch} style={{padding:'5px 10px', background:C.blue, color:'#fff', border:'none', borderRadius:6, cursor:'pointer', fontSize:12}}>
              <Search size={13}/>
            </button>
            <button onClick={()=>{setShowDeepResearch(true); setTab('research');}} title={L('Deep Research','深度研究')} style={{padding:'5px 10px', background:`${C.green}15`, color:C.green, border:`1px solid ${C.green}40`, borderRadius:6, cursor:'pointer', fontSize:10, fontWeight:700, whiteSpace:'nowrap', display:'flex', alignItems:'center', gap:4}}>
              <Zap size={12}/>{L('Deep','深度')}
            </button>
            {showSuggestions && search.trim() && (
              <div style={{position:'absolute', top:'100%', left:0, right:60, marginTop:4, background:C.card, border:`1px solid ${C.border}`, borderRadius:8, maxHeight:420, overflowY:'auto', zIndex:20, boxShadow:'0 8px 32px rgba(0,0,0,.25)'}}>
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
            if (showDeepResearch || (!ticker && !isFocus)) return (
              <div>
                {isFocus && <div style={{marginBottom:16}}><Research L={L} lk={lk} ticker={ticker} stocks={allStocks} open={open} toggle={toggle} C={C} liveData={liveData} eqrData={eqrData} rdcfData={rdcfData}/></div>}
                <DeepResearchPanel L={L} lk={lk} onComplete={handleDeepResearchComplete} C={C}/>
              </div>
            );
            if (isFocus) return <Research L={L} lk={lk} ticker={ticker} stocks={allStocks} open={open} toggle={toggle} C={C} liveData={liveData} eqrData={eqrData} rdcfData={rdcfData}/>;
            if (isUniverse) return <UniverseStockView ticker={ticker} universeStocks={universeStocks} liveData={liveData} L={L} lk={lk} C={C} onDeepResearch={(tk)=>{setSearch(tk); setShowDeepResearch(true);}}/>;
            return <DeepResearchPanel L={L} lk={lk} onComplete={handleDeepResearchComplete} C={C}/>;
          })()}
          {tab==='tracker'  && <Tracker L={L} stocks={allStocks} C={C} predictions={predictions}/>}
          {tab==='watchlist'&& <Watchlist L={L} stocks={allStocks} C={C}/>}
          {tab==='system'   && <SystemTab L={L} C={C}/>}
        </div>
      </div>
    </div>
  );
}
