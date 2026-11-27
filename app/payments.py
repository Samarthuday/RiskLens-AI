"""Minimal, read-only Razorpay Test Mode payment event adapter."""

import hashlib
import hmac
import json
import re
from typing import Any

EVENT_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


class WebhookError(ValueError):
    pass


def verify_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    """Verify the HMAC over the original bytes before parsing JSON."""
    if not signature or not re.fullmatch(r"[0-9a-fA-F]{64}", signature):
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.lower())


def normalize_payment_event(raw_body: bytes, provider_event_id: str, received_at: str) -> dict[str, Any]:
    if not EVENT_ID_RE.fullmatch(provider_event_id):
        raise WebhookError("x-razorpay-event-id is missing or malformed")
    try:
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise WebhookError("signed webhook body is not valid JSON") from error
    if not isinstance(payload, dict):
        raise WebhookError("webhook body must be a JSON object")
    event_type = payload.get("event")
    if not isinstance(event_type, str) or not event_type.startswith("payment."):
        raise WebhookError("only payment.* notification events are accepted")
    created_at = payload.get("created_at")
    if not isinstance(created_at, int) or isinstance(created_at, bool) or created_at <= 0:
        raise WebhookError("event created_at must be a positive Unix timestamp")
    event_payload = payload.get("payload")
    payment_payload = event_payload.get("payment") if isinstance(event_payload, dict) else None
    payment = payment_payload.get("entity") if isinstance(payment_payload, dict) else None
    if not isinstance(payment, dict) or payment.get("entity") != "payment":
        raise WebhookError("webhook does not contain a payment entity")
    payment_id = payment.get("id")
    status = payment.get("status")
    amount = payment.get("amount")
    currency = payment.get("currency")
    method = payment.get("method")
    order_id = payment.get("order_id")
    if not isinstance(payment_id, str) or not re.fullmatch(r"pay_[A-Za-z0-9]+", payment_id):
        raise WebhookError("payment entity has an invalid payment id")
    if not isinstance(status, str) or len(status) > 32:
        raise WebhookError("payment entity has an invalid status")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
        raise WebhookError("payment amount must be an integer in provider currency subunits")
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Za-z]{3}", currency):
        raise WebhookError("payment entity has an invalid currency code")
    if method is not None and (not isinstance(method, str) or len(method) > 32):
        raise WebhookError("payment entity has an invalid method")
    if order_id is not None and (not isinstance(order_id, str) or len(order_id) > 64):
        raise WebhookError("payment entity has an invalid order id")
    return {
        "provider_event_id": provider_event_id,
        "event_type": event_type,
        "payment_id": payment_id,
        "order_id": order_id,
        "amount_subunits": amount,
        "currency": currency.upper(),
        "payment_method": method,
        "payment_status": status,
        "event_created_at": created_at,
        "received_at": received_at,
        "payload_sha256": hashlib.sha256(raw_body).hexdigest(),
    }
