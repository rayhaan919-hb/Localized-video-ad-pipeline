import { NextResponse } from 'next/server';
import type { VideoJobRecord } from '@/types/studio';

const ACCESS_COOKIE_NAME = 'lva_access_token';
const REFRESH_COOKIE_NAME = 'lva_refresh_token';
const DEFAULT_WORKER_TIMEOUT_MS = 10000;
const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isValidUuid(value: string): boolean {
  return UUID_RE.test(value.trim());
}

export function stripAuthTokensFromPayload(payload: unknown): unknown {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    return payload;
  }
  const rest = { ...(payload as Record<string, unknown>) };
  delete rest.access_token;
  delete rest.refresh_token;
  return rest;
}

function collectAllowedOrigins(request: Request): Set<string> {
  const allowed = new Set<string>();
  try {
    allowed.add(new URL(request.url).origin);
  } catch {
    // ignore invalid synthetic request URL
  }
  const host = request.headers.get('host')?.trim();
  if (host) {
    allowed.add(`http://${host}`);
    allowed.add(`https://${host}`);
  }
  const forwardedHost = request.headers
    .get('x-forwarded-host')
    ?.split(',')[0]
    ?.trim();
  if (forwardedHost) {
    allowed.add(`http://${forwardedHost}`);
    allowed.add(`https://${forwardedHost}`);
  }
  for (const envUrl of [
    process.env.FRONTEND_APP_URL,
    process.env.NEXT_PUBLIC_APP_URL,
  ]) {
    if (envUrl?.trim()) {
      try {
        allowed.add(new URL(envUrl.trim()).origin);
      } catch {
        // ignore invalid env URL
      }
    }
  }
  return allowed;
}

export function assertSameOriginRequest(request: Request): NextResponse | null {
  const secFetchSite = request.headers.get('sec-fetch-site')?.trim().toLowerCase();
  if (secFetchSite === 'cross-site') {
    return NextResponse.json(
      { detail: 'Cross-site request blocked.' },
      { status: 403 }
    );
  }

  const allowed = collectAllowedOrigins(request);
  const origin = request.headers.get('origin')?.trim();
  if (origin !== undefined && origin !== '') {
    if (origin === 'null' || !allowed.has(origin)) {
      return NextResponse.json(
        { detail: 'Cross-origin request blocked.' },
        { status: 403 }
      );
    }
    return null;
  }

  const referer = request.headers.get('referer')?.trim();
  if (referer) {
    try {
      const refOrigin = new URL(referer).origin;
      if (!allowed.has(refOrigin)) {
        return NextResponse.json(
          { detail: 'Cross-origin referer blocked.' },
          { status: 403 }
        );
      }
      return null;
    } catch {
      return NextResponse.json(
        { detail: 'Invalid referer header.' },
        { status: 403 }
      );
    }
  }

  const cookieHeader = request.headers.get('cookie') ?? '';
  const hasSessionCookie =
    cookieHeader.includes(`${ACCESS_COOKIE_NAME}=`) ||
    cookieHeader.includes(`${REFRESH_COOKIE_NAME}=`);
  const hasAuthHeader = Boolean(request.headers.get('authorization')?.trim());

  if (hasSessionCookie && !hasAuthHeader) {
    return NextResponse.json(
      { detail: 'Origin header is required for cookie-authenticated mutations.' },
      { status: 403 }
    );
  }

  return null;
}

export function getWorkerBaseUrl(): string {
  const configured =
    process.env.WORKER_API_URL ??
    process.env.NEXT_PUBLIC_WORKER_API_URL ??
    'http://127.0.0.1:8000';
  return configured.replace(/\/+$/, '');
}

export function extractCookieValue(
  cookieHeader: string | null,
  cookieName: string
): string | null {
  if (!cookieHeader) {
    return null;
  }
  const parts = cookieHeader.split(';');
  for (const part of parts) {
    const eqIndex = part.indexOf('=');
    if (eqIndex <= 0) {
      continue;
    }
    const name = part.slice(0, eqIndex).trim();
    if (name === cookieName) {
      const val = part.slice(eqIndex + 1).trim();
      if (!val) {
        return null;
      }
      try {
        return decodeURIComponent(val);
      } catch {
        return val;
      }
    }
  }
  return null;
}

