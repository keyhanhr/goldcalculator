#!/usr/bin/env python3
"""
🤖 Gold Price Calculator Bot — Telegram Bot
محاسبه‌گر قیمت طلا + واچ‌لیست قیمت‌ها
"""

from __future__ import annotations

import os
import re
import logging
import threading
import time as _time
from http.server import HTTPServer, BaseHTTPRequestHandler
from decimal import Decimal, InvalidOperation
from httpx import Client

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, CallbackContext,
    PicklePersistence, PersistenceInput
)

# ─── Config ──────────────────────────────────────────────────────────
TOKEN = os.environ.get("BOT_TOKEN", "8738042848:***")
DATA_FILE = "bot_data.pkl"

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
    s = str(n.quantize(Decimal("1")) if n == n.to_integral() else n.normalize())
    int_part, _, dec_part = s.partition(".")
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

# ─── Watchlist Default Items ─────────────────────────────────────────
WATCHLIST_DEFAULTS = [
    ("بیت‌کوین", "crypto:bitcoin"),
    ("طلای ۱۸ عیار", "tala:18k"),
    ("تتر", "crypto:tether"),
    ("اونس طلا", "crypto:pax-gold"),
    ("سکه امامی", "tala:sekke"),
    ("نیم سکه", "tala:sekke-nim"),
    ("ربع سکه", "tala:sekke-rob"),
]

WATCHLIST_LABELS = {
    "crypto:bitcoin": ("₿ بیت‌کوین", "USD"),
    "crypto:tether": ("💵 تتر (USDT)", "USD"),
    "crypto:pax-gold": ("🪙 اونس طلا (XAU)", "USD"),
    "crypto:ethereum": ("♦️ اتریوم", "USD"),
    "crypto:solana": ("◎ سولانا", "USD"),
    "crypto:ripple": ("✧ ریپل", "USD"),
    "crypto:cardano": ("🟣 کاردانو", "USD"),
    "crypto:dogecoin": ("🐕 دوج‌کوین", "USD"),
    "crypto:binancecoin": ("🔶 بایننس", "USD"),
    "tala:18k": ("🥇 طلای ۱۸ عیار", "تومان"),
    "tala:sekke": ("🪙 سکه امامی", "تومان"),
    "tala:sekke-nim": ("🪙 نیم سکه", "تومان"),
    "tala:sekke-rob": ("🪙 ربع سکه", "تومان"),
}

def cg_id(item: str) -> str:
    """Map watchlist item to CoinGecko ID or tala path."""
    return item.split(":", 1)[1]

# ─── Price Cache ─────────────────────────────────────────────────────
PRICE_CACHE: dict = {"data": {}, "time": 0}

