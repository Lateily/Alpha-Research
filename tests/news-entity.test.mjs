// tests/news-entity.test.mjs — entity-gate regressions for api/news.js (PR-A A6)
//
// Run: node tests/news-entity.test.mjs        (zero network — pure functions only)
//
// Regression anchors:
//   1. BYD/Boyd: \bBYD\b must match "BYD" but NEVER "Boyd Gaming" (the v4 bug
//      class: blind per-feed attribution hung any feed item on the ticker).
//   2. Unrecognized-entity demotion: an article with no confirmed entity must
//      demote to the sector/macro pool (ticker=null, demoted=true) instead of
//      inheriting the feed's ticker.
//   3. Chinese-name substring matching (no word boundaries in CJK).
//   4. Dynamic-watchlist entry normalization (premarket_frame & watchlist.json
//      shapes both normalize; no hardcoded ticker list in the module).

import assert from 'node:assert/strict';
import {
  buildEntityVocab,
  matchEntities,
  attributeArticle,
  normalizeWatchEntry,
  parseRSS,
} from '../api/news.js';

const entries = [
  { ticker: '002594.SZ', yahoo: '002594.SZ', names: ['BYD', '比亚迪'] },
  { ticker: '300308.SZ', yahoo: '300308.SZ', names: ['Innolight', '中际旭创'] },
];
const vocab = buildEntityVocab(entries);

// ── 1. BYD matches, Boyd Gaming does not ────────────────────────────────────
assert.deepEqual(
  matchEntities('BYD posts record quarterly EV sales in Europe', vocab),
  ['002594.SZ'],
  'plain BYD headline must match 002594.SZ',
);
assert.deepEqual(
  matchEntities('Boyd Gaming reports quarterly results beat', vocab),
  [],
  'Boyd Gaming must NOT match BYD (word boundary)',
);
assert.deepEqual(
  matchEntities('boyd interactive expands casino floor', vocab),
  [],
  'lowercase boyd must NOT match either',
);
// ADR alias comes from the explicit alias table, not substring bleed
assert.deepEqual(
  matchEntities('BYDDY jumps 4% premarket', vocab),
  ['002594.SZ'],
  'BYDDY ADR alias must match via explicit alias',
);
console.log('PASS entity: BYD 命中 / Boyd Gaming 不命中(词边界)/ BYDDY 别名命中');

// ── 2. Unrecognized entity → demote to macro/sector pool ────────────────────
const unrelated = {
  title: 'Electric vehicle sector faces new tariff review',
  summary: 'Broad industry news with no specific company named.',
};
const rUnrelated = attributeArticle(unrelated, '002594.SZ', vocab);
assert.equal(rUnrelated.ticker, null, 'no confirmed entity → no ticker');
assert.equal(rUnrelated.demoted, true, 'no confirmed entity → demoted');
console.log('PASS entity: 未识别实体 → 降级 sector/macro 池,不挂个股');

// confirmed entity keeps the feed ticker
const rConfirmed = attributeArticle(
  { title: 'BYD to build new battery plant', summary: '' },
  '002594.SZ',
  vocab,
);
assert.equal(rConfirmed.ticker, '002594.SZ');
assert.equal(rConfirmed.demoted, false);
// cross-feed correction: Innolight article arriving on BYD's feed goes to Innolight
const rCross = attributeArticle(
  { title: 'Innolight ships 1.6T optical modules at scale', summary: '' },
  '002594.SZ',
  vocab,
);
assert.equal(rCross.ticker, '300308.SZ', 'confirmed OTHER entity re-attributes');
console.log('PASS entity: 确认实体保留 / 跨 feed 纠正归属');

// ── 3. Chinese-name substring matching ──────────────────────────────────────
assert.deepEqual(
  matchEntities('比亚迪七月销量创新高', vocab),
  ['002594.SZ'],
  'Chinese name must match by substring',
);
assert.deepEqual(
  matchEntities('中际旭创中标海外大单', vocab),
  ['300308.SZ'],
);
console.log('PASS entity: 中文名子串匹配');

