export const DEFAULT_PROGRESS_API_ORIGIN = 'https://equity-research-ten.vercel.app';

export function resolveProgressApiBase({ configuredBase = '', hostname = '' } = {}) {
  const configured = String(configuredBase || '').trim().replace(/\/+$/, '');
  if (configured) return configured;
  if (hostname === 'lateily.github.io') return DEFAULT_PROGRESS_API_ORIGIN;
  return '';
}

export function normalizeProgressWriteKey(value) {
  return String(value || '').trim();
}

export function parseProgressApiPayload({ status, contentType = '', body = '' }) {
  try {
    return JSON.parse(body);
  } catch {
    const protectedHtml =
      (status === 401 || status === 403) &&
      (/text\/html/i.test(contentType) || /protected deployment|vercel authentication/i.test(body));

    if (protectedHtml) {
      throw new Error(
        'Vercel deployment protection blocked this address. Use the stable team URL instead of a generated deployment URL.'
      );
    }
    throw new Error(`Progress API returned non-JSON HTTP ${status}.`);
  }
}

export async function readProgressApiResponse(response) {
  const body = await response.text();
  return parseProgressApiPayload({
    status: response.status,
    contentType: response.headers.get('content-type') || '',
    body,
  });
}
