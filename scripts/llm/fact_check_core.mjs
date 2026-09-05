#!/usr/bin/env node
/** Deterministic, offline fact tracing shared by the API and Python CLI. */

import { createHash } from 'node:crypto';
import { pathToFileURL } from 'node:url';

export const FACT_CHECK_SCHEMA = 'fact-check.v1';
export const FACT_CHECK_BLOCKED = 'BLOCKED_PENDING_HUMAN';

const BLOCKING_ENTITY_CLASSES = new Set(['MONETARY', 'ORDER', 'CONTRACT', 'CAPACITY']);
const SKIP_PATH_PARTS = new Set([
  '_fact_check', '_quality', 'qc_checklist', 'qcChecklistResults',
  'ticker', 'ts_code', 'name', 'en', 'sector',
]);
const SOURCE_METADATA_KEYS = new Set([
  'source', 'source_date', 'published_at', 'ann_date', 'announcement_date',
  'observed_at', 'fetched_at', 'generated_at', 'context_built_at', 'date', 'as_of', 'trade_date',
  'tier', 'source_tier', 'currency', 'unit', 'operator', 'comparator',
  'period', 'periods', 'measurement_period', 'report_period', 'end_date',
  'ticker', 'ts_code', 'security_code', 'entity', 'metric', 'entity_class',
]);
const SOURCE_DATE_KEYS = [
  'source_date', 'published_at', 'ann_date', 'announcement_date', 'observed_at',
  'fetched_at', 'generated_at', 'context_built_at', 'date', 'as_of', 'trade_date',
];
const INLINE_TICKER_RE = /(?<![A-Z0-9.])(?:\d{6}\.(?:SH|SZ|BJ)|\d{1,5}\.HK)(?![A-Z0-9.])/gi;

const METRIC_ALIASES = [
  ['order_book', ['order book', 'backlog', '在手订单', '订单']],
  ['gross_margin', ['gross margin', 'gross_margin', 'gm', '毛利率', '毛利']],
  ['contract_amount', ['contract amount', 'contract value', '合同金额', '合同额', '合同']],
  ['capacity', ['capacity', 'wfr/month', 'wafer/month', '产能', '产量']],
  ['revenue', ['total_revenue', 'revenue', 'sales', '营收', '收入']],
  ['net_profit', ['net_profit', 'net income', '归母', '净利润', '净利']],
  ['eps', ['diluted_eps', 'basic_eps', 'eps', '每股收益']],
  ['operating_cash_flow', ['operating cash flow', 'ocf', '经营现金流']],
  ['market_cap', ['market cap', 'market_cap', 'mktcap', '市值']],
  ['price', ['target price', 'live_price', 'current price', 'price', '股价', '目标价']],
  ['ratio', ['book-to-bill', 'reward_to_risk', 'reward to risk', 'ratio', '比例', '占比']],
];

const DATE_SOURCE = '(?:20\\d{2}[-/]\\d{1,2}[-/]\\d{1,2}|20\\d{6}|FY20\\d{2}|FY\\d{2}|20\\d{2}\\s*[HQ]\\d|\\d{2}[HQ]\\d|[HQ]\\d\\s*20\\d{2}|20\\d{2})';
const NUMBER_SOURCE = [
  '(?<![A-Za-z0-9_.])',
  '(?:(?<wordComparator>at\\s+least|at\\s+most|no\\s+less\\s+than|no\\s+more\\s+than|less\\s+than|more\\s+than|below|above|under|over|不少于|不低于|不高于|不超过|低于|高于|超过)\\s*)?',
  '(?<currency>RMB|CNY|USD|HKD|HK\\$|¥|￥|\\$)?\\s*',
  '(?<symbolComparator><=|>=|≤|≥|<|>|~|≈)?\\s*',
  '(?<sign>[+\\-−])?\\s*',
  '(?<value>\\d{1,3}(?:,\\d{3})+(?:\\.\\d+)?|\\d+(?:\\.\\d+)?)\\s*',
  '(?<unit>%|pp|bps|[Bb](?:n|illion)?|[Mm](?:n|illion)?|亿|万元|万|wfr/month|wafer/month|片/月|x|×)?\\s*',
  '(?<currencySuffix>港元|港币|美元|人民币|元)?',
  '(?![A-Za-z0-9_]|%|pp|bps|亿|万元|万|x|×|\\.\\d)',
].join('');
const CLAUSE_SPLIT_RE = /(?:\r?\n|[;；。！？!?]+)/;

