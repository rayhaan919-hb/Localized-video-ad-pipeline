import type {
  AdAngle,
  CaptionSegment,
  LocalizedAdProps,
  SupportedLanguage,
} from '@video-ad/remotion';

export type JobStatus =
  | 'PENDING'
  | 'GENERATING_CLIPS'
  | 'COMPOSITING'
  | 'COMPLETED'
  | 'FAILED';

export type ViewStateMode = 'normal' | 'loading' | 'empty' | 'error';

export interface CreditLedgerEntry {
  id: string;
  workspace_id?: string;
  job_id: string | null;
  delta: number;
  reason: string;
  balance_after: number;
  created_at: string;
}

export interface WorkspaceInfo {
  id: string;
  owner_id: string;
  credit_balance: number;
  created_at: string;
  ledger: CreditLedgerEntry[];
}

export interface ScrapedProductMetadata {
  product_url: string;
  title: string;
  brand: string;
  category: string;
  currency: string;
  price: string;
  original_price?: string;
  discount_badge?: string;
  features: string[];
  image_url: string;
  target_language: SupportedLanguage;
  suggested_props?: LocalizedAdProps;
}

export interface VideoJobScriptJson {
  target_language: SupportedLanguage;
  language_name: string;
  direction: 'rtl' | 'ltr';
  is_rtl: boolean;
  font_family: string;
  voice_id?: string;
  ad_angle: AdAngle;
  product_title: string;
  brand: string;
  price_badge: string;
  original_price?: string;
  discount_badge?: string;
  currency: string;
  hook: string;
  cta_text: string;
  captions: CaptionSegment[];
  veo_prompt: string;
  aspect_ratio?: string;
  fps?: number;
  duration_ms?: number;
  status_history?: JobStatus[];
  voiceover_url?: string;
  veo_mocked?: boolean;
  final_mp4_size_bytes?: number;
  error?: string;
}

export interface VideoJobRecord {
  id: string;
  job_id: string;
  workspace_id: string;
  product_url: string;
  target_language: SupportedLanguage;
  script_json: VideoJobScriptJson | null;
  veo_gcs_uri: string | null;
  final_mp4_url: string | null;
  status: JobStatus;
  credit_balance?: number | null;
  created_at: string;
}

export interface CreditPackageTier {
  id: string;
  name: string;
  credits: number;
  priceUsd: string;
  perCreditUsd: string;
  description: string;
  badge?: string;
}
