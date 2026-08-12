"""
Tests for the server-side field validation on BusinessSettingsRequest
(api/settings.py) - added as defense-in-depth alongside the client-side
sanitizers/validators in templates/settings.html, since this route can be
called directly, bypassing anything the UI enforces.

api/website.py's WebsiteRequest got the same treatment (user_id/url Field
constraints), but api/website.py can't be imported in this environment -
it pulls in incremental_ingest -> website_ingest -> trafilatura, which
isn't installed here (see other website-related test files for the same
constraint). Its regex logic was verified manually instead; see the
conversation this was built in for the verification transcript.
"""

import pytest
from pydantic import ValidationError

from api.settings import BusinessSettingsRequest


def _valid_kwargs(**overrides):
    kwargs = dict(
        user_id="+14155238886",
        business_name="Tata Power & Co.",
        welcome_message="Welcome! We're here to help.",
        ai_instructions="Always mention our 10-year warranty.",
    )
    kwargs.update(overrides)
    return kwargs


def test_valid_request_is_accepted():
    req = BusinessSettingsRequest(**_valid_kwargs())
    assert req.business_name == "Tata Power & Co."


def test_welcome_message_and_ai_instructions_allow_normal_punctuation():
    # These are full sentences a business owner writes - periods,
    # exclamation marks, apostrophes, commas must all still work.
    req = BusinessSettingsRequest(**_valid_kwargs(
        welcome_message="Hi there! Thanks for reaching out, we'll reply soon.",
        ai_instructions="Never quote prices; redirect to our sales team.",
    ))
    assert "!" in req.welcome_message
    assert ";" in req.ai_instructions


@pytest.mark.parametrize("bad_user_id", [
    "",
    "not-a-phone",
    "12345",  # too short
    "1" * 20,  # too long
    "+1 415 523 8886",  # spaces not allowed
    "+1-415-523-8886",  # dashes not allowed
])
def test_invalid_user_id_rejected(bad_user_id):
    with pytest.raises(ValidationError):
        BusinessSettingsRequest(**_valid_kwargs(user_id=bad_user_id))


@pytest.mark.parametrize("bad_name", [
    "",
    "x" * 101,
    "Acme <script>alert(1)</script>",
    "Acme; DROP TABLE users;",
    "Acme {malicious}",
])
def test_invalid_business_name_rejected(bad_name):
    with pytest.raises(ValidationError):
        BusinessSettingsRequest(**_valid_kwargs(business_name=bad_name))


def test_business_name_allows_common_punctuation():
    req = BusinessSettingsRequest(**_valid_kwargs(
        business_name="O'Brien's Solar & Electric - Est. 1998, Inc."
    ))
    assert "O'Brien's" in req.business_name


@pytest.mark.parametrize("field", ["welcome_message", "ai_instructions"])
def test_free_text_fields_reject_angle_brackets(field):
    with pytest.raises(ValidationError):
        BusinessSettingsRequest(**_valid_kwargs(**{field: "<b>hi</b>"}))


def test_welcome_message_over_limit_rejected():
    with pytest.raises(ValidationError):
        BusinessSettingsRequest(**_valid_kwargs(welcome_message="x" * 301))


def test_ai_instructions_over_limit_rejected():
    with pytest.raises(ValidationError):
        BusinessSettingsRequest(**_valid_kwargs(ai_instructions="x" * 1001))


def test_free_text_fields_default_to_empty_string():
    req = BusinessSettingsRequest(
        user_id="+14155238886",
        business_name="Acme Inc.",
    )
    assert req.welcome_message == ""
    assert req.ai_instructions == ""
