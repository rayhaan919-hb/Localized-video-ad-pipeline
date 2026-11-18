import { NextResponse } from 'next/server';
import {
  fetchWorker,
  isValidUuid,
  workerUnavailableResponse,
} from '@/lib/serverStore';

interface RouteContext {
  params: Promise<{
    assetId: string;
  }>;
}

const ALLOWED_ASSET_MIME = new Set([
  'image/png',
  'image/jpeg',
  'image/webp',
]);

export async function GET(
  request: Request,
  context: RouteContext
): Promise<NextResponse> {
  const { assetId: rawAssetId } = await context.params;
  const assetId = (rawAssetId ?? '').trim();
  if (!assetId || !isValidUuid(assetId)) {
    return NextResponse.json(
      { detail: 'Valid UUID assetId is required.' },
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

  const rawType = (workerRes.headers.get('content-type') ?? '')
    .split(';')[0]
    .trim()
    .toLowerCase();
  const safeType = ALLOWED_ASSET_MIME.has(rawType)
    ? rawType
    : 'application/octet-stream';

  const headers: Record<string, string> = {
    'Content-Type': safeType,
    'Cache-Control': 'private, max-age=300',
    'X-Content-Type-Options': 'nosniff',
    'Content-Security-Policy': "default-src 'none'; sandbox",
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
