"""
Regression tests for the polling-support functions dashboard.html calls
every 5s to detect new WhatsApp messages without a full page reload
(checkCustomerUpdates() -> GET /customers-last/{user_id} ->
conversations.get_last_customer_update(), and
checkConversationUpdates() -> GET /conversation-last/{user_id}/{phone} ->
api/settings._fetch_last_message()).

Both used to build their `conversations.phone` lookup key straight from
user_id (e.g. f"{user_id}:%"), but every real row is keyed by business_id
- a distinct value looked up via crm.customer_mapping.get_business_id().
Whenever business_id != user_id for a given business, both functions
silently matched zero rows forever: the poll's hash never changed, so
the inbox list and an already-open conversation never refreshed on
their own - only a full page reload (which goes through
analytics.customer_stats.get_customer_stats(), which resolves
business_id correctly) ever showed new messages. These tests use a
user_id that deliberately differs from business_id to catch that class
of bug if it comes back.
"""

from crm.customer_mapping import save_customer_number
from conversations import add_message, get_last_customer_update
from api.settings import _fetch_last_message


def test_get_last_customer_update_none_for_unregistered_user(isolated_db):
    assert get_last_customer_update("owner_with_no_business") is None


def test_get_last_customer_update_none_with_no_conversations_yet(isolated_db):
    save_customer_number("owner1", "+10000000001", "biz1")

    assert get_last_customer_update("owner1") is None


def test_get_last_customer_update_finds_message_keyed_by_business_id(isolated_db):
    save_customer_number("owner1", "+10000000001", "biz1")
    add_message("biz1:+919900000000", "user", "Hi there")

    assert get_last_customer_update("owner1") is not None


def test_fetch_last_message_empty_for_unregistered_user(isolated_db):
    assert _fetch_last_message("owner_with_no_business", "+919900000000") == ""


def test_fetch_last_message_empty_with_no_conversation_yet(isolated_db):
    save_customer_number("owner1", "+10000000001", "biz1")

    assert _fetch_last_message("owner1", "+919900000000") == ""


def test_fetch_last_message_finds_message_keyed_by_business_id(isolated_db):
    save_customer_number("owner1", "+10000000001", "biz1")
    add_message("biz1:+919900000000", "user", "Hi there")

    assert _fetch_last_message("owner1", "+919900000000") != ""


def test_fetch_last_message_is_scoped_to_the_right_customer(isolated_db):
    save_customer_number("owner1", "+10000000001", "biz1")
    add_message("biz1:+919900000000", "user", "Hi there")

    # A different customer of the same business with no messages of
    # their own must not pick up biz1's other conversation.
    assert _fetch_last_message("owner1", "+919900000001") == ""
