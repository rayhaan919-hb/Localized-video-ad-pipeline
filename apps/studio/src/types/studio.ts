import type {
  AdAngle,
  CaptionSegment,
  LocalizedAdProps,
  SupportedLanguage,
} from '@video-ad/remotion';

export type JobStatus =
  | 'CREATED'
  | 'QUEUED'
  | 'PROCESSING'
  | 'RENDERING'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED'
  // Legacy v1 status aliases (normalized in UI helpers)
  | 'PENDING'
  | 'GENERATING_CLIPS'
  | 'COMPOSITING';

export type WorkspaceRole = 'owner' | 'admin' | 'member';

export interface WorkspaceSummary {
  id: string;
  name: string;
  owner_id: string;
  role: WorkspaceRole;
  credit_balance: number;
  reserved_balance?: number;
  created_at: string;
}

export interface AuthUserSummary {
  id: string;
  email: string;
  full_name?: string | null;
  auth_provider?: string;
  is_email_verified: boolean;
  is_admin: boolean;
  workspaces: WorkspaceSummary[];
}

export interface CreditLedgerEntry {
  id: string;
  workspace_id?: string;
  user_id?: string | null;
  job_id: string | null;
  payment_id?: string | null;
  transaction_type?: string;
  amount?: number;
  delta: number;
  previous_balance?: number;
  new_balance?: number;
  balance_after: number;
  reason: string;
  status?: string;
  metadata?: Record<string, unknown> | null;
  created_at: string;
}

export interface WorkspaceMemberInfo {
  user_id: string;
  email: string;
  full_name?: string | null;
  role: WorkspaceRole;
  created_at: string;
}

export interface WorkspaceInfo {
  id: string;
  name: string;
  owner_id: string;
  role?: WorkspaceRole;
  credit_balance: number;
  reserved_balance?: number;
  created_at: string;
  ledger?: CreditLedgerEntry[];
  members?: WorkspaceMemberInfo[];
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
  description?: string;
  features: string[];
  image_url: string;
  image_candidates?: string[];
  target_language: SupportedLanguage;
  scrape_status?: string;
  verified_fields?: string[];
  missing_fields?: string[];
  requires_user_confirmation?: boolean;
  error?: string | null;
  suggested_props?: LocalizedAdProps;
}

export interface WorkspaceAssetItem {
  id: string;
  workspace_id?: string;
  asset_kind: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  created_at: string;
}

export interface VideoJobScriptJson {
  target_language: SupportedLanguage;
  language_name: string;
  direction: 'rtl' | 'ltr';
  is_rtl: boolean;
  font_family: string;
  ad_angle: AdAngle;
  product_title: string;
  brand: string;
  price_badge: string;
  original_price?: string;
  discount_badge?: string;
  currency: string;
  hook: string;
  cta_text: string;
  captions: Array<
    CaptionSegment & {
      start_ms?: number;
      end_ms?: number;
    }
  >;
  veo_prompt: string;
  aspect_ratio: '9:16' | '16:9';
  fps: number;
  duration_ms: number;
  status_history: string[];
  product_image_url?: string;
  product_image_asset_id?: string;
  veo_model?: string;
  veo_mocked?: boolean;
  tts_mocked?: boolean;
  voiceover_synthesized?: boolean;
  final_mp4_size_bytes?: number;
  error?: string;
}

export interface VideoJobRecord {
  id: string;
  job_id?: string;
  workspace_id: string;
  user_id?: string | null;
  product_url: string;
  target_language: SupportedLanguage;
  aspect_ratio?: '9:16' | '16:9';
  duration_seconds?: number;
  script_json: VideoJobScriptJson | null;
  veo_gcs_uri: string | null;
  final_mp4_url: string | null;
  status: JobStatus;
  progress_pct?: number;
  stage_detail?: string | null;
  error_code?: string | null;
  error_message?: string | null;
  credit_balance?: number;
  created_at: string;
  completed_at?: string | null;
}

export interface CreditPackageTier {
  id: 'starter_10' | 'growth_50' | 'scale_200';
  name: string;
  credits: number;
  priceUsd: string;
  perCreditUsd: string;
  description: string;
  badge?: string;
}

export type ViewStateMode = 'normal' | 'loading' | 'empty' | 'error';
