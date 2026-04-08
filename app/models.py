"""
models.py — ลานสุข POS
SQLAlchemy 2.0 ORM models ทั้งหมดในไฟล์เดียว

Sections:
  1. Mixins
  2. Enums
  3. Staff + LatePolicy
  4. Zone + DiningTable + TableSession
  5. Category + MenuItem + Modifier
  6. Member + Promotion
  7. Order + OrderItem + OrderItemModifier
  8. Shift + AttendanceLog
  9. OTRequest
  10. PayrollCycle + PayrollEntry
"""
from __future__ import annotations

import enum
from datetime import date, datetime, time, timezone
from decimal import Decimal

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, Enum as SAEnum,
    Float, ForeignKey, Integer, Numeric, String, Text, Time, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


# ══════════════════════════════════════════════════════════════════════════════
#  1. MIXINS
# ══════════════════════════════════════════════════════════════════════════════

class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )


class SoftDeleteMixin:
    """
    ไม่มี hard-delete เลย — set deleted_at แทน
    ข้อมูลถูกเก็บไว้อย่างน้อย 2 ปีเพื่อการตรวจสอบ
    Query active records: .where(Model.deleted_at.is_(None))
    """
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None, index=True
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def soft_delete(self) -> None:
        self.deleted_at = datetime.now(timezone.utc)


# ══════════════════════════════════════════════════════════════════════════════
#  2. ENUMS
# ══════════════════════════════════════════════════════════════════════════════

class StaffRole(str, enum.Enum):
    ADMIN   = "admin"     # เจ้าของ/ผู้จัดการ — Telegram admin menu
    CASHIER = "cashier"   # แคชเชียร์
    WAITER  = "waiter"    # พนักงานเสิร์ฟ
    KITCHEN = "kitchen"   # ครัว
    BAR     = "bar"       # บาร์


class StaffStatus(str, enum.Enum):
    PENDING   = "pending"    # กรอก /apply แล้ว รอบัตรประชาชน
    REVIEWING = "reviewing"  # อัปโหลดบัตรแล้ว รอ admin อนุมัติ
    ACTIVE    = "active"     # ใช้งานได้ปกติ
    INACTIVE  = "inactive"   # ลาออก/ระงับ — revoke bot, ข้อมูลยังอยู่


class WageType(str, enum.Enum):
    DAILY   = "daily"    # รายวัน
    MONTHLY = "monthly"  # รายเดือน


class TableStatus(str, enum.Enum):
    AVAILABLE = "available"  # ว่าง
    OCCUPIED  = "occupied"   # มีลูกค้า
    RESERVED  = "reserved"   # จอง
    CLEANING  = "cleaning"   # กำลังเก็บโต๊ะ


class KDSRoute(str, enum.Enum):
    KITCHEN = "kitchen"  # ส่งครัว
    BAR     = "bar"      # ส่งบาร์
    BOTH    = "both"     # ส่งทั้งคู่


class OrderStatus(str, enum.Enum):
    PENDING   = "pending"    # เพิ่งสั่ง
    CONFIRMED = "confirmed"  # KDS รับแล้ว
    PREPARING = "preparing"  # กำลังทำ
    READY     = "ready"      # พร้อมเสิร์ฟ
    SERVED    = "served"     # เสิร์ฟแล้ว
    CANCELLED = "cancelled"  # ยกเลิก


class PaymentMethod(str, enum.Enum):
    CASH   = "cash"    # เงินสด
    QR_PAY = "qr_pay"  # PromptPay
    CARD   = "card"    # บัตรเครดิต
    OTHER  = "other"


class ShiftType(str, enum.Enum):
    MORNING   = "morning"    # 09:00-17:00
    AFTERNOON = "afternoon"  # 12:00-20:00
    EVENING   = "evening"    # 16:00-00:00
    CUSTOM    = "custom"     # กำหนดเอง


class AttendanceStatus(str, enum.Enum):
    ON_TIME = "on_time"  # มาตรงเวลา
    LATE    = "late"     # สายแต่ยังอยู่ใน quota
    FINED   = "fined"    # เกิน quota — หักเงิน
    ABSENT  = "absent"   # ขาด
    OFF     = "off"      # วันหยุด


