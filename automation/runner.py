import logging

from automation.database import get_all_rules
from automation.evaluator import evaluate_rule
from automation.executor import execute_actions
from automation.rule_stats import record_rule_execution
from analytics.customer_stats import get_customer_stats
from crm.customer_mapping import get_active_businesses
from config import BUSINESS_ID

logger = logging.getLogger(__name__)


def run_automation():
    """
    Runs every minute via APScheduler (see automation/service.py).

    Single-tenant-per-deployment: this deployment only ever runs
    automation for its own business (BUSINESS_ID - see config.py), even
    though get_active_businesses() queries the same shared Postgres
    database every other customer's deployment also connects to. Without
    this filter, this deployment's scheduler would also fire rules for
    every *other* active business in the shared registry - each
    customer's portal used to be the same single multi-tenant app
    looping over every tenant, but now that each customer has their own
    deployment, only the admin app's registry is meant to see every
    business; this one sees (and acts on) only its own. If the admin
    deactivates this business, get_active_businesses() stops including
    it and this loop naturally does nothing that tick.
    """

    logger.info("Automation Runner Started")

    try:

        businesses = [
            business for business in get_active_businesses()
            if business["business_id"] == BUSINESS_ID
        ]

        if not businesses:
            logger.info("This deployment's business (%s) is not active - skipping.", BUSINESS_ID)
            return

        for business in businesses:

            business_id = business["business_id"]
            user_id = business["user_id"]

            rules = get_all_rules(business_id)

            logger.info(
                "Business %s: %d rule(s) found", business_id, len(rules)
            )

            if not rules:
                continue

            # Fetched once and reused across every one of this
            # business's rules below, instead of evaluate_rule()
            # re-running the same get_customer_stats(user_id) query (4+
            # queries on its own - see analytics/customer_stats.py) once
            # per rule.
            customers = get_customer_stats(user_id)

            for rule in rules:

                logger.debug("Evaluating Rule : %s", rule["name"])

                matched = evaluate_rule(rule, user_id, customers)

                logger.debug("Matched Customers : %d", len(matched))

                if matched:

                    execute_actions(rule, matched)

                    for customer in matched:

                        # Logged regardless of whether execute_actions()'s
                        # individual action handlers succeeded - "the rule
                        # fired for this customer" is about the condition
                        # match, not the action outcome. Feeds the Rule
                        # Performance table on the Analytics page (see
                        # automation/rule_stats.py).
                        record_rule_execution(
                            rule["id"],
                            rule["name"],
                            business_id,
                            customer["phone"]
                        )

                        logger.debug(
                            "  %s (Lead Score: %s)",
                            customer["phone"],
                            customer["lead_score"],
                        )

                else:

                    logger.debug(
                        "No matching customers for rule : %s", rule["name"]
                    )

    except Exception:

        logger.exception("Error inside automation runner")

    logger.info("Automation Runner Finished")
