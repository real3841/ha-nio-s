"""Pure helpers for NIO service-order / battery-swap payloads.

Ported from foxwang/nio ``src/lib/change.ts`` — kept import-light for tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ServiceSummary:
    """Aggregated stats from a service-order API response."""

    total: int
    swap_completed: int
    swap_cancelled: int
    swap_spent: float
    swap_avg_spent: float
    upgrade_completed: int
    upgrade_spent: float
    last_order_time: int | None


def _parse_payment_info(order: dict[str, Any]) -> list[dict[str, Any]]:
    extend = order.get("extendInfo") or {}
    raw = extend.get("paymentInfo") if isinstance(extend, dict) else None
    if not isinstance(raw, list):
        return []
    return [p for p in raw if isinstance(p, dict) and "amount" in p]


def order_spent_amount(order: dict[str, Any]) -> float:
    cash = float(order.get("priceCash") or 0)
    if cash > 0:
        return cash
    return sum(float(p.get("amount") or 0) for p in _parse_payment_info(order))


def _is_completed_order(order: dict[str, Any]) -> bool:
    name = str(order.get("orderStatusName") or "")
    code = str(order.get("orderStatus") or "")
    return (
        code in ("100", "1000")
        or "完成" in name
        or "已支付" in name
    )


def _is_cancelled_order(order: dict[str, Any]) -> bool:
    name = str(order.get("orderStatusName") or "")
    code = str(order.get("orderStatus") or "")
    return code in ("255", "900") or "取消" in name


def extract_orders(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull the order list from getTabOrder payloads (camelCase or snake_case)."""
    for result_key in ("resultData", "result_data"):
        result_data = payload.get(result_key)
        if not isinstance(result_data, dict):
            continue
        for list_key in ("data", "list", "orders"):
            orders = result_data.get(list_key)
            if isinstance(orders, list):
                return [o for o in orders if isinstance(o, dict)]
    return []


def analyze_service_orders(payload: dict[str, Any]) -> ServiceSummary:
    """Summarise orders from a getTabOrder API ``data`` payload."""
    sorted_orders = sorted(
        extract_orders(payload),
        key=lambda o: int(o.get("createTime") or 0),
        reverse=True,
    )

    swap_orders = [o for o in sorted_orders if o.get("orderType") == "pe_shaman_change"]
    swap_completed = [o for o in swap_orders if _is_completed_order(o)]
    swap_cancelled = [o for o in swap_orders if _is_cancelled_order(o)]
    swap_spent = sum(float(o.get("priceCash") or 0) for o in swap_completed)

    upgrade_orders = [
        o for o in sorted_orders if o.get("orderType") == "battery_flexible_upgrade"
    ]
    upgrade_completed = [o for o in upgrade_orders if _is_completed_order(o)]
    upgrade_spent = sum(order_spent_amount(o) for o in upgrade_completed)

    return ServiceSummary(
        total=len(sorted_orders),
        swap_completed=len(swap_completed),
        swap_cancelled=len(swap_cancelled),
        swap_spent=round(swap_spent, 2),
        swap_avg_spent=round(swap_spent / len(swap_completed), 2) if swap_completed else 0.0,
        upgrade_completed=len(upgrade_completed),
        upgrade_spent=round(upgrade_spent, 2),
        last_order_time=int(sorted_orders[0]["createTime"])
        if sorted_orders and sorted_orders[0].get("createTime") is not None
        else None,
    )
