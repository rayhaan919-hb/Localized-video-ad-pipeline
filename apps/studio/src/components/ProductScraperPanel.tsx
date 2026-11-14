'use client';

import React, { useRef } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Globe,
  ImagePlus,
  Link2,
  PackageSearch,
  RotateCcw,
  Sparkles,
  Tag,
  Type,
  Wand2,
} from 'lucide-react';
import {
  AD_ANGLES,
  LANGUAGE_FONT_METADATA,
  SUPPORTED_LANGUAGES,
  type AdAngle,
  type CaptionSegment,
  type SupportedLanguage,
} from '@video-ad/remotion';
import type {
  ScrapedProductMetadata,
  ViewStateMode,
  WorkspaceAssetItem,
} from '@/types/studio';

interface ProductScraperPanelProps {
  productUrl: string;
  onChangeProductUrl: (url: string) => void;
  targetLanguage: SupportedLanguage;
  onChangeLanguage: (lang: SupportedLanguage) => void;
  adAngle: AdAngle;
  onChangeAdAngle: (angle: AdAngle) => void;
  aspectRatio: '9:16' | '16:9';
  onChangeAspectRatio: (ratio: '9:16' | '16:9') => void;
  durationSeconds: number;
  onChangeDurationSeconds: (dur: number) => void;
  productTitle: string;
  onChangeProductTitle: (title: string) => void;
  brandName: string;
  onChangeBrandName: (brand: string) => void;
  priceDisplay: string;
  onChangePriceDisplay: (price: string) => void;
  originalPriceDisplay: string;
  onChangeOriginalPriceDisplay: (origPrice: string) => void;
  discountBadge: string;
  onChangeDiscountBadge: (badge: string) => void;
  productImageUrl: string;
  onChangeProductImageUrl: (url: string) => void;
  selectedAssetId: string;
  onChangeSelectedAssetId: (assetId: string) => void;
  workspaceAssets: WorkspaceAssetItem[];
  isUploadingAsset: boolean;
  assetUploadError: string | null;
  onUploadProductAsset: (file: File) => void;
  hookText: string;
  onChangeHookText: (hook: string) => void;
  ctaText: string;
  onChangeCtaText: (cta: string) => void;
  captions: CaptionSegment[];
  onChangeCaptionText: (index: number, text: string) => void;
  onChangeCaptionHighlight: (index: number, highlightWord: string) => void;
  isScraping: boolean;
  scrapeError: string | null;
  scrapeMetadata: ScrapedProductMetadata | null;
  fieldsConfirmed: boolean;
  onChangeFieldsConfirmed: (confirmed: boolean) => void;
  isProductEmpty: boolean;
  onScrapeUrl: (overrideUrl?: string) => void;
  onClearProduct: () => void;
  onLoadDefaultPreset: () => void;
  isGenerating: boolean;
  creditBalance: number;
  isAuthenticated: boolean;
  onGenerateVideo: () => void;
  onOpenCreditModal: () => void;
  viewStateMode: ViewStateMode;
}

const SAMPLE_STORE_URLS = [
  {
    id: 'example-product',
    label: 'Example Store URL',
    url: 'https://example.com/products/vitamin-c-glow-serum',
  },
];

const ANGLE_UI_LABELS: Record<AdAngle, { title: string; tag: string }> = {
  problem_solution: { title: 'Problem → Solution', tag: 'PAIN + FIX' },
  ugc_testimonial: { title: 'UGC Review', tag: 'SOCIAL PROOF' },
  flash_sale: { title: 'Flash Sale Offer', tag: 'URGENCY' },
  unboxing: { title: 'Unboxing Reveal', tag: 'FIRST LOOK' },
};