class OTStatus(str, enum.Enum):
    PENDING  = "pending"   # รอ admin อนุมัติ
    APPROVED = "approved"  # อนุมัติ
    REJECTED = "rejected"  # ไม่อนุมัติ


class PayrollStatus(str, enum.Enum):
    DRAFT    = "draft"     # กำลังคำนวณ
    PENDING  = "pending"   # รอ admin ยืนยัน
    APPROVED = "approved"  # admin อนุมัติแล้ว
    PAID     = "paid"      # จ่ายแล้ว


# ══════════════════════════════════════════════════════════════════════════════
#  3. STAFF + LATE POLICY
# ══════════════════════════════════════════════════════════════════════════════

class Staff(Base, TimestampMixin):
    __tablename__ = "staff"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ── ข้อมูลส่วนตัว ─────────────────────────────────────────────────────────
    full_name:    Mapped[str]        = mapped_column(String(120), nullable=False)
    nickname:     Mapped[str]        = mapped_column(String(60),  nullable=False)
    phone:        Mapped[str]        = mapped_column(String(20),  nullable=False)
    address:      Mapped[str | None] = mapped_column(Text,        nullable=True)
    national_id:  Mapped[str | None] = mapped_column(String(13),  nullable=True)   # encrypt at rest
    id_card_path: Mapped[str | None] = mapped_column(String(300), nullable=True)   # path ในเครื่อง

    # ── Telegram / Auth ──────────────────────────────────────────────────────
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)
    pin_hash:         Mapped[str | None] = mapped_column(String(128), nullable=True)  # bcrypt
    bot_state:        Mapped[str | None] = mapped_column(String(80),  nullable=True)  # FSM state key

    # ── การจ้างงาน ────────────────────────────────────────────────────────────
    role:       Mapped[StaffRole]   = mapped_column(SAEnum(StaffRole),   nullable=False, default=StaffRole.WAITER)
    status:     Mapped[StaffStatus] = mapped_column(SAEnum(StaffStatus), nullable=False, default=StaffStatus.PENDING, index=True)
    wage_type:  Mapped[WageType]    = mapped_column(SAEnum(WageType),    nullable=False, default=WageType.DAILY)
    wage_rate:  Mapped[Decimal]     = mapped_column(Numeric(10, 2),      nullable=False, default=0)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date:   Mapped[date | None] = mapped_column(Date, nullable=True)  # วันลาออก

    # ── Relationships ─────────────────────────────────────────────────────────
    late_policy:      Mapped[LatePolicy | None]         = relationship(back_populates="staff", uselist=False, lazy="joined")
    zone_assignments: Mapped[list[ZoneStaffAssignment]] = relationship(back_populates="staff")
    shifts:           Mapped[list[Shift]]               = relationship(back_populates="staff")
    attendance_logs:  Mapped[list[AttendanceLog]]       = relationship(back_populates="staff")
    payroll_entries:  Mapped[list[PayrollEntry]]        = relationship(back_populates="staff")

    # ── Methods ───────────────────────────────────────────────────────────────
    def deactivate(self) -> None:
        """ระงับพนักงาน — revoke bot access แต่เก็บข้อมูลทั้งหมดไว้"""
        self.status           = StaffStatus.INACTIVE
        self.telegram_chat_id = None
        self.bot_state        = None
        self.end_date         = date.today()

    @property
    def is_admin(self) -> bool:
        return self.role == StaffRole.ADMIN

    @property
    def is_active(self) -> bool:
        return self.status == StaffStatus.ACTIVE

    def __repr__(self) -> str:
        return f"<Staff id={self.id} nickname={self.nickname!r} role={self.role} status={self.status}>"


class LatePolicy(Base, TimestampMixin):
    """
    นโยบายสายต่อคน — ถ้าไม่มีแถวสำหรับ staff คนนั้น
    ระบบใช้ค่า default จาก config.py แทน
    """
    __tablename__ = "late_policies"

    id:                  Mapped[int]     = mapped_column(Integer, primary_key=True)
    staff_id:            Mapped[int]     = mapped_column(ForeignKey("staff.id"), unique=True, nullable=False)
    free_late_per_month: Mapped[int]     = mapped_column(Integer,          default=3)    # ครั้งที่ไม่โดนหัก
    fine_per_minute:     Mapped[Decimal] = mapped_column(Numeric(8, 2),    default=5)    # บาท/นาที หลัง quota
    grace_minutes:       Mapped[int]     = mapped_column(Integer,          default=5)    # นาทีที่ยกโทษ

    staff: Mapped[Staff] = relationship(back_populates="late_policy")


