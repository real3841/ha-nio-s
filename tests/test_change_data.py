"""HA-free tests for service-order capture parsing and order analytics."""

import json
import sys
from pathlib import Path

COMPONENT = Path(__file__).parent.parent / "custom_components" / "nio"
sys.path.insert(0, str(COMPONENT))

import change_capture  # noqa: E402
import change_data  # noqa: E402

CHANGE_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "change.json").read_text()
)

SAMPLE_URL = (
    "POST https://gateway-front-external.nio.com/moat/1100367/api/v1/otd/car/"
    "ext/general/serviceOrder/getTabOrder?hash_type=sha256&lang=zh&region=US"
)


def test_parse_change_capture_post_line():
    url, method = change_capture.parse_change_capture(SAMPLE_URL)
    assert method == "POST"
    assert "serviceOrder/getTabOrder" in url
    assert url.startswith("https://gateway-front-external.nio.com/")


def test_parse_change_capture_full_url():
    full = SAMPLE_URL.split(" ", 1)[1]
    url, method = change_capture.parse_change_capture(full)
    assert method == "POST"
    assert url == full


def test_change_unique_id_stable():
    uid1 = change_capture.change_unique_id("https://example.com/a?x=1")
    uid2 = change_capture.change_unique_id("https://example.com/a?x=1")
    uid3 = change_capture.change_unique_id("https://example.com/a?x=2")
    assert uid1 == uid2
    assert uid1 != uid3


def test_analyze_service_orders():
    summary = change_data.analyze_service_orders(CHANGE_FIXTURE)
    assert summary.total > 0
    assert summary.swap_completed >= 1
    assert summary.swap_spent > 0
    assert summary.last_order_time is not None
    print(
        f"  orders={summary.total} swaps={summary.swap_completed} "
        f"spent={summary.swap_spent}"
    )


def test_order_spent_amount_from_pay_desc():
    assert change_data.order_spent_amount({"payDesc": "¥ 26.21"}) == 26.21
    assert change_data.order_spent_amount({"priceCash": "10"}) == 10.0


if __name__ == "__main__":
    for fn in (
        test_parse_change_capture_post_line,
        test_parse_change_capture_full_url,
        test_change_unique_id_stable,
        test_analyze_service_orders,
        test_order_spent_amount_from_pay_desc,
    ):
        print(f"{fn.__name__}:")
        fn()
    print("ALL CHANGE TESTS PASSED")
