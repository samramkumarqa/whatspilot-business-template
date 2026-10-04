from datetime import datetime


def generate_daily_briefing(dashboard):

    lead_scores = dashboard["lead_scores"]

    reminders = dashboard["reminders"]

    opportunities = dashboard["opportunities"]

    forecast = dashboard["forecast"]

    customer_health = dashboard["customer_health"]

    alerts = dashboard["ai_alerts"]

    lines = []

    greeting = (
        "Good Morning"
        if datetime.now().hour < 12
        else "Good Afternoon"
    )

    lines.append(f"{greeting} 👋")

    lines.append("")

    lines.append("Today's AI Sales Brief")

    lines.append("")

    if lead_scores["hot"]:

        lines.append(
            f"🔥 {lead_scores['hot']} Hot Leads need attention."
        )

    if reminders["today"]:

        lines.append(
            f"📅 {reminders['today']} Follow-ups scheduled today."
        )

    if reminders["overdue"]:

        lines.append(
            f"⚠️ {reminders['overdue']} Overdue follow-ups."
        )

    if opportunities["pipeline_value"]:

        lines.append(
            f"💰 Pipeline Value: ₹{opportunities['pipeline_value']:,}"
        )

    if forecast["expected_revenue"]:

        lines.append(
            f"📈 Expected Revenue: ₹{forecast['expected_revenue']:,}"
        )

    if customer_health["at_risk"]:

        lines.append(
            f"🚨 {customer_health['at_risk']} customers are at risk."
        )

    if alerts:

        lines.append("")

        lines.append("Priority Alerts")

        for alert in alerts[:3]:

            lines.append(
                # analytics/ai_alerts.py emits {"type", "priority",
                # "message"} - there is no "title" key, so indexing it
                # raised KeyError and 500'd the whole /dashboard/{user_id}
                # response for any business with at least one alert.
                f"• {alert.get('title') or alert.get('type') or alert.get('message')}"
            )

    return "\n".join(lines)