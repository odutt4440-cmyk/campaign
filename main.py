#!/usr/bin/env python3
"""
🤖 TELEGRAM PROMO BOT v2.3 (ULTRACLEAN & FIXED EDITION)
------------------------------------------------------
+ Full English quote support (never truncated)
+ 🖼️ Photo: custom image upload or auto-generated image
+ 🎨 Auto Image: message text -> stylish image (same font, emoji rendered properly)
+ ⏰ Two time modes: One-Time schedule OR 🔁 Loop Mode (repeat every X minutes)
+ 🌐 Promo My GCs: send to ALL groups where the account is already a member (auto-discover)
+ ✉️ Promo My DMs: send to ALL private chats of the account (auto-discover)
+ 💬 Promo DM + GC: DMs + groups dono ek hi run me
+ 🔄 STOP/DONE ke baad Restart + Main Menu buttons
+ ⏰ Smart time parsing (13:40 / 1340 / 13 40 / 13.40)
+ 🔧 PEER RESOLUTION & DISCOVERY FIX: Auto-cache peers & safe scope entries handling
"""

import asyncio
import io
import json
import os
from dotenv import load_dotenv
load_dotenv()
import re
from datetime import datetime, timedelta

from pyrogram import Client, filters
from pyrogram.enums import ChatType
from pyrogram.errors import (FloodWait, PasswordHashInvalid, PhoneCodeExpired,
                             PhoneCodeInvalid, SessionPasswordNeeded,
                             UserAlreadyParticipant)
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
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

if not API_ID or not API_HASH or not BOT_TOKEN:
    raise SystemExit(
        "❌ Missing config!\n"
        "Create a .env file in this folder:\n"
        "API_ID=1336473\n"
        "API_HASH=your_real_hash\n"
        "BOT_TOKEN=your_real_token"
    )

# Delays to avoid flooding/bans (seconds)
DELAY_BETWEEN_MSGS = 3
DELAY_BETWEEN_ACCOUNTS = 10

bot = Client("promo_manager", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

user_state = {}
promo_state = {}
promo_scope = {}   # last scope remember karta hai (🔄 Restart ke liye)

# ===================== SAFE CLIENT STOP =====================
async def safe_stop(client):
    """Stops a client safely — never crashes even if it's already stopped."""
    if client is None:
        return
    try:
        await client.stop()
    except Exception:
        pass

# ===================== SESSION FILE =====================
async def deliver_session(message, phone, session):
    """Sends the session string as session_<phone>.txt so the user can
    reuse it in any other Pyrogram tool."""
    try:
        buf = io.BytesIO(session.encode("utf-8"))
        buf.name = f"session_{phone}.txt"
        await message.reply_document(
            buf,
            caption=(
                "🔑 **Session file generated**\n\n"
                f"`{phone}`\n\n"
                "This string = full access to this Telegram account. "
                "Never share it with anyone.\n"
                "You can reuse it in any Pyrogram client as a session string."
            ),
        )
    except Exception:
        pass

# ===================== DATA STORE (per-user) =====================
def data_path(uid):
    return f"data_{uid}.json"

def default_data():
    return {"accounts": [], "groups": [], "message": "",
            "time": "", "running": False, "photo": "", "auto_image": True,
            "mode": "once", "interval": 0}

def load_data(uid):
    path = data_path(uid)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default_data()

def save_data(data, uid):
    with open(data_path(uid), "w", encoding="utf-8") as f:
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

    draw.rectangle([0, 0, IMG_WIDTH, 10], fill=IMG_ACCENT)
    q_font = ImageFont.truetype(fp, 90)
    draw.text((pad, pad - 55), "\u201C", font=q_font, fill=IMG_ACCENT)

    with Pilmoji(img) as pmj:
        pmj.text((pad, pad + 20), "\n".join(lines), font=font,
                 fill=IMG_FG, spacing=12,
                 emoji_scale_factor=1.25, emoji_position_offset=(0, 4))

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
        [InlineKeyboardButton("🚀 START PROMO", callback_data="start_promo"),
         InlineKeyboardButton("🌐 Promo My GCs", callback_data="promo_all")],
        [InlineKeyboardButton("✉️ Promo My DMs", callback_data="promo_dm"),
         InlineKeyboardButton("💬 Promo DM + GC", callback_data="promo_dm_gc")],
    ])

