"""routers/reports.py — Sales analytics"""
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import MenuItem, Order, OrderItem, TableSession
from app.schemas import SalesSummaryOut

router = APIRouter()


@router.get("/sales", response_model=SalesSummaryOut)
async def sales_summary(
    date_from: date,
    date_to:   date,
    db: AsyncSession = Depends(get_db),
):
    """ยอดขายรวม + รายวัน + top items ในช่วงวันที่กำหนด"""

    # ── ยอดรวม ────────────────────────────────────────────────────────────────
    total_result = await db.execute(
        select(func.count(Order.id), func.coalesce(func.sum(Order.total), 0))
        .join(TableSession, Order.session_id == TableSession.id)
        .where(Order.paid_at.isnot(None))
        .where(func.date(Order.paid_at) >= date_from)
        .where(func.date(Order.paid_at) <= date_to)
    )
    order_count, total_revenue = total_result.one()

    # ── รายวัน ────────────────────────────────────────────────────────────────
    daily_result = await db.execute(
        select(
            func.date(Order.paid_at).label("sale_date"),
            func.count(Order.id).label("order_count"),
            func.coalesce(func.sum(Order.total), 0).label("total_revenue"),
        )
        .where(Order.paid_at.isnot(None))
        .where(func.date(Order.paid_at) >= date_from)
        .where(func.date(Order.paid_at) <= date_to)
        .group_by(func.date(Order.paid_at))
        .order_by(func.date(Order.paid_at))
    )
    daily = [
        {
            "sale_date":     row.sale_date,
            "order_count":   row.order_count,
            "total_revenue": row.total_revenue,
            "avg_per_order": row.total_revenue / row.order_count if row.order_count else 0,
        }
        for row in daily_result.all()
    ]

    # ── Top 10 รายการขายดี ────────────────────────────────────────────────────
    top_result = await db.execute(
        select(
            OrderItem.menu_item_id,
            func.sum(OrderItem.quantity).label("quantity_sold"),
            func.sum(OrderItem.unit_price * OrderItem.quantity).label("total_revenue"),
        )
        .join(Order, OrderItem.order_id == Order.id)
        .where(Order.paid_at.isnot(None))
        .where(func.date(Order.paid_at) >= date_from)
        .where(func.date(Order.paid_at) <= date_to)
        .group_by(OrderItem.menu_item_id)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(10)
    )
    top_rows = top_result.all()

    # ดึงชื่อเมนู
    top_items = []
    for row in top_rows:
        item = await db.get(MenuItem, row.menu_item_id)
        top_items.append({
            "menu_item_id":  row.menu_item_id,
            "name":          item.name if item else "—",
            "quantity_sold": row.quantity_sold,
            "total_revenue": row.total_revenue,
        })

    return {
        "date_from":     date_from,
        "date_to":       date_to,
        "total_revenue": total_revenue,
        "order_count":   order_count,
        "daily":         daily,
        "top_items":     top_items,
    }


@router.get("/attendance")
async def attendance_report(
    staff_id:  int | None = None,
    date_from: date | None = None,
    date_to:   date | None = None,
    db: AsyncSession = Depends(get_db),
):
    """รายงานเข้างาน — filter ตาม staff และช่วงวันที่"""
    from app.models import AttendanceLog
    q = select(AttendanceLog)
    if staff_id:
        q = q.where(AttendanceLog.staff_id == staff_id)
    if date_from:
        q = q.where(AttendanceLog.log_date >= date_from)
    if date_to:
        q = q.where(AttendanceLog.log_date <= date_to)
    result = await db.execute(q.order_by(AttendanceLog.log_date.desc()))
    logs = result.scalars().all()
    return [
        {
            "id":            l.id,
            "staff_id":      l.staff_id,
            "log_date":      l.log_date,
            "clock_in_at":   l.clock_in_at,
            "clock_out_at":  l.clock_out_at,
            "late_minutes":  l.late_minutes,
            "status":        l.status,
            "late_fine":     float(l.late_fine_baht),
        }
        for l in logs
    ]