#!/usr/bin/env python3
"""
🤖 Gold Price Calculator Bot — Telegram Bot
محاسبه‌گر قیمت طلا با دکمه‌های预设
"""

from __future__ import annotations

import os
import re
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from decimal import Decimal, InvalidOperation
from httpx import Client, ConnectTimeout, ReadTimeout

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, CallbackContext
)

# ─── Config ──────────────────────────────────────────────────────────
TOKEN = os.environ.get("BOT_TOKEN", "8738042848:AAHplME4R3zlV2J9fpgVYI3qAY1iAeVKswE")

# ─── Logging ─────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── Conversation States ─────────────────────────────────────────────
(GOLD_PRICE, WEIGHT, MANUF_FEE, SELLER_PROFIT, VAT) = range(5)

# ─── Persian digit helpers ───────────────────────────────────────────
PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
PERSIAN_MAP = {"0":"۰","1":"۱","2":"۲","3":"۳","4":"۴","5":"۵","6":"۶","7":"۷","8":"۸","9":"۹"}

def clean_number(text: str) -> str:
    text = text.translate(PERSIAN_DIGITS)
    return text.replace(",", "").replace("٬", "").strip()

def parse_decimal(text: str) -> Decimal | None:
    try:
        val = Decimal(clean_number(text))
        return val if val >= 0 else None
    except (InvalidOperation, ValueError):
        return None

def fmt(n: Decimal) -> str:
    """Format number with Persian digits and thousands separator."""
    s = str(n.quantize(Decimal("1")) if n == n.to_integral() else n.normalize())
    int_part, _, dec_part = s.partition(".")
    # Add commas
    result = []
    for i, ch in enumerate(reversed(int_part)):
        if i and i % 3 == 0:
            result.append("٬")
        result.append(ch)
    int_part = "".join(reversed(result))
    for e, p in PERSIAN_MAP.items():
        int_part = int_part.replace(e, p)
    if dec_part:
        for e, p in PERSIAN_MAP.items():
            dec_part = dec_part.replace(e, p)
        return f"{int_part}/{dec_part}"
    return int_part

# ─── Calculator ──────────────────────────────────────────────────────
def calc_gold(gp: Decimal, w: Decimal, mf: Decimal, sp: Decimal, vat: Decimal) -> dict:
    gold_val   = gp * w
    manuf_amt  = gold_val * mf / Decimal("100")
    profit_amt = (gold_val + manuf_amt) * sp / Decimal("100")
    vat_amt    = (gold_val + manuf_amt + profit_amt) * vat / Decimal("100")
    total      = gold_val + manuf_amt + profit_amt + vat_amt
    return {
        "gold_val": gold_val, "manuf_amt": manuf_amt,
        "profit_amt": profit_amt, "vat_amt": vat_amt,
        "total": total, "per_gram": total / w if w else Decimal("0"),
        "mf_pct": mf, "sp_pct": sp, "vat_pct": vat,
    }

def build_result(r: dict) -> str:
    return (
        "━━━━━━━━━━━━━━━━━━\n"
        "💰 *محاسبه‌گر قیمت طلا*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"📌 قیمت خالص طلا:\n`{fmt(r['gold_val'])}` تومان\n\n"
        f"🔧 اجرت ساخت ({fmt(r['mf_pct'])}%):\n`{fmt(r['manuf_amt'])}` تومان\n\n"
        f"📈 سود فروشنده ({fmt(r['sp_pct'])}%):\n`{fmt(r['profit_amt'])}` تومان\n\n"
        f"🧾 مالیات بر ارزش افزوده ({fmt(r['vat_pct'])}%):\n`{fmt(r['vat_amt'])}` تومان\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🟡 *قیمت نهایی:*\n`{fmt(r['total'])}` تومان\n\n"
        f"📊 میانگین هر گرم:\n`{fmt(r['per_gram'])}` تومان"
    )

# ─── Price Fetching ──────────────────────────────────────────────────
CACHE: dict = {"tala": None, "time": 0}
import time as _time

