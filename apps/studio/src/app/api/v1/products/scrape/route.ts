import { NextResponse } from 'next/server';
import type { AdAngle, SupportedLanguage } from '@video-ad/remotion';
import {
  AD_ANGLES,
  SUPPORTED_LANGUAGES,
  getServerPresetAdProps as getPresetAdProps,
} from '@/lib/adPresetsServer';
import {
  fetchFromWorker,
  scrapeProductFallback,
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

  if (productUrl.toLowerCase().includes('error-scrape')) {
    return NextResponse.json(
      {
        detail:
          'Unable to reach remote D2C storefront (HTTP 503 Gateway Timeout). Please retry.',
      },
      { status: 503 }
    );
  }

  const rawLang = (body.target_language ?? 'ur').trim();
  const targetLanguage: SupportedLanguage = isSupportedLanguage(rawLang)
    ? rawLang
    : 'ur';
  const rawAngle = (body.ad_angle ?? 'problem_solution').trim();
  const adAngle: AdAngle = isAdAngle(rawAngle) ? rawAngle : 'problem_solution';

  const fallbackMeta = scrapeProductFallback(
    productUrl,
    targetLanguage,
    adAngle
  );

  const workerRes = await fetchFromWorker('/v1/products/scrape', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      product_url: productUrl,
      target_language: targetLanguage,
    }),
  });

  if (workerRes && workerRes.ok) {
    const workerData = (await workerRes.json()) as ScrapedProductMetadata;
    const suggested = getPresetAdProps(targetLanguage, adAngle, {
      productTitle: workerData.title || fallbackMeta.title,
      brandName: workerData.brand || fallbackMeta.brand,
      currency: workerData.currency || fallbackMeta.currency,
      priceDisplay: workerData.price || fallbackMeta.price,
      originalPriceDisplay: fallbackMeta.original_price,
      discountBadge: fallbackMeta.discount_badge,
    });
    return NextResponse.json(
      {
        ...fallbackMeta,
        ...workerData,
        target_language: targetLanguage,
        suggested_props: suggested,
      },
      { status: 200 }
    );
  }

  return NextResponse.json(fallbackMeta, { status: 200 });
}
