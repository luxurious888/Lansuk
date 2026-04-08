import logging
import os
from datetime import date, datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Staff, StaffStatus

logger = logging.getLogger(__name__)
BOT_API = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}"
GROUP_CHAT_ID = -5111246315

KEYBOARDS = {
    "staff": {
        "keyboard": [
            ["📸 เช็คอิน", "📍 โซนของฉัน"],
            ["💰 รายได้ของฉัน", "🚪 เช็คเอาท์"],
            ["📊 สรุปการเข้างาน", "🕐 ตารางกะวันนี้"],
        ],
        "resize_keyboard": True,
    },
    "admin": {
        "keyboard": [
            ["📊 ยอดขายวันนี้", "👥 พนักงานทั้งหมด"],
            ["🗺️ แผนผังโต๊ะ", "❌ มาร์คหมด"],
            ["🔓 เปิดโต๊ะ", "🔒 ปิดโต๊ะ"],
        ],
        "resize_keyboard": True,
    },
}

GROUP_INLINE_MENU = {
    "inline_keyboard": [
        [
            {"text": "📊 ยอดขายวันนี้", "callback_data": "group:summary"},
            {"text": "🗺️ แผนผังโต๊ะ",  "callback_data": "group:floorplan"},
        ],
        [
            {"text": "👥 พนักงาน",      "callback_data": "group:stafflist"},
            {"text": "❌ เมนูหมด",      "callback_data": "group:soldout_list"},
        ],
        [
            {"text": "🔓 เปิดโต๊ะ",     "callback_data": "group:opentable"},
            {"text": "🔒 ปิดโต๊ะ",      "callback_data": "group:closetable"},
        ],
        [
            {"text": "📋 ออเดอร์",      "callback_data": "group:orders"},
            {"text": "💰 สรุปรายได้",   "callback_data": "group:revenue"},
        ],
    ]
}


async def dispatch_update(update: dict, db):
    if cq := update.get("callback_query"):
        user_id  = cq["from"]["id"]
        msg_chat = cq.get("message", {}).get("chat", {}).get("id", user_id)
        staff    = await _get_staff(user_id, db)
        await _handle_callback(cq, staff, msg_chat, db)
        return

    msg = update.get("message")
    if not msg:
        return

    chat_type = msg["chat"].get("type", "private")
    user_id   = msg["from"]["id"]
    chat_id   = msg["chat"]["id"]
    text      = msg.get("text", "").strip().split("@")[0]

    if chat_type in ["group", "supergroup"]:
        if text in ["/เมนู", "/menu", "/start"]:
            await _send_group_menu(chat_id)
        elif "/สมัคร" in text or "/apply" in text:
            await _send(user_id, "📝 กรุณาสมัครงานผ่าน DM กับ bot โดยตรงนะครับ")
        elif text.startswith("/อนุมัติ_") or text.startswith("/approve_"):
            tid = int(text.split("_")[1])
            t   = await db.get(Staff, tid)
            if t:
                t.status = StaffStatus.ACTIVE
                await _send(chat_id, f"✅ อนุมัติ {t.full_name} ({t.nickname}) เข้าทีมแล้ว")
                if t.telegram_chat_id:
                    await _send(t.telegram_chat_id, "🎉 ได้รับการอนุมัติแล้ว! ยินดีต้อนรับสู่ทีมลานสุขครับ", reply_markup=KEYBOARDS["staff"])
            else:
                await _send(chat_id, f"ไม่พบพนักงาน id={tid}")
        elif text.startswith("/ปฏิเสธ_") or text.startswith("/reject_"):
            tid = int(text.split("_")[1])
            t   = await db.get(Staff, tid)
            if t:
                t.status = StaffStatus.INACTIVE
                await _send(chat_id, f"❌ ปฏิเสธ {t.full_name} แล้ว")
        elif text.startswith("/หมด "):
            await _cmd_soldout(text, chat_id, db)
        elif text.startswith("/เปิดโต๊ะ"):
            await _cmd_open_table(text, chat_id, db)
        elif text.startswith("/ปิดโต๊ะ"):
            await _cmd_close_table(text, chat_id, db)
        elif text in ["/ยอดขาย", "/summary"]:
            await _cmd_summary(chat_id, db)
        elif text in ["/พนักงาน", "/staff"]:
            await _cmd_staff_list(chat_id, db)
        elif text.startswith("/ระงับ_"):
            await _cmd_deactivate(text, chat_id, db)
        return

    # DM
    staff = await _get_staff(user_id, db)

    if not staff:
        if text in ["/สมัคร", "/apply", "/start"]:
            await _start_apply(user_id, db)
        else:
            await _send(user_id, "สวัสดีครับ 👋 พิมพ์ /สมัคร เพื่อสมัครงานลานสุขครับ")
        return

    if staff.status == StaffStatus.INACTIVE:
        await _send(user_id, "❌ บัญชีของคุณถูกระงับ กรุณาติดต่อผู้จัดการ")
        return

    state = staff.bot_state or ""
    if state.startswith("apply:"):
        await _handle_apply_step(msg, staff, state, db)
    elif state.startswith("clockin:"):
        await _handle_clockin_step(msg, staff, state, db)
    elif state.startswith("clockout:"):
        await _handle_clockout_step(msg, staff, state, db)
    else:
        await _handle_menu(msg, staff, db)


