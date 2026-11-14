'use client';

import React, { useState } from 'react';
import {
  Building2,
  Coins,
  Film,
  Layers,
  LogOut,
  Plus,
  RefreshCw,
  ShieldCheck,
  UserCheck,
} from 'lucide-react';
import type {
  AuthUserSummary,
  ViewStateMode,
  WorkspaceSummary,
} from '@/types/studio';

interface StudioHeaderProps {
  user: AuthUserSummary | null;
  workspaces: WorkspaceSummary[];
  activeWorkspaceId: string;
  onSelectWorkspace: (workspaceId: string) => void;
  onCreateWorkspace: (name: string) => Promise<void>;
  onOpenAuthModal: (mode?: 'login' | 'register' | 'verify_email') => void;
  onLogout: () => Promise<void>;
  creditBalance: number;
  isLoadingCredits: boolean;
  totalJobsCount: number;
  completedJobsCount: number;
  viewStateMode: ViewStateMode;
  onChangeViewStateMode: (mode: ViewStateMode) => void;
  onOpenCreditModal: () => void;
  onRefreshAll: () => void;
}

const VIEW_MODES: Array<{ id: ViewStateMode; label: string }> = [
  { id: 'normal', label: 'Live' },
  { id: 'loading', label: 'Skeleton' },
  { id: 'empty', label: 'Empty' },
  { id: 'error', label: 'Error' },
];

export const StudioHeader: React.FC<StudioHeaderProps> = ({
  user,
  workspaces,
  activeWorkspaceId,
  onSelectWorkspace,
  onCreateWorkspace,
  onOpenAuthModal,
  onLogout,
  creditBalance,
  isLoadingCredits,
  totalJobsCount,
  completedJobsCount,
  viewStateMode,
  onChangeViewStateMode,
  onOpenCreditModal,
  onRefreshAll,
}) => {
  const [isCreatingWs, setIsCreatingWs] = useState(false);
  const [newWsName, setNewWsName] = useState('');

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = newWsName.trim();
    if (!trimmed) {
      return;
    }
    await onCreateWorkspace(trimmed);
    setNewWsName('');
    setIsCreatingWs(false);
  };

  return (
    <header className="sticky top-0 z-30 border-b border-[#27272A] bg-[#18181B]">
      <div className="mx-auto flex max-w-[1200px] flex-wrap items-center justify-between gap-4 px-6 py-3">
        {/* Brand Identity & Workspace Selector */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded border border-[#27272A] bg-[#09090B]">
            <Film className="h-4 w-4 text-[#6366F1]" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-sm font-semibold tracking-tight text-[#FAFAFA]">
                Localized Ad Studio
              </h1>
              <span className="font-mono-code rounded border border-[#27272A] bg-[#09090B] px-1.5 py-0.5 text-[10px] font-medium text-[#6366F1]">
                VEO 3.1 + REMOTION
              </span>
            </div>

            <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-[#A1A1AA]">
              <Building2 className="h-3 w-3 text-[#6366F1]" />
              {user && workspaces.length > 0 ? (
                <select
                  aria-label="Active Workspace"
                  value={activeWorkspaceId}
                  onChange={(e) => onSelectWorkspace(e.target.value)}
                  className="font-mono-code rounded border border-[#27272A] bg-[#09090B] px-2 py-0.5 text-[11px] text-[#FAFAFA] focus:border-[#6366F1] focus:outline-none"
                >
                  {workspaces.map((ws) => (
                    <option key={ws.id} value={ws.id}>
                      {ws.name} ({ws.role.toUpperCase()} · {ws.id.slice(0, 8)})
                    </option>
                  ))}
                </select>
              ) : (
                <span className="font-mono-code text-[11px] text-[#A1A1AA]">
                  UNAUTHENTICATED
                </span>
              )}

              {user ? (
                <button
                  type="button"
                  onClick={() => setIsCreatingWs((prev) => !prev)}
                  className="rounded border border-[#27272A] bg-[#09090B] px-1.5 py-0.5 text-[10px] text-[#A1A1AA] hover:border-[#6366F1] hover:text-[#FAFAFA]"
                >
                  + Workspace
                </button>
              ) : null}
            </div>
          </div>
        </div>

        {/* Inline New Workspace Form */}
        {isCreatingWs ? (
          <form
            onSubmit={(e) => void handleCreateSubmit(e)}
            className="flex items-center gap-1.5"
          >
            <input
              type="text"
              value={newWsName}
              onChange={(e) => setNewWsName(e.target.value)}
              placeholder="New Brand Workspace"
              className="rounded border border-[#27272A] bg-[#09090B] px-2.5 py-1 text-xs text-[#FAFAFA] focus:border-[#6366F1] focus:outline-none"
            />
            <button
              type="submit"
              className="rounded border border-[#6366F1] bg-[#6366F1] px-2.5 py-1 text-xs font-semibold text-[#FAFAFA]"
            >
              Create
            </button>
          </form>
        ) : null}

        {/* Right Telemetry & Actions */}
        <div className="flex flex-wrap items-center gap-2.5">
          {/* UI State Preview Toggle */}
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
                {user ? creditBalance : '—'}
              </span>
            )}
          </div>

          {/* Top Up Credits Trigger */}
          <button
            type="button"
            disabled={!user}
            onClick={onOpenCreditModal}
            className="flex items-center gap-1.5 rounded border border-[#6366F1] bg-[#6366F1] px-3 py-1.5 text-xs font-semibold text-[#FAFAFA] transition-colors hover:bg-[#5254E8] disabled:opacity-50"
          >
            <Plus className="h-3.5 w-3.5" />
            <span>Buy Credits</span>
          </button>

          {/* Refresh Telemetry Button */}
          <button
            type="button"
            disabled={!user}
            onClick={onRefreshAll}
            title="Sync Workspace & Render Queue"
            className="flex h-8 w-8 items-center justify-center rounded border border-[#27272A] bg-[#09090B] text-[#A1A1AA] transition-colors hover:border-[#FAFAFA] hover:text-[#FAFAFA] disabled:opacity-50"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>

          {/* Auth User Pill / Sign Out */}
          {user ? (
            <div className="flex items-center gap-1.5 rounded border border-[#27272A] bg-[#09090B] px-2.5 py-1">
              <UserCheck className="h-3.5 w-3.5 text-[#6366F1]" />
              <span className="max-w-[130px] truncate text-xs text-[#FAFAFA]">
                {user.email}
              </span>
              {!user.is_email_verified ? (
                <button
                  type="button"
                  onClick={() => onOpenAuthModal('verify_email')}
                  className="font-mono-code rounded border border-amber-500/60 px-1.5 py-0.5 text-[10px] text-amber-400 hover:bg-amber-500/10"
                >
                  VERIFY
                </button>
              ) : (
                <ShieldCheck className="h-3.5 w-3.5 text-emerald-400" />
              )}
              <button
                type="button"
                onClick={() => void onLogout()}
                title="Sign out"
                className="ml-1 text-[#A1A1AA] hover:text-red-400"
              >
                <LogOut className="h-3.5 w-3.5" />
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => onOpenAuthModal('login')}
              className="rounded border border-[#27272A] bg-[#09090B] px-3 py-1.5 text-xs font-semibold text-[#FAFAFA] hover:border-[#6366F1]"
            >
              Sign In
            </button>
          )}
        </div>
      </div>
    </header>
  );
};
