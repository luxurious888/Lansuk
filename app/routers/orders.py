"""
routers/orders.py
ลูกค้าสั่งอาหาร + KDS (Kitchen Display System)
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import (
    MenuItem, ModifierOption, Order, OrderItem,
    OrderItemModifier, OrderStatus, TableSession,
)
from app.schemas import (
    KDSItemUpdate, OrderOut, PlaceOrderRequest,
)
from app.services.qr_service import verify_qr_token

router = APIRouter()


# ── POST /api/orders ──────────────────────────────────────────────────────────
@router.post("", response_model=OrderOut)
async def place_order(
    body: PlaceOrderRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    ลูกค้าสั่งอาหาร (ผ่าน QR code):
    1. ตรวจสอบ JWT token
    2. ดึง session
    3. สร้าง Order + OrderItems + Modifiers
    4. Push ไป Firebase KDS node (kitchen/bar)
    """
    # ── ตรวจ QR token ─────────────────────────────────────────────────────────
    payload = verify_qr_token(body.session_token)
    if not payload:
        raise HTTPException(status_code=401, detail="QR หมดอายุหรือไม่ถูกต้อง")

    # ── ดึง session ───────────────────────────────────────────────────────────
    result = await db.execute(
        select(TableSession)
        .where(TableSession.qr_token == body.session_token)
        .where(TableSession.closed_at.is_(None))
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session ไม่พบหรือปิดแล้ว")

    # ── สร้าง Order ───────────────────────────────────────────────────────────
    order = Order(session_id=session.id)
    db.add(order)
    await db.flush()

    # ── สร้าง OrderItems ──────────────────────────────────────────────────────
    for item_in in body.items:
        menu_item = await db.get(MenuItem, item_in.menu_item_id)
        if not menu_item:
            raise HTTPException(status_code=404, detail=f"ไม่พบเมนู id={item_in.menu_item_id}")
        if menu_item.is_sold_out:
            raise HTTPException(status_code=400, detail=f"'{menu_item.name}' หมดแล้ว")

        order_item = OrderItem(
            order_id=order.id,
            menu_item_id=menu_item.id,
            quantity=item_in.quantity,
            unit_price=menu_item.price,
            note=item_in.note,
            kds_route=menu_item.kds_route.value,
        )
        db.add(order_item)
        await db.flush()

        # ── Modifiers ─────────────────────────────────────────────────────────
        for mod_in in item_in.modifiers:
            option = await db.get(ModifierOption, mod_in.option_id)
            if not option:
                raise HTTPException(status_code=404, detail=f"ไม่พบ modifier option id={mod_in.option_id}")
            db.add(OrderItemModifier(
                order_item_id=order_item.id,
                option_id=option.id,
                name=option.name,
                extra_price=option.extra_price,
            ))

        # ── ลด stock ถ้าเปิด track ────────────────────────────────────────────
        if menu_item.track_stock:
            menu_item.stock_qty -= item_in.quantity
            if menu_item.stock_qty <= 0:
                menu_item.is_sold_out = True

    await db.flush()

    # ── TODO: push ไป Firebase KDS ───────────────────────────────────────────
    # await kds_service.push_order(order)

    # ── โหลด relationships ก่อน return ───────────────────────────────────────
    await db.refresh(order)
    result2 = await db.execute(
        select(Order)
        .where(Order.id == order.id)
        .options(
            selectinload(Order.items)
            .selectinload(OrderItem.modifiers)
        )
    )
    return result2.scalar_one()


# ── GET /api/orders/session/{session_id} ──────────────────────────────────────
@router.get("/session/{session_id}", response_model=list[OrderOut])
async def get_session_orders(
    session_id: int,
    db: AsyncSession = Depends(get_db),
):
    """ดู orders ทั้งหมดของ session (สำหรับแสดงบิล)"""
    result = await db.execute(
        select(Order)
        .where(Order.session_id == session_id)
        .options(
            selectinload(Order.items)
            .selectinload(OrderItem.modifiers)
        )
    )
    return result.scalars().all()


# ── GET /api/orders/kds/{route} ───────────────────────────────────────────────
@router.get("/kds/{route}")
async def get_kds_orders(
    route: str,
    db: AsyncSession = Depends(get_db),
):
    """
    KDS ดึง orders ที่ยังไม่เสร็จ แยกตาม route (kitchen / bar)
    Tablet kitchen เรียก /kds/kitchen
    Tablet bar เรียก /kds/bar
    """
    result = await db.execute(
        select(OrderItem)
        .where(OrderItem.kds_route.in_([route, "both"]))
        .where(OrderItem.status.in_([
            OrderStatus.PENDING,
            OrderStatus.CONFIRMED,
            OrderStatus.PREPARING,
        ]))
        .options(selectinload(OrderItem.modifiers))
        .order_by(OrderItem.id)
    )
    items = result.scalars().all()
    return [
        {
            "order_item_id": i.id,
            "order_id":      i.order_id,
            "menu_item_id":  i.menu_item_id,
            "quantity":      i.quantity,
            "note":          i.note,
            "status":        i.status,
            "modifiers":     [{"name": m.name, "extra_price": float(m.extra_price)} for m in i.modifiers],
        }
        for i in items
    ]


# ── PATCH /api/orders/kds/update ─────────────────────────────────────────────
@router.patch("/kds/update")
async def update_kds_item(
    body: KDSItemUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    พนักงานครัว/บาร์กด Ready หรือ Served บน KDS tablet
    ถ้าทุก item ใน order READY → พิมพ์ slip ที่ pass station
    """
    item = await db.get(OrderItem, body.order_item_id)
    if not item:
        raise HTTPException(status_code=404, detail="ไม่พบรายการนี้")

    item.status = body.status
    if body.status == OrderStatus.READY:
        item.ready_at = datetime.now(timezone.utc)

    # ตรวจว่าทุก item ใน order พร้อมหมดไหม
    result = await db.execute(
        select(OrderItem)
        .where(OrderItem.order_id == item.order_id)
    )
    all_items = result.scalars().all()
    all_ready = all(i.status in [OrderStatus.READY, OrderStatus.SERVED] for i in all_items)

    if all_ready:
        # TODO: await printer_service.print_pass_slip(item.order_id)
        pass

    return {"ok": True, "all_ready": all_ready}


# ── PATCH /api/orders/{order_id}/cancel ──────────────────────────────────────
@router.patch("/{order_id}/cancel")
async def cancel_order(order_id: int, db: AsyncSession = Depends(get_db)):
    """ยกเลิก order (เฉพาะที่ยัง PENDING)"""
    order = await db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="ไม่พบ order")
    if order.status != OrderStatus.PENDING:
        raise HTTPException(status_code=400, detail="ยกเลิกได้เฉพาะ order ที่ยัง PENDING")
    order.status = OrderStatus.CANCELLED
    return {"ok": True}