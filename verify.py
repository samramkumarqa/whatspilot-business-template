"""
Twilio Verify wrapper for business-owner login OTPs (see api/auth.py's
business-login routes). This is a distinct Twilio product from
whatsapp.py's send_message() - Verify generates, delivers, expires, and
rate-limits one-time codes itself; it isn't a free-form message send, so
it doesn't share whatsapp.py's chunking/sandbox concerns.

Uses config.OTP_CHANNEL ("sms" by default) rather than "whatsapp" -
Verify's WhatsApp channel requires a registered production WhatsApp
sender and Meta-approved Authentication Templates, neither of which
exist on the Twilio Sandbox this app currently runs on. Switching to
WhatsApp later is a one-line env var change (config.py's OTP_CHANNEL),
not a code change here.
"""

import logging

from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client

from config import (
    OTP_CHANNEL,
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_VERIFY_SERVICE_SID,
)

logger = logging.getLogger(__name__)

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


class VerifyNotConfigured(Exception):
    """
    Raised when TWILIO_VERIFY_SERVICE_SID isn't set - business login is
    meant to be optional until that's provisioned (unlike admin login,
    which main.py refuses to start without). Callers turn this into a
    friendly in-page error rather than a 500.
    """


def _require_service_sid():

    if not TWILIO_VERIFY_SERVICE_SID:
        raise VerifyNotConfigured(
            "TWILIO_VERIFY_SERVICE_SID is not set - create a Verify "
            "Service in the Twilio console and add its SID to .env "
            "before business-owner login can send OTPs."
        )


def send_otp(phone: str, channel: str = None) -> bool:
    """
    Sends a one-time code to `phone` (E.164, e.g. "+15017122661" - no
    "whatsapp:" prefix regardless of channel) via Twilio Verify.
    `channel` defaults to config.OTP_CHANNEL. Returns True if Twilio
    accepted the request (status "pending"); raises VerifyNotConfigured
    if no Verify Service is set up, or TwilioRestException for anything
    Twilio itself rejects (e.g. malformed number) - callers should catch
    both and show a friendly error rather than letting either 500.
    """

    _require_service_sid()

    verification = client.verify.v2.services(
        TWILIO_VERIFY_SERVICE_SID
    ).verifications.create(
        to=phone,
        channel=channel or OTP_CHANNEL,
    )

    logger.info(
        "OTP requested for %s via %s: status=%s",
        phone, channel or OTP_CHANNEL, verification.status
    )

    return verification.status in ("pending", "approved")


def check_otp(phone: str, code: str) -> bool:
    """
    Verifies a code the user entered against Twilio's record for
    `phone`. Returns True only for an "approved" check - a wrong code,
    expired code, or too many attempts all come back False rather than
    raising, except for TwilioRestException cases like "no pending
    verification found" (e.g. a code that was never sent, or was
    already used), which are caught here and also treated as a failed
    check rather than surfacing as a 500.
    """

    _require_service_sid()

    try:

        check = client.verify.v2.services(
            TWILIO_VERIFY_SERVICE_SID
        ).verification_checks.create(
            to=phone,
            code=code,
        )

    except TwilioRestException:

        logger.exception("OTP check failed for %s", phone)

        return False

    return check.status == "approved"