async def _send_group_menu(chat_id: int):
    try:
        async with httpx.AsyncClient() as client:
            await client.post(f"{BOT_API}/sendMessage", json={
                "chat_id":      chat_id,
                "text":         "🌿 ลานสุข — ระบบจัดการ\n\nเลือกเมนูที่ต้องการ:",
                "reply_markup": GROUP_INLINE_MENU,
            }, timeout=10)
    except Exception as e:
        logger.error(f"send group menu error: {e}")


async def _start_apply(chat_id: int, db):
    existing = await _get_staff(chat_id, db)
    if existing:
        await _send(chat_id, "คุณมีบัญชีอยู่แล้วครับ")
        return
    staff = Staff(
        full_name="", nickname="", phone="",
        telegram_chat_id=chat_id,
        status=StaffStatus.PENDING,
        bot_state="apply:name",
        wage_rate=0,
    )
    db.add(staff)
    await db.flush()
    await _send(chat_id, "📝 สมัครงานลานสุข\n\nกรอกชื่อ-นามสกุลจริงของคุณ:")


async def _handle_apply_step(msg: dict, staff, state: str, db):
    text    = msg.get("text", "").strip()
    chat_id = msg["from"]["id"]
    if state == "apply:name":
        staff.full_name = text
        staff.bot_state = "apply:nickname"
        await _send(chat_id, "ชื่อเล่น:")
    elif state == "apply:nickname":
        staff.nickname  = text
        staff.bot_state = "apply:phone"
        await _send(chat_id, "เบอร์โทรศัพท์:")
    elif state == "apply:phone":
        staff.phone     = text
        staff.bot_state = "apply:address"
        await _send(chat_id, "ที่อยู่ (สำหรับติดต่อ):")
    elif state == "apply:address":
        staff.address   = text
        staff.bot_state = "apply:role"
        await _send(chat_id, "ตำแหน่งที่สมัคร:\n1. พนักงานเสิร์ฟ\n2. ครัว\n3. บาร์\n4. แคชเชียร์")
    elif state == "apply:role":
        from app.models import StaffRole
        role_map = {"1": "waiter", "2": "kitchen", "3": "bar", "4": "cashier"}
        staff.role      = StaffRole(role_map.get(text, "waiter"))
        staff.bot_state = "apply:id_card"
        await _send(chat_id, "📸 ส่งรูปถ่ายบัตรประชาชนของคุณ:")
    elif state == "apply:id_card":
        if "photo" not in msg:
            await _send(chat_id, "กรุณาส่งรูปถ่ายบัตรประชาชนครับ")
            return
        path = await _download_photo(msg, staff.id, "id_card")
        staff.id_card_path = path
        staff.status       = StaffStatus.REVIEWING
        staff.bot_state    = None
        await _send(chat_id, "✅ ส่งใบสมัครเสร็จแล้ว! รอ admin อนุมัติครับ")
        summary = (
            f"📋 ใบสมัครใหม่\n"
            f"👤 {staff.full_name} ({staff.nickname})\n"
            f"📱 {staff.phone}\n"
            f"🏠 {staff.address}\n"
            f"💼 {staff.role}\n\n"
            f"✅ อนุมัติ: /อนุมัติ_{staff.id}\n"
            f"❌ ปฏิเสธ: /ปฏิเสธ_{staff.id}"
        )
        await _send(GROUP_CHAT_ID, summary)
        await _send(settings.ADMIN_CHAT_ID, summary)


