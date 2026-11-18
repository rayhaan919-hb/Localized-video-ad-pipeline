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
    <header className="sticky top-0 z-30 border-b border-[#E6E0D5] bg-[#FAF7F2]/95 backdrop-blur">
      <div className="mx-auto flex max-w-[1200px] flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
        {/* Brand Identity & Workspace Selector */}
        <div className="flex min-w-0 flex-wrap items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-[#BBF7D0] bg-[#F0FDF4]">
            <Film className="h-4 w-4 text-[#166534]" />
          </div>
          <div className="min-w-0">
            <h1 className="text-sm font-semibold tracking-tight text-[#1C1917]">
              Localized Ad Studio
            </h1>

            <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-[#57534E]">
              <Building2 className="h-3.5 w-3.5 shrink-0 text-[#166534]" />
              {user && workspaces.length > 0 ? (
                <select
                  aria-label="Active Workspace"
                  value={activeWorkspaceId}
                  onChange={(e) => onSelectWorkspace(e.target.value)}
                  className="min-h-[34px] max-w-[180px] truncate rounded-full border border-[#E6E0D5] bg-white px-3 py-1 text-xs font-medium text-[#1C1917] focus:border-[#15803D] focus:outline-none sm:max-w-[210px]"
                >
                  {workspaces.map((ws) => (
                    <option key={ws.id} value={ws.id}>
                      {ws.name}
                    </option>
                  ))}
                </select>
              ) : (
                <span className="text-[11px] text-[#57534E]">
                  Sign in to select workspace
                </span>
              )}

              {user ? (
                <button
                  type="button"
                  onClick={() => setIsCreatingWs((prev) => !prev)}
                  className="min-h-[34px] rounded-full border border-[#E6E0D5] bg-white px-3 py-1 text-xs font-medium text-[#57534E] transition-colors hover:border-[#15803D] hover:text-[#166534]"
                >
                  + New
                </button>
              ) : null}
            </div>
          </div>
        </div>

        {/* Inline New Workspace Form */}
        {isCreatingWs ? (
          <form
            onSubmit={(e) => void handleCreateSubmit(e)}
            className="flex flex-wrap items-center gap-1.5"
          >
            <input
              type="text"
              aria-label="New Workspace Name"
              value={newWsName}
              onChange={(e) => setNewWsName(e.target.value)}
              placeholder="New brand workspace"
              className="min-h-[34px] rounded-full border border-[#D6CEC0] bg-white px-3.5 py-1 text-xs text-[#1C1917] placeholder-[#6E6A63] focus:border-[#15803D] focus:outline-none"
            />
            <button
              type="submit"
              className="min-h-[34px] rounded-full bg-[#15803D] px-3.5 py-1 text-xs font-semibold text-white transition-colors hover:bg-[#166534]"
            >
              Create
            </button>
          </form>
        ) : null}

        {/* Right Credits & User Controls */}
        <div className="flex flex-wrap items-center gap-2">
          {/* UI State Preview Toggle (dev/test only) */}
          {process.env.NODE_ENV !== 'production' ? (
            <div
              className="flex items-center gap-1 rounded-full border border-[#E6E0D5] bg-[#F4EFE6] p-1"
              role="group"
              aria-label="UI State Inspector"
            >
              <Layers className="ml-1.5 mr-1 h-3.5 w-3.5 text-[#57534E]" />
              {VIEW_MODES.map((mode) => {
                const active = viewStateMode === mode.id;
                return (
                  <button
                    key={mode.id}
                    type="button"
                    onClick={() => onChangeViewStateMode(mode.id)}
                    className={`min-h-[28px] rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors ${
                      active
                        ? 'bg-[#15803D] text-white'
                        : 'text-[#57534E] hover:text-[#1C1917]'
                    }`}
                  >
                    {mode.label}
                  </button>
                );
              })}
            </div>
          ) : null}

          {/* Credit Balance Pill */}
          <div className="flex min-h-[36px] items-center gap-1.5 rounded-full border border-[#E6E0D5] bg-white px-3.5 py-1.5">
            <Coins className="h-3.5 w-3.5 text-[#166534]" />
            <span className="text-xs text-[#57534E]">Credits</span>
            {isLoadingCredits || viewStateMode === 'loading' ? (
              <span className="inline-block h-4 w-7 animate-pulse rounded-full bg-[#E6E0D5]" />
            ) : (
              <span
                data-testid="credit-balance-value"
                className={`font-mono-code tabular-nums text-xs font-bold ${
                  creditBalance === 0 ? 'text-[#B91C1C]' : 'text-[#1C1917]'
                }`}
              >
                {user ? creditBalance : '—'}
              </span>
            )}
          </div>

          {/* Primary Top Up Credits Trigger */}
          <button
            type="button"
            disabled={!user}
            onClick={onOpenCreditModal}
            className="flex min-h-[38px] items-center gap-1.5 rounded-full bg-[#15803D] px-4 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-[#166534] disabled:opacity-50"
          >
            <Plus className="h-3.5 w-3.5" />
            <span>Buy Credits</span>
          </button>

          {/* Refresh Telemetry Button */}
          <button
            type="button"
            disabled={!user}
            onClick={onRefreshAll}
            title="Sync workspace & videos"
            aria-label="Sync Workspace and Render Queue"
            className="flex h-9 w-9 items-center justify-center rounded-full border border-[#E6E0D5] bg-white text-[#57534E] transition-colors hover:border-[#15803D] hover:text-[#166534] disabled:opacity-50"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>

          {/* Auth User Pill / Sign Out */}
          {user ? (
            <div className="flex min-h-[36px] max-w-full items-center gap-1.5 rounded-full border border-[#E6E0D5] bg-white px-3 py-1">
              <UserCheck className="h-3.5 w-3.5 shrink-0 text-[#166534]" />
              <span className="max-w-[120px] truncate text-xs font-medium text-[#1C1917]">
                {user.email}
              </span>
              {!user.is_email_verified ? (
                <button
                  type="button"
                  onClick={() => onOpenAuthModal('verify_email')}
                  className="min-h-[26px] rounded-full border border-[#FDE68A] bg-[#FFFBEB] px-2 py-0.5 text-[10px] font-semibold text-[#92400E] hover:bg-[#FEF3C7]"
                >
                  Verify
                </button>
              ) : (
                <ShieldCheck className="h-3.5 w-3.5 shrink-0 text-[#15803D]" />
              )}
              <button
                type="button"
                onClick={() => void onLogout()}
                title="Sign out"
                aria-label="Sign out"
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[#57534E] transition-colors hover:bg-[#FEF2F2] hover:text-[#B91C1C]"
              >
                <LogOut className="h-3.5 w-3.5" />
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => onOpenAuthModal('login')}
              className="min-h-[38px] rounded-full border border-[#D6CEC0] bg-white px-4 py-1.5 text-xs font-semibold text-[#1C1917] transition-colors hover:border-[#15803D] hover:text-[#166534]"
            >
              Sign In
            </button>
          )}
        </div>
      </div>
    </header>
  );
};
