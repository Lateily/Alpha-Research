import { useState } from "react";
import { Search, TrendingUp, TrendingDown, Minus, ChevronDown, BarChart3,
         Shield, Zap, Globe, Eye, Target, Filter, Radio, Crosshair,
         AlertCircle, CheckCircle, ArrowUpRight, ArrowDownRight,
         Database, RefreshCw, Layers, BookOpen, Info, Calendar } from "lucide-react";

/* ── THEME ─────────────────────────────────────────────────────────────────── */
const C = { blue:'#4A90D9', gold:'#BFA76A', green:'#3D8B6E', red:'#C25450',
            dark:'#2C3E50', mid:'#7F8C8D', bg:'#FAFAF7', card:'#fff', border:'#E8E2D4',
            soft:'#F5F3ED' };
const S = {
  card:{ background:C.card, border:`1px solid ${C.border}`, borderRadius:10, marginBottom:14, overflow:'hidden' },
  cardHd:{ padding:'13px 16px', cursor:'pointer', display:'flex', justifyContent:'space-between',
           alignItems:'center', borderBottom:`1px solid ${C.border}` },
  cardBd:{ padding:'13px 16px' },
  row:{ display:'flex', alignItems:'center', gap:8 },
  flex:{ display:'flex' },
  tag:(c)=>({ fontSize:10, fontWeight:700, padding:'3px 8px', borderRadius:3,
               background:`${c}18`, color:c, border:`1px solid ${c}30` }),
  mono:{ fontFamily:'monospace' },
  label:{ fontSize:11, color:C.mid, fontWeight:600 },
  val:{ fontSize:13, fontWeight:700, color:C.dark },
  sec:{ fontSize:12, color:C.dark, lineHeight:1.7 },
};

