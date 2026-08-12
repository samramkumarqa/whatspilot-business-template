from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
import asyncio
import logging

from auth import enforce_tenant_access
from incremental_ingest import incremental_ingest
from site_discovery import MAX_PAGES_PER_SITE
from doc_tracker import get_indexed_pages, clear_registry
from vector_store import clear_user_vectorstore

from website_manager import (
    add_website as save_website,
    delete_website,
    get_websites,
)
logger = logging.getLogger(__name__)

router = APIRouter()

# Mirrors the client-side rules in templates/settings.html
# (sanitizePhoneInput/sanitizeUrlInput/validate*()) - enforced here too
# since this route can be called directly, bypassing the UI.
class WebsiteRequest(BaseModel):
    user_id: str = Field(
        min_length=7, max_length=16, pattern=r"^\+?[0-9]{7,15}$"
    )
    url: str = Field(
        max_length=500, pattern=r'^https?://[^\s<>"\']+$'
    )
    # Multi-page discovery (sitemap-first, capped at
    # site_discovery.MAX_PAGES_PER_SITE) now happens automatically at
    # reindex time - see website_ingest.load_website_chunks() - rather
    # than here at add-time, so a business only ever adds their one root
    # URL. These fields are kept for API back-compat but are unused.
    crawl: bool = False
    max_pages: int = 50

def schedule_reindex(user_id: str):

    logger.info(
        f"Scheduling background reindex for {user_id}"
    )
    asyncio.create_task(
        asyncio.to_thread(
            incremental_ingest,
            user_id
        )
    )

@router.post("/reindex/{user_id}")
async def reindex(user_id: str, request: Request):

    enforce_tenant_access(request, user_id)

    try:
        await asyncio.to_thread(
            incremental_ingest,
            user_id
        )

        return {
            "status": "success",
            "message": f"Reindexed {user_id}"
        }

    except Exception as e:

        logger.exception(e)

        return {
            "status": "error",
            "message": str(e)
        }


@router.get("/websites")
async def websites():

    sites = await run_in_threadpool(get_websites)

    return {
        "status": "success",
        "count": len(sites),
        "websites": sorted(sites)
    }


@router.post("/website")
async def add_site(request: WebsiteRequest, http_request: Request):

    enforce_tenant_access(http_request, request.user_id)

    try:

        logger.info(
            f"Adding website for {request.user_id}"
        )

        result = await run_in_threadpool(
            save_website,
            request.user_id,
            request.url
        )

        # ------------------------------------
        # Blocked by the 1-website-per-business limit
        # ------------------------------------

        if result == "limit_reached":

            return {
                "status": "limit_reached",
                "message": (
                    "Only 1 website can be indexed per business. "
                    "Remove the existing website before adding a new one."
                )
            }

        # ------------------------------------
        # Nothing new
        # ------------------------------------

        if result == "exists":

            return {
                "status": "exists",
                "message": "Website(s) already exist."
            }

        # ------------------------------------
        # Background Reindex - this is where the site's other pages
        # actually get discovered (sitemap-first, capped at
        # MAX_PAGES_PER_SITE) and indexed, not here at add-time.
        # ------------------------------------

        logger.info(
            f"Starting background indexing for {request.user_id}"
        )

        schedule_reindex(request.user_id)

        return {

            "status": "success",

            "added_count": 1,

            "added_urls": [request.url],

            "message": (
                f"Background indexing started - up to "
                f"{MAX_PAGES_PER_SITE} pages of this site will be "
                f"discovered and indexed automatically."
            )

        }

    except Exception as e:

        logger.exception(
            f"Website add failed: {e}"
        )

        return {

            "status": "error",

            "message": str(e)

        }

@router.delete("/website")
async def remove_site(
    request: WebsiteRequest,
    http_request: Request
):

    enforce_tenant_access(http_request, request.user_id)

    try:

        removed = await run_in_threadpool(
            delete_website,
            request.user_id,
            request.url
        )

        if not removed:
            return {
                "status": "not_found",
                "message": "Website not found"
            }

        # This business has no website configured anymore - clear the
        # indexed-pages registry AND the actual embeddings in Chroma too,
        # so neither the Settings page nor the AI's answers keep
        # reflecting a site that's no longer there.
        remaining = await run_in_threadpool(
            get_websites,
            request.user_id
        )

        if not remaining:

            await run_in_threadpool(
                clear_registry,
                request.user_id
            )

            await run_in_threadpool(
                clear_user_vectorstore,
                request.user_id
            )

            # Nothing left to reindex - a reindex here would just be a
            # no-op (see website_ingest.load_website_chunks), so saying
            # "reindex started" would be misleading now that everything
            # has already been cleared above.
            return {
                "status": "success",
                "message": "Website removed - all indexed content cleared."
            }

        # Only reachable if a business ever has more than one website
        # configured (not currently possible - see website_manager.py's
        # MAX_WEBSITES_PER_USER - but kept in case that changes): other
        # sites are still indexed, so a reindex is actually meaningful.
        schedule_reindex(request.user_id)

        return {
            "status": "success",
            "message": "Website removed and reindex started"
        }

    except Exception as e:

        logger.exception(
            f"Delete website error: {e}"
        )

        return {
            "status": "error",
            "message": str(e)
        }

@router.get("/websites/{user_id}")
async def list_websites(user_id: str, request: Request):

    enforce_tenant_access(request, user_id)

    websites = await run_in_threadpool(get_websites, user_id)

    return {
        "status": "success",
        "count": len(websites),
        "websites": websites
    }


@router.get("/indexed-pages/{user_id}")
async def indexed_pages(user_id: str, request: Request):

    enforce_tenant_access(request, user_id)

    pages = await run_in_threadpool(get_indexed_pages, user_id)

    return {
        "status": "success",
        "count": len(pages),
        "pages": pages
    }