async def _handle_clockin_step(msg: dict, staff, state: str, db):
    chat_id = msg["from"]["id"]
    if state == "clockin:selfie":
        if "photo" not in msg:
            await _send(chat_id, "กรุณาส่งรูป selfie ครับ")
            return
        path = await _download_photo(msg, staff.id, "selfie_in")
        staff.bot_state = f"clockin:gps|{path}"
        await _send(chat_id, "📍 ส่ง Location เพื่อยืนยันตำแหน่งครับ")
    elif state.startswith("clockin:gps"):
        selfie_path = state.split("|")[1] if "|" in state else ""
        if "location" not in msg:
            await _send(chat_id, "กรุณาส่ง Location ครับ")
            return
        lat = msg["location"]["latitude"]
        lon = msg["location"]["longitude"]
        from app.services.attendance_service import process_clock_in
        log = await process_clock_in(staff, lat, lon, selfie_path, db)
        staff.bot_state = None
        emoji    = "✅" if log.gps_valid_in else "⚠️"
        late_msg = f"\n⏰ สาย {log.late_minutes} นาที" if log.late_minutes > 0 else ""
        fine_msg = f"\n💸 ค่าปรับ ฿{float(log.late_fine_baht):.0f}" if float(log.late_fine_baht) > 0 else ""
        await _send(chat_id, f"{emoji} เช็คอินบันทึกแล้ว\n🕐 {log.clock_in_at.strftime('%H:%M')}{late_msg}{fine_msg}",
                    reply_markup=KEYBOARDS["admin" if staff.is_admin else "staff"])


async def _handle_clockout_step(msg: dict, staff, state: str, db):
    chat_id = msg["from"]["id"]
    if "photo" not in msg:
        await _send(chat_id, "กรุณาส่งรูป selfie ก่อนเช็คเอาท์ครับ")
        return
    path = await _download_photo(msg, staff.id, "selfie_out")
    from app.services.attendance_service import process_clock_out
    log, ot_req = await process_clock_out(staff, path, db)
    staff.bot_state = None
    msg_text = f"✅ เช็คเอาท์บันทึกแล้ว\n🕐 {log.clock_out_at.strftime('%H:%M')}"
    if ot_req:
        msg_text += f"\n⏰ OT {ot_req.ot_minutes} นาที (฿{float(ot_req.ot_amount):.0f}) — รอ admin อนุมัติ"
    await _send(chat_id, msg_text, reply_markup=KEYBOARDS["admin" if staff.is_admin else "staff"])


async def _cmd_soldout(text: str, chat_id: int, db):
    from app.models import MenuItem
    from sqlalchemy import select as sa_select
    parts = text.split(" ", 1)
    if len(parts) < 2:
        await _send(chat_id, "รูปแบบ: /หมด [ชื่อเมนู]\nเช่น /หมด ข้าวผัด")
        return
    name   = parts[1].strip()
    result = await db.execute(sa_select(MenuItem).where(MenuItem.name.contains(name)).where(MenuItem.deleted_at.is_(None)))
    items  = result.scalars().all()
    if not items:
        await _send(chat_id, f"❌ ไม่พบเมนู '{name}'")
        return
    for item in items:
        item.is_sold_out = not item.is_sold_out
    await db.flush()
    lines = ["อัปเดตแล้ว:"]
    for i in items:
        lines.append(f"{'❌' if i.is_sold_out else '✅'} {i.name} — {'หมด' if i.is_sold_out else 'มีแล้ว'}")
    await _send(chat_id, "\n".join(lines))


