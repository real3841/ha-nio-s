"""Pure helpers for NIO vehicle status (ported from foxwang/nio vehicle.ts).

Works with the flat icar API payload stored in the coordinator (sections at
top level). Also tolerates widget API nesting (``data.status``).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

DOOR_ALERT_FIELDS: tuple[tuple[str, str], ...] = (
    ("door_ajar_front_left_status", "左前车门"),
    ("door_ajar_front_right_status", "右前车门"),
    ("door_ajar_rear_left_status", "左后车门"),
    ("door_ajar_rear_right_status", "右后车门"),
    ("tailgate_ajar_status", "尾门"),
    ("engine_hood_ajar_status", "前备箱"),
    ("second_charge_port_ajar_status", "充电口"),
)

WINDOW_ALERT_FIELDS: tuple[tuple[str, str], ...] = (
    ("win_front_left_posn", "左前窗"),
    ("win_front_right_posn", "右前窗"),
    ("win_rear_left_posn", "左后窗"),
    ("win_rear_right_posn", "右后窗"),
    ("sun_roof_posn", "天窗"),
)

HEAT_LEVELS = ("off", "low", "medium", "high")
CHARGE_STATES = ("not_charging", "charging", "complete", "fault")
BATTERY_PACKS = ("75kwh", "100kwh", "unknown")


@dataclass(frozen=True)
class VehicleAlert:
    """One computed alert row."""

    id: str
    tone: str
    title: str
    detail: str


def status_root(data: dict[str, Any]) -> dict[str, Any]:
    """Return the block holding hvac_status, door_status, etc."""
    nested = data.get("status")
    if isinstance(nested, dict):
        return nested
    return data


def meta_root(data: dict[str, Any]) -> dict[str, Any]:
    """Return the block holding alarm, checked_in (widget API extras)."""
    if isinstance(data.get("status"), dict):
        return data
    return data


def heat_level(value: Any) -> str:
    level = int(value or 0)
    if level <= 0:
        return "off"
    if level == 1:
        return "low"
    if level == 2:
        return "medium"
    return "high"


def charge_state(value: Any) -> str:
    mapping = {0: "not_charging", 1: "charging", 2: "complete", 3: "fault"}
    return mapping.get(int(value if value is not None else 0), "not_charging")


def full_charge_range_km(remaining_range: Any, soc: Any) -> int | None:
    soc_f = float(soc or 0)
    range_f = float(remaining_range or 0)
    if soc_f <= 0:
        return None
    return round(range_f / soc_f * 100)


def battery_pack(full_range_km: int | None) -> str:
    if full_range_km is None:
        return "unknown"
    if full_range_km < 549:
        return "75kwh"
    if full_range_km > 550:
        return "100kwh"
    return "unknown"


def mode_active(value: Any, active_value: int = 1) -> bool:
    return int(value or 0) >= active_value


def maintenance_detail(data: dict[str, Any]) -> str | None:
    maintain = status_root(data).get("maintain_status") or {}
    if int(maintain.get("maintain_status") or 0) < 1:
        return None
    items = maintain.get("current_maintenance_list") or []
    if not items or not isinstance(items[0], dict):
        return None
    item = items[0]
    name = item.get("name") or ""
    code = item.get("code") or ""
    return f"{name}（{code}）" if code else name or None


def compute_alerts(data: dict[str, Any]) -> list[VehicleAlert]:
    """Mirror foxwang/nio ``computeAlerts()`` against coordinator data."""
    status = status_root(data)
    meta = meta_root(data)
    alerts: list[VehicleAlert] = []

    doors = status.get("door_status") or {}
    for field, label in DOOR_ALERT_FIELDS:
        if doors.get(field) not in (None, 1):
            alerts.append(
                VehicleAlert(
                    id=f"door-{label}",
                    tone="danger",
                    title=f"{label}未关闭",
                    detail="请确认车辆安全后再离开。",
                )
            )

    if doors.get("vehicle_lock_status") not in (None, 1):
        alerts.append(
            VehicleAlert(
                id="unlock",
                tone="warning",
                title="车辆未上锁",
                detail="建议远程锁车或检查钥匙距离。",
            )
        )

    soc = float((status.get("soc_status") or {}).get("soc") or 0)
    if soc < 10:
        alerts.append(
            VehicleAlert(
                id="soc-critical",
                tone="danger",
                title="电量极低",
                detail=f"剩余 {soc:g}%，请尽快充电。",
            )
        )
    elif soc < 20:
        alerts.append(
            VehicleAlert(
                id="soc-low",
                tone="warning",
                title="电量偏低",
                detail=f"剩余 {soc:g}%，建议提前规划补能。",
            )
        )

    connection = status.get("connection_status") or {}
    if connection.get("connected") is False:
        alerts.append(
            VehicleAlert(
                id="offline",
                tone="danger",
                title="车辆离线",
                detail="远程连接不可用，数据可能已过期。",
            )
        )

    if connection.get("adc_connected") is False:
        alerts.append(
            VehicleAlert(
                id="adc-offline",
                tone="info",
                title="ADC 智驾离线",
                detail="智驾域控制器未连接，不影响基础远程车况。",
            )
        )

    detail = maintenance_detail(data)
    if detail:
        alerts.append(
            VehicleAlert(
                id="maintain",
                tone="info",
                title="维保提醒",
                detail=detail,
            )
        )

    windows = status.get("window_status") or {}
    for field, label in WINDOW_ALERT_FIELDS:
        pos = windows.get(field)
        if pos not in (None, 0) and float(pos) > 0:
            alerts.append(
                VehicleAlert(
                    id=f"window-{label}",
                    tone="warning",
                    title=f"{label}未完全关闭",
                    detail=f"当前开度 {round(float(pos))}%。",
                )
            )

    offcar = status.get("offcar_mode_status") or {}
    if int(offcar.get("defender_mode") or 0) >= 2:
        alerts.append(
            VehicleAlert(
                id="defender",
                tone="info",
                title="守卫模式运行中",
                detail="车辆处于守卫监控状态。",
            )
        )

    alarm = meta.get("alarm")
    if isinstance(alarm, list) and len(alarm) > 0:
        alerts.append(
            VehicleAlert(
                id="server-alarm",
                tone="danger",
                title="服务端告警",
                detail=f"收到 {len(alarm)} 条告警，请查看 App。",
            )
        )

    if not alerts:
        checked_in = meta.get("checked_in") or {}
        days = checked_in.get("days", "—")
        alerts.append(
            VehicleAlert(
                id="all-clear",
                tone="success",
                title="状态正常",
                detail=f"已连续用车 {days} 天，无异常项。",
            )
        )

    return alerts


def alerts_as_attributes(alerts: list[VehicleAlert]) -> list[dict[str, str]]:
    return [asdict(alert) for alert in alerts]


def problem_alert_count(alerts: list[VehicleAlert]) -> int:
    return sum(1 for alert in alerts if alert.tone in ("danger", "warning"))


def has_problem_alert(data: dict[str, Any]) -> bool:
    return problem_alert_count(compute_alerts(data)) > 0
