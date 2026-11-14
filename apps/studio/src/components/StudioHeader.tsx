'use client';

import React from 'react';
import {
  Coins,
  Database,
  Layers,
  Plus,
  RefreshCw,
  ShieldCheck,
  Terminal,
} from 'lucide-react';
import { getSupabaseConnectionInfo } from '@/lib/supabase';
import type { ViewStateMode } from '@/types/studio';

interface StudioHeaderProps {
  workspaceId: string;
  creditBalance: number;
  isLoadingCredits: boolean;
  totalJobsCount: number;
  completedJobsCount: number;
  viewStateMode: ViewStateMode;
  onChangeViewStateMode: (mode: ViewStateMode) => void;
  onOpenCreditModal: () => void;
  onRefreshAll: () => void;
}

const VIEW_MODES: readonly { id: ViewStateMode; label: string }[] = [
  { id: 'normal', label: 'Live View' },
  { id: 'loading', label: 'Skeleton' },
  { id: 'empty', label: 'Empty State' },
  { id: 'error', label: 'Error State' },
] as const;

export const StudioHeader: React.FC<StudioHeaderProps> = ({
  workspaceId,
  creditBalance,
  isLoadingCredits,
  totalJobsCount,
  completedJobsCount,
  viewStateMode,
  onChangeViewStateMode,
  onOpenCreditModal,
  onRefreshAll,
}) => {
  const supabaseInfo = getSupabaseConnectionInfo();
  const shortWorkspaceId = `${workspaceId.slice(0, 8)}…${workspaceId.slice(-4)}`;

  return (
    <header className="w-full border-b border-[#27272A] bg-[#18181B]">
      <div className="mx-auto flex max-w-[1200px] flex-wrap items-center justify-between gap-3 px-6 py-3">
        {/* Left: Brand Identity + Workspace Telemetry */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded border border-[#6366F1] bg-[#09090B]">
              <Terminal className="h-4 w-4 text-[#6366F1]" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold tracking-tight text-[#FAFAFA]">
                  VEO 3.1 · D2C AD STUDIO
                </span>
                <span className="font-mono-code tabular-nums rounded border border-[#27272A] bg-[#09090B] px-2 py-0.5 text-[11px] font-medium text-[#A1A1AA]">
                  9:16 RTL/LTR
                </span>
              </div>
              <p className="text-xs text-[#A1A1AA]">
                Non-English D2C Video Ad Pipeline · Veo 3.1 + Remotion
              </p>
            </div>
          </div>

          {/* Workspace UUID Badge */}
          <div
            title={`Workspace UUID: ${workspaceId}`}
            className="hidden items-center gap-2 rounded border border-[#27272A] bg-[#09090B] px-3 py-1.5 md:flex"
          >
            <Database className="h-3.5 w-3.5 text-[#6366F1]" />
            <span className="text-xs text-[#A1A1AA]">WS</span>
            <span className="font-mono-code tabular-nums text-xs text-[#FAFAFA]">
              {shortWorkspaceId}
            </span>
          </div>

          {/* Supabase Auth & Ledger Status */}
          <div
            title={supabaseInfo.projectUrl}
            className="hidden items-center gap-1.5 rounded border border-[#27272A] bg-[#09090B] px-2.5 py-1.5 lg:flex"
          >
            <ShieldCheck className="h-3.5 w-3.5 text-[#6366F1]" />
            <span className="font-mono-code tabular-nums text-[11px] text-[#A1A1AA]">
              {supabaseInfo.modeLabel}
            </span>
          </div>
        </div>

        {/* Right: State Inspector Toggle + Queue Telemetry + Atomic Credit Balance + Top Up */}
        <div className="flex flex-wrap items-center gap-3">
          {/* View State Inspector (Normal / Skeleton / Empty / Error) */}
          <div
            className="flex items-center gap-1 rounded border border-[#27272A] bg-[#09090B] p-1"
            role="group"
            aria-label="UI State Inspector"
          >
            <Layers className="ml-1.5 mr-1 h-3.5 w-3.5 text-[#A1A1AA]" />
            {VIEW_MODES.map((mode) => {
              const active = viewStateMode === mode.id;
              return (
                <button
                  key={mode.id}
                  type="button"
                  onClick={() => onChangeViewStateMode(mode.id)}
                  className={`rounded px-2 py-1 text-xs font-medium transition-colors ${
                    active
                      ? 'bg-[#6366F1] text-[#FAFAFA]'
                      : 'text-[#A1A1AA] hover:text-[#FAFAFA]'
                  }`}
                >
                  {mode.label}
                </button>
              );
            })}
          </div>

          {/* Render Count Pill */}
          <div className="hidden items-center gap-2 rounded border border-[#27272A] bg-[#09090B] px-3 py-1.5 sm:flex">
            <span className="text-xs text-[#A1A1AA]">Renders</span>
            <span className="font-mono-code tabular-nums text-xs font-semibold text-[#FAFAFA]">
              {completedJobsCount}/{totalJobsCount}
            </span>
          </div>

          {/* Credit Balance Pill */}
          <div className="flex items-center gap-2 rounded border border-[#27272A] bg-[#09090B] px-3 py-1.5">
            <Coins className="h-3.5 w-3.5 text-[#6366F1]" />
            <span className="text-xs text-[#A1A1AA]">Credits</span>
            {isLoadingCredits || viewStateMode === 'loading' ? (
              <span className="inline-block h-4 w-8 animate-pulse rounded bg-[#27272A]" />
            ) : (
              <span
                data-testid="credit-balance-value"
                className={`font-mono-code tabular-nums text-xs font-bold ${
                  creditBalance === 0 ? 'text-red-400' : 'text-[#FAFAFA]'
                }`}
              >
                {creditBalance}
              </span>
            )}
          </div>

          {/* Top Up Credits Trigger */}
          <button
            type="button"
            onClick={onOpenCreditModal}
            className="flex items-center gap-1.5 rounded border border-[#6366F1] bg-[#6366F1] px-3 py-1.5 text-xs font-semibold text-[#FAFAFA] transition-colors hover:bg-[#5254E8]"
          >
            <Plus className="h-3.5 w-3.5" />
            <span>Top Up Credits</span>
          </button>

          {/* Refresh Telemetry Button */}
          <button
            type="button"
            onClick={onRefreshAll}
            title="Sync Workspace & Render Queue"
            className="flex h-8 w-8 items-center justify-center rounded border border-[#27272A] bg-[#09090B] text-[#A1A1AA] transition-colors hover:border-[#FAFAFA] hover:text-[#FAFAFA]"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </header>
  );
};
