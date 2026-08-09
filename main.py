#!/usr/bin/env python3
"""
🤖 TELEGRAM PROMO BOT v2
------------------------
+ Full English quote support (never truncated)
+ 🖼️ Photo: custom image upload or auto-generated image
+ 🎨 Auto Image: message text -> stylish image (same font, emoji rendered properly)
+ All previous features: accounts/sessions, GCs, time, status, start/stop

Install: pip install pyrogram tgcrypto pillow pilmoji requests
Font:    put any .ttf (Poppins/Montserrat) in the bot folder,
         otherwise the default DejaVu font is used
"""

import asyncio
import json
import os
import re
from datetime import datetime, timedelta

from pyrogram import Client, filters
from pyrogram.errors import (FloodWait, PhoneCodeExpired, PhoneCodeInvalid,
                             SessionPasswordNeeded, UserAlreadyParticipant)
from pyrogram.types import (CallbackQuery, InlineKeyboardButton,
                            InlineKeyboardMarkup, Message)

# ===================== IMAGE ENGINE =====================
from PIL import Image, ImageDraw, ImageFont
from pilmoji import Pilmoji

FONT_PATH = "Poppins-Bold.ttf"      # your font file name (optional)
IMG_WIDTH = 1080                     # image width (px)
IMG_BG = (22, 26, 44)                # background color
IMG_FG = (255, 255, 255)             # text color
IMG_ACCENT = (66, 211, 146)          # accent color (bar / quote mark)
AUTO_SEND_TEXT = True                # also send the text message alongside the auto image
PHOTO_DIR = "photos"

# ===================== CONFIG =====================
API_ID = int(os.getenv("API_ID", "YOUR_API_ID"))
API_HASH = os.getenv("API_HASH", "YOUR_API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")

DATA_FILE = "data.json"

# Delays to avoid flooding/bans (seconds)
DELAY_BETWEEN_MSGS = 3
DELAY_BETWEEN_ACCOUNTS = 10

bot = Client("promo_manager", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

user_state = {}
promo_state = {}

# ===================== DATA STORE =====================
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"accounts": [], "groups": [], "message": "",
            "time": "", "running": False, "photo": "", "auto_image": True}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ===================== IMAGE GENERATION =====================
def find_font():
    candidates = [
        FONT_PATH,
        "Montserrat-Bold.ttf", "Poppins-SemiBold.ttf", "arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None

def wrap_text(text, font, max_width):
    """Wraps words and preserves newlines — the full quote is never cut off."""
    lines = []
    for para in text.split("\n"):
        words = para.split()
        if not words:
            lines.append("")
            continue
        cur = ""
        for w in words:
            test = (cur + " " + w).strip()
            if font.getlength(test) <= max_width:
                cur = test
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines

def pick_font_size(text_len):
    if text_len > 1500: return 30
    if text_len > 900:  return 34
    if text_len > 500:  return 38
    return 46

def generate_promo_image(text, font_path=None):
    """Converts the message into a proper image (with emoji support)."""
    fp = font_path or find_font()
    if not fp:
        raise FileNotFoundError("No font found! Put a .ttf font file in the bot folder.")
    font_size = pick_font_size(len(text))
    font = ImageFont.truetype(fp, font_size)

    pad = 70
    max_width = IMG_WIDTH - (pad * 2)
    lines = wrap_text(text, font, max_width)
    line_h = int(font_size * 1.45)
    height = pad + (len(lines) * line_h) + 90

    img = Image.new("RGB", (IMG_WIDTH, height), IMG_BG)
    draw = ImageDraw.Draw(img)

    # top accent bar + big quote mark
    draw.rectangle([0, 0, IMG_WIDTH, 10], fill=IMG_ACCENT)
    q_font = ImageFont.truetype(fp, 90)
    draw.text((pad, pad - 55), "\u201C", font=q_font, fill=IMG_ACCENT)

    # main text — Pilmoji renders emoji (Twemoji) properly
    with Pilmoji(img) as pmj:
        pmj.text((pad, pad + 20), "\n".join(lines), font=font,
                 fill=IMG_FG, spacing=12,
                 emoji_scale_factor=1.25, emoji_position_offset=(0, 4))

    # footer line
    draw.rectangle([pad, height - 60, IMG_WIDTH - pad, height - 56], fill=IMG_ACCENT)
    return img

def generate_image_file(text):
    os.makedirs(PHOTO_DIR, exist_ok=True)
    img = generate_promo_image(text)
    path = os.path.join(PHOTO_DIR, "auto_promo.jpg")
    img.save(path, "JPEG", quality=92)
    return path

# ===================== HELPERS =====================
def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Account", callback_data="add_acc"),
         InlineKeyboardButton("👥 My Accounts", callback_data="my_accs")],
        [InlineKeyboardButton("➕ Add Group", callback_data="add_gc"),
         InlineKeyboardButton("📋 My Groups", callback_data="my_gcs")],
        [InlineKeyboardButton("✏️ Custom Message", callback_data="set_msg"),
         InlineKeyboardButton("🖼️ Promo Photo", callback_data="photo_menu")],
        [InlineKeyboardButton("⏰ Set Time", callback_data="set_time"),
         InlineKeyboardButton("📊 Current Promo", callback_data="status")],
        [InlineKeyboardButton("🚀 START PROMO", callback_data="start_promo")],
    ])

