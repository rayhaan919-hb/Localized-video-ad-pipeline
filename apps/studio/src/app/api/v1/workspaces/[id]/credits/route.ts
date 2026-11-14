import { NextResponse } from 'next/server';
import {
  ensureWorkspaceFallback,
  fetchFromWorker,
  topUpCreditsFallback,
} from '@/lib/serverStore';
import { DEFAULT_WORKSPACE_ID } from '@/lib/supabase';
import type { WorkspaceInfo } from '@/types/studio';

interface RouteContext {
  params: {
    id: string;
  };
}

interface CheckoutPayload {
  credits?: number;
  pack_id?: string;
}

export async function GET(
  _request: Request,
  context: RouteContext
): Promise<NextResponse> {
  const workspaceId = context.params.id || DEFAULT_WORKSPACE_ID;

  const workerRes = await fetchFromWorker(
    `/v1/workspaces/${encodeURIComponent(workspaceId)}`,
    { method: 'GET' }
  );

  if (workerRes && workerRes.ok) {
    const data = (await workerRes.json()) as WorkspaceInfo;
    return NextResponse.json(data, { status: 200 });
  }

  const ws = ensureWorkspaceFallback(workspaceId);
  return NextResponse.json(ws, { status: 200 });
}

export async function POST(
  request: Request,
  context: RouteContext
): Promise<NextResponse> {
  const workspaceId = context.params.id || DEFAULT_WORKSPACE_ID;

  let body: CheckoutPayload = {};
  try {
    body = (await request.json()) as CheckoutPayload;
  } catch {
    body = {};
  }

  const credits = Number(body.credits ?? 10);
  const packId = (body.pack_id ?? 'starter_10').trim();

  if (!Number.isFinite(credits) || credits <= 0) {
    return NextResponse.json(
      { detail: 'credits must be a positive integer' },
      { status: 422 }
    );
  }

  const workerRes = await fetchFromWorker(
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/credits/checkout`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        credits,
        pack_id: packId,
      }),
    }
  );

  if (workerRes && workerRes.ok) {
    // Also fetch updated ledger from worker
    const wsRes = await fetchFromWorker(
      `/v1/workspaces/${encodeURIComponent(workspaceId)}`,
      { method: 'GET' }
    );
    if (wsRes && wsRes.ok) {
      const wsData = (await wsRes.json()) as WorkspaceInfo;
      return NextResponse.json(wsData, { status: 200 });
    }
  }

  const updated = topUpCreditsFallback(workspaceId, credits, packId);
  return NextResponse.json(updated, { status: 200 });
}
