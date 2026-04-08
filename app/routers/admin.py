"""routers/admin.py — Floor plan, zones, menu, sold-out"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import (
    Category, DiningTable, MenuItem, ModifierGroup, ModifierOption,
    Zone, ZoneStaffAssignment,
)
from app.schemas import (
    CategoryCreate, CategoryOut,
    MenuItemCreate, MenuItemOut, MenuItemUpdate,
    MessageResponse, ZoneAssignOut, ZoneAssignRequest,
    ZoneCreate, ZoneOut,
)

router = APIRouter()


@router.get("/zones", response_model=list[ZoneOut])
async def list_zones(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Zone))
    return result.scalars().all()


@router.post("/zones", response_model=ZoneOut, status_code=201)
async def create_zone(body: ZoneCreate, db: AsyncSession = Depends(get_db)):
    zone = Zone(**body.model_dump())
    db.add(zone)
    await db.flush()
    return zone


@router.post("/zones/assign", response_model=ZoneAssignOut, status_code=201)
async def assign_staff_to_zone(body: ZoneAssignRequest, db: AsyncSession = Depends(get_db)):
    assignment = ZoneStaffAssignment(**body.model_dump())
    db.add(assignment)
    await db.flush()
    return assignment


@router.get("/zones/{zone_id}/tables")
async def zone_tables(zone_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(DiningTable).where(DiningTable.zone_id == zone_id).order_by(DiningTable.table_number)
    )
    return result.scalars().all()


@router.get("/floor-plan")
async def floor_plan(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(DiningTable).options(selectinload(DiningTable.zone)).order_by(DiningTable.table_number)
    )
    tables = result.scalars().all()
    return [
        {
            "id": t.id, "table_number": t.table_number,
            "col": t.col, "row": t.row, "status": t.status,
            "zone": {"id": t.zone.id, "name": t.zone.name, "color": t.zone.color} if t.zone else None,
        }
        for t in tables
    ]


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Category).where(Category.deleted_at.is_(None)).order_by(Category.sort_order)
    )
    return result.scalars().all()


@router.post("/categories", response_model=CategoryOut, status_code=201)
async def create_category(body: CategoryCreate, db: AsyncSession = Depends(get_db)):
    cat = Category(**body.model_dump())
    db.add(cat)
    await db.flush()
    return cat


@router.get("/menu", response_model=list[MenuItemOut])
async def list_menu(category_id: int | None = None, db: AsyncSession = Depends(get_db)):
    q = (
        select(MenuItem)
        .where(MenuItem.deleted_at.is_(None))
        .options(
            selectinload(MenuItem.modifier_groups)
            .selectinload(ModifierGroup.options)
        )
    )
    if category_id:
        q = q.where(MenuItem.category_id == category_id)
    result = await db.execute(q)
    return result.scalars().all()


@router.post("/menu", response_model=MenuItemOut, status_code=201)
async def create_menu_item(body: MenuItemCreate, db: AsyncSession = Depends(get_db)):
    item = MenuItem(
        category_id=body.category_id,
        name=body.name,
        name_en=body.name_en,
        description=body.description,
        price=body.price,
        image_url=body.image_url,
        kds_route=body.kds_route.value if hasattr(body.kds_route, 'value') else body.kds_route,
        track_stock=body.track_stock,
        stock_qty=body.stock_qty,
    )
    db.add(item)
    await db.flush()

    for grp_data in body.modifier_groups:
        grp = ModifierGroup(
            item_id=item.id,
            name=grp_data.name,
            required=grp_data.required,
            min_select=grp_data.min_select,
            max_select=grp_data.max_select,
        )
        db.add(grp)
        await db.flush()
        for opt_data in grp_data.options:
            db.add(ModifierOption(
                group_id=grp.id,
                name=opt_data.name,
                extra_price=opt_data.extra_price,
            ))

    await db.flush()

    result = await db.execute(
        select(MenuItem)
        .where(MenuItem.id == item.id)
        .options(
            selectinload(MenuItem.modifier_groups)
            .selectinload(ModifierGroup.options)
        )
    )
    return result.scalar_one()


@router.patch("/menu/{item_id}", response_model=MenuItemOut)
async def update_menu_item(item_id: int, body: MenuItemUpdate, db: AsyncSession = Depends(get_db)):
    item = await db.get(MenuItem, item_id)
    if not item or item.deleted_at:
        raise HTTPException(status_code=404, detail="ไม่พบเมนูนี้")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(item, field, value)
    return item


@router.post("/menu/{item_id}/sold-out", response_model=MessageResponse)
async def toggle_sold_out(item_id: int, db: AsyncSession = Depends(get_db)):
    item = await db.get(MenuItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="ไม่พบเมนูนี้")
    item.is_sold_out = not item.is_sold_out
    status_th = "หมด" if item.is_sold_out else "มีแล้ว"
    return {"message": f"'{item.name}' — {status_th}"}


@router.delete("/menu/{item_id}", response_model=MessageResponse)
async def delete_menu_item(item_id: int, db: AsyncSession = Depends(get_db)):
    item = await db.get(MenuItem, item_id)
    if not item or item.deleted_at:
        raise HTTPException(status_code=404, detail="ไม่พบเมนูนี้")
    item.soft_delete()
    return {"message": f"ลบ '{item.name}' สำเร็จ"}
