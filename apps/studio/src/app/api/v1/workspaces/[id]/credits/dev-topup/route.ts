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

  const rawBody = await request.text();
  const workerRes = await fetchWorker(
    request,
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/credits/dev-topup`,
    {
      method: 'POST',
      extraHeaders: { 'content-type': 'application/json' },
      body: rawBody || '{"pack_id":"starter_10"}',
    }
  );
  if (!workerRes) {
    return workerUnavailableResponse();
  }
  return forwardWorkerJsonResponse(workerRes);
}
