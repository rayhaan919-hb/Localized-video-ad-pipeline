import { NextResponse } from 'next/server';
import { fetchWorker, workerUnavailableResponse } from '@/lib/serverStore';

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
  if (!rawJobId) {
    return NextResponse.json({ detail: 'jobId is required.' }, { status: 400 });
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

  const arrayBuf = await workerRes.arrayBuffer();
  return new NextResponse(arrayBuf, {
    status: 200,
    headers: {
      'Content-Type': 'video/mp4',
      'Content-Disposition': `attachment; filename="localized-ad-${rawJobId.slice(0, 8)}.mp4"`,
      'Cache-Control': 'no-store',
    },
  });
}
