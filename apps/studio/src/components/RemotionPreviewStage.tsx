'use client';

import React, { useEffect, useState } from 'react';
import { Player } from '@remotion/player';
import { Download } from 'lucide-react';
import {
  LANGUAGE_FONT_METADATA,
  VERTICAL_AD_CONFIG,
  VerticalAdTemplate,
  type LocalizedAdProps,
} from '@video-ad/remotion';
import type { VideoJobRecord, ViewStateMode } from '@/types/studio';

interface RemotionPreviewStageProps {
  adProps: LocalizedAdProps;
  activeJob: VideoJobRecord | null;
  aspectRatio: '9:16' | '16:9';
  viewStateMode: ViewStateMode;
}

export const RemotionPreviewStage: React.FC<RemotionPreviewStageProps> = ({
  adProps,
  activeJob,
  aspectRatio,
  viewStateMode,
}) => {
  const [isMounted, setIsMounted] = useState(false);

  useEffect(() => {
    setIsMounted(true);
  }, []);

  const fontMeta = LANGUAGE_FONT_METADATA[adProps.language];
  const compWidth = aspectRatio === '16:9' ? 1920 : VERTICAL_AD_CONFIG.width;
  const compHeight = aspectRatio === '16:9' ? 1080 : VERTICAL_AD_CONFIG.height;

  const scriptClassName =
    adProps.language === 'ur'
      ? 'font-script-ur'
      : adProps.language === 'ar'
      ? 'font-script-ar'
      : adProps.language === 'hi'
      ? 'font-script-hi'
      : 'font-script-en';

  const statusBadge =
    activeJob?.status === 'COMPLETED'
      ? { label: 'Ready', cls: 'border-[#BBF7D0] bg-[#F0FDF4] text-[#166534]' }
      : activeJob?.status === 'FAILED' || activeJob?.status === 'CANCELLED'
      ? { label: activeJob.status, cls: 'border-[#FECACA] bg-[#FEF2F2] text-[#B91C1C]' }
      : activeJob
      ? { label: 'Rendering', cls: 'border-[#FDE68A] bg-[#FFFBEB] text-[#92400E]' }
      : { label: 'Draft', cls: 'border-[#E6E0D5] bg-white text-[#57534E]' };

  return (
    <section
      aria-label="Live Video Preview"
      className="flex min-w-0 flex-1 flex-col gap-5 rounded-2xl border border-[#E6E0D5] bg-white p-5 shadow-[0_1px_2px_rgba(28,25,23,0.04)]"
    >
      {/* Clean Header Bar */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#E6E0D5] pb-3.5">
        <div className="flex flex-wrap items-baseline gap-2.5">
          <h2 className="text-base font-semibold text-[#1C1917]">
            Live Preview
          </h2>
          <span className="font-mono-code tabular-nums text-xs text-[#57534E]">
            {aspectRatio} · {compWidth}×{compHeight}
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full border border-[#E6E0D5] bg-[#FAF7F2] px-3 py-1 text-[11px] font-medium text-[#57534E]">
            {fontMeta.nativeLabel} · {fontMeta.dir.toUpperCase()}
          </span>
          {activeJob?.status === 'COMPLETED' && activeJob.final_mp4_url ? (
            <a
              href={activeJob.final_mp4_url}
              download={`localized-ad-${activeJob.id.slice(0, 8)}.mp4`}
              className="flex min-h-[38px] items-center gap-1.5 rounded-full bg-[#15803D] px-4 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-[#166534]"
            >
              <Download className="h-3.5 w-3.5" />
              <span>Download MP4</span>
            </a>
          ) : null}
        </div>
      </div>

      {/* Player & Clean Caption List */}
      <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-12">
        <div className="flex flex-col items-center justify-center xl:col-span-7">
          <div
            className={`relative overflow-hidden rounded-2xl border border-[#E6E0D5] bg-[#141416] shadow-sm ${
              aspectRatio === '16:9'
                ? 'aspect-video w-full'
                : 'aspect-[9/16] w-full max-w-[330px]'
            }`}
          >
            {!isMounted || viewStateMode === 'loading' ? (
              <div className="flex h-full w-full flex-col justify-between bg-[#FAF7F2] p-4">
                <div className="h-8 w-full animate-pulse rounded-xl bg-[#E6E0D5]" />
                <div className="h-64 w-full animate-pulse rounded-2xl bg-[#F4EFE6]" />
                <div className="h-24 w-full animate-pulse rounded-xl bg-[#E6E0D5]" />
              </div>
            ) : (
              <Player
                component={VerticalAdTemplate}
                inputProps={adProps}
                durationInFrames={VERTICAL_AD_CONFIG.durationInFrames}
                compositionWidth={compWidth}
                compositionHeight={compHeight}
                fps={VERTICAL_AD_CONFIG.fps}
                style={{
                  width: '100%',
                  height: '100%',
                }}
                controls
                loop
              />
            )}
          </div>
        </div>

        {/* Concise Summary & Captions */}
        <div className="flex min-w-0 flex-col gap-3.5 xl:col-span-5">
          {/* Compact Single-Line Summary Bar */}
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[#E6E0D5] bg-[#FAF7F2] px-3.5 py-2.5">
            <div className="min-w-0">
              <span className="block truncate text-xs font-semibold text-[#1C1917]">
                {adProps.brandName || 'Your Brand'}
              </span>
              <span className="font-mono-code tabular-nums text-xs font-semibold text-[#166534]">
                {adProps.priceDisplay || '—'}
              </span>
            </div>
            <span
              className={`rounded-full border px-2.5 py-0.5 text-[11px] font-semibold ${statusBadge.cls}`}
            >
              {statusBadge.label}
            </span>
          </div>

          {/* Captions Breakdown */}
          <div className="flex flex-col gap-2.5">
            <div className="flex items-center justify-between px-0.5">
              <span className="text-xs font-semibold text-[#1C1917]">
                Captions
              </span>
              <span className="text-[11px] text-[#57534E]">
                {adProps.captions.length}{' '}
                {adProps.captions.length === 1 ? 'segment' : 'segments'}
              </span>
            </div>

            {adProps.captions.map((seg, idx) => (
              <div
                key={seg.id}
                dir={fontMeta.dir}
                className="flex flex-col gap-1.5 rounded-xl border border-[#E6E0D5] bg-[#FAF7F2] p-3"
              >
                <div
                  dir="ltr"
                  className="flex items-center justify-between text-[11px]"
                >
                  <span className="font-mono-code tabular-nums font-semibold text-[#166534]">
                    {String(idx + 1).padStart(2, '0')}
                  </span>
                  <span className="font-mono-code tabular-nums text-[#57534E]">
                    {String(seg.startFrame).padStart(2, '0')}F →{' '}
                    {String(seg.endFrame).padStart(2, '0')}F
                  </span>
                </div>
                <p className={`${scriptClassName} text-xs text-[#1C1917]`}>
                  {seg.text}
                </p>
                {seg.highlightWord ? (
                  <div dir="ltr" className="flex items-center gap-1.5 pt-0.5">
                    <span className="text-[11px] text-[#57534E]">
                      Highlight:
                    </span>
                    <span
                      dir={fontMeta.dir}
                      className={`${scriptClassName} rounded-full border border-[#BBF7D0] bg-[#F0FDF4] px-2.5 py-1 text-[11px] font-semibold leading-relaxed text-[#166534]`}
                    >
                      {seg.highlightWord}
                    </span>
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
};
