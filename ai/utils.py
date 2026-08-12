import json
import logging

logger = logging.getLogger(__name__)


def parse_ai_json(response, default=None):
    """
    Safely parse JSON returned by an LLM.
    Accepts either a dict or a string containing JSON.
    """

    if isinstance(response, dict):
        return response

    if not response:
        return default

    try:
        start = response.find("{")
        end = response.rfind("}") + 1

        if start == -1 or end <= start:
            return default

        return json.loads(response[start:end])

    except Exception:
        logger.exception("Failed to parse AI JSON")
        return default