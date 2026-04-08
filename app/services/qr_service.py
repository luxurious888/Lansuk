"""services/qr_service.py — สร้างและตรวจ JWT QR token"""
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.config import settings

ALGORITHM = "HS256"


def create_qr_token(table_id: int) -> str:
    """สร้าง signed JWT สำหรับ QR code ของโต๊ะ"""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.QR_EXPIRE_MINUTES)
    payload = {
        "table_id": table_id,
        "exp":      expire,
        "type":     "qr",
    }
    return jwt.encode(payload, settings.QR_SECRET_KEY, algorithm=ALGORITHM)


def verify_qr_token(token: str) -> dict | None:
    """คืน payload ถ้า token valid, คืน None ถ้า expired/invalid"""
    try:
        payload = jwt.decode(token, settings.QR_SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "qr":
            return None
        return payload
    except JWTError:
        return None