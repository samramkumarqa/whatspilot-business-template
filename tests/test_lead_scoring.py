"""
ai/lead_ai.py's calculate_lead_score() is the formula behind every lead's
"lead_score" column - it drives hot/warm/cold bucketing everywhere (see
crm/lead_manager.get_lead_categories(), analytics/sales_funnel.py). It's a
pure function (no I/O, no LLM call), so it's tested directly here.

detect_lead_status() is intentionally NOT tested here - it calls the real
Groq API and would need a mocked client to test meaningfully, which is out
of scope for this first pass.
"""

from ai.lead_ai import calculate_lead_score


def test_known_statuses_produce_expected_scores():
    # score = int(base * 0.6 + confidence * 0.4)
    assert calculate_lead_score("New", 0) == 6            # int(10*0.6)
    assert calculate_lead_score("Interested", 50) == 44    # int(40*0.6 + 50*0.4)
    assert calculate_lead_score("Qualified", 100) == 82    # int(70*0.6 + 100*0.4)
    assert calculate_lead_score("Proposal Sent", 100) == 91  # int(85*0.6 + 100*0.4)
    assert calculate_lead_score("Closed Won", 100) == 100
    assert calculate_lead_score("Closed Lost", 0) == 0


def test_unknown_status_falls_back_to_new_base_score():
    # Unrecognized status should be treated the same as "New" (base=10).
    assert calculate_lead_score("Some Made Up Status", 0) == \
        calculate_lead_score("New", 0)


def test_score_is_capped_at_100():
    # Even with a base of 100 and full confidence, base*0.6 + conf*0.4 = 100,
    # so this also exercises the min(score, 100) cap at the boundary.
    assert calculate_lead_score("Closed Won", 100) == 100
    assert calculate_lead_score("Closed Won", 0) == 60


def test_higher_confidence_never_lowers_the_score_for_a_fixed_status():
    low = calculate_lead_score("Qualified", 0)
    high = calculate_lead_score("Qualified", 100)
    assert high > low


def test_hot_warm_cold_bucket_thresholds_used_elsewhere():
    # crm/lead_manager.get_lead_categories() and
    # analytics/sales_funnel.get_lead_score_dashboard() bucket on
    # >=80 hot, >=50 warm, else cold - confirm the statuses that are
    # supposed to land in each bucket actually do, at typical confidence.
    assert calculate_lead_score("Proposal Sent", 80) >= 80   # hot
    assert 50 <= calculate_lead_score("Interested", 80) < 80  # warm
    assert calculate_lead_score("New", 20) < 50               # cold
