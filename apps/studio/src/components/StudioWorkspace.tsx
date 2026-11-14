'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  getPresetAdProps,
  type AdAngle,
  type CaptionSegment,
  type LocalizedAdProps,
  type SupportedLanguage,
} from '@video-ad/remotion';
import { DEFAULT_WORKSPACE_ID } from '@/lib/supabase';
import type {
  CreditLedgerEntry,
  ScrapedProductMetadata,
  VideoJobRecord,
  ViewStateMode,
  WorkspaceInfo,
} from '@/types/studio';
import { CreditCheckoutModal } from './CreditCheckoutModal';
import {
  ProductScraperPanel,
  SAMPLE_STORE_URLS,
} from './ProductScraperPanel';
import { RemotionPreviewStage } from './RemotionPreviewStage';
import { RenderQueueGallery } from './RenderQueueGallery';
import { StudioHeader } from './StudioHeader';

export const StudioWorkspace: React.FC = () => {
  const initialPreset = useMemo(
    () => getPresetAdProps('ur', 'problem_solution'),
    []
  );

  // Global View State Inspector (allows instant inspection of Normal / Skeleton / Empty / Error states)
  const [viewStateMode, setViewStateMode] = useState<ViewStateMode>('normal');

  // Workspace & Credit Ledger State
  const [workspaceId] = useState<string>(DEFAULT_WORKSPACE_ID);
  const [creditBalance, setCreditBalance] = useState<number>(10);
  const [ledger, setLedger] = useState<CreditLedgerEntry[]>([]);
  const [isLoadingCredits, setIsLoadingCredits] = useState<boolean>(false);
  const [creditsError, setCreditsError] = useState<string | null>(null);
  const [isCreditModalOpen, setIsCreditModalOpen] = useState<boolean>(false);
  const [isCheckingOutPackId, setIsCheckingOutPackId] = useState<string | null>(
    null
  );

  // Left Panel: Product URL & Localized Ad Script State
  const [productUrl, setProductUrl] = useState<string>(
    SAMPLE_STORE_URLS[0]?.url ??
      'https://zaynaskin.pk/products/vitamin-c-glow-serum'
  );
  const [targetLanguage, setTargetLanguage] = useState<SupportedLanguage>('ur');
  const [adAngle, setAdAngle] = useState<AdAngle>('problem_solution');
  const [productTitle, setProductTitle] = useState<string>(
    initialPreset.productTitle
  );
  const [brandName, setBrandName] = useState<string>(initialPreset.brandName);
  const [currency, setCurrency] = useState<string>(initialPreset.currency);
  const [priceDisplay, setPriceDisplay] = useState<string>(
    initialPreset.priceDisplay
  );
  const [originalPriceDisplay, setOriginalPriceDisplay] = useState<string>(
    initialPreset.originalPriceDisplay ?? 'PKR 7,200'
  );
  const [discountBadge, setDiscountBadge] = useState<string>(
    initialPreset.discountBadge ?? '-31% OFF'
  );
  const [hookText, setHookText] = useState<string>(initialPreset.hookText);
  const [ctaText, setCtaText] = useState<string>(initialPreset.ctaText);
  const [captions, setCaptions] = useState<CaptionSegment[]>(
    initialPreset.captions
  );
  const [isScraping, setIsScraping] = useState<boolean>(false);
  const [scrapeError, setScrapeError] = useState<string | null>(null);
  const [isProductEmpty, setIsProductEmpty] = useState<boolean>(false);

  // Render Queue State
  const [jobs, setJobs] = useState<VideoJobRecord[]>([]);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [isLoadingJobs, setIsLoadingJobs] = useState<boolean>(false);
  const [jobsError, setJobsError] = useState<string | null>(null);
  const [isGenerating, setIsGenerating] = useState<boolean>(false);
  const [bannerMessage, setBannerMessage] = useState<string | null>(null);

  // Fetch workspace credits & ledger
  const fetchWorkspaceCredits = useCallback(async () => {
    setIsLoadingCredits(true);
    setCreditsError(null);
    try {
      const response = await fetch(
        `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/credits`,
        { cache: 'no-store' }
      );
      if (!response.ok) {
        throw new Error(`HTTP ${response.status} loading workspace credits`);
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
  }, [workspaceId]);

  // Fetch video_jobs queue
  const fetchVideoJobs = useCallback(async () => {
    setIsLoadingJobs(true);
    setJobsError(null);
    try {
      const response = await fetch(
        `/api/v1/videos?workspace_id=${encodeURIComponent(workspaceId)}`,
        { cache: 'no-store' }
      );
      if (!response.ok) {
        throw new Error(`HTTP ${response.status} loading render queue`);
      }
      const data = (await response.json()) as VideoJobRecord[];
      setJobs(data);
      if (data.length > 0 && !activeJobId) {
        setActiveJobId(data[0]?.id ?? null);
      }
    } catch (err) {
      setJobsError(
        err instanceof Error ? err.message : 'Failed to fetch video render jobs'
      );
    } finally {
      setIsLoadingJobs(false);
    }
  }, [workspaceId, activeJobId]);

  useEffect(() => {
    void fetchWorkspaceCredits();
    void fetchVideoJobs();
  }, [fetchWorkspaceCredits, fetchVideoJobs]);

  // Synchronize preset when language or ad angle changes
  const applyPresetForLanguageAndAngle = useCallback(
    (nextLang: SupportedLanguage, nextAngle: AdAngle) => {
      const preset = getPresetAdProps(nextLang, nextAngle);
      setTargetLanguage(nextLang);
      setAdAngle(nextAngle);
      setProductTitle(preset.productTitle);
      setBrandName(preset.brandName);
      setCurrency(preset.currency);
      setPriceDisplay(preset.priceDisplay);
      setOriginalPriceDisplay(preset.originalPriceDisplay ?? '');
      setDiscountBadge(preset.discountBadge ?? '-30% OFF');
      setHookText(preset.hookText);
      setCtaText(preset.ctaText);
      setCaptions(preset.captions);
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
      applyPresetForLanguageAndAngle(nextLang, adAngle);
    },
    [adAngle, applyPresetForLanguageAndAngle]
  );

  const handleAdAngleChange = useCallback(
    (nextAngle: AdAngle) => {
      applyPresetForLanguageAndAngle(targetLanguage, nextAngle);
    },
    [targetLanguage, applyPresetForLanguageAndAngle]
  );

  // Scrape D2C Product URL
  const handleScrapeUrl = useCallback(
    async (overrideUrl?: string) => {
      const urlToScrape = (overrideUrl ?? productUrl).trim();
      setIsScraping(true);
      setScrapeError(null);

      try {
        const response = await fetch('/api/v1/products/scrape', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
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

        const suggested =
          payload.suggested_props ??
          getPresetAdProps(targetLanguage, adAngle, {
            productTitle: payload.title,
            brandName: payload.brand,
            currency: payload.currency,
            priceDisplay: payload.price,
            originalPriceDisplay: payload.original_price,
            discountBadge: payload.discount_badge,
          });

        setProductTitle(suggested.productTitle);
        setBrandName(suggested.brandName);
        setCurrency(suggested.currency);
        setPriceDisplay(suggested.priceDisplay);
        setOriginalPriceDisplay(suggested.originalPriceDisplay ?? '');
        setDiscountBadge(suggested.discountBadge ?? '-30% OFF');
        setHookText(suggested.hookText);
        setCtaText(suggested.ctaText);
        setCaptions(suggested.captions);
        setIsProductEmpty(false);
        if (viewStateMode !== 'normal') {
          setViewStateMode('normal');
        }
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
    [productUrl, targetLanguage, adAngle, viewStateMode]
  );

  const handleClearProduct = useCallback(() => {
    setProductTitle('');
    setBrandName('');
    setPriceDisplay('');
    setHookText('');
    setCtaText('');
    setCaptions([]);
    setIsProductEmpty(true);
  }, []);

  const handleLoadDefaultPreset = useCallback(() => {
    const defaultUrl =
      SAMPLE_STORE_URLS[0]?.url ??
      'https://zaynaskin.pk/products/vitamin-c-glow-serum';
    setProductUrl(defaultUrl);
    applyPresetForLanguageAndAngle(targetLanguage, adAngle);
  }, [targetLanguage, adAngle, applyPresetForLanguageAndAngle]);

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

  // Dispatch POST /api/v1/videos/generate (atomic 1 credit deduction + Veo 3.1 + Remotion render)
  const handleGenerateVideo = useCallback(
    async (simulateFailure = false) => {
      setIsGenerating(true);
      setJobsError(null);
      setBannerMessage(null);

      try {
        const response = await fetch('/api/v1/videos/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            workspace_id: workspaceId,
            product_url: productUrl,
            target_language: targetLanguage,
            ad_angle: adAngle,
            simulate_failure: simulateFailure,
            custom_props: {
              productTitle,
              brandName,
              priceDisplay,
              originalPriceDisplay,
              discountBadge,
              hookText,
              ctaText,
              captions,
            },
          }),
        });

        const payload = (await response.json()) as VideoJobRecord & {
          detail?: string;
        };

        if (response.status === 402) {
          setIsCreditModalOpen(true);
          throw new Error(
            payload.detail ??
              'Insufficient credits in workspace. Please top up credits.'
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
            `Job #${payload.id.slice(0, 8)} failed — 1 credit was atomically refunded to workspace.`
          );
        } else {
          setBannerMessage(
            `Job #${payload.id.slice(0, 8)} (${payload.target_language.toUpperCase()}) rendered — 1 credit deducted atomically.`
          );
        }

        void fetchWorkspaceCredits();
        if (viewStateMode === 'empty') {
          setViewStateMode('normal');
        }
      } catch (err) {
        setJobsError(
          err instanceof Error
            ? err.message
            : 'Unable to dispatch video render job'
        );
      } finally {
        setIsGenerating(false);
      }
    },
    [
      workspaceId,
      productUrl,
      targetLanguage,
      adAngle,
      productTitle,
      brandName,
      priceDisplay,
      originalPriceDisplay,
      discountBadge,
      hookText,
      ctaText,
      captions,
      fetchWorkspaceCredits,
      viewStateMode,
    ]
  );

  // Load a job from the Bottom Render Queue into the Center Remotion Preview
  const handleSelectJobForPreview = useCallback((job: VideoJobRecord) => {
    setActiveJobId(job.id);
    setProductUrl(job.product_url);
    setTargetLanguage(job.target_language);

    const script = job.script_json;
    const fallbackPreset = getPresetAdProps(
      job.target_language,
      script?.ad_angle ?? 'problem_solution'
    );

    if (script) {
      setAdAngle(script.ad_angle ?? 'problem_solution');
      setProductTitle(script.product_title || fallbackPreset.productTitle);
      setBrandName(script.brand || fallbackPreset.brandName);
      setCurrency(script.currency || fallbackPreset.currency);
      setPriceDisplay(script.price_badge || fallbackPreset.priceDisplay);
      setOriginalPriceDisplay(
        script.original_price ?? fallbackPreset.originalPriceDisplay ?? ''
      );
      setDiscountBadge(
        script.discount_badge ?? fallbackPreset.discountBadge ?? '-30% OFF'
      );
      setHookText(script.hook || fallbackPreset.hookText);
      setCtaText(script.cta_text || fallbackPreset.ctaText);
      setCaptions(
        script.captions && script.captions.length > 0
          ? script.captions.map((c, idx) => ({
              id: c.id ?? `cap-${idx + 1}`,
              text: c.text,
              startFrame:
                typeof c.startFrame === 'number' ? c.startFrame : idx * 20,
              endFrame:
                typeof c.endFrame === 'number' ? c.endFrame : (idx + 1) * 20,
              highlightWord: c.highlightWord,
            }))
          : fallbackPreset.captions
      );
    } else {
      setProductTitle(fallbackPreset.productTitle);
      setBrandName(fallbackPreset.brandName);
      setCurrency(fallbackPreset.currency);
      setPriceDisplay(fallbackPreset.priceDisplay);
      setHookText(fallbackPreset.hookText);
      setCtaText(fallbackPreset.ctaText);
      setCaptions(fallbackPreset.captions);
    }
    setIsProductEmpty(false);
  }, []);

  // Credit Top-Up Checkout
  const handleCheckoutCredits = useCallback(
    async (creditsToAdd: number, packId: string) => {
      setIsCheckingOutPackId(packId);
      setCreditsError(null);
      try {
        const response = await fetch(
          `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/credits`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              credits: creditsToAdd,
              pack_id: packId,
            }),
          }
        );
        if (!response.ok) {
          throw new Error(`Checkout failed with status ${response.status}`);
        }
        const updated = (await response.json()) as WorkspaceInfo;
        setCreditBalance(updated.credit_balance);
        if (updated.ledger) {
          setLedger(updated.ledger);
        }
        setBannerMessage(
          `Added +${creditsToAdd} credits (${packId}) — New balance: ${updated.credit_balance} credits.`
        );
      } catch (err) {
        setCreditsError(
          err instanceof Error ? err.message : 'Credit checkout failed'
        );
      } finally {
        setIsCheckingOutPackId(null);
      }
    },
    [workspaceId]
  );

  const activeJob = useMemo(
    () => jobs.find((item) => item.id === activeJobId) ?? null,
    [jobs, activeJobId]
  );

  const completedJobsCount = useMemo(
    () => jobs.filter((item) => item.status === 'COMPLETED').length,
    [jobs]
  );

  // Build live LocalizedAdProps for the Remotion Player
  const liveAdProps: LocalizedAdProps = useMemo(
    () =>
      getPresetAdProps(targetLanguage, adAngle, {
        jobId: activeJobId ?? 'live_studio_preview',
        language: targetLanguage,
        adAngle,
        productTitle: productTitle || initialPreset.productTitle,
        brandName: brandName || initialPreset.brandName,
        currency: currency || initialPreset.currency,
        priceDisplay: priceDisplay || initialPreset.priceDisplay,
        originalPriceDisplay:
          originalPriceDisplay || initialPreset.originalPriceDisplay,
        discountBadge: discountBadge || initialPreset.discountBadge,
        hookText: hookText || initialPreset.hookText,
        ctaText: ctaText || initialPreset.ctaText,
        captions: captions.length > 0 ? captions : initialPreset.captions,
      }),
    [
      targetLanguage,
      adAngle,
      activeJobId,
      productTitle,
      brandName,
      currency,
      priceDisplay,
      originalPriceDisplay,
      discountBadge,
      hookText,
      ctaText,
      captions,
      initialPreset,
    ]
  );

  return (
    <div className="min-h-screen bg-[#09090B] text-[#FAFAFA]">
      {/* Top Studio Header Bar */}
      <StudioHeader
        workspaceId={workspaceId}
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
        }}
      />

      {/* Main Studio Container (Strictly max-w-[1200px], spacing scale 4/8/12/16/24/32px) */}
      <main className="mx-auto flex max-w-[1200px] flex-col gap-6 px-6 py-6">
        {/* Status Notification Strip */}
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

        {/* Top Workspace Row: Left 360px Input Panel + Center 9:16 Remotion Player Preview */}
        <div className="flex flex-col items-stretch gap-6 lg:flex-row">
          <ProductScraperPanel
            productUrl={productUrl}
            onChangeProductUrl={setProductUrl}
            targetLanguage={targetLanguage}
            onChangeLanguage={handleLanguageChange}
            adAngle={adAngle}
            onChangeAdAngle={handleAdAngleChange}
            productTitle={productTitle}
            onChangeProductTitle={setProductTitle}
            brandName={brandName}
            onChangeBrandName={setBrandName}
            priceDisplay={priceDisplay}
            onChangePriceDisplay={setPriceDisplay}
            discountBadge={discountBadge}
            onChangeDiscountBadge={setDiscountBadge}
            hookText={hookText}
            onChangeHookText={setHookText}
            ctaText={ctaText}
            onChangeCtaText={setCtaText}
            captions={captions}
            onChangeCaptionText={handleCaptionTextChange}
            onChangeCaptionHighlight={handleCaptionHighlightChange}
            isScraping={isScraping}
            scrapeError={scrapeError}
            isProductEmpty={isProductEmpty}
            onScrapeUrl={(overrideUrl) => {
              void handleScrapeUrl(overrideUrl);
            }}
            onClearProduct={handleClearProduct}
            onLoadDefaultPreset={handleLoadDefaultPreset}
            isGenerating={isGenerating}
            creditBalance={creditBalance}
            onGenerateVideo={() => {
              void handleGenerateVideo(false);
            }}
            onOpenCreditModal={() => setIsCreditModalOpen(true)}
            viewStateMode={viewStateMode}
          />

          <RemotionPreviewStage
            adProps={liveAdProps}
            activeJob={activeJob}
            viewStateMode={viewStateMode}
            onGenerateVideo={() => {
              void handleGenerateVideo(false);
            }}
          />
        </div>

        {/* Bottom Render Queue Strip & MP4 Download Gallery */}
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
          onGenerateFirstJob={() => {
            setViewStateMode('normal');
            void handleGenerateVideo(false);
          }}
          onClearLocalJobs={() => {
            setJobs([]);
            setActiveJobId(null);
          }}
          onTriggerTestFailureJob={() => {
            void handleGenerateVideo(true);
          }}
        />
      </main>

      {/* Credit Checkout & Atomic Credit Ledger Modal */}
      <CreditCheckoutModal
        isOpen={isCreditModalOpen}
        onClose={() => setIsCreditModalOpen(false)}
        workspaceId={workspaceId}
        creditBalance={creditBalance}
        ledger={ledger}
        isLoadingCredits={isLoadingCredits}
        isCheckingOutPackId={isCheckingOutPackId}
        creditsError={creditsError}
        viewStateMode={viewStateMode}
        onCheckoutCredits={(credits, packId) => {
          void handleCheckoutCredits(credits, packId);
        }}
        onRetryFetchCredits={() => {
          setViewStateMode('normal');
          void fetchWorkspaceCredits();
        }}
      />
    </div>
  );
};
