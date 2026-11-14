import { NextResponse } from 'next/server';
import type { VideoJobRecord } from '@/types/studio';

const ACCESS_COOKIE_NAME = 'lva_access_token';
const DEFAULT_WORKER_TIMEOUT_MS = 10000;

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
