"""
routers/attendance.py
Shift management + Clock-in/out endpoints
- Manager สร้าง/ดู shift
- Attendance logs
- รองรับทั้ง Telegram bot และ HTTP (สำหรับ manager UI)
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import extract, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import AttendanceLog, Shift, Staff
from app.schemas import (
    AttendanceOut, ClockInRequest, ClockOutRequest,
    MessageResponse, ShiftCreate, ShiftOut,
)
from app.services.attendance_service import process_clock_in, process_clock_out

router = APIRouter()


# ══ SHIFTS ════════════════════════════════════════════════════════════════════

@router.get("/shifts", response_model=list[ShiftOut])
async def list_shifts(
    staff_id:   int | None = None,
    shift_date: date | None = None,
    db: AsyncSession = Depends(get_db),
):
    """ดูตารางกะงาน — filter ตาม staff หรือวันที่"""
    q = select(Shift)
    if staff_id:
        q = q.where(Shift.staff_id == staff_id)
    if shift_date:
        q = q.where(Shift.shift_date == shift_date)
    result = await db.execute(q.order_by(Shift.shift_date, Shift.start_time))
    return result.scalars().all()


@router.post("/shifts", response_model=ShiftOut, status_code=201)
async def create_shift(body: ShiftCreate, db: AsyncSession = Depends(get_db)):
    """Manager สร้างกะงานให้พนักงาน"""
    staff = await db.get(Staff, body.staff_id)
    if not staff:
        raise HTTPException(status_code=404, detail="ไม่พบพนักงานนี้")

    shift = Shift(**body.model_dump())
    db.add(shift)
    await db.flush()
    return shift


@router.delete("/shifts/{shift_id}", response_model=MessageResponse)
async def delete_shift(shift_id: int, db: AsyncSession = Depends(get_db)):
    shift = await db.get(Shift, shift_id)
    if not shift:
        raise HTTPException(status_code=404, detail="ไม่พบกะงานนี้")
    await db.delete(shift)
    return {"message": f"ลบกะ #{shift_id} สำเร็จ"}


# ══ CLOCK-IN / CLOCK-OUT (HTTP — สำหรับ manager UI / testing) ════════════════

@router.post("/clock-in", response_model=AttendanceOut)
async def clock_in(body: ClockInRequest, db: AsyncSession = Depends(get_db)):
    """
    Clock-in ผ่าน HTTP (Telegram bot ใช้ attendance_service โดยตรง)
    ใช้สำหรับ manager UI หรือ testing
    """
    staff = await db.get(Staff, body.staff_id)
    if not staff:
        raise HTTPException(status_code=404, detail="ไม่พบพนักงานนี้")

    log = await process_clock_in(
        staff=staff,
        lat=body.gps_lat,
        lon=body.gps_lon,
        selfie_path=body.selfie_path,
        db=db,
    )
    return log


@router.post("/clock-out", response_model=AttendanceOut)
async def clock_out(body: ClockOutRequest, db: AsyncSession = Depends(get_db)):
    """Clock-out ผ่าน HTTP"""
    staff = await db.get(Staff, body.staff_id)
    if not staff:
        raise HTTPException(status_code=404, detail="ไม่พบพนักงานนี้")

    log, ot_req = await process_clock_out(
        staff=staff,
        selfie_path=body.selfie_path,
        db=db,
    )
    return log


# ══ ATTENDANCE LOGS ════════════════════════════════════════════════════════════

@router.get("/logs", response_model=list[AttendanceOut])
async def list_logs(
    staff_id:   int | None  = None,
    date_from:  date | None = None,
    date_to:    date | None = None,
    db: AsyncSession = Depends(get_db),
):
    """ดู attendance logs — filter ตาม staff และช่วงวันที่"""
    q = select(AttendanceLog)
    if staff_id:
        q = q.where(AttendanceLog.staff_id == staff_id)
    if date_from:
        q = q.where(AttendanceLog.log_date >= date_from)
    if date_to:
        q = q.where(AttendanceLog.log_date <= date_to)
    result = await db.execute(q.order_by(AttendanceLog.log_date.desc()))
    return result.scalars().all()


@router.get("/logs/{log_id}", response_model=AttendanceOut)
async def get_log(log_id: int, db: AsyncSession = Depends(get_db)):
    log = await db.get(AttendanceLog, log_id)
    if not log:
        raise HTTPException(status_code=404, detail="ไม่พบ log นี้")
    return log


@router.get("/summary/monthly")
async def monthly_summary(
    staff_id: int,
    year:     int,
    month:    int,
    db: AsyncSession = Depends(get_db),
):
    """
    สรุปรายเดือน: วันที่มา, สาย, ขาด, ค่าปรับรวม
    ใช้แสดงใน Telegram /earnings และ manager UI
    """
    from sqlalchemy import func
    from app.models import AttendanceStatus

    result = await db.execute(
        select(AttendanceLog)
        .where(AttendanceLog.staff_id == staff_id)
        .where(extract("year",  AttendanceLog.log_date) == year)
        .where(extract("month", AttendanceLog.log_date) == month)
    )
    logs = result.scalars().all()

    on_time = sum(1 for l in logs if l.status == AttendanceStatus.ON_TIME)
    late    = sum(1 for l in logs if l.status == AttendanceStatus.LATE)
    fined   = sum(1 for l in logs if l.status == AttendanceStatus.FINED)
    absent  = sum(1 for l in logs if l.status == AttendanceStatus.ABSENT)
    total_fine = sum(float(l.late_fine_baht) for l in logs)

    return {
        "staff_id":    staff_id,
        "year":        year,
        "month":       month,
        "days_worked": on_time + late + fined,
        "on_time":     on_time,
        "late":        late,
        "fined":       fined,
        "absent":      absent,
        "total_fine_baht": total_fine,
    }