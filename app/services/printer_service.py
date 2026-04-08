"""
services/printer_service.py
พิมพ์ใบเสร็จภาษาไทยด้วย Pillow (render เป็นรูปแก้ปัญหา floating vowel)
ส่งไปยัง thermal printer ผ่าน ESC/POS LAN
"""
import io
import logging
import socket
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

from app.config import settings

logger = logging.getLogger(__name__)

FONT_PATH    = "fonts/THSarabunNew.ttf"
FONT_BOLD    = "fonts/THSarabunNew Bold.ttf"
RECEIPT_W    = 576   # dots — 80mm paper at 203dpi
LINE_H       = 36
PADDING      = 20


def _get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    try:
        path = FONT_BOLD if bold else FONT_PATH
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def render_receipt(session, orders: list) -> bytes:
    """
    สร้างรูปใบเสร็จ (PNG bytes) จาก session + orders
    ใช้ Pillow วาดทีละบรรทัดเพื่อแก้ปัญหา floating vowel ภาษาไทย
    """
    lines: list[tuple[str, int, bool, str]] = []  # (text, font_size, bold, align)
    font_h = 28
    font_s = 22

    # ── Header ────────────────────────────────────────────────────────────────
    lines.append(("ลานสุข",           36, True,  "center"))
    lines.append(("Lan Sook Restaurant", font_s, False, "center"))
    lines.append(("─" * 32,            font_s, False, "center"))
    lines.append((f"โต๊ะ: {session.table.table_number}   Session #{session.id}", font_h, False, "center"))
    lines.append((datetime.now().strftime("%d/%m/%Y  %H:%M"), font_s, False, "center"))
    lines.append(("─" * 32,            font_s, False, "center"))

    # ── Items ─────────────────────────────────────────────────────────────────
    total = 0
    for order in orders:
        for item in order.items:
            name  = item.menu_item_id   # TODO: join MenuItem.name
            price = float(item.line_total)
            total += price
            lines.append((f"{item.quantity}x  รายการ #{item.menu_item_id}", font_h, False, "left"))
            lines.append((f"  {'฿{:.2f}'.format(price)}", font_h, False, "right"))
            for mod in item.modifiers:
                lines.append((f"   + {mod.name}  ฿{float(mod.extra_price):.2f}", font_s, False, "left"))

    lines.append(("─" * 32, font_s, False, "center"))

    # ── Totals ────────────────────────────────────────────────────────────────
    order_obj = orders[-1] if orders else None
    if order_obj:
        vat      = float(order_obj.vat_amt or 0)
        discount = float(order_obj.discount_amt or 0)
        grand    = float(order_obj.total or total)
        if discount > 0:
            lines.append((f"ส่วนลด          ฿{discount:.2f}", font_h, False, "left"))
        lines.append((f"ภาษี 7%         ฿{vat:.2f}", font_h, False, "left"))
        lines.append((f"รวมทั้งหมด      ฿{grand:.2f}", font_h, True,  "left"))
        lines.append((f"ชำระด้วย: {order_obj.payment_method or '—'}", font_s, False, "left"))

    lines.append(("─" * 32, font_s, False, "center"))
    lines.append(("ขอบคุณที่ใช้บริการ 🙏",  font_h, True,  "center"))
    lines.append(("",         font_s, False, "center"))

    # ── Render ────────────────────────────────────────────────────────────────
    total_h = sum(LINE_H for _ in lines) + PADDING * 2
    img     = Image.new("RGB", (RECEIPT_W, total_h), color="white")
    draw    = ImageDraw.Draw(img)
    y       = PADDING

    for (text, fsize, bold, align) in lines:
        font = _get_font(fsize, bold)
        bbox = draw.textbbox((0, 0), text, font=font)
        tw   = bbox[2] - bbox[0]

        if align == "center":
            x = (RECEIPT_W - tw) // 2
        elif align == "right":
            x = RECEIPT_W - tw - PADDING
        else:
            x = PADDING

        draw.text((x, y), text, fill="black", font=font)
        y += LINE_H

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _send_to_printer(data: bytes) -> bool:
    """ส่ง raw bytes ไปยัง thermal printer ผ่าน LAN port 9100"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(5)
            s.connect((settings.PRINTER_IP, settings.PRINTER_PORT))
            s.sendall(data)
        return True
    except Exception as e:
        logger.error(f"Printer error: {e}")
        return False


async def print_receipt(session, orders: list) -> bool:
    """Render รูปใบเสร็จ แล้วส่งพิมพ์"""
    try:
        from escpos.printer import Network
        from escpos.capabilities import ESCPOS_CAPABILITIES

        png_bytes = render_receipt(session, orders)

        # ESC/POS: init → print image → cut
        p = Network(settings.PRINTER_IP, settings.PRINTER_PORT)
        p.image(Image.open(io.BytesIO(png_bytes)))
        p.cut()
        p.close()
        return True
    except Exception as e:
        logger.error(f"print_receipt error: {e}")
        return False


async def print_pass_slip(order_id: int) -> bool:
    """
    พิมพ์ slip เล็กที่ pass station เมื่อทุก item พร้อม
    (ใช้ ESC/POS text mode โดยตรง ไม่ต้อง render รูป)
    """
    try:
        from escpos.printer import Network
        p = Network(settings.PRINTER_IP, settings.PRINTER_PORT)
        p.set(align="center", bold=True)
        p.text(f"ORDER #{order_id} READY\n")
        p.cut()
        p.close()
        return True
    except Exception as e:
        logger.error(f"print_pass_slip error: {e}")
        return False