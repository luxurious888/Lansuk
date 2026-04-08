"""routers/staff.py — CRUD staff + onboarding approval"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Staff, LatePolicy, StaffStatus
from app.schemas import (
    MessageResponse, StaffCreate, StaffDetail,
    StaffOut, StaffUpdate, LatePolicyUpdate,
)

router = APIRouter()


@router.get("", response_model=list[StaffOut])
async def list_staff(
    status: StaffStatus | None = None,
    db: AsyncSession = Depends(get_db),
):
    q = select(Staff)
    if status:
        q = q.where(Staff.status == status)
    result = await db.execute(q.order_by(Staff.id))
    return result.scalars().all()


@router.get("/{staff_id}", response_model=StaffDetail)
async def get_staff(staff_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Staff)
        .where(Staff.id == staff_id)
        .options(selectinload(Staff.late_policy))
    )
    staff = result.scalar_one_or_none()
    if not staff:
        raise HTTPException(status_code=404, detail="ไม่พบพนักงานนี้")
    return staff


@router.post("", response_model=StaffOut, status_code=201)
async def create_staff(body: StaffCreate, db: AsyncSession = Depends(get_db)):
    staff = Staff(**body.model_dump())
    db.add(staff)
    await db.flush()
    return staff


@router.patch("/{staff_id}", response_model=StaffOut)
async def update_staff(
    staff_id: int,
    body: StaffUpdate,
    db: AsyncSession = Depends(get_db),
):
    staff = await db.get(Staff, staff_id)
    if not staff:
        raise HTTPException(status_code=404, detail="ไม่พบพนักงานนี้")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(staff, field, value)
    return staff


@router.post("/{staff_id}/approve", response_model=MessageResponse)
async def approve_staff(staff_id: int, db: AsyncSession = Depends(get_db)):
    """Admin อนุมัติพนักงานที่ status=REVIEWING → ACTIVE"""
    staff = await db.get(Staff, staff_id)
    if not staff:
        raise HTTPException(status_code=404, detail="ไม่พบพนักงานนี้")
    if staff.status != StaffStatus.REVIEWING:
        raise HTTPException(status_code=400, detail=f"สถานะปัจจุบัน: {staff.status}")
    staff.status = StaffStatus.ACTIVE
    return {"message": f"อนุมัติ {staff.nickname} สำเร็จ"}


@router.post("/{staff_id}/deactivate", response_model=MessageResponse)
async def deactivate_staff(staff_id: int, db: AsyncSession = Depends(get_db)):
    """ระงับพนักงาน — revoke bot แต่เก็บข้อมูลไว้"""
    staff = await db.get(Staff, staff_id)
    if not staff:
        raise HTTPException(status_code=404, detail="ไม่พบพนักงานนี้")
    staff.deactivate()
    return {"message": f"ระงับ {staff.nickname} สำเร็จ"}


@router.put("/{staff_id}/late-policy", response_model=MessageResponse)
async def set_late_policy(
    staff_id: int,
    body: LatePolicyUpdate,
    db: AsyncSession = Depends(get_db),
):
    staff = await db.get(Staff, staff_id)
    if not staff:
        raise HTTPException(status_code=404, detail="ไม่พบพนักงานนี้")

    result = await db.execute(
        select(LatePolicy).where(LatePolicy.staff_id == staff_id)
    )
    policy = result.scalar_one_or_none()
    if policy:
        policy.free_late_per_month = body.free_late_per_month
        policy.fine_per_minute     = body.fine_per_minute
        policy.grace_minutes       = body.grace_minutes
    else:
        db.add(LatePolicy(staff_id=staff_id, **body.model_dump()))
    return {"message": "อัปเดตนโยบายสายสำเร็จ"}