def fetch_gold_prices() -> tuple:
    """Fetch 18K gold price from tala.ir.
    Returns (tala_price, None) in Tomans, or (None, None) on failure."""
    now = _time.time()
    if now - CACHE["time"] < 120 and CACHE["tala"] is not None:
        return CACHE["tala"]

    tala_price = None

    try:
        with Client(verify=False, timeout=8) as c:
            r = c.get("https://www.tala.ir/price/18k", headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            # Find the 18K gold selling price (after "عیار 750 یا 18")
            m = re.search(
                r'عیار\s*750\s*یا\s*18.*?<h5[^>]*>([0-9,]+)',
                r.text,
                re.DOTALL
            )
            if m:
                tala_price = int(m.group(1).replace(",", ""))
    except Exception as e:
        logger.warning(f"tala.ir fetch failed: {e}")

    CACHE["tala"] = tala_price
    CACHE["time"] = now
    return tala_price

# ─── Inline Keyboards ────────────────────────────────────────────────
def btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=data)

def price_kb() -> InlineKeyboardMarkup:
    tala = fetch_gold_prices()

    buttons = []
    if tala:
        buttons.append([btn(f"🟡 قیمت لحظه‌ای ({fmt(Decimal(str(tala)))})", f"gp:{tala}")])

    buttons.append([btn("✏️ وارد کردن دستی", "gp:custom")])
    return InlineKeyboardMarkup(buttons)

def weight_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn("۱ گرم", "w:1"), btn("۲ گرم", "w:2"), btn("۵ گرم", "w:5")],
        [btn("۱۰ گرم", "w:10"), btn("۱۵ گرم", "w:15"), btn("۲۰ گرم", "w:20")],
        [btn("✏️ خودم می‌نویسم", "w:custom")],
    ])

def manuf_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn("۰٪ (بدون اجرت)", "mf:0"), btn("۵٪", "mf:5"), btn("۱۰٪", "mf:10")],
        [btn("۱۵٪", "mf:15"), btn("۲۰٪", "mf:20"), btn("۲۵٪", "mf:25")],
        [btn("✏️ خودم می‌نویسم", "mf:custom")],
    ])

def profit_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn("۵٪", "sp:5"), btn("۷٪", "sp:7"), btn("۱۰٪", "sp:10")],
        [btn("۱۵٪", "sp:15"), btn("✏️ خودم می‌نویسم", "sp:custom")],
    ])

def vat_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn("۹٪", "vat:9"), btn("۱۰٪", "vat:10"), btn("✏️ خودم می‌نویسم", "vat:custom")],
    ])

def main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton("📊 محاسبه جدید"), KeyboardButton("❓ راهنما")]],
        resize_keyboard=True
    )

# ─── Shared button rows for the result ───────────────────────────────
def result_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [btn("🔄 محاسبه جدید", "new_calc")],
    ])

# ─── Handler: store & advance ────────────────────────────────────────
def store_and_advance(context: CallbackContext, key: str, val: Decimal) -> str:
    context.user_data[key] = val
    return "✅"  # signal success

# ─── Entry ───────────────────────────────────────────────────────────
async def start(update: Update, context: CallbackContext) -> int:
    user = update.effective_user
    await update.message.reply_text(
        f"سلام {user.first_name} جان 🖐️\n\n"
        "از حساب‌کتاب طلایی که می‌خری سَر درنمیاری؟ 🤯\n"
        "نگران نباش، من اینجام تا کارو برات راحت کنم! 🪙\n\n"
        "با چند تا دکمه ساده، **قیمت نهایی طلا** رو با احتساب اجرت ساخت، سود فروشنده و مالیات برات حساب می‌کنم.\n\n"
        "همونقد که کیبوردتو می‌بندی، جیبت باز می‌شه 😄\n\n"
        "👇 از دکمه‌های زیر استفاده کن یا عدد رو دستی وارد کن:",
        reply_markup=main_kb(),
        parse_mode="Markdown"
    )
    return await ask_price(update, context)

