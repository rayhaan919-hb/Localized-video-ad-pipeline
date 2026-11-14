'use client';

import React, { useEffect, useState } from 'react';
import { Player } from '@remotion/player';
import {
  Download,
  Film,
  MonitorPlay,
  Sparkles,
} from 'lucide-react';
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
  viewStateMode: ViewStateMode;
  onGenerateVideo: () => void;
}

export const RemotionPreviewStage: React.FC<RemotionPreviewStageProps> = ({
  adProps,
  activeJob,
  viewStateMode,
  onGenerateVideo,
}) => {
  const [isMounted, setIsMounted] = useState(false);

  useEffect(() => {
    setIsMounted(true);
  }, []);

  const fontMeta = LANGUAGE_FONT_METADATA[adProps.language];

  const scriptClassName =
    adProps.language === 'ur'
      ? 'font-script-ur'
      : adProps.language === 'ar'
      ? 'font-script-ar'
      : adProps.language === 'hi'
      ? 'font-script-hi'
      : 'font-script-en';

  return (
    <section
      aria-label="Center 9:16 Remotion Player Preview"
      className="flex flex-1 flex-col justify-between rounded border border-[#27272A] bg-[#18181B] p-4"
    >
      {/* Stage Top Telemetry Bar */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#27272A] pb-3">
        <div className="flex items-center gap-2">
          <MonitorPlay className="h-4 w-4 text-[#6366F1]" />
          <h2 className="text-sm font-semibold text-[#FAFAFA]">
            2. Live 9:16 Remotion Compositor Preview
          </h2>
          <span className="font-mono-code tabular-nums rounded border border-[#27272A] bg-[#09090B] px-2 py-0.5 text-[11px] text-[#A1A1AA]">
            {VERTICAL_AD_CONFIG.width}×{VERTICAL_AD_CONFIG.height} ·{' '}
            {VERTICAL_AD_CONFIG.fps}FPS · {VERTICAL_AD_CONFIG.durationInFrames}F
          </span>
        </div>

        <div className="flex items-center gap-2">
          <span className="font-mono-code tabular-nums rounded border border-[#27272A] bg-[#09090B] px-2 py-0.5 text-[11px] text-[#FAFAFA]">
            {fontMeta.dir.toUpperCase()} · {fontMeta.fontFamily}
          </span>
          {activeJob?.status === 'COMPLETED' ? (
            <a
              href={`/api/v1/renders/${activeJob.id}`}
              download={`localized-ad-${activeJob.id.slice(0, 8)}.mp4`}
              className="flex items-center gap-1.5 rounded border border-[#6366F1] bg-[#6366F1] px-2.5 py-1 text-xs font-semibold text-[#FAFAFA] transition-colors hover:bg-[#5254E8]"
            >
              <Download className="h-3.5 w-3.5" />
              <span>Download MP4</span>
            </a>
          ) : null}
        </div>
      </div>

      {/* Center Stage Split: 9:16 Vertical Canvas + Real-Time Telemetry Inspector */}
      <div className="my-4 grid grid-cols-1 items-start gap-6 xl:grid-cols-12">
        {/* 9:16 Vertical Remotion Player Frame */}
        <div className="flex flex-col items-center justify-center xl:col-span-7">
          <div className="relative aspect-[9/16] w-full max-w-[330px] overflow-hidden rounded border border-[#27272A] bg-[#09090B]">
            {!isMounted || viewStateMode === 'loading' ? (
              <div className="flex h-full w-full flex-col justify-between p-4">
                <div className="h-8 w-full animate-pulse rounded bg-[#18181B]" />
                <div className="h-64 w-full animate-pulse rounded border border-[#27272A] bg-[#18181B]" />
                <div className="h-24 w-full animate-pulse rounded bg-[#18181B]" />
              </div>
            ) : (
              <Player
                component={VerticalAdTemplate}
                inputProps={adProps}
                durationInFrames={VERTICAL_AD_CONFIG.durationInFrames}
                compositionWidth={VERTICAL_AD_CONFIG.width}
                compositionHeight={VERTICAL_AD_CONFIG.height}
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

        {/* Right Sub-Column: Synchronized RTL/LTR Caption & Veo 3.1 Telemetry */}
        <div className="flex flex-col gap-3 xl:col-span-5">
          {/* Active Composition Spec Card */}
          <div className="flex flex-col gap-2 rounded border border-[#27272A] bg-[#09090B] p-3">
            <div className="flex items-center justify-between border-b border-[#27272A] pb-2">
              <span className="text-xs font-semibold text-[#FAFAFA]">
                Composition Telemetry
              </span>
              <span className="font-mono-code tabular-nums text-[11px] text-[#6366F1]">
                VerticalAd
              </span>
            </div>

            <div className="grid grid-cols-2 gap-2 text-xs">
              <div className="rounded border border-[#27272A] bg-[#18181B] p-2">
                <span className="block text-[10px] text-[#A1A1AA]">
                  DIRECTION & SCRIPT
                </span>
                <span className="font-mono-code tabular-nums mt-0.5 block font-semibold text-[#FAFAFA]">
                  {fontMeta.dir.toUpperCase()} · {adProps.language.toUpperCase()}
                </span>
              </div>
              <div className="rounded border border-[#27272A] bg-[#18181B] p-2">
                <span className="block text-[10px] text-[#A1A1AA]">
                  LINE HEIGHT
                </span>
                <span className="font-mono-code tabular-nums mt-0.5 block font-semibold text-[#FAFAFA]">
                  {fontMeta.lineHeight}× ({fontMeta.fontFamily.split(' ')[0]})
                </span>
              </div>
              <div className="rounded border border-[#27272A] bg-[#18181B] p-2">
                <span className="block text-[10px] text-[#A1A1AA]">
                  PRICE OVERLAY
                </span>
                <span className="font-mono-code tabular-nums mt-0.5 block font-semibold text-[#FAFAFA]">
                  {adProps.priceDisplay}
                </span>
              </div>
              <div className="rounded border border-[#27272A] bg-[#18181B] p-2">
                <span className="block text-[10px] text-[#A1A1AA]">
                  DURATION
                </span>
                <span className="font-mono-code tabular-nums mt-0.5 block font-semibold text-[#FAFAFA]">
                  2.00s · 60 Frames
                </span>
              </div>
            </div>
          </div>

          {/* Synchronized Caption Timeline Breakdown */}
          <div className="flex flex-col gap-2 rounded border border-[#27272A] bg-[#09090B] p-3">
            <div className="flex items-center justify-between border-b border-[#27272A] pb-2">
              <span className="text-xs font-semibold text-[#FAFAFA]">
                Caption Frame Timeline
              </span>
              <span className="font-mono-code tabular-nums text-[11px] text-[#A1A1AA]">
                {adProps.captions.length} SEGMENTS
              </span>
            </div>

            <div className="flex flex-col gap-2">
              {adProps.captions.map((seg, idx) => (
                <div
                  key={seg.id}
                  dir={fontMeta.dir}
                  className="flex flex-col gap-1 rounded border border-[#27272A] bg-[#18181B] p-2.5"
                >
                  <div
                    dir="ltr"
                    className="flex items-center justify-between text-[10px]"
                  >
                    <span className="font-mono-code tabular-nums font-semibold text-[#6366F1]">
                      CAPTION 0{idx + 1}
                    </span>
                    <span className="font-mono-code tabular-nums text-[#A1A1AA]">
                      {String(seg.startFrame).padStart(2, '0')}F →{' '}
                      {String(seg.endFrame).padStart(2, '0')}F
                    </span>
                  </div>
                  <p className={`${scriptClassName} text-xs text-[#FAFAFA]`}>
                    {seg.text}
                  </p>
                  {seg.highlightWord ? (
                    <div dir="ltr" className="flex items-center gap-1 pt-0.5">
                      <span className="text-[10px] text-[#A1A1AA]">
                        Highlight:
                      </span>
                      <span
                        dir={fontMeta.dir}
                        className={`${scriptClassName} rounded border border-[#6366F1] bg-[#09090B] px-1.5 py-0.5 text-[10px] font-semibold text-[#FAFAFA]`}
                      >
                        {seg.highlightWord}
                      </span>
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          </div>

          {/* Veo 3.1 Prompt & GCS Output Target */}
          <div className="flex flex-col gap-2 rounded border border-[#27272A] bg-[#09090B] p-3">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-xs font-semibold text-[#FAFAFA]">
                <Film className="h-3.5 w-3.5 text-[#6366F1]" />
                <span>Vertex AI Veo 3.1 Target</span>
              </span>
              <span className="font-mono-code tabular-nums text-[10px] text-[#A1A1AA]">
                MOCK_VERTEX_VEO=true
              </span>
            </div>
            <p className="font-mono-code tabular-nums truncate rounded border border-[#27272A] bg-[#18181B] px-2 py-1.5 text-[11px] text-[#A1A1AA]">
              {activeJob?.veo_gcs_uri ??
                'gs://videosaving/renders/pending/veo_raw.mp4'}
            </p>
            <button
              type="button"
              onClick={onGenerateVideo}
              className="flex items-center justify-center gap-1.5 rounded border border-[#27272A] bg-[#18181B] px-3 py-2 text-xs font-semibold text-[#FAFAFA] transition-colors hover:border-[#6366F1]"
            >
              <Sparkles className="h-3.5 w-3.5 text-[#6366F1]" />
              <span>Render Current Composition to MP4</span>
            </button>
          </div>
        </div>
      </div>

      {/* Bottom Stage Footer */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[#27272A] pt-3 text-xs text-[#A1A1AA]">
        <span>
          Active Brand:{' '}
          <strong className="font-semibold text-[#FAFAFA]">
            {adProps.brandName}
          </strong>
        </span>
        <span className="font-mono-code tabular-nums">
          JOB: {activeJob?.id ? activeJob.id.slice(0, 12) : 'LIVE_DRAFT'}
        </span>
      </div>
    </section>
  );
};