const EVENT_ALIASES = [
  ['FDA_APPROVAL', /\bfda\s+approval\b|美国食药监局.{0,8}(?:批准|获批)/i],
  ['BOARD_APPROVAL', /\bboard\s+approval\b|董事会.{0,8}(?:批准|通过)/i],
  ['REGULATORY_APPROVAL', /\bapproval\b|获批|批准/i],
  ['EARNINGS_REPORT', /\bearnings\b|\breport\b|业绩|财报/i],
  ['ANNOUNCEMENT', /\bannouncement\b|公告/i],
  ['TENDER_AWARD', /\btender\b|\baward\b|招标|中标/i],
  ['PRODUCT_LAUNCH', /\blaunch\b|发布/i],
  ['GUIDANCE', /\bguidance\b|指引/i],
  ['CAPACITY_EVENT', /扩产|投产/i],
];

function stableValue(value) {
  if (Array.isArray(value)) return value.map(stableValue);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.keys(value).sort().map(key => [key, stableValue(value[key])]));
  }
  return value;
}

export function canonicalHash(value) {
  return `sha256:${createHash('sha256').update(JSON.stringify(stableValue(value))).digest('hex')}`;
}

function pathText(path) {
  return path.map(part => String(part).replaceAll('_', ' ')).join(' ').toLowerCase();
}

function canonicalMetric(value) {
  const text = String(value || '').toLowerCase().replaceAll('_', ' ');
  for (const [metric, aliases] of METRIC_ALIASES) {
    if (metric.replaceAll('_', ' ') === text || aliases.some(alias => alias.toLowerCase() === text)) return metric;
  }
  return '';
}

function metricFor(text, path, start, metadata = {}) {
  const explicit = canonicalMetric(metadata.metric);
  if (explicit) return explicit;
  const window = text.toLowerCase().slice(Math.max(0, start - 80), start + 40);
  const hint = pathText(path);
  let best = null;
  METRIC_ALIASES.forEach(([metric, aliases], rank) => {
    aliases.forEach(alias => {
      const position = window.lastIndexOf(alias.toLowerCase());
      const candidate = position >= 0
        ? [window.length - position, rank, metric]
        : hint.includes(alias.toLowerCase()) ? [100, rank, metric] : null;
      if (candidate && (!best || candidate[0] < best[0] || (candidate[0] === best[0] && candidate[1] < best[1]))) best = candidate;
    });
  });
  return best ? best[2] : 'unclassified';
}

function canonicalPeriod(rawValue) {
  const raw = String(rawValue || '').toUpperCase().replace(/[\s/]/g, '');
  if (/^20\d{2}-\d{1,2}-\d{1,2}$/.test(raw)) return raw.replaceAll('-', '');
  if (/^FY20\d{2}$/.test(raw)) return raw;
  if (/^FY\d{2}$/.test(raw)) return `FY20${raw.slice(2)}`;
  if (/^\d{2}[HQ]\d$/.test(raw)) return `20${raw}`;
  if (/^[HQ]\d20\d{2}$/.test(raw)) return `${raw.slice(2)}${raw.slice(0, 2)}`;
  if (/^20\d{2}[HQ]\d$/.test(raw)) return raw;
  return raw;
}

function periodsFromText(text) {
  return [...new Set([...String(text).matchAll(new RegExp(DATE_SOURCE, 'gi'))]
    .map(match => canonicalPeriod(match[0])))].sort();
}

function periodMatches(text) {
  return [...String(text).matchAll(new RegExp(DATE_SOURCE, 'gi'))].map(match => ({
    start: match.index,
    end: match.index + match[0].length,
    period: canonicalPeriod(match[0]),
  }));
}

function canonicalCurrency(prefix, suffix, metadataCurrency = '') {
  const raw = String(prefix || suffix || metadataCurrency || '').toUpperCase();
  if (['RMB', 'CNY', '¥', '￥', '人民币', '元'].includes(raw)) return 'CNY';
  if (['USD', '$', '美元'].includes(raw)) return 'USD';
  if (['HKD', 'HK$', '港元', '港币'].includes(raw)) return 'HKD';
  return 'UNSPECIFIED';
}

function canonicalComparator(word, symbol, metadataComparator = '') {
  const raw = String(word || symbol || metadataComparator || '').trim().toLowerCase();
  if (['>', 'above', 'over', 'more than', '高于', '超过'].includes(raw)) return 'GT';
  if (['>=', '≥', 'at least', 'no less than', '不少于', '不低于'].includes(raw)) return 'GTE';
  if (['<', 'below', 'under', 'less than', '低于'].includes(raw)) return 'LT';
  if (['<=', '≤', 'at most', 'no more than', '不高于', '不超过'].includes(raw)) return 'LTE';
  if (['~', '≈', 'approx', 'approximately', '约'].includes(raw)) return 'APPROX';
  const upper = raw.toUpperCase();
  return ['EQ', 'GT', 'GTE', 'LT', 'LTE', 'APPROX'].includes(upper) ? upper : 'EQ';
}