def back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back")]])

def stop_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🛑 STOP PROMO", callback_data="stop_promo")]])

def photo_kb(d):
    kb = [[InlineKeyboardButton("🖼️ Send Photo", callback_data="photo_send")]]
    if d.get("photo"):
        kb.append([InlineKeyboardButton("❌ Remove Photo", callback_data="photo_rm")])
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="back")])
    return InlineKeyboardMarkup(kb)

def accs_kb(data):
    kb = [[InlineKeyboardButton(f"{i}. {a['name']}  ❌", callback_data=f"rm_acc:{i-1}")]
          for i, a in enumerate(data["accounts"], 1)]
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="back")])
    return InlineKeyboardMarkup(kb)

def groups_kb(data):
    kb = [[InlineKeyboardButton(f"{i}. {g['raw']}  ❌", callback_data=f"rm_gc:{i-1}")]
          for i, g in enumerate(data["groups"], 1)]
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="back")])
    return InlineKeyboardMarkup(kb)

def normalize_phone(p):
    p = p.strip().replace(" ", "").replace("-", "")
    if p.startswith("00"):
        p = "+" + p[2:]
    if p.startswith("+"):
        return p if p[1:].isdigit() else None
    if p.isdigit() and len(p) >= 8:
        return "+" + p
    return None

def parse_group(text):
    t = text.strip()
    m = re.match(r"^(?:https?://)?t\.me/\+([A-Za-z0-9_-]+)$", t)
    if m:
        return {"raw": t, "type": "invite", "value": m.group(1), "ids": {}}
    if t.startswith("+") and re.match(r"^\+[A-Za-z0-9_-]{5,}$", t):
        return {"raw": t, "type": "invite", "value": t[1:], "ids": {}}
    m = re.match(r"^(?:https?://)?t\.me/([A-Za-z0-9_]{4,})$", t)
    if m:
        return {"raw": t, "type": "username", "value": m.group(1), "ids": {}}
    if t.startswith("@"):
        u = t[1:]
        return {"raw": t, "type": "username", "value": u, "ids": {}} if re.match(r"^[A-Za-z0-9_]{4,}$", u) else None
    if t.lstrip("-").isdigit():
        return {"raw": t, "type": "id", "value": int(t), "ids": {}}
    if re.match(r"^[A-Za-z0-9_]{4,}$", t):
        return {"raw": t, "type": "username", "value": t, "ids": {}}
    return None

def compute_target(time_str):
    t = time_str.strip()
    if ":" in t:
        hh, mm = t.split(":")
        now = datetime.now()
        target = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target
    return datetime.now() + timedelta(minutes=float(t))

def split_text(text, limit=4000):
    return [text[i:i + limit] for i in range(0, len(text), limit)]

