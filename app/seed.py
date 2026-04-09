"""
Seed script — สร้างข้อมูลเริ่มต้น (โต๊ะ + เมนู + categories)
Idempotent: รันซ้ำได้ ไม่สร้างข้อมูลซ้ำ

วิธีใช้:
    python -m app.seed
หรือเรียกผ่าน endpoint:
    POST /api/admin/seed
"""
import asyncio
from decimal import Decimal
from sqlalchemy import select

from app.database import AsyncSessionLocal, engine, Base
from app.models import (
    DiningTable, TableStatus,
    Category, MenuItem, ModifierGroup, ModifierOption,
    KDSRoute,
)


TABLES_DATA = []
# โต๊ะ 1-10 คอลัมน์ 1 (แถว 1-10)
for r in range(1, 11):
    TABLES_DATA.append((r, 1, r, 4))
# โต๊ะ 11-20 คอลัมน์ 2 (แถว 10-1)
for r in range(10, 0, -1):
    TABLES_DATA.append((21 - r, 2, r, 4))
# โต๊ะ 21-30 คอลัมน์ 3 (แถว 1-10)
for r in range(1, 11):
    TABLES_DATA.append((20 + r, 3, r, 4))
# โต๊ะ 31-40 คอลัมน์ 4 (แถว 10-1)
for r in range(10, 0, -1):
    TABLES_DATA.append((41 - r, 4, r, 4))
# โต๊ะ 41-50 คอลัมน์ 5 (แถว 1-10)
for r in range(1, 11):
    TABLES_DATA.append((40 + r, 5, r, 4))


CATEGORIES_DATA = [
    ("อาหารจานเดียว", "Rice Dishes", 1),
    ("อาหารแนะนำ",   "Recommended",  2),
    ("เครื่องดื่ม",  "Drinks",       3),
    ("ของทอด",       "Fried",        4),
]


MENU_DATA = [
    # (ชื่อ, ชื่ออังกฤษ, category_name, price, kds_route, description, modifiers)
    ("ข้าวผัดกระเพราหมูสับ", "Basil Fried Rice", "อาหารจานเดียว", 60, "kitchen",
     "หมูสับผัดกระเพราราดข้าว",
     [
         ("ความเผ็ด", True, 1, 1, [("ไม่เผ็ด", 0), ("เผ็ดน้อย", 0), ("เผ็ดกลาง", 0), ("เผ็ดมาก", 0)]),
         ("เพิ่มไข่ดาว", False, 0, 1, [("ไข่ดาว", 10)]),
     ]),
    ("ผัดไทยกุ้งสด", "Pad Thai", "อาหารจานเดียว", 80, "kitchen",
     "เส้นผัดไทยกุ้งสด ถั่วงอก ไข่",
     [("ความเผ็ด", True, 1, 1, [("ไม่เผ็ด", 0), ("เผ็ดน้อย", 0), ("เผ็ดมาก", 0)])]),
    ("ข้าวมันไก่", "Khao Man Gai", "อาหารจานเดียว", 55, "kitchen",
     "ข้าวมันไก่ต้ม ซุปใส น้ำจิ้ม", []),
    ("ข้าวหมูทอดกระเทียม", "Garlic Pork Rice", "อาหารจานเดียว", 65, "kitchen",
     "หมูทอดกระเทียม ราดข้าวสวย", []),
    ("ยำวุ้นเส้น", "Yum Woon Sen", "อาหารแนะนำ", 80, "kitchen",
     "ยำวุ้นเส้นรสแซ่บ หมูสับ กุ้ง",
     [("ความเผ็ด", True, 1, 1, [("ไม่เผ็ด", 0), ("เผ็ดน้อย", 0), ("เผ็ดกลาง", 0), ("เผ็ดมาก", 0)])]),
    ("ต้มยำกุ้งน้ำข้น", "Tom Yum Goong", "อาหารแนะนำ", 150, "kitchen",
     "ต้มยำกุ้งน้ำข้น รสจัดจ้าน", []),
    ("ส้มตำไทย", "Papaya Salad", "อาหารแนะนำ", 60, "kitchen",
     "ส้มตำไทย รสชาติต้นตำรับ",
     [("ความเผ็ด", True, 1, 1, [("ไม่เผ็ด", 0), ("เผ็ดน้อย", 0), ("เผ็ดมาก", 0), ("เผ็ดพิเศษ", 0)])]),
    ("น้ำเปล่า", "Water", "เครื่องดื่ม", 15, "bar", "", []),
    ("น้ำอัดลม", "Soft Drink", "เครื่องดื่ม", 25, "bar", "โค้ก/เป๊ปซี่/สไปรท์", []),
    ("น้ำส้มคั้นสด", "Fresh Orange", "เครื่องดื่ม", 35, "bar", "", []),
    ("ชาไทยเย็น", "Thai Iced Tea", "เครื่องดื่ม", 30, "bar", "", []),
    ("ไก่ทอดกระเทียม", "Fried Chicken", "ของทอด", 120, "kitchen",
     "ไก่ทอดสมุนไพร เสิร์ฟพร้อมน้ำจิ้ม", []),
    ("ปอเปี๊ยะทอด", "Spring Rolls", "ของทอด", 60, "kitchen",
     "ปอเปี๊ยะทอดกรอบ 4 ชิ้น", []),
    ("เฟรนช์ฟรายส์", "French Fries", "ของทอด", 50, "kitchen", "", []),
]


async def seed():
    """รัน seed data — idempotent"""
    created = {"tables": 0, "categories": 0, "menus": 0}

    async with AsyncSessionLocal() as db:
        # ── โต๊ะ ────────────────────────────────────────────
        for num, col, row, cap in TABLES_DATA:
            exists = await db.execute(
                select(DiningTable).where(DiningTable.table_number == num)
            )
            if not exists.scalar_one_or_none():
                db.add(DiningTable(
                    table_number=num, col=col, row=row,
                    capacity=cap, status=TableStatus.AVAILABLE,
                ))
                created["tables"] += 1
        await db.commit()

        # ── หมวดหมู่ ────────────────────────────────────────
        cat_map = {}
        for name, name_en, order in CATEGORIES_DATA:
            exists = await db.execute(
                select(Category).where(Category.name == name)
            )
            c = exists.scalar_one_or_none()
            if not c:
                c = Category(name=name, name_en=name_en, sort_order=order)
                db.add(c)
                await db.flush()
                created["categories"] += 1
            cat_map[name] = c.id
        await db.commit()

        # ── เมนู ────────────────────────────────────────────
        for name, name_en, cat_name, price, kds, desc, mods in MENU_DATA:
            exists = await db.execute(
                select(MenuItem).where(MenuItem.name == name)
            )
            if exists.scalar_one_or_none():
                continue

            item = MenuItem(
                category_id=cat_map[cat_name],
                name=name,
                name_en=name_en,
                description=desc or None,
                price=Decimal(str(price)),
                kds_route=KDSRoute(kds),
            )
            db.add(item)
            await db.flush()
            created["menus"] += 1

            for g_name, required, mn, mx, opts in mods:
                group = ModifierGroup(
                    item_id=item.id, name=g_name,
                    required=required, min_select=mn, max_select=mx,
                )
                db.add(group)
                await db.flush()
                for o_name, extra in opts:
                    db.add(ModifierOption(
                        group_id=group.id, name=o_name,
                        extra_price=Decimal(str(extra)),
                    ))
        await db.commit()

    return created


async def main():
    print("🌱 Seed: เริ่มสร้างข้อมูลเริ่มต้น...")
    result = await seed()
    print(f"✅ เสร็จสิ้น: สร้างใหม่ {result}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
