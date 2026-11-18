import { NextResponse } from 'next/server';
import {
  fetchWorker,
  forwardWorkerJsonResponse,
  normalizeVideoJob,
  workerUnavailableResponse,
} from '@/lib/serverStore';
import type { VideoJobRecord } from '@/types/studio';

interface RouteContext {
  params: Promise<{
    jobId: string;
  }>;
}

export async function POST(
  request: Request,
  context: RouteContext
): Promise<NextResponse> {
  const { jobId: rawJobId } = await context.params;
  const jobId = (rawJobId ?? '').trim();
  if (!jobId) {
    return NextResponse.json({ detail: 'jobId is required.' }, { status: 400 });
  }

  const workerRes = await fetchWorker(
    request,
    `/v1/videos/${encodeURIComponent(jobId)}/retry`,
    { method: 'POST', timeoutMs: 30000 }
  );
  if (!workerRes) {
    return workerUnavailableResponse();
  }

  return forwardWorkerJsonResponse(workerRes, {
    transformPayload: (data) => normalizeVideoJob(data as VideoJobRecord),
  });
}
