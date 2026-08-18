import os
import threading
import logging

from config import CHROMA_DB

logger = logging.getLogger(__name__)


_embeddings = None

# Chroma's default local persistent backend isn't safe for two separate
# Chroma client instances to hit the same on-disk persist_dir at once -
# incremental_ingest.py (background reindex, runs in its own thread) and
# rag_handler.py (a live customer query, runs in its own thread too - see
# _retrieve_docs()) each construct a fresh Chroma(...) via
# get_user_vectorstore() below. Without serializing them, a query that
# lands while a reindex is mid-write throws (typically a sqlite "database
# is locked" style error from Chroma's backing store), which
# rag_handler.py's broad except Exception turns into "Sorry, I am unable
# to access the knowledge base right now." - exactly what happened right
# after a website was first added, while its initial background index
# was still running. One lock per business (not global) so concurrent
# indexing/querying for *different* businesses on the same deployment
# still runs in parallel.
_user_locks = {}
_user_locks_guard = threading.Lock()


def get_user_lock(user_id: str) -> threading.Lock:

    with _user_locks_guard:

        if user_id not in _user_locks:
            _user_locks[user_id] = threading.Lock()

        return _user_locks[user_id]


class _FastEmbedEmbeddings:
    """
    Minimal LangChain Embeddings-compatible wrapper around fastembed's
    TextEmbedding - implements just the two methods langchain_chroma.Chroma
    actually calls (embed_documents/embed_query).

    Replaces langchain_huggingface.HuggingFaceEmbeddings, which pulls in
    sentence-transformers -> torch (transitively ~1-2GB installed, several
    hundred MB just to import). fastembed runs the *same* model
    (sentence-transformers/all-MiniLM-L6-v2 - see fastembed's supported-
    models list, 384-dim, ~90MB) via ONNX Runtime instead of PyTorch, so
    embedding quality is unchanged, but the app no longer needs torch,
    transformers, or sentence-transformers at all. This is what was
    OOM-ing every business-portal deployment on Render's 512MB free tier
    (see whatspilot-admin-repo's task history, "post-boot runtime OOM") -
    the earlier fix (deferring the *import* to first use, below) wasn't
    enough on its own, because the underlying torch/transformers stack is
    heavy even just sitting imported in memory once anything touches it.
    """

    def __init__(self, model_name="sentence-transformers/all-MiniLM-L6-v2"):
        from fastembed import TextEmbedding
        self._model = TextEmbedding(model_name=model_name)

    def embed_documents(self, texts):
        return [vec.tolist() for vec in self._model.embed(texts)]

    def embed_query(self, text):
        return next(self._model.embed([text])).tolist()


def get_embeddings():
    """
    Deferred to first use (instead of module level) so a plain app boot
    (auth, dashboard, webhook receiving, CRM, automation - everything
    that doesn't touch the website-RAG feature) doesn't pay the cost of
    loading the embedding model at all.
    """

    global _embeddings
    if _embeddings is None:
        _embeddings = _FastEmbedEmbeddings()
    return _embeddings


def get_user_vectorstore(user_id: str):

    from langchain_chroma import Chroma

    # CHROMA_DB defaults to "./chroma_db" (see config.py) but is
    # overridable via CHROMA_DB_PATH - this was previously ignored here
    # (hardcoded to "chroma_db/{user_id}"), so setting that env var in
    # production silently did nothing. Wired through now so pointing it
    # at a persistent disk mount (once one is attached) actually works.
    persist_dir = os.path.join(CHROMA_DB, user_id)

    os.makedirs(persist_dir, exist_ok=True)

    return Chroma(
        persist_directory=persist_dir,
        embedding_function=get_embeddings()
    )


def clear_user_vectorstore(user_id: str):
    """
    Wipes all indexed website content for this user - called when their
    last website is deleted (see api/website.py's DELETE /website), so old
    page embeddings don't linger in Chroma and keep surfacing in AI
    answers after the site itself is gone from Settings.

    Safe to call even if nothing was ever indexed for this user - Chroma
    raises if there's no collection to delete, which we just log and
    swallow rather than fail the whole delete-website request over.
    """

    try:

        vectorstore = get_user_vectorstore(user_id)
        vectorstore.delete_collection()

    except Exception as e:

        logger.info(
            f"clear_user_vectorstore: nothing to clear for {user_id}: {e}"
        )


def get_retriever(user_id: str):

    vectorstore = get_user_vectorstore(user_id)

    return vectorstore.as_retriever(
        search_type="mmr",
        search_kwargs={
            "k": 5,
            "fetch_k": 20
        }
    )