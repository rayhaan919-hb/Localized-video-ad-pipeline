'use client';

import React, { useEffect } from 'react';
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
  useEffect(() => {
    if (!isOpen) {
      return;
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

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
      aria-label="Credits and Billing"
      className="fixed inset-0 z-50 flex items-center justify-center bg-[#1C1917]/50 p-4 backdrop-blur-[2px]"
    >
      <div className="max-h-[90vh] w-full max-w-4xl overflow-y-auto rounded-3xl border border-[#E6E0D5] bg-[#FAF7F2] p-5 shadow-2xl sm:p-6">
        {/* Modal Header */}
        <div className="flex items-start justify-between gap-3 border-b border-[#E6E0D5] pb-4">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-[#BBF7D0] bg-[#F0FDF4]">
              <CreditCard className="h-5 w-5 text-[#166534]" />
            </div>
            <div className="min-w-0">
              <h2 className="text-base font-semibold text-[#1C1917]">
                Credits &amp; Billing
              </h2>
              <p className="text-xs text-[#57534E]">
                Choose a credit pack or review recent credit transactions
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            aria-label="Close billing modal"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-[#E6E0D5] bg-white text-[#57534E] transition-colors hover:border-[#15803D] hover:text-[#166534]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Balance Banner */}
        <div className="mt-4 flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-[#E6E0D5] bg-white p-4">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-[#F0FDF4]">
              <Coins className="h-5 w-5 text-[#166534]" />
            </div>
            <div>
              <span className="block text-xs text-[#57534E]">
                Available Render Balance
              </span>
              <span className="font-mono-code tabular-nums text-xl font-bold text-[#1C1917]">
                {creditBalance} {creditBalance === 1 ? 'Credit' : 'Credits'}
              </span>
            </div>
          </div>

          <div className="flex items-center gap-2 rounded-full border border-[#BBF7D0] bg-[#F0FDF4] px-3.5 py-1.5 text-xs text-[#166534]">
            <ShieldCheck className="h-4 w-4 shrink-0" />
            <span>
              Credits are added automatically upon verified Stripe payment.
            </span>
          </div>
        </div>

        {/* Error Banner */}
        {showError ? (
          <div
            role="alert"
            className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[#FECACA] bg-[#FEF2F2] p-3.5"
          >
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 shrink-0 text-[#B91C1C]" />
              <p className="text-xs text-[#B91C1C]">
                {creditsError ?? 'Failed to synchronize credit history.'}
              </p>
            </div>
            <button
              type="button"
              onClick={onRetryFetchCredits}
              className="flex min-h-[36px] items-center gap-1.5 rounded-full border border-[#FECACA] bg-white px-3.5 py-1.5 text-xs font-semibold text-[#1C1917] hover:border-[#15803D] hover:text-[#166534]"
            >
              <RotateCcw className="h-3 w-3 text-[#166534]" />
              <span>Retry</span>
            </button>
          </div>
        ) : null}

        {/* Credit Packages */}
        <div className="mt-6">
          <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-[#57534E]">
            Select a Pack
          </h3>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            {CREDIT_PACKAGE_TIERS.map((tier) => {
              const isBusy = isCheckingOutPackId === tier.id;
              return (
                <div
                  key={tier.id}
                  className={`flex flex-col justify-between rounded-2xl border bg-white p-4 shadow-[0_1px_2px_rgba(28,25,23,0.04)] ${
                    tier.badge ? 'border-[#15803D]' : 'border-[#E6E0D5]'
                  }`}
                >
                  <div>
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-semibold text-[#1C1917]">
                        {tier.name}
                      </span>
                      {tier.badge ? (
                        <span className="rounded-full bg-[#15803D] px-2.5 py-0.5 text-[10px] font-bold text-white">
                          {tier.badge}
                        </span>
                      ) : null}
                    </div>

                    <div className="mt-3 flex items-baseline gap-2">
                      <span className="font-mono-code tabular-nums text-2xl font-bold text-[#1C1917]">
                        +{tier.credits}
                      </span>
                      <span className="text-xs text-[#57534E]">credits</span>
                    </div>

                    <div className="mt-1 flex items-center justify-between text-xs">
                      <span className="font-mono-code tabular-nums font-semibold text-[#166534]">
                        {tier.priceUsd}
                      </span>
                      <span className="font-mono-code tabular-nums text-[#57534E]">
                        {tier.perCreditUsd}
                      </span>
                    </div>

                    <p className="mt-3 text-xs text-[#57534E]">
                      {tier.description}
                    </p>
                  </div>

                  <div className="mt-4 flex flex-col gap-2">
                    <button
                      type="button"
                      disabled={Boolean(isCheckingOutPackId)}
                      onClick={() => onCheckoutCredits(tier.id)}
                      className="flex min-h-[42px] w-full items-center justify-center gap-1.5 rounded-full bg-[#15803D] px-4 py-2 text-xs font-semibold text-white transition-colors hover:bg-[#166534] disabled:opacity-50"
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
                        className="flex min-h-[32px] w-full items-center justify-center gap-1 rounded-full border border-[#E6E0D5] bg-[#FAF7F2] px-3 py-1 text-[11px] font-medium text-[#57534E] hover:border-[#15803D] hover:text-[#166534]"
                      >
                        <Wrench className="h-3 w-3" />
                        <span>Dev Top-Up</span>
                      </button>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Credit History */}
        <div className="mt-6 border-t border-[#E6E0D5] pt-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <span className="flex items-center gap-1.5 text-xs font-semibold text-[#1C1917]">
              <History className="h-3.5 w-3.5 text-[#166534]" />
              <span>Credit History</span>
            </span>
            <span className="font-mono-code tabular-nums rounded-full bg-[#F4EFE6] px-2.5 py-0.5 text-xs font-medium text-[#57534E]">
              {ledger.length}{' '}
              {ledger.length === 1 ? 'transaction' : 'transactions'}
            </span>
          </div>

          {showSkeleton ? (
            <div className="flex flex-col gap-2">
              {[0, 1, 2].map((idx) => (
                <div
                  key={idx}
                  className="h-9 w-full animate-pulse rounded-xl border border-[#E6E0D5] bg-white"
                />
              ))}
            </div>
          ) : showEmpty ? (
            <div className="flex flex-col items-center justify-center gap-2 rounded-2xl border border-[#E6E0D5] bg-white p-6 text-center">
              <Coins className="h-5 w-5 text-[#166534]" />
              <p className="text-xs text-[#57534E]">
                No credit transactions recorded for this workspace yet.
              </p>
            </div>
          ) : (
            <div className="max-h-56 overflow-x-auto overflow-y-auto rounded-2xl border border-[#E6E0D5] bg-white">
              <table className="w-full border-collapse text-left text-xs">
                <thead>
                  <tr className="border-b border-[#E6E0D5] bg-[#FAF7F2] text-[11px] text-[#57534E]">
                    <th className="py-2.5 px-3 font-semibold">Type</th>
                    <th className="py-2.5 px-3 font-semibold">Delta</th>
                    <th className="py-2.5 px-3 font-semibold">Reason</th>
                    <th className="py-2.5 px-3 font-semibold">Ref</th>
                    <th className="py-2.5 px-3 font-semibold">Balance</th>
                    <th className="py-2.5 px-3 font-semibold">Timestamp</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#E6E0D5]">
                  {ledger.map((entry) => {
                    const isPositive = entry.delta > 0;
                    const refLabel = entry.job_id
                      ? `job:#${entry.job_id.slice(0, 8)}`
                      : entry.payment_id
                      ? `pay:${entry.payment_id.slice(0, 10)}`
                      : '—';
                    return (
                      <tr key={entry.id} className="hover:bg-[#FAF7F2]/70">
                        <td className="font-mono-code py-2 px-3 text-[11px] text-[#57534E]">
                          {entry.transaction_type ?? 'ledger'}
                        </td>
                        <td className="font-mono-code tabular-nums py-2 px-3 font-semibold">
                          <span
                            className={`inline-flex items-center gap-1 ${
                              isPositive ? 'text-[#166534]' : 'text-[#1C1917]'
                            }`}
                          >
                            {isPositive ? (
                              <ArrowUpRight className="h-3 w-3" />
                            ) : (
                              <ArrowDownRight className="h-3 w-3 text-[#57534E]" />
                            )}
                            {isPositive ? `+${entry.delta}` : entry.delta}
                          </span>
                        </td>
                        <td className="py-2 px-3 text-[#1C1917]">
                          {entry.reason}
                        </td>
                        <td className="font-mono-code tabular-nums py-2 px-3 text-[#57534E]">
                          {refLabel}
                        </td>
                        <td className="font-mono-code tabular-nums py-2 px-3 font-semibold text-[#1C1917]">
                          {entry.balance_after}
                        </td>
                        <td className="font-mono-code tabular-nums py-2 px-3 text-[#57534E]">
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
