'use client';

import React from 'react';
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  Check,
  Coins,
  CreditCard,
  History,
  RotateCcw,
  ShieldCheck,
  Wrench,
  X,
} from 'lucide-react';
import { CREDIT_PACKAGE_TIERS } from '@/lib/supabase';
import type { CreditLedgerEntry, ViewStateMode } from '@/types/studio';

interface CreditCheckoutModalProps {
  isOpen: boolean;
  onClose: () => void;
  workspaceId: string;
  creditBalance: number;
  ledger: CreditLedgerEntry[];
  isLoadingCredits: boolean;
  isCheckingOutPackId: string | null;
  creditsError: string | null;
  viewStateMode: ViewStateMode;
  onCheckoutCredits: (packId: string) => void;
  onDevTopup?: (packId: string) => void;
  onRetryFetchCredits: () => void;
}

export const CreditCheckoutModal: React.FC<CreditCheckoutModalProps> = ({
  isOpen,
  onClose,
  workspaceId,
  creditBalance,
  ledger,
  isLoadingCredits,
  isCheckingOutPackId,
  creditsError,
  viewStateMode,
  onCheckoutCredits,
  onDevTopup,
  onRetryFetchCredits,
}) => {
  if (!isOpen) {
    return null;
  }

  const showSkeleton = isLoadingCredits || viewStateMode === 'loading';
  const showError = Boolean(creditsError) || viewStateMode === 'error';
  const showEmpty =
    (!showSkeleton && ledger.length === 0) || viewStateMode === 'empty';

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Workspace Credit Billing and Ledger"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4"
    >
      <div className="max-h-[90vh] w-full max-w-4xl overflow-y-auto rounded border border-[#27272A] bg-[#18181B] p-6">
        {/* Modal Header */}
        <div className="flex items-start justify-between border-b border-[#27272A] pb-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded border border-[#27272A] bg-[#09090B]">
              <CreditCard className="h-5 w-5 text-[#6366F1]" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-[#FAFAFA]">
                Workspace Credit Billing & Atomic Ledger
              </h2>
              <p className="font-mono-code tabular-nums text-xs text-[#A1A1AA]">
                WORKSPACE {workspaceId}
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            aria-label="Close billing modal"
            className="rounded border border-[#27272A] bg-[#09090B] p-1.5 text-[#A1A1AA] transition-colors hover:border-[#FAFAFA] hover:text-[#FAFAFA]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Balance Banner */}
        <div className="mt-4 flex flex-wrap items-center justify-between gap-4 rounded border border-[#27272A] bg-[#09090B] p-4">
          <div className="flex items-center gap-3">
            <Coins className="h-5 w-5 text-[#6366F1]" />
            <div>
              <span className="block text-xs text-[#A1A1AA]">
                Available Render Balance
              </span>
              <span className="font-mono-code tabular-nums text-xl font-bold text-[#FAFAFA]">
                {creditBalance} Credits
              </span>
            </div>
          </div>

          <div className="flex items-center gap-2 rounded border border-[#27272A] bg-[#18181B] px-3 py-1.5 text-xs text-[#A1A1AA]">
            <ShieldCheck className="h-4 w-4 text-[#6366F1]" />
            <span>
              Credits are granted strictly after verified Stripe webhook
              settlement.
            </span>
          </div>
        </div>

        {/* Error Banner */}
        {showError ? (
          <div
            role="alert"
            className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded border border-red-500/60 bg-[#09090B] p-3"
          >
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-red-400" />
              <p className="text-xs text-[#FAFAFA]">
                {creditsError ??
                  'Failed to synchronize workspace credit ledger.'}
              </p>
            </div>
            <button
              type="button"
              onClick={onRetryFetchCredits}
              className="flex items-center gap-1.5 rounded border border-[#27272A] bg-[#18181B] px-3 py-1 text-xs font-semibold text-[#FAFAFA] hover:border-[#6366F1]"
            >
              <RotateCcw className="h-3 w-3 text-[#6366F1]" />
              <span>Retry</span>
            </button>
          </div>
        ) : null}

        {/* Server-Authoritative Credit Packages */}
        <div className="mt-6">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-[#A1A1AA]">
              Stripe Checkout Packages (Server-Verified Pricing)
            </h3>
            <span className="font-mono-code tabular-nums text-xs text-[#A1A1AA]">
              IDEMPOTENT WEBHOOK GRANTS
            </span>
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            {CREDIT_PACKAGE_TIERS.map((tier) => {
              const isBusy = isCheckingOutPackId === tier.id;
              return (
                <div
                  key={tier.id}
                  className={`flex flex-col justify-between rounded border p-4 ${
                    tier.badge
                      ? 'border-[#6366F1] bg-[#09090B]'
                      : 'border-[#27272A] bg-[#09090B]'
                  }`}
                >
                  <div>
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-semibold text-[#FAFAFA]">
                        {tier.name}
                      </span>
                      {tier.badge ? (
                        <span className="font-mono-code rounded bg-[#6366F1] px-2 py-0.5 text-[10px] font-bold text-[#FAFAFA]">
                          {tier.badge}
                        </span>
                      ) : null}
                    </div>

                    <div className="mt-3 flex items-baseline gap-2">
                      <span className="font-mono-code tabular-nums text-2xl font-bold text-[#FAFAFA]">
                        +{tier.credits}
                      </span>
                      <span className="text-xs text-[#A1A1AA]">credits</span>
                    </div>

                    <div className="mt-1 flex items-center justify-between text-xs">
                      <span className="font-mono-code tabular-nums font-semibold text-[#6366F1]">
                        {tier.priceUsd}
                      </span>
                      <span className="font-mono-code tabular-nums text-[#A1A1AA]">
                        {tier.perCreditUsd}
                      </span>
                    </div>

                    <p className="mt-3 text-xs text-[#A1A1AA]">
                      {tier.description}
                    </p>
                  </div>

                  <div className="mt-4 flex flex-col gap-1.5">
                    <button
                      type="button"
                      disabled={Boolean(isCheckingOutPackId)}
                      onClick={() => onCheckoutCredits(tier.id)}
                      className="flex w-full items-center justify-center gap-1.5 rounded border border-[#6366F1] bg-[#6366F1] px-3 py-2 text-xs font-semibold text-[#FAFAFA] transition-colors hover:bg-[#5254E8] disabled:opacity-50"
                    >
                      <Check className="h-3.5 w-3.5" />
                      <span className="tabular-nums">
                        {isBusy
                          ? 'Redirecting to Stripe…'
                          : `Checkout ${tier.credits} Credits (${tier.priceUsd})`}
                      </span>
                    </button>

                    {onDevTopup && process.env.NODE_ENV !== 'production' ? (
                      <button
                        type="button"
                        disabled={Boolean(isCheckingOutPackId)}
                        onClick={() => onDevTopup(tier.id)}
                        className="flex w-full items-center justify-center gap-1 rounded border border-[#27272A] bg-[#18181B] px-2 py-1 text-[10px] text-[#A1A1AA] hover:border-[#6366F1] hover:text-[#FAFAFA]"
                      >
                        <Wrench className="h-3 w-3" />
                        <span>Dev Top-Up (requires ENABLE_DEV_TOPUP=true)</span>
                      </button>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Atomic Credit Ledger Audit Trail */}
        <div className="mt-6 border-t border-[#27272A] pt-4">
          <div className="mb-3 flex items-center justify-between">
            <span className="flex items-center gap-1.5 text-xs font-semibold text-[#FAFAFA]">
              <History className="h-3.5 w-3.5 text-[#6366F1]" />
              <span>Atomic Credit Ledger Audit Trail</span>
            </span>
            <span className="font-mono-code tabular-nums text-xs text-[#A1A1AA]">
              {ledger.length} TRANSACTIONS
            </span>
          </div>

          {showSkeleton ? (
            <div className="flex flex-col gap-2">
              {[0, 1, 2].map((idx) => (
                <div
                  key={idx}
                  className="h-9 w-full animate-pulse rounded border border-[#27272A] bg-[#09090B]"
                />
              ))}
            </div>
          ) : showEmpty ? (
            <div className="flex flex-col items-center justify-center gap-2 rounded border border-[#27272A] bg-[#09090B] p-6 text-center">
              <Coins className="h-5 w-5 text-[#6366F1]" />
              <p className="text-xs text-[#A1A1AA]">
                No credit ledger transactions recorded for this workspace yet.
              </p>
            </div>
          ) : (
            <div className="max-h-56 overflow-y-auto rounded border border-[#27272A] bg-[#09090B]">
              <table className="w-full border-collapse text-left text-xs">
                <thead>
                  <tr className="border-b border-[#27272A] bg-[#18181B] text-[11px] text-[#A1A1AA]">
                    <th className="py-2 px-3 font-medium">Type</th>
                    <th className="py-2 px-3 font-medium">Delta</th>
                    <th className="py-2 px-3 font-medium">Reason</th>
                    <th className="py-2 px-3 font-medium">Ref</th>
                    <th className="py-2 px-3 font-medium">Balance</th>
                    <th className="py-2 px-3 font-medium">Timestamp</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#27272A]">
                  {ledger.map((entry) => {
                    const isPositive = entry.delta > 0;
                    const refLabel = entry.job_id
                      ? `job:#${entry.job_id.slice(0, 8)}`
                      : entry.payment_id
                      ? `pay:${entry.payment_id.slice(0, 10)}`
                      : '—';
                    return (
                      <tr key={entry.id} className="hover:bg-[#18181B]/60">
                        <td className="font-mono-code py-2 px-3 text-[11px] text-[#A1A1AA]">
                          {entry.transaction_type ?? 'ledger'}
                        </td>
                        <td className="font-mono-code tabular-nums py-2 px-3 font-semibold">
                          <span
                            className={`inline-flex items-center gap-1 ${
                              isPositive ? 'text-[#6366F1]' : 'text-[#FAFAFA]'
                            }`}
                          >
                            {isPositive ? (
                              <ArrowUpRight className="h-3 w-3" />
                            ) : (
                              <ArrowDownRight className="h-3 w-3 text-[#A1A1AA]" />
                            )}
                            {isPositive ? `+${entry.delta}` : entry.delta}
                          </span>
                        </td>
                        <td className="font-mono-code py-2 px-3 text-[#FAFAFA]">
                          {entry.reason}
                        </td>
                        <td className="font-mono-code tabular-nums py-2 px-3 text-[#A1A1AA]">
                          {refLabel}
                        </td>
                        <td className="font-mono-code tabular-nums py-2 px-3 font-semibold text-[#FAFAFA]">
                          {entry.balance_after}
                        </td>
                        <td className="font-mono-code tabular-nums py-2 px-3 text-[#A1A1AA]">
                          {new Date(entry.created_at).toLocaleTimeString([], {
                            hour: '2-digit',
                            minute: '2-digit',
                            second: '2-digit',
                          })}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
