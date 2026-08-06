import { createHash, timingSafeEqual } from 'node:crypto';

const BASE_URL = 'https://api.deepseek.com';
const DEFAULT_MODEL = 'deepseek-v4-flash';
const SUPPORTED_MODELS = new Set(['deepseek-v4-flash', 'deepseek-v4-pro']);
const MAX_PROMPT_CHARS = 6000;
const MAX_SYSTEM_CHARS = 2000;
const MAX_TOKENS_LIMIT = 2048;

const PRICING_CNY_PER_1M = {
  'deepseek-v4-flash': {
    cacheHitInput: 0.02016,
    cacheMissInput: 1.008,
    output: 2.016,
  },
  'deepseek-v4-pro': {
    cacheHitInput: 0.0261,
    cacheMissInput: 3.132,
    output: 6.264,
  },
};

function allowCors(req, res) {
  const origin = req.headers?.origin;
  const allowed = [
    'http://localhost:5173',
    'http://127.0.0.1:5173',
    ...(process.env.AIOS_ALLOWED_ORIGINS || '')
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean),
  ];
  if (origin && allowed.includes(origin)) {
    res.setHeader('Access-Control-Allow-Origin', origin);
    res.setHeader('Vary', 'Origin');
  }
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, X-AIOS-Run-Key');
}

function headerValue(req, name) {
  const value = req.headers?.[name] || req.headers?.[name.toLowerCase()];
  return Array.isArray(value) ? value[0] : value;
}

function timingSafeEqualString(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string') return false;
  const bufA = Buffer.from(a, 'utf8');
  const bufB = Buffer.from(b, 'utf8');
  if (bufA.length !== bufB.length) {
    timingSafeEqual(bufB, bufB);
    return false;
  }
  return timingSafeEqual(bufA, bufB);
}

async function parseBody(req) {
  if (req.body && typeof req.body === 'object') return req.body;
  if (typeof req.body === 'string') return JSON.parse(req.body);

  const chunks = [];
  for await (const chunk of req) chunks.push(Buffer.from(chunk));
  const raw = Buffer.concat(chunks).toString('utf8').trim();
  return raw ? JSON.parse(raw) : {};
}

function cleanString(value, field, maxLength) {
  if (typeof value !== 'string' || !value.trim()) throw new Error(`${field} is required.`);
  const cleaned = value.trim();
  if (cleaned.length > maxLength) throw new Error(`${field} is too long.`);
  return cleaned;
}

function cleanOptionalString(value, field, maxLength) {
  if (value === undefined || value === null || value === '') return '';
  if (typeof value !== 'string') throw new Error(`${field} must be a string.`);
  const cleaned = value.trim();
  if (cleaned.length > maxLength) throw new Error(`${field} is too long.`);
  return cleaned;
}

function normalizeRequest(input) {
  const model = typeof input.model === 'string' && input.model.trim()
    ? input.model.trim()
    : DEFAULT_MODEL;
  if (!SUPPORTED_MODELS.has(model)) throw new Error('Unsupported DeepSeek model.');

  const prompt = cleanString(input.prompt, 'prompt', MAX_PROMPT_CHARS);
  const system = cleanOptionalString(input.system, 'system', MAX_SYSTEM_CHARS);
  const mode = input.mode === 'live' ? 'live' : 'dry_run';
  const thinking = input.thinking === 'enabled' ? 'enabled' : 'disabled';
  const maxTokens = Number.isFinite(Number(input.max_tokens))
    ? Math.min(Math.max(1, Math.floor(Number(input.max_tokens))), MAX_TOKENS_LIMIT)
    : 512;

  return { model, prompt, system, mode, thinking, maxTokens };
}

function inputHash({ model, prompt, system, thinking }) {
  return `sha256:${createHash('sha256')
    .update(JSON.stringify({ model, prompt, system, thinking }))
    .digest('hex')}`;
}

function buildMessages({ prompt, system }) {
  const messages = [];
  if (system) messages.push({ role: 'system', content: system });
  messages.push({ role: 'user', content: prompt });
  return messages;
}