def build_status(d):
    lines = ["📊 **CURRENT PROMO**\n"]
    lines.append(f"📱 Accounts ({len(d['accounts'])}):")
    for i, a in enumerate(d["accounts"], 1):
        lines.append(f"   {i}. {a['name']}")
    lines.append(f"\n📋 Groups ({len(d['groups'])}):")
    for i, g in enumerate(d["groups"], 1):
        lines.append(f"   {i}. {g['raw']}")
    msg = d["message"]
    lines.append(f"\n✏️ Message: {msg[:60] + '...' if len(msg) > 60 else msg}")
    if d.get("photo"):
        lines.append("🖼️ Photo: ✅ custom image set")
    elif d.get("auto_image"):
        lines.append("🎨 Photo: auto-generate (image created from message)")
    else:
        lines.append("🖼️ Photo: ❌ none")
    lines.append(f"⏰ Time: {d['time'] or '❌ not set'}")
    lines.append(f"▶️ Running: {'✅ YES' if d.get('running') else '❌ NO'}")
    return "\n".join(lines)

# ===================== GROUP LOGIC =====================
async def add_group_entry(entry, message):
    d = load_data()
    if entry["type"] == "invite":
        link = f"https://t.me/+{entry['value']}"
        for acc in d["accounts"]:
            try:
                async with Client(f"gj_{acc['name']}", API_ID, API_HASH,
                                  session_string=acc["session"], in_memory=True) as user:
                    try:
                        chat = await user.join_chat(link)
                        entry["ids"][acc["name"]] = chat.id
                    except UserAlreadyParticipant:
                        pass
                    except FloodWait as e:
                        await asyncio.sleep(min(e.x, 300))
                        try:
                            chat = await user.join_chat(link)
                            entry["ids"][acc["name"]] = chat.id
                        except Exception:
                            pass
                    except Exception:
                        pass
            except Exception:
                pass
    d["groups"].append(entry)
    save_data(d)

async def resolve_chat_id(user, entry, acc_name):
    """Resolves the group chat ID (joins via username/invite if needed)."""
    if entry["type"] == "id":
        return entry["value"], None
    if entry["type"] == "username":
        try:
            await user.join_chat(entry["value"])
        except UserAlreadyParticipant:
            pass
        except Exception:
            pass
        try:
            return (await user.get_chat(entry["value"])).id, None
        except Exception as e:
            return None, f"get_chat failed: {e}"
    # invite link
    chat_id = entry["ids"].get(acc_name)
    if chat_id is not None:
        return chat_id, None
    try:
        chat = await user.join_chat(f"https://t.me/+{entry['value']}")
        return chat.id, None
    except UserAlreadyParticipant:
        return None, "already a member, chat ID could not be resolved"
    except Exception as e:
        return None, f"join failed: {e}"

async def send_payload(user, chat_id, d, stop_event):
    """Sends photo (if set) + full message. The message is never truncated."""
    text = d["message"]
    photo = d.get("photo", "") or ""
    auto = d.get("auto_image", True)

    # ---- Send photo ----
    if photo and os.path.exists(photo):
        caption = text[:1024]            # caption limit is 1024 chars
        rest = text[1024:]
        try:
            await user.send_photo(chat_id, photo, caption=caption)
        except Exception as e:
            return f"photo failed: {e}"
        remaining = split_text(rest) if rest else []
    elif auto:
        try:
            img_path = generate_image_file(text)
            try:
                await user.send_photo(chat_id, img_path)   # full quote inside the image
            except Exception as e:
                return f"photo failed: {e}"
            remaining = split_text(text) if AUTO_SEND_TEXT else []
        except Exception as e:
            remaining = split_text(text)   # if the image fails, send text only
    else:
        remaining = split_text(text)

    # ---- Send remaining text chunks ----
    for chunk in remaining:
        if stop_event.is_set():
            return "stopped"
        try:
            await user.send_message(chat_id, chunk)
        except FloodWait as e:
            await asyncio.sleep(min(e.x, 300))
            if stop_event.is_set():
                return "stopped"
            await user.send_message(chat_id, chunk)
        except Exception as e:
            return f"send failed: {e}"
        await asyncio.sleep(DELAY_BETWEEN_MSGS)
    return "✅"

