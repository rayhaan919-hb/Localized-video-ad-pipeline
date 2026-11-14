'use client';

import React from 'react';
import {
  AlertTriangle,
  Globe,
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
import type { ViewStateMode } from '@/types/studio';

export interface SampleStorePreset {
  id: string;
  label: string;
  url: string;
}

export const SAMPLE_STORE_URLS: readonly SampleStorePreset[] = [
  {
    id: 'skincare',
    label: 'Skincare Serum',
    url: 'https://zaynaskin.pk/products/vitamin-c-glow-serum',
  },
  {
    id: 'oud',
    label: 'Kashmiri Oud',
    url: 'https://nooratelier.sa/products/royal-kashmiri-oud-parfum',
  },
  {
    id: 'earbuds',
    label: 'ANC Earbuds',
    url: 'https://aeropulse.io/products/aeropulse-pro-anc-earbuds',
  },
  {
    id: 'honey',
    label: 'Sidr Honey',
    url: 'https://zaytoon.organic/products/royal-mountain-sidr-honey',
  },
] as const;

const ANGLE_UI_LABELS: Record<AdAngle, { title: string; tag: string }> = {
  problem_solution: { title: 'Problem / Solution', tag: 'PAIN → RELIEF' },
  ugc_testimonial: { title: 'UGC Testimonial', tag: '4.9★ SOCIAL' },
  flash_sale: { title: '24H Flash Sale', tag: 'URGENCY' },
  unboxing: { title: 'Luxury Unboxing', tag: 'FIRST LOOK' },
};

interface ProductScraperPanelProps {
  productUrl: string;
  onChangeProductUrl: (url: string) => void;
  targetLanguage: SupportedLanguage;
  onChangeLanguage: (lang: SupportedLanguage) => void;
  adAngle: AdAngle;
  onChangeAdAngle: (angle: AdAngle) => void;
  productTitle: string;
  onChangeProductTitle: (val: string) => void;
  brandName: string;
  onChangeBrandName: (val: string) => void;
  priceDisplay: string;
  onChangePriceDisplay: (val: string) => void;
  discountBadge: string;
  onChangeDiscountBadge: (val: string) => void;
  hookText: string;
  onChangeHookText: (val: string) => void;
  ctaText: string;
  onChangeCtaText: (val: string) => void;
  captions: CaptionSegment[];
  onChangeCaptionText: (index: number, text: string) => void;
  onChangeCaptionHighlight: (index: number, highlightWord: string) => void;
  isScraping: boolean;
  scrapeError: string | null;
  isProductEmpty: boolean;
  onScrapeUrl: (overrideUrl?: string) => void;
  onClearProduct: () => void;
  onLoadDefaultPreset: () => void;
  isGenerating: boolean;
  creditBalance: number;
  onGenerateVideo: () => void;
  onOpenCreditModal: () => void;
  viewStateMode: ViewStateMode;
}

export const ProductScraperPanel: React.FC<ProductScraperPanelProps> = ({
  productUrl,
  onChangeProductUrl,
  targetLanguage,
  onChangeLanguage,
  adAngle,
  onChangeAdAngle,
  productTitle,
  onChangeProductTitle,
  brandName,
  onChangeBrandName,
  priceDisplay,
  onChangePriceDisplay,
  discountBadge,
  onChangeDiscountBadge,
  hookText,
  onChangeHookText,
  ctaText,
  onChangeCtaText,
  captions,
  onChangeCaptionText,
  onChangeCaptionHighlight,
  isScraping,
  scrapeError,
  isProductEmpty,
  onScrapeUrl,
  onClearProduct,
  onLoadDefaultPreset,
  isGenerating,
  creditBalance,
  onGenerateVideo,
  onOpenCreditModal,
  viewStateMode,
}) => {
  const fontMeta = LANGUAGE_FONT_METADATA[targetLanguage];
  const showSkeleton = isScraping || viewStateMode === 'loading';
  const showError = Boolean(scrapeError) || viewStateMode === 'error';
  const showEmpty =
    (!showSkeleton && isProductEmpty) || viewStateMode === 'empty';

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
            360PX PANEL
          </span>
        </div>

        {/* Product URL Input & Scraper Trigger */}
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <label
              htmlFor="product-url-input"
              className="text-xs font-medium text-[#FAFAFA]"
            >
              D2C Product URL
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
              placeholder="https://store.pk/products/glow-serum"
              className="font-mono-code min-w-0 flex-1 rounded border border-[#27272A] bg-[#09090B] px-3 py-2 text-xs text-[#FAFAFA] placeholder-[#A1A1AA]/50 focus:border-[#6366F1] focus:outline-none"
            />
            <button
              type="button"
              onClick={() => onScrapeUrl()}
              disabled={isScraping}
              className="shrink-0 rounded border border-[#6366F1] bg-[#6366F1] px-3 py-2 text-xs font-semibold text-[#FAFAFA] transition-colors hover:bg-[#5254E8] disabled:opacity-50"
            >
              {isScraping ? 'Scraping…' : 'Scrape URL'}
            </button>
          </div>

          {/* Preset Catalog Quick-Pills */}
          <div className="flex flex-wrap gap-1 pt-1">
            {SAMPLE_STORE_URLS.map((preset) => {
              const isSelected = productUrl === preset.url;
              return (
                <button
                  key={preset.id}
                  type="button"
                  onClick={() => {
                    onChangeProductUrl(preset.url);
                    onScrapeUrl(preset.url);
                  }}
                  className={`rounded border px-2 py-1 text-[11px] font-medium transition-colors ${
                    isSelected
                      ? 'border-[#6366F1] bg-[#09090B] text-[#FAFAFA]'
                      : 'border-[#27272A] bg-[#09090B] text-[#A1A1AA] hover:border-[#FAFAFA]/40 hover:text-[#FAFAFA]'
                  }`}
                >
                  {preset.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Inline Error Banner with Retry Button (Mandatory DESIGN.md State 3) */}
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
                    'Remote storefront timed out while extracting OpenGraph price & RTL copy.'}
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

        {/* Target Language Selector (ur, ar, hi, en) */}
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

        {/* Ad Angle Selector */}
        <div className="flex flex-col gap-2 border-t border-[#27272A] pt-3">
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-1.5 text-xs font-medium text-[#FAFAFA]">
              <Tag className="h-3.5 w-3.5 text-[#6366F1]" />
              <span>D2C Ad Angle</span>
            </span>
            <span className="font-mono-code tabular-nums text-[11px] text-[#A1A1AA]">
              4 TEMPLATES
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

        {/* Scraped Metadata & Localized Script Section: Skeleton / Empty / Normal */}
        <div className="border-t border-[#27272A] pt-3">
          {showSkeleton ? (
            /* Mandatory State 1: Skeleton Loader matching exact dimensions */
            <div
              data-testid="scraper-skeleton"
              className="flex flex-col gap-3 rounded border border-[#27272A] bg-[#09090B] p-3"
            >
              <div className="flex items-center justify-between">
                <div className="h-3.5 w-28 animate-pulse rounded bg-[#27272A]" />
                <div className="h-3.5 w-16 animate-pulse rounded bg-[#27272A]" />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div className="h-9 animate-pulse rounded border border-[#27272A] bg-[#18181B]" />
                <div className="h-9 animate-pulse rounded border border-[#27272A] bg-[#18181B]" />
              </div>
              <div className="h-9 w-full animate-pulse rounded border border-[#27272A] bg-[#18181B]" />
              <div className="h-16 w-full animate-pulse rounded border border-[#27272A] bg-[#18181B]" />
              <div className="h-20 w-full animate-pulse rounded border border-[#27272A] bg-[#18181B]" />
            </div>
          ) : showEmpty ? (
            /* Mandatory State 2: Actionable Empty State (icon + 1-line explanation + primary CTA) */
            <div
              data-testid="scraper-empty-state"
              className="flex flex-col items-center justify-center gap-3 rounded border border-[#27272A] bg-[#09090B] p-6 text-center"
            >
              <div className="flex h-10 w-10 items-center justify-center rounded border border-[#27272A] bg-[#18181B]">
                <PackageSearch className="h-5 w-5 text-[#6366F1]" />
              </div>
              <p className="text-xs text-[#A1A1AA]">
                No product metadata loaded. Scrape a D2C URL or load a verified
                regional preset.
              </p>
              <button
                type="button"
                onClick={onLoadDefaultPreset}
                className="rounded border border-[#6366F1] bg-[#6366F1] px-3 py-1.5 text-xs font-semibold text-[#FAFAFA] transition-colors hover:bg-[#5254E8]"
              >
                Load Sample D2C Product
              </button>
            </div>
          ) : (
            /* Active Localized Copy & Price Editor */
            <div className="flex flex-col gap-3">
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-1.5 text-xs font-medium text-[#FAFAFA]">
                  <Type className="h-3.5 w-3.5 text-[#6366F1]" />
                  <span>Localized Script & Price Overlay</span>
                </span>
                <span className="font-mono-code tabular-nums text-[11px] text-[#A1A1AA]">
                  LIVE SYNC
                </span>
              </div>

              {/* Brand & Price Row */}
              <div className="grid grid-cols-2 gap-2">
                <div className="flex flex-col gap-1">
                  <label
                    htmlFor="brand-name-input"
                    className="text-[11px] text-[#A1A1AA]"
                  >
                    Brand Name
                  </label>
                  <input
                    id="brand-name-input"
                    type="text"
                    value={brandName}
                    onChange={(e) => onChangeBrandName(e.target.value)}
                    className="rounded border border-[#27272A] bg-[#09090B] px-2.5 py-1.5 text-xs text-[#FAFAFA] focus:border-[#6366F1] focus:outline-none"
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <label
                    htmlFor="price-display-input"
                    className="text-[11px] text-[#A1A1AA]"
                  >
                    Price Badge (Mono)
                  </label>
                  <input
                    id="price-display-input"
                    type="text"
                    value={priceDisplay}
                    onChange={(e) => onChangePriceDisplay(e.target.value)}
                    className="font-mono-code tabular-nums rounded border border-[#27272A] bg-[#09090B] px-2.5 py-1.5 text-xs text-[#FAFAFA] focus:border-[#6366F1] focus:outline-none"
                  />
                </div>
              </div>

              {/* Product Title & Discount Row */}
              <div className="grid grid-cols-3 gap-2">
                <div className="col-span-2 flex flex-col gap-1">
                  <label
                    htmlFor="product-title-input"
                    className="text-[11px] text-[#A1A1AA]"
                  >
                    Localized Product Title
                  </label>
                  <input
                    id="product-title-input"
                    type="text"
                    dir={fontMeta.dir}
                    value={productTitle}
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
                    onChange={(e) => onChangeDiscountBadge(e.target.value)}
                    className="font-mono-code tabular-nums rounded border border-[#27272A] bg-[#09090B] px-2.5 py-1.5 text-xs text-[#FAFAFA] focus:border-[#6366F1] focus:outline-none"
                  />
                </div>
              </div>

              {/* Localized Hook Headline */}
              <div className="flex flex-col gap-1">
                <div className="flex items-center justify-between">
                  <label
                    htmlFor="hook-text-input"
                    className="text-[11px] text-[#A1A1AA]"
                  >
                    Opening Hook ({fontMeta.dir.toUpperCase()})
                  </label>
                  <span className="font-mono-code tabular-nums text-[10px] text-[#A1A1AA]">
                    00F–60F
                  </span>
                </div>
                <textarea
                  id="hook-text-input"
                  rows={2}
                  dir={fontMeta.dir}
                  value={hookText}
                  onChange={(e) => onChangeHookText(e.target.value)}
                  className={`${scriptClassName} rounded border border-[#27272A] bg-[#09090B] px-2.5 py-1.5 text-xs text-[#FAFAFA] focus:border-[#6366F1] focus:outline-none`}
                />
              </div>

              {/* Animated Caption Segments (3 segments) */}
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
            </div>
          )}
        </div>

        {/* Primary Action: Deduct 1 Credit Atomically & Dispatch Veo 3.1 + Remotion Render */}
        <div className="flex flex-col gap-2 border-t border-[#27272A] pt-3">
          {creditBalance < 1 ? (
            <button
              type="button"
              onClick={onOpenCreditModal}
              className="flex w-full items-center justify-center gap-2 rounded border border-red-500/80 bg-[#09090B] px-4 py-2.5 text-xs font-semibold text-[#FAFAFA] transition-colors hover:border-[#6366F1]"
            >
              <Sparkles className="h-4 w-4 text-[#6366F1]" />
              <span className="tabular-nums">
                0 Credits Remaining — Top Up Credits
              </span>
            </button>
          ) : (
            <button
              type="button"
              onClick={onGenerateVideo}
              disabled={isGenerating || isProductEmpty}
              className="flex w-full items-center justify-center gap-2 rounded border border-[#6366F1] bg-[#6366F1] px-4 py-2.5 text-xs font-semibold text-[#FAFAFA] transition-colors hover:bg-[#5254E8] disabled:opacity-50"
            >
              <Wand2 className="h-4 w-4" />
              <span className="tabular-nums">
                {isGenerating
                  ? 'Dispatching Veo 3.1 + Remotion Job…'
                  : 'Generate 9:16 Video Ad (1 Credit)'}
              </span>
            </button>
          )}

          <div className="flex items-center justify-between text-[11px] text-[#A1A1AA]">
            <span>Atomic SQL Ledger Deduction</span>
            <span className="font-mono-code tabular-nums">
              veo-3.1-generate-001
            </span>
          </div>
        </div>
      </div>
    </aside>
  );
};