def back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back")]])

def stop_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🛑 STOP PROMO", callback_data="stop_promo")]])

def restart_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Restart Promo", callback_data="restart_promo")],
        [InlineKeyboardButton("📋 Main Menu", callback_data="back")],
    ])

def time_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🕐 One-Time Schedule", callback_data="time_once")],
        [InlineKeyboardButton("🔁 Loop Mode (repeat)", callback_data="time_loop")],
        [InlineKeyboardButton("🔙 Back", callback_data="back")],
    ])

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

def normalize_phone(raw):
    t = raw.strip().replace(" ", "")
    if not t.startswith("+"):
        t = "+" + t
    if re.fullmatch(r"\+\d{7,15}", t):
        return t
    return None

def parse_group(raw):
    t = raw.strip()
    m = re.search(r"t\.me/\+([A-Za-z0-9_\-]+)", t)
    if m:
        return {"type": "invite", "value": m.group(1), "raw": t, "ids": {}}
    m = re.search(r"t\.me/([A-Za-z0-9_]{5,})", t)
    if m:
        return {"type": "username", "value": m.group(1), "raw": t, "ids": {}}
    m = re.fullmatch(r"@([A-Za-z0-9_]{5,})", t)
    if m:
        return {"type": "username", "value": m.group(1), "raw": t, "ids": {}}
    m = re.fullmatch(r"(-?\d{9,15})", t)
    if m:
        return {"type": "id", "value": int(t), "raw": t, "ids": {}}
    return None

def parse_time_input(raw):
    t = raw.strip().replace(" ", "").replace(".", ":")
    m = re.fullmatch(r"(\d{1,2}):(\d{1,2})", t)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return ("clock", hh, mm)
    m = re.fullmatch(r"(\d{4})", t)
    if m:
        hh, mm = int(t[:2]), int(t[2:])
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return ("clock", hh, mm)
    if re.fullmatch(r"\d+", t):
        return ("minutes", 0, int(t))
    return None

def compute_target(time_str):
    parsed = parse_time_input(time_str)
    if parsed is None:
        raise ValueError("invalid time format")
    kind, a, b = parsed
    if kind == "clock":
        now = datetime.now()
        target = now.replace(hour=a, minute=b, second=0, microsecond=0)
        return target
    return datetime.now() + timedelta(minutes=b)

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
    mode = d.get("mode", "once")
    if mode == "loop":
        lines.append(f"🔁 Mode: LOOP — every {d.get('interval', 0)} min (until stopped)")
    else:
        lines.append(f"⏰ Time: {d['time'] or '❌ not set'}")
    lines.append(f"▶️ Running: {'✅ YES' if d.get('running') else '❌ NO'}")
    return "\n".join(lines)

def promo_missing(d, scope="saved"):
    missing = []
    if not d["accounts"]: missing.append("accounts")
    if scope == "saved" and not d["groups"]: missing.append("groups")
    if not d["message"]: missing.append("message")
    mode = d.get("mode", "once")
    if mode == "loop":
        if not d.get("interval"):
            missing.append("loop interval (⏰ Set Time → 🔁 Loop Mode)")
    else:
        if not d["time"]:
            missing.append("time (⏰ Set Time → 🕐 One-Time)")
    return missing

