'use client';

import React, { useEffect, useState } from 'react';
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
    preferredWorkspaceId?: string,
    devVerifyToken?: string
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
  const [touched, setTouched] = useState<Record<string, boolean>>({});

  const markTouched = (field: string) =>
    setTouched((prev) => ({ ...prev, [field]: true }));

  const emailInvalid = Boolean(
    touched.email &&
      (!email.trim() || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim()))
  );
  const passwordInvalid = Boolean(
    touched.password &&
      ((mode === 'register' && password.length < 8) ||
        (mode === 'login' && password.length === 0))
  );
  const newPasswordInvalid = Boolean(
    touched.newPassword && mode === 'reset_confirm' && newPassword.length < 8
  );

  useEffect(() => {
    if (isOpen) {
      setMode(initialMode);
      setErrorMsg(null);
      setTouched({});
      if (currentUserEmail) {
        setEmail(currentUserEmail);
      }
    }
  }, [isOpen, initialMode, currentUserEmail]);

  useEffect(() => {
    if (!isOpen || isBlockingGate || !onClose) {
      return;
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, isBlockingGate, onClose]);

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
        onAuthSuccess(
          data.user,
          data.primary_workspace_id,
          data.verify_email_token
        );
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
      className="fixed inset-0 z-50 flex items-center justify-center bg-[#1C1917]/50 p-4 backdrop-blur-[2px]"
    >
      <div className="w-full max-w-md rounded-3xl border border-[#E6E0D5] bg-white p-5 shadow-2xl sm:p-6">
        <div className="flex items-start justify-between gap-3 border-b border-[#E6E0D5] pb-4">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-[#BBF7D0] bg-[#F0FDF4]">
              <ShieldCheck className="h-4 w-4 text-[#166534]" />
            </div>
            <div className="min-w-0">
              <h2 className="text-sm font-semibold text-[#1C1917]">
                {mode === 'register'
                  ? 'Create your account'
                  : mode === 'verify_email'
                  ? 'Verify email'
                  : mode === 'reset_request'
                  ? 'Reset password'
                  : mode === 'reset_confirm'
                  ? 'Confirm new password'
                  : 'Sign in to Localized Ad Studio'}
              </h2>
              <p className="text-xs text-[#57534E]">
                Private workspaces, product imports, and rendered videos
              </p>
            </div>
          </div>

          {!isBlockingGate && onClose ? (
            <button
              type="button"
              onClick={onClose}
              aria-label="Close authentication modal"
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-[#E6E0D5] bg-[#FAF7F2] text-[#57534E] transition-colors hover:border-[#15803D] hover:text-[#166534]"
            >
              <X className="h-4 w-4" />
            </button>
          ) : null}
        </div>

        {/* Mode Switcher Tabs */}
        <div className="mt-4 grid grid-cols-3 gap-1 rounded-full bg-[#F4EFE6] p-1">
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
                  setTouched({});
                }}
                className={`min-h-[36px] rounded-full px-2 py-1.5 text-xs font-medium transition-colors ${
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

        {errorMsg ? (
          <div
            role="alert"
            className="mt-4 rounded-2xl border border-[#FECACA] bg-[#FEF2F2] p-3 text-xs text-[#B91C1C]"
          >
            {errorMsg}
          </div>
        ) : null}

        {infoMsg ? (
          <div
            role="status"
            aria-live="polite"
            className="mt-4 rounded-2xl border border-[#BBF7D0] bg-[#F0FDF4] p-3 text-xs text-[#166534]"
          >
            {infoMsg}
          </div>
        ) : null}

        <form onSubmit={(e) => void handleSubmit(e)} className="mt-4 space-y-3">
          {mode === 'register' ? (
            <div className="flex flex-col gap-1">
              <label
                htmlFor="auth-fullname"
                className="text-xs font-medium text-[#1C1917]"
              >
                Full Name / Brand
              </label>
              <input
                id="auth-fullname"
                type="text"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                placeholder="Zayna Studio"
                className="min-h-[40px] rounded-xl border border-[#D6CEC0] bg-[#FAF7F2] px-3.5 py-2 text-xs text-[#1C1917] placeholder-[#6E6A63] focus:border-[#15803D] focus:bg-white focus:outline-none"
              />
            </div>
          ) : null}

          {mode !== 'verify_email' && mode !== 'reset_confirm' ? (
            <div className="flex flex-col gap-1">
              <label
                htmlFor="auth-email"
                className="text-xs font-medium text-[#1C1917]"
              >
                Work Email
              </label>
              <div className="relative">
                <Mail className="pointer-events-none absolute left-3.5 top-3 h-3.5 w-3.5 text-[#57534E]" />
                <input
                  id="auth-email"
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  onBlur={() => markTouched('email')}
                  aria-invalid={emailInvalid}
                  aria-describedby={emailInvalid ? 'auth-email-error' : undefined}
                  placeholder="founder@brand.com"
                  className={`min-h-[40px] w-full rounded-xl border bg-[#FAF7F2] py-2 pl-9 pr-3.5 text-xs text-[#1C1917] placeholder-[#6E6A63] focus:bg-white focus:outline-none ${
                    emailInvalid
                      ? 'border-[#B91C1C]'
                      : 'border-[#D6CEC0] focus:border-[#15803D]'
                  }`}
                />
              </div>
              {emailInvalid ? (
                <p
                  id="auth-email-error"
                  role="alert"
                  className="text-[11px] font-medium text-[#B91C1C]"
                >
                  Enter a valid email address
                </p>
              ) : null}
            </div>
          ) : null}

          {mode === 'login' || mode === 'register' ? (
            <div className="flex flex-col gap-1">
              <label
                htmlFor="auth-password"
                className="text-xs font-medium text-[#1C1917]"
              >
                Password {mode === 'register' ? '(min 8 chars)' : ''}
              </label>
              <div className="relative">
                <Lock className="pointer-events-none absolute left-3.5 top-3 h-3.5 w-3.5 text-[#57534E]" />
                <input
                  id="auth-password"
                  type="password"
                  required
                  minLength={mode === 'register' ? 8 : 1}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  onBlur={() => markTouched('password')}
                  aria-invalid={passwordInvalid}
                  aria-describedby={
                    passwordInvalid ? 'auth-password-error' : undefined
                  }
                  placeholder="••••••••"
                  className={`min-h-[40px] w-full rounded-xl border bg-[#FAF7F2] py-2 pl-9 pr-3.5 text-xs text-[#1C1917] placeholder-[#6E6A63] focus:bg-white focus:outline-none ${
                    passwordInvalid
                      ? 'border-[#B91C1C]'
                      : 'border-[#D6CEC0] focus:border-[#15803D]'
                  }`}
                />
              </div>
              {passwordInvalid ? (
                <p
                  id="auth-password-error"
                  role="alert"
                  className="text-[11px] font-medium text-[#B91C1C]"
                >
                  {mode === 'register'
                    ? 'Password must be at least 8 characters'
                    : 'Enter your password'}
                </p>
              ) : null}
            </div>
          ) : null}

          {mode === 'verify_email' || mode === 'reset_confirm' ? (
            <div className="flex flex-col gap-1">
              <label
                htmlFor="auth-token"
                className="text-xs font-medium text-[#1C1917]"
              >
                {mode === 'verify_email'
                  ? 'Email Verification Token'
                  : 'Password Reset Token'}
              </label>
              <div className="relative">
                <KeyRound className="pointer-events-none absolute left-3.5 top-3 h-3.5 w-3.5 text-[#57534E]" />
                <input
                  id="auth-token"
                  type="text"
                  required
                  value={tokenInput}
                  onChange={(e) => setTokenInput(e.target.value)}
                  placeholder="Paste verification or reset token"
                  className="font-mono-code min-h-[40px] w-full rounded-xl border border-[#D6CEC0] bg-[#FAF7F2] py-2 pl-9 pr-3.5 text-xs text-[#1C1917] placeholder-[#6E6A63] focus:border-[#15803D] focus:bg-white focus:outline-none"
                />
              </div>
            </div>
          ) : null}

          {mode === 'reset_confirm' ? (
            <div className="flex flex-col gap-1">
              <label
                htmlFor="auth-new-password"
                className="text-xs font-medium text-[#1C1917]"
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
                onBlur={() => markTouched('newPassword')}
                aria-invalid={newPasswordInvalid}
                aria-describedby={
                  newPasswordInvalid ? 'auth-new-password-error' : undefined
                }
                placeholder="New strong password"
                className={`min-h-[40px] rounded-xl border bg-[#FAF7F2] px-3.5 py-2 text-xs text-[#1C1917] placeholder-[#6E6A63] focus:bg-white focus:outline-none ${
                  newPasswordInvalid
                    ? 'border-[#B91C1C]'
                    : 'border-[#D6CEC0] focus:border-[#15803D]'
                }`}
              />
              {newPasswordInvalid ? (
                <p
                  id="auth-new-password-error"
                  role="alert"
                  className="text-[11px] font-medium text-[#B91C1C]"
                >
                  New password must be at least 8 characters
                </p>
              ) : null}
            </div>
          ) : null}

          <button
            type="submit"
            disabled={isSubmitting}
            className="flex min-h-[42px] w-full items-center justify-center gap-2 rounded-full bg-[#15803D] px-5 py-2 text-xs font-semibold text-white transition-colors hover:bg-[#166534] disabled:opacity-50"
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
              onClick={() => {
                setMode('reset_confirm');
                setTouched({});
              }}
              className="min-h-[32px] w-full rounded-full py-1 text-center text-xs text-[#57534E] underline-offset-2 hover:text-[#166534] hover:underline"
            >
              Already have a reset token? Enter it here
            </button>
          ) : mode === 'login' && currentUserEmail ? (
            <button
              type="button"
              onClick={() => {
                setMode('verify_email');
                setTouched({});
              }}
              className="min-h-[32px] w-full rounded-full py-1 text-center text-xs text-[#57534E] underline-offset-2 hover:text-[#166534] hover:underline"
            >
              Verify email with token
            </button>
          ) : null}
        </form>
      </div>
    </div>
  );
};
