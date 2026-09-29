// Pure display helpers for the research trust line and the desk run headline.
// Nothing here grants approval: rates below the minimum sample stay withheld,
// missing values stay visible, and levels are plain text chips.

const levelLabels = {
  MEETS_BAR: '达草案门槛',
  MISSES_BAR: '未达草案门槛',
  RATE_WITHHELD_N_BELOW_MIN: '样本不足·比率暂缓',
  NOT_COMPUTABLE: '不可算'
};
const relianceLabels = {
  TRUSTED_FOR_TRIAGE: '可用于分诊排序（仍由人审）',
  ADVISORY_SHOW_STALE_SHARE: '仅作提示·须同看陈旧占比',
  COVERAGE_HONEST: '覆盖如实',
  COVERAGE_GAP_DISCLOSE: '覆盖缺口须披露',
  UNRATED: '未评级'
};
const metricLabels = {
  red_flag_stale_evidence_share: '红旗依赖已被取代证据',
  red_flag_cross_model_confirmed_share: '红旗被 E1 层确认',
  red_flag_human_confirmed_share: '红旗被人确认',
  u4_ready_false_ready_share: 'U4 可审被人否掉',
  complete_label_defect_share: 'COMPLETE 标签被人发现错',
  news_channel_available_share: '消息面可用',
  macro_event_consensus_coverage: '宏观事件一致预期覆盖'
};

const count = value => Number.isInteger(value) ? String(value) : '—';

export function countText(metric) {
  if (!metric) return '—';
  // A not-computable metric has no sample: never show 0 / 0 beside 不可算.
  if (metric.level === 'NOT_COMPUTABLE') return '— / —';
  return `${count(metric.numerator)} / ${count(metric.denominator)}`;
}

export function rateText(metric) {
  if (!metric) return '—';
  if (metric.level === 'NOT_COMPUTABLE') return `不可算 · ${metric.not_computable_reason || 'REASON_MISSING'}`;
  if (metric.rate == null || !Number.isFinite(metric.rate)) return `— (n<${metric.min_n ?? 20})`;
  return `${(metric.rate * 100).toFixed(1)}%`;
}

export function thresholdText(metric) {
  if (!metric || typeof metric.threshold !== 'number') return '—';
  const op = metric.direction === 'LOWER_IS_BETTER' ? '≤' : '≥';
  return `${op} ${(metric.threshold * 100).toFixed(0)}%（草案）`;
}

export function levelChip(level) {
  return {
    text: `${levelLabels[level] || '未知档位'} ${level || 'UNKNOWN'}`,
    tone: level === 'MISSES_BAR' ? 'amber' : 'neutral'
  };
}

export function relianceText(reliance) {
  return `${relianceLabels[reliance] || '未知'} · ${reliance || 'UNKNOWN'}`;
}

export function metricLabel(metricId) {
  return metricLabels[metricId] || metricId;
}

export function trustLineStatus(trust) {
  if (!trust || !trust.status) return { value: 'NOT_EVALUATED', detail: '未观察到信任线' };
  if (trust.status === 'PRESENT') return { value: 'PRESENT / DESCRIPTIVE_ONLY', detail: `E1 基准 ${trust.e1_basis} · ${trust.retention_status}` };
  if (trust.status === 'NOT_PRODUCED') return { value: 'NOT_PRODUCED', detail: '本 run 未产出信任线（不是 0）' };
  return { value: trust.status, detail: trust.reason || 'REASON_MISSING' };
}

// Run completeness and data quality are different facts; the desk shows both.
export function runQualityPairs(attempt) {
  const a = attempt || {};
  return [
    ['运行完整性', a.report || 'NOT_OBSERVED'],
    ['数据质量', a.data_quality || 'UNAVAILABLE'],
    ['研究数据质量', a.research_data_quality || 'UNAVAILABLE']
  ];
}

export function fileBindingText(observation) {
  if (!observation) return 'NOT_OBSERVED';
  const n = Array.isArray(observation.issues) ? observation.issues.length : null;
  return n == null ? 'UNAVAILABLE' : `${n} FILE_BINDING_ISSUES`;
}
