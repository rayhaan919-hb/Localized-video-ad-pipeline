import { NextResponse } from 'next/server';
import { fetchWorker, workerUnavailableResponse } from '@/lib/serverStore';

interface RouteContext {
  params: {
    assetId: string;
  };
}

export async function GET(
  request: Request,
  context: RouteContext
): Promise<NextResponse> {
  const assetId = (context.params.assetId ?? '').trim();
  if (!assetId) {
    return NextResponse.json(
      { detail: 'assetId is required.' },
      { status: 400 }
    );
  }

  const workerRes = await fetchWorker(
    request,
    `/v1/assets/${encodeURIComponent(assetId)}`,
    { method: 'GET', timeoutMs: 20000 }
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
      payload = { detail: errText || `Asset fetch failed (${workerRes.status})` };
    }
    return NextResponse.json(payload, { status: workerRes.status });
  }

  const arrayBuf = await workerRes.arrayBuffer();
  return new NextResponse(arrayBuf, {
    status: 200,
    headers: {
      'Content-Type':
        workerRes.headers.get('content-type') ?? 'application/octet-stream',
      'Cache-Control': 'private, max-age=300',
    },
  });
}
