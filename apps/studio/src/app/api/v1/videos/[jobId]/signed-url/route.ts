import { NextResponse } from 'next/server';
import {
  fetchWorker,
  forwardWorkerJsonResponse,
  isValidUuid,
  workerUnavailableResponse,
} from '@/lib/serverStore';

interface RouteContext {
  params: Promise<{
    jobId: string;
  }>;
}

export async function GET(
  request: Request,
  context: RouteContext
): Promise<NextResponse> {
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
    `/v1/videos/${encodeURIComponent(jobId)}/signed-url`,
    { method: 'GET' }
  );
  if (!workerRes) {
    return workerUnavailableResponse();
  }

  return forwardWorkerJsonResponse(workerRes, {
    transformPayload: (data) => {
      const payload = data as {
        job_id?: string;
        download_path?: string;
        expires_at?: number;
      };
      const rawPath = payload.download_path ?? '';
      const qIdx = rawPath.indexOf('?');
      const tokenQuery = qIdx >= 0 ? rawPath.slice(qIdx) : '';
      return {
        ...payload,
        download_path: `/api/v1/renders/${encodeURIComponent(jobId)}${tokenQuery}`,
      };
    },
  });
}