async def ask_price(update: Update, context: CallbackContext) -> int:
    msg = update.message or update.callback_query.message
    await msg.reply_text(
        "💰 *قیمت هر گرم طلای ۱۸ عیار* رو وارد کن:\n\n"
        "قیمت لحظه‌ای از سایت‌های زیر دریافت شد. یکی رو انتخاب کن یا دستی وارد کن:",
        reply_markup=price_kb(),
        parse_mode="Markdown"
    )
    return GOLD_PRICE

# ─── Gold Price ──────────────────────────────────────────────────────
async def gold_price_handler(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text == "📊 محاسبه جدید":
        return await reset_all(update, context)
    if text == "❓ راهنما":
        await help_cmd(update, context)
        return GOLD_PRICE

    val = parse_decimal(text)
    if val is None or val <= 0:
        await update.message.reply_text(
            "⚠️ لطفاً یه عدد معتبر وارد کن.\n"
            "میتونی از دکمه‌های بالا استفاده کنی یا دستی بنویسی.",
            reply_markup=price_kb(),
            parse_mode="Markdown"
        )
        return GOLD_PRICE

    context.user_data["gold_price"] = val
    return await ask_weight(update, context)

async def gold_price_cb(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "gp:custom":
        await query.edit_message_text(
            "💰 لطفاً *قیمت هر گرم* رو به صورت دستی تایپ کن:\n\n"
            "فقط عدد رو بفرست، مثل:\n"
            "`۱۸۸۵۰۰۰۰` یا `18900000`",
            reply_markup=None,
            parse_mode="Markdown"
        )
        return GOLD_PRICE

    val = Decimal(data.split(":")[1])
    context.user_data["gold_price"] = val
    await query.edit_message_text(
        f"✅ قیمت: `{fmt(val)}` تومان",
        parse_mode="Markdown"
    )
    return await ask_weight(update, context)

async def ask_weight(update: Update, context: CallbackContext) -> int:
    msg = update.message or update.callback_query.message
    await msg.reply_text(
        "⚖️ حالا *وزن طلا* رو به گرم وارد کن:\n\n"
        "مثال: `۱۲.۳۴۵` یا `12.345`",
        reply_markup=weight_kb(),
        parse_mode="Markdown"
    )
    return WEIGHT

# ─── Weight ──────────────────────────────────────────────────────────
async def weight_handler(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text == "📊 محاسبه جدید":
        return await reset_all(update, context)
    if text == "❓ راهنما":
        await help_cmd(update, context)
        return WEIGHT

    val = parse_decimal(text)
    if val is None or val <= 0:
        await update.message.reply_text(
            "⚠️ لطفاً وزن معتبر وارد کن.\nمثال: `۱۲.۳۴۵` یا `12.345`",
            reply_markup=weight_kb(),
            parse_mode="Markdown"
        )
        return WEIGHT

    context.user_data["weight"] = val
    return await ask_manuf(update, context)

async def weight_cb(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "w:custom":
        await query.edit_message_text(
            "⚖️ لطفاً *وزن* رو به صورت دستی تایپ کن:\n\n"
            "مثال: `۱۲.۳۴۵` یا `12.345`",
            reply_markup=None,
            parse_mode="Markdown"
        )
        return WEIGHT
    val = Decimal(data.split(":")[1])
    context.user_data["weight"] = val
    await query.edit_message_text(
        f"✅ وزن: `{fmt(val)}` گرم",
        parse_mode="Markdown"
    )
    return await ask_manuf(update, context)

async def ask_manuf(update: Update, context: CallbackContext) -> int:
    msg = update.message or update.callback_query.message
    await msg.reply_text(
        "🔧 *درصد اجرت ساخت* رو وارد کن:\n\n"
        "اگه اجرت نداره، ۰ رو انتخاب کن.",
        reply_markup=manuf_kb(),
        parse_mode="Markdown"
    )
    return MANUF_FEE

# ─── Manufacturing Fee ───────────────────────────────────────────────
async def manuf_handler(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text == "📊 محاسبه جدید":
        return await reset_all(update, context)
    if text == "❓ راهنما":
        await help_cmd(update, context)
        return MANUF_FEE

    val = parse_decimal(text)
    if val is None:
        await update.message.reply_text(
            "⚠️ لطفاً یه درصد معتبر وارد کن.\nمثال: `۱۵` یا `0`",
            reply_markup=manuf_kb(),
            parse_mode="Markdown"
        )
        return MANUF_FEE

    context.user_data["manuf_fee"] = val
    return await ask_profit(update, context)

async def manuf_cb(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "mf:custom":
        await query.edit_message_text(
            "🔧 لطفاً *درصد اجرت ساخت* رو تایپ کن:\n\n"
            "مثال: `۱۵` یا `0`",
            reply_markup=None,
            parse_mode="Markdown"
        )
        return MANUF_FEE
    val = Decimal(data.split(":")[1])
    context.user_data["manuf_fee"] = val
    await query.edit_message_text(
        f"✅ اجرت ساخت: `{fmt(val)}`٪",
        parse_mode="Markdown"
    )
    return await ask_profit(update, context)

async def ask_profit(update: Update, context: CallbackContext) -> int:
    msg = update.message or update.callback_query.message
    await msg.reply_text(
        "📈 *درصد سود فروشنده* رو وارد کن:\n\n"
        "پیشنهاد: ۷٪",
        reply_markup=profit_kb(),
        parse_mode="Markdown"
    )
    return SELLER_PROFIT

# ─── Seller Profit ───────────────────────────────────────────────────
async def profit_handler(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text == "📊 محاسبه جدید":
        return await reset_all(update, context)
    if text == "❓ راهنما":
        await help_cmd(update, context)
        return SELLER_PROFIT

    val = parse_decimal(text)
    if val is None:
        await update.message.reply_text(
            "⚠️ لطفاً یه درصد معتبر وارد کن.\nمثال: `۷`",
            reply_markup=profit_kb(),
            parse_mode="Markdown"
        )
        return SELLER_PROFIT

    context.user_data["seller_profit"] = val
    return await ask_vat(update, context)

async def profit_cb(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "sp:custom":
        await query.edit_message_text(
            "📈 لطفاً *درصد سود فروشنده* رو تایپ کن:\n\n"
            "مثال: `۷`",
            reply_markup=None,
            parse_mode="Markdown"
        )
        return SELLER_PROFIT
    val = Decimal(data.split(":")[1])
    context.user_data["seller_profit"] = val
    await query.edit_message_text(
        f"✅ سود فروشنده: `{fmt(val)}`٪",
        parse_mode="Markdown"
    )
    return await ask_vat(update, context)

async def ask_vat(update: Update, context: CallbackContext) -> int:
    msg = update.message or update.callback_query.message
    await msg.reply_text(
        "🧾 *درصد مالیات بر ارزش افزوده* رو وارد کن:\n\n"
        "پیشنهاد: ۱۰٪",
        reply_markup=vat_kb(),
        parse_mode="Markdown"
    )
    return VAT

# ─── VAT ─────────────────────────────────────────────────────────────
async def vat_handler(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text == "📊 محاسبه جدید":
        return await reset_all(update, context)
    if text == "❓ راهنما":
        await help_cmd(update, context)
        return VAT

    val = parse_decimal(text)
    if val is None:
        await update.message.reply_text(
            "⚠️ لطفاً یه درصد معتبر وارد کن.\nمثال: `۱۰`",
            reply_markup=vat_kb(),
            parse_mode="Markdown"
        )
        return VAT

    context.user_data["vat"] = val
    return await show_result(update, context)

async def vat_cb(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "vat:custom":
        await query.edit_message_text(
            "🧾 لطفاً *درصد مالیات* رو تایپ کن:\n\n"
            "مثال: `۱۰`",
            reply_markup=None,
            parse_mode="Markdown"
        )
        return VAT
    val = Decimal(data.split(":")[1])
    context.user_data["vat"] = val
    await query.edit_message_text(
        f"✅ مالیات: `{fmt(val)}`٪",
        parse_mode="Markdown"
    )
    return await show_result(update, context)

# ─── Show Result ─────────────────────────────────────────────────────
async def show_result(update: Update, context: CallbackContext) -> int:
    data = context.user_data
    try:
        r = calc_gold(
            data["gold_price"], data["weight"],
            data["manuf_fee"], data["seller_profit"], data["vat"]
        )
    except Exception as e:
        logger.error(f"Calc error: {e}")
        msg = update.message or update.callback_query.message
        await msg.reply_text("⚠️ خطایی رخ داد. لطفاً دوباره تلاش کن.")
        return ConversationHandler.END

    msg = update.message or update.callback_query.message
    await msg.reply_text(
        build_result(r),
        parse_mode="Markdown",
        reply_markup=main_kb()
    )

    await msg.reply_text(
        "👇 برای محاسبه جدید کلیک کن:",
        reply_markup=result_kb()
    )
    return ConversationHandler.END

# ─── New Calculation (from inline button) ────────────────────────────
async def new_calc_cb(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text("🔄 شروع محاسبه جدید...")
    return await ask_price(update, context)

# ─── Reset from message ──────────────────────────────────────────────
async def reset_all(update: Update, context: CallbackContext) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "🔄 محاسبه جدید\n\n"
        "👇 از دکمه‌ها استفاده کن یا دستی وارد کن:",
        reply_markup=price_kb(),
        parse_mode="Markdown"
    )
    return GOLD_PRICE

# ─── Help ────────────────────────────────────────────────────────────
async def help_cmd(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text(
        "🤖 *راهنمای استفاده*\n\n"
        "۱. قیمت هر گرم طلای ۱۸ عیار رو وارد کن\n"
        "۲. وزن طلا رو به گرم وارد کن\n"
        "۳. درصد اجرت ساخت رو انتخاب کن\n"
        "۴. درصد سود فروشنده رو انتخاب کن (معمولاً ۷)\n"
        "۵. درصد مالیات رو انتخاب کن (معمولاً ۱۰)\n\n"
        "💡 می‌تونی از دکمه‌های预设 استفاده کنی یا عدد رو دستی تایپ کنی.\n"
        "❌ برای لغو /cancel رو بزن.",
        parse_mode="Markdown"
    )

async def cancel(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text(
        "❌ محاسبه لغو شد.\n\n"
        "برای شروع دوباره /start رو بزن.",
        reply_markup=main_kb()
    )
    return ConversationHandler.END

async def fallback(update: Update, context: CallbackContext) -> None:
    text = update.message.text
    if text == "📊 محاسبه جدید":
        await update.message.reply_text("لطفاً /start رو بزن 👇", reply_markup=main_kb())
    elif text == "❓ راهنما":
        await help_cmd(update, context)
    else:
        await update.message.reply_text(
            "برای شروع /start رو بزن 👇",
            reply_markup=main_kb()
        )

# ─── Health HTTP Server (for Render keep-alive) ──────────────────────
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, fmt: str, *args: tuple) -> None:
        pass  # suppress health-check logs

def run_http() -> None:
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    logger.info(f"🌐 Health server on port {port}")
    server.serve_forever()

# ─── Main ────────────────────────────────────────────────────────────
def main() -> None:
    # Start health HTTP server in background thread
    threading.Thread(target=run_http, daemon=True).start()

    app = Application.builder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex(r"^📊 محاسبه جدید$"), reset_all),
            CallbackQueryHandler(new_calc_cb, pattern="^new_calc$"),
        ],
        states={
            GOLD_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, gold_price_handler),
                CallbackQueryHandler(gold_price_cb, pattern=r"^gp:"),
            ],
            WEIGHT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, weight_handler),
                CallbackQueryHandler(weight_cb, pattern=r"^w:"),
            ],
            MANUF_FEE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, manuf_handler),
                CallbackQueryHandler(manuf_cb, pattern=r"^mf:"),
            ],
            SELLER_PROFIT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, profit_handler),
                CallbackQueryHandler(profit_cb, pattern=r"^sp:"),
            ],
            VAT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, vat_handler),
                CallbackQueryHandler(vat_cb, pattern=r"^vat:"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback))

    logger.info("🤖 Bot started! Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()