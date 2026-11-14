'use client';

import React, { useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Download,
  Eye,
  Film,
  HardDriveDownload,
  Play,
  RotateCcw,
  Trash2,
  XCircle,
} from 'lucide-react';
import { LANGUAGE_FONT_METADATA } from '@video-ad/remotion';
import type {
  JobStatus,
  VideoJobRecord,
  ViewStateMode,
} from '@/types/studio';

interface RenderQueueGalleryProps {
  jobs: VideoJobRecord[];
  activeJobId: string | null;
  isLoadingJobs: boolean;
  jobsError: string | null;
  viewStateMode: ViewStateMode;
  onSelectJobForPreview: (job: VideoJobRecord) => void;
  onRetryFetchJobs: () => void;
  onGenerateFirstJob: () => void;
  onClearLocalJobs: () => void;
  onTriggerTestFailureJob: () => void;
}

type FilterTab = 'ALL' | 'COMPLETED' | 'ACTIVE' | 'FAILED';

const PIPELINE_STEPS: readonly { key: JobStatus; label: string }[] = [
  { key: 'PENDING', label: '1. Queued' },
  { key: 'GENERATING_CLIPS', label: '2. Veo 3.1' },
  { key: 'COMPOSITING', label: '3. Remotion' },
  { key: 'COMPLETED', label: '4. MP4 Ready' },
] as const;

function getStepProgressIndex(status: JobStatus): number {
  switch (status) {
    case 'PENDING':
      return 1;
    case 'GENERATING_CLIPS':
      return 2;
    case 'COMPOSITING':
      return 3;
    case 'COMPLETED':
      return 4;
    case 'FAILED':
      return 0;
  }
}