# ══════════════════════════════════════════════════════════════════════════════
#  4. ZONE + TABLE + TABLE SESSION
# ══════════════════════════════════════════════════════════════════════════════

class Zone(Base, TimestampMixin):
    """Zone คือการจัดกลุ่มโต๊ะ เช่น 'A', 'B', 'ริมรั้ว'"""
    __tablename__ = "zones"

    id:    Mapped[int] = mapped_column(Integer, primary_key=True)
    name:  Mapped[str] = mapped_column(String(60), nullable=False)
    color: Mapped[str] = mapped_column(String(7),  nullable=False, default="#4CAF50")  # hex color สำหรับ floor plan

    tables:      Mapped[list[DiningTable]]        = relationship(back_populates="zone")
    assignments: Mapped[list[ZoneStaffAssignment]] = relationship(back_populates="zone")


class ZoneStaffAssignment(Base):
    """Assignment รายวัน — พนักงานคนไหนรับผิดชอบ zone ไหนวันนี้"""
    __tablename__ = "zone_staff_assignments"

    id:            Mapped[int]  = mapped_column(Integer, primary_key=True)
    zone_id:       Mapped[int]  = mapped_column(ForeignKey("zones.id"),  nullable=False)
    staff_id:      Mapped[int]  = mapped_column(ForeignKey("staff.id"),  nullable=False)
    assigned_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    zone:  Mapped[Zone]  = relationship(back_populates="assignments")
    staff: Mapped[Staff] = relationship(back_populates="zone_assignments")


class DiningTable(Base, TimestampMixin):
    """
    โต๊ะ 50 ตัว จัดใน grid 5 คอลัมน์ x 10 แถว
    col: 1-5, row: 1-10, table_number: 1-50
    """
    __tablename__ = "dining_tables"

    id:           Mapped[int]         = mapped_column(Integer, primary_key=True)
    table_number: Mapped[int]         = mapped_column(Integer, unique=True, nullable=False)
    col:          Mapped[int]         = mapped_column(Integer, nullable=False)  # 1-5
    row:          Mapped[int]         = mapped_column(Integer, nullable=False)  # 1-10
    capacity:     Mapped[int]         = mapped_column(Integer, nullable=False, default=4)
    zone_id:      Mapped[int | None]  = mapped_column(ForeignKey("zones.id"), nullable=True)
    status: Mapped[TableStatus] = mapped_column(
        SAEnum(TableStatus), nullable=False, default=TableStatus.AVAILABLE, index=True
    )

    zone:     Mapped[Zone | None]       = relationship(back_populates="tables")
    sessions: Mapped[list[TableSession]] = relationship(back_populates="table")

    @property
    def active_session(self) -> TableSession | None:
        """คืน session ที่ยังเปิดอยู่ (closed_at is None)"""
        return next((s for s in self.sessions if s.closed_at is None), None)

    def __repr__(self) -> str:
        return f"<DiningTable #{self.table_number} col={self.col} row={self.row} status={self.status}>"


class TableSession(Base):
    """
    สร้างเมื่อแคชเชียร์เปิดโต๊ะ — QR token ผูกกับ session นี้
    ปิด session = QR หมดอายุ + พิมพ์ใบเสร็จ
    """
    __tablename__ = "table_sessions"

    id:          Mapped[int]            = mapped_column(Integer, primary_key=True)
    table_id:    Mapped[int]            = mapped_column(ForeignKey("dining_tables.id"), nullable=False, index=True)
    opened_by:   Mapped[int]            = mapped_column(ForeignKey("staff.id"),         nullable=False)
    qr_token:    Mapped[str]            = mapped_column(String(512), unique=True, nullable=False)  # JWT
    guest_count: Mapped[int]            = mapped_column(Integer, nullable=False, default=1)
    opened_at:   Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at:   Mapped[datetime | None]= mapped_column(DateTime(timezone=True), nullable=True)
    is_paid:     Mapped[bool]           = mapped_column(Boolean, nullable=False, default=False)
    customer_name: Mapped[str | None]   = mapped_column(String(120), nullable=True)  # ชื่อลูกค้า/บิล

    table:  Mapped[DiningTable]  = relationship(back_populates="sessions")
    orders: Mapped[list[Order]]  = relationship(back_populates="session")


