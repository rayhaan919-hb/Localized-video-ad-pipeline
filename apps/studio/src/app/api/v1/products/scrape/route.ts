import { NextResponse } from 'next/server';
import type { AdAngle, SupportedLanguage } from '@video-ad/remotion';
import {
  AD_ANGLES,
  SUPPORTED_LANGUAGES,
  getServerPresetAdProps,
} from '@/lib/adPresetsServer';
import {
  assertSameOriginRequest,
  fetchWorker,
  workerUnavailableResponse,
} from '@/lib/serverStore';
import type { ScrapedProductMetadata } from '@/types/studio';

interface ScrapeBody {
  product_url?: string;
  target_language?: string;
  ad_angle?: string;
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

  let body: ScrapeBody;
  try {
    body = (await request.json()) as ScrapeBody;
  } catch {
    return NextResponse.json(
      { detail: 'Invalid JSON request body' },
      { status: 400 }
    );
  }

  const productUrl = (body.product_url ?? '').trim();
  if (!productUrl || !/^https?:\/\/.+/i.test(productUrl)) {
    return NextResponse.json(
      {
        detail:
          'Please enter a valid D2C product URL starting with https:// or http://',
      },
      { status: 422 }
    );
  }

  const rawLang = (body.target_language ?? 'ur').trim();
  const targetLanguage: SupportedLanguage = isSupportedLanguage(rawLang)
    ? rawLang
    : 'ur';
  const rawAngle = (body.ad_angle ?? 'problem_solution').trim();
  const adAngle: AdAngle = isAdAngle(rawAngle) ? rawAngle : 'problem_solution';

  const workerRes = await fetchWorker(request, '/v1/products/scrape', {
    method: 'POST',
    extraHeaders: { 'content-type': 'application/json' },
    timeoutMs: 15000,
    body: JSON.stringify({
      product_url: productUrl,
      target_language: targetLanguage,
    }),
  });

  if (!workerRes) {
    return workerUnavailableResponse();
  }

  const rawText = await workerRes.text();
  let parsed: Record<string, unknown>;
  try {
    parsed = rawText ? (JSON.parse(rawText) as Record<string, unknown>) : {};
  } catch {
    parsed = { detail: rawText || `Worker returned HTTP ${workerRes.status}` };
  }

  if (!workerRes.ok) {
    return NextResponse.json(parsed, { status: workerRes.status });
  }

  const workerData = parsed as unknown as ScrapedProductMetadata;
  const scriptScaffolding = getServerPresetAdProps(targetLanguage, adAngle);

  // Never invent unverified factual product fields (title, brand, price, discount).
  const suggestedProps = {
    ...scriptScaffolding,
    productTitle: workerData.title ?? '',
    brandName: workerData.brand ?? '',
    currency: workerData.currency ?? '',
    priceDisplay: workerData.price ?? '',
    originalPriceDisplay: workerData.original_price ?? '',
    discountBadge: workerData.discount_badge ?? '',
    productImageUrl: workerData.image_url || undefined,
  };

  return NextResponse.json(
    {
      ...workerData,
      target_language: targetLanguage,
      suggested_props: suggestedProps,
    },
    { status: 200 }
  );
}