def fetch_watchlist_prices(items: list[str]) -> dict:
    """Fetch prices for watchlist items. Returns {item_key: price_string}."""
    now = _time.time()
    if now - PRICE_CACHE["time"] < 60 and PRICE_CACHE["data"]:
        return PRICE_CACHE["data"]

    result = {}
    crypto_ids = []
    tala_paths = []

    for item in items:
        if item.startswith("crypto:"):
            crypto_ids.append(cg_id(item))
        elif item.startswith("tala:"):
            tala_paths.append(item)

    # Fetch crypto prices from CoinPaprika
    for item in items:
        if item.startswith("crypto:"):
            cid = cg_id(item)
            # Map CoinGecko IDs to CoinPaprika IDs
            cp_map = {
                "bitcoin": "btc-bitcoin",
                "tether": "usdt-tether",
                "pax-gold": "paxg-pax-gold",
                "ethereum": "eth-ethereum",
                "solana": "sol-solana",
                "ripple": "xrp-xrp",
                "cardano": "ada-cardano",
                "dogecoin": "doge-dogecoin",
                "binancecoin": "bnb-binance-coin",
            }
            cp_id = cp_map.get(cid, cid)
            try:
                with Client(verify=False, timeout=8) as c:
                    r = c.get(
                        f"https://api.coinpaprika.com/v1/tickers/{cp_id}",
                        headers={"User-Agent": "Mozilla/5.0"}
                    )
                    data = r.json()
                    price = data.get("quotes", {}).get("USD", {}).get("price")
                    if price:
                        price_f = float(price)
                        if price_f >= 1:
                            result[item] = f"{price_f:,.2f} $"
                        elif price_f >= 0.01:
                            result[item] = f"{price_f:.4f} $"
                        else:
                            result[item] = f"{price_f:.6f} $"
                    else:
                        result[item] = "—"
            except Exception as e:
                logger.warning(f"CoinPaprika {cp_id} error: {e}")
                result[item] = "⚠️ خطا"

    # Fetch Iranian prices from tala.ir (only 18k works server-side)
    # Calculate coin prices from 18K gold price
    gold_18k = None
    for item in tala_paths:
        if item == "tala:18k":
            try:
                with Client(verify=False, timeout=8) as c:
                    r = c.get("https://www.tala.ir/price/18k", headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    })
                    m = re.search(r'عیار\s*750\s*یا\s*18.*?<h5[^>]*>([0-9,]+)', r.text, re.DOTALL)
                    if m:
                        gold_18k = int(m.group(1).replace(",", ""))
                        result[item] = f"{gold_18k:,} تومان"
                    else:
                        result[item] = "—"
            except Exception as e:
                logger.warning(f"tala.ir/18k error: {e}")
                result[item] = "⚠️ خطا"
        elif item.startswith("tala:") and gold_18k:
            # Calculate Iranian coin prices from 18K gold
            # Gold 900 (21.6K) per gram = 18K * 900/750
            gold_900 = gold_18k * 900 // 750
            premium = 3  # 3% premium for coin
            if item == "tala:sekke":
                # Emami coin: 8.133g of gold 900
                coin_price = int(8.133 * gold_900 * (100 + premium) / 100)
            elif item == "tala:sekke-nim":
                # Half coin: 4.0665g of gold 900
                coin_price = int(4.0665 * gold_900 * (100 + premium) / 100)
            elif item == "tala:sekke-rob":
                # Quarter coin: 2.03325g of gold 900
                coin_price = int(2.03325 * gold_900 * (100 + premium) / 100)
            else:
                coin_price = None
            if coin_price:
                result[item] = f"{coin_price:,} تومان"
            else:
                result[item] = "—"

    PRICE_CACHE["data"] = result
    PRICE_CACHE["time"] = now
    return result

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
        f"📊 هر گرم:\n`{fmt(r['per_gram'])}` تومان"
    )

# ─── Gold Price Fetch (for calculator) ───────────────────────────────
GOLD_CACHE: dict = {"tala": None, "time": 0}
import time as _gtime

def fetch_gold_price() -> int | None:
    now = _gtime.time()
    if now - GOLD_CACHE["time"] < 120 and GOLD_CACHE["tala"] is not None:
        return GOLD_CACHE["tala"]
    try:
        with Client(verify=False, timeout=8) as c:
            r = c.get("https://www.tala.ir/price/18k", headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            m = re.search(r'عیار\s*750\s*یا\s*18.*?<h5[^>]*>([0-9,]+)', r.text, re.DOTALL)
            if m:
                GOLD_CACHE["tala"] = int(m.group(1).replace(",", ""))
                GOLD_CACHE["time"] = now
                return GOLD_CACHE["tala"]
    except Exception as e:
        logger.warning(f"tala.ir fetch failed: {e}")
    return None

# ─── Keyboards ───────────────────────────────────────────────────────
def btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=data)

def price_kb() -> InlineKeyboardMarkup:
    tala = fetch_gold_price()
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
        [[KeyboardButton("📊 محاسبه طلا"), KeyboardButton("📋 واچ‌لیست")],
         [KeyboardButton("❓ راهنما")]],
        resize_keyboard=True
    )

# ─── Watchlist ───────────────────────────────────────────────────────
DEFAULT_COINS = [
    "crypto:bitcoin", "tala:18k", "crypto:tether",
    "crypto:pax-gold", "tala:sekke", "tala:sekke-nim", "tala:sekke-rob",
]

