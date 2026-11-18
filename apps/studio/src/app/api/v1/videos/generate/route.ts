import { NextResponse } from 'next/server';
import type {
  AdAngle,
  CaptionSegment,
  SupportedLanguage,
} from '@video-ad/remotion';
import { AD_ANGLES, SUPPORTED_LANGUAGES } from '@/lib/adPresetsServer';
import {
  assertSameOriginRequest,
  fetchWorker,
  forwardWorkerJsonResponse,
  isValidUuid,
  normalizeVideoJob,
  workerUnavailableResponse,
} from '@/lib/serverStore';
import type { VideoJobRecord } from '@/types/studio';

interface GenerateRequestBody {
  workspace_id?: string;
  product_url?: string;
  target_language?: string;
  ad_angle?: string;
  aspect_ratio?: '9:16' | '16:9';
  duration_seconds?: number;
  simulate_failure?: boolean;
  custom_props?: {
    productTitle?: string;
    brandName?: string;
    priceDisplay?: string;
    originalPriceDisplay?: string;
    discountBadge?: string;
    hookText?: string;
    ctaText?: string;
    productImageUrl?: string;
    productImageAssetId?: string;
    captions?: CaptionSegment[];
    confirmedMetadata?: Record<string, unknown>;
  };
}

function isSupportedLanguage(val: string): val is SupportedLanguage {
  return (SUPPORTED_LANGUAGES as readonly string[]).includes(val);
}

function isAdAngle(val: string): val is AdAngle {
  return (AD_ANGLES as readonly string[]).includes(val);
}

export async function POST(request: Request): Promise<NextResponse> {
  const csrfErr = assertSameOriginRequest(request);
  if (csrfErr) {
    return csrfErr;
  }

  let body: GenerateRequestBody;
  try {
    body = (await request.json()) as GenerateRequestBody;
  } catch {
    return NextResponse.json(
      { detail: 'Invalid JSON payload' },
      { status: 400 }
    );
  }

  const workspaceId = (body.workspace_id ?? '').trim();
  if (!workspaceId || !isValidUuid(workspaceId)) {
    return NextResponse.json(
      { detail: 'Valid UUID workspace_id is required.' },
      { status: 422 }
    );
  }

  const productUrl = (body.product_url ?? '').trim();
  const rawLang = (body.target_language ?? 'ur').trim();
  const rawAngle = (body.ad_angle ?? 'problem_solution').trim();
  const aspectRatio = body.aspect_ratio === '16:9' ? '16:9' : '9:16';

  if (!productUrl || !/^https?:\/\/.+/i.test(productUrl)) {
    return NextResponse.json(
      { detail: 'A valid http(s) product_url is required.' },
      { status: 422 }
    );
  }

  if (!isSupportedLanguage(rawLang)) {
    return NextResponse.json(
      { detail: 'target_language must be one of: ur, ar, hi, en' },
      { status: 422 }
    );
  }

  const adAngle: AdAngle = isAdAngle(rawAngle) ? rawAngle : 'problem_solution';
  const durationSeconds =
    typeof body.duration_seconds === 'number' &&
    Number.isFinite(body.duration_seconds)
      ? Math.max(2, Math.min(15, body.duration_seconds))
      : 4;

  const customProps =
    body.custom_props && typeof body.custom_props === 'object'
      ? body.custom_props
      : undefined;

  const workerRes = await fetchWorker(request, '/v1/videos/generate', {
    method: 'POST',
    extraHeaders: { 'content-type': 'application/json' },
    timeoutMs: 30000,
    body: JSON.stringify({
      workspace_id: workspaceId,
      product_url: productUrl,
      target_language: rawLang,
      ad_angle: adAngle,
      aspect_ratio: aspectRatio,
      duration_seconds: durationSeconds,
      simulate_failure: Boolean(body.simulate_failure),
      ...(customProps ? { custom_props: customProps } : {}),
    }),
  });

  if (!workerRes) {
    return workerUnavailableResponse();
  }

  return forwardWorkerJsonResponse(workerRes, {
    transformPayload: (data) => normalizeVideoJob(data as VideoJobRecord),
  });
}