function entityClass(metric, baseClass) {
  if (metric === 'order_book') return 'ORDER';
  if (metric === 'contract_amount') return 'CONTRACT';
  if (metric === 'capacity') return 'CAPACITY';
  return baseClass;
}

function normalizeNumber(value, unit, currency, metric) {
  const lower = String(unit || '').toLowerCase();
  if (unit === '%') return [value, 'percent', 'RATIO'];
  if (lower === 'pp') return [value, 'percentage_point', 'RATIO'];
  if (lower === 'bps') return [value, 'basis_point', 'RATIO'];
  if (lower === 'x' || unit === '×') return [value, 'multiple', 'RATIO'];
  if (['wfr/month', 'wafer/month', '片/月'].includes(lower)) return [value, 'wafer_per_month', 'CAPACITY'];
  let multiplier = 1;
  if (['b', 'bn', 'billion'].includes(lower)) multiplier = 1e9;
  else if (['m', 'mn', 'million'].includes(lower)) multiplier = 1e6;
  else if (unit === '亿') multiplier = 1e8;
  else if (unit === '万' || unit === '万元') multiplier = 1e4;
  const moneyMetric = new Set([
    'order_book', 'contract_amount', 'revenue', 'net_profit',
    'operating_cash_flow', 'market_cap', 'price',
  ]).has(metric);
  if (currency !== 'UNSPECIFIED' || multiplier !== 1 || moneyMetric) return [value * multiplier, 'money', 'MONETARY'];
  if (metric === 'gross_margin') return [Math.abs(value) <= 1 ? value * 100 : value, 'percent', 'RATIO'];
  return [value, 'number', 'OTHER'];
}

function canonicalEntity(value, fallback = '') {
  const raw = String(value || fallback || '').trim().toUpperCase();
  return raw;
}

function entityForText(text, fallback = '') {
  const explicit = [...new Set(
    [...String(text || '').matchAll(INLINE_TICKER_RE)].map(match => canonicalEntity(match[0])),
  )];
  if (explicit.length === 1) return explicit[0];
  if (explicit.length > 1) return 'AMBIGUOUS_INLINE_ENTITY';
  return canonicalEntity(fallback);
}

function eventIdentity(text) {
  for (const [eventType, pattern] of EVENT_ALIASES) {
    if (!pattern.test(text)) continue;
    const subject = String(text)
      .toLowerCase()
      .replace(new RegExp(DATE_SOURCE, 'gi'), ' ')
      .replace(pattern, ' ')
      .replace(/\b(?:was|is|has|have|been|were|granted|received|occurred|announced|the|a|an)\b/g, ' ')
      .replace(/[\W_]+/g, ' ')
      .trim();
    return { event_type: eventType, event_subject: subject || 'UNSPECIFIED' };
  }
  return null;
}

function periodsFor(text, metadata) {
  const values = periodsFromText(text);
  const supplied = metadata.periods || (metadata.period ? [metadata.period] : []);
  for (const value of supplied) {
    const canonical = canonicalPeriod(value);
    if (canonical) values.push(canonical);
  }
  return [...new Set(values)].sort();
}

function periodsForPosition(text, metadata, offset) {
  const matches = periodMatches(text);
  if (matches.length) {
    const prior = matches.filter(match => match.end <= offset).at(-1);
    const selected = prior || matches[0];
    // governance-mutation: FACT_CHECK_LOCAL_PERIOD_BINDING
    return selected.period ? [selected.period] : [];
  }
  return periodsFor('', metadata);
}

function observationFromNumber(raw, value, unit, currency, comparator, metric, metadata, periods) {
  const sign = value < 0 ? 'NEGATIVE' : value > 0 ? 'POSITIVE' : 'ZERO';
  const [normalized, normalizedUnit, baseClass] = normalizeNumber(value, unit, currency, metric);
  return {
    raw,
    metric,
    normalized,
    unit: normalizedUnit,
    currency,
    comparator,
    sign,
    entity: canonicalEntity(metadata.entity),
    entity_class: entityClass(metric, baseClass),
    periods,
  };
}

