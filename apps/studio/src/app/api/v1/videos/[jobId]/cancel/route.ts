import { NextResponse } from 'next/server';
import {
  assertSameOriginRequest,
  fetchWorker,
  forwardWorkerJsonResponse,
  isValidUuid,
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
  const csrfErr = assertSameOriginRequest(request);
  if (csrfErr) {
    return csrfErr;
  }

  const { jobId: rawJobId } = await context.params;
  const jobId = (rawJobId ?? '').trim();
  if (!jobId || !isValidUuid(jobId)) {
    return NextResponse.json(
      { detail: 'Valid UUID jobId is required.' },
      { status: 400 }
    );
  }

  const workerRes = await fetchWorker(
    request,
    `/v1/videos/${encodeURIComponent(jobId)}/cancel`,
    { method: 'POST' }
  );
  if (!workerRes) {
    return workerUnavailableResponse();
  }

  return forwardWorkerJsonResponse(workerRes, {
    transformPayload: (data) => normalizeVideoJob(data as VideoJobRecord),
  });
}
