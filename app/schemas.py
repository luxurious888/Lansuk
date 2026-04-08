"""
schemas.py — ลานสุข POS
Pydantic v2 schemas สำหรับ request / response ทุก router

Sections:
  1.  Common
  2.  Staff
  3.  Zone & Table
  4.  Menu
  5.  Order
  6.  Member & Promotion
  7.  Attendance & Shift
  8.  Payroll
  9.  Telegram / Bot
  10. Reports
"""
from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import (
    AttendanceStatus, KDSRoute, OTStatus, OrderStatus,
    PaymentMethod, PayrollStatus, ShiftType,
    StaffRole, StaffStatus, TableStatus, WageType,
)


# ══════════════════════════════════════════════════════════════════════════════
#  1. COMMON
# ══════════════════════════════════════════════════════════════════════════════

class OrmBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class MessageResponse(BaseModel):
    message: str


class PaginatedResponse(BaseModel):
    total: int
    page:  int
    size:  int
    items: list[Any]


# ══════════════════════════════════════════════════════════════════════════════
#  2. STAFF
# ══════════════════════════════════════════════════════════════════════════════

class StaffCreate(BaseModel):
    full_name:  str        = Field(..., min_length=2, max_length=120)
    nickname:   str        = Field(..., min_length=1, max_length=60)
    phone:      str        = Field(..., min_length=9, max_length=20)
    address:    str | None = None
    role:       StaffRole  = StaffRole.WAITER
    wage_type:  WageType   = WageType.DAILY
    wage_rate:  Decimal    = Field(..., ge=0)
    start_date: date | None = None


class StaffUpdate(BaseModel):
    full_name:  str | None     = None
    nickname:   str | None     = None
    phone:      str | None     = None
    address:    str | None     = None
    role:       StaffRole | None = None
    wage_type:  WageType | None  = None
    wage_rate:  Decimal | None   = None
    status:     StaffStatus | None = None


class LatePolicyUpdate(BaseModel):
    free_late_per_month: int   = Field(3, ge=0)
    fine_per_minute:     Decimal = Field(Decimal("5"), ge=0)
    grace_minutes:       int   = Field(5, ge=0)


class StaffOut(OrmBase):
    id:               int
    full_name:        str
    nickname:         str
    phone:            str
    role:             StaffRole
    status:           StaffStatus
    wage_type:        WageType
    wage_rate:        Decimal
    start_date:       date | None
    telegram_chat_id: int | None
    created_at:       datetime


class StaffDetail(StaffOut):
    address:     str | None
    national_id: str | None   # ส่งเฉพาะ admin
    late_policy: LatePolicyOut | None


class LatePolicyOut(OrmBase):
    free_late_per_month: int
    fine_per_minute:     Decimal
    grace_minutes:       int


# ══════════════════════════════════════════════════════════════════════════════
#  3. ZONE & TABLE
# ══════════════════════════════════════════════════════════════════════════════

class ZoneCreate(BaseModel):
    name:  str = Field(..., min_length=1, max_length=60)
    color: str = Field("#4CAF50", pattern=r"^#[0-9A-Fa-f]{6}$")


class ZoneOut(OrmBase):
    id:    int
    name:  str
    color: str


class ZoneAssignRequest(BaseModel):
    zone_id:       int
    staff_id:      int
    assigned_date: date


class ZoneAssignOut(OrmBase):
    id:            int
    zone_id:       int
    staff_id:      int
    assigned_date: date


class TableOut(OrmBase):
    id:           int
    table_number: int
    col:          int
    row:          int
    capacity:     int
    status:       TableStatus
    zone_id:      int | None


class TableStatusUpdate(BaseModel):
    status: TableStatus


class TableSessionOut(OrmBase):
    id:          int
    table_id:    int
    qr_token:    str
    guest_count: int
    opened_at:   datetime
    closed_at:   datetime | None
    is_paid:     bool


class OpenTableRequest(BaseModel):
    table_id:    int
    guest_count: int = Field(1, ge=1)


# ══════════════════════════════════════════════════════════════════════════════
#  4. MENU
# ══════════════════════════════════════════════════════════════════════════════

class CategoryCreate(BaseModel):
    name:       str        = Field(..., max_length=80)
    name_en:    str | None = None
    sort_order: int        = 0


