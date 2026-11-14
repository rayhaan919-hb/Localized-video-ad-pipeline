import type {
  AdAngle,
  LocalizedAdProps,
  SupportedLanguage,
} from '@video-ad/remotion';

export const GOOGLE_FONTS_STYLESHEET_URL =
  'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&family=Noto+Nastaliq+Urdu:wght@400;600;700&family=Noto+Sans+Arabic:wght@400;600;700;800&family=Noto+Sans+Devanagari:wght@400;600;700;800&display=swap';

export const SUPPORTED_LANGUAGES: readonly SupportedLanguage[] = [
  'ur',
  'ar',
  'hi',
  'en',
] as const;

export const AD_ANGLES: readonly AdAngle[] = [
  'problem_solution',
  'ugc_testimonial',
  'flash_sale',
  'unboxing',
] as const;

export interface ServerLanguageMeta {
  language: SupportedLanguage;
  label: string;
  dir: 'rtl' | 'ltr';
  isRtl: boolean;
  fontFamily: string;
}

const SERVER_LANGUAGE_META: Record<SupportedLanguage, ServerLanguageMeta> = {
  ur: {
    language: 'ur',
    label: 'Urdu (اردو)',
    dir: 'rtl',
    isRtl: true,
    fontFamily: 'Noto Nastaliq Urdu',
  },
  ar: {
    language: 'ar',
    label: 'Arabic (العربية)',
    dir: 'rtl',
    isRtl: true,
    fontFamily: 'Noto Sans Arabic',
  },
  hi: {
    language: 'hi',
    label: 'Hindi (हिन्दी)',
    dir: 'ltr',
    isRtl: false,
    fontFamily: 'Noto Sans Devanagari',
  },
  en: {
    language: 'en',
    label: 'English',
    dir: 'ltr',
    isRtl: false,
    fontFamily: 'Inter',
  },
};

export function getServerLanguageFontMeta(
  language: SupportedLanguage
): ServerLanguageMeta {
  return SERVER_LANGUAGE_META[language] ?? SERVER_LANGUAGE_META.ur;
}