/* ── DATA ───────────────────────────────────────────────────────────────────── */
const STOCKS = {
  '300308.SZ': {
    name:'中际旭创', en:'Innolight', sector:'AI Infra', dir:'LONG', vp:79, price:'¥138.50', mktcap:'¥184B',
    eqr:{ overall:'MED-HIGH', biz:'HIGH', variant:'MED', catalysts:'HIGH', risks:'MED' },
    pulse:{ e:'800G/1.6T demand peak. SiPh ramp inflection. Hyperscaler orders accelerating.', z:'800G/1.6T需求旺盛，硅光放量拐点，超大规模订单加速。' },
    biz:{ e:'① Problem: AI GPUs need >100Gbps per port; copper fails beyond 3m. ② Mechanism: Innolight converts electrical→optical (EO), transmits via fiber, back (OE). SiPh integrates EO/OE on-chip, cutting power 40%. ③ Money flow: Hyperscalers pay ¥1,100–2,200/transceiver × millions of ports × 3–5yr cycle. Top 3 = ~60% rev.', z:'① 问题：AI GPU每端口需100Gbps+，铜线3米外衰减失效。② 机制：光电转换+硅光一体集成，降低功耗40%。③ 资金流：超大规模客户每收发器¥1,100–2,200×百万端口。' },
    variant:{ e:'Market believes → 1.6T volume 2H 2026, SiPh gross margin 38%. → We believe → 1.6T qualifies Q2 2025; GM reaches 42% as SiPh mix hits 60%. → Mechanism → SiPh eliminates connectors; ByteDance/MSFT dual-source validation underway. → Right if → Q2 2025 revenue >¥4.2B and SiPh guidance raised. → Wrong if → 1.6T qualification slips to Q4 2025 OR hyperscaler CapEx cut >20%.', z:'市场认为→1.6T 2026下半年放量，硅光毛利38%。→ 我们认为→1.6T Q2 2025认证，毛利42%。→ 机制→硅光消除连接器，字节/微软双供认证中。→ 验证→Q2营收>¥42亿。→ 证伪→认证推迟或资本支出削减>20%。' },
    catalysts:[
      { e:'1.6T SiPh customer qualification (ByteDance/MSFT)', z:'1.6T硅光客户认证（字节/微软）', t:'Q2 2025', imp:'HIGH' },
      { e:'Q1 2025 earnings — SiPh mix > 50%', z:'Q1财报硅光占比>50%', t:'Apr 2025', imp:'HIGH' },
      { e:'State Grid power infra AI order', z:'国家电网AI电力基建订单', t:'2025', imp:'MED' },
    ],
    decomp:{ expectation_gap:{s:72,e:'Consensus underprices 1.6T speed',z:'共识低估1.6T进度'}, fundamental_acc:{s:80,e:'SiPh GM expansion accelerating',z:'硅光毛利快速扩张'}, narrative_shift:{s:65,e:'AI infra proxy re-rating',z:'AI基础设施重估'}, low_coverage:{s:55,e:'Limited sell-side SiPh model depth',z:'卖方硅光建模不足'}, catalyst_prox:{s:85,e:'Q2 qual event imminent',z:'Q2认证事件临近'} },
    risks:[{ e:'1.6T qualification delay beyond Q3 2025', z:'1.6T认证推迟至Q3+', p:'LOW', imp:'HIGH' },{ e:'Hyperscaler CapEx cut (recessionary)', z:'超大规模资本支出削减', p:'LOW', imp:'HIGH' },{ e:'SiPh yield ramp slower than guided', z:'硅光良率爬坡慢于指引', p:'MED', imp:'MED' }],
    fin:{ rev:'¥16.8B', revGr:'+47%', gm:'39%', pe:28, ev_ebitda:18, fcf:'¥2.1B' },
  },
  '700.HK': {
    name:'腾讯控股', en:'Tencent', sector:'Platform', dir:'LONG', vp:64, price:'HK$392', mktcap:'HK$3.8T',
    eqr:{ overall:'MED-HIGH', biz:'HIGH', variant:'MED-HIGH', catalysts:'MED', risks:'MED' },
    pulse:{ e:'WeChat AI monetisation underpriced. Buyback acceleration. State Council digital support.', z:'微信AI变现被低估。回购加速。国务院数字经济支持。' },
    biz:{ e:'① Problem: Digital attention fragmented; advertisers need reach, developers need distribution. ② Mechanism: WeChat closed-loop (communication+payments+mini-apps). Switching cost = 1.3B social graph + payment history. ③ Money flow: Advertisers pay HK$55–90 CPM. Gaming: 30% take on HK$200B. WePay: 0.6% per merchant txn.', z:'① 问题：数字注意力碎片化。② 机制：微信闭环生态，切换成本=13亿用户社交图谱+支付记录。③ 资金流：广告CPM 55–90港元，游戏抽成30%，支付0.6%。' },
    variant:{ e:'Market believes → AI investment is a drag; gaming recovery capped at 10%; buyback is price floor only. → We believe → Weixin AI (keyboard+search+mini-app) lifts ARPU 15–20% by 2026; gaming recovers 18%+ driven by overseas. → Mechanism → AI features deployed to 1.3B users with zero marginal distribution cost. → Right if → 2025 online ads >HK$120B; Weixin AI MAU >200M. → Wrong if → Regulatory cap on gaming minors extended OR macro consumption weakens sharply.', z:'市场认为→AI是拖累；游戏复苏封顶10%；回购只是底价。→ 我们认为→微信AI将ARPU提升15-20%；游戏海外驱动18%+。→ 验证→2025在线广告>1200亿港元。→ 证伪→游戏监管扩大或消费急剧恶化。' },
    catalysts:[{ e:'Weixin AI feature launch metrics (MAU/ARPU)', z:'微信AI功能上线数据', t:'Q2 2025', imp:'HIGH' },{ e:'Q4 2024 earnings — gaming international', z:'Q4财报海外游戏', t:'Mar 2025', imp:'MED' }],
    decomp:{ expectation_gap:{s:68,e:'AI monetisation not in consensus',z:'AI变现未入共识'}, fundamental_acc:{s:70,e:'Gaming + ads dual recovery',z:'游戏+广告双复苏'}, narrative_shift:{s:75,e:'State endorsement changes narrative',z:'国家背书改变叙事'}, low_coverage:{s:40,e:'Well-covered stock',z:'覆盖充分'}, catalyst_prox:{s:60,e:'AI launch timing uncertain',z:'AI上线时机不确定'} },
    risks:[{ e:'Regulatory re-tightening on gaming', z:'游戏监管重新收紧', p:'MED', imp:'HIGH' },{ e:'Macro consumption weakness', z:'宏观消费疲软', p:'MED', imp:'MED' }],
    fin:{ rev:'HK$660B', revGr:'+8%', gm:'52%', pe:16, ev_ebitda:12, fcf:'HK$180B' },
  },
  '9999.HK': {
    name:'网易', en:'NetEase', sector:'Gaming', dir:'LONG', vp:58, price:'HK$152', mktcap:'HK$207B',
    eqr:{ overall:'MED', biz:'MED-HIGH', variant:'MED', catalysts:'MED', risks:'MED' },
    pulse:{ e:'Stable gaming IP monetisation undervalued. Japan market penetration accelerating.', z:'稳定游戏IP变现被低估。日本市场渗透加速。' },
    biz:{ e:'① Problem: Gaming hits have short lifecycles; studios need durable IP revenue. ② Mechanism: NetEase builds franchise ecosystems (Fantasy Westward Journey 20yr). Deep in-game economy creates daily engagement loops. ③ Money flow: IAP (in-app purchase) at 30–40% GM; licensing fees from overseas publishers.', z:'① 问题：游戏爆款生命周期短。② 机制：网易构建IP生态（梦幻西游20年），深度游戏经济创造日常留存。③ 资金流：应用内购30-40%毛利；海外授权费。' },
    variant:{ e:'Market believes → NetEase is ex-growth; Blizzard loss is permanent damage. → We believe → Japan market (Naraka, Marvel Rivals) adds ¥4B incremental revenue by 2026; Blizzard titles replaceable. → Mechanism → Japanese gaming market lacks domestic multiplayer competition. → Right if → Japan MAU >3M by Q3 2025. → Wrong if → Marvel Rivals DAU drops below 2M.', z:'市场认为→网易增长停滞；暴雪流失永久损伤。→ 我们认为→日本市场(永劫/漫威对决)增量营收¥40亿。→ 验证→日本MAU>300万。→ 证伪→漫威对决DAU低于200万。' },
    catalysts:[{ e:'Marvel Rivals Season 2 launch metrics', z:'漫威对决S2上线数据', t:'Q2 2025', imp:'HIGH' },{ e:'Japan revenue disclosure in Q1 results', z:'Q1财报日本营收披露', t:'May 2025', imp:'MED' }],
    decomp:{ expectation_gap:{s:62,e:'Japan TAM underestimated',z:'日本TAM被低估'}, fundamental_acc:{s:55,e:'IP economics improving',z:'IP经济学改善'}, narrative_shift:{s:50,e:'Post-Blizzard recovery narrative',z:'后暴雪复苏叙事'}, low_coverage:{s:45,e:'Moderate coverage',z:'覆盖适中'}, catalyst_prox:{s:65,e:'S2 launch imminent',z:'S2即将发布'} },
    risks:[{ e:'Marvel Rivals user retention falls', z:'漫威对决留存下降', p:'MED', imp:'HIGH' },{ e:'China gaming licence delays', z:'国内版号延迟', p:'LOW', imp:'MED' }],
    fin:{ rev:'¥102B', revGr:'+7%', gm:'63%', pe:14, ev_ebitda:9, fcf:'¥28B' },
  },
  '6160.HK': {
    name:'百济神州', en:'BeiGene', sector:'Biotech', dir:'LONG', vp:71, price:'HK$108', mktcap:'HK$149B',
    eqr:{ overall:'MED-HIGH', biz:'MED-HIGH', variant:'MED', catalysts:'HIGH', risks:'MED' },
    pulse:{ e:'Brukinsa EU market share curve faster than US models. Profitability pull-forward likely Q3 2026.', z:'泽布替尼欧盟份额爬坡快于美国模型。盈利时间线可能提前至Q3 2026。' },
    biz:{ e:'① Problem: CLL/MCL patients need BTK inhibitors with better cardiac safety than ibrutinib. ② Mechanism: Brukinsa (zanubrutinib) = 2nd-gen BTK inhibitor, >99% occupancy, ALPINE trial proved superiority. ③ Money flow: $15,000/patient/month US. 40+ country ex-China rollout. Royalties from BMS partnership.', z:'① 问题：CLL/MCL患者需要比伊布替尼心脏安全性更好的BTK抑制剂。② 机制：泽布替尼=第二代BTK抑制剂，ALPINE试验证明优越性。③ 资金流：美国每患者每月1.5万美元，40+国家推广。' },
    variant:{ e:'Market believes → EU 2L CLL share = 32%; profitability Q4 2026. → We believe → EU share reaches 40% by end 2025 driven by faster EU oncologist adoption; profitability Q3 2026. → Mechanism → French/German prescriber data shows +28% QoQ scripts Q4 2025. → Right if → Q2 2025 EU revenue >$380M. → Wrong if → IRA negotiation cuts US price >30%.', z:'市场认为→欧盟2L CLL份额32%；Q4 2026盈利。→ 我们认为→欧盟份额40%，Q3盈利提前。→ 验证→Q2欧盟营收>3.8亿美元。→ 证伪→IRA谈判削价>30%。' },
    catalysts:[{ e:'Q1 2025 EU revenue disclosure', z:'Q1欧盟营收披露', t:'May 2025', imp:'HIGH' },{ e:'GAAP profitability announcement', z:'GAAP盈利公告', t:'Q3 2026', imp:'HIGH' }],
    decomp:{ expectation_gap:{s:74,e:'EU adoption speed mismodelled',z:'欧盟采纳速度建模错误'}, fundamental_acc:{s:68,e:'Revenue ramp non-linear',z:'营收爬坡非线性'}, narrative_shift:{s:60,e:'Profitability inflection re-rates stock',z:'盈利拐点重估股价'}, low_coverage:{s:50,e:'Good coverage but EU undermodelled',z:'覆盖尚可但欧盟建模不足'}, catalyst_prox:{s:80,e:'Q1 results in 4 weeks',z:'Q1财报4周内'} },
    risks:[{ e:'IRA Brukinsa price negotiation', z:'IRA泽布替尼价格谈判', p:'MED', imp:'HIGH' },{ e:'PD-1 combo Phase III futility', z:'PD-1联合Phase III无效', p:'LOW', imp:'MED' }],
    fin:{ rev:'$3.2B', revGr:'+63%', gm:'85%', pe:'NM', ev_ebitda:'NM', fcf:'-$0.4B' },
  },
  '002594.SZ': {
    name:'比亚迪', en:'BYD', sector:'EV/Auto', dir:'LONG', vp:52, price:'¥298', mktcap:'¥866B',
    eqr:{ overall:'MED', biz:'HIGH', variant:'MED', catalysts:'MED', risks:'MED' },
    pulse:{ e:'Overseas EV infrastructure building. DM5 hybrid tech moat widening. EM exposure underestimated.', z:'海外EV基础设施布局。DM5混动技术护城河扩大。新兴市场敞口被低估。' },
    biz:{ e:'① Problem: ICE vehicles face regulatory phase-out; consumers need affordable EVs with range anxiety solved. ② Mechanism: BYD vertical integration (Blade battery + e-Platform 3.0 + in-house semiconductor). DM5 PHEV = 2,000km range. ③ Money flow: Vehicle sales at ¥120K–400K ASP × 3M+ units/yr. Battery supply to VW/Toyota. IGBT/SiC chip licensing.', z:'① 问题：燃油车面临政策淘汰，消费者需要解决里程焦虑的平价电动车。② 机制：刀片电池+e平台3.0+自研芯片垂直整合。DM5混动续航2000公里。③ 资金流：12-40万均价×300万+台/年+电池供应大众/丰田。' },
    variant:{ e:'Market believes → BYD is China-only; margin pressure from price war. → We believe → EM export (Brazil/SEA/MENA) adds 400K units by 2026; DM5 enables premium pricing floors. → Mechanism → Local assembly partnerships bypass tariffs; DM5 has no Western equivalent. → Right if → 2025 export >350K units. → Wrong if → EU tariffs >35% AND Brazil imposes local content rules.', z:'市场认为→比亚迪只在中国；价格战压缩利润。→ 我们认为→新兴市场出口(巴西/东南亚/中东)增加40万台。→ 验证→2025出口>35万台。→ 证伪→欧盟关税>35%且巴西本地化要求。' },
    catalysts:[{ e:'Brazil factory opening + local pricing', z:'巴西工厂开业+本地定价', t:'Q2 2025', imp:'MED' },{ e:'DM6 announcement (3rd-gen hybrid)', z:'DM6发布（第三代混动）', t:'H2 2025', imp:'MED' }],
    decomp:{ expectation_gap:{s:55,e:'EM volume undermodelled',z:'新兴市场产量建模不足'}, fundamental_acc:{s:60,e:'DM5 ASP holding up',z:'DM5均价维持'}, narrative_shift:{s:45,e:'Global EV leader narrative building',z:'全球EV领导者叙事构建'}, low_coverage:{s:35,e:'High coverage stock',z:'高覆盖股票'}, catalyst_prox:{s:50,e:'Brazil opening in weeks',z:'巴西工厂数周内开业'} },
    risks:[{ e:'EU/US tariff escalation on Chinese EVs', z:'欧美对中国EV加征关税', p:'HIGH', imp:'HIGH' },{ e:'China EV price war deepens margins', z:'中国EV价格战加剧', p:'MED', imp:'MED' }],
    fin:{ rev:'¥770B', revGr:'+28%', gm:'23%', pe:22, ev_ebitda:14, fcf:'¥38B' },
  },
};