async def send_to_group(user, entry, acc_name, d, stop_event):
    chat_id, err = await resolve_chat_id(user, entry, acc_name)
    if err:
        return f"❌ {err}"
    try:
        res = await send_payload(user, chat_id, d, stop_event)
        return "✅" if res == "✅" else f"❌ {res}"
    except FloodWait as e:
        await asyncio.sleep(min(e.x, 300))
        res = await send_payload(user, chat_id, d, stop_event)
        return "✅" if res == "✅" else f"❌ {res}"

# ===================== PROMO RUNNER =====================
async def run_promo(chat_id, progress_msg_id):
    d = load_data()
    accounts, groups = d["accounts"], d["groups"]
    message_text, time_str = d["message"], d["time"]
    wait_until = compute_target(time_str)

    ev = asyncio.Event()
    promo_state[chat_id] = ev
    d["running"] = True
    save_data(d)

    try:
        await bot.edit_message_text(
            chat_id, progress_msg_id,
            f"⏳ **PROMO SCHEDULED**\n\n"
            f"📱 Accounts: {len(accounts)}\n📋 Groups: {len(groups)}\n"
            f"⏰ Time: {time_str} ({wait_until.strftime('%H:%M:%S')})\n\n"
            f"Tap 🛑 to stop.",
            reply_markup=stop_kb(),
        )

        delta = (wait_until - datetime.now()).total_seconds()
        if delta > 0:
            await asyncio.sleep(delta)
        if ev.is_set():
            return

        results = []
        for i, acc in enumerate(accounts, 1):
            if ev.is_set():
                results.append(f"🛑 {acc['name']}: stopped")
                break
            await bot.edit_message_text(
                chat_id, progress_msg_id,
                f"⏳ **{acc['name']}** → sending... ({i}/{len(accounts)})",
                reply_markup=stop_kb(),
            )
            ok = fail = 0
            try:
                async with Client(f"pr_{chat_id}_{i}", API_ID, API_HASH,
                                  session_string=acc["session"], in_memory=True) as user:
                    for entry in groups:
                        res = await send_to_group(user, entry, acc["name"], d, ev)
                        if res == "✅":
                            ok += 1
                        else:
                            fail += 1
                            results.append(f"❌ {acc['name']} → {entry['raw']}: {res}")
                        if ev.is_set():
                            break
            except Exception as e:
                fail += 1
                results.append(f"❌ {acc['name']}: {e}")
            results.append(f"{'✅' if fail == 0 else '⚠️'} {acc['name']}: {ok} ok / {fail} fail")
            await asyncio.sleep(DELAY_BETWEEN_ACCOUNTS)

        await bot.edit_message_text(
            chat_id, progress_msg_id,
            f"🏁 **PROMO DONE**\n\n" + "\n".join(results),
            reply_markup=main_kb(),
        )
    finally:
        d = load_data()
        d["running"] = False
        save_data(d)
        promo_state.pop(chat_id, None)

# ===================== COMMANDS =====================
@bot.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message: Message):
    st = user_state.pop(message.chat.id, None)
    if st and "temp" in st:
        try:
            await st["temp"].stop()
        except Exception:
            pass
    await message.reply_text(
        "👋 Welcome to **Promo Bot**!\n\n"
        "Manage everything with the buttons below 👇\n"
        "Step-by-step guide: /help",
        reply_markup=main_kb(),
    )