async def _cmd_open_table(text: str, chat_id: int, db):
    from app.models import DiningTable, TableSession, TableStatus
    from app.services.qr_service import create_qr_token
    from sqlalchemy import select as sa_select
    parts = text.split()
    if len(parts) < 2:
        await _send(chat_id, "รูปแบบ: /เปิดโต๊ะ [เลขโต๊ะ]\nเช่น /เปิดโต๊ะ 5")
        return
    try:
        table_num = int(parts[1])
    except:
        await _send(chat_id, "กรุณาระบุเลขโต๊ะ")
        return
    result = await db.execute(sa_select(DiningTable).where(DiningTable.table_number == table_num))
    table  = result.scalar_one_or_none()
    if not table:
        await _send(chat_id, f"❌ ไม่พบโต๊ะ {table_num}")
        return
    if table.status != TableStatus.AVAILABLE:
        await _send(chat_id, f"❌ โต๊ะ {table_num} ไม่ว่าง")
        return
    qr_token = create_qr_token(table_id=table.id)
    session  = TableSession(table_id=table.id, opened_by=1, qr_token=qr_token, guest_count=2)
    db.add(session)
    table.status = TableStatus.OCCUPIED
    await db.flush()
    await _send(chat_id, f"✅ เปิดโต๊ะ {table_num} แล้ว\n\nลิงค์สั่งอาหาร:\nhttps://psychic-space-bassoon-749p44vpvwgcpv7r-8000.app.github.dev/?token={qr_token}")


async def _cmd_close_table(text: str, chat_id: int, db):
    from app.models import DiningTable, TableSession, TableStatus
    from sqlalchemy import select as sa_select
    parts = text.split()
    if len(parts) < 2:
        await _send(chat_id, "รูปแบบ: /ปิดโต๊ะ [เลขโต๊ะ]\nเช่น /ปิดโต๊ะ 5")
        return
    try:
        table_num = int(parts[1])
    except:
        await _send(chat_id, "กรุณาระบุเลขโต๊ะ")
        return
    result = await db.execute(sa_select(DiningTable).where(DiningTable.table_number == table_num))
    table  = result.scalar_one_or_none()
    if not table:
        await _send(chat_id, f"❌ ไม่พบโต๊ะ {table_num}")
        return
    result2 = await db.execute(sa_select(TableSession).where(TableSession.table_id == table.id).where(TableSession.closed_at.is_(None)))
    session = result2.scalar_one_or_none()
    if session:
        session.closed_at = datetime.now(timezone.utc)
        session.is_paid   = True
    table.status = TableStatus.CLEANING
    await _send(chat_id, f"✅ ปิดโต๊ะ {table_num} แล้ว")


async def _cmd_summary(chat_id: int, db):
    from app.models import Order, TableSession
    from sqlalchemy import func, select as sa_select
    today  = date.today()
    result = await db.execute(
        sa_select(func.count(Order.id), func.coalesce(func.sum(Order.total), 0))
        .where(Order.paid_at.isnot(None))
        .where(func.date(Order.paid_at) == today)
    )
    count, total = result.one()
    result2 = await db.execute(sa_select(func.count(TableSession.id)).where(TableSession.closed_at.is_(None)))
    open_tables = result2.scalar() or 0
    await _send(chat_id,
        f"📊 ยอดขายวันที่ {today.strftime('%d/%m/%Y')}\n\n"
        f"💰 รายได้รวม: ฿{float(total):.0f}\n"
        f"🧾 จำนวน bill: {count}\n"
        f"🍽️ โต๊ะที่เปิดอยู่: {open_tables} โต๊ะ"
    )