const SCANNER = {
  regime:{ status:'Permissive', color:C.green, e:'China policy in expansion mode. Risk-on for quality growth. A-share liquidity improving.', z:'中国政策扩张模式。优质成长风险偏好提升。A股流动性改善。' },
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

const PEERS = [
  { pair:'Innolight vs Eoptolink', ticker:'300308 vs 603488', div:'VP 79 vs 45', corr:0.82, e:'SiPh premium vs margin compression. Pair trade on qualification delta.', z:'硅光溢价vs利润率压缩。认证差异配对交易。' },
  { pair:'Tencent vs Alibaba', ticker:'700 vs 9988', div:'VP 64 vs 48', corr:0.75, e:'WeChat AI vs restructuring overhang. Long TENCENT / short BABA.', z:'微信AI vs 重组阴影。做多腾讯/做空阿里。' },
];

/* ── MINI COMPONENTS ─────────────────────────────────────────────────────── */
const Tag = ({ text, c=C.blue }) => <span style={S.tag(c)}>{text}</span>;
const EQR = ({ lvl }) => {
  const c = lvl==='HIGH'?C.green : lvl==='MED-HIGH'?C.blue : lvl==='MED'?C.gold : C.red;
  return <span style={{...S.tag(c), fontSize:9}}>EQR: {lvl}</span>;
};
const TI = ({ t }) => t==='up' ? <TrendingUp size={13} style={{color:C.green}} />
                   : t==='down' ? <TrendingDown size={13} style={{color:C.red}} />
                   : <Minus size={13} style={{color:C.mid}} />;
const Pill = ({ n, label, c=C.blue }) => (
  <div style={{textAlign:'center', padding:'8px 12px', background:`${c}10`, borderRadius:8}}>
    <div style={{fontSize:20, fontWeight:700, color:c}}>{n}</div>
    <div style={{fontSize:10, color:C.mid}}>{label}</div>
  </div>
);

const Card = ({ title, sub, open, onToggle, children }) => (
  <div style={S.card}>
    <div style={S.cardHd} onClick={onToggle}>
      <div>
        <div style={{fontSize:13, fontWeight:600, color:C.dark}}>{title}</div>
        {sub && <div style={{fontSize:10, color:C.mid, marginTop:1}}>{sub}</div>}
      </div>
      <ChevronDown size={15} style={{color:C.mid, transform:open?'rotate(180deg)':'', transition:'transform .2s', flexShrink:0}} />
    </div>
    {open && <div style={S.cardBd}>{children}</div>}
  </div>
);

const VPRing = ({ score, sz=90 }) => {
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

const Bar = ({ v, max, c=C.blue }) => (
  <div style={{display:'flex', alignItems:'center', gap:6}}>
    <div style={{width:50, height:4, background:C.border, borderRadius:2, overflow:'hidden'}}>
      <div style={{height:'100%', background:c, width:`${Math.min(100,(v/max)*100)}%`}}/>
    </div>
    <span style={{fontSize:10, fontFamily:'monospace', color:c, fontWeight:600}}>{v}</span>
  </div>
);

/* ── TAB RENDERERS ────────────────────────────────────────────────────────── */
function Scanner({ L, open, toggle }) {
  return (
    <div>
      <div style={{...S.row, justifyContent:'space-between', marginBottom:14}}>
        <div>
          <div style={{fontSize:10, fontWeight:700, letterSpacing:'.1em', color:C.mid}}>{L('MORNING SCANNER','早间扫描')}</div>
          <div style={{fontSize:18, fontWeight:700, color:C.dark}}>{L(SCANNER.date.e, SCANNER.date.z)}</div>
        </div>
        <Tag text={SCANNER.regime.status} c={SCANNER.regime.color}/>
      </div>

      <div style={{background:`${SCANNER.regime.color}10`, border:`1px solid ${SCANNER.regime.color}30`, borderRadius:8, padding:12, marginBottom:14, fontSize:12, color:C.dark, lineHeight:1.7}}>
        <Radio size={13} style={{color:SCANNER.regime.color, marginRight:6}}/>
        <strong>{L('Regime:','制度:')}</strong> {L(SCANNER.regime.e, SCANNER.regime.z)}
      </div>

      <Card title={L('Factor Momentum','因子动量')} open={open.factors} onToggle={()=>toggle('factors')}>
        <div style={{display:'grid', gridTemplateColumns:'repeat(5,1fr)', gap:8}}>
          {SCANNER.factors.map((f,i) => (
            <div key={i} style={{background:C.soft, padding:10, borderRadius:6, textAlign:'center'}}>
              <div style={{fontSize:10, color:C.mid, fontWeight:600}}>{f.name}</div>
              <div style={{fontSize:18, fontWeight:700, color:f.val>60?C.green:f.val>40?C.gold:C.red, marginTop:2}}>{f.val}</div>
              <TI t={f.t}/>
            </div>
          ))}
        </div>
      </Card>

      <Card title={L('Screening Funnel','筛选漏斗')} sub="L0→L4" open={open.funnel} onToggle={()=>toggle('funnel')}>
        {SCANNER.funnel.map((f,i) => (
          <div key={i} style={{...S.row, padding:'7px 0', borderBottom:i<SCANNER.funnel.length-1?`1px solid ${C.border}`:'none'}}>
            <div style={{width:90, fontSize:11, fontWeight:600, color:C.blue}}>{f.s}</div>
            <div style={{width:50, fontSize:14, fontWeight:700, color:C.dark, fontFamily:'monospace'}}>{f.n}</div>
            <div style={{fontSize:10, color:C.mid}}>{f.r}</div>
          </div>
        ))}
      </Card>

      <Card title={L('Pair Trade Ideas','配对交易')} open={open.pairs} onToggle={()=>toggle('pairs')}>
        {PEERS.map((p,i) => (
          <div key={i} style={{background:C.soft, borderRadius:8, padding:12, marginBottom:i<PEERS.length-1?10:0}}>
            <div style={{...S.row, justifyContent:'space-between', marginBottom:6}}>
              <div style={{fontSize:12, fontWeight:700, color:C.dark}}>{p.pair}</div>
              <Tag text={p.div} c={C.blue}/>
            </div>
            <div style={{fontSize:11, color:C.mid, marginBottom:4}}>corr {p.corr} · {p.ticker}</div>
            <div style={{fontSize:11, color:C.dark, lineHeight:1.6}}>{L(p.e, p.z)}</div>
          </div>
        ))}
      </Card>
    </div>
  );
}

function Screener({ L, onSelect }) {
  const stocks = Object.entries(STOCKS);
  return (
    <div>
      <div style={{...S.row, marginBottom:14}}>
        <Filter size={14} style={{color:C.mid}}/>
        <span style={{fontSize:10, fontWeight:700, letterSpacing:'.1em', color:C.mid}}>{L('SCREENER — 5 POSITIONS','筛选器 — 5 持仓')}</span>
      </div>
      <div style={{background:C.soft, borderRadius:8, marginBottom:14, overflow:'hidden'}}>
        <table style={{width:'100%', borderCollapse:'collapse', fontSize:12}}>
          <thead>
            <tr style={{borderBottom:`1px solid ${C.border}`}}>
              {[L('Ticker','代码'),L('Name','名称'),L('Sector','板块'),L('Dir','方向'),'VP',L('Price','价格'),L('Mkt Cap','市值'),L('Rev Gr','营收增'),L('GM','毛利'),L('P/E','市盈率')].map((h,i)=>(
                <th key={i} style={{padding:'8px 10px', textAlign:i>4?'right':'left', fontSize:10, fontWeight:700, color:C.mid, letterSpacing:'.05em'}}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {stocks.map(([tk,s],i) => (
              <tr key={tk} onClick={()=>onSelect(tk)}
                style={{borderBottom:`1px solid ${C.border}`, cursor:'pointer', background:i%2?C.soft:C.card, ':hover':{background:`${C.blue}08`}}}>
                <td style={{padding:'9px 10px', fontFamily:'monospace', fontWeight:700, color:C.blue, fontSize:11}}>{tk}</td>
                <td style={{padding:'9px 10px'}}>
                  <div style={{fontWeight:600, color:C.dark}}>{s.name}</div>
                  <div style={{fontSize:10, color:C.mid}}>{s.en}</div>
                </td>
                <td style={{padding:'9px 10px'}}><Tag text={s.sector} c={C.mid}/></td>
                <td style={{padding:'9px 10px'}}><Tag text={s.dir} c={s.dir==='LONG'?C.green:C.red}/></td>
                <td style={{padding:'9px 10px'}}>
                  <div style={{display:'flex', alignItems:'center', gap:6}}>
                    <VPRing score={s.vp} sz={36}/>
                  </div>
                </td>
                <td style={{padding:'9px 10px', textAlign:'right', fontFamily:'monospace', fontWeight:600, color:C.dark}}>{s.price}</td>
                <td style={{padding:'9px 10px', textAlign:'right', fontFamily:'monospace', fontSize:11, color:C.mid}}>{s.mktcap}</td>
                <td style={{padding:'9px 10px', textAlign:'right', fontWeight:600, color:s.fin.revGr.startsWith('+')?C.green:C.red}}>{s.fin.revGr}</td>
                <td style={{padding:'9px 10px', textAlign:'right', color:C.dark}}>{s.fin.gm}</td>
                <td style={{padding:'9px 10px', textAlign:'right', color:C.dark}}>{s.fin.pe}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div style={{fontSize:10, color:C.mid, textAlign:'center'}}>
        {L('Click any row to open Research','点击任意行打开研究报告')} · EQR + variant perception + catalysts
      </div>
    </div>
  );
}

const VP_KEYS = [
  { k:'expectation_gap', w:30, label:'Expectation Gap' },
  { k:'fundamental_acc', w:25, label:'Fundamental Acc.' },
  { k:'narrative_shift', w:20, label:'Narrative Shift' },
  { k:'low_coverage',   w:15, label:'Low Coverage' },
  { k:'catalyst_prox',  w:10, label:'Catalyst Proximity' },
];

function Research({ L, ticker, open, toggle }) {
  if (!ticker) return (
    <div style={{display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center', height:300, color:C.mid, gap:12}}>
      <Crosshair size={36} style={{color:C.border}}/>
      <div style={{fontSize:13}}>{L('Select a stock from Screener','请从筛选器选择一只股票')}</div>
    </div>
  );
  const s = STOCKS[ticker];
  const vzParts = L(s.variant.e, s.variant.z).split('→');
  const vzLabels = [L('Market believes','市场认为'), L('We believe','我们认为'), L('Mechanism','机制'), L('✓ Right if','✓ 验证'), L('✗ Wrong if','✗ 证伪')];
  const vzColors = [C.mid, C.blue, '#7B6BA5', C.green, C.red];

  return (
    <div>
      {/* Header */}
      <div style={{...S.row, justifyContent:'space-between', marginBottom:14, flexWrap:'wrap', gap:8}}>
        <div>
          <div style={{...S.row, gap:8, marginBottom:4}}>
            <span style={{fontSize:20, fontWeight:800, color:C.dark}}>{s.name}</span>
            <span style={{fontSize:14, color:C.mid}}>{s.en}</span>
            <Tag text={s.dir} c={s.dir==='LONG'?C.green:C.red}/>
            <Tag text={s.sector} c={C.mid}/>
          </div>
          <div style={{...S.row, gap:6, flexWrap:'wrap'}}>
            <EQR lvl={s.eqr.overall}/>
            {['biz','variant','catalysts','risks'].map(k=>(
              <span key={k} style={{fontSize:9, color:C.mid}}>{k}:<EQR lvl={s.eqr[k]}/></span>
            ))}
          </div>
        </div>
        <div style={{...S.row, gap:16}}>
          <VPRing score={s.vp} sz={72}/>
          <div>
            <div style={{fontSize:11, color:C.mid, marginBottom:4}}>{L('Financials','财务')}</div>
            {[['Rev',s.fin.rev],['Growth',s.fin.revGr],['GM',s.fin.gm],['P/E',s.fin.pe]].map(([l,v])=>(
              <div key={l} style={{...S.row, gap:6, marginBottom:2}}>
                <span style={{fontSize:10, color:C.mid, width:42}}>{l}</span>
                <span style={{fontSize:11, fontWeight:700, fontFamily:'monospace', color:C.dark}}>{v}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Pulse */}
      <div style={{background:`${C.blue}08`, border:`1px solid ${C.blue}25`, borderRadius:8, padding:12, marginBottom:14, fontSize:12, lineHeight:1.7, color:C.dark}}>
        <Zap size={12} style={{color:C.gold, marginRight:6}}/><strong>{L('Pulse:','脉搏:')}</strong> {L(s.pulse.e, s.pulse.z)}
      </div>

      {/* AI Disclaimer */}
      <div style={{background:`${C.gold}08`, border:`1px solid ${C.gold}30`, borderRadius:6, padding:'8px 12px', marginBottom:14, fontSize:10, color:C.mid, lineHeight:1.6}}>
        <Info size={11} style={{color:C.gold, marginRight:5}}/>{L('AI-generated evidence & signals only. Not investment advice. Human judgment required.','AI生成证据和信号，仅供参考。非投资建议。需要人工判断。')}
      </div>

      {/* Business Model */}
      <Card title={L('Business Model','商业模型')} sub="① Problem → ② Mechanism → ③ Money Flow" open={open.biz} onToggle={()=>toggle('biz')}>
        {L(s.biz.e, s.biz.z).split(/①|②|③/).filter(Boolean).map((seg,i)=>(
          <div key={i} style={{display:'flex', gap:10, marginBottom:10}}>
            <span style={{fontWeight:800, fontSize:16, color:[C.blue,'#7B6BA5',C.green][i], flexShrink:0, width:20}}>{'①②③'[i]}</span>
            <span style={{fontSize:12, color:C.dark, lineHeight:1.7}}>{seg.trim()}</span>
          </div>
        ))}
      </Card>

      {/* Variant Perception */}
      <Card title="Variant Perception" sub="Market believes → We believe → Mechanism → Right if → Wrong if" open={open.variant} onToggle={()=>toggle('variant')}>
        {vzParts.filter(Boolean).map((seg,i)=>(
          <div key={i} style={{borderLeft:`3px solid ${vzColors[i]||C.mid}`, paddingLeft:10, marginBottom:10}}>
            <div style={{fontSize:10, fontWeight:700, color:vzColors[i]||C.mid, marginBottom:2}}>{vzLabels[i]||'—'}</div>
            <div style={{fontSize:12, color:C.dark, lineHeight:1.6}}>{seg.trim()}</div>
          </div>
        ))}
      </Card>

      {/* VP Decomposition */}
      <Card title={L('VP Score Decomposition','VP评分分解')} sub={`Total: ${s.vp}/100`} open={open.vp} onToggle={()=>toggle('vp')}>
        {VP_KEYS.map(({k,w,label})=>{
          const d = s.decomp[k]; if(!d) return null;
          const c = d.s>=70?C.green:d.s>=50?C.blue:d.s>=30?C.gold:C.red;
          return (
            <div key={k} style={{marginBottom:10}}>
              <div style={{...S.row, justifyContent:'space-between', marginBottom:3}}>
                <span style={{fontSize:11, color:C.dark}}>{label}</span>
                <span style={{fontSize:10, color:C.mid}}>wt {w}%</span>
              </div>
              <Bar v={d.s} max={100} c={c}/>
              <div style={{fontSize:10, color:C.mid, marginTop:2}}>{L(d.e,d.z)}</div>
            </div>
          );
        })}
      </Card>

      {/* Catalysts */}
      <Card title={L('Catalysts','催化剂')} open={open.cats} onToggle={()=>toggle('cats')}>
        {s.catalysts.map((c,i)=>(
          <div key={i} style={{...S.row, justifyContent:'space-between', padding:'7px 0', borderBottom:i<s.catalysts.length-1?`1px solid ${C.border}`:'none', flexWrap:'wrap', gap:6}}>
            <div style={{flex:1, fontSize:12, color:C.dark}}>{L(c.e, c.z)}</div>
            <div style={{...S.row, gap:6}}>
              <Tag text={c.t} c={C.mid}/>
              <Tag text={c.imp} c={c.imp==='HIGH'?C.green:C.gold}/>
            </div>
          </div>
        ))}
      </Card>

      {/* Risks */}
      <Card title={L('Key Risks','关键风险')} open={open.risks} onToggle={()=>toggle('risks')}>
        {s.risks.map((r,i)=>(
          <div key={i} style={{...S.row, gap:10, padding:'7px 0', borderBottom:i<s.risks.length-1?`1px solid ${C.border}`:'none', flexWrap:'wrap'}}>
            <AlertCircle size={13} style={{color:r.p==='HIGH'?C.red:C.gold, flexShrink:0}}/>
            <div style={{flex:1, fontSize:12, color:C.dark}}>{L(r.e, r.z)}</div>
            <div style={{...S.row, gap:4}}>
              <Tag text={`P:${r.p}`} c={r.p==='HIGH'?C.red:C.gold}/>
              <Tag text={`I:${r.imp}`} c={r.imp==='HIGH'?C.red:C.gold}/>
            </div>
          </div>
        ))}
      </Card>

      {/* TA Pending */}
      <Card title={L('Technical Analysis','技术分析')} sub={L('Pending AKShare integration','等待AKShare接入')} open={open.ta} onToggle={()=>toggle('ta')}>
        <div style={{fontSize:11, color:C.mid, lineHeight:1.8}}>
          <div>⏳ {L('Framework ready: 20/60d MA · RSI(14) · MACD · Volume spikes','框架已就绪：20/60日均线 · RSI(14) · MACD · 成交量异动')}</div>
          <div style={{marginTop:6, fontSize:10}}>
            <Tag text={L('Awaiting live data feed','等待实时数据接入')} c={C.gold}/>
          </div>
        </div>
      </Card>
    </div>
  );
}

function Tracker({ L }) {
  const stocks = Object.values(STOCKS);
  return (
    <div>
      <div style={{...S.row, marginBottom:14}}>
        <Target size={14} style={{color:C.mid}}/>
        <span style={{fontSize:10, fontWeight:700, letterSpacing:'.1em', color:C.mid}}>{L('POSITION TRACKER','持仓追踪')}</span>
      </div>
      <div style={{display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(200px,1fr))', gap:12}}>
        {stocks.map((s,i)=>(
          <div key={i} style={{...S.card, padding:14}}>
            <div style={{...S.row, justifyContent:'space-between', marginBottom:8}}>
              <div>
                <div style={{fontWeight:700, color:C.dark}}>{s.name}</div>
                <div style={{fontSize:10, color:C.mid}}>{s.en}</div>
              </div>
              <Tag text={s.dir} c={s.dir==='LONG'?C.green:C.red}/>
            </div>
            <div style={{...S.row, justifyContent:'space-between', marginBottom:8}}>
              <VPRing score={s.vp} sz={52}/>
              <div style={{textAlign:'right'}}>
                <div style={{fontSize:16, fontWeight:700, color:C.dark}}>{s.price}</div>
                <div style={{fontSize:11, color:s.fin.revGr.startsWith('+')?C.green:C.red}}>{s.fin.revGr}</div>
              </div>
            </div>
            <EQR lvl={s.eqr.overall}/>
          </div>
        ))}
      </div>
    </div>
  );
}

function Watchlist({ L }) {
  const candidates = [
    { name:'寒武纪', en:'Cambricon', tk:'688256.SH', why:L('AI chip domestic substitute play, SMIC 7nm ramp','国产AI芯片替代，SMIC 7nm爬坡'), vp:44, status:'monitoring' },
    { name:'中芯国际', en:'SMIC', tk:'688981.SH', why:L('Foundry capacity + mature node capex cycle inflection','先进封装+成熟节点资本周期拐点'), vp:38, status:'monitoring' },
    { name:'赛力斯', en:'Seres', tk:'601127.SH', why:L('Huawei AITO premium EV margin expansion thesis','华为AITO高端EV利润率扩张'), vp:41, status:'watching' },
  ];
  return (
    <div>
      <div style={{...S.row, marginBottom:14}}>
        <Eye size={14} style={{color:C.mid}}/>
        <span style={{fontSize:10, fontWeight:700, letterSpacing:'.1em', color:C.mid}}>{L('WATCHLIST — CANDIDATES','关注列表 — 候选')}</span>
      </div>
      {candidates.map((c,i)=>(
        <div key={i} style={{...S.card, padding:14}}>
          <div style={{...S.row, justifyContent:'space-between', marginBottom:8}}>
            <div style={{...S.row, gap:8}}>
              <span style={{fontWeight:700, color:C.dark}}>{c.name}</span>
              <span style={{fontSize:10, color:C.mid}}>{c.en} · {c.tk}</span>
            </div>
            <div style={{...S.row, gap:6}}>
              <Tag text={c.status} c={c.status==='monitoring'?C.blue:C.gold}/>
              <div style={{...S.row, gap:4}}><VPRing score={c.vp} sz={32}/></div>
            </div>
          </div>
          <div style={{fontSize:11, color:C.dark, lineHeight:1.6}}>{c.why}</div>
        </div>
      ))}
    </div>
  );
}

function SystemTab({ L }) {
  const layers = [
    { l:'L0', n:L('Data Ingestion + Calendar','数据摄取+日历'), c:C.mid, status:'live' },
    { l:'L1', n:L('Security Master','标的主数据'), c:C.gold, status:'live' },
    { l:'L2', n:L('Daily Screening Engine','每日筛选引擎'), c:C.blue, status:'integrated' },
    { l:'L3', n:L('LLM Research Builder','LLM研究构建'), c:C.red, status:'integrated' },
    { l:'L4', n:L('VP Score + Watchlist','VP评分+关注列表'), c:C.green, status:'integrated' },
  ];
  return (
    <div>
      <div style={{...S.row, marginBottom:14}}>
        <Layers size={14} style={{color:C.mid}}/>
        <span style={{fontSize:10, fontWeight:700, letterSpacing:'.1em', color:C.mid}}>{L('5-LAYER ARCHITECTURE','五层架构')}</span>
      </div>
      {layers.map((l,i)=>(
        <div key={i} style={{...S.card, padding:12, borderLeft:`4px solid ${l.c}`}}>
          <div style={{...S.row, justifyContent:'space-between'}}>
            <div style={{...S.row, gap:8}}>
              <span style={{fontFamily:'monospace', fontWeight:800, color:l.c}}>{l.l}</span>
              <span style={{fontSize:12, fontWeight:600, color:C.dark}}>{l.n}</span>
            </div>
            <Tag text={l.status} c={l.status==='live'?C.green:C.blue}/>
          </div>
        </div>
      ))}
      <div style={{marginTop:14, padding:12, background:C.soft, borderRadius:8, fontSize:11, color:C.mid, lineHeight:1.8}}>
        <div><strong>VP Formula:</strong> 30% Expectation Gap + 25% Fundamental Acc + 20% Narrative Shift + 15% Low Coverage + 10% Catalyst Proximity</div>
        <div><strong>EV Formula:</strong> (P_win × Upside) − (P_loss × Downside)</div>
        <div><strong>Alpha Engines:</strong> A=Earnings Surprise (30) · B=Multiple Expansion (40) · C=Capital Revaluation (30)</div>
      </div>
    </div>
  );
}

/* ── DASHBOARD ────────────────────────────────────────────────────────────── */
export default function Dashboard() {
  const [lang, setLang] = useState('en');
  const [tab, setTab] = useState('scanner');
  const [ticker, setTicker] = useState(null);
  const [search, setSearch] = useState('');
  const [open, setOpen] = useState({factors:true, funnel:true, pairs:false, biz:true, variant:true, vp:true, cats:true, risks:false, ta:false});

  const L = (e,z) => lang==='en' ? e : z;
  const toggle = k => setOpen(p=>({...p,[k]:!p[k]}));
  const goStock = tk => { setTicker(tk); setTab('research'); };

  const handleSearch = () => {
    const q = search.toLowerCase().trim();
    const found = Object.entries(STOCKS).find(([tk,s]) =>
      tk.toLowerCase().includes(q) || s.name.includes(q) || s.en.toLowerCase().includes(q)
    );
    if (found) goStock(found[0]);
  };

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
      <div style={{width:160, background:C.card, borderRight:`1px solid ${C.border}`, display:'flex', flexDirection:'column', flexShrink:0}}>
        <div style={{padding:'14px 14px 10px', borderBottom:`1px solid ${C.border}`}}>
          <div style={{fontSize:22, fontWeight:800, color:C.blue, letterSpacing:'-.02em'}}>AR</div>
          <div style={{fontSize:8, color:C.mid, letterSpacing:'.1em', marginTop:1}}>ALPHA RESEARCH v5.2</div>
        </div>
        <div style={{flex:1, paddingTop:4}}>
          {TABS.map(t=>(
            <button key={t.id} onClick={()=>setTab(t.id)} style={{
              width:'100%', padding:'9px 12px', display:'flex', alignItems:'center', gap:8,
              border:'none', background:tab===t.id?`${C.blue}10`:'transparent', cursor:'pointer',
              color:tab===t.id?C.blue:C.mid, fontSize:12, fontWeight:tab===t.id?700:400,
              borderLeft:`3px solid ${tab===t.id?C.blue:'transparent'}`, textAlign:'left',
              transition:'all .15s',
            }}>
              {t.icon}<span>{t.label}</span>
            </button>
          ))}
        </div>
        <div style={{padding:'10px 12px', borderTop:`1px solid ${C.border}`, fontSize:9, color:C.mid}}>
          {L('Evidence only. Not advice.','仅证据。非建议。')}
        </div>
      </div>

      {/* Main */}
      <div style={{flex:1, display:'flex', flexDirection:'column', overflow:'hidden'}}>
        {/* Topbar */}
        <div style={{background:C.card, borderBottom:`1px solid ${C.border}`, padding:'8px 16px', display:'flex', justifyContent:'space-between', alignItems:'center', gap:12}}>
          <div style={{display:'flex', gap:6, alignItems:'center', flex:1, maxWidth:380}}>
            <input value={search} onChange={e=>setSearch(e.target.value)}
              onKeyDown={e=>e.key==='Enter'&&handleSearch()}
              placeholder={L('Search ticker / name…','搜索代码/名称…')}
              style={{flex:1, padding:'5px 10px', border:`1px solid ${C.border}`, borderRadius:6, fontSize:12, outline:'none', background:C.soft}}/>
            <button onClick={handleSearch} style={{padding:'5px 10px', background:C.blue, color:'#fff', border:'none', borderRadius:6, cursor:'pointer', fontSize:12}}>
              <Search size={13}/>
            </button>
          </div>
          <div style={{display:'flex', gap:3, background:C.soft, padding:2, borderRadius:5}}>
            {['en','zh'].map(l=>(
              <button key={l} onClick={()=>setLang(l)} style={{
                padding:'3px 10px', border:'none', background:lang===l?C.blue:'transparent',
                color:lang===l?'#fff':C.mid, borderRadius:4, cursor:'pointer', fontSize:10, fontWeight:700, transition:'all .15s',
              }}>{l==='en'?'EN':'中文'}</button>
            ))}
          </div>
        </div>

        {/* Content */}
        <div style={{flex:1, overflowY:'auto', padding:16}}>
          {tab==='scanner'  && <Scanner L={L} open={open} toggle={toggle}/>}
          {tab==='screener' && <Screener L={L} onSelect={goStock}/>}
          {tab==='research' && <Research L={L} ticker={ticker} open={open} toggle={toggle}/>}
          {tab==='tracker'  && <Tracker L={L}/>}
          {tab==='watchlist'&& <Watchlist L={L}/>}
          {tab==='system'   && <SystemTab L={L}/>}
        </div>
      </div>
    </div>
  );
}
