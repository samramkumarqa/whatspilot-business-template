"""
Tests for verify.py - the Twilio Verify wrapper business-owner login
sends OTPs through (see api/auth.py's /business-login routes). The
Twilio client itself is monkeypatched throughout, so these never call
the real Verify API.
"""

import pytest
from twilio.base.exceptions import TwilioRestException

import verify


class _FakeVerification:
    def __init__(self, status):
        self.status = status


class _FakeVerificationCheck:
    def __init__(self, status):
        self.status = status


class _FakeVerifications:
    def __init__(self, status="pending", captured=None):
        self._status = status
        self._captured = captured

    def create(self, to, channel):
        if self._captured is not None:
            self._captured["to"] = to
            self._captured["channel"] = channel
        return _FakeVerification(self._status)


class _FakeVerificationChecks:
    def __init__(self, status="approved", raise_exc=None, captured=None):
        self._status = status
        self._raise_exc = raise_exc
        self._captured = captured

    def create(self, to, code):
        if self._captured is not None:
            self._captured["to"] = to
            self._captured["code"] = code
        if self._raise_exc:
            raise self._raise_exc
        return _FakeVerificationCheck(self._status)


class _FakeService:
    def __init__(self, verifications=None, verification_checks=None):
        self._verifications = verifications or _FakeVerifications()
        self._verification_checks = (
            verification_checks or _FakeVerificationChecks()
        )

    @property
    def verifications(self):
        return self._verifications

    @property
    def verification_checks(self):
        return self._verification_checks


class _FakeServices:
    def __init__(self, service):
        self._service = service

    def __call__(self, sid):
        return self._service


class _FakeVerifyV2:
    def __init__(self, service):
        self.services = _FakeServices(service)


class _FakeVerifyClient:
    def __init__(self, service):
        self.v2 = _FakeVerifyV2(service)


def _patch_client(monkeypatch, service):
    fake_client = type("FakeClient", (), {"verify": _FakeVerifyClient(service)})()
    monkeypatch.setattr(verify, "client", fake_client)


# ---------------------------------------------------------------------
# send_otp()
# ---------------------------------------------------------------------

def test_send_otp_requires_service_sid_configured(monkeypatch):
    monkeypatch.setattr(verify, "TWILIO_VERIFY_SERVICE_SID", None)

    with pytest.raises(verify.VerifyNotConfigured):
        verify.send_otp("+15550001111")


def test_send_otp_returns_true_for_pending_status(monkeypatch):
    monkeypatch.setattr(verify, "TWILIO_VERIFY_SERVICE_SID", "VAxxxx")
    _patch_client(monkeypatch, _FakeService(_FakeVerifications(status="pending")))

    assert verify.send_otp("+15550001111") is True


def test_send_otp_uses_configured_channel_by_default(monkeypatch):
    captured = {}
    monkeypatch.setattr(verify, "TWILIO_VERIFY_SERVICE_SID", "VAxxxx")
    monkeypatch.setattr(verify, "OTP_CHANNEL", "sms")
    _patch_client(
        monkeypatch,
        _FakeService(_FakeVerifications(status="pending", captured=captured))
    )

    verify.send_otp("+15550001111")

    assert captured == {"to": "+15550001111", "channel": "sms"}


def test_send_otp_channel_override_takes_precedence(monkeypatch):
    captured = {}
    monkeypatch.setattr(verify, "TWILIO_VERIFY_SERVICE_SID", "VAxxxx")
    monkeypatch.setattr(verify, "OTP_CHANNEL", "sms")
    _patch_client(
        monkeypatch,
        _FakeService(_FakeVerifications(status="pending", captured=captured))
    )

    verify.send_otp("+15550001111", channel="whatsapp")

    assert captured["channel"] == "whatsapp"


# ---------------------------------------------------------------------
# check_otp()
# ---------------------------------------------------------------------

def test_check_otp_requires_service_sid_configured(monkeypatch):
    monkeypatch.setattr(verify, "TWILIO_VERIFY_SERVICE_SID", None)

    with pytest.raises(verify.VerifyNotConfigured):
        verify.check_otp("+15550001111", "123456")


def test_check_otp_true_for_approved(monkeypatch):
    monkeypatch.setattr(verify, "TWILIO_VERIFY_SERVICE_SID", "VAxxxx")
    _patch_client(
        monkeypatch,
        _FakeService(verification_checks=_FakeVerificationChecks(status="approved"))
    )

    assert verify.check_otp("+15550001111", "123456") is True


def test_check_otp_false_for_pending_status(monkeypatch):
    # A wrong code comes back with status "pending", not "approved" -
    # only an exact "approved" counts as success.
    monkeypatch.setattr(verify, "TWILIO_VERIFY_SERVICE_SID", "VAxxxx")
    _patch_client(
        monkeypatch,
        _FakeService(verification_checks=_FakeVerificationChecks(status="pending"))
    )

    assert verify.check_otp("+15550001111", "000000") is False


def test_check_otp_false_when_twilio_raises(monkeypatch):
    # e.g. "no pending verification found" for an expired/already-used
    # code - treated as a failed check, not a 500.
    monkeypatch.setattr(verify, "TWILIO_VERIFY_SERVICE_SID", "VAxxxx")
    exc = TwilioRestException(404, "https://api.twilio.com/fake", msg="Not found")
    _patch_client(
        monkeypatch,
        _FakeService(verification_checks=_FakeVerificationChecks(raise_exc=exc))
    )

    assert verify.check_otp("+15550001111", "123456") is False
