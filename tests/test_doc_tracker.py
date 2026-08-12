import pytest

import doc_tracker


@pytest.fixture
def isolated_registry_dir(tmp_path, monkeypatch):
    """
    doc_tracker.py resolves its storage path ("data/doc_registry/...")
    relative to the process's cwd at call time, so chdir'ing into a
    throwaway directory is enough to keep these tests from touching the
    real project's data/doc_registry/ files.
    """

    monkeypatch.chdir(tmp_path)
    yield tmp_path


def test_get_indexed_pages_empty_when_nothing_indexed(isolated_registry_dir):
    assert doc_tracker.get_indexed_pages("biz1") == []


def test_get_indexed_pages_reflects_registry_sorted_by_url(isolated_registry_dir):
    doc_tracker.update_doc("biz1", "https://example.com/b", "hash-b", 3)
    doc_tracker.update_doc("biz1", "https://example.com/a", "hash-a", 5)

    pages = doc_tracker.get_indexed_pages("biz1")

    assert pages == [
        {"url": "https://example.com/a", "chunk_count": 5},
        {"url": "https://example.com/b", "chunk_count": 3},
    ]


def test_get_indexed_pages_is_per_user(isolated_registry_dir):
    doc_tracker.update_doc("biz1", "https://example.com/a", "hash-a", 5)
    doc_tracker.update_doc("biz2", "https://other.com/x", "hash-x", 2)

    assert doc_tracker.get_indexed_pages("biz1") == [
        {"url": "https://example.com/a", "chunk_count": 5},
    ]
    assert doc_tracker.get_indexed_pages("biz2") == [
        {"url": "https://other.com/x", "chunk_count": 2},
    ]


def test_clear_registry_removes_all_entries(isolated_registry_dir):
    doc_tracker.update_doc("biz1", "https://example.com/a", "hash-a", 5)
    doc_tracker.update_doc("biz1", "https://example.com/b", "hash-b", 3)

    doc_tracker.clear_registry("biz1")

    assert doc_tracker.get_indexed_pages("biz1") == []
    assert doc_tracker.is_changed("biz1", "https://example.com/a", "hash-a") is True


def test_clear_registry_does_not_affect_other_users(isolated_registry_dir):
    doc_tracker.update_doc("biz1", "https://example.com/a", "hash-a", 5)
    doc_tracker.update_doc("biz2", "https://other.com/x", "hash-x", 2)

    doc_tracker.clear_registry("biz1")

    assert doc_tracker.get_indexed_pages("biz1") == []
    assert doc_tracker.get_indexed_pages("biz2") == [
        {"url": "https://other.com/x", "chunk_count": 2},
    ]
