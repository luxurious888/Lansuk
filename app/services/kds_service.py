"""
services/kds_service.py
Push order items ไป Firebase Realtime DB แยก kitchen / bar node
KDS tablet subscribe ผ่าน Firebase SDK (Realtime listener)
"""
import logging

logger = logging.getLogger(__name__)

# Firebase path structure:
#   /kds/kitchen/{order_item_id} → item data
#   /kds/bar/{order_item_id}     → item data


async def push_order(order) -> None:
    """
    ส่ง order items ไป Firebase KDS nodes
    เรียกหลัง place_order สำเร็จ
    """
    try:
        import firebase_admin
        from firebase_admin import db as firebase_db

        for item in order.items:
            item_data = {
                "order_item_id": item.id,
                "order_id":      item.order_id,
                "menu_item_id":  item.menu_item_id,
                "quantity":      item.quantity,
                "note":          item.note or "",
                "status":        item.status,
                "modifiers": [
                    {"name": m.name, "extra_price": float(m.extra_price)}
                    for m in item.modifiers
                ],
            }

            routes = (
                ["kitchen", "bar"]
                if item.kds_route == "both"
                else [item.kds_route]
            )
            for route in routes:
                firebase_db.reference(f"/kds/{route}/{item.id}").set(item_data)

    except Exception as e:
        logger.error(f"Firebase KDS push error: {e}")


async def update_item_status(order_item_id: int, route: str, status: str) -> None:
    """อัปเดตสถานะ item บน Firebase (เรียกจาก KDS tablet)"""
    try:
        from firebase_admin import db as firebase_db
        firebase_db.reference(f"/kds/{route}/{order_item_id}/status").set(status)
    except Exception as e:
        logger.error(f"Firebase status update error: {e}")


async def clear_item(order_item_id: int) -> None:
    """ลบ item ออกจาก KDS หลัง SERVED"""
    try:
        from firebase_admin import db as firebase_db
        for route in ["kitchen", "bar"]:
            firebase_db.reference(f"/kds/{route}/{order_item_id}").delete()
    except Exception as e:
        logger.error(f"Firebase clear error: {e}")