function extractObservations(text, path = [], metadata = {}) {
  const observations = [];
  const source = String(text);
  // governance-mutation: FACT_CHECK_INLINE_ENTITY_BINDING
  const localMetadata = { ...metadata, entity: entityForText(source, metadata.entity) };
  const periods = periodsFor(source, localMetadata);
  const ignoredNumericSpans = [
    ...source.matchAll(new RegExp(DATE_SOURCE, 'gi')),
    // governance-mutation: FACT_CHECK_INLINE_ENTITY_NUMERIC_SPAN
    ...source.matchAll(INLINE_TICKER_RE),
  ].map(match => [match.index, match.index + match[0].length]);
  for (const match of source.matchAll(new RegExp(NUMBER_SOURCE, 'gi'))) {
    if (ignoredNumericSpans.some(([start, end]) => match.index >= start && match.index < end)) continue;
    const metric = metricFor(source, path, match.index, localMetadata);
    const unit = match.groups?.unit || localMetadata.unit || '';
    const currency = canonicalCurrency(match.groups?.currency, match.groups?.currencySuffix, localMetadata.currency);
    if (!unit && currency === 'UNSPECIFIED' && metric === 'unclassified') continue;
    const unsigned = Number(String(match.groups.value).replace(/,/g, ''));
    const value = ['-', '−'].includes(match.groups?.sign) ? -unsigned : unsigned;
    observations.push(observationFromNumber(
      match[0].trim(), value, unit, currency,
      canonicalComparator(match.groups?.wordComparator, match.groups?.symbolComparator, localMetadata.comparator),
      metric, localMetadata, periodsForPosition(source, localMetadata, match.index),
    ));
  }
  for (const match of source.matchAll(new RegExp(DATE_SOURCE, 'gi'))) {
    observations.push({
      raw: match[0], metric: 'date', normalized: canonicalPeriod(match[0]), unit: 'date',
      currency: 'UNSPECIFIED', comparator: 'EQ', sign: 'UNSPECIFIED',
      entity: canonicalEntity(localMetadata.entity), entity_class: 'EVENT', periods,
    });
  }
  const event = eventIdentity(source);
  if (event) {
    observations.push({
      raw: source.slice(0, 240), metric: 'event', normalized: null, unit: 'event',
      currency: 'UNSPECIFIED', comparator: 'EQ', sign: 'UNSPECIFIED',
      entity: canonicalEntity(localMetadata.entity), entity_class: 'EVENT', periods, ...event,
    });
  }
  return observations;
}

function nearestValue(ancestors, keys) {
  for (let index = ancestors.length - 1; index >= 0; index -= 1) {
    const value = ancestors[index];
    if (!value || typeof value !== 'object' || Array.isArray(value)) continue;
    for (const key of keys) {
      if (value[key] !== undefined && value[key] !== null && value[key] !== '') return value[key];
    }
  }
  return undefined;
}

function allValues(ancestors, keys) {
  const output = [];
  for (const value of ancestors) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) continue;
    for (const key of keys) {
      const candidate = value[key];
      if (candidate === undefined || candidate === null || candidate === '') continue;
      if (Array.isArray(candidate)) output.push(...candidate);
      else output.push(candidate);
    }
  }
  return output;
}

function leafMetadata(ancestors, path, fallbackEntity = '') {
  const leafIndex = /^\d+$/.test(String(path.at(-1))) ? Number(path.at(-1)) : null;
  let periods = nearestValue(ancestors, ['periods']);
  if (Array.isArray(periods) && leafIndex !== null && periods[leafIndex] !== undefined) periods = [periods[leafIndex]];
  else if (!Array.isArray(periods)) periods = [];
  const period = nearestValue(ancestors, ['period', 'measurement_period', 'report_period', 'end_date']);
  if (period !== undefined) periods = [...periods, period];
  return {
    metric: nearestValue(ancestors, ['metric']),
    currency: nearestValue(ancestors, ['currency']),
    unit: nearestValue(ancestors, ['unit']),
    comparator: nearestValue(ancestors, ['operator', 'comparator']),
    periods,
    period,
    entity: nearestValue(ancestors, ['ticker', 'ts_code', 'security_code', 'entity']) || fallbackEntity,
  };
}

function walkClaimLeaves(value, path = [], ancestors = [], output = []) {
  if (path.some(part => SKIP_PATH_PARTS.has(String(part)) || String(part).startsWith('_'))) return output;
  if (typeof value === 'string') output.push({ path, kind: 'string', value, metadata: leafMetadata(ancestors, path) });
  // governance-mutation: FACT_CHECK_NUMERIC_THESIS_LEAVES
  else if (typeof value === 'number' && Number.isFinite(value)) output.push({ path, kind: 'number', value, metadata: leafMetadata(ancestors, path) });
  else if (Array.isArray(value)) value.forEach((child, index) => walkClaimLeaves(child, [...path, String(index)], [...ancestors, value], output));
  else if (value && typeof value === 'object') Object.entries(value).forEach(([key, child]) => walkClaimLeaves(child, [...path, key], [...ancestors, value], output));
  return output;
}

