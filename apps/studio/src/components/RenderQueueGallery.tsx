'use client';

import React, { useMemo, useState } from 'react';
import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  Clock,
  Download,
  Eye,
  Film,
  Link,
  Play,
  RotateCcw,
  Trash2,
  XCircle,
} from 'lucide-react';
import { LANGUAGE_FONT_METADATA } from '@video-ad/remotion';
import type { JobStatus, VideoJobRecord, ViewStateMode } from '@/types/studio';

interface RenderQueueGalleryProps {
  jobs: VideoJobRecord[];
  activeJobId: string | null;
  isLoadingJobs: boolean;
  jobsError: string | null;
  viewStateMode: ViewStateMode;
  onSelectJobForPreview: (job: VideoJobRecord) => void;
  onRetryFetchJobs: () => void;
  onCancelJob: (jobId: string) => void;
  onRetryJob: (jobId: string) => void;
  onCopySignedUrl: (jobId: string) => void;
  onGenerateFirstJob: () => void;
  onClearLocalJobs: () => void;
}

const PIPELINE_STEPS: Array<{ key: string; label: string }> = [
  { key: 'CREATED', label: '01 QUEUED' },
  { key: 'PROCESSING', label: '02 AI + TTS' },
  { key: 'RENDERING', label: '03 FFMPEG' },
  { key: 'COMPLETED', label: '04 READY' },
];