async def watchlist_cmd(update: Update, context: CallbackContext) -> None:
    """Show the watchlist with current prices."""
    uid = str(update.effective_user.id)
    user_data = context.bot_data.get("watchlists", {}).get(uid, DEFAULT_COINS.copy())

    prices = fetch_watchlist_prices(user_data)

    lines = ["📋 *واچ‌لیست قیمت‌ها*\n━━━━━━━━━━━━━━━━━━\n"]
    for item in user_data:
        label, unit = WATCHLIST_LABELS.get(item, (item.split(":", 1)[1], ""))
        price = prices.get(item, "—")
        lines.append(f"{label}: `{price}`")

    lines.append("\n━━━━━━━━━━━━━━━━━━")
    lines.append("💡 /addcoin <نام> — اضافه کردن")
    lines.append("🗑 /delcoin <نام> — حذف کردن")
    lines.append("🔄 /watchlist — بروزرسانی")

    text = "\n".join(lines)

    kb = InlineKeyboardMarkup([
        [btn("🔄 بروزرسانی", "wl_refresh")],
        [btn("➕ اضافه کردن کوین", "wl_add"), btn("➖ حذف", "wl_del")],
    ])

    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)

async def watchlist_cb(update: Update, context: CallbackContext) -> None:
    """Handle watchlist callback buttons."""
    query = update.callback_query
    await query.answer()

    if query.data == "wl_refresh":
        await watchlist_refresh(update, context)
    elif query.data == "wl_add":
        await query.edit_message_text(
            "➕ اسم کوین رو بفرست:\n\n"
            "مثال: `ethereum` یا `solana` یا `ripple`\n\n"
            "برای دیدن لیست کامل کوین‌های قابل اضافه:\n"
            "https://www.coingecko.com/",
            parse_mode="Markdown"
        )
        context.user_data["awaiting_coin"] = True
    elif query.data == "wl_del":
        await show_delete_menu(update, context)

async def watchlist_refresh(update: Update, context: CallbackContext) -> None:
    """Refresh the watchlist."""
    uid = str(update.effective_user.id)
    user_data = context.bot_data.get("watchlists", {}).get(uid, DEFAULT_COINS.copy())
    prices = fetch_watchlist_prices(user_data)

    lines = ["📋 *واچ‌لیست قیمت‌ها*\n━━━━━━━━━━━━━━━━━━\n"]
    for item in user_data:
        label, unit = WATCHLIST_LABELS.get(item, (item.split(":", 1)[1], ""))
        price = prices.get(item, "—")
        lines.append(f"{label}: `{price}`")

    text = "\n".join(lines)

    kb = InlineKeyboardMarkup([
        [btn("🔄 بروزرسانی", "wl_refresh")],
        [btn("➕ اضافه کردن", "wl_add"), btn("➖ حذف", "wl_del")],
    ])

    try:
        await update.callback_query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=kb
        )
    except Exception:
        msg = update.callback_query.message
        await msg.reply_text(text, parse_mode="Markdown", reply_markup=kb)