function normalizeDate(rawValue) {
  if (rawValue === undefined || rawValue === null) return '';
  const raw = String(rawValue).trim();
  if (/^20\d{6}$/.test(raw)) {
    const year = Number(raw.slice(0, 4));
    const month = Number(raw.slice(4, 6));
    const day = Number(raw.slice(6, 8));
    const parsed = new Date(Date.UTC(year, month - 1, day));
    if (parsed.getUTCFullYear() !== year || parsed.getUTCMonth() !== month - 1 || parsed.getUTCDate() !== day) return '';
    return parsed.toISOString();
  }
  if (/^20\d{2}-\d{1,2}-\d{1,2}$/.test(raw)) {
    const [year, month, day] = raw.split('-').map(Number);
    const parsed = new Date(Date.UTC(year, month - 1, day));
    if (parsed.getUTCFullYear() !== year || parsed.getUTCMonth() !== month - 1 || parsed.getUTCDate() !== day) return '';
    return parsed.toISOString();
  }
  // governance-mutation: FACT_CHECK_EXPLICIT_TIMEZONE
  if (!/^20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+\-]\d{2}:\d{2})$/i.test(raw)) return '';
  const parsed = new Date(raw);
  return Number.isNaN(parsed.getTime()) ? '' : parsed.toISOString();
}

function datesInText(text) {
  const dates = [];
  for (const match of String(text || '').matchAll(/20\d{2}[-/]\d{1,2}[-/]\d{1,2}|20\d{6}/g)) {
    const normalized = normalizeDate(match[0].replaceAll('/', '-'));
    if (normalized) dates.push(normalized);
  }
  return dates;
}

function sourceMetadata(ancestors, document, fallbackEntity) {
  // governance-mutation: FACT_CHECK_ALL_SOURCE_DATES
  const explicitDates = [...allValues(ancestors, SOURCE_DATE_KEYS), document.source_date]
    .filter(value => value !== undefined && value !== null && value !== '');
  const sourceLabel = nearestValue(ancestors, ['source']) || document.label;
  const normalizedExplicit = explicitDates.map(normalizeDate);
  const explicitDatesValid = normalizedExplicit.every(Boolean);
  const dateCandidates = explicitDatesValid
    ? [...normalizedExplicit, ...datesInText(sourceLabel)].filter(Boolean).sort()
    : [];
  return {
    source_date: explicitDatesValid ? (dateCandidates.at(-1) || '') : '',
    source_label: String(sourceLabel || document.label || 'supplied'),
    source_tier: String(nearestValue(ancestors, ['tier', 'source_tier']) || document.tier || 'UNSPECIFIED'),
    entity: canonicalEntity(nearestValue(ancestors, ['ticker', 'ts_code', 'security_code', 'entity']), document.entity || fallbackEntity),
  };
}

function walkSourceLeaves(value, document, fallbackEntity, path = [], ancestors = [], output = []) {
  if (typeof value === 'string') {
    output.push({ path, kind: 'string', value, metadata: { ...leafMetadata(ancestors, path, fallbackEntity), ...sourceMetadata(ancestors, document, fallbackEntity) } });
  } else if (typeof value === 'number' && Number.isFinite(value)) {
    output.push({ path, kind: 'number', value, metadata: { ...leafMetadata(ancestors, path, fallbackEntity), ...sourceMetadata(ancestors, document, fallbackEntity) } });
  } else if (Array.isArray(value)) {
    value.forEach((child, index) => walkSourceLeaves(child, document, fallbackEntity, [...path, String(index)], [...ancestors, value], output));
  } else if (value && typeof value === 'object') {
    Object.entries(value).forEach(([key, child]) => {
      if (!SOURCE_METADATA_KEYS.has(key)) walkSourceLeaves(child, document, fallbackEntity, [...path, key], [...ancestors, value], output);
    });
  }
  return output;
}

function observationsForLeaf(leaf, fallbackEntity) {
  const metadata = { ...leaf.metadata, entity: leaf.metadata.entity || fallbackEntity };
  if (leaf.kind === 'string') {
    return String(leaf.value).split(CLAUSE_SPLIT_RE).map(part => part.trim()).filter(Boolean)
      .flatMap(clause => extractObservations(clause, leaf.path, metadata).map(observation => ({ clause, observation })));
  }
  const metric = metricFor('', leaf.path, 0, metadata);
  if (metric === 'unclassified' && !metadata.unit && !metadata.currency) return [];
  const currency = canonicalCurrency('', '', metadata.currency);
  const numeric = Number(leaf.value);
  const observation = observationFromNumber(
    String(leaf.value), numeric, metadata.unit || '', currency,
    canonicalComparator('', '', metadata.comparator), metric, metadata, periodsFor('', metadata),
  );
  return [{ clause: String(leaf.value), observation }];
}

