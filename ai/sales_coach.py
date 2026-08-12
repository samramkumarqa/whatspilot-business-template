def get_next_best_action(lead):

    score = lead.get("lead_score", 0)

    stage = lead.get("buying_stage", "")

    sentiment = lead.get("sentiment", "")

    objection = lead.get("objection", "")

    intent = lead.get("intent", "")

    if score >= 90:
        return {
            "action": "Call Immediately",
            "priority": "Critical",
            "reason": (
                "Very high lead score. "
                "Customer is highly likely to convert."
            )
        }

    if score >= 80:
        return {
            "action": "Schedule Sales Call",
            "priority": "High",
            "reason": (
                "Customer shows strong buying intent "
                "with a high lead score."
            )
        }

    if stage == "Ready to Buy":
        return {
            "action": "Send Proposal",
            "priority": "High",
            "reason": (
                "Customer appears ready to make a purchase."
            )
        }

    if intent == "Pricing Inquiry":
        return {
            "action": "Send Pricing Details",
            "priority": "Medium",
            "reason": (
                "Customer is actively requesting pricing."
            )
        }

    if objection == "Price":
        return {
            "action": "Send Discount Offer",
            "priority": "Medium",
            "reason": (
                "Customer's main concern is pricing."
            )
        }

    if objection == "Competitor":
        return {
            "action": "Send Comparison Sheet",
            "priority": "Medium",
            "reason": (
                "Customer mentioned a competitor."
            )
        }

    if sentiment == "Negative":
        return {
            "action": "Arrange Support Call",
            "priority": "High",
            "reason": (
                "Customer sentiment is negative."
            )
        }

    if stage == "Interested":
        return {
            "action": "Send Product Brochure",
            "priority": "Medium",
            "reason": (
                "Customer is evaluating the product."
            )
        }

    return {
        "action": "Follow Up Later",
        "priority": "Low",
        "reason": (
            "Customer currently shows low buying intent."
        )
    }