"""routers/payroll.py — Payroll cycles, OT approval, entries"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import OTRequest, OTStatus, PayrollCycle, PayrollEntry, PayrollStatus
from app.schemas import (
    MessageResponse, OTRequestOut, OTResolveRequest,
    PayrollCycleOut, PayrollEntryAdjust, PayrollEntryOut,
)

router = APIRouter()


@router.get("/cycles", response_model=list[PayrollCycleOut])
async def list_cycles(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(PayrollCycle).order_by(PayrollCycle.period_start.desc()))
    return result.scalars().all()


@router.post("/cycles/{cycle_id}/run", response_model=MessageResponse)
async def run_cycle(cycle_id: int, db: AsyncSession = Depends(get_db)):
    """Admin สั่งคำนวณเงินเดือนสำหรับ cycle นี้"""
    cycle = await db.get(PayrollCycle, cycle_id)
    if not cycle:
        raise HTTPException(status_code=404, detail="ไม่พบ cycle นี้")
    if cycle.status != PayrollStatus.DRAFT:
        raise HTTPException(status_code=400, detail=f"Cycle นี้อยู่ในสถานะ {cycle.status} แล้ว")

    # TODO: await payroll_service.compute_cycle(cycle, db)
    cycle.status = PayrollStatus.PENDING
    cycle.run_at = datetime.now(timezone.utc)
    return {"message": f"คำนวณรอบ {cycle.period_start} – {cycle.period_end} สำเร็จ"}


@router.get("/cycles/{cycle_id}/entries", response_model=list[PayrollEntryOut])
async def get_entries(cycle_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(PayrollEntry).where(PayrollEntry.cycle_id == cycle_id)
    )
    return result.scalars().all()


@router.patch("/entries/{entry_id}", response_model=PayrollEntryOut)
async def adjust_entry(
    entry_id: int,
    body: PayrollEntryAdjust,
    db: AsyncSession = Depends(get_db),
):
    """Admin ปรับยอดหักก่อน approve"""
    entry = await db.get(PayrollEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="ไม่พบรายการนี้")
    if body.other_deductions is not None:
        entry.other_deductions = body.other_deductions
    if body.deduction_note is not None:
        entry.deduction_note = body.deduction_note
    entry.compute()
    return entry


@router.post("/cycles/{cycle_id}/approve", response_model=MessageResponse)
async def approve_cycle(cycle_id: int, db: AsyncSession = Depends(get_db)):
    cycle = await db.get(PayrollCycle, cycle_id)
    if not cycle or cycle.status != PayrollStatus.PENDING:
        raise HTTPException(status_code=400, detail="Cycle ไม่อยู่ในสถานะ PENDING")
    cycle.status = PayrollStatus.APPROVED
    return {"message": "อนุมัติ cycle สำเร็จ"}


@router.get("/ot", response_model=list[OTRequestOut])
async def list_ot_requests(
    status: OTStatus | None = None,
    db: AsyncSession = Depends(get_db),
):
    q = select(OTRequest)
    if status:
        q = q.where(OTRequest.status == status)
    result = await db.execute(q.order_by(OTRequest.id.desc()))
    return result.scalars().all()


@router.post("/ot/{ot_id}/resolve", response_model=MessageResponse)
async def resolve_ot(
    ot_id: int,
    body: OTResolveRequest,
    db: AsyncSession = Depends(get_db),
):
    """Admin อนุมัติ/ปฏิเสธ OT ผ่าน API (หรือ Telegram inline button)"""
    ot = await db.get(OTRequest, ot_id)
    if not ot or ot.status != OTStatus.PENDING:
        raise HTTPException(status_code=400, detail="ไม่พบ OT หรือตัดสินไปแล้ว")
    ot.status      = body.status
    ot.admin_note  = body.admin_note
    ot.resolved_at = datetime.now(timezone.utc)
    result_th = "อนุมัติ" if body.status == OTStatus.APPROVED else "ปฏิเสธ"
    return {"message": f"{result_th} OT request #{ot_id} สำเร็จ"}