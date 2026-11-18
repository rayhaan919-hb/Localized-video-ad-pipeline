'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ShieldAlert } from 'lucide-react';
import {
  getPresetAdProps,
  type AdAngle,
  type CaptionSegment,
  type LocalizedAdProps,
  type SupportedLanguage,
} from '@video-ad/remotion';
import { AuthModal, type AuthModalMode } from '@/components/AuthModal';
import { CreditCheckoutModal } from '@/components/CreditCheckoutModal';
import { ProductScraperPanel } from '@/components/ProductScraperPanel';
import { RemotionPreviewStage } from '@/components/RemotionPreviewStage';
import { RenderQueueGallery } from '@/components/RenderQueueGallery';
import { StudioHeader } from '@/components/StudioHeader';
import type {
  AuthUserSummary,
  CreditLedgerEntry,
  ScrapedProductMetadata,
  VideoJobRecord,
  ViewStateMode,
  WorkspaceAssetItem,
  WorkspaceInfo,
  WorkspaceSummary,
} from '@/types/studio';

const ACTIVE_JOB_STATUSES = new Set([
  'CREATED',
  'QUEUED',
  'PROCESSING',
  'RENDERING',
  'PENDING',
  'GENERATING_CLIPS',
  'COMPOSITING',
]);

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = typeof reader.result === 'string' ? reader.result : '';
      const commaIdx = result.indexOf(',');
      resolve(commaIdx >= 0 ? result.slice(commaIdx + 1) : result);
    };
    reader.onerror = () => reject(new Error('Failed to read image file.'));
    reader.readAsDataURL(file);
  });
}