export const RenderQueueGallery: React.FC<RenderQueueGalleryProps> = ({
  jobs,
  activeJobId,
  isLoadingJobs,
  jobsError,
  viewStateMode,
  onSelectJobForPreview,
  onRetryFetchJobs,
  onGenerateFirstJob,
  onClearLocalJobs,
  onTriggerTestFailureJob,
}) => {
  const [filterTab, setFilterTab] = useState<FilterTab>('ALL');

  const showSkeleton = isLoadingJobs || viewStateMode === 'loading';
  const showError = Boolean(jobsError) || viewStateMode === 'error';

  const filteredJobs = jobs.filter((job) => {
    if (filterTab === 'ALL') return true;
    if (filterTab === 'COMPLETED') return job.status === 'COMPLETED';
    if (filterTab === 'FAILED') return job.status === 'FAILED';
    return (
      job.status === 'PENDING' ||
      job.status === 'GENERATING_CLIPS' ||
      job.status === 'COMPOSITING'
    );
  });

  const showEmpty =
    (!showSkeleton && filteredJobs.length === 0) || viewStateMode === 'empty';

  return (
    <section
      aria-label="Bottom Render Queue Strip and MP4 Download Gallery"
      className="w-full rounded border border-[#27272A] bg-[#18181B] p-4"
    >
      {/* Header Row */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#27272A] pb-3">
        <div className="flex items-center gap-2">
          <HardDriveDownload className="h-4 w-4 text-[#6366F1]" />
          <h2 className="text-sm font-semibold text-[#FAFAFA]">
            3. Render Queue & MP4 Download Gallery
          </h2>
          <span className="font-mono-code tabular-nums rounded border border-[#27272A] bg-[#09090B] px-2 py-0.5 text-[11px] font-semibold text-[#FAFAFA]">
            {jobs.length} JOBS
          </span>
        </div>

        {/* Filter Pills + Actions */}
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1 rounded border border-[#27272A] bg-[#09090B] p-1">
            {(['ALL', 'COMPLETED', 'ACTIVE', 'FAILED'] as const).map((tab) => {
              const active = filterTab === tab;
              return (
                <button
                  key={tab}
                  type="button"
                  onClick={() => setFilterTab(tab)}
                  className={`font-mono-code rounded px-2 py-0.5 text-[11px] font-medium transition-colors ${
                    active
                      ? 'bg-[#6366F1] text-[#FAFAFA]'
                      : 'text-[#A1A1AA] hover:text-[#FAFAFA]'
                  }`}
                >
                  {tab}
                </button>
              );
            })}
          </div>

          <button
            type="button"
            onClick={onTriggerTestFailureJob}
            title="Test Atomic Credit Refund on Failed Job"
            className="rounded border border-[#27272A] bg-[#09090B] px-2.5 py-1 text-xs text-[#A1A1AA] transition-colors hover:border-[#FAFAFA]/40 hover:text-[#FAFAFA]"
          >
            Simulate Fail + Refund
          </button>

          <button
            type="button"
            onClick={onClearLocalJobs}
            className="flex items-center gap-1 rounded border border-[#27272A] bg-[#09090B] px-2.5 py-1 text-xs text-[#A1A1AA] transition-colors hover:border-red-500/60 hover:text-red-400"
          >
            <Trash2 className="h-3 w-3" />
            <span>Clear</span>
          </button>
        </div>
      </div>

      {/* Mandatory DESIGN.md State 3: Inline Error Banner with Retry Button */}
      {showError ? (
        <div
          role="alert"
          data-testid="queue-error-banner"
          className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded border border-red-500/60 bg-[#09090B] p-3"
        >
          <div className="flex items-center gap-2.5">
            <AlertTriangle className="h-4 w-4 shrink-0 text-red-400" />
            <div>
              <p className="text-xs font-semibold text-[#FAFAFA]">
                Render Queue Synchronization Error
              </p>
              <p className="text-xs text-[#A1A1AA]">
                {jobsError ??
                  'Could not fetch video_jobs from worker endpoint (/v1/videos). Verify connection and retry.'}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onRetryFetchJobs}
            className="flex items-center gap-1.5 rounded border border-[#27272A] bg-[#18181B] px-3 py-1.5 text-xs font-semibold text-[#FAFAFA] transition-colors hover:border-[#6366F1]"
          >
            <RotateCcw className="h-3.5 w-3.5 text-[#6366F1]" />
            <span>Retry</span>
          </button>
        </div>
      ) : null}

      {/* Main Content Area: Skeleton Loader / Actionable Empty State / Job Cards */}
      <div className="mt-4">
        {showSkeleton ? (
          /* Mandatory DESIGN.md State 1: Skeleton Loader matching exact card grid dimensions */
          <div
            data-testid="queue-skeleton"
            className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3"
          >
            {[0, 1, 2].map((item) => (
              <div
                key={item}
                className="flex h-[228px] flex-col justify-between rounded border border-[#27272A] bg-[#09090B] p-4"
              >
                <div className="flex items-center justify-between">
                  <div className="h-4 w-28 animate-pulse rounded bg-[#27272A]" />
                  <div className="h-5 w-20 animate-pulse rounded bg-[#27272A]" />
                </div>
                <div className="flex flex-col gap-2">
                  <div className="h-4 w-3/4 animate-pulse rounded bg-[#27272A]" />
                  <div className="h-4 w-full animate-pulse rounded bg-[#18181B]" />
                  <div className="h-3 w-2/3 animate-pulse rounded bg-[#18181B]" />
                </div>
                <div className="grid grid-cols-2 gap-2 pt-2">
                  <div className="h-8 animate-pulse rounded bg-[#18181B]" />
                  <div className="h-8 animate-pulse rounded bg-[#27272A]" />
                </div>
              </div>
            ))}
          </div>
        ) : showEmpty ? (
          /* Mandatory DESIGN.md State 2: Actionable Empty State (icon + 1-line explanation + primary CTA) */
          <div
            data-testid="queue-empty-state"
            className="flex flex-col items-center justify-center gap-3 rounded border border-[#27272A] bg-[#09090B] py-8 px-4 text-center"
          >
            <div className="flex h-10 w-10 items-center justify-center rounded border border-[#27272A] bg-[#18181B]">
              <Film className="h-5 w-5 text-[#6366F1]" />
            </div>
            <p className="text-xs text-[#A1A1AA]">
              No rendered 9:16 video ads in this queue view yet — generate your
              first localized Veo 3.1 + Remotion ad to download the MP4.
            </p>
            <button
              type="button"
              onClick={onGenerateFirstJob}
              className="flex items-center gap-1.5 rounded border border-[#6366F1] bg-[#6366F1] px-4 py-2 text-xs font-semibold text-[#FAFAFA] transition-colors hover:bg-[#5254E8]"
            >
              <Play className="h-3.5 w-3.5" />
              <span>Generate First 9:16 Video Ad (1 Credit)</span>
            </button>
          </div>
        ) : (
          /* Active Render Job Cards Grid */
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            {filteredJobs.map((job) => {
              const langMeta =
                LANGUAGE_FONT_METADATA[job.target_language] ??
                LANGUAGE_FONT_METADATA.ur;
              const isSelected = activeJobId === job.id;
              const progressIdx = getStepProgressIndex(job.status);
              const scriptClassName =
                job.target_language === 'ur'
                  ? 'font-script-ur'
                  : job.target_language === 'ar'
                  ? 'font-script-ar'
                  : job.target_language === 'hi'
                  ? 'font-script-hi'
                  : 'font-script-en';

              const createdTime = new Date(job.created_at).toLocaleTimeString(
                [],
                {
                  hour: '2-digit',
                  minute: '2-digit',
                  second: '2-digit',
                }
              );

              return (
                <article
                  key={job.id}
                  className={`flex flex-col justify-between gap-3 rounded border p-4 transition-colors ${
                    isSelected
                      ? 'border-[#6366F1] bg-[#09090B]'
                      : 'border-[#27272A] bg-[#09090B] hover:border-[#FAFAFA]/30'
                  }`}
                >
                  {/* Top Row: Job UUID + Language Pill + Status Badge */}
                  <div className="flex items-center justify-between gap-2 border-b border-[#27272A] pb-2.5">
                    <div className="flex items-center gap-1.5">
                      <span className="font-mono-code tabular-nums text-xs font-semibold text-[#FAFAFA]">
                        #{job.id.slice(0, 8)}
                      </span>
                      <span className="font-mono-code tabular-nums rounded border border-[#27272A] bg-[#18181B] px-1.5 py-0.5 text-[10px] font-semibold text-[#A1A1AA]">
                        {job.target_language.toUpperCase()} ·{' '}
                        {langMeta.dir.toUpperCase()}
                      </span>
                    </div>

                    {job.status === 'COMPLETED' ? (
                      <span className="font-mono-code tabular-nums flex items-center gap-1 rounded border border-[#6366F1] bg-[#18181B] px-2 py-0.5 text-[10px] font-semibold text-[#FAFAFA]">
                        <CheckCircle2 className="h-3 w-3 text-[#6366F1]" />
                        COMPLETED
                      </span>
                    ) : job.status === 'FAILED' ? (
                      <span className="font-mono-code tabular-nums flex items-center gap-1 rounded border border-red-500/60 bg-[#18181B] px-2 py-0.5 text-[10px] font-semibold text-red-400">
                        <XCircle className="h-3 w-3 text-red-400" />
                        FAILED · REFUNDED
                      </span>
                    ) : (
                      <span className="font-mono-code tabular-nums flex items-center gap-1 rounded border border-[#27272A] bg-[#18181B] px-2 py-0.5 text-[10px] font-semibold text-[#A1A1AA]">
                        <Clock className="h-3 w-3 text-[#6366F1]" />
                        {job.status}
                      </span>
                    )}
                  </div>

                  {/* Pipeline Step Progress Strip */}
                  <div className="grid grid-cols-4 gap-1">
                    {PIPELINE_STEPS.map((step, idx) => {
                      const stepNum = idx + 1;
                      const reached =
                        job.status !== 'FAILED' && progressIdx >= stepNum;
                      return (
                        <div key={step.key} className="flex flex-col gap-1">
                          <div
                            className={`h-1 w-full rounded ${
                              job.status === 'FAILED'
                                ? 'bg-red-500/50'
                                : reached
                                ? 'bg-[#6366F1]'
                                : 'bg-[#27272A]'
                            }`}
                          />
                          <span className="font-mono-code tabular-nums text-[9px] text-[#A1A1AA]">
                            {step.label}
                          </span>
                        </div>
                      );
                    })}
                  </div>

                  {/* Middle: Product Title, Hook & Veo GCS URI */}
                  <div className="flex flex-col gap-1.5">
                    <div className="flex items-center justify-between text-xs">
                      <span className="font-semibold text-[#FAFAFA]">
                        {job.script_json?.brand ?? 'D2C Storefront'}
                      </span>
                      <span className="font-mono-code tabular-nums text-xs font-semibold text-[#6366F1]">
                        {job.script_json?.price_badge ?? 'PKR 4,990'}
                      </span>
                    </div>

                    <p
                      dir={langMeta.dir}
                      className={`${scriptClassName} line-clamp-2 rounded border border-[#27272A] bg-[#18181B] px-2.5 py-1.5 text-xs text-[#FAFAFA]`}
                    >
                      {job.script_json?.hook ??
                        job.script_json?.product_title ??
                        job.product_url}
                    </p>

                    <div className="flex items-center justify-between text-[10px] text-[#A1A1AA]">
                      <span className="font-mono-code tabular-nums truncate max-w-[190px]">
                        {job.veo_gcs_uri ??
                          (job.status === 'FAILED'
                            ? 'Credit atomically refunded (+1)'
                            : 'gs://videosaving/renders/pending')}
                      </span>
                      <span className="font-mono-code tabular-nums">
                        {createdTime}
                      </span>
                    </div>
                  </div>

                  {/* Bottom Actions: Load in Preview + Download MP4 */}
                  <div className="grid grid-cols-2 gap-2 border-t border-[#27272A] pt-2.5">
                    <button
                      type="button"
                      onClick={() => onSelectJobForPreview(job)}
                      className="flex items-center justify-center gap-1.5 rounded border border-[#27272A] bg-[#18181B] px-2.5 py-1.5 text-xs font-medium text-[#FAFAFA] transition-colors hover:border-[#6366F1]"
                    >
                      <Eye className="h-3.5 w-3.5 text-[#6366F1]" />
                      <span>Load Preview</span>
                    </button>

                    {job.status === 'COMPLETED' ? (
                      <a
                        href={`/api/v1/renders/${job.id}`}
                        download={`localized-ad-${job.id.slice(0, 8)}.mp4`}
                        className="flex items-center justify-center gap-1.5 rounded border border-[#6366F1] bg-[#6366F1] px-2.5 py-1.5 text-xs font-semibold text-[#FAFAFA] transition-colors hover:bg-[#5254E8]"
                      >
                        <Download className="h-3.5 w-3.5" />
                        <span>Download MP4</span>
                      </a>
                    ) : (
                      <button
                        type="button"
                        onClick={onGenerateFirstJob}
                        className="flex items-center justify-center gap-1.5 rounded border border-[#27272A] bg-[#18181B] px-2.5 py-1.5 text-xs font-medium text-[#A1A1AA] transition-colors hover:border-[#FAFAFA] hover:text-[#FAFAFA]"
                      >
                        <RotateCcw className="h-3.5 w-3.5" />
                        <span>Re-Run Job</span>
                      </button>
                    )}
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
};