# ══════════════════════════════════════════════════════════════════════════════
#  5. CATEGORY + MENU ITEM + MODIFIER
# ══════════════════════════════════════════════════════════════════════════════

class Category(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "categories"

    id:         Mapped[int]        = mapped_column(Integer, primary_key=True)
    name:       Mapped[str]        = mapped_column(String(80), nullable=False)         # ภาษาไทย
    name_en:    Mapped[str | None] = mapped_column(String(80), nullable=True)          # ภาษาอังกฤษ (optional)
    sort_order: Mapped[int]        = mapped_column(Integer, default=0)

    items: Mapped[list[MenuItem]] = relationship(back_populates="category")


class MenuItem(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "menu_items"

    id:          Mapped[int]        = mapped_column(Integer, primary_key=True)
    category_id: Mapped[int]        = mapped_column(ForeignKey("categories.id"), nullable=False)
    name:        Mapped[str]        = mapped_column(String(120), nullable=False)
    name_en:     Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str | None] = mapped_column(Text,        nullable=True)
    price:       Mapped[Decimal]    = mapped_column(Numeric(10, 2), nullable=False)
    image_url:   Mapped[str | None] = mapped_column(String(300), nullable=True)
    kds_route:   Mapped[KDSRoute]   = mapped_column(SAEnum(KDSRoute), nullable=False, default=KDSRoute.KITCHEN)

    # ── Stock ─────────────────────────────────────────────────────────────────
    track_stock: Mapped[bool] = mapped_column(Boolean, default=False)
    stock_qty:   Mapped[int]  = mapped_column(Integer,  default=0)
    is_sold_out: Mapped[bool] = mapped_column(Boolean,  default=False, index=True)

    category:        Mapped[Category]             = relationship(back_populates="items")
    modifier_groups: Mapped[list[ModifierGroup]]  = relationship(back_populates="item", cascade="all, delete-orphan")


class ModifierGroup(Base):
    """
    กลุ่ม modifier ของ menu item เช่น:
      - 'ความเผ็ด'     required=True,  min=1, max=1
      - 'เพิ่มท็อปปิ้ง' required=False, min=0, max=3
    """
    __tablename__ = "modifier_groups"

    id:         Mapped[int]  = mapped_column(Integer, primary_key=True)
    item_id:    Mapped[int]  = mapped_column(ForeignKey("menu_items.id"), nullable=False)
    name:       Mapped[str]  = mapped_column(String(80), nullable=False)
    required:   Mapped[bool] = mapped_column(Boolean, default=False)
    min_select: Mapped[int]  = mapped_column(Integer, default=0)
    max_select: Mapped[int]  = mapped_column(Integer, default=1)

    item:    Mapped[MenuItem]             = relationship(back_populates="modifier_groups")
    options: Mapped[list[ModifierOption]] = relationship(back_populates="group", cascade="all, delete-orphan")


class ModifierOption(Base):
    __tablename__ = "modifier_options"

    id:          Mapped[int]     = mapped_column(Integer, primary_key=True)
    group_id:    Mapped[int]     = mapped_column(ForeignKey("modifier_groups.id"), nullable=False)
    name:        Mapped[str]     = mapped_column(String(80), nullable=False)
    extra_price: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=0)
    is_active:   Mapped[bool]   = mapped_column(Boolean, default=True)

    group: Mapped[ModifierGroup] = relationship(back_populates="options")


# ══════════════════════════════════════════════════════════════════════════════
#  6. MEMBER + PROMOTION
# ══════════════════════════════════════════════════════════════════════════════