export const StudioWorkspace: React.FC = () => {
  const initialDraft = useMemo(
    () => getPresetAdProps('ur', 'problem_solution'),
    []
  );

  // Authenticated SaaS identity & workspace isolation state (never hardcoded)
  const [user, setUser] = useState<AuthUserSummary | null>(null);
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [workspaceId, setWorkspaceId] = useState<string>('');
  const [isAuthChecking, setIsAuthChecking] = useState<boolean>(true);
  const [isAuthModalOpen, setIsAuthModalOpen] = useState<boolean>(false);
  const [authModalMode, setAuthModalMode] = useState<AuthModalMode>('login');

  const [viewStateMode, setViewStateMode] = useState<ViewStateMode>('normal');

  // Form & localization state — honest product fields start empty until scraped/entered
  const [productUrl, setProductUrl] = useState<string>('');
  const [targetLanguage, setTargetLanguage] = useState<SupportedLanguage>('ur');
  const [adAngle, setAdAngle] = useState<AdAngle>('problem_solution');
  const [aspectRatio, setAspectRatio] = useState<'9:16' | '16:9'>('9:16');
  const [durationSeconds, setDurationSeconds] = useState<number>(4);

  const [productTitle, setProductTitle] = useState<string>('');
  const [brandName, setBrandName] = useState<string>('');
  const [currency, setCurrency] = useState<string>('PKR');
  const [priceDisplay, setPriceDisplay] = useState<string>('');
  const [originalPriceDisplay, setOriginalPriceDisplay] = useState<string>('');
  const [discountBadge, setDiscountBadge] = useState<string>('');
  const [productImageUrl, setProductImageUrl] = useState<string>('');
  const [selectedAssetId, setSelectedAssetId] = useState<string>('');
  const [workspaceAssets, setWorkspaceAssets] = useState<WorkspaceAssetItem[]>(
    []
  );
  const [isUploadingAsset, setIsUploadingAsset] = useState<boolean>(false);
  const [assetUploadError, setAssetUploadError] = useState<string | null>(null);

  const [hookText, setHookText] = useState<string>(initialDraft.hookText);
  const [ctaText, setCtaText] = useState<string>(initialDraft.ctaText);
  const [captions, setCaptions] = useState<CaptionSegment[]>(
    initialDraft.captions
  );
  const [isProductEmpty, setIsProductEmpty] = useState<boolean>(false);
  const [fieldsConfirmed, setFieldsConfirmed] = useState<boolean>(false);

  // Scraper state
  const [isScraping, setIsScraping] = useState<boolean>(false);
  const [scrapeError, setScrapeError] = useState<string | null>(null);
  const [scrapeMetadata, setScrapeMetadata] =
    useState<ScrapedProductMetadata | null>(null);

  // Credit ledger & billing modal state
  const [creditBalance, setCreditBalance] = useState<number>(0);
  const [ledger, setLedger] = useState<CreditLedgerEntry[]>([]);
  const [isLoadingCredits, setIsLoadingCredits] = useState<boolean>(false);
  const [creditsError, setCreditsError] = useState<string | null>(null);
  const [isCreditModalOpen, setIsCreditModalOpen] = useState<boolean>(false);
  const [isCheckingOutPackId, setIsCheckingOutPackId] = useState<string | null>(
    null
  );

  // Render queue state
  const [jobs, setJobs] = useState<VideoJobRecord[]>([]);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [isLoadingJobs, setIsLoadingJobs] = useState<boolean>(false);
  const [jobsError, setJobsError] = useState<string | null>(null);
  const [isGenerating, setIsGenerating] = useState<boolean>(false);
  const [bannerMessage, setBannerMessage] = useState<string | null>(null);

  const refreshPromiseRef = useRef<Promise<boolean> | null>(null);

  const refreshAccessToken = useCallback(async (): Promise<boolean> => {
    if (refreshPromiseRef.current) {
      return refreshPromiseRef.current;
    }
    const promise = (async () => {
      try {
        const res = await fetch('/api/v1/auth/refresh', {
          method: 'POST',
          credentials: 'include',
          cache: 'no-store',
        });
        return res.ok;
      } catch {
        return false;
      } finally {
        refreshPromiseRef.current = null;
      }
    })();
    refreshPromiseRef.current = promise;
    return promise;
  }, []);

  const fetchWithAuthRetry = useCallback(
    async (input: string, init?: RequestInit): Promise<Response> => {
      const firstRes = await fetch(input, {
        ...init,
        credentials: 'include',
        cache: 'no-store',
      });
      if (firstRes.status !== 401) {
        return firstRes;
      }
      const refreshed = await refreshAccessToken();
      if (!refreshed) {
        return firstRes;
      }
      return fetch(input, {
        ...init,
        credentials: 'include',
        cache: 'no-store',
      });
    },
    [refreshAccessToken]
  );

  // Fetch authenticated user & workspaces on mount
  const bootstrapSession = useCallback(async () => {
    setIsAuthChecking(true);
    try {
      const res = await fetchWithAuthRetry('/api/v1/auth/me', {
        method: 'GET',
      });
      if (!res.ok) {
        setUser(null);
        setWorkspaces([]);
        setWorkspaceId('');
        setCreditBalance(0);
        setLedger([]);
        setJobs([]);
        setWorkspaceAssets([]);
        setIsAuthModalOpen(true);
        return;
      }
      const data = (await res.json()) as { user?: AuthUserSummary };
      if (data.user) {
        setUser(data.user);
        setWorkspaces(data.user.workspaces ?? []);
        const firstWs = data.user.workspaces?.[0]?.id ?? '';
        setWorkspaceId((prev) =>
          prev && data.user?.workspaces?.some((w) => w.id === prev)
            ? prev
            : firstWs
        );
      }
    } catch {
      setUser(null);
      setWorkspaces([]);
    } finally {
      setIsAuthChecking(false);
    }
  }, [fetchWithAuthRetry]);

  useEffect(() => {
    void bootstrapSession();

    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.search);
      const checkoutStatus = params.get('checkout');
      if (checkoutStatus === 'success') {
        setBannerMessage(
          'Returned from Stripe Checkout. Credits reflect verified Stripe webhook settlement.'
        );
        window.history.replaceState({}, '', window.location.pathname);
      } else if (checkoutStatus === 'cancelled') {
        setBannerMessage('Stripe Checkout cancelled. No charge was made.');
        window.history.replaceState({}, '', window.location.pathname);
      }
    }
  }, [bootstrapSession]);

  // Fetch workspace balance & atomic ledger
  const fetchWorkspaceCredits = useCallback(async () => {
    if (!user || !workspaceId) {
      return;
    }
    setIsLoadingCredits(true);
    setCreditsError(null);
    try {
      const response = await fetchWithAuthRetry(
        `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/credits`
      );
      if (response.status === 401) {
        setUser(null);
        setIsAuthModalOpen(true);
        return;
      }
      if (!response.ok) {
        throw new Error(`HTTP ${response.status} fetching workspace credits`);
      }
      const data = (await response.json()) as WorkspaceInfo;
      setCreditBalance(data.credit_balance);
      setLedger(data.ledger ?? []);
    } catch (err) {
      setCreditsError(
        err instanceof Error
          ? err.message
          : 'Failed to load workspace credit ledger'
      );
    } finally {
      setIsLoadingCredits(false);
    }
  }, [user, workspaceId, fetchWithAuthRetry]);

  // Fetch workspace video jobs
  const fetchVideoJobs = useCallback(async () => {
    if (!user || !workspaceId) {
      return;
    }
    setIsLoadingJobs(true);
    setJobsError(null);
    try {
      const response = await fetchWithAuthRetry(
        `/api/v1/videos?workspace_id=${encodeURIComponent(workspaceId)}`
      );
      if (response.status === 401) {
        setUser(null);
        setIsAuthModalOpen(true);
        return;
      }
      if (!response.ok) {
        throw new Error(`HTTP ${response.status} loading render queue`);
      }
      const data = (await response.json()) as VideoJobRecord[];
      setJobs(data);
      setActiveJobId((prev) =>
        prev && data.some((j) => j.id === prev) ? prev : data[0]?.id ?? null
      );
    } catch (err) {
      setJobsError(
        err instanceof Error ? err.message : 'Failed to fetch video render jobs'
      );
    } finally {
      setIsLoadingJobs(false);
    }
  }, [user, workspaceId, fetchWithAuthRetry]);

  const fetchWorkspaceAssets = useCallback(async () => {
    if (!user || !workspaceId) {
      return;
    }
    try {
      const res = await fetchWithAuthRetry(
        `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/assets`
      );
      if (res.ok) {
        const data = (await res.json()) as { assets?: WorkspaceAssetItem[] };
        setWorkspaceAssets(data.assets ?? []);
      }
    } catch {
      // Non-fatal UI asset list sync failure
    }
  }, [user, workspaceId, fetchWithAuthRetry]);

  useEffect(() => {
    if (user && workspaceId) {
      void fetchWorkspaceCredits();
      void fetchVideoJobs();
      void fetchWorkspaceAssets();
    }
  }, [
    user,
    workspaceId,
    fetchWorkspaceCredits,
    fetchVideoJobs,
    fetchWorkspaceAssets,
  ]);

  // Poll non-terminal jobs cleanly until settled
  useEffect(() => {
    if (!user || !workspaceId) {
      return;
    }
    const hasInFlight = jobs.some((job) =>
      ACTIVE_JOB_STATUSES.has(job.status)
    );
    if (!hasInFlight) {
      return;
    }
    const timer = setInterval(() => {
      void fetchVideoJobs();
      void fetchWorkspaceCredits();
    }, 2500);
    return () => clearInterval(timer);
  }, [user, workspaceId, jobs, fetchVideoJobs, fetchWorkspaceCredits]);

  const handleAuthSuccess = useCallback(
    (
      nextUser: AuthUserSummary,
      preferredWorkspaceId?: string,
      devVerifyToken?: string
    ) => {
      setUser(nextUser);
      setWorkspaces(nextUser.workspaces ?? []);
      const targetWs =
        preferredWorkspaceId || nextUser.workspaces?.[0]?.id || '';
      setWorkspaceId(targetWs);
      setIsAuthModalOpen(false);
      setBannerMessage(
        devVerifyToken
          ? `Signed in cleanly as ${nextUser.email}. Dev email verification token: ${devVerifyToken}`
          : `Signed in cleanly as ${nextUser.email}.`
      );
    },
    []
  );

  const handleLogout = useCallback(async () => {
    await fetch('/api/v1/auth/logout', {
      method: 'POST',
      credentials: 'include',
    });
    setUser(null);
    setWorkspaces([]);
    setWorkspaceId('');
    setCreditBalance(0);
    setLedger([]);
    setJobs([]);
    setActiveJobId(null);
    setWorkspaceAssets([]);
    setIsAuthModalOpen(true);
    setAuthModalMode('login');
  }, []);

  const handleCreateWorkspace = useCallback(async (name: string) => {
    const res = await fetch('/api/v1/workspaces', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ name }),
    });
    const data = (await res.json()) as WorkspaceSummary & { detail?: string };
    if (!res.ok) {
      setBannerMessage(data.detail ?? 'Failed to create workspace.');
      return;
    }
    setWorkspaces((prev) => [...prev, data]);
    setWorkspaceId(data.id);
    setBannerMessage(`Created isolated workspace "${data.name}".`);
  }, []);

  // Synchronize copy draft scaffolding (never overwrites factual prices/brands)
  const applyLanguageDraft = useCallback(
    (nextLang: SupportedLanguage, nextAngle: AdAngle) => {
      const preset = getPresetAdProps(nextLang, nextAngle);
      setTargetLanguage(nextLang);
      setAdAngle(nextAngle);
      setHookText(preset.hookText);
      setCtaText(preset.ctaText);
      setCaptions(preset.captions);
      setCurrency(preset.currency);
      setIsProductEmpty(false);
      setScrapeError(null);
      if (viewStateMode === 'empty' || viewStateMode === 'error') {
        setViewStateMode('normal');
      }
    },
    [viewStateMode]
  );

  const handleLanguageChange = useCallback(
    (nextLang: SupportedLanguage) => {
      applyLanguageDraft(nextLang, adAngle);
    },
    [adAngle, applyLanguageDraft]
  );

  const handleAdAngleChange = useCallback(
    (nextAngle: AdAngle) => {
      applyLanguageDraft(targetLanguage, nextAngle);
    },
    [targetLanguage, applyLanguageDraft]
  );

  // Live SSRF-protected product scrape
  const handleScrapeUrl = useCallback(
    async (overrideUrl?: string) => {
      if (!user) {
        setIsAuthModalOpen(true);
        return;
      }
      const urlToScrape = (overrideUrl ?? productUrl).trim();
      setIsScraping(true);
      setScrapeError(null);
      setFieldsConfirmed(false);

      try {
        const response = await fetch('/api/v1/products/scrape', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            product_url: urlToScrape,
            target_language: targetLanguage,
            ad_angle: adAngle,
          }),
        });

        const payload = (await response.json()) as ScrapedProductMetadata & {
          detail?: string;
        };

        if (!response.ok) {
          throw new Error(
            payload.detail ?? `Scrape failed with status ${response.status}`
          );
        }

        setScrapeMetadata(payload);
        setProductTitle(payload.title ?? '');
        setBrandName(payload.brand ?? '');
        setCurrency(payload.currency ?? '');
        setPriceDisplay(payload.price ?? '');
        setOriginalPriceDisplay(payload.original_price ?? '');
        setDiscountBadge(payload.discount_badge ?? '');
        setProductImageUrl(payload.image_url ?? '');
        if (payload.suggested_props) {
          setHookText(payload.suggested_props.hookText);
          setCtaText(payload.suggested_props.ctaText);
          setCaptions(payload.suggested_props.captions);
        }
        setFieldsConfirmed(!payload.requires_user_confirmation);
        setIsProductEmpty(false);
      } catch (err) {
        setScrapeError(
          err instanceof Error
            ? err.message
            : 'Unable to extract D2C product metadata'
        );
      } finally {
        setIsScraping(false);
      }
    },
    [user, productUrl, targetLanguage, adAngle]
  );

  const handleUploadProductAsset = useCallback(
    async (file: File) => {
      if (!user || !workspaceId) {
        setIsAuthModalOpen(true);
        return;
      }
      setIsUploadingAsset(true);
      setAssetUploadError(null);
      try {
        const contentBase64 = await fileToBase64(file);
        const res = await fetch(
          `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/assets`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({
              filename: file.name,
              content_base64: contentBase64,
            }),
          }
        );
        const data = (await res.json()) as WorkspaceAssetItem & {
          detail?: string;
        };
        if (!res.ok) {
          throw new Error(data.detail ?? `Upload failed (${res.status})`);
        }
        setWorkspaceAssets((prev) => [data, ...prev]);
        setSelectedAssetId(data.id);
        setBannerMessage(`Uploaded product asset "${data.filename}".`);
      } catch (err) {
        setAssetUploadError(
          err instanceof Error ? err.message : 'Asset upload failed.'
        );
      } finally {
        setIsUploadingAsset(false);
      }
    },
    [user, workspaceId]
  );

  const handleClearProduct = useCallback(() => {
    setProductTitle('');
    setBrandName('');
    setPriceDisplay('');
    setOriginalPriceDisplay('');
    setDiscountBadge('');
    setProductImageUrl('');
    setSelectedAssetId('');
    setScrapeMetadata(null);
    setFieldsConfirmed(false);
    setHookText('');
    setCtaText('');
    setCaptions([]);
    setIsProductEmpty(true);
  }, []);

  const handleLoadDefaultPreset = useCallback(() => {
    applyLanguageDraft(targetLanguage, adAngle);
    setFieldsConfirmed(false);
  }, [targetLanguage, adAngle, applyLanguageDraft]);

  const handleCaptionTextChange = useCallback((index: number, text: string) => {
    setCaptions((prev) =>
      prev.map((item, idx) => (idx === index ? { ...item, text } : item))
    );
  }, []);

  const handleCaptionHighlightChange = useCallback(
    (index: number, highlightWord: string) => {
      setCaptions((prev) =>
        prev.map((item, idx) =>
          idx === index ? { ...item, highlightWord } : item
        )
      );
    },
    []
  );

  // Dispatch video render job to authenticated worker
  const handleGenerateVideo = useCallback(async () => {
    if (!user || !workspaceId) {
      setIsAuthModalOpen(true);
      return;
    }
    setIsGenerating(true);
    setJobsError(null);
    setBannerMessage(null);

    try {
      const response = await fetchWithAuthRetry('/api/v1/videos/generate', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key':
            typeof crypto !== 'undefined' && crypto.randomUUID
              ? crypto.randomUUID()
              : `${Date.now()}`,
        },
        body: JSON.stringify({
          workspace_id: workspaceId,
          product_url:
            productUrl.trim() || 'https://example.com/products/verified-item',
          target_language: targetLanguage,
          ad_angle: adAngle,
          aspect_ratio: aspectRatio,
          duration_seconds: durationSeconds,
          custom_props: {
            productTitle,
            brandName,
            currency,
            priceDisplay,
            ...(originalPriceDisplay ? { originalPriceDisplay } : {}),
            ...(discountBadge ? { discountBadge } : {}),
            ...(productImageUrl ? { productImageUrl } : {}),
            ...(selectedAssetId ? { productImageAssetId: selectedAssetId } : {}),
            hookText,
            ctaText,
            captions,
            confirmedMetadata: {
              title: productTitle,
              brand: brandName,
              currency,
              price: priceDisplay,
              image_url: productImageUrl,
              features: scrapeMetadata?.features ?? [],
              description: scrapeMetadata?.description ?? '',
            },
          },
        }),
      });

      const payload = (await response.json()) as VideoJobRecord & {
        detail?: string;
      };

      if (response.status === 401) {
        setUser(null);
        setIsAuthModalOpen(true);
        return;
      }

      if (response.status === 402) {
        setIsCreditModalOpen(true);
        throw new Error(
          payload.detail ??
            'Insufficient credits in workspace. Please purchase credits.'
        );
      }

      if (!response.ok) {
        throw new Error(
          payload.detail ?? `Video generation failed (${response.status})`
        );
      }

      setJobs((prev) => [
        payload,
        ...prev.filter((item) => item.id !== payload.id),
      ]);
      setActiveJobId(payload.id);

      if (typeof payload.credit_balance === 'number') {
        setCreditBalance(payload.credit_balance);
      }

      if (payload.status === 'FAILED') {
        setBannerMessage(
          `Job #${payload.id.slice(0, 8)} failed — reserved credit refunded atomically.`
        );
      } else {
        setBannerMessage(
          `Job #${payload.id.slice(0, 8)} (${payload.target_language.toUpperCase()} · ${aspectRatio}) queued/completed.`
        );
      }

      void fetchWorkspaceCredits();
    } catch (err) {
      setJobsError(
        err instanceof Error
          ? err.message
          : 'Unable to dispatch video render job'
      );
    } finally {
      setIsGenerating(false);
    }
  }, [
    user,
    workspaceId,
    productUrl,
    targetLanguage,
    adAngle,
    aspectRatio,
    durationSeconds,
    productTitle,
    brandName,
    currency,
    priceDisplay,
    originalPriceDisplay,
    discountBadge,
    productImageUrl,
    selectedAssetId,
    hookText,
    ctaText,
    captions,
    scrapeMetadata,
    fetchWithAuthRetry,
    fetchWorkspaceCredits,
  ]);

  const handleCancelJob = useCallback(
    async (jobId: string) => {
      const res = await fetch(
        `/api/v1/videos/${encodeURIComponent(jobId)}/cancel`,
        { method: 'POST', credentials: 'include' }
      );
      const data = (await res.json()) as VideoJobRecord & { detail?: string };
      if (!res.ok) {
        setBannerMessage(data.detail ?? 'Failed to cancel job.');
        return;
      }
      setJobs((prev) => prev.map((j) => (j.id === data.id ? data : j)));
      if (typeof data.credit_balance === 'number') {
        setCreditBalance(data.credit_balance);
      }
      void fetchWorkspaceCredits();
    },
    [fetchWorkspaceCredits]
  );

  const handleRetryJob = useCallback(
    async (jobId: string) => {
      const res = await fetch(
        `/api/v1/videos/${encodeURIComponent(jobId)}/retry`,
        { method: 'POST', credentials: 'include' }
      );
      const data = (await res.json()) as VideoJobRecord & { detail?: string };
      if (!res.ok) {
        setBannerMessage(data.detail ?? 'Failed to retry job.');
        return;
      }
      setJobs((prev) => [data, ...prev.filter((j) => j.id !== data.id)]);
      setActiveJobId(data.id);
      if (typeof data.credit_balance === 'number') {
        setCreditBalance(data.credit_balance);
      }
      void fetchWorkspaceCredits();
    },
    [fetchWorkspaceCredits]
  );

  const handleCopySignedUrl = useCallback(async (jobId: string) => {
    const res = await fetch(
      `/api/v1/videos/${encodeURIComponent(jobId)}/signed-url`,
      { method: 'GET', credentials: 'include' }
    );
    const data = (await res.json()) as {
      download_path?: string;
      detail?: string;
    };
    if (!res.ok || !data.download_path) {
      setBannerMessage(data.detail ?? 'Failed to generate signed URL.');
      return;
    }
    const fullUrl =
      typeof window !== 'undefined'
        ? `${window.location.origin}${data.download_path}`
        : data.download_path;
    if (typeof navigator !== 'undefined' && navigator.clipboard) {
      await navigator.clipboard.writeText(fullUrl);
      setBannerMessage(`Copied time-limited signed MP4 URL to clipboard.`);
    } else {
      setBannerMessage(`Signed URL: ${fullUrl}`);
    }
  }, []);

  const handleSelectJobForPreview = useCallback((job: VideoJobRecord) => {
    setActiveJobId(job.id);
    setProductUrl(job.product_url);
    setTargetLanguage(job.target_language);
    if (job.aspect_ratio === '16:9' || job.aspect_ratio === '9:16') {
      setAspectRatio(job.aspect_ratio);
    }

    const script = job.script_json;
    if (script) {
      setAdAngle(script.ad_angle ?? 'problem_solution');
      setProductTitle(script.product_title ?? '');
      setBrandName(script.brand ?? '');
      setCurrency(script.currency ?? '');
      setPriceDisplay(script.price_badge ?? '');
      setOriginalPriceDisplay(script.original_price ?? '');
      setDiscountBadge(script.discount_badge ?? '');
      setProductImageUrl(script.product_image_url ?? '');
      setHookText(script.hook ?? '');
      setCtaText(script.cta_text ?? '');
      setCaptions(
        (script.captions ?? []).map((c, idx) => ({
          id: c.id ?? `cap-${idx + 1}`,
          text: c.text,
          startFrame:
            typeof c.startFrame === 'number' ? c.startFrame : idx * 20,
          endFrame:
            typeof c.endFrame === 'number' ? c.endFrame : (idx + 1) * 20,
          highlightWord: c.highlightWord,
        }))
      );
      setFieldsConfirmed(true);
    }
    setIsProductEmpty(false);
  }, []);

  // Initiate real Stripe Checkout Session on worker (redirect only; never client credits)
  const handleCheckoutCredits = useCallback(
    async (packId: string) => {
      if (!user || !workspaceId) {
        setIsAuthModalOpen(true);
        return;
      }
      setIsCheckingOutPackId(packId);
      setCreditsError(null);
      try {
        const origin =
          typeof window !== 'undefined' ? window.location.origin : '';
        const response = await fetch(
          `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/credits`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({
              pack_id: packId,
              ...(origin
                ? {
                    success_url: `${origin}/?checkout=success`,
                    cancel_url: `${origin}/?checkout=cancelled`,
                  }
                : {}),
            }),
          }
        );
        const data = (await response.json()) as {
          checkout_url?: string;
          detail?: string;
        };
        if (!response.ok || !data.checkout_url) {
          throw new Error(
            data.detail ?? `Stripe Checkout failed (${response.status})`
          );
        }
        window.location.href = data.checkout_url;
      } catch (err) {
        setCreditsError(
          err instanceof Error
            ? err.message
            : 'Unable to launch Stripe Checkout.'
        );
      } finally {
        setIsCheckingOutPackId(null);
      }
    },
    [user, workspaceId]
  );

  // Explicitly dev-only top-up (blocked with 403 by FastAPI outside local dev)
  const handleDevTopup = useCallback(
    async (packId: string) => {
      if (!user || !workspaceId) {
        return;
      }
      setIsCheckingOutPackId(packId);
      setCreditsError(null);
      try {
        const res = await fetch(
          `/api/v1/workspaces/${encodeURIComponent(
            workspaceId
          )}/credits/dev-topup`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ pack_id: packId }),
          }
        );
        const data = (await res.json()) as {
          credit_balance?: number;
          detail?: string;
        };
        if (!res.ok) {
          throw new Error(
            data.detail ?? `Dev top-up rejected (${res.status})`
          );
        }
        await fetchWorkspaceCredits();
        setBannerMessage(`Dev top-up granted (${packId}).`);
      } catch (err) {
        setCreditsError(
          err instanceof Error ? err.message : 'Dev top-up unavailable.'
        );
      } finally {
        setIsCheckingOutPackId(null);
      }
    },
    [user, workspaceId, fetchWorkspaceCredits]
  );

  const activeJob = useMemo(
    () => jobs.find((item) => item.id === activeJobId) ?? null,
    [jobs, activeJobId]
  );

  const completedJobsCount = useMemo(
    () => jobs.filter((item) => item.status === 'COMPLETED').length,
    [jobs]
  );

  const liveAdProps: LocalizedAdProps = useMemo(() => {
    const resolvedImage = selectedAssetId
      ? `/api/v1/assets/${encodeURIComponent(selectedAssetId)}`
      : productImageUrl || undefined;
    return {
      ...initialDraft,
      jobId: activeJobId ?? 'live_studio_draft',
      language: targetLanguage,
      adAngle,
      productTitle: productTitle || 'Confirmed Product Title',
      brandName: brandName || 'Verified Brand',
      currency: currency || '',
      priceDisplay: priceDisplay || '—',
      originalPriceDisplay: originalPriceDisplay || undefined,
      discountBadge: discountBadge || undefined,
      productImageUrl: resolvedImage,
      hookText: hookText || initialDraft.hookText,
      ctaText: ctaText || initialDraft.ctaText,
      captions: captions.length > 0 ? captions : initialDraft.captions,
    };
  }, [
    initialDraft,
    activeJobId,
    targetLanguage,
    adAngle,
    productTitle,
    brandName,
    currency,
    priceDisplay,
    originalPriceDisplay,
    discountBadge,
    selectedAssetId,
    productImageUrl,
    hookText,
    ctaText,
    captions,
  ]);

  const canDispatchRender =
    Boolean(user) &&
    Boolean(workspaceId) &&
    Boolean(productTitle.trim()) &&
    Boolean(brandName.trim()) &&
    Boolean(priceDisplay.trim()) &&
    fieldsConfirmed &&
    creditBalance >= 1 &&
    !isGenerating;

  return (
    <div className="min-h-screen bg-[#09090B] text-[#FAFAFA]">
      <StudioHeader
        user={user}
        workspaces={workspaces}
        activeWorkspaceId={workspaceId}
        onSelectWorkspace={setWorkspaceId}
        onCreateWorkspace={handleCreateWorkspace}
        onOpenAuthModal={(mode = 'login') => {
          setAuthModalMode(mode);
          setIsAuthModalOpen(true);
        }}
        onLogout={handleLogout}
        creditBalance={creditBalance}
        isLoadingCredits={isLoadingCredits}
        totalJobsCount={jobs.length}
        completedJobsCount={completedJobsCount}
        viewStateMode={viewStateMode}
        onChangeViewStateMode={setViewStateMode}
        onOpenCreditModal={() => setIsCreditModalOpen(true)}
        onRefreshAll={() => {
          void fetchWorkspaceCredits();
          void fetchVideoJobs();
          void fetchWorkspaceAssets();
        }}
      />

      <main className="mx-auto flex max-w-[1200px] flex-col gap-6 px-6 py-6">
        {/* Auth Required Gate Banner when dismissed modal */}
        {!isAuthChecking && !user ? (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded border border-amber-500/60 bg-[#18181B] px-4 py-3 text-xs">
            <div className="flex items-center gap-2">
              <ShieldAlert className="h-4 w-4 text-amber-400" />
              <span>
                Sign in or register an account to access isolated workspaces,
                SSRF-guarded product scraping, Stripe credit checkout, and
                real MP4 rendering.
              </span>
            </div>
            <button
              type="button"
              onClick={() => {
                setAuthModalMode('login');
                setIsAuthModalOpen(true);
              }}
              className="rounded border border-[#6366F1] bg-[#6366F1] px-3 py-1.5 font-semibold text-[#FAFAFA]"
            >
              Sign In / Create Account
            </button>
          </div>
        ) : null}

        {bannerMessage ? (
          <div className="flex items-center justify-between rounded border border-[#6366F1] bg-[#18181B] px-4 py-2 text-xs text-[#FAFAFA]">
            <span className="font-mono-code tabular-nums">{bannerMessage}</span>
            <button
              type="button"
              onClick={() => setBannerMessage(null)}
              className="text-xs text-[#A1A1AA] hover:text-[#FAFAFA]"
            >
              Dismiss
            </button>
          </div>
        ) : null}

        <div className="flex flex-col items-stretch gap-6 lg:flex-row">
          <ProductScraperPanel
            productUrl={productUrl}
            onChangeProductUrl={setProductUrl}
            targetLanguage={targetLanguage}
            onChangeLanguage={handleLanguageChange}
            adAngle={adAngle}
            onChangeAdAngle={handleAdAngleChange}
            aspectRatio={aspectRatio}
            onChangeAspectRatio={setAspectRatio}
            durationSeconds={durationSeconds}
            onChangeDurationSeconds={setDurationSeconds}
            productTitle={productTitle}
            onChangeProductTitle={setProductTitle}
            brandName={brandName}
            onChangeBrandName={setBrandName}
            priceDisplay={priceDisplay}
            onChangePriceDisplay={setPriceDisplay}
            originalPriceDisplay={originalPriceDisplay}
            onChangeOriginalPriceDisplay={setOriginalPriceDisplay}
            discountBadge={discountBadge}
            onChangeDiscountBadge={setDiscountBadge}
            productImageUrl={productImageUrl}
            onChangeProductImageUrl={setProductImageUrl}
            selectedAssetId={selectedAssetId}
            onChangeSelectedAssetId={setSelectedAssetId}
            workspaceAssets={workspaceAssets}
            isUploadingAsset={isUploadingAsset}
            assetUploadError={assetUploadError}
            onUploadProductAsset={(f) => {
              void handleUploadProductAsset(f);
            }}
            hookText={hookText}
            onChangeHookText={setHookText}
            ctaText={ctaText}
            onChangeCtaText={setCtaText}
            captions={captions}
            onChangeCaptionText={handleCaptionTextChange}
            onChangeCaptionHighlight={handleCaptionHighlightChange}
            isScraping={isScraping}
            scrapeError={scrapeError}
            scrapeMetadata={scrapeMetadata}
            fieldsConfirmed={fieldsConfirmed}
            onChangeFieldsConfirmed={setFieldsConfirmed}
            isProductEmpty={isProductEmpty}
            onScrapeUrl={(overrideUrl) => {
              void handleScrapeUrl(overrideUrl);
            }}
            onClearProduct={handleClearProduct}
            onLoadDefaultPreset={handleLoadDefaultPreset}
            isGenerating={isGenerating}
            creditBalance={creditBalance}
            isAuthenticated={Boolean(user)}
            onGenerateVideo={() => {
              void handleGenerateVideo();
            }}
            onOpenCreditModal={() => setIsCreditModalOpen(true)}
            viewStateMode={viewStateMode}
          />

          <RemotionPreviewStage
            adProps={liveAdProps}
            activeJob={activeJob}
            aspectRatio={aspectRatio}
            canGenerate={canDispatchRender}
            viewStateMode={viewStateMode}
            onGenerateVideo={() => {
              void handleGenerateVideo();
            }}
          />
        </div>

        <RenderQueueGallery
          jobs={jobs}
          activeJobId={activeJobId}
          isLoadingJobs={isLoadingJobs}
          jobsError={jobsError}
          viewStateMode={viewStateMode}
          onSelectJobForPreview={handleSelectJobForPreview}
          onRetryFetchJobs={() => {
            setViewStateMode('normal');
            void fetchVideoJobs();
          }}
          onCancelJob={(id) => {
            void handleCancelJob(id);
          }}
          onRetryJob={(id) => {
            void handleRetryJob(id);
          }}
          onCopySignedUrl={(id) => {
            void handleCopySignedUrl(id);
          }}
          onGenerateFirstJob={() => {
            setViewStateMode('normal');
            void handleGenerateVideo();
          }}
          onClearLocalJobs={() => {
            setJobs([]);
            setActiveJobId(null);
          }}
        />
      </main>

      <CreditCheckoutModal
        isOpen={isCreditModalOpen}
        onClose={() => setIsCreditModalOpen(false)}
        workspaceId={workspaceId || 'UNAUTHENTICATED'}
        creditBalance={creditBalance}
        ledger={ledger}
        isLoadingCredits={isLoadingCredits}
        isCheckingOutPackId={isCheckingOutPackId}
        creditsError={creditsError}
        viewStateMode={viewStateMode}
        onCheckoutCredits={(packId) => {
          void handleCheckoutCredits(packId);
        }}
        onDevTopup={(packId) => {
          void handleDevTopup(packId);
        }}
        onRetryFetchCredits={() => {
          setViewStateMode('normal');
          void fetchWorkspaceCredits();
        }}
      />

      <AuthModal
        isOpen={isAuthModalOpen}
        initialMode={authModalMode}
        currentUserEmail={user?.email ?? ''}
        onClose={() => setIsAuthModalOpen(false)}
        onAuthSuccess={handleAuthSuccess}
      />
    </div>
  );
};
