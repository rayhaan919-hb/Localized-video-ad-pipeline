"""Server-authoritative Stripe Checkout and signed Webhook processing."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import CREDIT_PACKAGES, settings
from app.db import (
    StripeEvent,
    User,
    Workspace,
    WorkspaceMember,
    add_credits_atomically,
    reverse_credits_for_payment_refund,
    utcnow,
)
from app.security import log_audit_event


class BillingError(Exception):
    """Base billing/Stripe error."""


class BillingConfigurationError(BillingError):
    """Raised when required Stripe credentials or price IDs are not configured."""


class WebhookSignatureError(BillingError):
    """Raised when a Stripe webhook signature is missing, stale, or invalid."""


class WebhookValidationError(BillingError):
    """Raised when a Stripe event fails amount, currency, pack, or workspace checks."""


def _validate_redirect_url(raw_url: str | None, default_path: str) -> str:
    base = settings.effective_frontend_app_url or "http://localhost:3000"
    if not raw_url:
        return f"{base}{default_path}"
    parsed = urlparse(raw_url.strip())
    base_parsed = urlparse(base)
    if parsed.scheme in ("http", "https") and parsed.netloc == base_parsed.netloc:
        return raw_url.strip()
    raise BillingError("Redirect URL must match the configured application origin.")


def get_public_credit_packages() -> list[dict[str, Any]]:
    """Return server-authoritative package catalog (safe for frontend display)."""
    items = []
    for pack_id, pkg in CREDIT_PACKAGES.items():
        price_id = settings.get_stripe_price_id(pack_id)
        items.append(
            {
                "pack_id": pack_id,
                "name": pkg["name"],
                "credits": pkg["credits"],
                "amount_cents": pkg["amount_cents"],
                "currency": pkg["currency"],
                "stripe_configured": bool(settings.effective_stripe_secret_key and price_id),
            }
        )
    return items


def create_stripe_checkout_session(
    *,
    workspace: Workspace,
    user: User,
    pack_id: str,
    success_url: str | None = None,
    cancel_url: str | None = None,
) -> dict[str, Any]:
    """Create a real Stripe Checkout Session using server-defined price IDs and metadata."""
    pkg = CREDIT_PACKAGES.get(pack_id)
    if pkg is None:
        raise BillingError(f"Unknown credit package: {pack_id}")

    stripe_key = settings.effective_stripe_secret_key
    price_id = settings.get_stripe_price_id(pack_id)
    if not stripe_key or not price_id:
        raise BillingConfigurationError(
            f"Stripe billing is not configured for pack '{pack_id}'. "
            f"Configure STRIPE_SECRET_KEY and {pkg['price_env_key']}."
        )

    ok_url = _validate_redirect_url(
        success_url,
        f"/?checkout=success&pack_id={pack_id}&session_id={{CHECKOUT_SESSION_ID}}",
    )
    ko_url = _validate_redirect_url(cancel_url, "/?checkout=cancelled")

    form_data = {
        "mode": "payment",
        "success_url": ok_url,
        "cancel_url": ko_url,
        "client_reference_id": str(workspace.id),
        "customer_email": user.email,
        "line_items[0][price]": price_id,
        "line_items[0][quantity]": "1",
        "metadata[workspace_id]": str(workspace.id),
        "metadata[user_id]": str(user.id),
        "metadata[pack_id]": pack_id,
        "metadata[credits]": str(pkg["credits"]),
        "metadata[expected_amount_cents]": str(pkg["amount_cents"]),
        "metadata[expected_currency]": pkg["currency"],
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                "https://api.stripe.com/v1/checkout/sessions",
                data=form_data,
                headers={"Authorization": f"Bearer {stripe_key}"},
            )
    except httpx.HTTPError as exc:
        raise BillingError(f"Failed to contact Stripe Checkout API: {exc}") from exc

    if resp.status_code not in (200, 201):
        raise BillingError(f"Stripe Checkout session creation failed ({resp.status_code}).")

    payload = resp.json()
    session_id = str(payload.get("id") or "").strip()
    checkout_url = str(payload.get("url") or "").strip()
    if not session_id or not checkout_url.startswith("https://"):
        raise BillingError("Stripe returned an incomplete checkout session response.")

    log_audit_event(
        "stripe_checkout_session_created",
        user_id=user.id,
        workspace_id=workspace.id,
        details={
            "pack_id": pack_id,
            "credits": pkg["credits"],
            "amount_cents": pkg["amount_cents"],
            "checkout_session_id": session_id,
        },
    )
    return {
        "checkout_session_id": session_id,
        "checkout_url": checkout_url,
        "pack_id": pack_id,
        "credits": pkg["credits"],
        "amount_cents": pkg["amount_cents"],
        "currency": pkg["currency"],
    }


def verify_stripe_signature(
    raw_body: bytes,
    signature_header: str,
    webhook_secret: str,
    *,
    tolerance_seconds: int = 300,
) -> None:
    """Verify Stripe-Signature header using HMAC-SHA256 over '<timestamp>.<raw_body>'."""
    if not webhook_secret:
        raise BillingConfigurationError("STRIPE_WEBHOOK_SECRET is not configured.")
    if not signature_header:
        raise WebhookSignatureError("Missing Stripe-Signature header.")

    timestamp_str = ""
    v1_signatures: list[str] = []
    for part in signature_header.split(","):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.strip()
        v = v.strip()
        if k == "t":
            timestamp_str = v
        elif k == "v1" and v:
            v1_signatures.append(v)

    if not timestamp_str or not v1_signatures:
        raise WebhookSignatureError("Malformed Stripe-Signature header.")

    try:
        ts = int(timestamp_str)
    except ValueError as exc:
        raise WebhookSignatureError("Invalid Stripe-Signature timestamp.") from exc

    if abs(int(time.time()) - ts) > tolerance_seconds:
        raise WebhookSignatureError("Stripe webhook timestamp outside replay tolerance.")

    signed_payload = f"{ts}.".encode("utf-8") + raw_body
    expected_hex = hmac.new(
        webhook_secret.encode("utf-8"),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()

    if not any(hmac.compare_digest(expected_hex, sig) for sig in v1_signatures):
        raise WebhookSignatureError("Stripe webhook signature verification failed.")


def process_stripe_webhook(
    session: Session,
    *,
    raw_body: bytes,
    signature_header: str,
) -> dict[str, Any]:
    """Verify, deduplicate, and process Stripe payment, expiration, and refund webhooks."""
    webhook_secret = settings.effective_stripe_webhook_secret
    verify_stripe_signature(raw_body, signature_header, webhook_secret)

    try:
        event = json.loads(raw_body.decode("utf-8"))
    except Exception as exc:
        raise WebhookValidationError("Webhook payload is not valid UTF-8 JSON.") from exc

    event_id = str(event.get("id") or "").strip()
    event_type = str(event.get("type") or "").strip()
    obj = (event.get("data") or {}).get("object") or {}
    if not event_id or not event_type or not isinstance(obj, dict):
        raise WebhookValidationError("Malformed Stripe event structure.")

    existing = session.scalar(select(StripeEvent).where(StripeEvent.stripe_event_id == event_id))
    if existing is not None:
        return {
            "received": True,
            "status": "duplicate_ignored",
            "event_id": event_id,
            "event_type": event_type,
        }

    if event_type == "checkout.session.completed":
        payment_status = str(obj.get("payment_status") or "").lower()
        if payment_status != "paid":
            session.add(
                StripeEvent(
                    id=str(uuid.uuid4()),
                    stripe_event_id=event_id,
                    event_type=event_type,
                    checkout_session_id=str(obj.get("id") or ""),
                    status=f"ignored_payment_status_{payment_status or 'unknown'}",
                    credits_delta=0,
                    created_at=utcnow(),
                )
            )
            session.commit()
            return {"received": True, "status": "ignored_unpaid", "event_id": event_id}

        metadata = obj.get("metadata") or {}
        workspace_id = str(
            metadata.get("workspace_id") or obj.get("client_reference_id") or ""
        ).strip()
        user_id = str(metadata.get("user_id") or "").strip() or None
        pack_id = str(metadata.get("pack_id") or "").strip()
        amount_total = obj.get("amount_total")
        currency = str(obj.get("currency") or "").lower()
        checkout_session_id = str(obj.get("id") or "").strip()
        payment_intent_id = str(obj.get("payment_intent") or "").strip() or checkout_session_id

        pkg = CREDIT_PACKAGES.get(pack_id)
        if pkg is None:
            raise WebhookValidationError(f"Unknown credit package in webhook metadata: {pack_id}")

        if not isinstance(amount_total, int) or amount_total != int(pkg["amount_cents"]):
            raise WebhookValidationError(
                f"Payment amount mismatch: expected {pkg['amount_cents']}, got {amount_total}"
            )
        if currency != pkg["currency"]:
            raise WebhookValidationError(
                f"Payment currency mismatch: expected {pkg['currency']}, got {currency}"
            )

        workspace = session.get(Workspace, workspace_id)
        if workspace is None:
            raise WebhookValidationError(f"Workspace {workspace_id} not found.")

        if user_id:
            member = session.scalar(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.user_id == user_id,
                )
            )
            if member is None:
                raise WebhookValidationError("Webhook user does not belong to target workspace.")

        credits = int(pkg["credits"])
        new_balance = add_credits_atomically(
            session,
            workspace_id=workspace_id,
            credits=credits,
            transaction_type="purchased",
            reason=f"Stripe checkout completed ({pkg['name']})",
            user_id=user_id,
            payment_id=payment_intent_id,
            reference_id=checkout_session_id,
            idempotency_key=f"stripe_purchase:{payment_intent_id}",
            metadata={
                "stripe_event_id": event_id,
                "checkout_session_id": checkout_session_id,
                "pack_id": pack_id,
                "amount_cents": amount_total,
                "currency": currency,
            },
        )
        session.add(
            StripeEvent(
                id=str(uuid.uuid4()),
                stripe_event_id=event_id,
                event_type=event_type,
                payment_intent_id=payment_intent_id,
                checkout_session_id=checkout_session_id,
                workspace_id=workspace_id,
                user_id=user_id,
                pack_id=pack_id,
                amount_cents=amount_total,
                currency=currency,
                credits_delta=credits,
                status="processed",
                payload_summary={"new_balance": new_balance},
                created_at=utcnow(),
            )
        )
        session.commit()
        log_audit_event(
            "stripe_credits_granted",
            user_id=user_id,
            workspace_id=workspace_id,
            details={
                "event_id": event_id,
                "pack_id": pack_id,
                "credits_granted": credits,
                "new_balance": new_balance,
            },
        )
        return {
            "received": True,
            "status": "credited",
            "event_id": event_id,
            "workspace_id": workspace_id,
            "credits_granted": credits,
            "credit_balance": new_balance,
        }

    if event_type in ("checkout.session.expired", "payment_intent.payment_failed"):
        metadata = obj.get("metadata") or {}
        ws_id = str(metadata.get("workspace_id") or "").strip() or None
        session.add(
            StripeEvent(
                id=str(uuid.uuid4()),
                stripe_event_id=event_id,
                event_type=event_type,
                payment_intent_id=str(obj.get("payment_intent") or obj.get("id") or "") or None,
                checkout_session_id=str(obj.get("id") or "") or None,
                workspace_id=ws_id if ws_id and session.get(Workspace, ws_id) else None,
                credits_delta=0,
                status="payment_failed_or_expired",
                created_at=utcnow(),
            )
        )
        session.commit()
        return {"received": True, "status": "recorded_failure", "event_id": event_id}

    if event_type in ("charge.refunded", "charge.dispute.created"):
        payment_intent_id = str(obj.get("payment_intent") or "").strip()
        purchase_event = None
        if payment_intent_id:
            purchase_event = session.scalar(
                select(StripeEvent).where(
                    StripeEvent.payment_intent_id == payment_intent_id,
                    StripeEvent.credits_delta > 0,
                )
            )
        if purchase_event is None or not purchase_event.workspace_id:
            session.add(
                StripeEvent(
                    id=str(uuid.uuid4()),
                    stripe_event_id=event_id,
                    event_type=event_type,
                    payment_intent_id=payment_intent_id or None,
                    credits_delta=0,
                    status="refund_without_matching_purchase",
                    created_at=utcnow(),
                )
            )
            session.commit()
            return {"received": True, "status": "refund_unmatched", "event_id": event_id}

        original_credits = int(purchase_event.credits_delta)
        amount_total = int(purchase_event.amount_cents or obj.get("amount") or 0)
        amount_refunded = int(obj.get("amount_refunded") or obj.get("amount") or amount_total)
        if amount_total > 0 and amount_refunded < amount_total:
            credits_to_revoke = max(1, round(original_credits * (amount_refunded / amount_total)))
        else:
            credits_to_revoke = original_credits

        new_balance, actual_revoked = reverse_credits_for_payment_refund(
            session,
            workspace_id=purchase_event.workspace_id,
            credits_to_revoke=credits_to_revoke,
            payment_id=payment_intent_id,
            idempotency_key=f"stripe_refund:{event_id}",
            user_id=purchase_event.user_id,
            reason=f"Stripe {event_type} for payment {payment_intent_id}",
            metadata={
                "stripe_event_id": event_id,
                "amount_refunded": amount_refunded,
                "original_credits": original_credits,
            },
        )
        session.add(
            StripeEvent(
                id=str(uuid.uuid4()),
                stripe_event_id=event_id,
                event_type=event_type,
                payment_intent_id=payment_intent_id,
                workspace_id=purchase_event.workspace_id,
                user_id=purchase_event.user_id,
                pack_id=purchase_event.pack_id,
                amount_cents=amount_refunded,
                currency=purchase_event.currency,
                credits_delta=-actual_revoked,
                status="refund_processed",
                payload_summary={"new_balance": new_balance, "revoked": actual_revoked},
                created_at=utcnow(),
            )
        )
        session.commit()
        return {
            "received": True,
            "status": "refund_processed",
            "event_id": event_id,
            "credits_revoked": actual_revoked,
            "credit_balance": new_balance,
        }

    # Other signed Stripe events are recorded idempotently as ignored.
    session.add(
        StripeEvent(
            id=str(uuid.uuid4()),
            stripe_event_id=event_id,
            event_type=event_type,
            credits_delta=0,
            status="ignored_event_type",
            created_at=utcnow(),
        )
    )
    session.commit()
    return {"received": True, "status": "ignored", "event_id": event_id, "event_type": event_type}