# ===================== GROUP & DM DISCOVERY (FIXED) =====================
async def warm_peers(user, limit=500):
    """Warms up local peer cache so get_chat(id) doesn't fail."""
    count = 0
    try:
        async for dialog in user.get_dialogs(limit=limit):
            count += 1
    except Exception as e:
        print(f"[PEER WARMUP ERROR] {e}")
    return count

async def discover_groups(user, limit=500):
    found = []
    try:
        async for dialog in user.get_dialogs(limit=limit):
            try:
                if dialog.chat and dialog.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
                    found.append(dialog.chat)
            except Exception:
                continue
    except Exception as e:
        print(f"[DISCOVERY GC ERROR] {e}")
    return found

async def discover_dms(user, limit=500):
    found = []
    try:
        me = (await user.get_me()).id
        async for dialog in user.get_dialogs(limit=limit):
            try:
                if dialog.chat and dialog.chat.type == ChatType.PRIVATE and dialog.chat.id != me:
                    found.append(dialog.chat)
            except Exception:
                continue
    except Exception as e:
        print(f"[DISCOVERY DM ERROR] {e}")
    return found

async def discover_all(user, limit=500):
    found = []
    try:
        me = (await user.get_me()).id
        async for dialog in user.get_dialogs(limit=limit):
            try:
                c = dialog.chat
                if c and (c.type in (ChatType.GROUP, ChatType.SUPERGROUP) or (c.type == ChatType.PRIVATE and c.id != me)):
                    found.append(c)
            except Exception:
                continue
    except Exception as e:
        print(f"[DISCOVERY ALL ERROR] {e}")
    return found

def scope_entries(scope, chats):
    entries = []
    for c in chats:
        name = getattr(c, "title", None) or getattr(c, "first_name", None) or str(c.id)
        entries.append({
            "type": "id",
            "value": c.id,
            "raw": f"{name} ({c.id})",
            "ids": {}
        })
    return entries

async def add_group_entry(entry, chat_id):
    d = load_data(chat_id)
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
    save_data(d, chat_id)

async def resolve_chat_id(user, entry, acc_name):
    if entry["type"] == "id":
        cid = entry["value"]
        try:
            chat = await user.get_chat(cid)
            return chat.id, None
        except Exception:
            # Fallback: send directly using ID if peer exists in user cache
            return cid, None

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
    
    chat_id = entry["ids"].get(acc_name)
    if chat_id is not None:
        try:
            await user.get_chat(chat_id)
            return chat_id, None
        except Exception:
            pass
    try:
        chat = await user.join_chat(f"https://t.me/+{entry['value']}")
        entry["ids"][acc_name] = chat.id
        return chat.id, None
    except UserAlreadyParticipant:
        await warm_peers(user)
        cid = entry["ids"].get(acc_name)
        if cid is not None:
            return cid, None
        return None, "Chat ID could not be resolved"
    except Exception as e:
        return None, f"join failed: {e}"

async def send_payload(user, chat_id, d, stop_event, force_text=False):
    text = d["message"]
    photo = d.get("photo", "") or ""
    auto = d.get("auto_image", True)

    if force_text:
        remaining = split_text(text)
    else:
        if photo and os.path.exists(photo):
            caption = text[:1024]
            rest = text[1024:]
            try:
                await user.send_photo(chat_id, photo, caption=caption)
                remaining = split_text(rest) if rest else []
            except Exception:
                remaining = split_text(text)
        elif auto:
            try:
                img_path = generate_image_file(text)
                try:
                    await user.send_photo(chat_id, img_path)
                    remaining = split_text(text) if AUTO_SEND_TEXT else []
                except Exception:
                    remaining = split_text(text)
            except Exception:
                remaining = split_text(text)
        else:
            remaining = split_text(text)

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
    force_text = False
    try:
        res = await send_payload(user, chat_id, d, stop_event, force_text=force_text)
        return "✅" if res == "✅" else f"❌ {res}"
    except FloodWait as e:
        await asyncio.sleep(min(e.x, 300))
        res = await send_payload(user, chat_id, d, stop_event, force_text=force_text)
        return "✅" if res == "✅" else f"❌ {res}"