class Member(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "members"

    id:        Mapped[int]     = mapped_column(Integer, primary_key=True)
    name:      Mapped[str]     = mapped_column(String(120), nullable=False)
    phone:     Mapped[str]     = mapped_column(String(20),  unique=True, nullable=False)
    points:    Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    is_active: Mapped[bool]   = mapped_column(Boolean, default=True)

    orders: Mapped[list[Order]] = relationship(back_populates="member")


class Promotion(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "promotions"

    id:           Mapped[int]        = mapped_column(Integer, primary_key=True)
    name:         Mapped[str]        = mapped_column(String(120), nullable=False)
    code:         Mapped[str | None] = mapped_column(String(30),  unique=True, nullable=True)  # coupon code
    discount_pct: Mapped[Decimal]    = mapped_column(Numeric(5, 2),  default=0)   # 0-100 %
    discount_amt: Mapped[Decimal]    = mapped_column(Numeric(10, 2), default=0)   # fixed บาท
    valid_from:   Mapped[date]       = mapped_column(Date, nullable=False)
    valid_until:  Mapped[date]       = mapped_column(Date, nullable=False)
    is_active:    Mapped[bool]       = mapped_column(Boolean, default=True)

    orders: Mapped[list[Order]] = relationship(back_populates="promotion")


# ══════════════════════════════════════════════════════════════════════════════
#  7. ORDER + ORDER ITEM + ORDER ITEM MODIFIER
# ══════════════════════════════════════════════════════════════════════════════

class Order(Base, TimestampMixin):
    __tablename__ = "orders"

    id:         Mapped[int]         = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int]         = mapped_column(ForeignKey("table_sessions.id"), nullable=False, index=True)
    status:     Mapped[OrderStatus] = mapped_column(SAEnum(OrderStatus), default=OrderStatus.PENDING, index=True)

    # ── การชำระเงิน (กรอกตอน checkout) ──────────────────────────────────────
    subtotal:       Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    discount_amt:   Mapped[Decimal]        = mapped_column(Numeric(12, 2), default=0)
    service_charge: Mapped[Decimal]        = mapped_column(Numeric(12, 2), default=0)
    vat_amt:        Mapped[Decimal]        = mapped_column(Numeric(12, 2), default=0)
    total:          Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    payment_method: Mapped[PaymentMethod | None] = mapped_column(SAEnum(PaymentMethod), nullable=True)
    paid_at:        Mapped[datetime | None]      = mapped_column(DateTime(timezone=True), nullable=True)

    # ── สมาชิก / โปรโมชัน ──────────────────────────────────────────────────
    member_id:    Mapped[int | None] = mapped_column(ForeignKey("members.id"),    nullable=True)
    promotion_id: Mapped[int | None] = mapped_column(ForeignKey("promotions.id"), nullable=True)

    session:   Mapped[TableSession]  = relationship(back_populates="orders")
    items:     Mapped[list[OrderItem]] = relationship(back_populates="order", cascade="all, delete-orphan")
    member:    Mapped[Member | None]   = relationship(back_populates="orders")
    promotion: Mapped[Promotion | None]= relationship(back_populates="orders")

    def calculate_totals(self) -> None:
        """คำนวณ subtotal, vat, total จาก items"""
        self.subtotal       = Decimal(sum(i.line_total for i in self.items))
        self.subtotal       = self.subtotal - self.discount_amt
        self.vat_amt        = (self.subtotal * Decimal("0.07")).quantize(Decimal("0.01"))
        self.total          = self.subtotal + self.vat_amt + self.service_charge


class OrderItem(Base):
    __tablename__ = "order_items"

    id:           Mapped[int]         = mapped_column(Integer, primary_key=True)
    order_id:     Mapped[int]         = mapped_column(ForeignKey("orders.id"), nullable=False)
    menu_item_id: Mapped[int]         = mapped_column(ForeignKey("menu_items.id"), nullable=False)
    quantity:     Mapped[int]         = mapped_column(Integer, nullable=False, default=1)
    unit_price:   Mapped[Decimal]     = mapped_column(Numeric(10, 2), nullable=False)  # snapshot ราคาตอนสั่ง
    note:         Mapped[str | None]  = mapped_column(Text, nullable=True)             # หมายเหตุพิเศษ
    kds_route:    Mapped[str]         = mapped_column(String(20), nullable=False)       # snapshot จาก MenuItem
    status:       Mapped[OrderStatus] = mapped_column(SAEnum(OrderStatus), default=OrderStatus.PENDING)
    ready_at:     Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    order:     Mapped[Order]                    = relationship(back_populates="items")
    modifiers: Mapped[list[OrderItemModifier]]  = relationship(back_populates="order_item", cascade="all, delete-orphan")

    @property
    def line_total(self) -> Decimal:
        modifier_sum = sum(m.extra_price for m in self.modifiers)
        return (self.unit_price + Decimal(str(modifier_sum))) * self.quantity


class OrderItemModifier(Base):
    __tablename__ = "order_item_modifiers"

    id:            Mapped[int]     = mapped_column(Integer, primary_key=True)
    order_item_id: Mapped[int]     = mapped_column(ForeignKey("order_items.id"),       nullable=False)
    option_id:     Mapped[int]     = mapped_column(ForeignKey("modifier_options.id"),   nullable=False)
    name:          Mapped[str]     = mapped_column(String(80),    nullable=False)   # snapshot ชื่อ
    extra_price:   Mapped[Decimal] = mapped_column(Numeric(8, 2), default=0)        # snapshot ราคา

    order_item: Mapped[OrderItem] = relationship(back_populates="modifiers")


# ══════════════════════════════════════════════════════════════════════════════
#  8. SHIFT + ATTENDANCE LOG
# ══════════════════════════════════════════════════════════════════════════════

class Shift(Base, TimestampMixin):
    """ตารางกะงานของพนักงานแต่ละวัน"""
    __tablename__ = "shifts"

    id:           Mapped[int]       = mapped_column(Integer, primary_key=True)
    staff_id:     Mapped[int]       = mapped_column(ForeignKey("staff.id"), nullable=False, index=True)
    shift_date:   Mapped[date]      = mapped_column(Date, nullable=False, index=True)
    shift_type:   Mapped[ShiftType] = mapped_column(SAEnum(ShiftType), nullable=False)
    start_time:   Mapped[time]      = mapped_column(Time, nullable=False)
    end_time:     Mapped[time]      = mapped_column(Time, nullable=False)
    ping_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    staff:      Mapped[Staff]               = relationship(back_populates="shifts")
    attendance: Mapped[AttendanceLog | None] = relationship(back_populates="shift", uselist=False)


class AttendanceLog(Base, TimestampMixin):
    """
    บันทึกการเข้า-ออกงาน
    สร้างเมื่อพนักงาน clock-in (ส่ง selfie + GPS)
    อัปเดต clock_out_at เมื่อ clock-out
    """
    __tablename__ = "attendance_logs"

    id:       Mapped[int]  = mapped_column(Integer, primary_key=True)
    staff_id: Mapped[int]  = mapped_column(ForeignKey("staff.id"),  nullable=False, index=True)
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("shifts.id"), nullable=True)
    log_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # ── Clock-in ──────────────────────────────────────────────────────────────
    clock_in_at:    Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    selfie_in_path: Mapped[str | None]      = mapped_column(String(300), nullable=True)
    gps_lat_in:     Mapped[float | None]    = mapped_column(Float, nullable=True)
    gps_lon_in:     Mapped[float | None]    = mapped_column(Float, nullable=True)
    gps_valid_in:   Mapped[bool]            = mapped_column(Boolean, default=False)

    # ── Clock-out ─────────────────────────────────────────────────────────────
    clock_out_at:    Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    selfie_out_path: Mapped[str | None]      = mapped_column(String(300), nullable=True)

    # ── Computed ─────────────────────────────────────────────────────────────
    late_minutes:   Mapped[int]               = mapped_column(Integer,         default=0)
    status:         Mapped[AttendanceStatus]  = mapped_column(SAEnum(AttendanceStatus), default=AttendanceStatus.ON_TIME)
    late_fine_baht: Mapped[Decimal]           = mapped_column(Numeric(10, 2),  default=0)
    note:           Mapped[str | None]        = mapped_column(Text, nullable=True)

    staff:      Mapped[Staff]             = relationship(back_populates="attendance_logs")
    shift:      Mapped[Shift | None]      = relationship(back_populates="attendance")
    ot_request: Mapped[OTRequest | None]  = relationship(back_populates="attendance_log", uselist=False)