function normalizeSourceDocuments(sourceDocuments, enrichmentContext, ticker) {
  const supplied = Array.isArray(sourceDocuments) ? sourceDocuments : [];
  if (supplied.length) return supplied.map((document, index) => ({
    payload: document.payload,
    label: String(document.label || `source-${index}`),
    tier: String(document.tier || 'SUPPLIED'),
    entity: canonicalEntity(document.entity, ticker),
    source_date: document.source_date || '',
    // governance-mutation: FACT_CHECK_RECOMPUTES_CONTENT_HASH
    content_hash: canonicalHash(document.payload),
  }));
  const context = enrichmentContext || {};
  const contextDate = context?.extras?.context_built_at || context.generated_at || context.as_of || '';
  const documents = [];
  for (const [key, payload] of [['fundamentals', context.fundamentals], ['extras', context.extras]]) {
    if (payload && typeof payload === 'object') documents.push({
      payload, label: `enrichment_context.${key}`, tier: 'SUPPLIED_CONTEXT', entity: ticker,
      source_date: contextDate, content_hash: canonicalHash(payload),
    });
  }
  for (const [index, payload] of (Array.isArray(context.fact_sources) ? context.fact_sources : []).entries()) {
    documents.push({
      payload, label: String(payload?.source || `enrichment_context.fact_sources.${index}`),
      tier: String(payload?.tier || 'SUPPLIED_CONTEXT'), entity: canonicalEntity(payload?.ticker, ticker),
      source_date: payload?.source_date || contextDate, content_hash: canonicalHash(payload),
    });
  }
  return documents;
}

function sourceFacts(documents, ticker, cutoff) {
  const facts = [];
  for (const document of documents) {
    for (const leaf of walkSourceLeaves(document.payload, document, ticker, [document.label], [])) {
      for (const { clause, observation } of observationsForLeaf(leaf, ticker)) {
        facts.push({
          observation,
          source_path: leaf.path.join('.'),
          source_tier: leaf.metadata.source_tier,
          source_label: leaf.metadata.source_label,
          source_excerpt: clause.slice(0, 240),
          source_date: leaf.metadata.source_date || '',
          content_hash: document.content_hash,
        });
      }
    }
  }
  const seen = new Set();
  return facts.filter(fact => {
    const key = JSON.stringify([
      fact.observation.metric, fact.observation.normalized, fact.observation.unit,
      fact.observation.currency, fact.observation.comparator, fact.observation.sign,
      fact.observation.entity, fact.observation.periods, fact.source_path,
      fact.source_label, fact.source_date, fact.content_hash,
    ]);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  // governance-mutation: FACT_CHECK_SOURCE_PIT_CUTOFF
  }).map(fact => ({ ...fact, admissible: Boolean(fact.source_date) && fact.source_date <= cutoff }));
}

function numericEqual(left, right, unit) {
  if (typeof left === 'string' || typeof right === 'string') return left === right;
  if (!Number.isFinite(left) || !Number.isFinite(right)) return false;
  const tolerance = ['percent', 'percentage_point', 'number', 'multiple'].includes(unit)
    ? 0.02 : Math.max(1, Math.abs(left) * 0.0005);
  return Math.abs(left - right) <= tolerance;
}

function periodsCompatible(left, right) {
  if (!left.length && !right.length) return true;
  return left.some(period => right.includes(period));
}

function comparatorsCompatible(left, right) {
  if (left === right) return true;
  return new Set([left, right]).size === 2 && [left, right].every(value => ['EQ', 'APPROX'].includes(value));
}

function highRiskIdentityComplete(observation) {
  if (!BLOCKING_ENTITY_CLASSES.has(observation.entity_class)) return true;
  if (!observation.entity || !observation.periods.length) return false;
  if (['MONETARY', 'ORDER', 'CONTRACT'].includes(observation.entity_class) && observation.currency === 'UNSPECIFIED') return false;
  if (observation.entity_class === 'CAPACITY' && observation.unit === 'number') return false;
  return true;
}

function sameIdentity(left, right) {
  // governance-mutation: FACT_CHECK_HIGH_RISK_IDENTITY
  return left.metric === right.metric
    && left.unit === right.unit
    && left.currency === right.currency
    && comparatorsCompatible(left.comparator, right.comparator)
    && left.sign === right.sign
    && left.entity === right.entity
    && periodsCompatible(left.periods, right.periods);
}

function eventMatches(left, right) {
  // governance-mutation: FACT_CHECK_EVENT_SUBJECT_IDENTITY
  return left.event_type === right.event_type
    && left.event_subject === right.event_subject
    && left.entity === right.entity
    && periodsCompatible(left.periods, right.periods);
}

