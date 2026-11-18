import { NextResponse } from 'next/server';
import {
  fetchWorker,
  forwardWorkerJsonResponse,
  workerUnavailableResponse,
} from '@/lib/serverStore';

interface RouteContext {
  params: Promise<{
    path: string[];
  }>;
}

const ALLOWED_GET_PATHS = new Set(['me']);
const ALLOWED_POST_PATHS = new Set([
  'register',
  'login',
  'refresh',
  'logout',
  'verify-email',
  'password-reset/request',
  'password-reset/confirm',
]);

function resolveAuthPath(segments: string[] | undefined): string {
  return (segments ?? []).map((s) => s.trim()).filter(Boolean).join('/');
}

export async function GET(
  request: Request,
  context: RouteContext
): Promise<NextResponse> {
  const { path } = await context.params;
  const joined = resolveAuthPath(path);
  if (!ALLOWED_GET_PATHS.has(joined)) {
    return NextResponse.json({ detail: 'Not found' }, { status: 404 });
  }

  const workerRes = await fetchWorker(request, `/v1/auth/${joined}`, {
    method: 'GET',
  });
  if (!workerRes) {
    return workerUnavailableResponse();
  }
  return forwardWorkerJsonResponse(workerRes, { forwardCookies: true });
}

export async function POST(
  request: Request,
  context: RouteContext
): Promise<NextResponse> {
  const { path } = await context.params;
  const joined = resolveAuthPath(path);
  if (!ALLOWED_POST_PATHS.has(joined)) {
    return NextResponse.json({ detail: 'Not found' }, { status: 404 });
  }

  const rawBody = await request.text();
  const workerRes = await fetchWorker(request, `/v1/auth/${joined}`, {
    method: 'POST',
    extraHeaders: { 'content-type': 'application/json' },
    body: rawBody || '{}',
  });
  if (!workerRes) {
    return workerUnavailableResponse();
  }
  return forwardWorkerJsonResponse(workerRes, { forwardCookies: true });
}