# ══════════════════════════════════════════════════════════════════════════════
#  9. OT REQUEST
# ══════════════════════════════════════════════════════════════════════════════

class OTRequest(Base, TimestampMixin):
    """
    สร้างอัตโนมัติเมื่อ clock_out > shift.end_time
    Admin อนุมัติ/ปฏิเสธผ่าน Telegram inline button หรือ manager UI
    """
    __tablename__ = "ot_requests"

    id:                Mapped[int]      = mapped_column(Integer, primary_key=True)
    staff_id:          Mapped[int]      = mapped_column(ForeignKey("staff.id"),          nullable=False, index=True)
    attendance_log_id: Mapped[int]      = mapped_column(ForeignKey("attendance_logs.id"), nullable=False, unique=True)
    ot_minutes:        Mapped[int]      = mapped_column(Integer,         nullable=False)
    ot_rate_baht:      Mapped[Decimal]  = mapped_column(Numeric(10, 2),  nullable=False)  # บาท/ชั่วโมง ณ เวลาที่ขอ
    ot_amount:         Mapped[Decimal]  = mapped_column(Numeric(10, 2),  nullable=False)  # ot_minutes/60 * ot_rate
    status:            Mapped[OTStatus] = mapped_column(SAEnum(OTStatus), default=OTStatus.PENDING, index=True)
    admin_note:        Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at:       Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    attendance_log: Mapped[AttendanceLog] = relationship(back_populates="ot_request")