# ===================== PROMO RUNNER =====================
async def run_promo(chat_id, progress_msg_id, scope="saved"):
    d = load_data(chat_id)
    accounts, groups = d["accounts"], d["groups"]
    time_str = d["time"]
    mode = d.get("mode", "once")
    interval = int(d.get("interval", 0) or 0)

    ev = asyncio.Event()
    promo_state[chat_id] = ev
    promo_scope[chat_id] = scope
    d["running"] = True
    save_data(d, chat_id)

    scope_name = {"saved": "📋 SAVED GROUPS", "all_gc": "🌐 ALL MY GCS",
                  "dm": "✉️ MY DMs", "dm_gc": "💬 DMs + GCS"}.get(scope, "📋 SAVED GROUPS")

    results = []
    try:
        if mode == "loop":
            wait_until = datetime.now()
            await bot.edit_message_text(
                chat_id, progress_msg_id,
                f"🔁 **PROMO STARTING — {scope_name} (LOOP MODE)**\n\n"
                f"📱 Accounts: {len(accounts)}\n"
                f"⏱ Interval: every {interval} min\n"
                f"▶️ Runs now, then repeats until you stop it.\n\n"
                f"Tap 🛑 to stop.",
                reply_markup=stop_kb(),
            )
        else:
            try:
                wait_until = compute_target(time_str)
            except Exception:
                wait_until = datetime.now()
            delta = (wait_until - datetime.now()).total_seconds()
            if delta > 0:
                await bot.edit_message_text(
                    chat_id, progress_msg_id,
                    f"⏳ **PROMO SCHEDULED — {scope_name}**\n\n"
                    f"📱 Accounts: {len(accounts)}\n"
                    f"⏰ Run at: **{wait_until.strftime('%H:%M:%S')}**\n\n"
                    f"Tap 🛑 to stop.",
                    reply_markup=stop_kb(),
                )

        run_number = 0
        while True:
            while datetime.now() < wait_until:
                if ev.is_set():
                    break
                await asyncio.sleep(min(5, (wait_until - datetime.now()).total_seconds()))
            if ev.is_set():
                break

            run_number += 1
            results = []
            for i, acc in enumerate(accounts, 1):
                if ev.is_set():
                    results.append(f"🛑 {acc['name']}: stopped")
                    break
                await bot.edit_message_text(
                    chat_id, progress_msg_id,
                    f"⏳ **Run #{run_number}** — {acc['name']} → starting process... ({i}/{len(accounts)})",
                    reply_markup=stop_kb(),
                )
                ok = fail = 0
                entries = groups
                try:
                    async with Client(f"pr_{chat_id}_{i}", API_ID, API_HASH,
                                      session_string=acc["session"], in_memory=True) as user:
                        
                        # --- CLEAN DISCOVERY & PEER WARMUP BLOCK ---
                        if scope != "saved":
                            await bot.edit_message_text(
                                chat_id, progress_msg_id,
                                f"🔎 **DISCOVERING CHATS ({scope_name})**\n\n"
                                f"👤 Account: `{acc['name']}`\n"
                                f"📡 Fetching targets, please wait...",
                                reply_markup=stop_kb(),
                            )
                            
                            chats = []
                            if scope == "all_gc":
                                chats = await discover_groups(user, limit=500)
                            elif scope == "dm":
                                chats = await discover_dms(user, limit=500)
                            elif scope == "dm_gc":
                                chats = await discover_all(user, limit=500)
                                
                            entries = scope_entries(scope, chats)
                            
                            await bot.edit_message_text(
                                chat_id, progress_msg_id,
                                f"⚡ **DISCOVERY DONE** — Found `{len(entries)}` targets.\n"
                                f"👤 Sending messages via `{acc['name']}`...",
                                reply_markup=stop_kb(),
                            )
                        else:
                            await warm_peers(user)

                        for entry in entries:
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
                
                extra = f" ({len(entries)} targets)" if scope != "saved" else ""
                results.append(f"{'✅' if fail == 0 else '⚠️'} {acc['name']}: {ok} ok / {fail} fail{extra}")
                await asyncio.sleep(DELAY_BETWEEN_ACCOUNTS)

            if mode == "loop" and not ev.is_set():
                next_run = datetime.now() + timedelta(minutes=interval)
                await bot.edit_message_text(
                    chat_id, progress_msg_id,
                    f"🔁 **RUN #{run_number} DONE** ✅\n\n" + "\n".join(results) +
                    f"\n\n⏱ Next run: **{next_run.strftime('%H:%M:%S')}** (every {interval} min)\n"
                    f"Tap 🛑 to stop the loop.",
                    reply_markup=stop_kb(),
                )
                wait_until = next_run
            else:
                await bot.edit_message_text(
                    chat_id, progress_msg_id,
                    f"🏁 **PROMO DONE — {scope_name}**\n\n" + "\n".join(results),
                    reply_markup=restart_kb(),
                )
                break

        if ev.is_set():
            txt = "🛑 **PROMO STOPPED**"
            if results:
                txt += "\n\n" + "\n".join(results)
            await bot.edit_message_text(chat_id, progress_msg_id, txt, reply_markup=restart_kb())
    finally:
        d = load_data(chat_id)
        d["running"] = False
        save_data(d, chat_id)
        promo_state.pop(chat_id, None)

