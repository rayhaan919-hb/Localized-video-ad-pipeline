import type { NextResponse } from 'next/server';
import {
  fetchWorker,
  forwardWorkerJsonResponse,
  workerUnavailableResponse,
} from '@/lib/serverStore';

export async function GET(request: Request): Promise<NextResponse> {
  const workerRes = await fetchWorker(request, '/v1/workspaces', {
    method: 'GET',
  });
  if (!workerRes) {
    return workerUnavailableResponse();
  }
  return forwardWorkerJsonResponse(workerRes);
}

export async function POST(request: Request): Promise<NextResponse> {
  const rawBody = await request.text();
  const workerRes = await fetchWorker(request, '/v1/workspaces', {
    method: 'POST',
    extraHeaders: { 'content-type': 'application/json' },
    body: rawBody || '{}',
  });
  if (!workerRes) {
    return workerUnavailableResponse();
  }
  return forwardWorkerJsonResponse(workerRes);
}
