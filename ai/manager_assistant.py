from analytics.analytics import get_dashboard
from llm import ask_llm

def ask_manager(user_id, question):
    """
    AI Manager Assistant

    Answers natural language questions using
    dashboard analytics.
    """

    dashboard = get_dashboard(user_id)

    q = question.lower().strip()

    #
    # Hot Leads
    #
    if "hot" in q and "lead" in q:

        return (
            f"You currently have "
            f"{dashboard['lead_scores']['hot']} hot leads."
        )

    #
    # Warm Leads
    #
    if "warm" in q and "lead" in q:

        return (
            f"You currently have "
            f"{dashboard['lead_scores']['warm']} warm leads."
        )

    #
    # Cold Leads
    #
    if "cold" in q and "lead" in q:

        return (
            f"You currently have "
            f"{dashboard['lead_scores']['cold']} cold leads."
        )

    #
    # Sales Funnel
    #
    if "funnel" in q:

        funnel = dashboard["sales_funnel"]["funnel"]

        return (
            f"Sales Funnel\n\n"
            f"New: {funnel['New']}\n"
            f"Interested: {funnel['Interested']}\n"
            f"Qualified: {funnel['Qualified']}\n"
            f"Proposal Sent: {funnel['Proposal Sent']}\n"
            f"Won: {funnel['Won']}\n"
            f"Lost: {funnel['Lost']}"
        )

    #
    # Pipeline
    #
    if "pipeline" in q:

        return (
            f"Current Pipeline Value is "
            f"₹{dashboard['opportunities']['pipeline_value']:,}"
        )

    #
    # Opportunities
    #
    if "opportunit" in q:

        opp = dashboard["opportunities"]

        return (
            f"Total Opportunities: {opp['total']}\n"
            f"Open: {opp['open']}\n"
            f"Won: {opp['won']}\n"
            f"Lost: {opp['lost']}\n"
            f"Pipeline Value: ₹{opp['pipeline_value']:,}"
        )

    #
    # Forecast
    #
    if (
        "forecast" in q
        or "revenue" in q
        or "prediction" in q
    ):

        forecast = dashboard["forecast"]

        return (
            f"Expected Revenue: "
            f"₹{forecast['expected_revenue']:,}\n"
            f"Expected Deals: "
            f"{forecast['expected_deals']}\n"
            f"Average Win Rate: "
            f"{forecast['average_win_probability']}%"
        )

    #
    # Reminders
    #
    if "reminder" in q or "follow" in q:

        reminders = dashboard["reminders"]

        return (
            f"Today's Reminders: {reminders['today']}\n"
            f"Upcoming: {reminders['upcoming']}\n"
            f"Overdue: {reminders['overdue']}\n"
            f"Completed: {reminders['completed']}"
        )

    #
    # Customer Health
    #
    if (
        "health" in q
        or "risk" in q
        or "churn" in q
    ):

        health = dashboard["customer_health"]

        return (
            f"Healthy Customers: {health['healthy']}\n"
            f"Watch List: {health['watchlist']}\n"
            f"At Risk: {health['at_risk']}"
        )

    #
    # AI Alerts
    #
    if "alert" in q:

        alerts = dashboard["ai_alerts"]

        if not alerts:

            return "No active AI alerts."

        answer = "Current AI Alerts\n\n"

        for alert in alerts:

            answer += (
                f"• {alert['title']}\n"
                f"  {alert['message']}\n\n"
            )

        return answer

    #
    # Executive Summary
    #
    if (
        "summary" in q
        or "business summary" in q
    ):

        return dashboard["executive_summary"]

    #
    # Daily Briefing
    #
    if (
        "today" in q
        or "brief" in q
        or "daily" in q
    ):

        return dashboard["daily_briefing"]

    #
    # Business Insights
    #
    if (
        "insight" in q
        or "recommendation" in q
    ):

        insights = dashboard["business_insights"]

        if not insights:

            return "No business insights available."

        answer = "Business Insights\n\n"

        for item in insights:

            answer += (
                f"• {item['title']}\n"
                f"  {item['message']}\n\n"
            )

        return answer

    #
    # Metrics
    #
    if (
        "customer" in q
        or "message" in q
        or "metric" in q
    ):

        metrics = dashboard["metrics"]

        return (
            f"Customers: {metrics['customers']}\n"
            f"Messages: {metrics['messages']}\n"
            f"Today's Messages: {metrics['today_messages']}"
        )

    #
    # Default
    #
    dashboard = get_dashboard(user_id)

    prompt = f"""
    You are an experienced Sales Director.

    You are answering questions about a CRM.

    Below is the complete dashboard.

    Dashboard

    {dashboard}

    Manager Question

    {question}

    Answer professionally.

    Give practical business advice.

    Maximum 200 words.

    Do not use markdown.
    """

    try:

        answer = ask_llm(

            system_prompt="You are a Sales Director.",

            user_prompt=prompt

        )

        return answer.strip()

    except Exception:

        return (
            "I'm unable to answer that question right now."
        )