function requireLiveAccess(req) {
  const configuredKey = process.env.AIOS_DEEPSEEK_RUN_KEY;
  if (!configuredKey) {
    return { ok: false, code: 503, error: 'AIOS_DEEPSEEK_RUN_KEY is not configured.' };
  }
  const providedKey = headerValue(req, 'x-aios-run-key');
  if (!timingSafeEqualString(providedKey || '', configuredKey)) {
    return { ok: false, code: 401, error: 'Invalid AIOS run key.' };
  }
  if (!process.env.DEEPSEEK_API_KEY) {
    return { ok: false, code: 503, error: 'DEEPSEEK_API_KEY is not configured.' };
  }
  return { ok: true };
}

function estimateCostCny(model, usage = {}) {
  const pricing = PRICING_CNY_PER_1M[model];
  const inputTokens = Number(usage.prompt_tokens || usage.input_tokens || 0);
  const outputTokens = Number(usage.completion_tokens || usage.output_tokens || 0);
  const cachedTokens = Number(usage.prompt_cache_hit_tokens || usage.cached_tokens || 0);
  const cacheMissTokens = Number(usage.prompt_cache_miss_tokens || Math.max(inputTokens - cachedTokens, 0));
  const cost = (
    cachedTokens * pricing.cacheHitInput
    + cacheMissTokens * pricing.cacheMissInput
    + outputTokens * pricing.output
  ) / 1_000_000;
  return cost.toFixed(6);
}

async function callDeepSeek(request) {
  const response = await fetch(`${BASE_URL}/chat/completions`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${process.env.DEEPSEEK_API_KEY}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model: request.model,
      messages: buildMessages(request),
      max_tokens: request.maxTokens,
      thinking: { type: request.thinking },
      stream: false,
    }),
  });

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(`DeepSeek HTTP ${response.status}`);
  }
  return data;
}

function extractText(data) {
  const content = data?.choices?.[0]?.message?.content;
  return typeof content === 'string' ? content.trim() : '';
}

function dryRunResponse(request) {
  return {
    ok: true,
    mode: 'dry_run',
    provider: 'deepseek',
    model: request.model,
    input_hash: inputHash(request),
    output: {
      text: 'DRY_RUN: DeepSeek adapter request accepted by the backend gate. No provider API call was made.',
      no_trade_flag: true,
      data_status: 'DRY_RUN',
    },
    usage: {
      status: 'NOT_APPLICABLE',
      estimated_cost_cny: '0.000000',
    },
  };
}

export {
  normalizeRequest,
  estimateCostCny,
  dryRunResponse,
  requireLiveAccess,
};

export default async function handler(req, res) {
  allowCors(req, res);
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('X-AIOS-Provider', 'deepseek');
  res.setHeader('X-AIOS-Key-Boundary', 'server-only');

  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'POST') return res.status(405).json({ ok: false, error: 'Method not allowed' });

  try {
    const request = normalizeRequest(await parseBody(req));
    if (request.mode !== 'live') {
      return res.status(200).json(dryRunResponse(request));
    }

    const access = requireLiveAccess(req);
    if (!access.ok) return res.status(access.code).json({ ok: false, error: access.error });

    const data = await callDeepSeek(request);
    const usage = data.usage || {};
    if (!usage.prompt_tokens && !usage.input_tokens) {
      throw new Error('DeepSeek response did not report usage.');
    }

    return res.status(200).json({
      ok: true,
      mode: 'live',
      provider: 'deepseek',
      model: data.model || request.model,
      input_hash: inputHash(request),
      output: {
        text: extractText(data),
        finish_reason: data?.choices?.[0]?.finish_reason || null,
        no_trade_flag: true,
        data_status: 'MODEL_OUTPUT_UNVERIFIED',
      },
      usage: {
        status: 'REPORTED',
        input_tokens: usage.prompt_tokens || usage.input_tokens || 0,
        cached_input_tokens: usage.prompt_cache_hit_tokens || usage.cached_tokens || 0,
        output_tokens: usage.completion_tokens || usage.output_tokens || 0,
        estimated_cost_cny: estimateCostCny(request.model, usage),
      },
    });
  } catch (error) {
    return res.status(400).json({
      ok: false,
      error: error instanceof Error ? error.message : String(error),
    });
  }
}
