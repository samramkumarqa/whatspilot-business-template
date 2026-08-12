import os
import logging

from config import CHROMA_DB

logger = logging.getLogger(__name__)


_embeddings = None



def get_embeddings():
    """
    langchain_huggingface pulls in sentence-transformers -> torch, which
    alone commonly needs several hundred MB just to import - deferring
    the import to here (instead of module level) means a plain app boot
    (auth, dashboard, webhook receiving, CRM, automation - everything
    that doesn't touch the website-RAG feature) doesn't pay that cost.
    This matters concretely on Render's free/Starter tier (512MB RAM):
    the app OOM'd on startup before this change, purely from importing
    main.py's dependency chain, before a single request was served.
    """

    global _embeddings
    if _embeddings is None:
        from langchain_huggingface import HuggingFaceEmbeddings
        _embeddings = HuggingFaceEmbeddings(
            model_name="all-MiniLM-L6-v2"
        )
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