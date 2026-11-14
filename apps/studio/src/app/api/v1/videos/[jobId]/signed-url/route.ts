import { NextResponse } from 'next/server';
import {
  fetchWorker,
  forwardWorkerJsonResponse,
  workerUnavailableResponse,
} from '@/lib/serverStore';

interface RouteContext {
  params: {
    jobId: string;
  };
}

export async function GET(
  request: Request,
  context: RouteContext
): Promise<NextResponse> {
  const jobId = (context.params.jobId ?? '').trim();
  if (!jobId) {
    return NextResponse.json({ detail: 'jobId is required.' }, { status: 400 });
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
