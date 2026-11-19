import { NextResponse } from 'next/server';
import { copySetCookieHeaders, fetchWorker } from '@/lib/serverStore';

export async function GET(request: Request): Promise<NextResponse> {
  const { searchParams } = new URL(request.url);
  const mode = searchParams.get('mode') === 'register' ? 'register' : 'login';

  const workerRes = await fetchWorker(
    request,
    `/v1/auth/google/start?mode=${encodeURIComponent(mode)}`,
    { method: 'GET' }
  );

  if (!workerRes || !workerRes.ok) {
    const errorCode =
      workerRes?.status === 503 ? 'google_not_configured' : 'google_start_failed';
    return NextResponse.redirect(
      new URL(`/?auth_error=${errorCode}`, request.url),
      302
    );
  }

  let data: { authorization_url?: string } = {};
  try {
    data = (await workerRes.json()) as { authorization_url?: string };
  } catch {
    data = {};
  }

  const authUrl = data.authorization_url ?? '';
  if (!authUrl.startsWith('https://accounts.google.com/')) {
    return NextResponse.redirect(
      new URL('/?auth_error=google_start_failed', request.url),
      302
    );
  }

  const response = NextResponse.redirect(authUrl, 302);
  copySetCookieHeaders(workerRes.headers, response.headers);
  return response;
}
