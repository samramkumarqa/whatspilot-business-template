import pytest

import website_manager


@pytest.fixture
def isolated_website_dir(tmp_path, monkeypatch):
    """
    website_manager.WEBSITE_DIR is resolved once at import time relative to
    the real project directory (unlike the sqlite paths in database/db.py,
    which resolve relative to cwd) - so tests that call add_website/
    delete_website would otherwise write into this project's real
    data/websites/ directory. This points WEBSITE_DIR at a throwaway
    directory for the duration of the test instead.
    """

    monkeypatch.setattr(website_manager, "WEBSITE_DIR", tmp_path)
    yield tmp_path


def test_add_first_website_succeeds(isolated_website_dir):
    result = website_manager.add_website("biz1", "https://example.com")

    assert result == "added"
    assert website_manager.get_websites("biz1") == ["https://example.com"]


def test_add_same_website_twice_returns_exists(isolated_website_dir):
    website_manager.add_website("biz1", "https://example.com")
    result = website_manager.add_website("biz1", "https://example.com")

    assert result == "exists"
    assert website_manager.get_websites("biz1") == ["https://example.com"]


def test_add_second_distinct_website_is_blocked(isolated_website_dir):
    website_manager.add_website("biz1", "https://example.com")
    result = website_manager.add_website("biz1", "https://other-site.com")

    assert result == "limit_reached"
    # The rejected second website must not have been persisted.
    assert website_manager.get_websites("biz1") == ["https://example.com"]


def test_limit_is_per_user(isolated_website_dir):
    website_manager.add_website("biz1", "https://example.com")
    result = website_manager.add_website("biz2", "https://other-site.com")

    assert result == "added"
    assert website_manager.get_websites("biz2") == ["https://other-site.com"]


def test_delete_then_add_allows_a_new_website(isolated_website_dir):
    website_manager.add_website("biz1", "https://example.com")
    website_manager.delete_website("biz1", "https://example.com")

    result = website_manager.add_website("biz1", "https://new-site.com")

    assert result == "added"
    assert website_manager.get_websites("biz1") == ["https://new-site.com"]
