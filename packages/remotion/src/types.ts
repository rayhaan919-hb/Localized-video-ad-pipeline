export type SupportedLanguage = 'ur' | 'ar' | 'hi' | 'en';

export type AdAngle =
  | 'problem_solution'
  | 'ugc_testimonial'
  | 'flash_sale'
  | 'unboxing';

export interface CaptionSegment {
  id: string;
  text: string;
  startFrame: number;
  endFrame: number;
  highlightWord?: string;
}

export interface LocalizedAdProps {
  productTitle: string;
  brandName: string;
  priceDisplay: string;
  originalPriceDisplay?: string;
  discountBadge?: string;
  currency: string;
  language: SupportedLanguage;
  adAngle: AdAngle;
  hookText: string;
  ctaText: string;
  captions: CaptionSegment[];
  videoSrc?: string;
  productImageUrl?: string;
  jobId?: string;
}

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

export const VERTICAL_AD_CONFIG = {
  width: 1080,
  height: 1920,
  fps: 30,
  durationInFrames: 60,
} as const;

export const DESIGN_TOKENS = {
  bgCanvas: '#09090B',
  bgSurface: '#18181B',
  borderDark: '#27272A',
  borderLight: '#E2E8F0',
  accentPrimary: '#6366F1',
  textPrimary: '#FAFAFA',
  textMuted: '#A1A1AA',
  fontUi: "'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
  fontMono: "'JetBrains Mono', ui-monospace, SFMono-Regular, monospace",
} as const;