export function buildWorkerForwardHeaders(
  request: Request,
  extraHeaders?: Record<string, string>
): Headers {
  const headers = new Headers(extraHeaders);

  const authHeader = request.headers.get('authorization');
  const cookieHeader = request.headers.get('cookie');
  if (authHeader) {
    headers.set('authorization', authHeader);
  } else {
    const cookieToken = extractCookieValue(cookieHeader, ACCESS_COOKIE_NAME);
    if (cookieToken) {
      headers.set('authorization', `Bearer ${cookieToken}`);
    }
  }

  if (cookieHeader) {
    headers.set('cookie', cookieHeader);
  }

  const workerKey = process.env.WORKER_API_KEY?.trim();
  if (workerKey) {
    headers.set('x-worker-api-key', workerKey);
  }

  const passthroughNames = [
    'idempotency-key',
    'stripe-signature',
    'x-filename',
    'x-request-id',
  ];
  for (const name of passthroughNames) {
    const value = request.headers.get(name);
    if (value) {
      headers.set(name, value);
    }
  }

  return headers;
}

export function copySetCookieHeaders(
  sourceHeaders: Headers,
  targetHeaders: Headers
): void {
  const withGetSetCookie = sourceHeaders as Headers & {
    getSetCookie?: () => string[];
  };
  if (typeof withGetSetCookie.getSetCookie === 'function') {
    const cookies = withGetSetCookie.getSetCookie();
    for (const cookie of cookies) {
      targetHeaders.append('set-cookie', cookie);
    }
    return;
  }
  const raw = sourceHeaders.get('set-cookie');
  if (raw) {
    targetHeaders.append('set-cookie', raw);
  }
}

export async function fetchWorker(
  request: Request,
  workerPath: string,
  options: {
    method?: string;
    body?: BodyInit | null;
    extraHeaders?: Record<string, string>;
    timeoutMs?: number;
  } = {}
): Promise<Response | null> {
  const url = `${getWorkerBaseUrl()}${workerPath}`;
  const controller = new AbortController();
  const timeoutMs = options.timeoutMs ?? DEFAULT_WORKER_TIMEOUT_MS;
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const headers = buildWorkerForwardHeaders(request, options.extraHeaders);
    return await fetch(url, {
      method: options.method ?? request.method,
      headers,
      body: options.body,
      signal: controller.signal,
      cache: 'no-store',
    });
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

export function workerUnavailableResponse(
  detail = 'Video worker service unavailable. Ensure the FastAPI worker is running.'
): NextResponse {
  return NextResponse.json({ detail }, { status: 503 });
}

export async function forwardWorkerJsonResponse(
  workerRes: Response,
  options: {
    statusOverride?: number;
    forwardCookies?: boolean;
    transformPayload?: (data: unknown) => unknown;
  } = {}
): Promise<NextResponse> {
  const rawText = await workerRes.text();
  let parsed: unknown;
  try {
    parsed = rawText ? (JSON.parse(rawText) as unknown) : {};
  } catch {
    parsed = { detail: rawText || `Worker returned HTTP ${workerRes.status}` };
  }

  const finalPayload =
    workerRes.ok && options.transformPayload
      ? options.transformPayload(parsed)
      : parsed;

  const statusCode =
    workerRes.ok && options.statusOverride !== undefined
      ? options.statusOverride
      : workerRes.status;

  const response = NextResponse.json(finalPayload, { status: statusCode });
  const requestId = workerRes.headers.get('x-request-id');
  if (requestId) {
    response.headers.set('x-request-id', requestId);
  }
  if (options.forwardCookies) {
    copySetCookieHeaders(workerRes.headers, response.headers);
  }
  return response;
}

export function normalizeVideoJob(job: VideoJobRecord): VideoJobRecord {
  const hasCompletedVideo =
    job.status === 'COMPLETED' && Boolean(job.final_mp4_url);
  return {
    ...job,
    final_mp4_url: hasCompletedVideo ? `/api/v1/renders/${job.id}` : null,
  };
}