class CategoryOut(OrmBase):
    id:         int
    name:       str
    name_en:    str | None
    sort_order: int


class ModifierOptionCreate(BaseModel):
    name:        str     = Field(..., max_length=80)
    extra_price: Decimal = Field(Decimal("0"))


class ModifierGroupCreate(BaseModel):
    name:       str                         = Field(..., max_length=80)
    required:   bool                        = False
    min_select: int                         = Field(0, ge=0)
    max_select: int                         = Field(1, ge=1)
    options:    list[ModifierOptionCreate]  = []


class MenuItemCreate(BaseModel):
    category_id:     int
    name:            str        = Field(..., max_length=120)
    name_en:         str | None = None
    description:     str | None = None
    price:           Decimal    = Field(..., ge=0)
    image_url:       str | None = None
    kds_route:       KDSRoute   = KDSRoute.KITCHEN
    track_stock:     bool       = False
    stock_qty:       int        = 0
    modifier_groups: list[ModifierGroupCreate] = []


class MenuItemUpdate(BaseModel):
    name:        str | None     = None
    price:       Decimal | None = None
    kds_route:   KDSRoute | None = None
    is_sold_out: bool | None    = None
    stock_qty:   int | None     = None


class ModifierOptionOut(OrmBase):
    id:          int
    name:        str
    extra_price: Decimal
    is_active:   bool


class ModifierGroupOut(OrmBase):
    id:         int
    name:       str
    required:   bool
    min_select: int
    max_select: int
    options:    list[ModifierOptionOut]


class MenuItemOut(OrmBase):
    id:              int
    category_id:     int
    name:            str
    name_en:         str | None
    description:     str | None
    price:           Decimal
    image_url:       str | None
    kds_route:       KDSRoute
    is_sold_out:     bool
    stock_qty:       int
    modifier_groups: list[ModifierGroupOut]


# ══════════════════════════════════════════════════════════════════════════════
#  5. ORDER
# ══════════════════════════════════════════════════════════════════════════════

class OrderItemModifierIn(BaseModel):
    option_id: int


class OrderItemIn(BaseModel):
    menu_item_id: int
    quantity:     int    = Field(1, ge=1)
    note:         str | None = None
    modifiers:    list[OrderItemModifierIn] = []


class PlaceOrderRequest(BaseModel):
    """Request body จากหน้า customer (ผ่าน QR)"""
    session_token: str                  # JWT จาก QR code
    items:         list[OrderItemIn]


class CheckoutRequest(BaseModel):
    session_id:     int
    payment_method: PaymentMethod
    member_id:      int | None = None
    promotion_code: str | None = None


class OrderItemModifierOut(OrmBase):
    name:        str
    extra_price: Decimal


class OrderItemOut(OrmBase):
    id:          int
    menu_item_id: int
    quantity:    int
    unit_price:  Decimal
    note:        str | None
    kds_route:   str
    status:      OrderStatus
    line_total:  Decimal
    modifiers:   list[OrderItemModifierOut]


class OrderOut(OrmBase):
    id:             int
    session_id:     int
    status:         OrderStatus
    subtotal:       Decimal | None
    discount_amt:   Decimal
    vat_amt:        Decimal
    total:          Decimal | None
    payment_method: PaymentMethod | None
    paid_at:        datetime | None
    items:          list[OrderItemOut]


class KDSItemUpdate(BaseModel):
    """พนักงานกด Ready/Served บน KDS"""
    order_item_id: int
    status:        OrderStatus   # READY หรือ SERVED


# ══════════════════════════════════════════════════════════════════════════════
#  6. MEMBER & PROMOTION
# ══════════════════════════════════════════════════════════════════════════════

class MemberCreate(BaseModel):
    name:  str = Field(..., max_length=120)
    phone: str = Field(..., min_length=9, max_length=20)


class MemberOut(OrmBase):
    id:     int
    name:   str
    phone:  str
    points: Decimal


