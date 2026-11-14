import type { NextResponse } from 'next/server';
import {
  fetchWorker,
  forwardWorkerJsonResponse,
  normalizeVideoJob,
  workerUnavailableResponse,
} from '@/lib/serverStore';
import type { VideoJobRecord } from '@/types/studio';

export async function GET(request: Request): Promise<NextResponse> {
  const { searchParams } = new URL(request.url);
  const workspaceId = searchParams.get('workspace_id')?.trim();
  const query = workspaceId
    ? `?workspace_id=${encodeURIComponent(workspaceId)}`
    : '';

  const workerRes = await fetchWorker(request, `/v1/videos${query}`, {
    method: 'GET',
  });

  if (!workerRes) {
    return workerUnavailableResponse();
  }

  return forwardWorkerJsonResponse(workerRes, {
    transformPayload: (data) =>
      Array.isArray(data)
        ? (data as VideoJobRecord[]).map(normalizeVideoJob)
        : data,
  });
}
