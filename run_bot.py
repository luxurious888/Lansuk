import asyncio, httpx, logging
from app.config import settings
from app.database import AsyncSessionLocal
from app.services.telegram_fsm import dispatch_update

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    token  = settings.TELEGRAM_BOT_TOKEN
    offset = 0
    logger.info("Bot polling started...")

    async with httpx.AsyncClient() as client:
        await client.post(f"https://api.telegram.org/bot{token}/deleteWebhook")
        logger.info("Webhook deleted, switching to polling")

    while True:
        try:
            async with httpx.AsyncClient(timeout=35) as client:
                r = await client.get(
                    f"https://api.telegram.org/bot{token}/getUpdates",
                    params={"offset": offset, "timeout": 30, "limit": 10}
                )
                data = r.json()

            for update in data.get("result", []):
                offset = update["update_id"] + 1
                logger.info(f"Got update: {update.get('message',{}).get('text','')}")
                async with AsyncSessionLocal() as db:
                    try:
                        logger.info(f"Dispatching: {update}"); await dispatch_update(update, db); logger.info("Dispatch done")
                        await db.commit()
                    except Exception as e:
                        await db.rollback()
                        logger.error(f"Error: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"Polling error: {e}")
            await asyncio.sleep(5)

asyncio.run(main())