async def show_delete_menu(update: Update, context: CallbackContext) -> None:
    """Show items the user can delete."""
    uid = str(update.effective_user.id)
    user_data = context.bot_data.get("watchlists", {}).get(uid, DEFAULT_COINS.copy())

    if len(user_data) <= 1:
        await update.callback_query.edit_message_text(
            "❌ حداقل باید یک آیتم تو واچ‌لیست باشه."
        )
        return

    buttons = []
    for item in user_data:
        label, _ = WATCHLIST_LABELS.get(item, (item.split(":", 1)[1], ""))
        buttons.append([btn(f"❌ حذف {label}", f"wl_del:{item}")])

    buttons.append([btn("🔙 برگشت", "wl_refresh")])

    await update.callback_query.edit_message_text(
        "👇 روی آیتم مورد نظر کلیک کن تا حذف بشه:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def watchlist_del_cb(update: Update, context: CallbackContext) -> None:
    """Delete an item from watchlist."""
    query = update.callback_query
    await query.answer()

    item = query.data.replace("wl_del:", "")
    uid = str(update.effective_user.id)
    watchlists = context.bot_data.setdefault("watchlists", {})
    user_wl = watchlists.get(uid, DEFAULT_COINS.copy())

    if item in user_wl:
        user_wl.remove(item)
        watchlists[uid] = user_wl

    await show_delete_menu(update, context)

async def add_coin_handler(update: Update, context: CallbackContext) -> None:
    """Handle coin name input for adding to watchlist."""
    if not context.user_data.get("awaiting_coin"):
        return

    coin_name = update.message.text.strip().lower().replace(" ", "-")
    context.user_data["awaiting_coin"] = False

    # Verify the coin exists on CoinGecko
    try:
        with Client(verify=False, timeout=8) as c:
            r = c.get(
                f"https://api.coingecko.com/api/v3/simple/price?ids={coin_name}&vs_currencies=usd",
                headers={"User-Agent": "Mozilla/5.0"}
            )
            data = r.json()
            if coin_name not in data:
                await update.message.reply_text(
                    f"❌ کوین `{coin_name}` پیدا نشد!\n\n"
                    "اسم درست رو از اینجا پیدا کن:\n"
                    "https://www.coingecko.com/",
                    parse_mode="Markdown"
                )
                return
    except Exception:
        await update.message.reply_text(
            "❌ خطا در ارتباط با CoinGecko. بعداً تلاش کن."
        )
        return

    uid = str(update.effective_user.id)
    watchlists = context.bot_data.setdefault("watchlists", {})
    user_wl = watchlists.get(uid, DEFAULT_COINS.copy())

    item_key = f"crypto:{coin_name}"
    if item_key in user_wl:
        await update.message.reply_text(
            f"✅ `{coin_name}` از قبل تو واچ‌لیستت هست!",
            parse_mode="Markdown"
        )
        return

    user_wl.append(item_key)
    watchlists[uid] = user_wl

    # Clear cache so next fetch gets new data
    PRICE_CACHE["time"] = 0

    await update.message.reply_text(
        f"✅ `{coin_name}` به واچ‌لیست اضافه شد!\n"
        "از /watchlist برای دیدنش استفاده کن.",
        parse_mode="Markdown"
    )

# ══════════════════════════════════════════════════════════════════════
# Gold Calculator Conversation Handlers
# ══════════════════════════════════════════════════════════════════════

async def start(update: Update, context: CallbackContext) -> int:
    user = update.effective_user
    await update.message.reply_text(
        f"سلام {user.first_name} جان 🖐️\n\n"
        "از حساب‌کتاب طلایی که می‌خری سَر درنمیاری؟ 🤯\n"
        "نگران نباش، من اینجام تا کارو برات راحت کنم! 🪙\n\n"
        "✨ *کارایی که می‌تونم انجام بدم:*\n"
        "📊 محاسبه قیمت نهایی طلا با اجرت و مالیات\n"
        "📋 واچ‌لیست قیمت‌های لحظه‌ای (بیت‌کوین، طلا، تتر و...)\n\n"
        "👇 از دکمه‌های زیر استفاده کن:",
        reply_markup=main_kb(),
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def calc_start(update: Update, context: CallbackContext) -> int:
    """Start the gold calculator flow."""
    await update.message.reply_text(
        "🪙 *محاسبه‌گر قیمت طلا*\n\n"
        "💰 *قیمت هر گرم طلای ۱۸ عیار* رو وارد کن:\n\n"
        "قیمت لحظه‌ای:",
        reply_markup=price_kb(),
        parse_mode="Markdown"
    )
    return GOLD_PRICE

async def gold_price_handler(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text == "❓ راهنما":
        await help_cmd(update, context)
        return GOLD_PRICE
    val = parse_decimal(text)
    if val is None or val <= 0:
        await update.message.reply_text(
            "⚠️ لطفاً یه عدد معتبر وارد کن.\nمیتونی از دکمه‌ها استفاده کنی.",
            reply_markup=price_kb(), parse_mode="Markdown"
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
            "💰 لطفاً *قیمت هر گرم* رو دستی تایپ کن:\nمثال: `۱۸۸۵۰۰۰۰`",
            reply_markup=None, parse_mode="Markdown"
        )
        return GOLD_PRICE
    val = Decimal(data.split(":")[1])
    context.user_data["gold_price"] = val
    await query.edit_message_text(f"✅ قیمت: `{fmt(val)}` تومان", parse_mode="Markdown")
    return await ask_weight(update, context)

async def ask_weight(update: Update, context: CallbackContext) -> int:
    msg = update.message or update.callback_query.message
    await msg.reply_text("⚖️ *وزن طلا* رو به گرم وارد کن:", reply_markup=weight_kb(), parse_mode="Markdown")
    return WEIGHT

async def weight_handler(update: Update, context: CallbackContext) -> int:
    val = parse_decimal(update.message.text)
    if val is None or val <= 0:
        await update.message.reply_text("⚠️ وزن معتبر وارد کن.", reply_markup=weight_kb())
        return WEIGHT
    context.user_data["weight"] = val
    return await ask_manuf(update, context)

async def weight_cb(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "w:custom":
        await query.edit_message_text("⚖️ *وزن* رو دستی تایپ کن:", reply_markup=None, parse_mode="Markdown")
        return WEIGHT
    context.user_data["weight"] = Decimal(data.split(":")[1])
    await query.edit_message_text(f"✅ وزن: `{fmt(context.user_data['weight'])}` گرم", parse_mode="Markdown")
    return await ask_manuf(update, context)

async def ask_manuf(update: Update, context: CallbackContext) -> int:
    msg = update.message or update.callback_query.message
    await msg.reply_text("🔧 *درصد اجرت ساخت* رو وارد کن:", reply_markup=manuf_kb(), parse_mode="Markdown")
    return MANUF_FEE

async def manuf_handler(update: Update, context: CallbackContext) -> int:
    val = parse_decimal(update.message.text)
    if val is None:
        await update.message.reply_text("⚠️ درصد معتبر وارد کن.", reply_markup=manuf_kb())
        return MANUF_FEE
    context.user_data["manuf_fee"] = val
    return await ask_profit(update, context)

async def manuf_cb(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "mf:custom":
        await query.edit_message_text("🔧 *درصد اجرت ساخت* رو تایپ کن:", reply_markup=None, parse_mode="Markdown")
        return MANUF_FEE
    context.user_data["manuf_fee"] = Decimal(data.split(":")[1])
    await query.edit_message_text(f"✅ اجرت ساخت: `{fmt(context.user_data['manuf_fee'])}`٪", parse_mode="Markdown")
    return await ask_profit(update, context)

async def ask_profit(update: Update, context: CallbackContext) -> int:
    msg = update.message or update.callback_query.message
    await msg.reply_text("📈 *درصد سود فروشنده* رو وارد کن (پیشنهاد: ۷):", reply_markup=profit_kb(), parse_mode="Markdown")
    return SELLER_PROFIT

async def profit_handler(update: Update, context: CallbackContext) -> int:
    val = parse_decimal(update.message.text)
    if val is None:
        await update.message.reply_text("⚠️ درصد معتبر وارد کن.", reply_markup=profit_kb())
        return SELLER_PROFIT
    context.user_data["seller_profit"] = val
    return await ask_vat(update, context)

async def profit_cb(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "sp:custom":
        await query.edit_message_text("📈 *درصد سود فروشنده* رو تایپ کن:", reply_markup=None, parse_mode="Markdown")
        return SELLER_PROFIT
    context.user_data["seller_profit"] = Decimal(data.split(":")[1])
    await query.edit_message_text(f"✅ سود فروشنده: `{fmt(context.user_data['seller_profit'])}`٪", parse_mode="Markdown")
    return await ask_vat(update, context)

async def ask_vat(update: Update, context: CallbackContext) -> int:
    msg = update.message or update.callback_query.message
    await msg.reply_text("🧾 *درصد مالیات* رو وارد کن (پیشنهاد: ۱۰):", reply_markup=vat_kb(), parse_mode="Markdown")
    return VAT

async def vat_handler(update: Update, context: CallbackContext) -> int:
    val = parse_decimal(update.message.text)
    if val is None:
        await update.message.reply_text("⚠️ درصد معتبر وارد کن.", reply_markup=vat_kb())
        return VAT
    context.user_data["vat"] = val
    return await show_result(update, context)

async def vat_cb(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "vat:custom":
        await query.edit_message_text("🧾 *درصد مالیات* رو تایپ کن:", reply_markup=None, parse_mode="Markdown")
        return VAT
    context.user_data["vat"] = Decimal(data.split(":")[1])
    await query.edit_message_text(f"✅ مالیات: `{fmt(context.user_data['vat'])}`٪", parse_mode="Markdown")
    return await show_result(update, context)

async def show_result(update: Update, context: CallbackContext) -> int:
    data = context.user_data
    try:
        r = calc_gold(data["gold_price"], data["weight"], data["manuf_fee"], data["seller_profit"], data["vat"])
    except Exception as e:
        logger.error(f"Calc error: {e}")
        msg = update.message or update.callback_query.message
        await msg.reply_text("⚠️ خطایی رخ داد. دوباره تلاش کن.")
        return ConversationHandler.END
    msg = update.message or update.callback_query.message
    await msg.reply_text(build_result(r), parse_mode="Markdown", reply_markup=main_kb())
    await msg.reply_text("👇 برای محاسبه جدید:", reply_markup=InlineKeyboardMarkup([[btn("🔄 محاسبه جدید", "new_calc")]]))
    return ConversationHandler.END

async def new_calc_cb(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text("🔄 محاسبه جدید...")
    return await calc_start(update, context)

async def help_cmd(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text(
        "🤖 *راهنما*\n\n"
        "📊 **محاسبه طلا** — قیمت نهایی طلا با اجرت و مالیات\n"
        "📋 **واچ‌لیست** — قیمت لحظه‌ای ارزها و طلا\n"
        "➕ /addcoin <نام> — اضافه کردن کوین به واچ‌لیست\n"
        "🗑 /delcoin <نام> — حذف کوین از واچ‌لیست\n\n"
        "💡 مثال: `/addcoin ethereum`",
        parse_mode="Markdown"
    )

async def cancel(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text("❌ لغو شد.", reply_markup=main_kb())
    return ConversationHandler.END

async def fallback(update: Update, context: CallbackContext) -> None:
    text = update.message.text
    if text == "📊 محاسبه طلا":
        await calc_start(update, context)
    elif text == "📋 واچ‌لیست":
        await watchlist_cmd(update, context)
    elif text == "❓ راهنما":
        await help_cmd(update, context)
    else:
        await update.message.reply_text("از دکمه‌های زیر استفاده کن 👇", reply_markup=main_kb())

# ══════════════════════════════════════════════════════════════════════
# Health HTTP Server
# ══════════════════════════════════════════════════════════════════════

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, fmt: str, *args: tuple) -> None:
        pass

def run_http() -> None:
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    logger.info(f"🌐 Health server on port {port}")
    server.serve_forever()

# ══════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════

def main() -> None:
    threading.Thread(target=run_http, daemon=True).start()

    persistence = PicklePersistence(
        filepath=DATA_FILE,
        store_data=PersistenceInput(bot_data=True, user_data=False, chat_data=False)
    )
    app = Application.builder().token(TOKEN).persistence(persistence).build()

    # Init default watchlists if needed
    if "watchlists" not in app.bot_data:
        app.bot_data["watchlists"] = {}

    # Gold calculator conversation
    conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(r"^📊 محاسبه طلا$"), calc_start),
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
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("watchlist", watchlist_cmd))
    app.add_handler(CommandHandler("addcoin", add_coin_handler))
    app.add_handler(CallbackQueryHandler(watchlist_cb, pattern=r"^wl_(refresh|add|del)$"))
    app.add_handler(CallbackQueryHandler(watchlist_del_cb, pattern=r"^wl_del:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback))

    logger.info("🤖 Bot started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()