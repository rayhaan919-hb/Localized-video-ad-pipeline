'use client';

import React, { useState } from 'react';
import {
  CheckCircle2,
  KeyRound,
  Lock,
  Mail,
  ShieldCheck,
  UserPlus,
  X,
} from 'lucide-react';
import type { AuthUserSummary } from '@/types/studio';

export type AuthModalMode =
  | 'login'
  | 'register'
  | 'verify_email'
  | 'reset_request'
  | 'reset_confirm';

interface AuthModalProps {
  isOpen: boolean;
  isBlockingGate?: boolean;
  initialMode?: AuthModalMode;
  currentUserEmail?: string;
  onClose?: () => void;
  onAuthSuccess: (
    user: AuthUserSummary,
    preferredWorkspaceId?: string
  ) => void;
}

interface AuthApiResponse {
  user?: AuthUserSummary;
  primary_workspace_id?: string;
  verify_email_token?: string;
  reset_token?: string;
  verified?: boolean;
  password_reset?: boolean;
  message?: string;
  detail?: string;
}

export const AuthModal: React.FC<AuthModalProps> = ({
  isOpen,
  isBlockingGate = false,
  initialMode = 'login',
  currentUserEmail = '',
  onClose,
  onAuthSuccess,
}) => {
  const [mode, setMode] = useState<AuthModalMode>(initialMode);
  const [email, setEmail] = useState(currentUserEmail);
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [tokenInput, setTokenInput] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [infoMsg, setInfoMsg] = useState<string | null>(null);

  if (!isOpen) {
    return null;
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setErrorMsg(null);
    setInfoMsg(null);

    try {
      if (mode === 'login') {
        const res = await fetch('/api/v1/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ email, password }),
        });
        const data = (await res.json()) as AuthApiResponse;
        if (!res.ok || !data.user) {
          throw new Error(data.detail ?? 'Authentication failed.');
        }
        onAuthSuccess(data.user, data.primary_workspace_id);
        return;
      }

      if (mode === 'register') {
        const res = await fetch('/api/v1/auth/register', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            email,
            password,
            ...(fullName.trim() ? { full_name: fullName.trim() } : {}),
          }),
        });
        const data = (await res.json()) as AuthApiResponse;
        if (!res.ok || !data.user) {
          throw new Error(data.detail ?? 'Account registration failed.');
        }
        if (data.verify_email_token) {
          setInfoMsg(
            `Account created. Dev verification token: ${data.verify_email_token}`
          );
        }
        onAuthSuccess(data.user, data.primary_workspace_id);
        return;
      }

      if (mode === 'verify_email') {
        const res = await fetch('/api/v1/auth/verify-email', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ token: tokenInput.trim() }),
        });
        const data = (await res.json()) as AuthApiResponse;
        if (!res.ok) {
          throw new Error(data.detail ?? 'Verification failed.');
        }
        setInfoMsg('Email address verified cleanly.');
        // Refresh /me session summary
        const meRes = await fetch('/api/v1/auth/me', {
          method: 'GET',
          credentials: 'include',
        });
        if (meRes.ok) {
          const meData = (await meRes.json()) as AuthApiResponse;
          if (meData.user) {
            onAuthSuccess(meData.user);
            return;
          }
        }
        return;
      }

      if (mode === 'reset_request') {
        const res = await fetch('/api/v1/auth/password-reset/request', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email }),
        });
        const data = (await res.json()) as AuthApiResponse;
        if (!res.ok) {
          throw new Error(data.detail ?? 'Password reset request failed.');
        }
        if (data.reset_token) {
          setTokenInput(data.reset_token);
          setInfoMsg(
            `Reset token generated (dev mode): ${data.reset_token}. Enter your new password below.`
          );
          setMode('reset_confirm');
        } else {
          setInfoMsg(
            data.message ??
              'If that email exists, password reset instructions have been issued.'
          );
        }
        return;
      }

      if (mode === 'reset_confirm') {
        const res = await fetch('/api/v1/auth/password-reset/confirm', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            token: tokenInput.trim(),
            new_password: newPassword,
          }),
        });
        const data = (await res.json()) as AuthApiResponse;
        if (!res.ok) {
          throw new Error(data.detail ?? 'Password reset failed.');
        }
        setPassword('');
        setNewPassword('');
        setTokenInput('');
        setInfoMsg('Password updated cleanly. You can sign in now.');
        setMode('login');
      }
    } catch (err) {
      setErrorMsg(
        err instanceof Error ? err.message : 'Authentication request failed.'
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Account Authentication"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4"
    >
      <div className="w-full max-w-md rounded border border-[#27272A] bg-[#18181B] p-6">
        <div className="flex items-start justify-between border-b border-[#27272A] pb-4">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded border border-[#27272A] bg-[#09090B]">
              <ShieldCheck className="h-4 w-4 text-[#6366F1]" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-[#FAFAFA]">
                {mode === 'register'
                  ? 'Create Multi-Tenant Workspace Account'
                  : mode === 'verify_email'
                  ? 'Verify Email Address'
                  : mode === 'reset_request'
                  ? 'Reset Account Password'
                  : mode === 'reset_confirm'
                  ? 'Confirm New Password'
                  : 'Sign In to Localized Ad Studio'}
              </h2>
              <p className="text-xs text-[#A1A1AA]">
                Customer-isolated workspaces, assets, and credit ledger
              </p>
            </div>
          </div>

          {!isBlockingGate && onClose ? (
            <button
              type="button"
              onClick={onClose}
              aria-label="Close authentication modal"
              className="rounded border border-[#27272A] bg-[#09090B] p-1.5 text-[#A1A1AA] hover:text-[#FAFAFA]"
            >
              <X className="h-4 w-4" />
            </button>
          ) : null}
        </div>

        {/* Mode Switcher Tabs */}
        <div className="mt-4 grid grid-cols-3 gap-1 rounded border border-[#27272A] bg-[#09090B] p-1">
          {(
            [
              { id: 'login', label: 'Sign In' },
              { id: 'register', label: 'Create Account' },
              { id: 'reset_request', label: 'Reset Password' },
            ] as const
          ).map((tab) => {
            const active =
              mode === tab.id ||
              (tab.id === 'reset_request' && mode === 'reset_confirm');
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => {
                  setMode(tab.id);
                  setErrorMsg(null);
                }}
                className={`rounded px-2 py-1.5 text-xs font-medium transition-colors ${
                  active
                    ? 'bg-[#6366F1] text-[#FAFAFA]'
                    : 'text-[#A1A1AA] hover:text-[#FAFAFA]'
                }`}
              >
                {tab.label}
              </button>
            );
          })}
        </div>

        {errorMsg ? (
          <div
            role="alert"
            className="mt-4 rounded border border-red-500/60 bg-[#09090B] p-3 text-xs text-red-400"
          >
            {errorMsg}
          </div>
        ) : null}

        {infoMsg ? (
          <div className="mt-4 rounded border border-[#6366F1]/70 bg-[#09090B] p-3 text-xs text-[#FAFAFA]">
            {infoMsg}
          </div>
        ) : null}

        <form onSubmit={(e) => void handleSubmit(e)} className="mt-4 space-y-3">
          {mode === 'register' ? (
            <div className="flex flex-col gap-1">
              <label
                htmlFor="auth-fullname"
                className="text-[11px] text-[#A1A1AA]"
              >
                Full Name / Brand
              </label>
              <input
                id="auth-fullname"
                type="text"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                placeholder="Zayna Studio"
                className="rounded border border-[#27272A] bg-[#09090B] px-3 py-2 text-xs text-[#FAFAFA] focus:border-[#6366F1] focus:outline-none"
              />
            </div>
          ) : null}

          {mode !== 'verify_email' && mode !== 'reset_confirm' ? (
            <div className="flex flex-col gap-1">
              <label
                htmlFor="auth-email"
                className="text-[11px] text-[#A1A1AA]"
              >
                Work Email
              </label>
              <div className="relative">
                <Mail className="pointer-events-none absolute left-3 top-2.5 h-3.5 w-3.5 text-[#A1A1AA]" />
                <input
                  id="auth-email"
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="founder@brand.com"
                  className="w-full rounded border border-[#27272A] bg-[#09090B] py-2 pl-9 pr-3 text-xs text-[#FAFAFA] focus:border-[#6366F1] focus:outline-none"
                />
              </div>
            </div>
          ) : null}

          {mode === 'login' || mode === 'register' ? (
            <div className="flex flex-col gap-1">
              <label
                htmlFor="auth-password"
                className="text-[11px] text-[#A1A1AA]"
              >
                Password {mode === 'register' ? '(min 8 chars)' : ''}
              </label>
              <div className="relative">
                <Lock className="pointer-events-none absolute left-3 top-2.5 h-3.5 w-3.5 text-[#A1A1AA]" />
                <input
                  id="auth-password"
                  type="password"
                  required
                  minLength={mode === 'register' ? 8 : 1}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full rounded border border-[#27272A] bg-[#09090B] py-2 pl-9 pr-3 text-xs text-[#FAFAFA] focus:border-[#6366F1] focus:outline-none"
                />
              </div>
            </div>
          ) : null}

          {mode === 'verify_email' || mode === 'reset_confirm' ? (
            <div className="flex flex-col gap-1">
              <label
                htmlFor="auth-token"
                className="text-[11px] text-[#A1A1AA]"
              >
                {mode === 'verify_email'
                  ? 'Email Verification Token'
                  : 'Password Reset Token'}
              </label>
              <div className="relative">
                <KeyRound className="pointer-events-none absolute left-3 top-2.5 h-3.5 w-3.5 text-[#A1A1AA]" />
                <input
                  id="auth-token"
                  type="text"
                  required
                  value={tokenInput}
                  onChange={(e) => setTokenInput(e.target.value)}
                  placeholder="Paste verification or reset token"
                  className="font-mono-code w-full rounded border border-[#27272A] bg-[#09090B] py-2 pl-9 pr-3 text-xs text-[#FAFAFA] focus:border-[#6366F1] focus:outline-none"
                />
              </div>
            </div>
          ) : null}

          {mode === 'reset_confirm' ? (
            <div className="flex flex-col gap-1">
              <label
                htmlFor="auth-new-password"
                className="text-[11px] text-[#A1A1AA]"
              >
                New Password (min 8 chars)
              </label>
              <input
                id="auth-new-password"
                type="password"
                required
                minLength={8}
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="New strong password"
                className="rounded border border-[#27272A] bg-[#09090B] px-3 py-2 text-xs text-[#FAFAFA] focus:border-[#6366F1] focus:outline-none"
              />
            </div>
          ) : null}

          <button
            type="submit"
            disabled={isSubmitting}
            className="flex w-full items-center justify-center gap-2 rounded border border-[#6366F1] bg-[#6366F1] px-4 py-2 text-xs font-semibold text-[#FAFAFA] transition-colors hover:bg-[#5254E8] disabled:opacity-50"
          >
            {mode === 'register' ? (
              <UserPlus className="h-3.5 w-3.5" />
            ) : (
              <CheckCircle2 className="h-3.5 w-3.5" />
            )}
            <span>
              {isSubmitting
                ? 'Authenticating…'
                : mode === 'register'
                ? 'Create Account & Workspace'
                : mode === 'verify_email'
                ? 'Verify Email'
                : mode === 'reset_request'
                ? 'Request Reset Token'
                : mode === 'reset_confirm'
                ? 'Update Password'
                : 'Sign In'}
            </span>
          </button>

          {mode === 'reset_request' ? (
            <button
              type="button"
              onClick={() => setMode('reset_confirm')}
              className="w-full text-center text-[11px] text-[#A1A1AA] underline-offset-2 hover:text-[#FAFAFA] hover:underline"
            >
              Already have a reset token? Enter it here
            </button>
          ) : mode === 'login' && currentUserEmail ? (
            <button
              type="button"
              onClick={() => setMode('verify_email')}
              className="w-full text-center text-[11px] text-[#A1A1AA] underline-offset-2 hover:text-[#FAFAFA] hover:underline"
            >
              Verify email with token
            </button>
          ) : null}
        </form>
      </div>
    </div>
  );
};
