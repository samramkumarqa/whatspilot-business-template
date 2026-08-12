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
                f"• {alert['title']}"
            )

    return "\n".join(lines)