const SERVER_BASE_PRESETS: Record<SupportedLanguage, LocalizedAdProps> = {
  ur: {
    jobId: 'job_ur_ps_901',
    language: 'ur',
    adAngle: 'problem_solution',
    brandName: 'Zayna Skin Lab',
    productTitle: 'وٹامن سی گلو سیرم 30ml',
    currency: 'PKR',
    priceDisplay: 'PKR 4,990',
    originalPriceDisplay: 'PKR 7,200',
    discountBadge: '-31% OFF',
    hookText: 'بے رونق جلد اور سیاہ دھبوں سے پریشان ہیں؟',
    ctaText: 'ابھی آرڈر کریں — کیش آن ڈیلیوری',
    captions: [
      {
        id: 'ur-ps-1',
        text: 'گرمی اور دھوپ سے چہرے کی چمک ختم ہو جاتی ہے',
        startFrame: 0,
        endFrame: 20,
        highlightWord: 'چمک',
      },
      {
        id: 'ur-ps-2',
        text: 'خالص وٹامن سی سیرم صرف سات دن میں نکھار لائے',
        startFrame: 20,
        endFrame: 40,
        highlightWord: 'سات دن',
      },
      {
        id: 'ur-ps-3',
        text: 'پورے پاکستان میں مفت ڈیلیوری اور خصوصی رعایت',
        startFrame: 40,
        endFrame: 60,
        highlightWord: 'مفت ڈیلیوری',
      },
    ],
  },
  ar: {
    jobId: 'job_ar_ps_801',
    language: 'ar',
    adAngle: 'problem_solution',
    brandName: 'Noor Atelier Riyadh',
    productTitle: 'سيروم النضارة بفيتامين سي النقي',
    currency: 'SAR',
    priceDisplay: 'SAR 189',
    originalPriceDisplay: 'SAR 275',
    discountBadge: '-31% OFF',
    hookText: 'هل تعانين من بهتان البشرة والتصبغات اليومية؟',
    ctaText: 'اطلبي الآن — الدفع عند الاستلام',
    captions: [
      {
        id: 'ar-ps-1',
        text: 'حرارة الشمس والغبار يفقدان بشرتك إشراقتها الطبيعية',
        startFrame: 0,
        endFrame: 20,
        highlightWord: 'إشراقتها',
      },
      {
        id: 'ar-ps-2',
        text: 'تركيبة فيتامين سي المركز تمنحك ترطيباً وتفتيحاً فورياً',
        startFrame: 20,
        endFrame: 40,
        highlightWord: 'تفتيحاً',
      },
      {
        id: 'ar-ps-3',
        text: 'شحن سريع لجميع مناطق المملكة والخليج العربي',
        startFrame: 40,
        endFrame: 60,
        highlightWord: 'شحن سريع',
      },
    ],
  },
  hi: {
    jobId: 'job_hi_ps_701',
    language: 'hi',
    adAngle: 'problem_solution',
    brandName: 'Aarav Botanicals',
    productTitle: 'विटामिन सी रेडिएंस सीरम 30ml',
    currency: 'INR',
    priceDisplay: 'INR 1,499',
    originalPriceDisplay: 'INR 2,199',
    discountBadge: '-32% OFF',
    hookText: 'क्या धूप और प्रदूषण से आपकी त्वचा बेजान हो गई है?',
    ctaText: 'अभी ऑर्डर करें — कैश ऑन डिलीवरी',
    captions: [
      {
        id: 'hi-ps-1',
        text: 'डार्क स्पॉट्स और डल स्किन को कहें हमेशा के लिए अलविदा',
        startFrame: 0,
        endFrame: 20,
        highlightWord: 'अलविदा',
      },
      {
        id: 'hi-ps-2',
        text: '20% शुद्ध विटामिन सी दे सिर्फ 7 दिनों में नेचुरल ग्लो',
        startFrame: 20,
        endFrame: 40,
        highlightWord: '7 दिनों',
      },
      {
        id: 'hi-ps-3',
        text: 'पूरे भारत में तेज़ मुफ़्त डिलीवरी और सुरक्षित पैकेजिंग',
        startFrame: 40,
        endFrame: 60,
        highlightWord: 'मुफ़्त डिलीवरी',
      },
    ],
  },
  en: {
    jobId: 'job_en_ps_601',
    language: 'en',
    adAngle: 'problem_solution',
    brandName: 'Kinetix D2C Studio',
    productTitle: 'Bio-Active C20 Glass Skin Serum',
    currency: 'USD',
    priceDisplay: 'USD 49.00',
    originalPriceDisplay: 'USD 72.00',
    discountBadge: '-32% OFF',
    hookText: 'Tired of dull skin and stubborn dark spots that never fade?',
    ctaText: 'Claim 32% Off + Free Express Shipping',
    captions: [
      {
        id: 'en-ps-1',
        text: 'Most serums oxidize before they ever touch your skin',
        startFrame: 0,
        endFrame: 20,
        highlightWord: 'oxidize',
      },
      {
        id: 'en-ps-2',
        text: 'Stabilized 20% L-Ascorbic complex restores clarity in 7 days',
        startFrame: 20,
        endFrame: 40,
        highlightWord: '7 days',
      },
      {
        id: 'en-ps-3',
        text: 'Zero fragrance, clinically tested, ships direct in 24h',
        startFrame: 40,
        endFrame: 60,
        highlightWord: '24h',
      },
    ],
  },
};

export function getServerPresetAdProps(
  language: SupportedLanguage = 'ur',
  adAngle: AdAngle = 'problem_solution',
  overrides?: Partial<LocalizedAdProps>
): LocalizedAdProps {
  const base = SERVER_BASE_PRESETS[language] ?? SERVER_BASE_PRESETS.ur;
  if (!overrides) {
    return { ...base, adAngle };
  }
  return {
    ...base,
    adAngle,
    ...overrides,
    productTitle: overrides.productTitle || base.productTitle,
    brandName: overrides.brandName || base.brandName,
    priceDisplay: overrides.priceDisplay || base.priceDisplay,
    currency: overrides.currency || base.currency,
    hookText: overrides.hookText || base.hookText,
    ctaText: overrides.ctaText || base.ctaText,
    captions:
      overrides.captions && overrides.captions.length > 0
        ? overrides.captions
        : base.captions,
  };
}
