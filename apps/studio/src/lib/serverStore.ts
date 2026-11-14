import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { execFileSync } from 'node:child_process';
import type {
  AdAngle,
  CaptionSegment,
  LocalizedAdProps,
  SupportedLanguage,
} from '@video-ad/remotion';
import {
  getServerLanguageFontMeta as getLanguageFontMeta,
  getServerPresetAdProps as getPresetAdProps,
} from './adPresetsServer';
import { DEFAULT_OWNER_ID, DEFAULT_WORKSPACE_ID } from './supabase';
import type {
  CreditLedgerEntry,
  ScrapedProductMetadata,
  VideoJobRecord,
  VideoJobScriptJson,
  WorkspaceInfo,
} from '@/types/studio';

const WORKER_BASE_URL =
  process.env.WORKER_URL ??
  process.env.NEXT_PUBLIC_WORKER_URL ??
  'http://127.0.0.1:8000';

export function getWorkerBaseUrl(): string {
  return WORKER_BASE_URL.replace(/\/$/, '');
}

export async function fetchFromWorker(
  endpointPath: string,
  init?: RequestInit,
  timeoutMs = 1200
): Promise<Response | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const apiKey = process.env.WORKER_API_KEY?.trim();
  const mergedHeaders = new Headers(init?.headers);
  if (apiKey && !mergedHeaders.has('X-API-Key') && !mergedHeaders.has('Authorization')) {
    mergedHeaders.set('X-API-Key', apiKey);
  }
  try {
    const response = await fetch(`${getWorkerBaseUrl()}${endpointPath}`, {
      ...init,
      headers: mergedHeaders,
      signal: controller.signal,
      cache: 'no-store',
    });
    return response;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

interface CatalogPreset {
  keywords: readonly string[];
  category: string;
  brandByLang: Record<SupportedLanguage, string>;
  titleByLang: Record<SupportedLanguage, string>;
  pricesByLang: Record<
    SupportedLanguage,
    { currency: string; price: string; originalPrice: string; badge: string }
  >;
  features: readonly string[];
  imageUrl: string;
}

export const D2C_CATALOG_PRESETS: readonly CatalogPreset[] = [
  {
    keywords: ['serum', 'glow', 'skin', 'vitamin', 'niacinamide', 'beauty', 'cream', 'zayna'],
    category: 'Skincare',
    brandByLang: {
      ur: 'Zayna Skin Lab',
      ar: 'Noor Atelier Riyadh',
      hi: 'Aarav Botanicals',
      en: 'Kinetix D2C Studio',
    },
    titleByLang: {
      ur: 'وٹامن سی گلو سیرم 30ml',
      ar: 'سيروم النضارة بفيتامين سي النقي',
      hi: 'विटामिन सी रेडिएंस सीरम 30ml',
      en: 'Bio-Active C20 Glass Skin Serum',
    },
    pricesByLang: {
      ur: {
        currency: 'PKR',
        price: 'PKR 4,990',
        originalPrice: 'PKR 7,200',
        badge: '-31% OFF',
      },
      ar: {
        currency: 'SAR',
        price: 'SAR 189',
        originalPrice: 'SAR 275',
        badge: '-31% OFF',
      },
      hi: {
        currency: 'INR',
        price: 'INR 1,499',
        originalPrice: 'INR 2,199',
        badge: '-32% OFF',
      },
      en: {
        currency: 'USD',
        price: 'USD 49.00',
        originalPrice: 'USD 72.00',
        badge: '-32% OFF',
      },
    },
    features: [
      'Clinically proven 72-hour deep hydration',
      'Reduces dark spots and refines pores in 7 days',
      'Dermatologist-tested, halal & paraben-free formula',
    ],
    imageUrl: '',
  },
  {
    keywords: ['oud', 'perfume', 'fragrance', 'attar', 'scent', 'parfum', 'qamar'],
    category: 'Fragrance',
    brandByLang: {
      ur: 'Maison Al-Qamar PK',
      ar: 'دار القمر للعطور',
      hi: 'Al-Qamar Royale',
      en: 'Maison Al-Qamar',
    },
    titleByLang: {
      ur: 'رائل کشمیری عود و عنبر پرفیوم 100ml',
      ar: 'عطر العود الملكي والعنبر الفاخر',
      hi: 'रॉयल कश्मीरी ऊद और अंबर परफ्यूम',
      en: 'Royal Kashmiri Oud & Ambergris Extrait',
    },
    pricesByLang: {
      ur: {
        currency: 'PKR',
        price: 'PKR 6,800',
        originalPrice: 'PKR 9,500',
        badge: '-28% OFF',
      },
      ar: {
        currency: 'SAR',
        price: 'SAR 249',
        originalPrice: 'SAR 360',
        badge: '-30% OFF',
      },
      hi: {
        currency: 'INR',
        price: 'INR 2,499',
        originalPrice: 'INR 3,499',
        badge: '-29% OFF',
      },
      en: {
        currency: 'USD',
        price: 'USD 68.00',
        originalPrice: 'USD 96.00',
        badge: '-29% OFF',
      },
    },
    features: [
      '24-hour long-lasting concentrated extrait de parfum',
      'Handcrafted aged artisanal oud with saffron top notes',
      'Luxury magnetic box with free cash-on-delivery',
    ],
    imageUrl: '',
  },
  {
    keywords: ['earbuds', 'watch', 'audio', 'anc', 'tech', 'sonic', 'buds', 'smart'],
    category: 'Consumer Electronics',
    brandByLang: {
      ur: 'AeroPulse Audio PK',
      ar: 'آيرو بالس التقنية',
      hi: 'AeroPulse India',
      en: 'AeroPulse Audio',
    },
    titleByLang: {
      ur: 'ایرو پلس پرو وائرلیس ایئربڈز ANC',
      ar: 'سماعات آيرو بالس برو العازلة للضوضاء',
      hi: 'एरोपल्स प्रो एक्टिव नॉइज़ कैंसलिंग ईयरबड्स',
      en: 'AeroPulse Pro 42dB ANC Wireless Earbuds',
    },
    pricesByLang: {
      ur: {
        currency: 'PKR',
        price: 'PKR 7,999',
        originalPrice: 'PKR 11,500',
        badge: '-30% OFF',
      },
      ar: {
        currency: 'SAR',
        price: 'SAR 219',
        originalPrice: 'SAR 319',
        badge: '-31% OFF',
      },
      hi: {
        currency: 'INR',
        price: 'INR 2,799',
        originalPrice: 'INR 3,999',
        badge: '-30% OFF',
      },
      en: {
        currency: 'USD',
        price: 'USD 59.00',
        originalPrice: 'USD 89.00',
        badge: '-34% OFF',
      },
    },
    features: [
      '42dB Hybrid Active Noise Cancellation',
      '36-hour total battery life with 10-min warp charge',
      'IPX5 sweat-resistant with low-latency gaming mode',
    ],
    imageUrl: '',
  },
  {
    keywords: ['coffee', 'matcha', 'tea', 'protein', 'honey', 'sidr', 'organic'],
    category: 'Wellness & Nutrition',
    brandByLang: {
      ur: 'Zaytoon Organics',
      ar: 'مناحل زيتون الملكية',
      hi: 'Zaytoon Naturals',
      en: 'Zaytoon Organics',
    },
    titleByLang: {
      ur: 'خالص پہاڑی سدر شہد 500g',
      ar: 'عسل السدر الجبلي الملكي الفاخر 500g',
      hi: 'शुद्ध पहाड़ी सिदर शहद 500g',
      en: 'Wild Mountain Royal Sidr Honey 500g',
    },
    pricesByLang: {
      ur: {
        currency: 'PKR',
        price: 'PKR 5,200',
        originalPrice: 'PKR 7,000',
        badge: '-26% OFF',
      },
      ar: {
        currency: 'SAR',
        price: 'SAR 185',
        originalPrice: 'SAR 250',
        badge: '-26% OFF',
      },
      hi: {
        currency: 'INR',
        price: 'INR 1,899',
        originalPrice: 'INR 2,599',
        badge: '-27% OFF',
      },
      en: {
        currency: 'USD',
        price: 'USD 48.00',
        originalPrice: 'USD 65.00',
        badge: '-26% OFF',
      },
    },
    features: [
      '100% pure cold-extracted single-origin Sidr honey',
      'Lab-certified antioxidant and immunity booster',
      'Sealed glass jar with authenticity QR code',
    ],
    imageUrl: '',
  },
] as const;

export function scrapeProductFallback(
  productUrl: string,
  targetLanguage: SupportedLanguage = 'ur',
  adAngle: AdAngle = 'problem_solution'
): ScrapedProductMetadata {
  const lowered = productUrl.toLowerCase();
  let matched = D2C_CATALOG_PRESETS.find((preset) =>
    preset.keywords.some((kw) => lowered.includes(kw))
  );

  if (!matched) {
    const hash = crypto.createHash('sha256').update(productUrl).digest('hex');
    const idx = parseInt(hash.slice(0, 6), 16) % D2C_CATALOG_PRESETS.length;
    matched = D2C_CATALOG_PRESETS[idx] ?? D2C_CATALOG_PRESETS[0];
  }

  const priceObj = matched.pricesByLang[targetLanguage] ?? matched.pricesByLang.ur;
  const title = matched.titleByLang[targetLanguage] ?? matched.titleByLang.ur;
  const brand = matched.brandByLang[targetLanguage] ?? matched.brandByLang.ur;

  const basePreset = getPresetAdProps(targetLanguage, adAngle, {
    productTitle: title,
    brandName: brand,
    currency: priceObj.currency,
    priceDisplay: priceObj.price,
    originalPriceDisplay: priceObj.originalPrice,
    discountBadge: priceObj.badge,
  });

  return {
    product_url: productUrl,
    title,
    brand,
    category: matched.category,
    currency: priceObj.currency,
    price: priceObj.price,
    original_price: priceObj.originalPrice,
    discount_badge: priceObj.badge,
    features: [...matched.features],
    image_url: matched.imageUrl,
    target_language: targetLanguage,
    suggested_props: basePreset,
  };
}

export function buildScriptJsonFromProps(
  productUrl: string,
  language: SupportedLanguage,
  adAngle: AdAngle,
  customProps?: Partial<LocalizedAdProps>
): VideoJobScriptJson {
  const scraped = scrapeProductFallback(productUrl, language, adAngle);
  const preset = getPresetAdProps(language, adAngle, {
    productTitle: customProps?.productTitle || scraped.title,
    brandName: customProps?.brandName || scraped.brand,
    priceDisplay: customProps?.priceDisplay || scraped.price,
    originalPriceDisplay:
      customProps?.originalPriceDisplay || scraped.original_price,
    discountBadge: customProps?.discountBadge || scraped.discount_badge,
    currency: customProps?.currency || scraped.currency,
    hookText: customProps?.hookText,
    ctaText: customProps?.ctaText,
    captions: customProps?.captions,
  });
  const fontMeta = getLanguageFontMeta(language);

  return {
    target_language: language,
    language_name: fontMeta.label,
    direction: fontMeta.dir,
    is_rtl: fontMeta.isRtl,
    font_family: fontMeta.fontFamily,
    ad_angle: adAngle,
    product_title: preset.productTitle,
    brand: preset.brandName,
    price_badge: preset.priceDisplay,
    original_price: preset.originalPriceDisplay,
    discount_badge: preset.discountBadge,
    currency: preset.currency,
    hook: preset.hookText,
    cta_text: preset.ctaText,
    captions: preset.captions,
    veo_prompt: `Vertical 9:16 cinematic commercial b-roll of ${preset.productTitle} by ${preset.brandName}, studio rim lighting, macro hero shot, 30fps motion.`,
    aspect_ratio: '9:16',
    fps: 30,
    duration_ms: 2000,
    status_history: ['PENDING', 'GENERATING_CLIPS', 'COMPOSITING', 'COMPLETED'],
    veo_mocked: true,
    final_mp4_size_bytes: 28460,
  };
}

interface StudioMemoryStore {
  workspaces: Map<string, WorkspaceInfo>;
  jobs: VideoJobRecord[];
}

const globalForStudio = globalThis as unknown as {
  __videoAdStudioStore?: StudioMemoryStore;
};

function createInitialStore(): StudioMemoryStore {
  const now = new Date();
  const earlier1 = new Date(now.getTime() - 1000 * 60 * 14).toISOString();
  const earlier2 = new Date(now.getTime() - 1000 * 60 * 5).toISOString();

  const job1Id = '4c3f88fe-50a2-44d8-9810-1a82e9010101';
  const job2Id = '7845334b-ec88-44b1-8911-2b93f8020202';

  const script1 = buildScriptJsonFromProps(
    'https://zaynaskin.pk/products/vitamin-c-glow-serum',
    'ur',
    'problem_solution'
  );
  const script2 = buildScriptJsonFromProps(
    'https://nooratelier.sa/products/royal-oud-vitamin-serum',
    'ar',
    'flash_sale'
  );

  const initialJobs: VideoJobRecord[] = [
    {
      id: job2Id,
      job_id: job2Id,
      workspace_id: DEFAULT_WORKSPACE_ID,
      product_url: 'https://nooratelier.sa/products/royal-oud-vitamin-serum',
      target_language: 'ar',
      script_json: script2,
      veo_gcs_uri: `gs://videosaving/renders/${job2Id}/veo_raw.mp4`,
      final_mp4_url: `/api/v1/renders/${job2Id}`,
      status: 'COMPLETED',
      credit_balance: 10,
      created_at: earlier2,
    },
    {
      id: job1Id,
      job_id: job1Id,
      workspace_id: DEFAULT_WORKSPACE_ID,
      product_url: 'https://zaynaskin.pk/products/vitamin-c-glow-serum',
      target_language: 'ur',
      script_json: script1,
      veo_gcs_uri: `gs://videosaving/renders/${job1Id}/veo_raw.mp4`,
      final_mp4_url: `/api/v1/renders/${job1Id}`,
      status: 'COMPLETED',
      credit_balance: 10,
      created_at: earlier1,
    },
  ];

  const defaultWorkspace: WorkspaceInfo = {
    id: DEFAULT_WORKSPACE_ID,
    owner_id: DEFAULT_OWNER_ID,
    credit_balance: 10,
    created_at: new Date(now.getTime() - 1000 * 60 * 60).toISOString(),
    ledger: [
      {
        id: 'led-init-3',
        workspace_id: DEFAULT_WORKSPACE_ID,
        job_id: null,
        delta: 2,
        reason: 'checkout:starter_bonus',
        balance_after: 10,
        created_at: new Date(now.getTime() - 1000 * 60 * 2).toISOString(),
      },
      {
        id: 'led-init-2',
        workspace_id: DEFAULT_WORKSPACE_ID,
        job_id: job2Id,
        delta: -1,
        reason: 'video_render_deduction',
        balance_after: 8,
        created_at: earlier2,
      },
      {
        id: 'led-init-1',
        workspace_id: DEFAULT_WORKSPACE_ID,
        job_id: job1Id,
        delta: -1,
        reason: 'video_render_deduction',
        balance_after: 9,
        created_at: earlier1,
      },
      {
        id: 'led-init-0',
        workspace_id: DEFAULT_WORKSPACE_ID,
        job_id: null,
        delta: 10,
        reason: 'initial_seed',
        balance_after: 10,
        created_at: new Date(now.getTime() - 1000 * 60 * 60).toISOString(),
      },
    ],
  };

  const workspaces = new Map<string, WorkspaceInfo>();
  workspaces.set(DEFAULT_WORKSPACE_ID, defaultWorkspace);

  return {
    workspaces,
    jobs: initialJobs,
  };
}

export function getStudioStore(): StudioMemoryStore {
  if (!globalForStudio.__videoAdStudioStore) {
    globalForStudio.__videoAdStudioStore = createInitialStore();
  }
  return globalForStudio.__videoAdStudioStore;
}

export function ensureWorkspaceFallback(workspaceId: string): WorkspaceInfo {
  const store = getStudioStore();
  const normalized = workspaceId.trim() || DEFAULT_WORKSPACE_ID;
  const existing = store.workspaces.get(normalized);
  if (existing) {
    return existing;
  }
  const created: WorkspaceInfo = {
    id: normalized,
    owner_id: DEFAULT_OWNER_ID,
    credit_balance: 10,
    created_at: new Date().toISOString(),
    ledger: [
      {
        id: crypto.randomUUID(),
        workspace_id: normalized,
        job_id: null,
        delta: 10,
        reason: 'workspace_provisioned',
        balance_after: 10,
        created_at: new Date().toISOString(),
      },
    ],
  };
  store.workspaces.set(normalized, created);
  return created;
}

export function deductCreditFallback(
  workspaceId: string,
  jobId: string
): { deducted: boolean; workspace: WorkspaceInfo } {
  const ws = ensureWorkspaceFallback(workspaceId);
  if (ws.credit_balance < 1) {
    return { deducted: false, workspace: ws };
  }
  ws.credit_balance -= 1;
  const entry: CreditLedgerEntry = {
    id: crypto.randomUUID(),
    workspace_id: ws.id,
    job_id: jobId,
    delta: -1,
    reason: 'video_render_deduction',
    balance_after: ws.credit_balance,
    created_at: new Date().toISOString(),
  };
  ws.ledger.unshift(entry);
  return { deducted: true, workspace: ws };
}

export function refundCreditFallback(
  workspaceId: string,
  jobId: string,
  reason = 'video_render_failed_refund'
): WorkspaceInfo {
  const ws = ensureWorkspaceFallback(workspaceId);
  ws.credit_balance += 1;
  ws.ledger.unshift({
    id: crypto.randomUUID(),
    workspace_id: ws.id,
    job_id: jobId,
    delta: 1,
    reason,
    balance_after: ws.credit_balance,
    created_at: new Date().toISOString(),
  });
  return ws;
}

export function topUpCreditsFallback(
  workspaceId: string,
  credits: number,
  packId: string
): WorkspaceInfo {
  const ws = ensureWorkspaceFallback(workspaceId);
  const safeCredits = Math.max(1, Math.min(10000, Math.floor(credits)));
  ws.credit_balance += safeCredits;
  ws.ledger.unshift({
    id: crypto.randomUUID(),
    workspace_id: ws.id,
    job_id: null,
    delta: safeCredits,
    reason: `checkout:${packId}`,
    balance_after: ws.credit_balance,
    created_at: new Date().toISOString(),
  });
  return ws;
}

export interface CreateFallbackJobParams {
  workspaceId: string;
  productUrl: string;
  targetLanguage: SupportedLanguage;
  adAngle: AdAngle;
  simulateFailure?: boolean;
  customProps?: {
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

export function createVideoJobFallback(
  params: CreateFallbackJobParams
):
  | { ok: true; job: VideoJobRecord; workspace: WorkspaceInfo }
  | { ok: false; status: 402; detail: string; workspace: WorkspaceInfo } {
  const store = getStudioStore();
  const jobId = crypto.randomUUID();

  const { deducted, workspace } = deductCreditFallback(
    params.workspaceId,
    jobId
  );
  if (!deducted) {
    return {
      ok: false,
      status: 402,
      detail:
        'Insufficient credits in workspace. Please top up credits to generate a video.',
      workspace,
    };
  }

  const shouldFail =
    Boolean(params.simulateFailure) ||
    params.productUrl.toLowerCase().includes('simulate-fail');

  const scriptJson = buildScriptJsonFromProps(
    params.productUrl,
    params.targetLanguage,
    params.adAngle,
    params.customProps
  );

  if (shouldFail) {
    scriptJson.status_history = ['PENDING', 'GENERATING_CLIPS', 'FAILED'];
    scriptJson.error = 'Simulated Vertex AI Veo / pipeline failure';
    const refundedWs = refundCreditFallback(params.workspaceId, jobId);
    const failedJob: VideoJobRecord = {
      id: jobId,
      job_id: jobId,
      workspace_id: refundedWs.id,
      product_url: params.productUrl,
      target_language: params.targetLanguage,
      script_json: scriptJson,
      veo_gcs_uri: null,
      final_mp4_url: null,
      status: 'FAILED',
      credit_balance: refundedWs.credit_balance,
      created_at: new Date().toISOString(),
    };
    store.jobs.unshift(failedJob);
    return { ok: true, job: failedJob, workspace: refundedWs };
  }

  const completedJob: VideoJobRecord = {
    id: jobId,
    job_id: jobId,
    workspace_id: workspace.id,
    product_url: params.productUrl,
    target_language: params.targetLanguage,
    script_json: scriptJson,
    veo_gcs_uri: `gs://videosaving/renders/${jobId}/veo_raw.mp4`,
    final_mp4_url: `/api/v1/renders/${jobId}`,
    status: 'COMPLETED',
    credit_balance: workspace.credit_balance,
    created_at: new Date().toISOString(),
  };

  store.jobs.unshift(completedJob);
  return { ok: true, job: completedJob, workspace };
}

export function getRenderMp4Buffer(jobId: string): Buffer {
  const candidatePaths = [
    path.resolve(
      process.cwd(),
      '..',
      '..',
      'services',
      'worker',
      'static',
      'renders',
      `${jobId}.mp4`
    ),
    path.resolve(
      process.cwd(),
      '..',
      '..',
      'services',
      'worker',
      'fixtures',
      'sample_9_16.mp4'
    ),
  ];

  for (const filePath of candidatePaths) {
    try {
      if (fs.existsSync(filePath)) {
        const stat = fs.statSync(filePath);
        if (stat.size > 0) {
          return fs.readFileSync(filePath);
        }
      }
    } catch {
      // Fallback to synthesized MP4 container below
    }
  }

  const fixturePath = candidatePaths[1];
  try {
    fs.mkdirSync(path.dirname(fixturePath), { recursive: true });
    execFileSync(
      'ffmpeg',
      [
        '-y',
        '-f',
        'lavfi',
        '-i',
        'color=c=0x09090B:size=540x960:rate=30',
        '-f',
        'lavfi',
        '-i',
        'sine=frequency=220:sample_rate=24000',
        '-t',
        '2',
        '-vf',
        'drawbox=x=24:y=160:w=492:h=620:color=0x18181B@0.92:t=fill',
        '-c:v',
        'libx264',
        '-preset',
        'ultrafast',
        '-pix_fmt',
        'yuv420p',
        '-c:a',
        'aac',
        '-b:a',
        '96k',
        '-movflags',
        '+faststart',
        fixturePath,
      ],
      { stdio: 'ignore', timeout: 8000 }
    );
    if (fs.existsSync(fixturePath) && fs.statSync(fixturePath).size > 1024) {
      return fs.readFileSync(fixturePath);
    }
  } catch {
    // Fall back to deterministic MP4 atom header if ffmpeg binary is unavailable
  }

  // Synthesize a valid ISO Base Media (MP4) binary header + metadata payload
  const ftyp = Buffer.from([
    0x00, 0x00, 0x00, 0x18, 0x66, 0x74, 0x79, 0x70, 0x69, 0x73, 0x6f, 0x6d,
    0x00, 0x00, 0x02, 0x00, 0x69, 0x73, 0x6f, 0x6d, 0x69, 0x73, 0x6f, 0x32,
  ]);
  const metaText = Buffer.from(
    `VEO-3.1-REMOTION-9:16-RENDER:${jobId}`,
    'utf-8'
  );
  const mdatSize = 8 + metaText.length;
  const mdatHeader = Buffer.alloc(8);
  mdatHeader.writeUInt32BE(mdatSize, 0);
  mdatHeader.write('mdat', 4, 'ascii');

  return Buffer.concat([ftyp, mdatHeader, metaText]);
}