@bot.on_message(filters.command("help") & filters.private)
async def help_cmd(client, message: Message):
    text = """📖 **STEP-BY-STEP GUIDE**

**1️⃣ ADD ACCOUNTS**
• Tap ➕ Add Account
• Send your phone number in international format — `+919876543210`
• Send the OTP you receive (enter the 2FA password if enabled)
• Session saved ✅ — add as many accounts as you want
• To remove one, tap 👥 My Accounts → ❌

**2️⃣ ADD GROUPS (GC)**
• Tap ➕ Add Group
• Send: username `@testgroup` / invite link `t.me/+xyz` / ID `-100123456789`
• Accounts auto-join via the invite link
• To remove one, tap 📋 My Groups → ❌

**3️⃣ CUSTOM MESSAGE**
• Tap ✏️ Custom Message → send your English quote
• Any length — always sent in full, never truncated

**4️⃣ PROMO PHOTO (optional)**
• Tap 🖼️ Promo Photo
• **Send Photo** → upload your own image (your message goes as caption)
• **Auto Generate** → a stylish image is created from your message
   — same font, emojis rendered properly 🎨
• If no photo is set, auto-generate is the default

**5️⃣ SET TIME**
• `5` = 5 minutes from now | `14:30` = today at 14:30 (tomorrow if already passed)

**6️⃣ START**
• Tap 🚀 START PROMO — sends photo + message to all groups from all accounts 🚀
• Tap 🛑 STOP PROMO to stop mid-run

**⚠️ NOTE:** Sending too fast may get your Telegram account **banned**.
Delays are set (3s msgs / 10s accounts) — change them at the top of the code.

/cancel — cancel any current step"""
    await message.reply_text(text)

@bot.on_message(filters.command("cancel") & filters.private)
async def cancel_cmd(client, message: Message):
    st = user_state.pop(message.chat.id, None)
    if st and "temp" in st:
        try:
            await st["temp"].stop()
        except Exception:
            pass
    await message.reply_text("❌ Cancelled. Back to main menu:", reply_markup=main_kb())

# ===================== CALLBACKS =====================
@bot.on_callback_query()
async def on_cb(client, cb: CallbackQuery):
    data = cb.data
    chat_id = cb.message.chat.id
    d = load_data()

    if data == "add_acc":
        user_state[chat_id] = {"step": "phone"}
        await cb.message.edit_text(
            "📱 **ADD ACCOUNT**\n\n"
            "Send your phone number in **international format**:\n`+919876543210`\n\n"
            "Cancel: /cancel",
            reply_markup=back_kb(),
        )
        await cb.answer(); return

    if data == "my_accs":
        if not d["accounts"]:
            await cb.answer("❌ No accounts added yet!", show_alert=True); return
        text = "👥 **MY ACCOUNTS**\n\n" + "\n".join(
            f"{i}. {a['name']}" for i, a in enumerate(d["accounts"], 1))
        await cb.message.edit_text(text, reply_markup=accs_kb(d))
        await cb.answer(); return

    if data.startswith("rm_acc:"):
        idx = int(data.split(":")[1])
        removed = d["accounts"].pop(idx)
        save_data(d)
        await cb.answer(f"✅ {removed['name']} removed", show_alert=True)
        if d["accounts"]:
            await cb.message.edit_text("👥 **MY ACCOUNTS**", reply_markup=accs_kb(d))
        else:
            await cb.message.edit_text("👥 No accounts left.", reply_markup=main_kb())
        return

    if data == "add_gc":
        user_state[chat_id] = {"step": "gc"}
        await cb.message.edit_text(
            "➕ **ADD GROUP (GC)**\n\n"
            "Send:\n• `https://t.me/+xyz` (invite link)\n• `@groupusername`\n• `-100123456789` (ID)\n\n"
            "Accounts will auto-join via the invite link.",
            reply_markup=back_kb(),
        )
        await cb.answer(); return

    if data == "my_gcs":
        if not d["groups"]:
            await cb.answer("❌ No groups added yet!", show_alert=True); return
        text = "📋 **MY GROUPS**\n\n" + "\n".join(
            f"{i}. {g['raw']}" for i, g in enumerate(d["groups"], 1))
        await cb.message.edit_text(text, reply_markup=groups_kb(d))
        await cb.answer(); return

    if data.startswith("rm_gc:"):
        idx = int(data.split(":")[1])
        d["groups"].pop(idx)
        save_data(d)
        await cb.answer("✅ Group removed", show_alert=True)
        if d["groups"]:
            await cb.message.edit_text("📋 **MY GROUPS**", reply_markup=groups_kb(d))
        else:
            await cb.message.edit_text("📋 No groups left.", reply_markup=main_kb())
        return

    if data == "set_msg":
        user_state[chat_id] = {"step": "msg"}
        await cb.message.edit_text(
            "✏️ **CUSTOM MESSAGE**\n\n"
            "Send your **English quote** — any length, rendered in full 📝\n\n"
            "Cancel: /cancel",
            reply_markup=back_kb(),
        )
        await cb.answer(); return

    if data == "photo_menu":
        await cb.message.edit_text(
            "🖼️ **PROMO PHOTO**\n\n"
            "• **Send Photo** — upload your own image (caption = your message)\n"
            "• **Auto Generate** — image created automatically from your message (emoji rendered properly 🎨)",
            reply_markup=photo_kb(d),
        )
        await cb.answer(); return

    if data == "photo_send":
        user_state[chat_id] = {"step": "photo"}
        await cb.message.edit_text(
            "🖼️ Now send your **photo** (no caption needed — your message is already saved)\n\n"
            "Cancel: /cancel",
            reply_markup=back_kb(),
        )
        await cb.answer(); return

    if data == "photo_rm":
        d["photo"] = ""
        save_data(d)
        await cb.answer("❌ Photo removed", show_alert=True)
        await cb.message.edit_text("🖼️ **PROMO PHOTO** — photo removed. Auto-generate is active again.",
                                   reply_markup=photo_kb(d))
        return

    if data == "set_time":
        user_state[chat_id] = {"step": "time"}
        await cb.message.edit_text(
            "⏰ **SET TIME**\n\n`5` = 5 minutes from now\n`14:30` = today at 14:30\n\nCancel: /cancel",
            reply_markup=back_kb(),
        )
        await cb.answer(); return

    if data == "status":
        await cb.message.edit_text(build_status(d), reply_markup=main_kb())
        await cb.answer(); return

    if data == "start_promo":
        missing = []
        if not d["accounts"]: missing.append("accounts")
        if not d["groups"]: missing.append("groups")
        if not d["message"]: missing.append("message")
        if not d["time"]: missing.append("time")
        if missing:
            await cb.answer(f"❌ Set these first: {', '.join(missing)}", show_alert=True); return
        if promo_state.get(chat_id):
            await cb.answer("⏳ Promo already running!", show_alert=True); return
        msg = await cb.message.edit_text("🚀 **PROMO IS STARTING...**")
        asyncio.create_task(run_promo(chat_id, msg.id))
        await cb.answer(); return

    if data == "stop_promo":
        ev = promo_state.get(chat_id)
        if ev:
            ev.set()
            await cb.answer("🛑 Stopping...")
        else:
            await cb.answer("No promo is running right now.")
        return

    if data == "back":
        st = user_state.pop(chat_id, None)
        if st and "temp" in st:
            try:
                await st["temp"].stop()
            except Exception:
                pass
        await cb.message.edit_text("👋 Main menu:", reply_markup=main_kb())
        await cb.answer(); return

