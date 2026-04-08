"""services/payroll_service.py — คำนวณเงินเดือนอัตโนมัติ"""
from datetime import date
from decimal import Decimal

from sqlalchemy import select, extract, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import (
    AttendanceLog, AttendanceStatus, OTRequest, OTStatus,
    PayrollCycle, PayrollEntry, PayrollStatus, Staff, StaffStatus, WageType,
)


async def compute_cycle(cycle: PayrollCycle, db: AsyncSession) -> list[PayrollEntry]:
    """
    คำนวณ PayrollEntry สำหรับพนักงาน ACTIVE ทุกคนในรอบนี้
    เรียกจาก /api/payroll/cycles/{id}/run
    """
    # ดึงพนักงาน active ทั้งหมด
    result = await db.execute(
        select(Staff).where(Staff.status == StaffStatus.ACTIVE)
    )
    staff_list = result.scalars().all()
    entries    = []

    for staff in staff_list:
        entry = await _compute_staff_entry(staff, cycle, db)
        db.add(entry)
        entries.append(entry)

    await db.flush()
    return entries


async def _compute_staff_entry(
    staff: Staff,
    cycle: PayrollCycle,
    db: AsyncSession,
) -> PayrollEntry:
    """คำนวณ entry เดียวสำหรับพนักงาน 1 คน"""

    # ── จำนวนวันที่มา + ค่าปรับสาย ────────────────────────────────────────────
    att_result = await db.execute(
        select(AttendanceLog)
        .where(AttendanceLog.staff_id == staff.id)
        .where(AttendanceLog.log_date >= cycle.period_start)
        .where(AttendanceLog.log_date <= cycle.period_end)
        .where(AttendanceLog.clock_in_at.isnot(None))
    )
    logs       = att_result.scalars().all()
    days_worked = len(logs)
    late_fines  = Decimal(str(sum(float(l.late_fine_baht) for l in logs)))

    # ── Base wage ─────────────────────────────────────────────────────────────
    if staff.wage_type == WageType.DAILY:
        base_wage = staff.wage_rate * days_worked
    else:
        # Monthly: prorated by days in period
        period_days = (cycle.period_end - cycle.period_start).days + 1
        base_wage   = staff.wage_rate / Decimal("2")  # รอบ 2 สัปดาห์

    # ── OT ────────────────────────────────────────────────────────────────────
    ot_result = await db.execute(
        select(OTRequest)
        .join(AttendanceLog)
        .where(AttendanceLog.staff_id == staff.id)
        .where(AttendanceLog.log_date >= cycle.period_start)
        .where(AttendanceLog.log_date <= cycle.period_end)
        .where(OTRequest.status == OTStatus.APPROVED)
    )
    ot_rows        = ot_result.scalars().all()
    ot_minutes_total = sum(o.ot_minutes for o in ot_rows)
    ot_total         = Decimal(str(sum(float(o.ot_amount) for o in ot_rows)))

    entry = PayrollEntry(
        cycle_id=cycle.id,
        staff_id=staff.id,
        days_worked=days_worked,
        base_wage=base_wage,
        ot_minutes_total=ot_minutes_total,
        ot_total=ot_total,
        late_fines=late_fines,
    )
    entry.compute()  # คำนวณ gross และ net_pay
    return entry


async def schedule_cycles():
    """
    APScheduler job — ทำงานทุกวันที่ 1 และ 16 ของเดือน เวลา 00:01
    สร้าง PayrollCycle อัตโนมัติ
    """
    from app.database import AsyncSessionLocal
    today = date.today()

    if today.day not in (1, 16):
        return

    if today.day == 1:
        period_start = date(today.year, today.month, 16)
        period_end   = date(today.year, today.month, today.day - 1) if today.month > 1 else date(today.year - 1, 12, 31)
        # วันที่ 1 → ครอบคลุม 16-สิ้นเดือนก่อน (ปรับตามจริง)
    else:
        period_start = date(today.year, today.month, 1)
        period_end   = date(today.year, today.month, 15)

    async with AsyncSessionLocal() as db:
        cycle = PayrollCycle(
            period_start=period_start,
            period_end=period_end,
            status=PayrollStatus.DRAFT,
        )
        db.add(cycle)
        await db.commit()