async def _cmd_staff_list(chat_id: int, db):
    from sqlalchemy import select as sa_select
    result = await db.execute(sa_select(Staff).where(Staff.status == StaffStatus.ACTIVE))
    staff_list = result.scalars().all()
    if not staff_list:
        await _send(chat_id, "ไม่มีพนักงาน ACTIVE")
        return
    role_th = {"admin":"ผู้จัดการ","cashier":"แคชเชียร์","waiter":"เสิร์ฟ","kitchen":"ครัว","bar":"บาร์"}
    lines   = ["👥 พนักงานทั้งหมด\n"]
    for s in staff_list:
        lines.append(f"• {s.full_name} ({s.nickname}) — {role_th.get(s.role.value, s.role)}")
    await _send(chat_id, "\n".join(lines))


async def _cmd_deactivate(text: str, chat_id: int, db):
    try:
        tid = int(text.split("_")[1])
        t   = await db.get(Staff, tid)
        if t:
            t.deactivate()
            await _send(chat_id, f"✅ ระงับ {t.full_name} ({t.nickname}) แล้ว")
        else:
            await _send(chat_id, f"ไม่พบพนักงาน id={tid}")
    except Exception as e:
        await _send(chat_id, f"รูปแบบ: /ระงับ_[id]\nError: {e}")


