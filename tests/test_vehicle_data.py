"""HA-free tests for alert and dashboard helper logic."""

import json
import sys
from pathlib import Path

COMPONENT = Path(__file__).parent.parent / "custom_components" / "nio"
sys.path.insert(0, str(COMPONENT))

import vehicle_data  # noqa: E402

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "status.json").read_text()
)
DATA = FIXTURE["data"]


def test_compute_alerts_fixture_adc_offline():
    alerts = vehicle_data.compute_alerts(DATA)
    ids = {a.id for a in alerts}
    assert "adc-offline" in ids
    assert vehicle_data.problem_alert_count(alerts) == 0
    print(f"  info alerts: {[a.title for a in alerts]}")


def test_compute_alerts_all_clear():
    payload = json.loads(json.dumps(DATA))
    payload["connection_status"]["adc_connected"] = True
    alerts = vehicle_data.compute_alerts(payload)
    assert len(alerts) == 1
    assert alerts[0].tone == "success"
    print(f"  all-clear: {alerts[0].title}")


def test_compute_alerts_unlocked_and_low_soc():
    payload = json.loads(json.dumps(DATA))
    payload["door_status"]["vehicle_lock_status"] = 0
    payload["soc_status"]["soc"] = 15
    alerts = vehicle_data.compute_alerts(payload)
    ids = {a.id for a in alerts}
    assert "unlock" in ids
    assert "soc-low" in ids
    assert vehicle_data.problem_alert_count(alerts) == 2
    print(f"  problems={vehicle_data.problem_alert_count(alerts)} ids={ids}")


def test_full_charge_range_and_battery_pack():
    full = vehicle_data.full_charge_range_km(194.0, 38.5)
    assert full == 504
    assert vehicle_data.battery_pack(full) == "75kwh"
    print(f"  full_range={full} pack=75kwh")


def test_heat_and_charge_helpers():
    assert vehicle_data.heat_level(0) == "off"
    assert vehicle_data.heat_level(2) == "medium"
    assert vehicle_data.charge_state(1) == "charging"
    assert vehicle_data.mode_active(1) is True
    print("  heat/charge helpers ok")


if __name__ == "__main__":
    for fn in (
        test_compute_alerts_fixture_adc_offline,
        test_compute_alerts_all_clear,
        test_compute_alerts_unlocked_and_low_soc,
        test_full_charge_range_and_battery_pack,
        test_heat_and_charge_helpers,
    ):
        print(f"{fn.__name__}:")
        fn()
    print("ALL VEHICLE-DATA TESTS PASSED")
