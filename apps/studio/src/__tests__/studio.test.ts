import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import {
  assertSameOriginRequest,
  buildWorkerForwardHeaders,
  extractCookieValue,
  isValidUuid,
  normalizeVideoJob,
  stripAuthTokensFromPayload,
} from '../lib/serverStore';
import { CREDIT_PACKAGE_TIERS } from '../lib/supabase';
import {
  getServerLanguageFontMeta,
  getServerPresetAdProps,
} from '../lib/adPresetsServer';
import type { VideoJobRecord } from '../types/studio';

test('extractCookieValue and buildWorkerForwardHeaders propagate auth and service headers', () => {
  const cookieHeader = 'other=1; lva_access_token=jwt.token.value; theme=dark';
  assert.equal(
    extractCookieValue(cookieHeader, 'lva_access_token'),
    'jwt.token.value'
  );
  assert.equal(extractCookieValue(cookieHeader, 'missing'), null);

  const reqCookieOnly = new Request('http://localhost:3000/api/v1/videos', {
    headers: {
      cookie: cookieHeader,
      'idempotency-key': 'idem-123',
      'stripe-signature': 't=1,v1=sig',
    },
  });
  const forwarded = buildWorkerForwardHeaders(reqCookieOnly);
  assert.equal(forwarded.get('authorization'), 'Bearer jwt.token.value');
  assert.equal(forwarded.get('cookie'), cookieHeader);
  assert.equal(forwarded.get('idempotency-key'), 'idem-123');
  assert.equal(forwarded.get('stripe-signature'), 't=1,v1=sig');

  // Explicit Bearer header takes precedence over cookie
  const reqExplicitBearer = new Request('http://localhost:3000/api/v1/videos', {
    headers: {
      authorization: 'Bearer explicit-jwt',
      cookie: cookieHeader,
    },
  });
  const forwardedExplicit = buildWorkerForwardHeaders(reqExplicitBearer);
  assert.equal(forwardedExplicit.get('authorization'), 'Bearer explicit-jwt');
});

test('normalizeVideoJob only exposes download URL when status is COMPLETED', () => {
  const baseJob: VideoJobRecord = {
    id: '11111111-1111-1111-1111-111111111111',
    workspace_id: '22222222-2222-2222-2222-222222222222',
    product_url: 'https://example.com/p',
    target_language: 'ur',
    script_json: null,
    veo_gcs_uri: null,
    final_mp4_url: '/v1/videos/11111111-1111-1111-1111-111111111111/download',
    status: 'PROCESSING',
    created_at: '2026-01-01T00:00:00Z',
  };

  assert.equal(normalizeVideoJob(baseJob).final_mp4_url, null);
  assert.equal(
    normalizeVideoJob({ ...baseJob, status: 'COMPLETED' }).final_mp4_url,
    '/api/v1/renders/11111111-1111-1111-1111-111111111111'
  );
  assert.equal(
    normalizeVideoJob({ ...baseJob, status: 'COMPLETED', final_mp4_url: null })
      .final_mp4_url,
    null
  );
});

test('multi-tenant security refactor removes DEFAULT_WORKSPACE_ID and fake fallbacks from Studio source', () => {
  const cwdCandidate = path.join(process.cwd(), 'src');
  const studioSrcRoot = fs.existsSync(cwdCandidate)
    ? cwdCandidate
    : path.join(process.cwd(), 'apps', 'studio', 'src');
  const supabaseText = fs.readFileSync(
    path.join(studioSrcRoot, 'lib', 'supabase.ts'),
    'utf-8'
  );
  const storeText = fs.readFileSync(
    path.join(studioSrcRoot, 'lib', 'serverStore.ts'),
    'utf-8'
  );
  assert.equal(supabaseText.includes('DEFAULT_WORKSPACE_ID'), false);
  assert.equal(supabaseText.includes('DEFAULT_OWNER_ID'), false);
  assert.equal(storeText.includes('getRenderMp4Buffer'), false);
  assert.equal(storeText.includes('scrapeProductFallback'), false);
  assert.equal(storeText.includes('topUpCreditsFallback'), false);
  assert.deepEqual(
    CREDIT_PACKAGE_TIERS.map((p) => p.id),
    ['starter_10', 'growth_50', 'scale_200']
  );
});

test('RTL/LTR font metadata and localized presets remain consistent', () => {
  assert.equal(getServerLanguageFontMeta('ur').dir, 'rtl');
  assert.equal(getServerLanguageFontMeta('ar').dir, 'rtl');
  assert.equal(getServerLanguageFontMeta('hi').dir, 'ltr');
  assert.equal(getServerLanguageFontMeta('en').dir, 'ltr');

  const urPreset = getServerPresetAdProps('ur', 'flash_sale');
  assert.equal(urPreset.language, 'ur');
  assert.equal(urPreset.captions.length, 3);
});

