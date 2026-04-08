"""
routers/telegram.py
Webhook receiver เดียว — ทุก update จาก Telegram มาที่นี่
ตรวจสิทธิ์ด้วย chat_id → dispatch ไป StaffHandler หรือ AdminHandler
"""
from fastapi import APIRouter, BackgroundTasks, Request

from app.database import AsyncSessionLocal

router = APIRouter()


@router.post("/webhook")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Telegram ต้องการ 200 OK ภายใน 10 วินาที
    งานหนัก (DB, photo download, print) ทำใน background task
    """
    update = await request.json()
    background_tasks.add_task(_dispatch, update)
    return {"ok": True}


async def _dispatch(update: dict):
    async with AsyncSessionLocal() as db:
        try:
            from app.services.telegram_fsm import dispatch_update
            await dispatch_update(update, db)
            await db.commit()
        except Exception as e:
            await db.rollback()
            # Log แต่ไม่ raise — ไม่งั้น Telegram retry ไม่หยุด
            import logging
            logging.getLogger(__name__).error(f"Telegram dispatch error: {e}", exc_info=True)