function getStepProgressIndex(status: JobStatus): number {
  switch (status) {
    case 'CREATED':
    case 'QUEUED':
    case 'PENDING':
      return 1;
    case 'PROCESSING':
    case 'GENERATING_CLIPS':
      return 2;
    case 'RENDERING':
    case 'COMPOSITING':
      return 3;
    case 'COMPLETED':
      return 4;
    default:
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
  onCancelJob,
  onRetryJob,
  onCopySignedUrl,
  onGenerateFirstJob,
  onClearLocalJobs,
}) => {
  const [filterTab, setFilterTab] = useState<
    'ALL' | 'COMPLETED' | 'ACTIVE' | 'FAILED'
  >('ALL');

  const filteredJobs = useMemo(() => {
    if (filterTab === 'ALL') {
      return jobs;
    }
    if (filterTab === 'COMPLETED') {
      return jobs.filter((job) => job.status === 'COMPLETED');
    }
    if (filterTab === 'FAILED') {
      return jobs.filter(
        (job) => job.status === 'FAILED' || job.status === 'CANCELLED'
      );
    }
    return jobs.filter(
      (job) =>
        job.status !== 'COMPLETED' &&
        job.status !== 'FAILED' &&
        job.status !== 'CANCELLED'
    );
  }, [jobs, filterTab]);

  const showSkeleton = isLoadingJobs || viewStateMode === 'loading';
  const showError = Boolean(jobsError) || viewStateMode === 'error';
  const showEmpty =
    (!showSkeleton && filteredJobs.length === 0) || viewStateMode === 'empty';

  return (
    <section
      aria-label="Render Queue and MP4 Download Gallery"
      className="rounded border border-[#27272A] bg-[#18181B] p-4"
    >
      {/* Header & Filter Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#27272A] pb-3">
        <div className="flex items-center gap-2">
          <Film className="h-4 w-4 text-[#6366F1]" />
          <h2 className="text-sm font-semibold text-[#FAFAFA]">
            3. Workspace Render Queue & Private MP4 Downloads
          </h2>
          <span className="font-mono-code tabular-nums rounded border border-[#27272A] bg-[#09090B] px-2 py-0.5 text-[11px] font-semibold text-[#FAFAFA]">
            {jobs.length} JOBS
          </span>
        </div>

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
            onClick={onClearLocalJobs}
            className="flex items-center gap-1 rounded border border-[#27272A] bg-[#09090B] px-2.5 py-1 text-xs text-[#A1A1AA] transition-colors hover:border-red-500/60 hover:text-red-400"
          >
            <Trash2 className="h-3 w-3" />
            <span>Clear View</span>
          </button>
        </div>
      </div>

      {/* Inline Error Banner */}
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
                  'Could not fetch workspace video jobs from API. Verify sign-in and worker connectivity.'}
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

      {/* Main Content */}
      <div className="mt-4">
        {showSkeleton ? (
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
                </div>
              </div>
            ))}
          </div>
        ) : showEmpty ? (
          <div
            data-testid="queue-empty-state"
            className="flex flex-col items-center justify-center gap-3 rounded border border-[#27272A] bg-[#09090B] py-8 px-4 text-center"
          >
            <div className="flex h-10 w-10 items-center justify-center rounded border border-[#27272A] bg-[#18181B]">
              <Film className="h-5 w-5 text-[#6366F1]" />
            </div>
            <p className="text-xs text-[#A1A1AA]">
              No video renders in this workspace view yet. Confirm product
              details above and dispatch a render.
            </p>
            <button
              type="button"
              onClick={onGenerateFirstJob}
              className="flex items-center gap-1.5 rounded border border-[#6366F1] bg-[#6366F1] px-4 py-2 text-xs font-semibold text-[#FAFAFA] transition-colors hover:bg-[#5254E8]"
            >
              <Play className="h-3.5 w-3.5" />
              <span>Render Ad Job (1 Credit)</span>
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            {filteredJobs.map((job) => {
              const langMeta =
                LANGUAGE_FONT_METADATA[job.target_language] ??
                LANGUAGE_FONT_METADATA.ur;
              const isSelected = activeJobId === job.id;
              const progressIdx = getStepProgressIndex(job.status);
              const isTerminal =
                job.status === 'COMPLETED' ||
                job.status === 'FAILED' ||
                job.status === 'CANCELLED';

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
                  {/* Top Row */}
                  <div className="flex items-center justify-between gap-2 border-b border-[#27272A] pb-2.5">
                    <div className="flex items-center gap-1.5">
                      <span className="font-mono-code tabular-nums text-xs font-semibold text-[#FAFAFA]">
                        #{job.id.slice(0, 8)}
                      </span>
                      <span className="font-mono-code tabular-nums rounded border border-[#27272A] bg-[#18181B] px-1.5 py-0.5 text-[10px] font-semibold text-[#A1A1AA]">
                        {job.target_language.toUpperCase()} ·{' '}
                        {job.aspect_ratio ?? '9:16'}
                      </span>
                    </div>

                    {job.status === 'COMPLETED' ? (
                      <span className="font-mono-code tabular-nums flex items-center gap-1 rounded border border-[#6366F1] bg-[#18181B] px-2 py-0.5 text-[10px] font-semibold text-[#FAFAFA]">
                        <CheckCircle2 className="h-3 w-3 text-[#6366F1]" />
                        COMPLETED
                      </span>
                    ) : job.status === 'FAILED' || job.status === 'CANCELLED' ? (
                      <span className="font-mono-code tabular-nums flex items-center gap-1 rounded border border-red-500/60 bg-[#18181B] px-2 py-0.5 text-[10px] font-semibold text-red-400">
                        <XCircle className="h-3 w-3 text-red-400" />
                        {job.status} · REFUNDED
                      </span>
                    ) : (
                      <span className="font-mono-code tabular-nums flex items-center gap-1 rounded border border-[#27272A] bg-[#18181B] px-2 py-0.5 text-[10px] font-semibold text-[#A1A1AA]">
                        <Clock className="h-3 w-3 text-[#6366F1]" />
                        {job.status}
                      </span>
                    )}
                  </div>

                  {/* Step Progress Strip */}
                  <div className="grid grid-cols-4 gap-1">
                    {PIPELINE_STEPS.map((step, idx) => {
                      const stepNum = idx + 1;
                      const reached =
                        job.status !== 'FAILED' &&
                        job.status !== 'CANCELLED' &&
                        progressIdx >= stepNum;
                      return (
                        <div key={step.key} className="flex flex-col gap-1">
                          <div
                            className={`h-1 w-full rounded ${
                              job.status === 'FAILED' ||
                              job.status === 'CANCELLED'
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

                  {/* Middle Metadata */}
                  <div className="flex flex-col gap-1.5">
                    <div className="flex items-center justify-between text-xs">
                      <span className="truncate font-semibold text-[#FAFAFA]">
                        {job.script_json?.brand ?? 'Workspace Ad'}
                      </span>
                      <span className="font-mono-code tabular-nums text-xs font-semibold text-[#6366F1]">
                        {job.script_json?.price_badge ?? '—'}
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

                    {job.error_message || job.stage_detail ? (
                      <p
                        className={`truncate text-[10px] ${
                          job.status === 'FAILED'
                            ? 'text-red-400'
                            : 'text-[#A1A1AA]'
                        }`}
                      >
                        {job.error_message ?? job.stage_detail}
                      </p>
                    ) : null}

                    <div className="flex items-center justify-between text-[10px] text-[#A1A1AA]">
                      <span className="font-mono-code tabular-nums truncate max-w-[190px]">
                        {job.veo_gcs_uri ?? 'Workspace private storage'}
                      </span>
                      <span className="font-mono-code tabular-nums">
                        {createdTime}
                      </span>
                    </div>
                  </div>

                  {/* Bottom Actions */}
                  <div className="flex flex-wrap gap-2 border-t border-[#27272A] pt-2.5">
                    <button
                      type="button"
                      onClick={() => onSelectJobForPreview(job)}
                      className="flex flex-1 items-center justify-center gap-1.5 rounded border border-[#27272A] bg-[#18181B] px-2.5 py-1.5 text-xs font-medium text-[#FAFAFA] transition-colors hover:border-[#6366F1]"
                    >
                      <Eye className="h-3.5 w-3.5 text-[#6366F1]" />
                      <span>Preview</span>
                    </button>

                    {job.status === 'COMPLETED' && job.final_mp4_url ? (
                      <>
                        <a
                          href={job.final_mp4_url}
                          download={`localized-ad-${job.id.slice(0, 8)}.mp4`}
                          className="flex flex-1 items-center justify-center gap-1.5 rounded border border-[#6366F1] bg-[#6366F1] px-2.5 py-1.5 text-xs font-semibold text-[#FAFAFA] transition-colors hover:bg-[#5254E8]"
                        >
                          <Download className="h-3.5 w-3.5" />
                          <span>MP4</span>
                        </a>
                        <button
                          type="button"
                          onClick={() => onCopySignedUrl(job.id)}
                          title="Copy Signed Download URL"
                          aria-label="Copy Signed Download URL"
                          className="flex items-center justify-center rounded border border-[#27272A] bg-[#18181B] px-2 py-1.5 text-xs text-[#A1A1AA] hover:border-[#6366F1] hover:text-[#FAFAFA]"
                        >
                          <Link className="h-3.5 w-3.5" />
                        </button>
                      </>
                    ) : !isTerminal ? (
                      <button
                        type="button"
                        onClick={() => onCancelJob(job.id)}
                        className="flex flex-1 items-center justify-center gap-1.5 rounded border border-red-500/60 bg-[#18181B] px-2.5 py-1.5 text-xs font-medium text-red-400 hover:bg-red-500/10"
                      >
                        <Ban className="h-3.5 w-3.5" />
                        <span>Cancel & Refund</span>
                      </button>
                    ) : (
                      <button
                        type="button"
                        onClick={() => onRetryJob(job.id)}
                        className="flex flex-1 items-center justify-center gap-1.5 rounded border border-[#27272A] bg-[#18181B] px-2.5 py-1.5 text-xs font-medium text-[#A1A1AA] transition-colors hover:border-[#FAFAFA] hover:text-[#FAFAFA]"
                      >
                        <RotateCcw className="h-3.5 w-3.5" />
                        <span>Retry Job</span>
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
