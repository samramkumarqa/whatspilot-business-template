"""
Tests for the business-owner login resolution helpers in
crm/customer_mapping.py - get_business_by_login_number() (used by
api/auth.py's /business-login routes) and get_owning_business_user_id()
(used by auth.py's enforce_tenant_access_for_customer()).

register_business()/set_business_status()/delete_business()/
list_businesses() and the registry CRUD API live in the separate
whatspilot-admin repo now (see its api/businesses.py and
templates/businesses.html) - this repo only ever reads the registry,
via the two functions above, to resolve who's logging in.
"""

from crm.customer_mapping import (
    register_business,
    set_business_status,
    get_business_by_login_number,
    get_owning_business_user_id,
    save_mapping,
)


# ---------------------------------------------------------------------
# get_business_by_login_number() - business-owner login can use either
# the bot's own WhatsApp number or a separate personal number (see
# api/auth.py's /business-login routes). A business isn't required to
# set owner_whatsapp_number at all - it's only needed when the bot's
# number can't itself receive login codes (e.g. a WhatsApp Business API
# number once WhatsApp-channel OTPs are in use).
# ---------------------------------------------------------------------

def test_login_number_matches_business_whatsapp_number_with_no_owner_number_set(isolated_db):
    register_business("biz1", "+14155550001")
    set_business_status("biz1", "active")

    result = get_business_by_login_number("+14155550001")

    assert result is not None
    assert result["user_id"] == "biz1"


def test_login_number_matches_owner_number_when_set(isolated_db):
    register_business(
        "biz1", "+14155550001", owner_whatsapp_number="+919876500000"
    )
    set_business_status("biz1", "active")

    result = get_business_by_login_number("+919876500000")

    assert result is not None
    assert result["user_id"] == "biz1"


def test_login_number_matches_business_number_even_when_owner_number_also_set(isolated_db):
    # Both numbers should work - registering a personal number is an
    # addition, not a replacement for logging in with the bot's own
    # number.
    register_business(
        "biz1", "+14155550001", owner_whatsapp_number="+919876500000"
    )
    set_business_status("biz1", "active")

    result = get_business_by_login_number("+14155550001")

    assert result is not None
    assert result["user_id"] == "biz1"


def test_login_number_rejects_inactive_business(isolated_db):
    register_business("biz1", "+14155550001")
    # Left at the default 'inactive' status from registration.

    assert get_business_by_login_number("+14155550001") is None


def test_login_number_rejects_unknown_number(isolated_db):
    register_business("biz1", "+14155550001")
    set_business_status("biz1", "active")

    assert get_business_by_login_number("+10000000000") is None


# ---------------------------------------------------------------------
# get_owning_business_user_id() - the single-query replacement for the
# old get_business_phone_by_customer()+get_customer_by_number() pair,
# used by auth.py's enforce_tenant_access_for_customer() on every
# customer-detail route a business_owner session hits.
# ---------------------------------------------------------------------

def test_owning_business_user_id_resolves_correctly(isolated_db):
    register_business("biz1", "+14155550001")
    save_mapping("+919900000001", "+14155550001")

    assert get_owning_business_user_id("+919900000001") == "biz1"


def test_owning_business_user_id_none_for_unknown_customer(isolated_db):
    assert get_owning_business_user_id("+919900000099") is None


def test_owning_business_user_id_distinguishes_businesses(isolated_db):
    register_business("biz1", "+14155550001")
    register_business("biz2", "+14155550002")
    save_mapping("+919900000001", "+14155550001")
    save_mapping("+919900000002", "+14155550002")

    assert get_owning_business_user_id("+919900000001") == "biz1"
    assert get_owning_business_user_id("+919900000002") == "biz2"