# ===================== COMMANDS =====================
@bot.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message: Message):
    st = user_state.pop(message.chat.id, None)
    await safe_stop(st.get("temp") if st else None)
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
• Tap ➕ Add Account & follow prompt

**2️⃣ ADD GROUPS / DISCOVER ALL**
• Add groups manually or tap 🌐 **Promo My GCs** / ✉️ **Promo My DMs** / 💬 **Promo DM + GC**

**3️⃣ CUSTOM MESSAGE & PHOTO**
• Save your quote message and optionally set a custom promo photo.

**4️⃣ SET TIME & START**
• Select time mode and hit 🚀 **START PROMO**.
"""
    await message.reply_text(text)

@bot.on_message(filters.command("cancel") & filters.private)
async def cancel_cmd(client, message: Message):
    st = user_state.pop(message.chat.id, None)
    await safe_stop(st.get("temp") if st else None)
    await message.reply_text("❌ Cancelled. Back to main menu:", reply_markup=main_kb())

# ===================== CALLBACKS =====================
@bot.on_callback_query()
async def on_cb(client, cb: CallbackQuery):
    data = cb.data
    chat_id = cb.message.chat.id
    d = load_data(chat_id)

    if data == "add_acc":
        user_state[chat_id] = {"step": "phone"}
        await cb.message.edit_text(
            "📱 **ADD ACCOUNT**\n\nSend your phone number in **international format**:\n`+919876543210`\n\nCancel: /cancel",
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
        save_data(d, chat_id)
        await cb.answer(f"✅ {removed['name']} removed", show_alert=True)
        if d["accounts"]:
            await cb.message.edit_text("👥 **MY ACCOUNTS**", reply_markup=accs_kb(d))
        else:
            await cb.message.edit_text("👥 No accounts left.", reply_markup=main_kb())
        return

    if data == "add_gc":
        user_state[chat_id] = {"step": "gc"}
        await cb.message.edit_text(
            "➕ **ADD GROUP (GC)**\n\nSend link / username / ID:",
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
        save_data(d, chat_id)
        await cb.answer("✅ Group removed", show_alert=True)
        if d["groups"]:
            await cb.message.edit_text("📋 **MY GROUPS**", reply_markup=groups_kb(d))
        else:
            await cb.message.edit_text("📋 No groups left.", reply_markup=main_kb())
        return

    if data == "set_msg":
        user_state[chat_id] = {"step": "msg"}
        await cb.message.edit_text("✏️ **CUSTOM MESSAGE**\n\nSend your message text:", reply_markup=back_kb())
        await cb.answer(); return

    if data == "photo_menu":
        await cb.message.edit_text("🖼️ **PROMO PHOTO**", reply_markup=photo_kb(d))
        await cb.answer(); return

    if data == "photo_send":
        user_state[chat_id] = {"step": "photo"}
        await cb.message.edit_text("🖼️ Send your photo now:", reply_markup=back_kb())
        await cb.answer(); return

    if data == "photo_rm":
        d["photo"] = ""
        save_data(d, chat_id)
        await cb.answer("❌ Photo removed", show_alert=True)
        await cb.message.edit_text("🖼️ Photo removed.", reply_markup=photo_kb(d))
        return

    if data == "set_time":
        await cb.message.edit_text("⏰ **SET TIME — choose a mode**", reply_markup=time_kb())
        await cb.answer(); return

    if data == "time_once":
        user_state[chat_id] = {"step": "time", "sub": "once"}
        await cb.message.edit_text("🕐 Send time (e.g., `5` or `13:40`):", reply_markup=back_kb())
        await cb.answer(); return

    if data == "time_loop":
        user_state[chat_id] = {"step": "time", "sub": "loop"}
        await cb.message.edit_text("🔁 Send interval in minutes:", reply_markup=back_kb())
        await cb.answer(); return

    if data == "status":
        await cb.message.edit_text(build_status(d), reply_markup=main_kb())
        await cb.answer(); return

    if data in ("start_promo", "promo_all", "promo_dm", "promo_dm_gc"):
        scope = {"start_promo": "saved", "promo_all": "all_gc",
                 "promo_dm": "dm", "promo_dm_gc": "dm_gc"}[data]
        missing = promo_missing(d, scope)
        if missing:
            await cb.answer(f"❌ Set these first: {', '.join(missing)}", show_alert=True); return
        if promo_state.get(chat_id):
            await cb.answer("⏳ Promo already running!", show_alert=True); return
        
        msg = await cb.message.edit_text("🚀 **INITIALIZING PROMO...**")
        asyncio.create_task(run_promo(chat_id, msg.id, scope))
        await cb.answer(); return

    if data == "restart_promo":
        scope = promo_scope.get(chat_id) or "saved"
        missing = promo_missing(d, scope)
        if missing:
            await cb.answer(f"❌ Set these first: {', '.join(missing)}", show_alert=True); return
        if promo_state.get(chat_id):
            await cb.answer("⏳ Promo already running!", show_alert=True); return
        msg = await cb.message.edit_text("🚀 **RESTARTING PROMO...**")
        asyncio.create_task(run_promo(chat_id, msg.id, scope))
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
        await safe_stop(st.get("temp") if st else None)
        await cb.message.edit_text("👋 Main menu:", reply_markup=main_kb())
        await cb.answer(); return

# ===================== TEXT INPUT =====================
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
        except Exception as e:
            user_state.pop(chat_id, None)
            await message.reply_text(f"❌ Error: {e}\n\nPress /start to try again.")
            return
        user_state[chat_id] = {"step": "code", "temp": temp, "phone": phone, "ph": sent.phone_code_hash}
        await message.reply_text(f"📲 Enter OTP sent to **{phone}**:", reply_markup=back_kb())

    elif st["step"] == "code":
        temp = st["temp"]
        try:
            if not temp.is_connected:
                await temp.connect()
            await temp.sign_in(st["phone"], st["ph"], text)
        except SessionPasswordNeeded:
            user_state[chat_id]["step"] = "pass"
            await message.reply_text("🔐 Enter 2FA Password:", reply_markup=back_kb())
            return
        except PhoneCodeInvalid:
            await message.reply_text("❌ Wrong code. Try again:")
            return
        except Exception as e:
            await safe_stop(temp)
            user_state.pop(chat_id, None)
            await message.reply_text(f"❌ Error: {e}", reply_markup=main_kb())
            return

        session = await temp.export_session_string()
        d = load_data(chat_id)
        d["accounts"].append({"name": st["phone"], "session": session, "added": datetime.now().isoformat()})
        save_data(d, chat_id)
        user_state.pop(chat_id, None)
        await safe_stop(temp)
        await message.reply_text("✅ **Account added!**", reply_markup=main_kb())
        await deliver_session(message, st["phone"], session)

    elif st["step"] == "pass":
        temp = st["temp"]
        try:
            if not temp.is_connected:
                await temp.connect()
            await temp.check_password(text)
        except Exception as e:
            await safe_stop(temp)
            user_state.pop(chat_id, None)
            await message.reply_text(f"❌ Error: {e}", reply_markup=main_kb())
            return

        session = await temp.export_session_string()
        d = load_data(chat_id)
        d["accounts"].append({"name": st["phone"], "session": session, "added": datetime.now().isoformat()})
        save_data(d, chat_id)
        user_state.pop(chat_id, None)
        await safe_stop(temp)
        await message.reply_text("✅ **Account added!**", reply_markup=main_kb())
        await deliver_session(message, st["phone"], session)

    elif st["step"] == "gc":
        entry = parse_group(text)
        if entry is None:
            await message.reply_text("❌ Invalid format.")
            return
        user_state.pop(chat_id, None)
        await add_group_entry(entry, chat_id)
        await message.reply_text("✅ **Group added!**", reply_markup=main_kb())

    elif st["step"] == "msg":
        d = load_data(chat_id)
        d["message"] = message.text
        save_data(d, chat_id)
        user_state.pop(chat_id, None)
        await message.reply_text("✅ **Message saved!**", reply_markup=main_kb())

    elif st["step"] == "time":
        t = text.replace(" ", "").replace(".", ":")
        sub = st.get("sub", "once")
        if sub == "loop":
            try:
                interval = int(t)
            except ValueError:
                await message.reply_text("❌ Send interval in minutes.")
                return
            d = load_data(chat_id)
            d["mode"] = "loop"
            d["interval"] = interval
            save_data(d, chat_id)
            user_state.pop(chat_id, None)
            await message.reply_text("✅ **Loop Mode set!**", reply_markup=main_kb())
        else:
            d = load_data(chat_id)
            d["mode"] = "once"
            d["time"] = t
            save_data(d, chat_id)
            user_state.pop(chat_id, None)
            await message.reply_text(f"✅ Time set: **{t}**", reply_markup=main_kb())

# ===================== PHOTO UPLOAD =====================
@bot.on_message(filters.photo & filters.private)
async def handle_photo(client, message: Message):
    chat_id = message.chat.id
    st = user_state.get(chat_id)
    if not st or st["step"] != "photo":
        return
    os.makedirs(PHOTO_DIR, exist_ok=True)
    path = await message.download(file_name=os.path.join(PHOTO_DIR, "promo_photo.jpg"))
    d = load_data(chat_id)
    d["photo"] = path
    d["auto_image"] = False
    save_data(d, chat_id)
    user_state.pop(chat_id, None)
    await message.reply_text("🖼️ **Photo set!** ✅", reply_markup=main_kb())

# ===================== MAIN =====================
if __name__ == "__main__":
    for fname in os.listdir("."):
        if fname.startswith("data_") and fname.endswith(".json"):
            try:
                with open(fname, "r", encoding="utf-8") as f:
                    dd = json.load(f)
                if dd.get("running"):
                    dd["running"] = False
                    with open(fname, "w", encoding="utf-8") as f:
                        json.dump(dd, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
    print("🤖 Promo Bot v2.3 starting...")
    bot.run()
