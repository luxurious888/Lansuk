"""services/attendance_service.py — Clock-in/out, GPS check, late fine, OT"""
import math
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import (
    AttendanceLog, AttendanceStatus, LatePolicy,
    OTRequest, OTStatus, Shift, Staff,
)


def _haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """คำนวณระยะทางระหว่าง 2 พิกัด GPS (เมตร)"""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi  = math.radians(lat2 - lat1)
    dlam  = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


async def _get_policy(staff: Staff, db: AsyncSession) -> tuple[int, float, int]:
    """คืน (free_late_per_month, fine_per_minute, grace_minutes) ของพนักงาน"""
    result = await db.execute(
        select(LatePolicy).where(LatePolicy.staff_id == staff.id)
    )
    policy = result.scalar_one_or_none()
    if policy:
        return int(policy.free_late_per_month), float(policy.fine_per_minute), int(policy.grace_minutes)
    return (
        settings.DEFAULT_FREE_LATE_PER_MONTH,
        settings.DEFAULT_FINE_PER_MINUTE,
        settings.DEFAULT_GRACE_MINUTES,
    )


async def _count_late_this_month(staff_id: int, db: AsyncSession) -> int:
    """นับจำนวนครั้งที่สายในเดือนปัจจุบัน (LATE + FINED)"""
    from sqlalchemy import func, extract
    result = await db.execute(
        select(func.count(AttendanceLog.id))
        .where(AttendanceLog.staff_id == staff_id)
        .where(AttendanceLog.status.in_([AttendanceStatus.LATE, AttendanceStatus.FINED]))
        .where(extract("month", AttendanceLog.log_date) == date.today().month)
        .where(extract("year",  AttendanceLog.log_date) == date.today().year)
    )
    return result.scalar() or 0


async def process_clock_in(
    staff: Staff,
    lat: float,
    lon: float,
    selfie_path: str,
    db: AsyncSession,
) -> AttendanceLog:
    """
    บันทึก clock-in:
    1. ตรวจ GPS
    2. ดึง shift ของวันนี้
    3. คำนวณนาทีที่สาย
    4. คำนวณค่าปรับถ้าเกิน quota
    5. บันทึก AttendanceLog
    """
    now       = datetime.now(timezone.utc)
    today     = date.today()

    # ── GPS ──────────────────────────────────────────────────────────────────
    distance  = _haversine_meters(lat, lon, settings.RESTAURANT_LAT, settings.RESTAURANT_LON)
    gps_valid = distance <= settings.GPS_RADIUS_METERS

    # ── Shift ─────────────────────────────────────────────────────────────────
    result = await db.execute(
        select(Shift)
        .where(Shift.staff_id == staff.id)
        .where(Shift.shift_date == today)
    )
    shift = result.scalar_one_or_none()

    # ── Late calculation ──────────────────────────────────────────────────────
    late_minutes   = 0
    late_fine_baht = 0.0
    status         = AttendanceStatus.ON_TIME
    free_quota, fine_per_min, grace_min = await _get_policy(staff, db)

    if shift:
        shift_start = datetime.combine(today, shift.start_time, tzinfo=timezone.utc)
        diff        = (now - shift_start).total_seconds() / 60
        if diff > grace_min:
            late_minutes = int(diff)
            late_count   = await _count_late_this_month(staff.id, db)
            if late_count < free_quota:
                status = AttendanceStatus.LATE
            else:
                status         = AttendanceStatus.FINED
                late_fine_baht = late_minutes * fine_per_min

    # ── บันทึก ────────────────────────────────────────────────────────────────
    log = AttendanceLog(
        staff_id=staff.id,
        shift_id=shift.id if shift else None,
        log_date=today,
        clock_in_at=now,
        selfie_in_path=selfie_path,
        gps_lat_in=lat,
        gps_lon_in=lon,
        gps_valid_in=gps_valid,
        late_minutes=late_minutes,
        status=status,
        late_fine_baht=late_fine_baht,
    )
    db.add(log)
    await db.flush()
    return log


async def process_clock_out(
    staff: Staff,
    selfie_path: str,
    db: AsyncSession,
) -> tuple[AttendanceLog, OTRequest | None]:
    """
    บันทึก clock-out:
    1. อัปเดต AttendanceLog
    2. ถ้าออกหลัง shift.end_time → สร้าง OTRequest
    """
    now   = datetime.now(timezone.utc)
    today = date.today()

    # ── ดึง log วันนี้ ─────────────────────────────────────────────────────────
    result = await db.execute(
        select(AttendanceLog)
        .where(AttendanceLog.staff_id == staff.id)
        .where(AttendanceLog.log_date == today)
        .where(AttendanceLog.clock_out_at.is_(None))
    )
    log = result.scalar_one_or_none()
    if not log:
        # สร้าง log ใหม่ถ้ายังไม่ clock-in (กรณีผิดปกติ)
        log = AttendanceLog(staff_id=staff.id, log_date=today)
        db.add(log)
        await db.flush()

    log.clock_out_at    = now
    log.selfie_out_path = selfie_path

    # ── OT ────────────────────────────────────────────────────────────────────
    ot_request = None
    if log.shift_id:
        shift = await db.get(Shift, log.shift_id)
        if shift:
            shift_end  = datetime.combine(today, shift.end_time, tzinfo=timezone.utc)
            ot_minutes = int((now - shift_end).total_seconds() / 60)
            if ot_minutes > 0:
                # คำนวณ OT rate = wage_rate/8h × 1.5
                hourly     = float(staff.wage_rate) / 8 if staff.wage_rate else 0
                ot_rate    = hourly * settings.OT_RATE_MULTIPLIER
                ot_amount  = (ot_minutes / 60) * ot_rate
                ot_request = OTRequest(
                    staff_id=staff.id,
                    attendance_log_id=log.id,
                    ot_minutes=ot_minutes,
                    ot_rate_baht=ot_rate,
                    ot_amount=ot_amount,
                    status=OTStatus.PENDING,
                )
                db.add(ot_request)

    await db.flush()
    return log, ot_request