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
  { key: 'CREATED', label: 'Queued' },
  { key: 'PROCESSING', label: 'AI + TTS' },
  { key: 'RENDERING', label: 'Render' },
  { key: 'COMPLETED', label: 'Ready' },
];

const FILTER_TABS: Array<{
  id: 'ALL' | 'COMPLETED' | 'ACTIVE' | 'FAILED';
  label: string;
}> = [
  { id: 'ALL', label: 'All' },
  { id: 'COMPLETED', label: 'Completed' },
  { id: 'ACTIVE', label: 'Active' },
  { id: 'FAILED', label: 'Failed' },
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
      aria-label="Recent Videos and Downloads"
      className="rounded-2xl border border-[#E6E0D5] bg-white p-5 shadow-[0_1px_2px_rgba(28,25,23,0.04)]"
    >
      {/* Header & Filter Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#E6E0D5] pb-3.5">
        <div className="flex items-center gap-2.5">
          <h2 className="text-base font-semibold text-[#1C1917]">
            Recent Videos
          </h2>
          <span className="font-mono-code tabular-nums rounded-full bg-[#F4EFE6] px-2.5 py-0.5 text-[11px] font-medium text-[#57534E]">
            {jobs.length} {jobs.length === 1 ? 'video' : 'videos'}
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="flex flex-wrap items-center gap-1 rounded-full bg-[#F4EFE6] p-1">
            {FILTER_TABS.map((tab) => {
              const active = filterTab === tab.id;
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setFilterTab(tab.id)}
                  className={`min-h-[32px] rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                    active
                      ? 'bg-[#15803D] text-white'
                      : 'text-[#57534E] hover:text-[#1C1917]'
                  }`}
                >
                  {tab.label}
                </button>
              );
            })}
          </div>

          <button
            type="button"
            onClick={onClearLocalJobs}
            title="Clear videos from current screen view (does not delete server records)"
            className="flex min-h-[34px] items-center gap-1.5 rounded-full border border-[#E6E0D5] bg-[#FAF7F2] px-3 py-1 text-xs font-medium text-[#57534E] transition-colors hover:border-[#B91C1C] hover:bg-[#FEF2F2] hover:text-[#B91C1C]"
          >
            <Trash2 className="h-3 w-3" />
            <span>Hide list</span>
          </button>
        </div>
      </div>

      {/* Inline Error Banner */}
      {showError ? (
        <div
          role="alert"
          data-testid="queue-error-banner"
          className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[#FECACA] bg-[#FEF2F2] p-3.5"
        >
          <div className="flex items-center gap-2.5">
            <AlertTriangle className="h-4 w-4 shrink-0 text-[#B91C1C]" />
            <div>
              <p className="text-xs font-semibold text-[#B91C1C]">
                Could not load your videos
              </p>
              <p className="text-xs text-[#57534E]">
                {jobsError ??
                  'Unable to reach the video service right now. Check your connection and retry.'}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onRetryFetchJobs}
            className="flex min-h-[36px] items-center gap-1.5 rounded-full border border-[#FECACA] bg-white px-3.5 py-1.5 text-xs font-semibold text-[#1C1917] transition-colors hover:border-[#15803D] hover:text-[#166534]"
          >
            <RotateCcw className="h-3.5 w-3.5 text-[#166534]" />
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
                className="flex h-[200px] flex-col justify-between rounded-2xl border border-[#E6E0D5] bg-[#FAF7F2] p-4"
              >
                <div className="flex items-center justify-between">
                  <div className="h-4 w-28 animate-pulse rounded-full bg-[#E6E0D5]" />
                  <div className="h-5 w-20 animate-pulse rounded-full bg-[#E6E0D5]" />
                </div>
                <div className="flex flex-col gap-2">
                  <div className="h-4 w-3/4 animate-pulse rounded-full bg-[#E6E0D5]" />
                  <div className="h-10 w-full animate-pulse rounded-xl bg-white" />
                </div>
              </div>
            ))}
          </div>
        ) : showEmpty ? (
          <div
            data-testid="queue-empty-state"
            className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-[#E6E0D5] bg-[#FAF7F2] px-4 py-10 text-center"
          >
            <div className="flex h-11 w-11 items-center justify-center rounded-full border border-[#BBF7D0] bg-[#F0FDF4]">
              <Film className="h-5 w-5 text-[#166534]" />
            </div>
            <p className="max-w-sm text-xs text-[#57534E]">
              No videos in this view yet. Confirm your product details above and
              generate your first localized ad.
            </p>
            <button
              type="button"
              onClick={onGenerateFirstJob}
              className="flex min-h-[40px] items-center gap-1.5 rounded-full bg-[#15803D] px-5 py-2 text-xs font-semibold text-white transition-colors hover:bg-[#166534]"
            >
              <Play className="h-3.5 w-3.5" />
              <span>Create First Video (1 Credit)</span>
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
                  className={`flex min-w-0 flex-col justify-between gap-3 rounded-2xl border p-4 transition-colors ${
                    isSelected
                      ? 'border-[#15803D] bg-[#F0FDF4]/40'
                      : 'border-[#E6E0D5] bg-[#FAF7F2] hover:border-[#D6CEC0]'
                  }`}
                >
                  {/* Top Row: Brand, Price & Clean Status Pill */}
                  <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#E6E0D5] pb-2.5">
                    <div className="min-w-0">
                      <span className="block truncate text-xs font-semibold text-[#1C1917]">
                        {job.script_json?.brand ?? 'Workspace Ad'}
                      </span>
                      <span className="font-mono-code tabular-nums text-[11px] font-semibold text-[#166534]">
                        {job.script_json?.price_badge ?? '—'}
                      </span>
                    </div>

                    {job.status === 'COMPLETED' ? (
                      <span className="flex shrink-0 items-center gap-1 rounded-full border border-[#BBF7D0] bg-[#F0FDF4] px-2.5 py-0.5 text-[11px] font-semibold text-[#166534]">
                        <CheckCircle2 className="h-3 w-3" />
                        Completed
                      </span>
                    ) : job.status === 'FAILED' || job.status === 'CANCELLED' ? (
                      <span className="flex shrink-0 items-center gap-1 rounded-full border border-[#FECACA] bg-[#FEF2F2] px-2.5 py-0.5 text-[11px] font-semibold text-[#B91C1C]">
                        <XCircle className="h-3 w-3" />
                        {job.status === 'FAILED'
                          ? 'Failed · Refunded'
                          : 'Cancelled · Refunded'}
                      </span>
                    ) : (
                      <span className="flex shrink-0 items-center gap-1 rounded-full border border-[#FDE68A] bg-[#FFFBEB] px-2.5 py-0.5 text-[11px] font-semibold text-[#92400E]">
                        <Clock className="h-3 w-3" />
                        In Progress
                      </span>
                    )}
                  </div>

                  {/* Step Progress Strip shown only while rendering */}
                  {!isTerminal ? (
                    <div className="grid grid-cols-4 gap-1.5">
                      {PIPELINE_STEPS.map((step, idx) => {
                        const reached = progressIdx >= idx + 1;
                        return (
                          <div key={step.key} className="flex flex-col gap-1">
                            <div
                              className={`h-1.5 w-full rounded-full ${
                                reached ? 'bg-[#15803D]' : 'bg-[#E6E0D5]'
                              }`}
                            />
                            <span className="text-[10px] font-medium text-[#57534E]">
                              {step.label}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  ) : null}

                  {/* Script Hook Snippet */}
                  <div className="flex flex-col gap-2">
                    <p
                      dir={langMeta.dir}
                      className={`${scriptClassName} line-clamp-2 rounded-xl border border-[#E6E0D5] bg-white px-3 py-2 text-xs text-[#1C1917]`}
                    >
                      {job.script_json?.hook ??
                        job.script_json?.product_title ??
                        job.product_url}
                    </p>

                    {job.status === 'FAILED' && job.error_message ? (
                      <p className="truncate text-[11px] font-medium text-[#B91C1C]">
                        {job.error_message}
                      </p>
                    ) : null}

                    <div className="flex items-center justify-between gap-2 text-[11px] text-[#57534E]">
                      <span className="font-mono-code tabular-nums">
                        {job.target_language.toUpperCase()} ·{' '}
                        {job.aspect_ratio ?? '9:16'}
                      </span>
                      <span className="font-mono-code tabular-nums">
                        {createdTime}
                      </span>
                    </div>
                  </div>

                  {/* Rounded Pill Bottom Actions */}
                  <div className="flex flex-wrap gap-2 border-t border-[#E6E0D5] pt-3">
                    <button
                      type="button"
                      onClick={() => onSelectJobForPreview(job)}
                      className="flex min-h-[36px] flex-1 items-center justify-center gap-1.5 rounded-full border border-[#D6CEC0] bg-white px-3 py-1.5 text-xs font-medium text-[#1C1917] transition-colors hover:border-[#15803D] hover:text-[#166534]"
                    >
                      <Eye className="h-3.5 w-3.5 text-[#166534]" />
                      <span>Preview</span>
                    </button>

                    {job.status === 'COMPLETED' && job.final_mp4_url ? (
                      <>
                        <a
                          href={job.final_mp4_url}
                          download={`localized-ad-${job.id.slice(0, 8)}.mp4`}
                          className="flex min-h-[36px] flex-1 items-center justify-center gap-1.5 rounded-full bg-[#15803D] px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-[#166534]"
                        >
                          <Download className="h-3.5 w-3.5" />
                          <span>MP4</span>
                        </a>
                        <button
                          type="button"
                          onClick={() => onCopySignedUrl(job.id)}
                          title="Copy signed download link"
                          aria-label="Copy Signed Download URL"
                          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-[#D6CEC0] bg-white text-[#57534E] transition-colors hover:border-[#15803D] hover:text-[#166534]"
                        >
                          <Link className="h-3.5 w-3.5" />
                        </button>
                      </>
                    ) : !isTerminal ? (
                      <button
                        type="button"
                        onClick={() => onCancelJob(job.id)}
                        className="flex min-h-[36px] flex-1 items-center justify-center gap-1.5 rounded-full border border-[#FECACA] bg-white px-3 py-1.5 text-xs font-semibold text-[#B91C1C] transition-colors hover:bg-[#FEF2F2]"
                      >
                        <Ban className="h-3.5 w-3.5" />
                        <span>Cancel &amp; Refund</span>
                      </button>
                    ) : (
                      <button
                        type="button"
                        onClick={() => onRetryJob(job.id)}
                        className="flex min-h-[36px] flex-1 items-center justify-center gap-1.5 rounded-full border border-[#D6CEC0] bg-white px-3 py-1.5 text-xs font-medium text-[#1C1917] transition-colors hover:border-[#15803D] hover:text-[#166534]"
                      >
                        <RotateCcw className="h-3.5 w-3.5 text-[#166534]" />
                        <span>Retry</span>
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
