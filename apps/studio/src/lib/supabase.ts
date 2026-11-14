import { createBrowserClient } from '@supabase/ssr';
import { createClient, type SupabaseClient } from '@supabase/supabase-js';
import type { CreditPackageTier } from '@/types/studio';

export const DEFAULT_WORKSPACE_ID = '00000000-0000-0000-0000-000000000001';
export const DEFAULT_OWNER_ID = '00000000-0000-0000-0000-000000000099';

export const CREDIT_PACKAGE_TIERS: readonly CreditPackageTier[] = [
  {
    id: 'starter_10',
    name: 'Starter Pack',
    credits: 10,
    priceUsd: '$9.00',
    perCreditUsd: '$0.90 / ad',
    description: '10 Veo 3.1 + Remotion 9:16 localized D2C renders',
  },
  {
    id: 'growth_50',
    name: 'Growth Studio',
    credits: 50,
    priceUsd: '$39.00',
    perCreditUsd: '$0.78 / ad',
    description: '50 localized renders with priority Nastaliq & RTL queue',
    badge: 'MOST POPULAR',
  },
  {
    id: 'scale_200',
    name: 'Scale Agency',
    credits: 200,
    priceUsd: '$129.00',
    perCreditUsd: '$0.65 / ad',
    description: '200 multi-market renders across PK, KSA, UAE & IN',
  },
] as const;

export interface SupabaseConnectionInfo {
  configured: boolean;
  modeLabel: string;
  projectUrl: string;
}

export function getSupabaseConnectionInfo(): SupabaseConnectionInfo {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL ?? '';
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? '';
  const configured = Boolean(url && anonKey && !url.includes('placeholder'));

  return {
    configured,
    modeLabel: configured ? 'SUPABASE RLS · LIVE' : 'LOCAL LEDGER · RLS READY',
    projectUrl: configured ? url : 'postgresql://localhost:5432/video_ads',
  };
}

export function createStudioBrowserSupabaseClient(): SupabaseClient | null {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !anonKey) {
    return null;
  }
  return createBrowserClient(url, anonKey);
}

export function createStudioServerSupabaseClient(): SupabaseClient | null {
  const url =
    process.env.SUPABASE_URL ?? process.env.NEXT_PUBLIC_SUPABASE_URL;
  const serviceKey =
    process.env.SUPABASE_SERVICE_ROLE_KEY ??
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !serviceKey) {
    return null;
  }
  return createClient(url, serviceKey, {
    auth: {
      persistSession: false,
      autoRefreshToken: false,
    },
  });
}