async def _handle_menu(msg: dict, staff, db):
    chat_id = msg["from"]["id"]
    text    = msg.get("text", "")

    if text == "📸 เช็คอิน":
        staff.bot_state = "clockin:selfie"
        await _send(chat_id, "📸 ส่งรูป selfie เพื่อเช็คอินครับ")
    elif text == "🚪 เช็คเอาท์":
        staff.bot_state = "clockout:selfie"
        await _send(chat_id, "📸 ส่งรูป selfie เพื่อเช็คเอาท์ครับ")
    elif text == "📍 โซนของฉัน":
        from app.models import ZoneStaffAssignment, Zone
        from sqlalchemy import select as sa_select
        result = await db.execute(sa_select(ZoneStaffAssignment).where(ZoneStaffAssignment.staff_id == staff.id).where(ZoneStaffAssignment.assigned_date == date.today()))
        assign = result.scalar_one_or_none()
        if assign:
            zone = await db.get(Zone, assign.zone_id)
            await _send(chat_id, f"📍 Zone ของคุณวันนี้: {zone.name if zone else '—'}")
        else:
            await _send(chat_id, "ยังไม่ได้รับมอบหมาย zone วันนี้ครับ")
    elif text == "💰 รายได้ของฉัน":
        from app.models import PayrollEntry
        from sqlalchemy import select as sa_select
        result = await db.execute(sa_select(PayrollEntry).where(PayrollEntry.staff_id == staff.id).order_by(PayrollEntry.id.desc()).limit(3))
        entries = result.scalars().all()
        if not entries:
            await _send(chat_id, "ยังไม่มีข้อมูลรายได้ครับ")
        else:
            lines = [f"💰 รายได้ล่าสุด {staff.nickname}\n"]
            for e in entries:
                lines.append(f"• รอบ #{e.cycle_id}: ฿{float(e.net_pay):.0f} ({'✅จ่ายแล้ว' if e.is_paid else '⏳รอจ่าย'})")
            await _send(chat_id, "\n".join(lines))
    elif text == "📊 สรุปการเข้างาน":
        from app.models import AttendanceLog, AttendanceStatus
        from sqlalchemy import select as sa_select, extract
        today  = date.today()
        result = await db.execute(sa_select(AttendanceLog).where(AttendanceLog.staff_id == staff.id).where(extract("month", AttendanceLog.log_date) == today.month).where(extract("year", AttendanceLog.log_date) == today.year))
        logs   = result.scalars().all()
        on_time = sum(1 for l in logs if l.status == AttendanceStatus.ON_TIME)
        late    = sum(1 for l in logs if l.status in [AttendanceStatus.LATE, AttendanceStatus.FINED])
        fines   = sum(float(l.late_fine_baht) for l in logs)
        await _send(chat_id, f"📊 สรุปเดือนนี้ {staff.nickname}\n\n✅ มาตรงเวลา: {on_time} วัน\n⏰ มาสาย: {late} วัน\n💸 ค่าปรับ: ฿{fines:.0f}\n📅 รวมมา: {len(logs)} วัน")
    elif text == "🕐 ตารางกะวันนี้":
        from app.models import Shift
        from sqlalchemy import select as sa_select
        result = await db.execute(sa_select(Shift).where(Shift.staff_id == staff.id).where(Shift.shift_date == date.today()))
        shift  = result.scalar_one_or_none()
        if shift:
            await _send(chat_id, f"🕐 กะงานวันนี้\n\n⏰ {shift.start_time.strftime('%H:%M')} — {shift.end_time.strftime('%H:%M')}\n📋 {shift.shift_type}")
        else:
            await _send(chat_id, "ไม่มีกะงานวันนี้ครับ")
    elif text == "📊 ยอดขายวันนี้" and staff.is_admin:
        await _cmd_summary(chat_id, db)
    elif text == "👥 พนักงานทั้งหมด" and staff.is_admin:
        await _cmd_staff_list(chat_id, db)
    elif text == "❌ มาร์คหมด" and staff.is_admin:
        await _send(chat_id, "พิมพ์: /หมด [ชื่อเมนู]\nเช่น /หมด ข้าวผัด")
    elif text == "🔓 เปิดโต๊ะ" and staff.is_admin:
        await _send(chat_id, "พิมพ์: /เปิดโต๊ะ [เลขโต๊ะ]\nเช่น /เปิดโต๊ะ 5")
    elif text == "🔒 ปิดโต๊ะ" and staff.is_admin:
        await _send(chat_id, "พิมพ์: /ปิดโต๊ะ [เลขโต๊ะ]\nเช่น /ปิดโต๊ะ 5")
    elif text == "🗺️ แผนผังโต๊ะ" and staff.is_admin:
        from app.models import DiningTable
        from sqlalchemy import select as sa_select
        result = await db.execute(sa_select(DiningTable).order_by(DiningTable.table_number))
        tables = result.scalars().all()
        emoji  = {"available":"🟢","occupied":"🔴","cleaning":"🟡","reserved":"🔵"}
        lines  = ["🗺️ แผนผังโต๊ะ\n"]
        for i in range(0, 50, 5):
            row = tables[i:i+5] if i < len(tables) else []
            lines.append(" ".join([f"{emoji.get(t.status.value,'⬜')}{t.table_number}" for t in row]))
        lines.append("\n🟢ว่าง 🔴มีลูกค้า 🟡เก็บโต๊ะ 🔵จอง")
        await _send(chat_id, "\n".join(lines))
    else:
        keyboard = KEYBOARDS["admin" if staff.is_admin else "staff"]
        await _send(chat_id, f"สวัสดีครับ {staff.nickname} 😊", reply_markup=keyboard)