# ===================== TEXT INPUT (FLOW STATE) =====================
@bot.on_message(filters.text & filters.private)
async def handle_text(client, message: Message):
    chat_id = message.chat.id
    st = user_state.get(chat_id)
    if not st:
        return
    text = message.text.strip()

    if st["step"] == "phone":
        phone = normalize_phone(text)
        if not phone:
            await message.reply_text("❌ Invalid number. Format: `+919876543210`")
            return
        await message.reply_text("⏳ Sending OTP...")
        try:
            temp = Client(f"tmp_{chat_id}", API_ID, API_HASH, in_memory=True)
            await temp.connect()
            sent = await temp.send_code(phone)
        except FloodWait as e:
            await message.reply_text(f"⚠️ FloodWait: {e.x} sec — try again later.")
            return
        except Exception as e:
            user_state.pop(chat_id, None)
            await message.reply_text(f"❌ Error: {e}\n\nPress /start to try again.")
            return
        user_state[chat_id] = {"step": "code", "temp": temp, "phone": phone, "ph": sent.phone_code_hash}
        await message.reply_text(f"📲 Enter the OTP sent to **{phone}**:", reply_markup=back_kb())

    elif st["step"] == "code":
        temp = st["temp"]
        try:
            await temp.sign_in(st["phone"], st["ph"], text)
        except SessionPasswordNeeded:
            user_state[chat_id]["step"] = "pass"
            await message.reply_text("🔐 This account has **2FA password** enabled — send the password:")
            return
        except (PhoneCodeInvalid, PhoneCodeExpired):
            await message.reply_text("❌ Invalid/expired code. Press /cancel and request a new OTP.")
            return
        except FloodWait as e:
            await message.reply_text(f"⚠️ FloodWait: {e.x} sec — wait.")
            return
        except Exception as e:
            await temp.stop()
            user_state.pop(chat_id, None)
            await message.reply_text(f"❌ Error: {e}\n\nPress /start to try again.", reply_markup=main_kb())
            return
        session = await temp.export_session_string()
        await temp.stop()
        d = load_data()
        d["accounts"].append({"name": st["phone"], "session": session,
                              "added": datetime.now().isoformat()})
        save_data(d)
        user_state.pop(chat_id, None)
        await message.reply_text(
            f"✅ **Account added!**\n\n📱 {st['phone']}\nTotal: {len(d['accounts'])} accounts",
            reply_markup=main_kb())

    elif st["step"] == "pass":
        temp = st["temp"]
        try:
            await temp.check_password(text)
        except Exception as e:
            await message.reply_text(f"❌ Wrong password: {e}\nSend it again:")
            return
        session = await temp.export_session_string()
        await temp.stop()
        d = load_data()
        d["accounts"].append({"name": st["phone"], "session": session,
                              "added": datetime.now().isoformat()})
        save_data(d)
        user_state.pop(chat_id, None)
        await message.reply_text(
            f"✅ **Account added!**\n\n📱 {st['phone']}\nTotal: {len(d['accounts'])} accounts",
            reply_markup=main_kb())

    elif st["step"] == "gc":
        entry = parse_group(text)
        if entry is None:
            await message.reply_text("❌ Format not recognized. Send a link/username/ID, or /cancel.")
            return
        user_state.pop(chat_id, None)
        await message.reply_text("⏳ Adding group (accounts are joining via invite link)...")
        await add_group_entry(entry, message)
        d = load_data()
        await message.reply_text(
            f"✅ **Group added!**\n\n{entry['raw']}\nTotal groups: {len(d['groups'])}",
            reply_markup=main_kb())

    elif st["step"] == "msg":
        d = load_data()
        d["message"] = message.text
        save_data(d)
        user_state.pop(chat_id, None)
        preview = message.text[:80] + ("..." if len(message.text) > 80 else "")
        await message.reply_text(
            f"✅ **Message saved!** ({len(message.text)} chars) — sent in full\n\nPreview:\n{preview}",
            reply_markup=main_kb())

    elif st["step"] == "time":
        t = text.replace(" ", "")
        try:
            compute_target(t)
        except Exception:
            await message.reply_text("❌ Invalid format. Send `5` (minutes) or `14:30` (time).")
            return
        d = load_data()
        d["time"] = t
        save_data(d)
        user_state.pop(chat_id, None)
        await message.reply_text(f"✅ Time set: **{t}**", reply_markup=main_kb())

# ===================== PHOTO UPLOAD =====================
@bot.on_message(filters.photo & filters.private)
async def handle_photo(client, message: Message):
    chat_id = message.chat.id
    st = user_state.get(chat_id)
    if not st or st["step"] != "photo":
        return  # not in photo mode, ignore
    await message.reply_text("⏳ Saving photo...")
    os.makedirs(PHOTO_DIR, exist_ok=True)
    path = await message.download(file_name=os.path.join(PHOTO_DIR, "promo_photo.jpg"))
    if not path:
        await message.reply_text("❌ Download failed. Try again.")
        return
    d = load_data()
    d["photo"] = path
    d["auto_image"] = False
    save_data(d)
    user_state.pop(chat_id, None)
    await message.reply_text(
        "🖼️ **Photo set!** ✅\n\n"
        "The promo will send the photo + your message (as caption).\n"
        "Press /start and tap 🚀 START PROMO.",
        reply_markup=main_kb())

# ===================== MAIN =====================
if __name__ == "__main__":
    print("🤖 Promo Bot v2 starting...")
    bot.run()
