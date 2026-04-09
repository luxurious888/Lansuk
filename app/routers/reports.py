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


# ════════════════════════════════════════════════════════════════
#  RICH SALES REPORT — รายงานปิดร้านแบบจัดเต็ม
# ════════════════════════════════════════════════════════════════

@router.get("/sales/full")
async def sales_full_wrapper(
    date_from: date,
    date_to:   date,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await _sales_full_impl(date_from, date_to, db)
    except Exception as e:
        import traceback
        return {
            "error": str(e),
            "type": type(e).__name__,
            "traceback": traceback.format_exc().split("\n")[-20:],
        }


async def _sales_full_impl(
    date_from: date,
    date_to:   date,
    db: AsyncSession = Depends(get_db),
):
    """รายงานยอดขายแบบครบทุกมุม สำหรับหน้าปิดร้าน"""
    from sqlalchemy import select, func
    from sqlalchemy.orm import selectinload
    from app.models import (
        Order, OrderItem, MenuItem, TableSession,
        OrderStatus, PaymentMethod,
    )

    # ── ดึง orders ทั้งหมดในช่วง พร้อม items ─────────────────
    res = await db.execute(
        select(Order)
        .where(Order.paid_at.isnot(None))
        .where(func.date(Order.paid_at) >= date_from)
        .where(func.date(Order.paid_at) <= date_to)
        .options(
            selectinload(Order.items),
            selectinload(Order.session),
        )
    )
    orders = res.scalars().all()

    # ── Summary ─────────────────────────────────────────────
    gross_revenue   = 0.0
    total_discount  = 0.0
    vat             = 0.0
    net_revenue     = 0.0
    guest_count     = 0
    cancelled_count = 0
    cancelled_value = 0.0

    by_payment = {}
    by_hour    = {}
    item_stats = {}      # menu_item_id -> {qty, revenue}

    for o in orders:
        # ยอดก่อนส่วนลด = sum(line_total เต็ม โดยไม่หัก cancelled)
        gross = 0.0
        for i in (o.items or []):
            qty  = int(i.quantity or 0)
            cqty = int(i.cancelled_qty or 0)
            eff  = qty - cqty
            price = float(i.unit_price or 0)
            gross += price * qty   # ก่อนหัก
            if cqty > 0:
                cancelled_count += cqty
                cancelled_value += price * cqty

            # top items: นับเฉพาะที่ไม่ถูกยกเลิก
            if eff > 0:
                k = i.menu_item_id
                s = item_stats.setdefault(k, {"qty": 0, "revenue": 0.0})
                s["qty"]     += eff
                s["revenue"] += price * eff

        gross_revenue  += gross
        total_discount += float(o.discount_amt or 0)
        vat            += float(o.vat_amt or 0)
        net_revenue    += float(o.total or 0)

        if o.session and o.session.guest_count:
            guest_count += o.session.guest_count

        # by payment method
        pm = (o.payment_method.value if o.payment_method else "other")
        bp = by_payment.setdefault(pm, {"count": 0, "total": 0.0})
        bp["count"] += 1
        bp["total"] += float(o.total or 0)

        # by hour (00-23)
        if o.paid_at:
            h = o.paid_at.hour
            bh = by_hour.setdefault(h, {"orders": 0, "revenue": 0.0})
            bh["orders"]  += 1
            bh["revenue"] += float(o.total or 0)

    order_count   = len(orders)
    avg_per_order = (net_revenue / order_count) if order_count else 0

    # ── Top items: ผูกชื่อเมนู ────────────────────────────────
    top_items = []
    sorted_items = sorted(item_stats.items(), key=lambda x: x[1]["qty"], reverse=True)[:10]
    for mid, st in sorted_items:
        m = await db.get(MenuItem, mid)
        top_items.append({
            "menu_item_id": mid,
            "name":         m.name if m else f"#{mid}",
            "qty":          st["qty"],
            "revenue":      round(st["revenue"], 2),
        })

    # ── Cancelled items detail ────────────────────────────────
    cancelled_detail = []
    cres = await db.execute(
        select(OrderItem)
        .join(Order, OrderItem.order_id == Order.id)
        .where(OrderItem.cancelled_qty > 0)
        .where(OrderItem.cancelled_at.isnot(None))
        .where(func.date(OrderItem.cancelled_at) >= date_from)
        .where(func.date(OrderItem.cancelled_at) <= date_to)
        .order_by(OrderItem.cancelled_at.desc())
    )
    citems = cres.scalars().all()
    for i in citems[:50]:   # จำกัด 50 รายการ
        m = await db.get(MenuItem, i.menu_item_id)
        cancelled_detail.append({
            "name":         m.name if m else f"#{i.menu_item_id}",
            "qty":          i.cancelled_qty,
            "value":        round(float(i.unit_price or 0) * (i.cancelled_qty or 0), 2),
            "reason":       i.cancel_reason or "",
            "by":           i.cancelled_by or "—",
            "at":           i.cancelled_at.strftime("%d/%m/%Y %H:%M") if i.cancelled_at else "",
        })

    # ── Hourly chart: เติม hour ที่ไม่มีให้ครบ 24 ชั่วโมง ────
    hourly = []
    for h in range(24):
        d = by_hour.get(h, {"orders": 0, "revenue": 0.0})
        hourly.append({"hour": h, "orders": d["orders"], "revenue": round(d["revenue"], 2)})

    return {
        "date_from": str(date_from),
        "date_to":   str(date_to),
        "summary": {
            "gross_revenue":   round(gross_revenue, 2),
            "total_discount":  round(total_discount, 2),
            "vat":             round(vat, 2),
            "net_revenue":     round(net_revenue, 2),
            "order_count":     order_count,
            "guest_count":     guest_count,
            "avg_per_order":   round(avg_per_order, 2),
            "cancelled_count": cancelled_count,
            "cancelled_value": round(cancelled_value, 2),
        },
        "by_payment": [
            {"method": k, "count": v["count"], "total": round(v["total"], 2)}
            for k, v in sorted(by_payment.items(), key=lambda x: -x[1]["total"])
        ],
        "by_hour":         hourly,
        "top_items":       top_items,
        "cancelled_items": cancelled_detail,
    }


@router.get("/sales/export.csv")
async def sales_export_csv(
    date_from: date,
    date_to:   date,
    db: AsyncSession = Depends(get_db),
):
    """Export รายงานเป็น CSV"""
    import csv, io
    from fastapi.responses import StreamingResponse

    data = await sales_full(date_from, date_to, db)
    buf = io.StringIO()
    buf.write("﻿")  # BOM สำหรับ Excel เปิดภาษาไทย
    w = csv.writer(buf)

    s = data["summary"]
    w.writerow(["รายงานยอดขาย ลานสุข"])
    w.writerow([f"ช่วงวันที่: {data['date_from']} ถึง {data['date_to']}"])
    w.writerow([])
    w.writerow(["── สรุป ──"])
    w.writerow(["ยอดก่อนส่วนลด",  s["gross_revenue"]])
    w.writerow(["ส่วนลดรวม",       s["total_discount"]])
    w.writerow(["VAT",              s["vat"]])
    w.writerow(["ยอดสุทธิ",         s["net_revenue"]])
    w.writerow(["จำนวนบิล",         s["order_count"]])
    w.writerow(["จำนวนลูกค้า",      s["guest_count"]])
    w.writerow(["เฉลี่ย/บิล",       s["avg_per_order"]])
    w.writerow(["รายการที่ยกเลิก", s["cancelled_count"]])
    w.writerow(["มูลค่าที่ยกเลิก",  s["cancelled_value"]])

    w.writerow([])
    w.writerow(["── แยกตามวิธีชำระเงิน ──"])
    w.writerow(["วิธี", "จำนวนบิล", "ยอดรวม"])
    for p in data["by_payment"]:
        w.writerow([p["method"], p["count"], p["total"]])

    w.writerow([])
    w.writerow(["── เมนูขายดี Top 10 ──"])
    w.writerow(["อันดับ", "ชื่อเมนู", "จำนวน", "ยอดรวม"])
    for i, t in enumerate(data["top_items"], 1):
        w.writerow([i, t["name"], t["qty"], t["revenue"]])

    w.writerow([])
    w.writerow(["── รายการที่ยกเลิก ──"])
    w.writerow(["เวลา", "เมนู", "จำนวน", "มูลค่า", "เหตุผล", "ผู้ยกเลิก"])
    for c in data["cancelled_items"]:
        last_reason = c["reason"].split("\n")[-1] if c["reason"] else ""
        w.writerow([c["at"], c["name"], c["qty"], c["value"], last_reason, c["by"]])

    buf.seek(0)
    fname = f"sales_{date_from}_{date_to}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


@router.get("/sales/export.pdf")
async def sales_export_pdf(
    date_from: date,
    date_to:   date,
    db: AsyncSession = Depends(get_db),
):
    """Export รายงานเป็น PDF (รองรับภาษาไทย)"""
    import io
    from fastapi.responses import StreamingResponse
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
    )
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import os

    # ลงทะเบียนฟอนต์ไทย — ลองหาในระบบ
    font_name = "Helvetica"
    for fp in [
        "fonts/Sarabun-Regular.ttf",
        "app/static/fonts/Sarabun-Regular.ttf",
        "/usr/share/fonts/truetype/tlwg/Sarabun.ttf",
        "/usr/share/fonts/truetype/thai/Sarabun-Regular.ttf",
    ]:
        if os.path.exists(fp):
            try:
                pdfmetrics.registerFont(TTFont("Sarabun", fp))
                font_name = "Sarabun"
                break
            except Exception:
                pass

    data = await sales_full(date_from, date_to, db)
    s = data["summary"]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=15*mm, bottomMargin=15*mm)
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontName=font_name, fontSize=18, alignment=1)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontName=font_name, fontSize=13, textColor=colors.HexColor("#5C3D1E"))
    body = ParagraphStyle("body", parent=styles["BodyText"], fontName=font_name, fontSize=10)

    elems = []
    elems.append(Paragraph("รายงานยอดขาย ลานสุข", h1))
    elems.append(Paragraph(f"ช่วง: {data['date_from']} ถึง {data['date_to']}", body))
    elems.append(Spacer(1, 8))

    # Summary table
    elems.append(Paragraph("สรุป", h2))
    sm = [
        ["ยอดก่อนส่วนลด", f"{s['gross_revenue']:,.2f} บาท"],
        ["ส่วนลดรวม",      f"{s['total_discount']:,.2f} บาท"],
        ["VAT",             f"{s['vat']:,.2f} บาท"],
        ["ยอดสุทธิ",        f"{s['net_revenue']:,.2f} บาท"],
        ["จำนวนบิล",        f"{s['order_count']:,}"],
        ["จำนวนลูกค้า",     f"{s['guest_count']:,}"],
        ["เฉลี่ย/บิล",      f"{s['avg_per_order']:,.2f} บาท"],
        ["รายการยกเลิก",   f"{s['cancelled_count']:,} ({s['cancelled_value']:,.2f} บาท)"],
    ]
    t = Table(sm, colWidths=[80*mm, 80*mm])
    t.setStyle(TableStyle([
        ("FONTNAME",   (0,0), (-1,-1), font_name),
        ("FONTSIZE",   (0,0), (-1,-1), 11),
        ("BACKGROUND", (0,0), (0,-1),  colors.HexColor("#F5E6C8")),
        ("GRID",       (0,0), (-1,-1), 0.5, colors.HexColor("#D0C0A8")),
        ("ALIGN",      (1,0), (1,-1),  "RIGHT"),
        ("PADDING",    (0,0), (-1,-1), 6),
    ]))
    elems.append(t)
    elems.append(Spacer(1, 12))

    # Payment methods
    if data["by_payment"]:
        elems.append(Paragraph("แยกตามวิธีชำระเงิน", h2))
        rows = [["วิธี", "บิล", "ยอดรวม"]]
        for p in data["by_payment"]:
            rows.append([p["method"], str(p["count"]), f"{p['total']:,.2f}"])
        t = Table(rows, colWidths=[60*mm, 40*mm, 60*mm])
        t.setStyle(TableStyle([
            ("FONTNAME",   (0,0), (-1,-1), font_name),
            ("FONTSIZE",   (0,0), (-1,-1), 10),
            ("BACKGROUND", (0,0), (-1,0),  colors.HexColor("#5C3D1E")),
            ("TEXTCOLOR",  (0,0), (-1,0),  colors.white),
            ("GRID",       (0,0), (-1,-1), 0.5, colors.HexColor("#D0C0A8")),
            ("ALIGN",      (1,1), (-1,-1), "RIGHT"),
            ("PADDING",    (0,0), (-1,-1), 5),
        ]))
        elems.append(t)
        elems.append(Spacer(1, 12))

    # Top items
    if data["top_items"]:
        elems.append(Paragraph("เมนูขายดี Top 10", h2))
        rows = [["#", "ชื่อเมนู", "จำนวน", "ยอดรวม"]]
        for i, ti in enumerate(data["top_items"], 1):
            rows.append([str(i), ti["name"], str(ti["qty"]), f"{ti['revenue']:,.2f}"])
        t = Table(rows, colWidths=[15*mm, 90*mm, 25*mm, 40*mm])
        t.setStyle(TableStyle([
            ("FONTNAME",   (0,0), (-1,-1), font_name),
            ("FONTSIZE",   (0,0), (-1,-1), 10),
            ("BACKGROUND", (0,0), (-1,0),  colors.HexColor("#5C3D1E")),
            ("TEXTCOLOR",  (0,0), (-1,0),  colors.white),
            ("GRID",       (0,0), (-1,-1), 0.5, colors.HexColor("#D0C0A8")),
            ("ALIGN",      (2,1), (-1,-1), "RIGHT"),
            ("PADDING",    (0,0), (-1,-1), 5),
        ]))
        elems.append(t)
        elems.append(Spacer(1, 12))

    # Cancelled items
    if data["cancelled_items"]:
        elems.append(PageBreak())
        elems.append(Paragraph("รายการที่ยกเลิก", h2))
        rows = [["เวลา", "เมนู", "จำนวน", "เหตุผล", "ผู้ยกเลิก"]]
        for c in data["cancelled_items"][:30]:
            last_reason = c["reason"].split("\n")[-1] if c["reason"] else ""
            rows.append([c["at"], c["name"], str(c["qty"]), last_reason[:40], c["by"]])
        t = Table(rows, colWidths=[28*mm, 50*mm, 18*mm, 55*mm, 25*mm])
        t.setStyle(TableStyle([
            ("FONTNAME",   (0,0), (-1,-1), font_name),
            ("FONTSIZE",   (0,0), (-1,-1), 9),
            ("BACKGROUND", (0,0), (-1,0),  colors.HexColor("#C0392B")),
            ("TEXTCOLOR",  (0,0), (-1,0),  colors.white),
            ("GRID",       (0,0), (-1,-1), 0.5, colors.HexColor("#D0C0A8")),
            ("ALIGN",      (2,1), (2,-1),  "CENTER"),
            ("PADDING",    (0,0), (-1,-1), 4),
        ]))
        elems.append(t)

    doc.build(elems)
    buf.seek(0)
    fname = f"sales_{date_from}_{date_to}.pdf"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )
