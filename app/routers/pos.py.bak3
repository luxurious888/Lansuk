"""
routers/pos.py
เปิด/ปิดโต๊ะ, สร้าง QR, checkout, เปลี่ยนสถานะโต๊ะ
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import DiningTable, Staff, TableSession, TableStatus
from app.schemas import (
    MessageResponse, OpenTableRequest,
    TableOut, TableSessionOut,
    CheckoutRequest, OrderOut,
)
from app.services.qr_service import create_qr_token, verify_qr_token

router = APIRouter()


# ── GET /api/pos/tables ───────────────────────────────────────────────────────
@router.get("/tables", response_model=list[TableOut])
async def list_tables(db: AsyncSession = Depends(get_db)):
    """แสดงโต๊ะทั้งหมดพร้อมสถานะ สำหรับ floor plan"""
    result = await db.execute(
        select(DiningTable).order_by(DiningTable.table_number)
    )
    return result.scalars().all()


# ── POST /api/pos/tables/open ─────────────────────────────────────────────────
@router.post("/tables/open", response_model=TableSessionOut)
async def open_table(
    body: OpenTableRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    แคชเชียร์เปิดโต๊ะ:
    1. ตรวจว่าโต๊ะว่างอยู่
    2. สร้าง JWT QR token
    3. สร้าง TableSession
    4. เปลี่ยนสถานะโต๊ะเป็น OCCUPIED
    """
    table = await db.get(DiningTable, body.table_id)
    if not table:
        raise HTTPException(status_code=404, detail="ไม่พบโต๊ะนี้")
    if table.status != TableStatus.AVAILABLE:
        raise HTTPException(status_code=400, detail=f"โต๊ะนี้ไม่ว่าง (สถานะ: {table.status})")

    # สร้าง QR token
    qr_token = create_qr_token(table_id=body.table_id)

    session = TableSession(
        table_id=body.table_id,
        opened_by=1,            # TODO: ดึงจาก auth token จริง
        qr_token=qr_token,
        guest_count=body.guest_count,
    )
    db.add(session)

    table.status = TableStatus.OCCUPIED
    await db.flush()

    return session


# ── GET /api/pos/tables/{table_id}/session ────────────────────────────────────
@router.get("/tables/{table_id}/session", response_model=TableSessionOut)
async def get_active_session(table_id: int, db: AsyncSession = Depends(get_db)):
    """ดู session ที่ active อยู่ของโต๊ะ (ถ้ามีหลาย session คืนตัวแรกสุด)"""
    result = await db.execute(
        select(TableSession)
        .where(TableSession.table_id == table_id)
        .where(TableSession.closed_at.is_(None))
        .order_by(TableSession.opened_at.asc())
    )
    session = result.scalars().first()
    if not session:
        raise HTTPException(status_code=404, detail="โต๊ะนี้ยังไม่เปิด")
    return session