export const ProductScraperPanel: React.FC<ProductScraperPanelProps> = ({
  productUrl,
  onChangeProductUrl,
  targetLanguage,
  onChangeLanguage,
  adAngle,
  onChangeAdAngle,
  aspectRatio,
  onChangeAspectRatio,
  durationSeconds,
  onChangeDurationSeconds,
  productTitle,
  onChangeProductTitle,
  brandName,
  onChangeBrandName,
  priceDisplay,
  onChangePriceDisplay,
  originalPriceDisplay,
  onChangeOriginalPriceDisplay,
  discountBadge,
  onChangeDiscountBadge,
  productImageUrl,
  onChangeProductImageUrl,
  selectedAssetId,
  onChangeSelectedAssetId,
  workspaceAssets,
  isUploadingAsset,
  assetUploadError,
  onUploadProductAsset,
  hookText,
  onChangeHookText,
  ctaText,
  onChangeCtaText,
  captions,
  onChangeCaptionText,
  onChangeCaptionHighlight,
  isScraping,
  scrapeError,
  scrapeMetadata,
  fieldsConfirmed,
  onChangeFieldsConfirmed,
  isProductEmpty,
  onScrapeUrl,
  onClearProduct,
  onLoadDefaultPreset,
  isGenerating,
  creditBalance,
  isAuthenticated,
  onGenerateVideo,
  onOpenCreditModal,
  viewStateMode,
}) => {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const fontMeta = LANGUAGE_FONT_METADATA[targetLanguage];
  const showSkeleton = isScraping || viewStateMode === 'loading';
  const showError = Boolean(scrapeError) || viewStateMode === 'error';
  const showEmpty =
    (!showSkeleton && isProductEmpty) || viewStateMode === 'empty';

  const hasRequiredFacts =
    Boolean(productTitle.trim()) &&
    Boolean(brandName.trim()) &&
    Boolean(priceDisplay.trim());

  const canDispatchRender =
    isAuthenticated &&
    !isGenerating &&
    !isProductEmpty &&
    hasRequiredFacts &&
    fieldsConfirmed &&
    creditBalance >= 1;

  const scriptClassName =
    targetLanguage === 'ur'
      ? 'font-script-ur'
      : targetLanguage === 'ar'
      ? 'font-script-ar'
      : targetLanguage === 'hi'
      ? 'font-script-hi'
      : 'font-script-en';

  return (
    <aside
      aria-label="Product URL Scraper and Localized Script Controls"
      className="w-full shrink-0 rounded border border-[#27272A] bg-[#18181B] p-4 lg:w-[360px]"
    >
      <div className="flex flex-col gap-4">
        {/* Panel Title Row */}
        <div className="flex items-center justify-between border-b border-[#27272A] pb-3">
          <div className="flex items-center gap-2">
            <Link2 className="h-4 w-4 text-[#6366F1]" />
            <h2 className="text-sm font-semibold text-[#FAFAFA]">
              1. Product & Localization
            </h2>
          </div>
          <span className="font-mono-code tabular-nums rounded border border-[#27272A] bg-[#09090B] px-2 py-0.5 text-[11px] text-[#A1A1AA]">
            {aspectRatio}
          </span>
        </div>

        {/* Product URL Input & Scraper Trigger */}
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <label
              htmlFor="product-url-input"
              className="text-xs font-medium text-[#FAFAFA]"
            >
              D2C Product URL (SSRF-Guarded Live Fetch)
            </label>
            <button
              type="button"
              onClick={onClearProduct}
              className="text-[11px] text-[#A1A1AA] underline-offset-2 hover:text-[#FAFAFA] hover:underline"
            >
              Clear fields
            </button>
          </div>

          <div className="flex gap-2">
            <input
              id="product-url-input"
              type="url"
              value={productUrl}
              onChange={(e) => onChangeProductUrl(e.target.value)}
              placeholder="https://yourstore.com/products/serum"
              className="font-mono-code min-w-0 flex-1 rounded border border-[#27272A] bg-[#09090B] px-3 py-2 text-xs text-[#FAFAFA] placeholder-[#A1A1AA]/50 focus:border-[#6366F1] focus:outline-none"
            />
            <button
              type="button"
              onClick={() => onScrapeUrl()}
              disabled={isScraping || !isAuthenticated}
              className="shrink-0 rounded border border-[#6366F1] bg-[#6366F1] px-3 py-2 text-xs font-semibold text-[#FAFAFA] transition-colors hover:bg-[#5254E8] disabled:opacity-50"
            >
              {isScraping ? 'Fetching…' : 'Fetch URL'}
            </button>
          </div>

          <div className="flex flex-wrap gap-1 pt-0.5">
            {SAMPLE_STORE_URLS.map((sample) => (
              <button
                key={sample.id}
                type="button"
                onClick={() => onChangeProductUrl(sample.url)}
                className="rounded border border-[#27272A] bg-[#09090B] px-2 py-0.5 text-[10px] text-[#A1A1AA] hover:border-[#6366F1] hover:text-[#FAFAFA]"
              >
                Use {sample.label}
              </button>
            ))}
          </div>
        </div>

        {/* Honest Extraction Telemetry Banner */}
        {scrapeMetadata ? (
          <div className="flex flex-col gap-1.5 rounded border border-[#27272A] bg-[#09090B] p-2.5 text-[11px]">
            <div className="flex items-center justify-between">
              <span className="font-mono-code font-semibold text-[#FAFAFA]">
                SCRAPE STATUS: {(scrapeMetadata.scrape_status ?? 'ok').toUpperCase()}
              </span>
              {scrapeMetadata.requires_user_confirmation ? (
                <span className="font-mono-code text-amber-400">
                  CONFIRM REQUIRED
                </span>
              ) : (
                <span className="font-mono-code text-emerald-400">VERIFIED</span>
              )}
            </div>
            {scrapeMetadata.verified_fields &&
            scrapeMetadata.verified_fields.length > 0 ? (
              <p className="text-[#A1A1AA]">
                Verified: {scrapeMetadata.verified_fields.join(', ')}
              </p>
            ) : null}
            {scrapeMetadata.missing_fields &&
            scrapeMetadata.missing_fields.length > 0 ? (
              <p className="text-amber-300">
                Missing / unverified:{' '}
                {scrapeMetadata.missing_fields.join(', ')} — enter exact store values below.
              </p>
            ) : null}
          </div>
        ) : null}

        {/* Inline Error Banner with Retry Button */}
        {showError ? (
          <div
            role="alert"
            className="flex flex-col gap-2 rounded border border-red-500/60 bg-[#09090B] p-3"
          >
            <div className="flex items-start gap-2">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-red-400" />
              <div className="flex-1">
                <p className="text-xs font-semibold text-[#FAFAFA]">
                  Product Metadata Extraction Failed
                </p>
                <p className="mt-0.5 text-xs text-[#A1A1AA]">
                  {scrapeError ??
                    'Remote storefront failed to respond with verified OpenGraph/JSON-LD metadata.'}
                </p>
              </div>
            </div>
            <div className="flex justify-end">
              <button
                type="button"
                onClick={() => onScrapeUrl()}
                className="flex items-center gap-1.5 rounded border border-[#27272A] bg-[#18181B] px-3 py-1 text-xs font-semibold text-[#FAFAFA] hover:border-[#6366F1]"
              >
                <RotateCcw className="h-3 w-3 text-[#6366F1]" />
                <span>Retry</span>
              </button>
            </div>
          </div>
        ) : null}

        {/* Target Language Selector */}
        <div className="flex flex-col gap-2 border-t border-[#27272A] pt-3">
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-1.5 text-xs font-medium text-[#FAFAFA]">
              <Globe className="h-3.5 w-3.5 text-[#6366F1]" />
              <span>Target Language</span>
            </span>
            <span className="font-mono-code tabular-nums rounded border border-[#27272A] bg-[#09090B] px-2 py-0.5 text-[11px] text-[#A1A1AA]">
              {fontMeta.dir.toUpperCase()} · {fontMeta.fontFamily}
            </span>
          </div>

          <div className="grid grid-cols-2 gap-2">
            {SUPPORTED_LANGUAGES.map((lang) => {
              const meta = LANGUAGE_FONT_METADATA[lang];
              const active = targetLanguage === lang;
              return (
                <button
                  key={lang}
                  type="button"
                  onClick={() => onChangeLanguage(lang)}
                  className={`flex flex-col items-start justify-between rounded border p-2.5 text-left transition-colors ${
                    active
                      ? 'border-[#6366F1] bg-[#09090B] text-[#FAFAFA]'
                      : 'border-[#27272A] bg-[#09090B] text-[#A1A1AA] hover:border-[#FAFAFA]/40 hover:text-[#FAFAFA]'
                  }`}
                >
                  <div className="flex w-full items-center justify-between">
                    <span className="text-xs font-semibold text-[#FAFAFA]">
                      {meta.nativeLabel}
                    </span>
                    <span
                      className={`font-mono-code rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                        active
                          ? 'bg-[#6366F1] text-[#FAFAFA]'
                          : 'border border-[#27272A] text-[#A1A1AA]'
                      }`}
                    >
                      {lang.toUpperCase()} · {meta.dir.toUpperCase()}
                    </span>
                  </div>
                  <span className="mt-1 text-[11px] text-[#A1A1AA]">
                    {meta.regionLabel}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Aspect Ratio & Duration + Ad Angle */}
        <div className="flex flex-col gap-2 border-t border-[#27272A] pt-3">
          <div className="grid grid-cols-2 gap-2">
            <div className="flex flex-col gap-1">
              <span className="text-[11px] text-[#A1A1AA]">Aspect Ratio</span>
              <div className="grid grid-cols-2 gap-1 rounded border border-[#27272A] bg-[#09090B] p-1">
                {(['9:16', '16:9'] as const).map((ratio) => (
                  <button
                    key={ratio}
                    type="button"
                    onClick={() => onChangeAspectRatio(ratio)}
                    className={`font-mono-code rounded py-1 text-[11px] font-medium ${
                      aspectRatio === ratio
                        ? 'bg-[#6366F1] text-[#FAFAFA]'
                        : 'text-[#A1A1AA] hover:text-[#FAFAFA]'
                    }`}
                  >
                    {ratio}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex flex-col gap-1">
              <span className="text-[11px] text-[#A1A1AA]">Clip Duration</span>
              <div className="grid grid-cols-3 gap-1 rounded border border-[#27272A] bg-[#09090B] p-1">
                {([4, 6, 8] as const).map((sec) => (
                  <button
                    key={sec}
                    type="button"
                    onClick={() => onChangeDurationSeconds(sec)}
                    className={`font-mono-code rounded py-1 text-[11px] font-medium ${
                      durationSeconds === sec
                        ? 'bg-[#6366F1] text-[#FAFAFA]'
                        : 'text-[#A1A1AA] hover:text-[#FAFAFA]'
                    }`}
                  >
                    {sec}s
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="flex items-center justify-between pt-1">
            <span className="flex items-center gap-1.5 text-xs font-medium text-[#FAFAFA]">
              <Tag className="h-3.5 w-3.5 text-[#6366F1]" />
              <span>D2C Ad Angle</span>
            </span>
          </div>

          <div className="grid grid-cols-2 gap-2">
            {AD_ANGLES.map((angle) => {
              const active = adAngle === angle;
              const info = ANGLE_UI_LABELS[angle];
              return (
                <button
                  key={angle}
                  type="button"
                  onClick={() => onChangeAdAngle(angle)}
                  className={`flex flex-col items-start rounded border p-2 text-left transition-colors ${
                    active
                      ? 'border-[#6366F1] bg-[#09090B] text-[#FAFAFA]'
                      : 'border-[#27272A] bg-[#09090B] text-[#A1A1AA] hover:border-[#FAFAFA]/40 hover:text-[#FAFAFA]'
                  }`}
                >
                  <span className="text-xs font-semibold text-[#FAFAFA]">
                    {info.title}
                  </span>
                  <span className="font-mono-code mt-0.5 text-[10px] text-[#A1A1AA]">
                    {info.tag}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Product Assets & Metadata Editor */}
        <div className="border-t border-[#27272A] pt-3">
          {showSkeleton ? (
            <div
              data-testid="scraper-skeleton"
              className="flex flex-col gap-3 rounded border border-[#27272A] bg-[#09090B] p-3"
            >
              <div className="h-3.5 w-28 animate-pulse rounded bg-[#27272A]" />
              <div className="grid grid-cols-2 gap-2">
                <div className="h-9 animate-pulse rounded border border-[#27272A] bg-[#18181B]" />
                <div className="h-9 animate-pulse rounded border border-[#27272A] bg-[#18181B]" />
              </div>
              <div className="h-16 w-full animate-pulse rounded border border-[#27272A] bg-[#18181B]" />
            </div>
          ) : showEmpty ? (
            <div
              data-testid="scraper-empty-state"
              className="flex flex-col items-center justify-center gap-3 rounded border border-[#27272A] bg-[#09090B] p-6 text-center"
            >
              <div className="flex h-10 w-10 items-center justify-center rounded border border-[#27272A] bg-[#18181B]">
                <PackageSearch className="h-5 w-5 text-[#6366F1]" />
              </div>
              <p className="text-xs text-[#A1A1AA]">
                No script draft loaded. Fetch a live storefront URL above or
                load localized copy scaffolding.
              </p>
              <button
                type="button"
                onClick={onLoadDefaultPreset}
                className="rounded border border-[#6366F1] bg-[#6366F1] px-3 py-1.5 text-xs font-semibold text-[#FAFAFA] transition-colors hover:bg-[#5254E8]"
              >
                Load Localized Copy Template
              </button>
            </div>
          ) : (
            <div className="flex flex-col gap-3">
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-1.5 text-xs font-medium text-[#FAFAFA]">
                  <Type className="h-3.5 w-3.5 text-[#6366F1]" />
                  <span>Confirmed Facts & Localized Script</span>
                </span>
              </div>

              {/* Brand & Price Row */}
              <div className="grid grid-cols-2 gap-2">
                <div className="flex flex-col gap-1">
                  <label
                    htmlFor="brand-name-input"
                    className="text-[11px] text-[#A1A1AA]"
                  >
                    Brand Name *
                  </label>
                  <input
                    id="brand-name-input"
                    type="text"
                    value={brandName}
                    placeholder="Verified brand"
                    onChange={(e) => onChangeBrandName(e.target.value)}
                    className="rounded border border-[#27272A] bg-[#09090B] px-2.5 py-1.5 text-xs text-[#FAFAFA] focus:border-[#6366F1] focus:outline-none"
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <label
                    htmlFor="price-display-input"
                    className="text-[11px] text-[#A1A1AA]"
                  >
                    Verified Price *
                  </label>
                  <input
                    id="price-display-input"
                    type="text"
                    value={priceDisplay}
                    placeholder="e.g. PKR 4,990"
                    onChange={(e) => onChangePriceDisplay(e.target.value)}
                    className="font-mono-code tabular-nums rounded border border-[#27272A] bg-[#09090B] px-2.5 py-1.5 text-xs text-[#FAFAFA] focus:border-[#6366F1] focus:outline-none"
                  />
                </div>
              </div>

              {/* Product Title & Optional Compare/Promo Row */}
              <div className="grid grid-cols-3 gap-2">
                <div className="col-span-2 flex flex-col gap-1">
                  <label
                    htmlFor="product-title-input"
                    className="text-[11px] text-[#A1A1AA]"
                  >
                    Product Title *
                  </label>
                  <input
                    id="product-title-input"
                    type="text"
                    dir={fontMeta.dir}
                    value={productTitle}
                    placeholder="Product name"
                    onChange={(e) => onChangeProductTitle(e.target.value)}
                    className={`${scriptClassName} rounded border border-[#27272A] bg-[#09090B] px-2.5 py-1.5 text-xs text-[#FAFAFA] focus:border-[#6366F1] focus:outline-none`}
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <label
                    htmlFor="discount-badge-input"
                    className="text-[11px] text-[#A1A1AA]"
                  >
                    Promo Tag
                  </label>
                  <input
                    id="discount-badge-input"
                    type="text"
                    value={discountBadge}
                    placeholder="Optional"
                    onChange={(e) => onChangeDiscountBadge(e.target.value)}
                    className="font-mono-code tabular-nums rounded border border-[#27272A] bg-[#09090B] px-2.5 py-1.5 text-xs text-[#FAFAFA] focus:border-[#6366F1] focus:outline-none"
                  />
                </div>
              </div>

              <div className="flex flex-col gap-1">
                <label
                  htmlFor="orig-price-input"
                  className="text-[11px] text-[#A1A1AA]"
                >
                  Original Compare-At Price (optional)
                </label>
                <input
                  id="orig-price-input"
                  type="text"
                  value={originalPriceDisplay}
                  placeholder="Leave blank if none"
                  onChange={(e) =>
                    onChangeOriginalPriceDisplay(e.target.value)
                  }
                  className="font-mono-code rounded border border-[#27272A] bg-[#09090B] px-2.5 py-1.5 text-xs text-[#FAFAFA] focus:border-[#6366F1] focus:outline-none"
                />
              </div>

              {/* Product Visual Conditioning: URL or Uploaded Workspace Asset */}
              <div className="flex flex-col gap-2 rounded border border-[#27272A] bg-[#09090B] p-2.5">
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-1.5 text-[11px] font-medium text-[#FAFAFA]">
                    <ImagePlus className="h-3.5 w-3.5 text-[#6366F1]" />
                    <span>Product Image / Asset</span>
                  </span>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept="image/png,image/jpeg,image/webp"
                    className="hidden"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) {
                        onUploadProductAsset(file);
                        e.target.value = '';
                      }
                    }}
                  />
                  <button
                    type="button"
                    disabled={isUploadingAsset || !isAuthenticated}
                    onClick={() => fileInputRef.current?.click()}
                    className="rounded border border-[#27272A] bg-[#18181B] px-2 py-0.5 text-[10px] font-medium text-[#FAFAFA] hover:border-[#6366F1] disabled:opacity-50"
                  >
                    {isUploadingAsset ? 'Uploading…' : 'Upload PNG/JPG'}
                  </button>
                </div>

                {assetUploadError ? (
                  <p className="text-[11px] text-red-400">{assetUploadError}</p>
                ) : null}

                {workspaceAssets.length > 0 ? (
                  <select
                    aria-label="Workspace Uploaded Product Asset"
                    value={selectedAssetId}
                    onChange={(e) => onChangeSelectedAssetId(e.target.value)}
                    className="font-mono-code rounded border border-[#27272A] bg-[#18181B] px-2 py-1 text-[11px] text-[#FAFAFA]"
                  >
                    <option value="">-- Optional: Select uploaded asset --</option>
                    {workspaceAssets.map((asset) => (
                      <option key={asset.id} value={asset.id}>
                        {asset.filename} ({Math.round(asset.size_bytes / 1024)} KB)
                      </option>
                    ))}
                  </select>
                ) : null}

                <input
                  type="url"
                  value={productImageUrl}
                  onChange={(e) => onChangeProductImageUrl(e.target.value)}
                  placeholder="https://... extracted or direct product image URL"
                  className="font-mono-code rounded border border-[#27272A] bg-[#18181B] px-2 py-1 text-[11px] text-[#FAFAFA] focus:border-[#6366F1] focus:outline-none"
                />

                {scrapeMetadata?.image_candidates &&
                scrapeMetadata.image_candidates.length > 0 ? (
                  <div className="flex flex-wrap gap-1">
                    {scrapeMetadata.image_candidates.slice(0, 4).map((cand, i) => (
                      <button
                        key={cand}
                        type="button"
                        onClick={() => onChangeProductImageUrl(cand)}
                        className={`font-mono-code rounded border px-1.5 py-0.5 text-[10px] ${
                          productImageUrl === cand
                            ? 'border-[#6366F1] text-[#FAFAFA]'
                            : 'border-[#27272A] text-[#A1A1AA]'
                        }`}
                      >
                        Candidate #{i + 1}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>

              {/* Opening Hook Headline */}
              <div className="flex flex-col gap-1">
                <label
                  htmlFor="hook-text-input"
                  className="text-[11px] text-[#A1A1AA]"
                >
                  Opening Hook ({fontMeta.dir.toUpperCase()})
                </label>
                <textarea
                  id="hook-text-input"
                  rows={2}
                  dir={fontMeta.dir}
                  value={hookText}
                  onChange={(e) => onChangeHookText(e.target.value)}
                  className={`${scriptClassName} rounded border border-[#27272A] bg-[#09090B] px-2.5 py-1.5 text-xs text-[#FAFAFA] focus:border-[#6366F1] focus:outline-none`}
                />
              </div>

              {/* Animated Captions */}
              <div className="flex flex-col gap-2">
                <span className="text-[11px] text-[#A1A1AA]">
                  Animated Captions & Highlight Words
                </span>
                {captions.map((cap, idx) => (
                  <div
                    key={cap.id}
                    className="flex flex-col gap-1.5 rounded border border-[#27272A] bg-[#09090B] p-2"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-mono-code tabular-nums text-[10px] font-semibold text-[#6366F1]">
                        SEG #{idx + 1} · {cap.startFrame}F–{cap.endFrame}F
                      </span>
                      <input
                        type="text"
                        dir={fontMeta.dir}
                        value={cap.highlightWord ?? ''}
                        onChange={(e) =>
                          onChangeCaptionHighlight(idx, e.target.value)
                        }
                        placeholder="Highlight word"
                        aria-label={`Caption ${idx + 1} highlight word`}
                        className={`${scriptClassName} w-28 rounded border border-[#27272A] bg-[#18181B] px-2 py-0.5 text-[11px] text-[#FAFAFA] focus:border-[#6366F1] focus:outline-none`}
                      />
                    </div>
                    <input
                      type="text"
                      dir={fontMeta.dir}
                      value={cap.text}
                      onChange={(e) => onChangeCaptionText(idx, e.target.value)}
                      aria-label={`Caption ${idx + 1} text`}
                      className={`${scriptClassName} w-full rounded border border-[#27272A] bg-[#18181B] px-2 py-1 text-xs text-[#FAFAFA] focus:border-[#6366F1] focus:outline-none`}
                    />
                  </div>
                ))}
              </div>

              {/* CTA Text */}
              <div className="flex flex-col gap-1">
                <label
                  htmlFor="cta-text-input"
                  className="text-[11px] text-[#A1A1AA]"
                >
                  Bottom Dock CTA Text
                </label>
                <input
                  id="cta-text-input"
                  type="text"
                  dir={fontMeta.dir}
                  value={ctaText}
                  onChange={(e) => onChangeCtaText(e.target.value)}
                  className={`${scriptClassName} rounded border border-[#27272A] bg-[#09090B] px-2.5 py-1.5 text-xs text-[#FAFAFA] focus:border-[#6366F1] focus:outline-none`}
                />
              </div>

              {/* Mandatory Storefront Truth Confirmation */}
              <label className="flex cursor-pointer items-start gap-2 rounded border border-[#27272A] bg-[#09090B] p-2.5 text-[11px] text-[#FAFAFA]">
                <input
                  type="checkbox"
                  checked={fieldsConfirmed}
                  onChange={(e) => onChangeFieldsConfirmed(e.target.checked)}
                  className="mt-0.5 h-3.5 w-3.5 accent-[#6366F1]"
                />
                <span>
                  I confirm the brand, title, price, and ad copy accurately match
                  my product before rendering.
                </span>
              </label>
            </div>
          )}
        </div>

        {/* Primary Action */}
        <div className="flex flex-col gap-2 border-t border-[#27272A] pt-3">
          {creditBalance < 1 ? (
            <button
              type="button"
              disabled={!isAuthenticated}
              onClick={onOpenCreditModal}
              className="flex w-full items-center justify-center gap-2 rounded border border-red-500/80 bg-[#09090B] px-4 py-2.5 text-xs font-semibold text-[#FAFAFA] transition-colors hover:border-[#6366F1] disabled:opacity-50"
            >
              <Sparkles className="h-4 w-4 text-[#6366F1]" />
              <span className="tabular-nums">
                0 Credits Remaining — Buy Credits
              </span>
            </button>
          ) : (
            <button
              type="button"
              onClick={onGenerateVideo}
              disabled={!canDispatchRender}
              className="flex w-full items-center justify-center gap-2 rounded border border-[#6366F1] bg-[#6366F1] px-4 py-2.5 text-xs font-semibold text-[#FAFAFA] transition-colors hover:bg-[#5254E8] disabled:opacity-50"
            >
              <Wand2 className="h-4 w-4" />
              <span className="tabular-nums">
                {isGenerating
                  ? 'Dispatching Veo 3.1 + Remotion Job…'
                  : !hasRequiredFacts
                  ? 'Enter Brand, Title & Price First'
                  : !fieldsConfirmed
                  ? 'Confirm Facts Above to Generate'
                  : `Generate ${aspectRatio} Video Ad (1 Credit)`}
              </span>
            </button>
          )}

          <div className="flex items-center justify-between text-[11px] text-[#A1A1AA]">
            <span className="flex items-center gap-1">
              <CheckCircle2 className="h-3 w-3 text-[#6366F1]" />
              Atomic Credit Reservation
            </span>
            <span className="font-mono-code tabular-nums">
              veo-3.1-generate-001
            </span>
          </div>
        </div>
      </div>
    </aside>
  );
};
