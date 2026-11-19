'use client';

import React, { useRef, useState } from 'react';
import {
  AlertTriangle,
  ImagePlus,
  PackageSearch,
  RotateCcw,
  Sparkles,
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
  customPrompt: string;
  onChangeCustomPrompt: (prompt: string) => void;
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

const ANGLE_UI_LABELS: Record<AdAngle, string> = {
  problem_solution: 'Problem → Solution',
  ugc_testimonial: 'UGC Review',
  flash_sale: 'Flash Sale',
  unboxing: 'Unboxing',
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
  customPrompt,
  onChangeCustomPrompt,
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
  const [touched, setTouched] = useState<Record<string, boolean>>({});

  const markTouched = (field: string) =>
    setTouched((prev) => ({ ...prev, [field]: true }));

  const urlInvalid = Boolean(
    touched.productUrl &&
      productUrl.trim() &&
      !/^https?:\/\/.+/i.test(productUrl.trim())
  );
  const brandInvalid = Boolean(touched.brandName && !brandName.trim());
  const priceInvalid = Boolean(touched.priceDisplay && !priceDisplay.trim());
  const titleInvalid = Boolean(touched.productTitle && !productTitle.trim());

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
      aria-label="Create Video Ad Controls"
      className="w-full min-w-0 shrink-0 rounded-2xl border border-[#E6E0D5] bg-white p-5 shadow-[0_1px_2px_rgba(28,25,23,0.04)] lg:w-[372px]"
    >
      <div className="flex flex-col gap-5">
        {/* Panel Title Row */}
        <div className="flex items-center justify-between border-b border-[#E6E0D5] pb-3.5">
          <h2 className="text-base font-semibold text-[#1C1917]">
            Create Video Ad
          </h2>
          <button
            type="button"
            onClick={onClearProduct}
            className="min-h-[32px] rounded-full px-3 text-xs font-medium text-[#57534E] transition-colors hover:bg-[#F4EFE6] hover:text-[#1C1917]"
          >
            Clear
          </button>
        </div>

        {/* Product URL Input & Scraper Trigger */}
        <div className="flex flex-col gap-2">
          <label
            htmlFor="product-url-input"
            className="text-xs font-medium text-[#1C1917]"
          >
            Product Storefront URL
          </label>

          <div className="flex gap-2">
            <input
              id="product-url-input"
              type="url"
              value={productUrl}
              onChange={(e) => onChangeProductUrl(e.target.value)}
              onBlur={() => markTouched('productUrl')}
              aria-invalid={urlInvalid}
              aria-describedby={urlInvalid ? 'product-url-error' : undefined}
              placeholder="https://yourstore.com/products/serum"
              className={`min-h-[40px] min-w-0 flex-1 rounded-xl border bg-[#FAF7F2] px-3.5 py-2 text-xs text-[#1C1917] placeholder-[#6E6A63] focus:bg-white focus:outline-none ${
                urlInvalid
                  ? 'border-[#B91C1C]'
                  : 'border-[#D6CEC0] focus:border-[#15803D]'
              }`}
            />
            <button
              type="button"
              onClick={() => onScrapeUrl()}
              disabled={isScraping || !isAuthenticated}
              className="min-h-[40px] shrink-0 rounded-full bg-[#15803D] px-4 py-2 text-xs font-semibold text-white transition-colors hover:bg-[#166534] disabled:opacity-50"
            >
              {isScraping ? 'Fetching…' : 'Fetch'}
            </button>
          </div>

          {urlInvalid ? (
            <p
              id="product-url-error"
              role="alert"
              className="text-[11px] font-medium text-[#B91C1C]"
            >
              Enter a URL starting with https:// or http://
            </p>
          ) : null}

          <div className="flex flex-wrap gap-1.5">
            {SAMPLE_STORE_URLS.map((sample) => (
              <button
                key={sample.id}
                type="button"
                onClick={() => onChangeProductUrl(sample.url)}
                className="min-h-[30px] rounded-full bg-[#F4EFE6] px-3 py-1 text-[11px] font-medium text-[#57534E] transition-colors hover:bg-[#E6E0D5] hover:text-[#1C1917]"
              >
                Use {sample.label}
              </button>
            ))}
          </div>
        </div>

        {/* Scrape Telemetry Banner */}
        {scrapeMetadata ? (
          <div className="flex flex-col gap-1 rounded-xl border border-[#E6E0D5] bg-[#FAF7F2] p-3 text-xs">
            <div className="flex items-center justify-between gap-2">
              <span className="font-semibold text-[#1C1917]">
                Storefront Import
              </span>
              {scrapeMetadata.requires_user_confirmation ? (
                <span className="rounded-full border border-[#FDE68A] bg-[#FFFBEB] px-2.5 py-0.5 text-[10px] font-semibold text-[#92400E]">
                  Review fields
                </span>
              ) : (
                <span className="rounded-full border border-[#BBF7D0] bg-[#F0FDF4] px-2.5 py-0.5 text-[10px] font-semibold text-[#166534]">
                  Verified
                </span>
              )}
            </div>
            {scrapeMetadata.missing_fields &&
            scrapeMetadata.missing_fields.length > 0 ? (
              <p className="text-[11px] text-[#92400E]">
                Check missing fields: {scrapeMetadata.missing_fields.join(', ')}
              </p>
            ) : null}
          </div>
        ) : null}

        {/* Inline Error Banner with Retry Button */}
        {showError ? (
          <div
            role="alert"
            className="flex flex-col gap-2 rounded-xl border border-[#FECACA] bg-[#FEF2F2] p-3"
          >
            <div className="flex items-start gap-2">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-[#B91C1C]" />
              <div className="min-w-0 flex-1">
                <p className="text-xs font-semibold text-[#B91C1C]">
                  Couldn&apos;t import that URL
                </p>
                <p className="mt-0.5 text-xs text-[#57534E]">
                  {scrapeError ??
                    'Enter your product details manually below or try another storefront URL.'}
                </p>
              </div>
            </div>
            <div className="flex justify-end">
              <button
                type="button"
                onClick={() => onScrapeUrl()}
                className="flex min-h-[32px] items-center gap-1.5 rounded-full border border-[#FECACA] bg-white px-3 py-1 text-xs font-semibold text-[#1C1917] hover:border-[#15803D] hover:text-[#166534]"
              >
                <RotateCcw className="h-3 w-3 text-[#166534]" />
                <span>Retry</span>
              </button>
            </div>
          </div>
        ) : null}

        {/* Language, Format, Duration & Ad Style */}
        <div className="flex flex-col gap-3.5 border-t border-[#E6E0D5] pt-4">
          <div className="flex flex-col gap-2">
            <span className="text-xs font-medium text-[#1C1917]">
              Target Language
            </span>
            <div className="grid grid-cols-2 gap-2">
              {SUPPORTED_LANGUAGES.map((lang) => {
                const meta = LANGUAGE_FONT_METADATA[lang];
                const active = targetLanguage === lang;
                return (
                  <button
                    key={lang}
                    type="button"
                    onClick={() => onChangeLanguage(lang)}
                    className={`flex min-h-[42px] items-center justify-between gap-2 rounded-xl border px-3 py-2 text-left transition-colors ${
                      active
                        ? 'border-[#15803D] bg-[#F0FDF4] text-[#166534]'
                        : 'border-[#E6E0D5] bg-[#FAF7F2] text-[#1C1917] hover:border-[#D6CEC0]'
                    }`}
                  >
                    <span className="text-xs font-semibold">
                      {meta.nativeLabel}
                    </span>
                    <span
                      className={`font-mono-code rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                        active
                          ? 'bg-[#15803D] text-white'
                          : 'bg-white text-[#57534E]'
                      }`}
                    >
                      {lang.toUpperCase()}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2.5">
            <div className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-[#1C1917]">Format</span>
              <div className="grid grid-cols-2 gap-1 rounded-full bg-[#F4EFE6] p-1">
                {(['9:16', '16:9'] as const).map((ratio) => (
                  <button
                    key={ratio}
                    type="button"
                    onClick={() => onChangeAspectRatio(ratio)}
                    className={`font-mono-code min-h-[32px] rounded-full py-1 text-xs font-semibold transition-colors ${
                      aspectRatio === ratio
                        ? 'bg-[#15803D] text-white'
                        : 'text-[#57534E] hover:text-[#1C1917]'
                    }`}
                  >
                    {ratio}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-[#1C1917]">
                Duration
              </span>
              <div className="grid grid-cols-3 gap-1 rounded-full bg-[#F4EFE6] p-1">
                {([4, 6, 8] as const).map((sec) => (
                  <button
                    key={sec}
                    type="button"
                    onClick={() => onChangeDurationSeconds(sec)}
                    className={`font-mono-code min-h-[32px] rounded-full py-1 text-xs font-semibold transition-colors ${
                      durationSeconds === sec
                        ? 'bg-[#15803D] text-white'
                        : 'text-[#57534E] hover:text-[#1C1917]'
                    }`}
                  >
                    {sec}s
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-[#1C1917]">Ad Style</span>
            <div className="grid grid-cols-2 gap-2">
              {AD_ANGLES.map((angle) => {
                const active = adAngle === angle;
                return (
                  <button
                    key={angle}
                    type="button"
                    onClick={() => onChangeAdAngle(angle)}
                    className={`flex min-h-[38px] items-center rounded-xl border px-3 py-1.5 text-left text-xs font-medium transition-colors ${
                      active
                        ? 'border-[#15803D] bg-[#F0FDF4] font-semibold text-[#166534]'
                        : 'border-[#E6E0D5] bg-[#FAF7F2] text-[#1C1917] hover:border-[#D6CEC0]'
                    }`}
                  >
                    {ANGLE_UI_LABELS[angle]}
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        {/* Product Details & Collapsible Script Editor */}
        <div className="border-t border-[#E6E0D5] pt-4">
          {showSkeleton ? (
            <div
              data-testid="scraper-skeleton"
              className="flex flex-col gap-3 rounded-xl border border-[#E6E0D5] bg-[#FAF7F2] p-3"
            >
              <div className="h-3.5 w-28 animate-pulse rounded-full bg-[#E6E0D5]" />
              <div className="grid grid-cols-2 gap-2">
                <div className="h-10 animate-pulse rounded-xl bg-[#F4EFE6]" />
                <div className="h-10 animate-pulse rounded-xl bg-[#F4EFE6]" />
              </div>
              <div className="h-16 w-full animate-pulse rounded-xl bg-[#F4EFE6]" />
            </div>
          ) : showEmpty ? (
            <div
              data-testid="scraper-empty-state"
              className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-[#E6E0D5] bg-[#FAF7F2] p-6 text-center"
            >
              <div className="flex h-11 w-11 items-center justify-center rounded-full border border-[#BBF7D0] bg-[#F0FDF4]">
                <PackageSearch className="h-5 w-5 text-[#166534]" />
              </div>
              <p className="text-xs text-[#57534E]">
                No product loaded yet. Import a store URL above or start with a
                ready-to-edit localized template.
              </p>
              <button
                type="button"
                onClick={onLoadDefaultPreset}
                className="min-h-[40px] rounded-full bg-[#15803D] px-4 py-2 text-xs font-semibold text-white transition-colors hover:bg-[#166534]"
              >
                Load Localized Copy Template
              </button>
            </div>
          ) : (
            <div className="flex flex-col gap-3.5">
              {/* Brand & Price Row */}
              <div className="grid grid-cols-2 gap-2.5">
                <div className="flex min-w-0 flex-col gap-1">
                  <label
                    htmlFor="brand-name-input"
                    className="text-xs font-medium text-[#1C1917]"
                  >
                    Brand Name *
                  </label>
                  <input
                    id="brand-name-input"
                    type="text"
                    value={brandName}
                    placeholder="Verified brand"
                    onChange={(e) => onChangeBrandName(e.target.value)}
                    onBlur={() => markTouched('brandName')}
                    aria-invalid={brandInvalid}
                    aria-describedby={
                      brandInvalid ? 'brand-name-error' : undefined
                    }
                    className={`min-h-[40px] w-full rounded-xl border bg-[#FAF7F2] px-3 py-2 text-xs text-[#1C1917] placeholder-[#6E6A63] focus:bg-white focus:outline-none ${
                      brandInvalid
                        ? 'border-[#B91C1C]'
                        : 'border-[#D6CEC0] focus:border-[#15803D]'
                    }`}
                  />
                  {brandInvalid ? (
                    <p
                      id="brand-name-error"
                      role="alert"
                      className="text-[11px] font-medium text-[#B91C1C]"
                    >
                      Enter your brand name
                    </p>
                  ) : null}
                </div>

                <div className="flex min-w-0 flex-col gap-1">
                  <label
                    htmlFor="price-display-input"
                    className="text-xs font-medium text-[#1C1917]"
                  >
                    Verified Price *
                  </label>
                  <input
                    id="price-display-input"
                    type="text"
                    value={priceDisplay}
                    placeholder="e.g. PKR 4,990"
                    onChange={(e) => onChangePriceDisplay(e.target.value)}
                    onBlur={() => markTouched('priceDisplay')}
                    aria-invalid={priceInvalid}
                    aria-describedby={
                      priceInvalid ? 'price-display-error' : undefined
                    }
                    className={`font-mono-code tabular-nums min-h-[40px] w-full rounded-xl border bg-[#FAF7F2] px-3 py-2 text-xs text-[#1C1917] placeholder-[#6E6A63] focus:bg-white focus:outline-none ${
                      priceInvalid
                        ? 'border-[#B91C1C]'
                        : 'border-[#D6CEC0] focus:border-[#15803D]'
                    }`}
                  />
                  {priceInvalid ? (
                    <p
                      id="price-display-error"
                      role="alert"
                      className="text-[11px] font-medium text-[#B91C1C]"
                    >
                      Enter verified price
                    </p>
                  ) : null}
                </div>
              </div>

              {/* Product Title */}
              <div className="flex min-w-0 flex-col gap-1">
                <label
                  htmlFor="product-title-input"
                  className="text-xs font-medium text-[#1C1917]"
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
                  onBlur={() => markTouched('productTitle')}
                  aria-invalid={titleInvalid}
                  aria-describedby={
                    titleInvalid ? 'product-title-error' : undefined
                  }
                  className={`${scriptClassName} min-h-[40px] w-full rounded-xl border bg-[#FAF7F2] px-3 py-2 text-xs text-[#1C1917] placeholder-[#6E6A63] focus:bg-white focus:outline-none ${
                    titleInvalid
                      ? 'border-[#B91C1C]'
                      : 'border-[#D6CEC0] focus:border-[#15803D]'
                  }`}
                />
                {titleInvalid ? (
                  <p
                    id="product-title-error"
                    role="alert"
                    className="text-[11px] font-medium text-[#B91C1C]"
                  >
                    Enter the product name to display in the ad
                  </p>
                ) : null}
              </div>

              {/* Product Image / Asset */}
              <div className="flex flex-col gap-2 rounded-xl border border-[#E6E0D5] bg-[#FAF7F2] p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="flex items-center gap-1.5 text-xs font-medium text-[#1C1917]">
                    <ImagePlus className="h-3.5 w-3.5 text-[#166534]" />
                    <span>Product Image</span>
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
                    className="min-h-[32px] rounded-full border border-[#D6CEC0] bg-white px-3 py-1 text-[11px] font-medium text-[#1C1917] transition-colors hover:border-[#15803D] hover:text-[#166534] disabled:opacity-50"
                  >
                    {isUploadingAsset ? 'Uploading…' : 'Upload PNG/JPG'}
                  </button>
                </div>

                {assetUploadError ? (
                  <p className="text-[11px] font-medium text-[#B91C1C]">
                    {assetUploadError}
                  </p>
                ) : null}

                {workspaceAssets.length > 0 ? (
                  <select
                    aria-label="Workspace Uploaded Product Asset"
                    value={selectedAssetId}
                    onChange={(e) => onChangeSelectedAssetId(e.target.value)}
                    className="min-h-[36px] w-full rounded-xl border border-[#D6CEC0] bg-white px-3 py-1 text-xs text-[#1C1917]"
                  >
                    <option value="">-- Select uploaded asset --</option>
                    {workspaceAssets.map((asset) => (
                      <option key={asset.id} value={asset.id}>
                        {asset.filename} ({Math.round(asset.size_bytes / 1024)}{' '}
                        KB)
                      </option>
                    ))}
                  </select>
                ) : null}

                <input
                  type="url"
                  aria-label="Direct Product Image URL"
                  value={productImageUrl}
                  onChange={(e) => onChangeProductImageUrl(e.target.value)}
                  placeholder="https://... direct product image URL"
                  className="min-h-[38px] w-full rounded-xl border border-[#D6CEC0] bg-white px-3 py-1.5 text-xs text-[#1C1917] placeholder-[#6E6A63] focus:border-[#15803D] focus:outline-none"
                />

                {scrapeMetadata?.image_candidates &&
                scrapeMetadata.image_candidates.length > 0 ? (
                  <div className="flex flex-wrap gap-1.5">
                    {scrapeMetadata.image_candidates.slice(0, 4).map((cand, i) => (
                      <button
                        key={cand}
                        type="button"
                        onClick={() => onChangeProductImageUrl(cand)}
                        className={`min-h-[30px] rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${
                          productImageUrl === cand
                            ? 'border-[#15803D] bg-[#F0FDF4] text-[#166534]'
                            : 'border-[#E6E0D5] bg-white text-[#57534E]'
                        }`}
                      >
                        Image #{i + 1}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>

              {/* Custom Video Prompt & Script Controls — always visible on main menu */}
              <div className="flex flex-col gap-3 rounded-xl border border-[#E6E0D5] bg-[#FAF7F2] p-3.5">
                <div>
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <label
                      htmlFor="custom-prompt-input"
                      className="text-xs font-medium text-[#1C1917]"
                    >
                      Custom Video Prompt
                    </label>
                    <span className="text-[11px] text-[#78716C]">Optional</span>
                  </div>
                  <textarea
                    id="custom-prompt-input"
                    rows={3}
                    maxLength={1500}
                    value={customPrompt}
                    onChange={(e) => onChangeCustomPrompt(e.target.value)}
                    placeholder="Describe camera motion, lighting, scene mood, and visual pacing (sent directly to Veo)..."
                    className="w-full rounded-xl border border-[#E6E0D5] bg-[#FFFFFF] px-3 py-2 text-xs text-[#1C1917] placeholder:text-[#A8A29E] focus:border-[#15803D] focus:outline-none"
                  />
                </div>
                  <div className="grid grid-cols-2 gap-2">
                    <div className="flex flex-col gap-1">
                      <label
                        htmlFor="discount-badge-input"
                        className="text-[11px] font-medium text-[#57534E]"
                      >
                        Promo Tag
                      </label>
                      <input
                        id="discount-badge-input"
                        type="text"
                        value={discountBadge}
                        placeholder="Optional"
                        onChange={(e) => onChangeDiscountBadge(e.target.value)}
                        className="min-h-[36px] w-full rounded-xl border border-[#D6CEC0] bg-white px-2.5 py-1 text-xs text-[#1C1917] placeholder-[#6E6A63] focus:border-[#15803D] focus:outline-none"
                      />
                    </div>
                    <div className="flex flex-col gap-1">
                      <label
                        htmlFor="orig-price-input"
                        className="text-[11px] font-medium text-[#57534E]"
                      >
                        Original Price
                      </label>
                      <input
                        id="orig-price-input"
                        type="text"
                        value={originalPriceDisplay}
                        placeholder="Compare-at"
                        onChange={(e) =>
                          onChangeOriginalPriceDisplay(e.target.value)
                        }
                        className="font-mono-code min-h-[36px] w-full rounded-xl border border-[#D6CEC0] bg-white px-2.5 py-1 text-xs text-[#1C1917] placeholder-[#6E6A63] focus:border-[#15803D] focus:outline-none"
                      />
                    </div>
                  </div>

                  {/* Opening Hook */}
                  <div className="flex flex-col gap-1">
                    <label
                      htmlFor="hook-text-input"
                      className="text-[11px] font-medium text-[#57534E]"
                    >
                      Opening Hook
                    </label>
                    <textarea
                      id="hook-text-input"
                      rows={2}
                      dir={fontMeta.dir}
                      value={hookText}
                      onChange={(e) => onChangeHookText(e.target.value)}
                      className={`${scriptClassName} w-full rounded-xl border border-[#D6CEC0] bg-white px-3 py-2 text-xs text-[#1C1917] focus:border-[#15803D] focus:outline-none`}
                    />
                  </div>

                  {/* Animated Captions */}
                  <div className="flex flex-col gap-2">
                    <span className="text-[11px] font-medium text-[#57534E]">
                      Captions &amp; Highlight Words
                    </span>
                    {captions.map((cap, idx) => (
                      <div
                        key={cap.id}
                        className="flex flex-col gap-1.5 rounded-xl border border-[#E6E0D5] bg-white p-2.5"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="font-mono-code tabular-nums text-[10px] font-semibold text-[#166534]">
                            #{idx + 1} · {cap.startFrame}F–{cap.endFrame}F
                          </span>
                          <input
                            type="text"
                            dir={fontMeta.dir}
                            value={cap.highlightWord ?? ''}
                            onChange={(e) =>
                              onChangeCaptionHighlight(idx, e.target.value)
                            }
                            placeholder="Highlight"
                            aria-label={`Caption ${idx + 1} highlight word`}
                            className={`${scriptClassName} min-h-[32px] w-28 rounded-lg border border-[#D6CEC0] bg-[#FAF7F2] px-2 py-0.5 text-[11px] text-[#1C1917] placeholder-[#6E6A63] focus:border-[#15803D] focus:outline-none`}
                          />
                        </div>
                        <input
                          type="text"
                          dir={fontMeta.dir}
                          value={cap.text}
                          onChange={(e) =>
                            onChangeCaptionText(idx, e.target.value)
                          }
                          aria-label={`Caption ${idx + 1} text`}
                          className={`${scriptClassName} min-h-[36px] w-full rounded-lg border border-[#D6CEC0] bg-[#FAF7F2] px-2.5 py-1 text-xs text-[#1C1917] focus:border-[#15803D] focus:outline-none`}
                        />
                      </div>
                    ))}
                  </div>

                  {/* CTA Text */}
                  <div className="flex flex-col gap-1">
                    <label
                      htmlFor="cta-text-input"
                      className="text-[11px] font-medium text-[#57534E]"
                    >
                      Bottom Button CTA
                    </label>
                    <input
                      id="cta-text-input"
                      type="text"
                      dir={fontMeta.dir}
                      value={ctaText}
                      onChange={(e) => onChangeCtaText(e.target.value)}
                      className={`${scriptClassName} min-h-[36px] w-full rounded-xl border border-[#D6CEC0] bg-white px-3 py-1.5 text-xs text-[#1C1917] focus:border-[#15803D] focus:outline-none`}
                    />
                  </div>
              </div>

              {/* Mandatory Confirmation */}
              <label className="flex cursor-pointer items-start gap-2.5 rounded-xl border border-[#E6E0D5] bg-[#FAF7F2] p-3 text-xs text-[#1C1917]">
                <input
                  type="checkbox"
                  checked={fieldsConfirmed}
                  onChange={(e) => onChangeFieldsConfirmed(e.target.checked)}
                  className="mt-0.5 h-4 w-4 shrink-0 rounded accent-[#15803D]"
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
        <div className="border-t border-[#E6E0D5] pt-4">
          {creditBalance < 1 ? (
            <button
              type="button"
              disabled={!isAuthenticated}
              onClick={onOpenCreditModal}
              className="flex min-h-[44px] w-full items-center justify-center gap-2 rounded-full border border-[#FECACA] bg-[#FEF2F2] px-5 py-2.5 text-xs font-semibold text-[#B91C1C] transition-colors hover:bg-[#FEE2E2] disabled:opacity-50"
            >
              <Sparkles className="h-4 w-4" />
              <span className="tabular-nums">
                0 Credits Remaining — Buy Credits
              </span>
            </button>
          ) : (
            <button
              type="button"
              onClick={onGenerateVideo}
              disabled={!canDispatchRender}
              className="flex min-h-[44px] w-full items-center justify-center gap-2 rounded-full bg-[#15803D] px-5 py-2.5 text-xs font-semibold text-white transition-colors hover:bg-[#166534] disabled:opacity-50"
            >
              <Wand2 className="h-4 w-4" />
              <span className="tabular-nums">
                {isGenerating
                  ? 'Dispatching Video Render Job…'
                  : !hasRequiredFacts
                  ? 'Enter Brand, Title & Price First'
                  : !fieldsConfirmed
                  ? 'Confirm Facts Above to Generate'
                  : `Generate ${aspectRatio} Video Ad (1 Credit)`}
              </span>
            </button>
          )}
        </div>
      </div>
    </aside>
  );
};