function factReference(fact) {
  return {
    source_path: fact.source_path,
    source_tier: fact.source_tier,
    source: fact.source_label,
    source_date: fact.source_date,
    content_hash: fact.content_hash,
    raw: fact.observation.raw,
    normalized: fact.observation.normalized,
    identity: {
      metric: fact.observation.metric, unit: fact.observation.unit,
      currency: fact.observation.currency, comparator: fact.observation.comparator,
      sign: fact.observation.sign, entity: fact.observation.entity,
      periods: fact.observation.periods,
    },
  };
}

function checkObservation(observation, allFacts) {
  const admissibleFacts = allFacts.filter(fact => fact.admissible);
  const base = { ...observation };
  if (observation.metric === 'event') {
    const found = admissibleFacts.find(fact => fact.observation.metric === 'event' && eventMatches(observation, fact.observation));
    return found ? { ...base, state: 'TRACED', source: factReference(found) } : { ...base, state: 'UNTRACED' };
  }
  if (observation.metric === 'date') {
    const found = admissibleFacts.find(fact => fact.observation.metric === 'date'
      && observation.normalized === fact.observation.normalized && observation.entity === fact.observation.entity);
    return found ? { ...base, state: 'TRACED', source: factReference(found) } : { ...base, state: 'UNTRACED' };
  }
  if (!highRiskIdentityComplete(observation)) return { ...base, state: 'UNTRACED', identity_error: 'HIGH_RISK_IDENTITY_INCOMPLETE' };
  const sameMetric = admissibleFacts.filter(fact => fact.observation.metric === observation.metric);
  const candidates = sameMetric.filter(fact => sameIdentity(observation, fact.observation));
  const exact = candidates.find(fact => numericEqual(observation.normalized, fact.observation.normalized, observation.unit));
  if (exact) return { ...base, state: 'TRACED', source: factReference(exact) };
  if (candidates.length && observation.metric !== 'unclassified') {
    const ranked = [...candidates].sort((left, right) => {
      const leftDistance = Number.isFinite(left.observation.normalized)
        ? Math.abs(observation.normalized - left.observation.normalized) : Number.POSITIVE_INFINITY;
      const rightDistance = Number.isFinite(right.observation.normalized)
        ? Math.abs(observation.normalized - right.observation.normalized) : Number.POSITIVE_INFINITY;
      return leftDistance - rightDistance || left.source_path.localeCompare(right.source_path);
    });
    return { ...base, state: 'MISMATCH', source: factReference(ranked[0]) };
  }
  return { ...base, state: 'UNTRACED' };
}

function assertCutoff(cutoff) {
  const normalized = normalizeDate(cutoff);
  if (!normalized) throw new Error('fact-check cutoff must be a valid frozen timestamp');
  return normalized;
}

export function factCheckThesis(thesis, enrichmentContext = {}, ticker = '', cutoff, sourceDocuments = []) {
  const frozenCutoff = assertCutoff(cutoff);
  const canonicalTicker = canonicalEntity(ticker);
  const documents = normalizeSourceDocuments(sourceDocuments, enrichmentContext, canonicalTicker);
  const facts = sourceFacts(documents, canonicalTicker, frozenCutoff);
  const claims = [];
  const mismatches = [];
  const untraced = [];
  const fabricationSuspects = [];
  const blockingMismatches = [];

  for (const leaf of walkClaimLeaves(thesis)) {
    leaf.metadata.entity = leaf.metadata.entity || canonicalTicker;
    const checkedByClause = new Map();
    for (const { clause, observation } of observationsForLeaf(leaf, canonicalTicker)) {
      const checked = checkObservation(observation, facts);
      if (!checkedByClause.has(clause)) checkedByClause.set(clause, []);
      checkedByClause.get(clause).push(checked);
    }
    for (const [clause, checked] of checkedByClause.entries()) {
      if (!checked.length) continue;
      const states = new Set(checked.map(item => item.state));
      const state = states.has('UNTRACED') ? 'UNTRACED' : states.has('MISMATCH') ? 'MISMATCH' : 'TRACED';
      const claim = { path: leaf.path.join('.'), excerpt: clause.slice(0, 300), state, observations: checked };
      claims.push(claim);
      for (const item of checked) {
        const row = { path: claim.path, excerpt: claim.excerpt, ...item };
        if (item.state === 'MISMATCH') {
          mismatches.push(row);
          // governance-mutation: FACT_CHECK_BLOCKS_MISMATCHED_MONETARY_CLAIMS
          // For money / orders / contracts / capacity, "the number disagrees with the
          // source" is at least as serious as "no source at all" — and looks more
          // credible, so it is the easier lie to ship. No tolerance band: an
          // unvalidated threshold has no place in a fail-closed gate.
          if (BLOCKING_ENTITY_CLASSES.has(item.entity_class)) {
            blockingMismatches.push(row);
            fabricationSuspects.push(row);
          }
        } else if (item.state === 'UNTRACED') {
          untraced.push(row);
          if (BLOCKING_ENTITY_CLASSES.has(item.entity_class)) fabricationSuspects.push(row);
        }
      }
    }
  }

  // governance-mutation: FACT_CHECK_BLOCKS_UNTRACED_MONETARY_CLAIMS
  const status = fabricationSuspects.length ? FACT_CHECK_BLOCKED : 'PASS';
  const thesisHash = canonicalHash(thesis);
  const sourceDescriptors = documents.map(document => ({
    label: document.label, tier: document.tier, entity: document.entity,
    source_date: document.source_date, content_hash: document.content_hash,
  })).sort((left, right) => JSON.stringify(left).localeCompare(JSON.stringify(right)));
  const sourceSetHash = canonicalHash({ cutoff: frozenCutoff, sources: sourceDescriptors });
  // governance-mutation: FACT_CHECK_RECEIPT_BINDS_EVIDENCE
  const inputHash = canonicalHash({ ticker: canonicalTicker, cutoff: frozenCutoff, thesis_hash: thesisHash, source_set_hash: sourceSetHash });
  const receipt = {
    schema_version: FACT_CHECK_SCHEMA,
    status,
    ticker: canonicalTicker,
    cutoff: frozenCutoff,
    thesis_hash: thesisHash,
    source_set_hash: sourceSetHash,
    input_hash: inputHash,
    summary: {
      claims: claims.length,
      traced: claims.filter(item => item.state === 'TRACED').length,
      mismatches: mismatches.length,
      blocking_mismatches: blockingMismatches.length,
      untraced: untraced.length,
      fabrication_suspects: fabricationSuspects.length,
      source_facts: facts.length,
      admissible_source_facts: facts.filter(fact => fact.admissible).length,
      future_source_facts: facts.filter(fact => fact.source_date && fact.source_date > frozenCutoff).length,
      undated_source_facts: facts.filter(fact => !fact.source_date).length,
    },
    claims, mismatches, blocking_mismatches: blockingMismatches,
    untraced, fabrication_suspects: fabricationSuspects,
  };
  return { ...receipt, receipt_hash: canonicalHash(receipt) };
}

