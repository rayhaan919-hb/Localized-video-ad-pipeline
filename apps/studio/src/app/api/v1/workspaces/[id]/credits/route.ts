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

interface CheckoutPayload {
  pack_id?: string;
  success_url?: string;
  cancel_url?: string;
}

export async function GET(
  request: Request,
  context: RouteContext
): Promise<NextResponse> {
  const { id } = await context.params;
  const workspaceId = (id ?? '').trim();
  if (!workspaceId || !isValidUuid(workspaceId)) {
    return NextResponse.json(
      { detail: 'Valid UUID workspace id is required.' },
      { status: 400 }
    );
  }

  const workerRes = await fetchWorker(
    request,
    `/v1/workspaces/${encodeURIComponent(workspaceId)}`,
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

  let body: CheckoutPayload = {};
  try {
    body = (await request.json()) as CheckoutPayload;
  } catch {
    body = {};
  }

  const packId = (body.pack_id ?? '').trim();
  if (!['starter_10', 'growth_50', 'scale_200'].includes(packId)) {
    return NextResponse.json(
      { detail: 'pack_id must be one of: starter_10, growth_50, scale_200' },
      { status: 422 }
    );
  }

  // Only forward server-recognized pack_id and redirect URLs; never trust amounts/credits.
  const workerRes = await fetchWorker(
    request,
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/credits/checkout`,
    {
      method: 'POST',
      extraHeaders: { 'content-type': 'application/json' },
      body: JSON.stringify({
        pack_id: packId,
        ...(body.success_url ? { success_url: body.success_url } : {}),
        ...(body.cancel_url ? { cancel_url: body.cancel_url } : {}),
      }),
    }
  );

  if (!workerRes) {
    return workerUnavailableResponse();
  }

  return forwardWorkerJsonResponse(workerRes);
}
