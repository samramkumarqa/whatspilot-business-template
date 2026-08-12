def generate_business_insights(
    lead_scores,
    sales_funnel,
    opportunities,
    reminders
):

    insights = []

    #
    # Lead Quality
    #

    if lead_scores["hot"] >= 5:

        insights.append({
            "type": "positive",
            "title": "Hot Leads",
            "message": f"You currently have {lead_scores['hot']} hot leads ready for sales."
        })

    if lead_scores["cold"] > lead_scores["warm"]:

        insights.append({
            "type": "warning",
            "title": "Lead Quality",
            "message": "Most leads are currently cold. Consider running a re-engagement campaign."
        })

    #
    # Sales Funnel
    #

    funnel = sales_funnel.get("funnel", {})

    if funnel.get("Proposal Sent", 0) > funnel.get("Won", 0):

        insights.append({
            "type": "warning",
            "title": "Proposal Conversion",
            "message": "Many proposals have not converted into sales. Review pricing or follow-up strategy."
        })

    #
    # Opportunities
    #

    if opportunities["pipeline_value"] > 500000:

        insights.append({
            "type": "positive",
            "title": "Strong Pipeline",
            "message": f"Current sales pipeline value is ₹{opportunities['pipeline_value']:,}."
        })

    #
    # Reminders
    #

    if reminders["overdue"] > 0:

        insights.append({
            "type": "critical",
            "title": "Overdue Follow-ups",
            "message": f"{reminders['overdue']} customer follow-ups are overdue."
        })

    if reminders["today"] > 0:

        insights.append({
            "type": "info",
            "title": "Today's Tasks",
            "message": f"You have {reminders['today']} reminders scheduled today."
        })

    return insights