async def _handle_callback(cq: dict, staff, msg_chat: int, db):
    data = cq.get("data", "")

    if data.startswith("group:"):
        action = data.replace("group:", "")
        if action == "summary":
            await _cmd_summary(msg_chat, db)
        elif action == "floorplan":
            from app.models import DiningTable
            from sqlalchemy import select as sa_select
            result = await db.execute(sa_select(DiningTable).order_by(DiningTable.table_number))
            tables = result.scalars().all()
            emoji  = {"available":"🟢","occupied":"🔴","cleaning":"🟡","reserved":"🔵"}
            lines  = ["🗺️ แผนผังโต๊ะ\n"]
            for i in range(0, 50, 5):
                row = tables[i:i+5] if i < len(tables) else []
                lines.append(" ".join([f"{emoji.get(t.status.value,'⬜')}{t.table_number}" for t in row]))
            lines.append("\n🟢ว่าง 🔴มีลูกค้า 🟡เก็บโต๊ะ 🔵จอง")
            await _send(msg_chat, "\n".join(lines))
        elif action == "stafflist":
            await _cmd_staff_list(msg_chat, db)
        elif action == "soldout_list":
            from app.models import MenuItem
            from sqlalchemy import select as sa_select
            result = await db.execute(sa_select(MenuItem).where(MenuItem.is_sold_out == True).where(MenuItem.deleted_at.is_(None)))
            items  = result.scalars().all()
            if items:
                lines = ["❌ เมนูที่หมดอยู่:\n"] + [f"• {i.name}" for i in items]
                lines.append("\nพิมพ์ /หมด [ชื่อ] เพื่อเปลี่ยนสถานะ")
                await _send(msg_chat, "\n".join(lines))
            else:
                await _send(msg_chat, "✅ ไม่มีเมนูที่หมดอยู่")
        elif action == "opentable":
            await _send(msg_chat, "🔓 เปิดโต๊ะ\nพิมพ์: /เปิดโต๊ะ [เลขโต๊ะ]\nเช่น /เปิดโต๊ะ 5")
        elif action == "closetable":
            await _send(msg_chat, "🔒 ปิดโต๊ะ\nพิมพ์: /ปิดโต๊ะ [เลขโต๊ะ]\nเช่น /ปิดโต๊ะ 5")
        elif action == "orders":
            from app.models import TableSession, DiningTable
            from sqlalchemy import select as sa_select
            result = await db.execute(sa_select(TableSession).where(TableSession.closed_at.is_(None)))
            sessions = result.scalars().all()
            if sessions:
                lines = [f"📋 โต๊ะที่เปิดอยู่ {len(sessions)} โต๊ะ\n"]
                for s in sessions[:10]:
                    table    = await db.get(DiningTable, s.table_id)
                    tnum     = table.table_number if table else s.table_id
                    opened   = s.opened_at.strftime("%H:%M") if s.opened_at else "—"
                    lines.append(f"🔴 โต๊ะ {tnum}  |  เปิด {opened} น.")
                await _send(msg_chat, "\n".join(lines))
            else:
                await _send(msg_chat, "✅ ไม่มีโต๊ะที่เปิดอยู่")
        elif action == "revenue":
            await _cmd_summary(msg_chat, db)
        await _send_group_menu(msg_chat)
        return

    if data.startswith("ot_approve_"):
        ot_id = int(data.split("_")[2])
        from app.models import OTRequest, OTStatus
        ot = await db.get(OTRequest, ot_id)
        if ot and ot.status == OTStatus.PENDING:
            ot.status      = OTStatus.APPROVED
            ot.resolved_at = datetime.now(timezone.utc)
            chat_id = cq["from"]["id"]
            await _send(chat_id, f"✅ อนุมัติ OT #{ot_id}")


async def _get_staff(chat_id: int, db):
    result = await db.execute(select(Staff).where(Staff.telegram_chat_id == chat_id))
    return result.scalar_one_or_none()


async def _send(chat_id: int, text: str, reply_markup: dict | None = None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        async with httpx.AsyncClient() as client:
            await client.post(f"{BOT_API}/sendMessage", json=payload, timeout=10)
    except Exception as e:
        logger.error(f"Telegram send error: {e}")


async def _download_photo(msg: dict, staff_id: int, context: str) -> str:
    file_id   = msg["photo"][-1]["file_id"]
    today     = date.today().strftime("%Y%m%d")
    save_dir  = f"uploads/{staff_id}"
    os.makedirs(save_dir, exist_ok=True)
    save_path = f"{save_dir}/{today}_{context}.jpg"
    try:
        async with httpx.AsyncClient() as client:
            r  = await client.get(f"{BOT_API}/getFile", params={"file_id": file_id})
            fp = r.json()["result"]["file_path"]
            r2 = await client.get(f"https://api.telegram.org/file/bot{settings.TELEGRAM_BOT_TOKEN}/{fp}")
            with open(save_path, "wb") as f:
                f.write(r2.content)
    except Exception as e:
        logger.error(f"Photo download error: {e}")
    return save_path
