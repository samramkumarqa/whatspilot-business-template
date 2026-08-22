import doc_tracker


def test_get_indexed_pages_empty_when_nothing_indexed(isolated_db):
    assert doc_tracker.get_indexed_pages("biz1") == []


def test_get_indexed_pages_reflects_registry_sorted_by_url(isolated_db):
    doc_tracker.update_doc("biz1", "https://example.com/b", "hash-b", 3)
    doc_tracker.update_doc("biz1", "https://example.com/a", "hash-a", 5)

    pages = doc_tracker.get_indexed_pages("biz1")

    assert pages == [
        {"url": "https://example.com/a", "chunk_count": 5},
        {"url": "https://example.com/b", "chunk_count": 3},
    ]


def test_get_indexed_pages_is_per_user(isolated_db):
    doc_tracker.update_doc("biz1", "https://example.com/a", "hash-a", 5)
    doc_tracker.update_doc("biz2", "https://other.com/x", "hash-x", 2)

    assert doc_tracker.get_indexed_pages("biz1") == [
        {"url": "https://example.com/a", "chunk_count": 5},
    ]
    assert doc_tracker.get_indexed_pages("biz2") == [
        {"url": "https://other.com/x", "chunk_count": 2},
    ]


def test_clear_registry_removes_all_entries(isolated_db):
    doc_tracker.update_doc("biz1", "https://example.com/a", "hash-a", 5)
    doc_tracker.update_doc("biz1", "https://example.com/b", "hash-b", 3)

    doc_tracker.clear_registry("biz1")

    assert doc_tracker.get_indexed_pages("biz1") == []
    assert doc_tracker.is_changed("biz1", "https://example.com/a", "hash-a") is True


def test_clear_registry_does_not_affect_other_users(isolated_db):
    doc_tracker.update_doc("biz1", "https://example.com/a", "hash-a", 5)
    doc_tracker.update_doc("biz2", "https://other.com/x", "hash-x", 2)

    doc_tracker.clear_registry("biz1")

    assert doc_tracker.get_indexed_pages("biz1") == []
    assert doc_tracker.get_indexed_pages("biz2") == [
        {"url": "https://other.com/x", "chunk_count": 2},
    ]


def test_is_changed_true_first_time(isolated_db):
    assert doc_tracker.is_changed("biz1", "https://example.com/a", "hash-a") is True


def test_is_changed_false_when_hash_matches(isolated_db):
    doc_tracker.update_doc("biz1", "https://example.com/a", "hash-a", 5)
    assert doc_tracker.is_changed("biz1", "https://example.com/a", "hash-a") is False


def test_is_changed_true_when_hash_differs(isolated_db):
    doc_tracker.update_doc("biz1", "https://example.com/a", "hash-a", 5)
    assert doc_tracker.is_changed("biz1", "https://example.com/a", "hash-b") is True


def test_update_doc_overwrites_existing_entry(isolated_db):
    doc_tracker.update_doc("biz1", "https://example.com/a", "hash-a", 5)
    doc_tracker.update_doc("biz1", "https://example.com/a", "hash-a2", 9)

    assert doc_tracker.get_indexed_pages("biz1") == [
        {"url": "https://example.com/a", "chunk_count": 9},
    ]
    assert doc_tracker.is_changed("biz1", "https://example.com/a", "hash-a2") is False
