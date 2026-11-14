import { NextResponse } from 'next/server';
import type {
  AdAngle,
  CaptionSegment,
  SupportedLanguage,
} from '@video-ad/remotion';
import { AD_ANGLES, SUPPORTED_LANGUAGES } from '@/lib/adPresetsServer';
import {
  createVideoJobFallback,
  fetchFromWorker,
} from '@/lib/serverStore';
import { DEFAULT_WORKSPACE_ID } from '@/lib/supabase';
import type { VideoJobRecord } from '@/types/studio';

interface GenerateRequestBody {
  workspace_id?: string;
  product_url?: string;
  target_language?: string;
  ad_angle?: string;
  simulate_failure?: boolean;
  custom_props?: {
    productTitle?: string;
    brandName?: string;
    priceDisplay?: string;
    originalPriceDisplay?: string;
    discountBadge?: string;
    hookText?: string;
    ctaText?: string;
    captions?: CaptionSegment[];
  };
}

function isSupportedLanguage(val: string): val is SupportedLanguage {
  return (SUPPORTED_LANGUAGES as readonly string[]).includes(val);
}

function isAdAngle(val: string): val is AdAngle {
  return (AD_ANGLES as readonly string[]).includes(val);
}

export async function POST(request: Request): Promise<NextResponse> {
  let body: GenerateRequestBody;
  try {
    body = (await request.json()) as GenerateRequestBody;
  } catch {
    return NextResponse.json(
      { detail: 'Invalid JSON payload' },
      { status: 400 }
    );
  }

  const workspaceId = (body.workspace_id ?? DEFAULT_WORKSPACE_ID).trim();
  const productUrl = (body.product_url ?? '').trim();
  const rawLang = (body.target_language ?? 'ur').trim();
  const rawAngle = (body.ad_angle ?? 'problem_solution').trim();

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

  // First try proxying to the FastAPI worker if reachable
  const workerRes = await fetchFromWorker('/v1/videos/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      workspace_id: workspaceId,
      product_url: productUrl,
      target_language: rawLang,
      ad_angle: adAngle,
      simulate_failure: Boolean(body.simulate_failure),
    }),
  });

  if (workerRes) {
    const workerData = (await workerRes.json()) as VideoJobRecord & {
      detail?: string;
    };
    if (!workerRes.ok) {
      return NextResponse.json(workerData, { status: workerRes.status });
    }
    if (workerData.final_mp4_url?.startsWith('/static/renders/')) {
      workerData.final_mp4_url = `/api/v1/renders/${workerData.id}`;
    }
    return NextResponse.json(workerData, { status: 202 });
  }

  // Fallback to deterministic studio store with atomic credit deduction
  const result = createVideoJobFallback({
    workspaceId,
    productUrl,
    targetLanguage: rawLang,
    adAngle,
    simulateFailure: Boolean(body.simulate_failure),
    customProps: body.custom_props,
  });

  if (!result.ok) {
    return NextResponse.json(
      { detail: result.detail, credit_balance: result.workspace.credit_balance },
      { status: result.status }
    );
  }

  return NextResponse.json(result.job, { status: 202 });
}
