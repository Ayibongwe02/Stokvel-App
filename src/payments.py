"""
PayFast integration
====================
South African payment gateway. Deposits go through PayFast's hosted
checkout (we never touch card data); confirmation is webhook-driven
(PayFast calls this back "ITN" — Instant Transaction Notification),
never trusted optimistically on browser redirect, because redirects
can be spoofed or abandoned mid-flow but a validated server-to-server
webhook can't.

Runs in SANDBOX mode by default so the whole flow (checkout -> ITN ->
balance update) can be built and demoed with zero real credentials.
Set PAYFAST_SANDBOX=false and real PAYFAST_MERCHANT_ID/KEY/PASSPHRASE
env vars to go live.
"""

import hashlib
import os
import urllib.parse

SANDBOX = os.environ.get("PAYFAST_SANDBOX", "true").lower() != "false"

MERCHANT_ID = os.environ.get("PAYFAST_MERCHANT_ID", "10000100")
MERCHANT_KEY = os.environ.get("PAYFAST_MERCHANT_KEY", "46f0cd694581a")
PASSPHRASE = os.environ.get("PAYFAST_PASSPHRASE", "")

CHECKOUT_URL = (
    "https://sandbox.payfast.co.za/eng/process" if SANDBOX else "https://www.payfast.co.za/eng/process"
)


def _signature(data: dict) -> str:
    """PayFast's documented signature scheme: urlencoded, ordered
    key=value pairs (excluding the signature field itself), MD5 hex
    digest, with the passphrase appended if one is configured."""
    pairs = []
    for key, value in data.items():
        if value in (None, ""):
            continue
        pairs.append(f"{key}={urllib.parse.quote_plus(str(value).strip())}")
    query = "&".join(pairs)
    if PASSPHRASE:
        query += f"&passphrase={urllib.parse.quote_plus(PASSPHRASE)}"
    return hashlib.md5(query.encode("utf-8")).hexdigest()


def build_checkout_payload(*, m_payment_id, amount, item_name, return_url, cancel_url, notify_url, email=None):
    """Builds the field set PayFast's hosted checkout form expects,
    signed and ready to render as hidden form fields."""
    data = {
        "merchant_id": MERCHANT_ID,
        "merchant_key": MERCHANT_KEY,
        "return_url": return_url,
        "cancel_url": cancel_url,
        "notify_url": notify_url,
        "m_payment_id": m_payment_id,
        "amount": f"{amount:.2f}",
        "item_name": item_name,
    }
    if email:
        data["email_address"] = email
    data["signature"] = _signature(data)
    return data


def verify_itn_signature(form_data: dict) -> bool:
    """Validates an inbound ITN webhook's signature. In sandbox mode
    this still runs the real algorithm against the sandbox credentials
    so the reconciliation code path is genuinely exercised, not
    stubbed out."""
    received_sig = form_data.get("signature", "")
    check_data = {k: v for k, v in form_data.items() if k != "signature"}
    expected_sig = _signature(check_data)
    return received_sig == expected_sig


def is_configured() -> bool:
    """True once real (non-placeholder) merchant credentials are set —
    used purely to show a 'sandbox mode' banner in the UI, not to gate
    functionality."""
    return MERCHANT_ID != "10000100" or MERCHANT_KEY != "46f0cd694581a"