test('security headers, AuthModal mode sync, and automatic token refresh are wired cleanly', () => {
  const cwdCandidate = path.join(process.cwd(), 'next.config.mjs');
  const studioRoot = fs.existsSync(cwdCandidate)
    ? process.cwd()
    : path.join(process.cwd(), 'apps', 'studio');

  const nextConfigText = fs.readFileSync(
    path.join(studioRoot, 'next.config.mjs'),
    'utf-8'
  );
  assert.equal(nextConfigText.includes('X-Content-Type-Options'), true);
  assert.equal(nextConfigText.includes('X-Frame-Options'), true);
  assert.equal(nextConfigText.includes('Referrer-Policy'), true);
  assert.equal(nextConfigText.includes('Permissions-Policy'), true);

  const authModalText = fs.readFileSync(
    path.join(studioRoot, 'src', 'components', 'AuthModal.tsx'),
    'utf-8'
  );
  assert.equal(authModalText.includes('useEffect'), true);
  assert.equal(authModalText.includes('setMode(initialMode)'), true);

  const workspaceText = fs.readFileSync(
    path.join(studioRoot, 'src', 'components', 'StudioWorkspace.tsx'),
    'utf-8'
  );
  assert.equal(workspaceText.includes('/api/v1/auth/refresh'), true);
});

test('WCAG 2.2 AA tokens, focus indicators, reduced-motion, skip link, and aria-live status are configured', () => {
  const cwdCandidate = path.join(process.cwd(), 'src');
  const studioSrcRoot = fs.existsSync(cwdCandidate)
    ? cwdCandidate
    : path.join(process.cwd(), 'apps', 'studio', 'src');

  const globalsCssText = fs.readFileSync(
    path.join(studioSrcRoot, 'app', 'globals.css'),
    'utf-8'
  );
  assert.equal(globalsCssText.includes('--bg-canvas: #FAF7F2'), true);
  assert.equal(globalsCssText.includes('--accent-solid: #15803D'), true);
  assert.equal(globalsCssText.includes('--accent-text: #166534'), true);
  assert.equal(globalsCssText.includes(':focus-visible'), true);
  assert.equal(globalsCssText.includes('prefers-reduced-motion: reduce'), true);
  assert.equal(globalsCssText.includes('.skip-link'), true);

  const workspaceText = fs.readFileSync(
    path.join(studioSrcRoot, 'components', 'StudioWorkspace.tsx'),
    'utf-8'
  );
  assert.equal(workspaceText.includes('href="#studio-main"'), true);
  assert.equal(workspaceText.includes('aria-live="polite"'), true);
});

test('BFF enforces same-origin CSRF checks, strips raw tokens, validates UUIDs, and serves CSP/HSTS', () => {
  const sameOriginReq = new Request('http://127.0.0.1:3000/api/v1/workspaces', {
    method: 'POST',
    headers: {
      origin: 'http://127.0.0.1:3000',
      cookie: 'lva_access_token=jwt.value',
    },
  });
  assert.equal(assertSameOriginRequest(sameOriginReq), null);

  const crossOriginReq = new Request('http://127.0.0.1:3000/api/v1/workspaces', {
    method: 'POST',
    headers: {
      origin: 'https://evil.example',
      cookie: 'lva_access_token=jwt.value',
    },
  });
  assert.equal(assertSameOriginRequest(crossOriginReq)?.status, 403);

  const nullOriginReq = new Request('http://127.0.0.1:3000/api/v1/workspaces', {
    method: 'POST',
    headers: {
      origin: 'null',
      cookie: 'lva_access_token=jwt.value',
    },
  });
  assert.equal(assertSameOriginRequest(nullOriginReq)?.status, 403);

  const secFetchCrossReq = new Request(
    'http://127.0.0.1:3000/api/v1/workspaces',
    {
      method: 'POST',
      headers: {
        'sec-fetch-site': 'cross-site',
        origin: 'http://127.0.0.1:3000',
      },
    }
  );
  assert.equal(assertSameOriginRequest(secFetchCrossReq)?.status, 403);

  const missingOriginCookieReq = new Request(
    'http://127.0.0.1:3000/api/v1/workspaces',
    {
      method: 'POST',
      headers: {
        cookie: 'lva_refresh_token=secret.refresh',
      },
    }
  );
  assert.equal(assertSameOriginRequest(missingOriginCookieReq)?.status, 403);

  const bearerCliReq = new Request('http://127.0.0.1:3000/api/v1/workspaces', {
    method: 'POST',
    headers: {
      authorization: 'Bearer cli-jwt',
    },
  });
  assert.equal(assertSameOriginRequest(bearerCliReq), null);

  const stripped = stripAuthTokensFromPayload({
    access_token: 'raw-access',
    refresh_token: 'raw-refresh',
    user: { id: 'u1', email: 'a@example.com' },
    primary_workspace_id: '11111111-1111-1111-1111-111111111111',
  }) as Record<string, unknown>;
  assert.equal('access_token' in stripped, false);
  assert.equal('refresh_token' in stripped, false);
  assert.equal(
    stripped.primary_workspace_id,
    '11111111-1111-1111-1111-111111111111'
  );

  assert.equal(
    isValidUuid('11111111-1111-1111-1111-111111111111'),
    true
  );
  assert.equal(isValidUuid('../etc/passwd'), false);
  assert.equal(isValidUuid('bad"id'), false);

  const cwdCandidate = path.join(process.cwd(), 'next.config.mjs');
  const studioRoot = fs.existsSync(cwdCandidate)
    ? process.cwd()
    : path.join(process.cwd(), 'apps', 'studio');
  const nextConfigText = fs.readFileSync(
    path.join(studioRoot, 'next.config.mjs'),
    'utf-8'
  );
  assert.equal(nextConfigText.includes('Content-Security-Policy'), true);
  assert.equal(nextConfigText.includes('Strict-Transport-Security'), true);
});
