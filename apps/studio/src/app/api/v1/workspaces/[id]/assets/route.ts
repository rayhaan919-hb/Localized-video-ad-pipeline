import { NextResponse } from 'next/server';
import {
  fetchWorker,
  forwardWorkerJsonResponse,
  workerUnavailableResponse,
} from '@/lib/serverStore';

interface RouteContext {
  params: {
    id: string;
  };
}

export async function GET(
  request: Request,
  context: RouteContext
): Promise<NextResponse> {
  const workspaceId = (context.params.id ?? '').trim();
  if (!workspaceId) {
    return NextResponse.json(
      { detail: 'workspace id is required.' },
      { status: 400 }
    );
  }

  const workerRes = await fetchWorker(
    request,
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/assets`,
    { method: 'GET' }
  );
  if (!workerRes) {
    return workerUnavailableResponse();
  }
  return forwardWorkerJsonResponse(workerRes);
}

export async function POST(
  request: Request,
  context: RouteContext
): Promise<NextResponse> {
  const workspaceId = (context.params.id ?? '').trim();
  if (!workspaceId) {
    return NextResponse.json(
      { detail: 'workspace id is required.' },
      { status: 400 }
    );
  }

  const rawBuffer = await request.arrayBuffer();
  const contentType =
    request.headers.get('content-type') ?? 'application/octet-stream';

  const workerRes = await fetchWorker(
    request,
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/assets`,
    {
      method: 'POST',
      extraHeaders: { 'content-type': contentType },
      timeoutMs: 20000,
      body: rawBuffer,
    }
  );
  if (!workerRes) {
    return workerUnavailableResponse();
  }
  return forwardWorkerJsonResponse(workerRes);
}
