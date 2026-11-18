import { NextResponse } from 'next/server';
import {
  fetchWorker,
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
  const { jobId } = await context.params;
  const rawJobId = (jobId ?? '').replace(/\.mp4$/i, '').trim();
  if (!rawJobId || !isValidUuid(rawJobId)) {
    return NextResponse.json(
      { detail: 'Valid UUID jobId is required.' },
      { status: 400 }
    );
  }

  const { searchParams } = new URL(request.url);
  const signedToken = searchParams.get('token')?.trim();
  const suffix = signedToken
    ? `?token=${encodeURIComponent(signedToken)}`
    : '';

  const workerRes = await fetchWorker(
    request,
    `/v1/videos/${encodeURIComponent(rawJobId)}/download${suffix}`,
    { method: 'GET', timeoutMs: 30000 }
  );

  if (!workerRes) {
    return workerUnavailableResponse();
  }

  if (!workerRes.ok) {
    const errText = await workerRes.text();
    let payload: unknown;
    try {
      payload = errText ? (JSON.parse(errText) as unknown) : {};
    } catch {
      payload = { detail: errText || `Download failed (${workerRes.status})` };
    }
    return NextResponse.json(payload, { status: workerRes.status });
  }

  const headers: Record<string, string> = {
    'Content-Type': 'video/mp4',
    'Content-Disposition': `attachment; filename="localized-ad-${rawJobId.slice(0, 8)}.mp4"`,
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
  };
  const contentLength = workerRes.headers.get('content-length');
  if (contentLength) {
    headers['Content-Length'] = contentLength;
  }

  return new NextResponse(workerRes.body, {
    status: 200,
    headers,
  });
}
