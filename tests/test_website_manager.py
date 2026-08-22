import website_manager


def test_add_first_website_succeeds(isolated_db):
    result = website_manager.add_website("biz1", "https://example.com")

    assert result == "added"
    assert website_manager.get_websites("biz1") == ["https://example.com"]


def test_add_same_website_twice_returns_exists(isolated_db):
    website_manager.add_website("biz1", "https://example.com")
    result = website_manager.add_website("biz1", "https://example.com")

    assert result == "exists"
    assert website_manager.get_websites("biz1") == ["https://example.com"]


def test_add_second_distinct_website_is_blocked(isolated_db):
    website_manager.add_website("biz1", "https://example.com")
    result = website_manager.add_website("biz1", "https://other-site.com")

    assert result == "limit_reached"
    # The rejected second website must not have been persisted.
    assert website_manager.get_websites("biz1") == ["https://example.com"]


def test_limit_is_per_user(isolated_db):
    website_manager.add_website("biz1", "https://example.com")
    result = website_manager.add_website("biz2", "https://other-site.com")

    assert result == "added"
    assert website_manager.get_websites("biz2") == ["https://other-site.com"]


def test_delete_then_add_allows_a_new_website(isolated_db):
    website_manager.add_website("biz1", "https://example.com")
    website_manager.delete_website("biz1", "https://example.com")

    result = website_manager.add_website("biz1", "https://new-site.com")

    assert result == "added"
    assert website_manager.get_websites("biz1") == ["https://new-site.com"]


def test_delete_nonexistent_website_returns_false(isolated_db):
    assert website_manager.delete_website("biz1", "https://example.com") is False


def test_normalize_url_strips_trailing_slash():
    assert website_manager.normalize_url("https://example.com/") == "https://example.com"
    assert website_manager.normalize_url("  https://example.com  ") == "https://example.com"
