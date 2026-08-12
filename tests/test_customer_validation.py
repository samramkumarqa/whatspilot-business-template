"""
Tests for the server-side field validation on LeadRequest and
CustomerNameRequest (api/customer.py) - added as defense-in-depth
alongside the client-side sanitizers/validators in templates/dashboard.html
(sanitizeNameInput/sanitizeFreeTextInput/validate*()), since these routes
can be called directly, bypassing anything the UI enforces.
"""

import pytest
from pydantic import ValidationError

from api.customer import LeadRequest, CustomerNameRequest


def test_valid_lead_request_is_accepted():
    req = LeadRequest(
        customer_phone="+19998887777",
        status="Interested",
        notes="Called them, left a voicemail.",
    )
    assert req.status == "Interested"


def test_lead_notes_allow_normal_punctuation():
    req = LeadRequest(
        customer_phone="+19998887777",
        status="New",
        notes="They said: \"call back after 5pm\" - noted!",
    )
    assert "noted!" in req.notes


def test_lead_notes_default_to_empty_string():
    req = LeadRequest(customer_phone="+19998887777", status="New")
    assert req.notes == ""


@pytest.mark.parametrize("bad_status", [
    "",
    "Bogus",
    "new",  # wrong case
    "Closed",
])
def test_invalid_lead_status_rejected(bad_status):
    with pytest.raises(ValidationError):
        LeadRequest(customer_phone="+19998887777", status=bad_status, notes="")


def test_lead_notes_reject_angle_brackets():
    with pytest.raises(ValidationError):
        LeadRequest(
            customer_phone="+19998887777",
            status="New",
            notes="<script>alert(1)</script>",
        )


def test_lead_notes_over_limit_rejected():
    with pytest.raises(ValidationError):
        LeadRequest(
            customer_phone="+19998887777",
            status="New",
            notes="x" * 1001,
        )


def test_customer_name_allows_empty_string():
    req = CustomerNameRequest(customer_phone="+19998887777", name="")
    assert req.name == ""


def test_customer_name_allows_common_punctuation():
    req = CustomerNameRequest(customer_phone="+19998887777", name="O'Brien-Smith Jr.")
    assert req.name == "O'Brien-Smith Jr."


@pytest.mark.parametrize("bad_name", [
    "x" * 101,
    "Bad <script>alert(1)</script>",
    "Name; DROP TABLE users;",
    "Name {malicious}",
])
def test_customer_name_rejects_invalid_input(bad_name):
    with pytest.raises(ValidationError):
        CustomerNameRequest(customer_phone="+19998887777", name=bad_name)
