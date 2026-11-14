import { NextResponse } from 'next/server';
import { fetchFromWorker, getRenderMp4Buffer } from '@/lib/serverStore';

interface RouteContext {
  params: {
    jobId: string;
  };
}

export async function GET(
  _request: Request,
  context: RouteContext
): Promise<NextResponse> {
  const rawJobId = (context.params.jobId ?? 'sample').replace(/\.mp4$/i, '');

  const workerRes = await fetchFromWorker(
    `/static/renders/${encodeURIComponent(rawJobId)}.mp4`,
    { method: 'GET' }
  );

  if (workerRes && workerRes.ok) {
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

  const mp4Buffer = getRenderMp4Buffer(rawJobId);
  return new NextResponse(new Uint8Array(mp4Buffer), {
    status: 200,
    headers: {
      'Content-Type': 'video/mp4',
      'Content-Disposition': `attachment; filename="localized-ad-${rawJobId.slice(0, 8)}.mp4"`,
      'Cache-Control': 'no-store',
    },
  });
}