# ══════════════════════════════════════════════════════════════════════════════
#  10. PAYROLL CYCLE + PAYROLL ENTRY
# ══════════════════════════════════════════════════════════════════════════════

class PayrollCycle(Base, TimestampMixin):
    """
    รอบการจ่ายเงินเดือน — คำนวณทุกวันที่ 1 และ 16 ของเดือน
    period_start / period_end กำหนดช่วงเวลาที่ครอบคลุม
    """
    __tablename__ = "payroll_cycles"

    id:           Mapped[int]           = mapped_column(Integer, primary_key=True)
    period_start: Mapped[date]          = mapped_column(Date, nullable=False, index=True)
    period_end:   Mapped[date]          = mapped_column(Date, nullable=False)
    run_at:       Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status:       Mapped[PayrollStatus] = mapped_column(SAEnum(PayrollStatus), default=PayrollStatus.DRAFT, index=True)
    note:         Mapped[str | None]    = mapped_column(Text, nullable=True)

    entries: Mapped[list[PayrollEntry]] = relationship(back_populates="cycle")


class PayrollEntry(Base, TimestampMixin):
    """
    1 row ต่อพนักงาน ต่อ cycle

    สูตร:
      gross    = base_wage + ot_total
      net_pay  = gross - late_fines - other_deductions
    """
    __tablename__ = "payroll_entries"

    id:       Mapped[int] = mapped_column(Integer, primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("payroll_cycles.id"), nullable=False, index=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff.id"),          nullable=False, index=True)

    # ── รายได้ ────────────────────────────────────────────────────────────────
    days_worked:      Mapped[int]     = mapped_column(Integer,         default=0)
    base_wage:        Mapped[Decimal] = mapped_column(Numeric(12, 2),  default=0)  # wage_rate × days (หรือ prorated)
    ot_minutes_total: Mapped[int]     = mapped_column(Integer,         default=0)
    ot_total:         Mapped[Decimal] = mapped_column(Numeric(12, 2),  default=0)

    # ── หักออก ────────────────────────────────────────────────────────────────
    late_fines:       Mapped[Decimal]    = mapped_column(Numeric(12, 2), default=0)
    other_deductions: Mapped[Decimal]    = mapped_column(Numeric(12, 2), default=0)
    deduction_note:   Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── รวม ───────────────────────────────────────────────────────────────────
    gross:       Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    net_pay:     Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)

    # ── การจ่าย ───────────────────────────────────────────────────────────────
    is_paid:     Mapped[bool]           = mapped_column(Boolean, default=False)
    paid_at:     Mapped[datetime | None]= mapped_column(DateTime(timezone=True), nullable=True)
    payment_ref: Mapped[str | None]     = mapped_column(String(120), nullable=True)

    cycle: Mapped[PayrollCycle] = relationship(back_populates="entries")
    staff: Mapped[Staff]        = relationship(back_populates="payroll_entries")

    def compute(self) -> None:
        """คำนวณ gross และ net_pay จาก fields ที่มีอยู่"""
        self.gross   = self.base_wage + self.ot_total
        self.net_pay = self.gross - self.late_fines - self.other_deductions

    def __repr__(self) -> str:
        return f"<PayrollEntry staff_id={self.staff_id} net_pay={self.net_pay} cycle_id={self.cycle_id}>"