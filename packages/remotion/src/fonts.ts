import type { AdAngle, SupportedLanguage } from './types';

export interface LanguageFontMetadata {
  language: SupportedLanguage;
  code: SupportedLanguage;
  label: string;
  nativeLabel: string;
  regionLabel: string;
  isRtl: boolean;
  dir: 'rtl' | 'ltr';
  fontFamily: string;
  fontStack: string;
  lineHeight: number;
  hookLineHeight: number;
  captionLineHeight: number;
  letterSpacing: string;
  wordSpacing: string;
  verifiedD2cLabel: string;
  priceLabel: string;
  originalPriceLabel: string;
  codBadgeLabel: string;
  angleLabels: Record<AdAngle, string>;
}

export type LanguageMeta = LanguageFontMetadata;

export const GOOGLE_FONTS_STYLESHEET_URL =
  'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&family=Noto+Nastaliq+Urdu:wght@400;600;700&family=Noto+Sans+Arabic:wght@400;600;700;800&family=Noto+Sans+Devanagari:wght@400;600;700;800&display=swap';

export const LANGUAGE_FONT_METADATA: Record<
  SupportedLanguage,
  LanguageFontMetadata
> = {
  ur: {
    language: 'ur',
    code: 'ur',
    label: 'Urdu (اردو)',
    nativeLabel: 'اردو',
    regionLabel: 'PK · D2C',
    isRtl: true,
    dir: 'rtl',
    fontFamily: 'Noto Nastaliq Urdu',
    fontStack: "'Noto Nastaliq Urdu', 'Noto Sans Arabic', 'Inter', serif",
    lineHeight: 1.85,
    hookLineHeight: 1.85,
    captionLineHeight: 1.85,
    letterSpacing: '0px',
    wordSpacing: '2px',
    verifiedD2cLabel: 'تصدیق شدہ برانڈ',
    priceLabel: 'خصوصی قیمت',
    originalPriceLabel: 'اصل قیمت',
    codBadgeLabel: 'کیش آن ڈیلیوری دستیاب',
    angleLabels: {
      problem_solution: 'مسئلہ اور فوری حل',
      ugc_testimonial: 'صارف کا تجربہ',
      flash_sale: 'محدود وقت کی سیل',
      unboxing: 'ان باکسنگ ریویو',
    },
  },
  ar: {
    language: 'ar',
    code: 'ar',
    label: 'Arabic (العربية)',
    nativeLabel: 'العربية',
    regionLabel: 'KSA / UAE · D2C',
    isRtl: true,
    dir: 'rtl',
    fontFamily: 'Noto Sans Arabic',
    fontStack: "'Noto Sans Arabic', 'Inter', sans-serif",
    lineHeight: 1.5,
    hookLineHeight: 1.45,
    captionLineHeight: 1.5,
    letterSpacing: '0px',
    wordSpacing: '1px',
    verifiedD2cLabel: 'علامة تجارية موثقة',
    priceLabel: 'سعر العرض الحصري',
    originalPriceLabel: 'السعر السابق',
    codBadgeLabel: 'الدفع عند الاستلام متاح',
    angleLabels: {
      problem_solution: 'المشكلة والحل الفوري',
      ugc_testimonial: 'تجربة عميل حقيقية',
      flash_sale: 'تخفيض خاطف محدود',
      unboxing: 'فتح الصندوق واستعراض',
    },
  },
  hi: {
    language: 'hi',
    code: 'hi',
    label: 'Hindi (हिन्दी)',
    nativeLabel: 'हिन्दी',
    regionLabel: 'IN · D2C',
    isRtl: false,
    dir: 'ltr',
    fontFamily: 'Noto Sans Devanagari',
    fontStack: "'Noto Sans Devanagari', 'Inter', sans-serif",
    lineHeight: 1.55,
    hookLineHeight: 1.45,
    captionLineHeight: 1.55,
    letterSpacing: '0px',
    wordSpacing: '1px',
    verifiedD2cLabel: 'सत्यापित D2C ब्रांड',
    priceLabel: 'विशेष ऑफ़र मूल्य',
    originalPriceLabel: 'एमआरपी',
    codBadgeLabel: 'कैश ऑन डिलीवरी उपलब्ध',
    angleLabels: {
      problem_solution: 'समस्या और सटीक समाधान',
      ugc_testimonial: 'ग्राहक समीक्षा',
      flash_sale: 'सीमित समय फ्लैश सेल',
      unboxing: 'अनबॉक्सिंग और फर्स्ट लुक',
    },
  },
  en: {
    language: 'en',
    code: 'en',
    label: 'English',
    nativeLabel: 'English',
    regionLabel: 'GLOBAL · D2C',
    isRtl: false,
    dir: 'ltr',
    fontFamily: 'Inter',
    fontStack: "'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
    lineHeight: 1.35,
    hookLineHeight: 1.25,
    captionLineHeight: 1.35,
    letterSpacing: '-0.02em',
    wordSpacing: '0px',
    verifiedD2cLabel: 'VERIFIED D2C STORE',
    priceLabel: 'DIRECT LAUNCH PRICE',
    originalPriceLabel: 'RETAIL',
    codBadgeLabel: 'EXPRESS DISPATCH · 24H',
    angleLabels: {
      problem_solution: 'PROBLEM / SOLUTION',
      ugc_testimonial: 'CREATOR REVIEW',
      flash_sale: 'FLASH DROP · 24H',
      unboxing: 'FIRST LOOK UNBOXING',
    },
  },
};

export const LANGUAGE_METADATA = LANGUAGE_FONT_METADATA;

export function getLanguageFontMeta(
  language: SupportedLanguage
): LanguageFontMetadata {
  return LANGUAGE_FONT_METADATA[language] ?? LANGUAGE_FONT_METADATA.ur;
}

export const getLanguageMeta = getLanguageFontMeta;
export const getFontConfig = getLanguageFontMeta;

export function isRtlLanguage(language: SupportedLanguage): boolean {
  return getLanguageFontMeta(language).isRtl;
}
