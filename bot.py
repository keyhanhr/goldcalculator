#!/usr/bin/env python3
"""
🤖 Gold Price Calculator Bot — Telegram Bot
محاسبه‌گر قیمت طلا در تلگرام
"""

from __future__ import annotations

import os
import re
import logging
from decimal import Decimal, InvalidOperation
from typing import Optional

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ConversationHandler, filters, CallbackContext
)

# ─── Config ──────────────────────────────────────────────────────────
TOKEN = os.environ.get("BOT_TOKEN", "8738042848:AAHplME4R3zlV2J9fpgVYI3qAY1iAeVKswE")
BOT_USERNAME = "gold_calculator_bot"  # change if needed

# ─── Logging ─────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── Conversation States ─────────────────────────────────────────────
(GOLD_PRICE, WEIGHT, MANUF_FEE, SELLER_PROFIT, VAT) = range(5)

# ─── Helpers ─────────────────────────────────────────────────────────
PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

def clean_number(text: str) -> str:
    """Convert Persian/Arabic digits to English, remove commas."""
    text = text.translate(PERSIAN_DIGITS)
    text = text.replace(",", "").replace("٬", "").strip()
    return text

def parse_decimal(text: str) -> Decimal | None:
    try:
        val = Decimal(clean_number(text))
        if val < 0:
            return None
        return val
    except (InvalidOperation, ValueError):
        return None

def fmt(n: Decimal) -> str:
    """Format number with Persian thousands separator."""
    # Separate integer and decimal parts
    s = str(n.quantize(Decimal("1")) if n == n.to_integral() else n.normalize())
    if "." in s:
        int_part, dec_part = s.split(".")
    else:
        int_part, dec_part = s, ""

    # Add commas
    result = []
    for i, ch in enumerate(reversed(int_part)):
        if i > 0 and i % 3 == 0:
            result.append("٬")
        result.append(ch)
    int_part = "".join(reversed(result))

    # Convert to Persian digits
    persian_digits = {"0":"۰","1":"۱","2":"۲","3":"۳","4":"۴","5":"۵","6":"۶","7":"۷","8":"۸","9":"۹"}
    for eng, per in persian_digits.items():
        int_part = int_part.replace(eng, per)

    if dec_part:
        for eng, per in persian_digits.items():
            dec_part = dec_part.replace(eng, per)
        return f"{int_part}/{dec_part}"
    return int_part

def calc_gold(gold_price: Decimal, weight: Decimal, manuf_pct: Decimal,
              profit_pct: Decimal, vat_pct: Decimal) -> dict:
    """Standard Iranian gold pricing formula."""
    gold_value    = gold_price * weight
    manuf_amount  = gold_value * manuf_pct / Decimal("100")
    after_manuf   = gold_value + manuf_amount
    profit_amount = after_manuf * profit_pct / Decimal("100")
    after_profit  = after_manuf + profit_amount
    vat_amount    = after_profit * vat_pct / Decimal("100")
    total         = after_profit + vat_amount
    per_gram      = total / weight if weight > 0 else Decimal("0")

    return {
        "gold_value": gold_value,
        "manuf_amount": manuf_amount,
        "profit_amount": profit_amount,
        "vat_amount": vat_amount,
        "total": total,
        "per_gram": per_gram,
        "manuf_pct": manuf_pct,
        "profit_pct": profit_pct,
        "vat_pct": vat_pct,
    }

def build_result_text(r: dict) -> str:
    """Build the formatted result message."""
    return (
        "💰 *محاسبه‌گر قیمت طلا*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 قیمت خالص طلا:\n`{fmt(r['gold_value'])}` تومان\n\n"
        f"➕ اجرت ساخت ({fmt(r['manuf_pct'])}%):\n`{fmt(r['manuf_amount'])}` تومان\n\n"
        f"➕ سود فروشنده ({fmt(r['profit_pct'])}%):\n`{fmt(r['profit_amount'])}` تومان\n\n"
        f"➕ مالیات بر ارزش افزوده ({fmt(r['vat_pct'])}%):\n`{fmt(r['vat_amount'])}` تومان\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🟡 *قیمت نهایی:*\n`{fmt(r['total'])}` تومان\n\n"
        f"📊 قیمت هر گرم با احتساب هزینه‌ها:\n`{fmt(r['per_gram'])}` تومان"
    )

