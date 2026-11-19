import { NextResponse } from 'next/server';
import { copySetCookieHeaders, fetchWorker } from '@/lib/serverStore';

function clearOAuthStateRedirect(url: URL): NextResponse {
  const res = NextResponse.redirect(url, 302);
  res.cookies.delete('lva_oauth_state');
  return res;
}

export async function GET(request: Request): Promise<NextResponse> {
  const { searchParams } = new URL(request.url);
  const oauthError = searchParams.get('error')?.trim();
  const code = searchParams.get('code')?.trim() ?? '';
  const state = searchParams.get('state')?.trim() ?? '';

  if (oauthError) {
    return clearOAuthStateRedirect(
      new URL('/?auth_error=google_cancelled', request.url)
    );
  }

  if (!code || !state) {
    return clearOAuthStateRedirect(
      new URL('/?auth_error=google_auth_failed', request.url)
    );
  }

  const workerRes = await fetchWorker(request, '/v1/auth/google/callback', {
    method: 'POST',
    extraHeaders: { 'content-type': 'application/json' },
    body: JSON.stringify({ code, state }),
    timeoutMs: 20000,
  });

  if (!workerRes || !workerRes.ok) {
    const errorCode =
      workerRes?.status === 403
        ? 'google_email_unverified'
        : 'google_auth_failed';
    return clearOAuthStateRedirect(
      new URL(`/?auth_error=${errorCode}`, request.url)
    );
  }

  const response = NextResponse.redirect(
    new URL('/?auth=google_success', request.url),
    302
  );
  copySetCookieHeaders(workerRes.headers, response.headers);
  return response;
}