class PromotionCreate(BaseModel):
    name:         str        = Field(..., max_length=120)
    code:         str | None = Field(None, max_length=30)
    discount_pct: Decimal    = Field(Decimal("0"), ge=0, le=100)
    discount_amt: Decimal    = Field(Decimal("0"), ge=0)
    valid_from:   date
    valid_until:  date

    @field_validator("valid_until")
    @classmethod
    def end_after_start(cls, v: date, info: Any) -> date:
        if "valid_from" in info.data and v < info.data["valid_from"]:
            raise ValueError("valid_until ต้องมาหลัง valid_from")
        return v


class PromotionOut(OrmBase):
    id:           int
    name:         str
    code:         str | None
    discount_pct: Decimal
    discount_amt: Decimal
    valid_from:   date
    valid_until:  date
    is_active:    bool


# ══════════════════════════════════════════════════════════════════════════════
#  7. ATTENDANCE & SHIFT
# ══════════════════════════════════════════════════════════════════════════════

class ShiftCreate(BaseModel):
    staff_id:   int
    shift_date: date
    shift_type: ShiftType
    start_time: time
    end_time:   time


class ShiftOut(OrmBase):
    id:         int
    staff_id:   int
    shift_date: date
    shift_type: ShiftType
    start_time: time
    end_time:   time


class ClockInRequest(BaseModel):
    """ส่งจาก Telegram service หลัง validate selfie + GPS"""
    staff_id:  int
    shift_id:  int | None
    gps_lat:   float
    gps_lon:   float
    gps_valid: bool
    selfie_path: str


class ClockOutRequest(BaseModel):
    staff_id:    int
    selfie_path: str


class AttendanceOut(OrmBase):
    id:              int
    staff_id:        int
    log_date:        date
    clock_in_at:     datetime | None
    clock_out_at:    datetime | None
    late_minutes:    int
    status:          AttendanceStatus
    late_fine_baht:  Decimal
    gps_valid_in:    bool


# ══════════════════════════════════════════════════════════════════════════════
#  8. PAYROLL
# ══════════════════════════════════════════════════════════════════════════════

class OTRequestOut(OrmBase):
    id:           int
    staff_id:     int
    ot_minutes:   int
    ot_rate_baht: Decimal
    ot_amount:    Decimal
    status:       OTStatus


class OTResolveRequest(BaseModel):
    status:     OTStatus   # APPROVED หรือ REJECTED
    admin_note: str | None = None


class PayrollCycleOut(OrmBase):
    id:           int
    period_start: date
    period_end:   date
    status:       PayrollStatus
    run_at:       datetime | None


class PayrollEntryOut(OrmBase):
    id:               int
    staff_id:         int
    days_worked:      int
    base_wage:        Decimal
    ot_total:         Decimal
    late_fines:       Decimal
    other_deductions: Decimal
    gross:            Decimal
    net_pay:          Decimal
    is_paid:          bool
    paid_at:          datetime | None


class PayrollEntryAdjust(BaseModel):
    """Admin ปรับยอดด้วยมือก่อน approve"""
    other_deductions: Decimal | None = None
    deduction_note:   str | None     = None


# ══════════════════════════════════════════════════════════════════════════════
#  9. TELEGRAM / BOT
# ══════════════════════════════════════════════════════════════════════════════

class TelegramWebhookUpdate(BaseModel):
    """Raw Telegram update — pass-through เพื่อ type hint เท่านั้น"""
    update_id: int
    message:   dict | None          = None
    callback_query: dict | None     = None


class BotApplyForm(BaseModel):
    """ข้อมูลจาก /apply FSM flow"""
    full_name: str
    nickname:  str
    phone:     str
    address:   str
    role:      StaffRole


# ══════════════════════════════════════════════════════════════════════════════
#  10. REPORTS
# ══════════════════════════════════════════════════════════════════════════════

class SalesSummaryRequest(BaseModel):
    date_from: date
    date_to:   date


class DailySalesOut(BaseModel):
    sale_date:    date
    order_count:  int
    total_revenue: Decimal
    avg_per_order: Decimal


class TopItemOut(BaseModel):
    menu_item_id:  int
    name:          str
    quantity_sold: int
    total_revenue: Decimal


class SalesSummaryOut(BaseModel):
    date_from:     date
    date_to:       date
    total_revenue: Decimal
    order_count:   int
    daily:         list[DailySalesOut]
    top_items:     list[TopItemOut]


# ── Forward refs ──────────────────────────────────────────────────────────────
StaffDetail.model_rebuild()