from langchain_core.documents import Document

import vector_store


# ------------------------------------------------------------------
# Pure-math helpers - no DB needed, so these run even without a real
# Postgres/pgvector connection.
# ------------------------------------------------------------------

def test_cosine_similarity_identical_vectors_is_one():
    v = [1.0, 2.0, 3.0]
    assert vector_store._cosine_similarity(v, v) == 1.0


def test_cosine_similarity_orthogonal_vectors_is_zero():
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert vector_store._cosine_similarity(a, b) == 0.0


def test_cosine_similarity_opposite_vectors_is_minus_one():
    a = [1.0, 0.0]
    b = [-1.0, 0.0]
    assert vector_store._cosine_similarity(a, b) == -1.0


def test_cosine_similarity_zero_vector_does_not_divide_by_zero():
    a = [0.0, 0.0]
    b = [1.0, 1.0]
    assert vector_store._cosine_similarity(a, b) == 0.0


def test_to_pgvector_literal_formats_as_bracketed_csv():
    literal = vector_store._to_pgvector_literal([0.1, 0.2, 0.3])
    assert literal == "[0.1,0.2,0.3]"


def test_parse_pgvector_round_trips_the_literal_format():
    original = [0.1, 0.2, 0.3]
    literal = vector_store._to_pgvector_literal(original)
    assert vector_store._parse_pgvector(literal) == original


def test_parse_pgvector_handles_none():
    assert vector_store._parse_pgvector(None) == []


def test_parse_pgvector_handles_already_parsed_list():
    assert vector_store._parse_pgvector([0.1, 0.2]) == [0.1, 0.2]


def test_mmr_select_returns_all_candidates_when_fewer_than_k():
    candidates = [
        {"content": "a", "source": "s1", "embedding": [1.0, 0.0]},
        {"content": "b", "source": "s2", "embedding": [0.0, 1.0]},
    ]
    result = vector_store._mmr_select([1.0, 0.0], candidates, k=5)
    assert result == candidates


def test_mmr_select_prefers_diversity_over_pure_similarity():
    """
    Three candidates: two are near-identical to each other and to the
    query (99.99% redundant with each other), one is more distinct
    (lower but still solid relevance to the query). Plain top-2 cosine
    similarity would return the two near-duplicates; MMR should prefer
    including the distinct one for the second slot instead, since its
    small relevance drop is outweighed by how much less redundant it is
    with the already-selected near-duplicate.
    """

    query = [1.0, 0.0, 0.0]

    near_dup_1 = {
        "content": "near dup 1",
        "source": "s1",
        "embedding": [0.9, 0.1, 0.0],
    }
    near_dup_2 = {
        "content": "near dup 2",
        "source": "s2",
        "embedding": [0.89, 0.11, 0.0],
    }
    distinct_but_relevant = {
        "content": "distinct",
        "source": "s3",
        "embedding": [0.75, 0.0, 0.66],
    }

    candidates = [near_dup_1, near_dup_2, distinct_but_relevant]

    result = vector_store._mmr_select(query, candidates, k=2)

    assert near_dup_1 in result
    assert distinct_but_relevant in result
    assert near_dup_2 not in result


def test_mmr_select_first_pick_is_always_most_relevant_to_query():
    query = [1.0, 0.0]

    candidates = [
        {"content": "low", "source": "s1", "embedding": [0.1, 0.99]},
        {"content": "high", "source": "s2", "embedding": [0.99, 0.1]},
    ]

    result = vector_store._mmr_select(query, candidates, k=1)

    assert result == [candidates[1]]


# ------------------------------------------------------------------
# DB-backed behavior - requires isolated_db (a real Postgres
# connection with the vector extension enabled - see enable_pgvector.py).
# ------------------------------------------------------------------

def _fake_chunk(text, source):
    return Document(page_content=text, metadata={"source": source})


def test_add_documents_then_similarity_search_finds_relevant_chunk(isolated_db):

    vector_store.add_documents(
        "biz1",
        "https://example.com/pricing",
        [_fake_chunk("Our pricing starts at $129 for the Starter plan.", "https://example.com/pricing")],
    )

    vector_store.add_documents(
        "biz1",
        "https://example.com/about",
        [_fake_chunk("We are a small business based in Chennai.", "https://example.com/about")],
    )

    results = vector_store.similarity_search("biz1", "How much does it cost?", k=1)

    assert len(results) == 1
    assert "pricing" in results[0]["content"].lower() or "$129" in results[0]["content"]


def test_similarity_search_is_scoped_per_user(isolated_db):

    vector_store.add_documents(
        "biz1",
        "https://example.com/a",
        [_fake_chunk("Business One content about widgets.", "https://example.com/a")],
    )

    vector_store.add_documents(
        "biz2",
        "https://other.com/a",
        [_fake_chunk("Business Two content about gadgets.", "https://other.com/a")],
    )

    results = vector_store.similarity_search("biz1", "widgets", k=5)

    assert all("biz2" not in r["source"] for r in results)
    assert all(r["source"].startswith("https://example.com") for r in results)


def test_add_documents_replaces_old_chunks_for_same_url(isolated_db):

    url = "https://example.com/page"

    vector_store.add_documents(
        "biz1", url, [_fake_chunk("Old outdated content here.", url)]
    )

    vector_store.add_documents(
        "biz1", url, [_fake_chunk("New updated content here.", url)]
    )

    conn = __import__("database.db", fromlist=["get_crm_connection"]).get_crm_connection()
    rows = conn.execute(
        "SELECT content FROM website_chunks WHERE user_id = ? AND url = ?",
        ("biz1", url),
    ).fetchall()
    conn.close()

    assert len(rows) == 1
    assert rows[0][0] == "New updated content here."


def test_clear_user_vectorstore_removes_all_chunks(isolated_db):

    vector_store.add_documents(
        "biz1",
        "https://example.com/a",
        [_fake_chunk("Some content.", "https://example.com/a")],
    )

    vector_store.clear_user_vectorstore("biz1")

    assert vector_store.similarity_search("biz1", "content", k=5) == []


def test_get_user_lock_same_user_returns_same_lock():
    assert vector_store.get_user_lock("biz1") is vector_store.get_user_lock("biz1")


def test_get_user_lock_different_users_return_different_locks():
    assert vector_store.get_user_lock("biz1") is not vector_store.get_user_lock("biz2")