export function attachFactCheck(thesis, enrichmentContext = {}, ticker = '', cutoff) {
  const receipt = factCheckThesis(thesis, enrichmentContext, ticker, cutoff);
  return { data: { ...thesis, _fact_check: receipt }, status: receipt.status };
}

// governance-mutation: FACT_CHECK_COVERS_EVERY_RETURNED_BLOCK
// A multi-agent response ships several thesis blocks. Gating only the synthesis
// leaves the rest returned, rendered and quotable while the envelope still reads
// OK — the fabricated number simply moves one key to the left. Every block that
// leaves the API is checked, and any blocked block blocks the envelope.
export function attachFactCheckToBlocks(blocks, enrichmentContext = {}, ticker = '', cutoff) {
  const receipts = {};
  const checked = {};
  let blocked = false;
  for (const [name, block] of Object.entries(blocks || {})) {
    if (!block || typeof block !== 'object' || Array.isArray(block)) {
      checked[name] = block;
      continue;
    }
    const receipt = factCheckThesis(block, enrichmentContext, ticker, cutoff);
    receipts[name] = receipt;
    checked[name] = { ...block, _fact_check: receipt };
    if (receipt.status === 'BLOCKED_PENDING_HUMAN') blocked = true;
  }
  return {
    blocks: checked,
    receipts,
    status: blocked ? 'BLOCKED_PENDING_HUMAN' : 'PASS',
    summary: {
      checked_blocks: Object.keys(receipts).length,
      blocked_blocks: Object.entries(receipts)
        .filter(([, r]) => r.status === 'BLOCKED_PENDING_HUMAN').map(([n]) => n),
      fabrication_suspects: Object.values(receipts)
        .reduce((total, r) => total + Number(r?.summary?.fabrication_suspects || 0), 0),
    },
  };
}

export function factCheckRequest(request) {
  if (!request || typeof request !== 'object' || Array.isArray(request)) throw new Error('fact-check request must be an object');
  if (!request.thesis || typeof request.thesis !== 'object' || Array.isArray(request.thesis)) throw new Error('fact-check thesis must be an object');
  return factCheckThesis(
    request.thesis,
    request.enrichment_context || {},
    request.ticker || '',
    request.cutoff,
    request.source_documents || [],
  );
}

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return Buffer.concat(chunks).toString('utf8');
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const request = JSON.parse(await readStdin());
    process.stdout.write(`${JSON.stringify(factCheckRequest(request))}\n`);
  } catch (error) {
    process.stderr.write(`fact-check refused: ${error.message}\n`);
    process.exitCode = 2;
  }
}