# ─── Keyboard ────────────────────────────────────────────────────────
def get_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton("📊 محاسبه جدید"), KeyboardButton("❓ راهنما")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ─── Handlers ────────────────────────────────────────────────────────
async def start(update: Update, context: CallbackContext) -> int:
    user = update.effective_user
    await update.message.reply_text(
        f"سلام {user.first_name} 👋\n\n"
        "به *محاسبه‌گر قیمت طلا* خوش اومدی 🪙\n\n"
        "من بهت کمک می‌کنم قیمت نهایی طلا رو با احتساب اجرت ساخت، سود فروشنده و مالیات محاسبه کنی.\n\n"
        "برای شروع، دکمه *محاسبه جدید* رو بزن یا قیمت هر گرم طلای ۱۸ عیار رو بفرست.",
        reply_markup=get_keyboard(),
        parse_mode="Markdown"
    )
    return GOLD_PRICE

async def help_command(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text(
        "🤖 *راهنمای استفاده*\n\n"
        "۱. قیمت هر گرم طلای ۱۸ عیار رو به تومان وارد کن\n"
        "۲. وزن طلا رو به گرم وارد کن (مثال: ۱۲.۳۴۵)\n"
        "۳. درصد اجرت ساخت رو وارد کن\n"
        "۴. درصد سود فروشنده رو وارد کن (پیش‌فرض: ۷)\n"
        "۵. درصد مالیات بر ارزش افزوده رو وارد کن (پیش‌فرض: ۱۰)\n\n"
        "در هر مرحله می‌تونی /cancel رو بزنی تا لغو کنی.",
        parse_mode="Markdown"
    )

async def cancel(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text(
        "❌ محاسبه لغو شد.\n\n"
        "برای شروع دوباره /start رو بزن.",
        reply_markup=get_keyboard()
    )
    return ConversationHandler.END

async def gold_price_handler(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text == "📊 محاسبه جدید":
        return await reset_and_start(update, context)
    if text == "❓ راهنما":
        await help_command(update, context)
        return GOLD_PRICE

    val = parse_decimal(text)
    if val is None or val <= 0:
        await update.message.reply_text(
            "⚠️ لطفاً یه عدد معتبر وارد کن.\nمثال: `۳٬۳۵۰٬۰۰۰` یا `3350000`",
            parse_mode="Markdown"
        )
        return GOLD_PRICE

    context.user_data["gold_price"] = val
    await update.message.reply_text(
        f"✅ قیمت هر گرم: `{fmt(val)}` تومان ثبت شد.\n\n"
        "حالا *وزن طلا* رو به گرم وارد کن:\n"
        "مثال: `۱۲.۳۴۵` یا `12.345`",
        parse_mode="Markdown"
    )
    return WEIGHT

async def weight_handler(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text == "📊 محاسبه جدید":
        return await reset_and_start(update, context)
    if text == "❓ راهنما":
        await help_command(update, context)
        return WEIGHT

    val = parse_decimal(text)
    if val is None or val <= 0:
        await update.message.reply_text(
            "⚠️ لطفاً وزن معتبر وارد کن.\nمثال: `۱۲.۳۴۵` یا `12.345`",
            parse_mode="Markdown"
        )
        return WEIGHT

    context.user_data["weight"] = val
    await update.message.reply_text(
        f"✅ وزن: `{fmt(val)}` گرم ثبت شد.\n\n"
        "حالا *درصد اجرت ساخت* رو وارد کن:\n"
        "مثال: `۱۵` (یعنی ۱۵٪)\n"
        "اگه اجرت نداره، `۰` بفرست.",
        parse_mode="Markdown"
    )
    return MANUF_FEE

async def manuf_fee_handler(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text == "📊 محاسبه جدید":
        return await reset_and_start(update, context)
    if text == "❓ راهنما":
        await help_command(update, context)
        return MANUF_FEE

    val = parse_decimal(text)
    if val is None:
        await update.message.reply_text(
            "⚠️ لطفاً یه درصد معتبر وارد کن.\nمثال: `۱۵` یا `0`",
            parse_mode="Markdown"
        )
        return MANUF_FEE

    context.user_data["manuf_fee"] = val
    await update.message.reply_text(
        f"✅ اجرت ساخت: `{fmt(val)}`٪ ثبت شد.\n\n"
        "حالا *درصد سود فروشنده* رو وارد کن:\n"
        "پیش‌فرض: `۷` درصد",
        parse_mode="Markdown"
    )
    return SELLER_PROFIT

async def seller_profit_handler(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text == "📊 محاسبه جدید":
        return await reset_and_start(update, context)
    if text == "❓ راهنما":
        await help_command(update, context)
        return SELLER_PROFIT

    val = parse_decimal(text)
    if val is None:
        await update.message.reply_text(
            "⚠️ لطفاً یه درصد معتبر وارد کن.\n"
            "پیش‌فرض: `۷` درصد",
            parse_mode="Markdown"
        )
        return SELLER_PROFIT

    context.user_data["seller_profit"] = val
    await update.message.reply_text(
        f"✅ سود فروشنده: `{fmt(val)}`٪ ثبت شد.\n\n"
        "حالا *درصد مالیات بر ارزش افزوده* رو وارد کن:\n"
        "پیش‌فرض: `۱۰` درصد",
        parse_mode="Markdown"
    )
    return VAT

async def vat_handler(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text == "📊 محاسبه جدید":
        return await reset_and_start(update, context)
    if text == "❓ راهنما":
        await help_command(update, context)
        return VAT

    val = parse_decimal(text)
    if val is None:
        await update.message.reply_text(
            "⚠️ لطفاً یه درصد معتبر وارد کن.\n"
            "پیش‌فرض: `۱۰` درصد",
            parse_mode="Markdown"
        )
        return VAT

    context.user_data["vat"] = val

    # ─── Calculate & Show Result ──────────────────────
    data = context.user_data
    try:
        result = calc_gold(
            data["gold_price"], data["weight"],
            data["manuf_fee"], data["seller_profit"], data["vat"]
        )
    except Exception as e:
        logger.error(f"Calc error: {e}")
        await update.message.reply_text("⚠️ خطایی در محاسبه رخ داد. دوباره تلاش کن.")
        return ConversationHandler.END

    text = build_result_text(result)
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=get_keyboard()
    )

    # ─── Ask if they want another calculation ─────────
    await update.message.reply_text(
        "برای محاسبه جدید دکمه *محاسبه جدید* رو بزن 👇",
        parse_mode="Markdown",
        reply_markup=get_keyboard()
    )

    return ConversationHandler.END

async def reset_and_start(update: Update, context: CallbackContext) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "🔄 محاسبه جدید\n\n"
        "لطفاً *قیمت هر گرم طلای ۱۸ عیار* رو به تومان وارد کن:\n"
        "مثال: `۳٬۳۵۰٬۰۰۰` یا `3350000`",
        parse_mode="Markdown"
    )
    return GOLD_PRICE

async def fallback_handler(update: Update, context: CallbackContext) -> None:
    """Handle messages outside conversation."""
    text = update.message.text
    if text == "📊 محاسبه جدید":
        await update.message.reply_text(
            "برای شروع /start رو بزن 👇",
            reply_markup=get_keyboard()
        )
    elif text == "❓ راهنما":
        await help_command(update, context)
    else:
        await update.message.reply_text(
            "برای شروع /start رو بزن یا از دکمه‌ها استفاده کن 👇",
            reply_markup=get_keyboard()
        )

# ─── Main ────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex(r"^📊 محاسبه جدید$"), reset_and_start),
        ],
        states={
            GOLD_PRICE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, gold_price_handler)],
            WEIGHT:        [MessageHandler(filters.TEXT & ~filters.COMMAND, weight_handler)],
            MANUF_FEE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, manuf_fee_handler)],
            SELLER_PROFIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_profit_handler)],
            VAT:           [MessageHandler(filters.TEXT & ~filters.COMMAND, vat_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_handler))

    logger.info("🤖 Bot started! Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()