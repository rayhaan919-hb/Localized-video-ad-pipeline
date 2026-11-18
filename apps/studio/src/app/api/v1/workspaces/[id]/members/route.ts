import { NextResponse } from 'next/server';
import {
  assertSameOriginRequest,
  fetchWorker,
  forwardWorkerJsonResponse,
  isValidUuid,
  workerUnavailableResponse,
} from '@/lib/serverStore';

interface RouteContext {
  params: Promise<{
    id: string;
  }>;
}

export async function POST(
  request: Request,
  context: RouteContext
): Promise<NextResponse> {
  const csrfErr = assertSameOriginRequest(request);
  if (csrfErr) {
    return csrfErr;
  }

  const { id } = await context.params;
  const workspaceId = (id ?? '').trim();
  if (!workspaceId || !isValidUuid(workspaceId)) {
    return NextResponse.json(
      { detail: 'Valid UUID workspace id is required.' },
      { status: 400 }
    );
  }

  const rawBody = await request.text();
  const workerRes = await fetchWorker(
    request,
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/members`,
    {
      method: 'POST',
      extraHeaders: { 'content-type': 'application/json' },
      body: rawBody || '{}',
    }
  );
  if (!workerRes) {
    return workerUnavailableResponse();
  }
  return forwardWorkerJsonResponse(workerRes);
}
