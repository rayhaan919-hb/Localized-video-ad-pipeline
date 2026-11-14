export {
  AD_ANGLES,
  DESIGN_TOKENS,
  SUPPORTED_LANGUAGES,
  VERTICAL_AD_CONFIG,
  type AdAngle,
  type CaptionSegment,
  type LocalizedAdProps,
  type SupportedLanguage,
} from './types';

export {
  GOOGLE_FONTS_STYLESHEET_URL,
  LANGUAGE_FONT_METADATA,
  LANGUAGE_METADATA,
  getFontConfig,
  getLanguageFontMeta,
  getLanguageMeta,
  isRtlLanguage,
  type LanguageFontMetadata,
  type LanguageMeta,
} from './fonts';

export {
  SAMPLE_ADS_BY_LANGUAGE,
  SAMPLE_ADS_BY_LANGUAGE_AND_ANGLE,
  getPresetAdProps,
  getSampleAd,
  type LocalizedAdPresetBundle,
} from './presets';

export { VerticalAdTemplate } from './VerticalAdTemplate';
export { RemotionRoot, VerticalAdRoot } from './Root';
