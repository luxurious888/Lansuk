from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import init_db
from app.routers import admin, attendance, orders, payroll, pos, reports, staff, telegram


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.DEBUG:
        await init_db()
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


# ── Static mount ท้ายสุด ─────────────────────────────────────────────────────
app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