# ── POST /api/pos/checkout ────────────────────────────────────────────────────
@router.post("/checkout", response_model=MessageResponse)
async def checkout(
    body: CheckoutRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    ปิดโต๊ะ:
    1. คำนวณยอดรวม
    2. mark session is_paid + closed_at
    3. เปลี่ยนสถานะโต๊ะเป็น CLEANING
    4. TODO: สั่งพิมพ์ใบเสร็จผ่าน printer_service
    """
    result = await db.execute(
        select(TableSession)
        .where(TableSession.id == body.session_id)
        .where(TableSession.closed_at.is_(None))
        .options(selectinload(TableSession.orders))
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="ไม่พบ session หรือปิดไปแล้ว")

    # คำนวณยอดทุก order ใน session
    for order in session.orders:
        order.payment_method = body.payment_method
        order.paid_at        = datetime.now(timezone.utc)
        order.calculate_totals()

    session.closed_at = datetime.now(timezone.utc)
    session.is_paid   = True

    table = await db.get(DiningTable, session.table_id)
    if table:
        table.status = TableStatus.CLEANING

    # TODO: await printer_service.print_receipt(session)

    return {"message": f"ปิดโต๊ะสำเร็จ — session #{body.session_id}"}


# ── PATCH /api/pos/tables/{table_id}/status ───────────────────────────────────
@router.patch("/tables/{table_id}/status", response_model=TableOut)
async def update_table_status(
    table_id: int,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """เปลี่ยนสถานะโต๊ะ (เช่น CLEANING → AVAILABLE หลังเก็บโต๊ะเสร็จ)"""
    table = await db.get(DiningTable, table_id)
    if not table:
        raise HTTPException(status_code=404, detail="ไม่พบโต๊ะนี้")
    table.status = TableStatus(body["status"])
    return table


# ── GET /api/pos/qr/verify ────────────────────────────────────────────────────
@router.get("/qr/verify")
async def verify_qr(token: str, db: AsyncSession = Depends(get_db)):
    """
    ลูกค้าสแกน QR → frontend เรียก endpoint นี้เพื่อตรวจ token
    คืน session_id และ table_number ถ้า valid
    """
    payload = verify_qr_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="QR หมดอายุหรือไม่ถูกต้อง")

    result = await db.execute(
        select(TableSession)
        .where(TableSession.qr_token == token)
        .where(TableSession.closed_at.is_(None))
        .options(selectinload(TableSession.table))
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session ไม่พบหรือปิดแล้ว")

    return {
        "session_id":   session.id,
        "table_number": session.table.table_number,
        "guest_count":  session.guest_count,
    }

# ── POST /api/pos/tables ─────────────────────────────────────────────────────
@router.post("/tables", status_code=201)
async def create_table(body: dict, db: AsyncSession = Depends(get_db)):
    """เพิ่มโต๊ะใหม่"""
    from app.models import DiningTable, TableStatus
    table = DiningTable(
        table_number=body["table_number"],
        col=body.get("col", 1),
        row=body.get("row", 1),
        capacity=body.get("capacity", 4),
        status=TableStatus.AVAILABLE,
    )
    db.add(table)
    await db.flush()
    return {"id": table.id, "table_number": table.table_number, "message": f"เพิ่มโต๊ะ {table.table_number} สำเร็จ"}


@router.delete("/tables/{table_id}")
async def delete_table(table_id: int, db: AsyncSession = Depends(get_db)):
    """ลบโต๊ะ"""
    table = await db.get(DiningTable, table_id)
    if not table:
        raise HTTPException(status_code=404, detail="ไม่พบโต๊ะ")
    await db.delete(table)
    return {"message": f"ลบโต๊ะสำเร็จ"}


@router.patch("/tables/{table_id}/number")
async def update_table_number(table_id: int, body: dict, db: AsyncSession = Depends(get_db)):
    """เปลี่ยนเลขโต๊ะ"""
    table = await db.get(DiningTable, table_id)
    if not table:
        raise HTTPException(status_code=404, detail="ไม่พบโต๊ะ")
    table.table_number = body["table_number"]
    return {"message": f"เปลี่ยนเลขโต๊ะเป็น {table.table_number} สำเร็จ"}


@router.patch("/sessions/{session_id}/customer")
async def set_customer_name(session_id: int, body: dict, db: AsyncSession = Depends(get_db)):
    """ตั้งชื่อลูกค้าให้ session"""
    session = await db.get(TableSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="ไม่พบ session")
    session.customer_name = body["customer_name"]
    return {"message": f"ตั้งชื่อลูกค้า '{body['customer_name']}' สำเร็จ"}


@router.get("/bills")
async def list_bills(
    paid: bool | None = None,
    date_str: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.models import Order, OrderItem
    from app.models import OrderItemModifier
    q = (
        select(TableSession)
        .options(
            selectinload(TableSession.orders)
            .selectinload(Order.items)
            .selectinload(OrderItem.modifiers)
        )
        .order_by(TableSession.opened_at.desc())
    )
    if paid is not None:
        q = q.where(TableSession.is_paid == paid)
    result = await db.execute(q)
    sessions = result.scalars().all()
    bills = []
    for s in sessions:
        total = sum(
            float(i.unit_price or 0) * int(i.quantity or 1)
            for o in s.orders
            for i in o.items
        )
        items_count = sum(len(o.items) for o in s.orders)
        # ข้าม merged sessions ที่ถูกโอน orders ออกหมดแล้ว
        if items_count == 0 and s.is_paid:
            continue
        bills.append({
            "session_id":    s.id,
            "table_id":      s.table_id,
            "customer_name": s.customer_name or f"โต๊ะ {s.table_id}",
            "opened_at":     s.opened_at.strftime("%d/%m/%Y %H:%M") if s.opened_at else "—",
            "closed_at":     s.closed_at.strftime("%d/%m/%Y %H:%M") if s.closed_at else None,
            "is_paid":       s.is_paid,
            "total":         total,
            "items_count":   items_count,
        })
    return bills


@router.post("/checkout/discount")
async def checkout_with_discount(body: dict, db: AsyncSession = Depends(get_db)):
    """ชำระเงินพร้อมส่วนลด"""
    from datetime import datetime, timezone
    from decimal import Decimal
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.models import Order, OrderItem, OrderStatus, PaymentMethod, TableStatus

    session_id = body["session_id"]
    result = await db.execute(
        select(TableSession)
        .where(TableSession.id == session_id)
        .where(TableSession.closed_at.is_(None))
        .options(
            selectinload(TableSession.orders)
            .selectinload(Order.items)
            .selectinload(OrderItem.modifiers)
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="ไม่พบ session")

    food_discount_pct  = Decimal(str(body.get("food_discount_pct", 0)))
    total_discount_pct = Decimal(str(body.get("total_discount_pct", 0)))
    fixed_discount     = Decimal(str(body.get("fixed_discount", 0)))

    for order in session.orders:
        if order.status == OrderStatus.CANCELLED:
            continue
        subtotal = Decimal(str(sum(float(i.line_total) for i in order.items)))
        food_disc = subtotal * food_discount_pct / 100
        total_disc = (subtotal - food_disc) * total_discount_pct / 100
        all_disc = food_disc + total_disc + fixed_discount

        order.subtotal       = subtotal
        order.discount_amt   = all_disc
        order.vat_amt        = (subtotal - all_disc) * Decimal("0.07")
        order.total          = subtotal - all_disc + order.vat_amt
        order.payment_method = PaymentMethod(body.get("payment_method", "cash"))
        order.paid_at        = datetime.now(timezone.utc)

    session.closed_at = datetime.now(timezone.utc)
    session.is_paid   = True

    # ถ้าโต๊ะไม่มี session อื่นที่ active → เปลี่ยนเป็น CLEANING
    others = await db.execute(
        select(TableSession)
        .where(TableSession.table_id == session.table_id)
        .where(TableSession.closed_at.is_(None))
        .where(TableSession.id != session.id)
    )
    if not others.scalars().first():
        table = await db.get(DiningTable, session.table_id)
        if table:
            table.status = TableStatus.CLEANING

    return {"message": "ชำระเงินสำเร็จ", "session_id": session_id}



# ── POST /api/pos/tables/move ─────────────────────────────────────────────────
@router.post("/tables/move")
async def move_table(body: dict, db: AsyncSession = Depends(get_db)):
    """ย้ายโต๊ะ — โอน session + orders จากโต๊ะเก่าไปโต๊ะใหม่"""
    from app.models import TableStatus
    from sqlalchemy import select

    from_id = body["from_table_id"]
    to_id   = body["to_table_id"]

    from_table = await db.get(DiningTable, from_id)
    if not from_table:
        raise HTTPException(status_code=404, detail="ไม่พบโต๊ะต้นทาง")

    to_table = await db.get(DiningTable, to_id)
    if not to_table:
        raise HTTPException(status_code=404, detail="ไม่พบโต๊ะปลายทาง")
    if to_table.status != TableStatus.AVAILABLE:
        raise HTTPException(status_code=400, detail=f"โต๊ะปลายทางไม่ว่าง (สถานะ: {to_table.status})")

    result = await db.execute(
        select(TableSession)
        .where(TableSession.table_id == from_id)
        .where(TableSession.closed_at.is_(None))
        .order_by(TableSession.opened_at.asc())
    )
    active_sessions = result.scalars().all()

    if not active_sessions:
        raise HTTPException(status_code=404, detail="ไม่พบ session ที่เปิดอยู่ของโต๊ะนี้")
    if len(active_sessions) > 1:
        raise HTTPException(
            status_code=400,
            detail=f"โต๊ะนี้มี {len(active_sessions)} บิลที่ยังไม่ปิด กรุณารวมบิลหรือชำระให้เหลือบิลเดียวก่อนย้าย"
        )

    session = active_sessions[0]
    session.table_id = to_id
    from_table.status = TableStatus.AVAILABLE
    to_table.status   = TableStatus.OCCUPIED

    return {
        "message": f"ย้ายจากโต๊ะ {from_table.table_number} → โต๊ะ {to_table.table_number} สำเร็จ",
        "session_id":        session.id,
        "from_table_number": from_table.table_number,
        "to_table_number":   to_table.table_number,
    }



# ── POST /api/pos/bills/merge ─────────────────────────────────────────────────
@router.post("/bills/merge")
async def merge_bills(body: dict, db: AsyncSession = Depends(get_db)):
    """รวมบิลหลายบิลเข้าด้วยกัน — ย้าย orders ไป main session แล้วปิดบิลอื่น"""
    from datetime import datetime, timezone
    from sqlalchemy import select
    from app.models import Order, TableStatus

    session_ids = body["session_ids"]
    main_id     = body["main_session_id"]

    if main_id not in session_ids:
        raise HTTPException(status_code=400, detail="main_session_id ต้องอยู่ใน session_ids")

    main_session = await db.get(TableSession, main_id)
    if not main_session:
        raise HTTPException(status_code=404, detail="ไม่พบ main session")

    for sid in session_ids:
        if sid == main_id:
            continue

        await db.execute(
            Order.__table__.update()
            .where(Order.session_id == sid)
            .values(session_id=main_id)
        )

        s = await db.get(TableSession, sid)
        if s:
            s.closed_at = datetime.now(timezone.utc)
            s.is_paid   = True
            s.customer_name = (s.customer_name or "") + f" → รวม #{main_id}"

            if s.table_id != main_session.table_id:
                others = await db.execute(
                    select(TableSession)
                    .where(TableSession.table_id == s.table_id)
                    .where(TableSession.closed_at.is_(None))
                    .where(TableSession.id != sid)
                )
                if not others.scalars().first():
                    t = await db.get(DiningTable, s.table_id)
                    if t:
                        t.status = TableStatus.CLEANING

    return {"message": f"รวม {len(session_ids)} บิลเข้าด้วยกันสำเร็จ", "main_session_id": main_id}



# ── POST /api/pos/bills/split ─────────────────────────────────────────────────
@router.post("/bills/split")
async def split_bill(body: dict, db: AsyncSession = Depends(get_db)):
    """
    แยกบิล — แยก order_item_ids บางส่วนออกเป็น session ใหม่
    body: { session_id, order_item_ids: [1,2,3] }
    """
    from decimal import Decimal
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.models import Order, OrderItem, OrderStatus
    from app.services.qr_service import create_qr_token

    session_id     = body.get("session_id")
    split_item_ids = body.get("order_item_ids") or []

    if not split_item_ids:
        raise HTTPException(status_code=400, detail="กรุณาเลือกรายการที่ต้องการแยก")

    session = await db.get(TableSession, session_id)
    if not session or session.closed_at:
        raise HTTPException(status_code=404, detail="ไม่พบ session หรือปิดแล้ว")

    # 🔑 โหลด items พร้อม modifiers — กัน MissingGreenlet จาก lazy load
    result = await db.execute(
        select(OrderItem)
        .where(OrderItem.id.in_(split_item_ids))
        .options(selectinload(OrderItem.modifiers))
    )
    items = result.scalars().all()
    if not items:
        raise HTTPException(status_code=404, detail="ไม่พบรายการที่ต้องการแยก")

    # ตรวจว่าทุก item อยู่ใน session นี้จริง ๆ
    old_order_ids = {i.order_id for i in items}
    orders_res = await db.execute(
        select(Order).where(Order.id.in_(old_order_ids))
    )
    old_orders = {o.id: o for o in orders_res.scalars().all()}
    for item in items:
        parent = old_orders.get(item.order_id)
        if not parent or parent.session_id != session_id:
            raise HTTPException(status_code=400, detail="มีรายการที่ไม่ได้อยู่ใน session นี้")

    # สร้าง session ใหม่ (ใช้โต๊ะเดิม)
    new_token = create_qr_token(table_id=session.table_id)
    new_session = TableSession(
        table_id      = session.table_id,
        opened_by     = session.opened_by,
        qr_token      = new_token,
        guest_count   = 1,
        customer_name = f"แยกจาก #{session_id}",
    )
    db.add(new_session)
    await db.flush()

    # สร้าง order ใหม่ใน session ใหม่
    new_order = Order(
        session_id = new_session.id,
        status     = OrderStatus.CONFIRMED,
    )
    db.add(new_order)
    await db.flush()

    # โอน items ไป order ใหม่ (ตอนนี้ modifiers โหลดมาแล้ว ปลอดภัย)
    total = Decimal("0")
    for item in items:
        item.order_id = new_order.id
        total += Decimal(str(item.line_total))

    new_order.subtotal = total
    new_order.total    = total

    return {
        "message":        "แยกบิลสำเร็จ",
        "new_session_id": new_session.id,
        "new_qr_token":   new_token,
        "items_moved":    len(items),
        "split_total":    float(total),
    }


@router.get("/fix-db")
async def fix_db():
    """Fix missing columns directly"""
    import aiosqlite, os
    db_path = "lansook.db"
    results = []
    sqls = [
        "ALTER TABLE table_sessions ADD COLUMN customer_name TEXT",
        "ALTER TABLE orders ADD COLUMN discount_amt REAL DEFAULT 0",
        "ALTER TABLE orders ADD COLUMN vat_amt REAL DEFAULT 0",
        "ALTER TABLE orders ADD COLUMN subtotal REAL DEFAULT 0",
        "ALTER TABLE orders ADD COLUMN payment_method TEXT DEFAULT 'cash'",
        "ALTER TABLE orders ADD COLUMN paid_at DATETIME",
    ]
    async with aiosqlite.connect(db_path) as db:
        for sql in sqls:
            try:
                await db.execute(sql)
                await db.commit()
                results.append("OK: " + sql[:50])
            except Exception as e:
                results.append("SKIP: " + str(e)[:50])
    return {"results": results}