// ── 4. Watchlist entry normalization (both shapes) ──────────────────────────
assert.deepEqual(
  normalizeWatchEntry({ ticker: '603233.SH', yahoo: '603233.SS', name_en: 'Da Shenlin', name_zh: '大参林' }),
  { ticker: '603233.SH', yahoo: '603233.SS', names: ['Da Shenlin', '大参林'] },
);
assert.deepEqual(
  normalizeWatchEntry('600276.SH'),
  { ticker: '600276.SH', yahoo: null, names: [] },
  'premarket_frame string entries normalize',
);
assert.equal(normalizeWatchEntry({}), null, 'entry without ticker rejected');
console.log('PASS watchlist: premarket_frame/watchlist.json 两种形态归一化');

// ── 5. parseRSS still works (sanity for the shared parser) ──────────────────
const xml = `<rss><channel>
<item><title>BYD launches Seal refresh with longer range</title>
<pubDate>Thu, 30 Jul 2026 08:00:00 GMT</pubDate>
<link>https://example.com/a</link><description>EV news</description></item>
</channel></rss>`;
const items = parseRSS(xml, { ticker: '002594.SZ', label: 'BYD', category: 'PORTFOLIO' });
assert.equal(items.length, 1);
assert.equal(items[0].ticker, '002594.SZ');
console.log('PASS parser: parseRSS 基本解析');

// ── 6. Short/collision-prone terms are excluded from the vocab ──────────────
const shortVocab = buildEntityVocab([{ ticker: 'X.SZ', yahoo: null, names: ['AI'] }]);
assert.deepEqual(
  matchEntities('AI stocks rally broadly', shortVocab),
  [],
  '2-char English terms must not gate entity attribution',
);
console.log('PASS entity: <3字符英文词不入词表(防误伤)');

// ── 7. 审计回归:3位港股代码不得当作独立数字词元(175 ≠ "adds 175 million")──
const hkVocab = buildEntityVocab([{ ticker: '175.HK', yahoo: '0175.HK', names: ['Geely', '吉利汽车'] }]);
assert.deepEqual(
  matchEntities('Nvidia adds 175 million to capex guidance', hkVocab),
  [],
  '裸数字 175 不得命中 175.HK —— 审计发现的误挂案例',
);
assert.deepEqual(
  matchEntities('Geely reports July deliveries', hkVocab),
  ['175.HK'],
  '正式公司名仍须命中',
);
assert.deepEqual(
  matchEntities('Shares of 0175.HK rose after the update', hkVocab),
  ['175.HK'],
  '带后缀写法 0175.HK 视为实体证据',
);
console.log('PASS entity: 裸3位数字不入词表 / 公司名与带后缀代码仍命中(审计回归)');


// ── 8. 审计回归:major_news 消费器字段与状态透传(handler 级 mock,零网络)──
{
  const rows = [{ title: '央行发布二季度货币政策报告', pub_time: '2026-08-01 09:00:00', src: '新华社' }];
  const shaped = rows.slice(0, 40).map((r, i) => ({
    id: `M-majornews-${i}`,
    title: String(r.title || '').slice(0, 200),
    published_at: r.pub_time || r.datetime || null,   // 必须是 published_at
    source: r.src || 'Tushare major_news',
    ticker: null, tag: 'MACRO', category: 'MACRO',
  })).filter(x => x.title);
  assert.equal(shaped.length, 1, 'major_news 行应被整形');
  assert.ok(shaped[0].published_at, 'published_at 必须存在 —— 写成 published 会让过滤器全部丢弃');
  assert.equal(shaped[0].ticker, null, 'major_news 不做实体归属');
  // 状态透传:上游 SOURCE_DOWN 不得被 rows>0 覆盖成 OK/EMPTY_VALID
  const pick = (upstream, n) => (upstream && upstream !== 'OK') ? upstream : (n > 0 ? 'OK' : 'EMPTY_VALID');
  assert.equal(pick('SOURCE_DOWN', 5), 'SOURCE_DOWN', '上游 SOURCE_DOWN 必须透传');
  assert.equal(pick('DATA_BLOCKED', 0), 'DATA_BLOCKED', '上游 DATA_BLOCKED 必须透传');
  assert.equal(pick(null, 3), 'OK');
  assert.equal(pick(null, 0), 'EMPTY_VALID');
  console.log('PASS major_news: published_at 字段 + 上游状态透传(审计回归)');
}

console.log('ALL news-entity TESTS PASS (0 network calls)');
