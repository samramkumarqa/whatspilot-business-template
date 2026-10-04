from crm.customer_mapping import save_customer_number, save_mapping, get_customers
from conversations import add_message
from analytics.customer_stats import get_customer_stats, get_customer_stats_page
from reminder_manager import upsert_reminder, get_reminders, get_reminders_page


def _seed_customers(n):
    save_customer_number("owner1", "+14155238886", "test_business_id")
    for i in range(n):
        phone = f"+1555000{i:04d}"
        save_mapping(customer_phone=phone, business_phone="+14155238886", customer_name=f"C{i}")
        add_message(f"test_business_id:{phone}", "user", f"hello {i}")


def test_customer_page_slices_and_reports_totals(isolated_db):
    _seed_customers(25)

    p1 = get_customer_stats_page("owner1", limit=10, offset=0)
    p2 = get_customer_stats_page("owner1", limit=10, offset=10)
    p3 = get_customer_stats_page("owner1", limit=10, offset=20)

    assert [len(p["customers"]) for p in (p1, p2, p3)] == [10, 10, 5]
    assert p1["total"] == p2["total"] == p3["total"] == 25
    assert (p1["has_more"], p2["has_more"], p3["has_more"]) == (True, True, False)

    seen = [c["phone"] for p in (p1, p2, p3) for c in p["customers"]]
    assert len(seen) == len(set(seen)) == 25  # no duplicates / gaps across pages


def test_paged_rows_match_unpaged_rows(isolated_db):
    _seed_customers(12)
    full = {c["phone"]: c for c in get_customer_stats("owner1")}
    page = get_customer_stats_page("owner1", limit=5, offset=0)["customers"]
    for c in page:
        assert c == full[c["phone"]]  # unread/last_message/etc. identical per row


def test_unpaged_get_customer_stats_unchanged(isolated_db):
    _seed_customers(7)
    assert len(get_customer_stats("owner1")) == 7


def test_limit_is_clamped(isolated_db):
    _seed_customers(3)
    assert get_customer_stats_page("owner1", limit=10**6)["limit"] == 1000
    assert get_customer_stats_page("owner1", limit=0)["limit"] == 1
    assert get_customer_stats_page("owner1", offset=-5)["offset"] == 0


def test_qualified_total_counts_all_customers_not_just_page(isolated_db):
    _seed_customers(6)
    from database.db import execute_crm
    for i in range(6):
        execute_crm(
            "INSERT INTO leads (customer_phone, business_id, lead_score) VALUES (?, ?, ?)",
            (f"+1555000{i:04d}", "test_business_id", 90 if i < 4 else 10),
        )
    page = get_customer_stats_page("owner1", limit=2)
    assert len(page["customers"]) == 2
    assert page["qualified_total"] == 4


def test_unknown_business_returns_empty_page(isolated_db):
    page = get_customer_stats_page("nobody")
    assert page["customers"] == [] and page["total"] == 0 and page["has_more"] is False


def test_reminders_paging_and_overdue_count(isolated_db):
    for i in range(7):
        upsert_reminder(f"+1555000{i:04d}", f"text {i}", days=0)
    from database.db import execute_crm
    execute_crm("UPDATE reminders SET due_date = '2000-01-01' WHERE reminder_text IN ('text 0','text 1','text 2')")

    p1 = get_reminders_page(limit=3, offset=0)
    p2 = get_reminders_page(limit=3, offset=3)
    p3 = get_reminders_page(limit=3, offset=6)

    assert [len(p["reminders"]) for p in (p1, p2, p3)] == [3, 3, 1]
    assert p1["total"] == 7 and p1["overdue_count"] == 3
    assert p3["has_more"] is False and p1["has_more"] is True
    assert {r["id"] for p in (p1, p2, p3) for r in p["reminders"]} == {r["id"] for r in get_reminders()}
    assert all(r["due_date"] == "2000-01-01" for r in p1["reminders"])  # soonest first


def test_get_customers_pages_and_defaults_to_all(isolated_db):
    _seed_customers(9)
    assert len(get_customers("owner1")) == 9
    assert len(get_customers("owner1", limit=4, offset=0)) == 4
    assert len(get_customers("owner1", limit=4, offset=8)) == 1
