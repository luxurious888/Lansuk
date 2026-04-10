from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import init_db
from app.routers import admin, attendance, orders, payroll, pos, reports, staff, telegram




async def _register_telegram_webhook():
    """ลงทะเบียน Telegram webhook อัตโนมัติตอน startup"""
    import httpx
    from app.config import settings

    token = settings.TELEGRAM_BOT_TOKEN
    secret = settings.TELEGRAM_WEBHOOK_SECRET

    if not token:
        print("[telegram] ไม่มี BOT_TOKEN — ข้าม webhook registration")
        return

    # ดึง URL จาก env var RAILWAY_PUBLIC_DOMAIN หรือใช้ default
    import os
    domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "")
    if not domain:
        # ลองใช้ RAILWAY_STATIC_URL
        domain = os.getenv("RAILWAY_STATIC_URL", "").replace("https://", "").replace("http://", "")
    if not domain:
        print("[telegram] ไม่เจอ RAILWAY_PUBLIC_DOMAIN — ข้าม webhook registration")
        print("[telegram] ตั้ง webhook ด้วยมือ: curl Telegram API setWebhook")
        return

    webhook_url = f"https://{domain}/api/telegram/webhook"
    api_url = f"https://api.telegram.org/bot{token}/setWebhook"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(api_url, json={
                "url": webhook_url,
                "secret_token": secret if secret != "change-me" else None,
                "allowed_updates": ["message", "callback_query"],
            })
            data = resp.json()
            if data.get("ok"):
                print(f"[telegram] ✅ Webhook registered: {webhook_url}")
            else:
                print(f"[telegram] ❌ Webhook failed: {data}")
    except Exception as e:
        print(f"[telegram] ❌ Error: {e}")


async def _run_migrations():
    """รัน ALTER TABLE ทุกครั้งที่ app start — idempotent"""
    import aiosqlite, re
    url = settings.DATABASE_URL
    # แปลง sqlite+aiosqlite:///path → path
    m = re.match(r"sqlite(?:\+aiosqlite)?:///+(.*)", url)
    db_file = m.group(1) if m else "lansook.db"
    # absolute path: //// → / prefix
    if url.startswith("sqlite+aiosqlite:////") or url.startswith("sqlite:////"):
        db_file = "/" + db_file.lstrip("/")
    import os
    parent = os.path.dirname(db_file)
    if parent:
        os.makedirs(parent, exist_ok=True)
    sqls = [
        "ALTER TABLE table_sessions ADD COLUMN customer_name TEXT",
        "ALTER TABLE orders ADD COLUMN discount_amt REAL DEFAULT 0",
        "ALTER TABLE orders ADD COLUMN vat_amt REAL DEFAULT 0",
        "ALTER TABLE orders ADD COLUMN subtotal REAL DEFAULT 0",
        "ALTER TABLE orders ADD COLUMN payment_method TEXT DEFAULT 'cash'",
        "ALTER TABLE orders ADD COLUMN paid_at DATETIME",
        "ALTER TABLE order_items ADD COLUMN cancelled_qty INTEGER DEFAULT 0",
        "ALTER TABLE order_items ADD COLUMN cancelled_at DATETIME",
        "ALTER TABLE order_items ADD COLUMN cancel_reason TEXT",
                "ALTER TABLE order_items ADD COLUMN cancelled_by TEXT",
        "ALTER TABLE table_sessions ADD COLUMN payment_status TEXT DEFAULT 'active'",
        "ALTER TABLE table_sessions ADD COLUMN pending_payment_method TEXT",
        "ALTER TABLE table_sessions ADD COLUMN pending_food_disc REAL DEFAULT 0",
        "ALTER TABLE table_sessions ADD COLUMN pending_total_disc REAL DEFAULT 0",
        "ALTER TABLE table_sessions ADD COLUMN pending_fixed_disc REAL DEFAULT 0",
    ]
    print(f"[migrate] db_file={db_file}")
    try:
        async with aiosqlite.connect(db_file) as conn:
            for sql in sqls:
                try:
                    await conn.execute(sql)
                    await conn.commit()
                    print(f"[migrate] OK: {sql[:70]}")
                except Exception as e:
                    msg = str(e).lower()
                    if "duplicate column" not in msg:
                        print(f"[migrate] FAIL: {sql[:60]} → {e}")
        print("[migrate] เสร็จ")
    except Exception as e:
        print(f"[migrate] ERROR: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # init tables (สร้างตารางใหม่ถ้ายังไม่มี)
    await init_db()
    # auto-migrate (เพิ่ม column ที่ขาด)
    await _run_migrations()
    await _register_telegram_webhook()
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(pos.router,        prefix="/api/pos",        tags=["POS"])
app.include_router(orders.router,     prefix="/api/orders",     tags=["Orders"])
app.include_router(admin.router,      prefix="/api/admin",      tags=["Admin"])
app.include_router(staff.router,      prefix="/api/staff",      tags=["Staff"])
app.include_router(attendance.router, prefix="/api/attendance", tags=["Attendance"])
app.include_router(payroll.router,    prefix="/api/payroll",    tags=["Payroll"])
app.include_router(reports.router,    prefix="/api/reports",    tags=["Reports"])
app.include_router(telegram.router,   prefix="/api/telegram",   tags=["Telegram"])


@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.APP_NAME}



@app.get("/debug/env")
async def debug_env():
    """Debug: ดู db path จริง"""
    import os
    from app.config import settings
    return {
        "settings_DATABASE_URL": settings.DATABASE_URL,
        "env_DATABASE_URL": os.getenv("DATABASE_URL", "NOT_SET"),
        "cwd": os.getcwd(),
        "data_dir_exists": os.path.exists("/data"),
        "data_dir_writable": os.access("/data", os.W_OK) if os.path.exists("/data") else False,
        "data_files": os.listdir("/data") if os.path.exists("/data") else [],
    }


# ── Static mount ท้ายสุด ─────────────────────────────────────────────────────
app.mount("/", StaticFiles(directory="app/static", html=True), name="static")