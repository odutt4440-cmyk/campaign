#!/usr/bin/env python3
"""
🤖 TELEGRAM PROMO BOT v2
------------------------
+ Full English quote support (never truncated)
+ 🖼️ Photo: custom image upload or auto-generated image
+ 🎨 Auto Image: message text -> stylish image (same font, emoji rendered properly)
+ ⏰ Two time modes: One-Time schedule OR 🔁 Loop Mode (repeat every X minutes)
+ 🌐 NEW: "Promo in ALL GCs" — sends to every group/channel the account is a member of
+ 🔐 NEW: per-user private data (nobody sees another user's accounts/groups)
+ 🔑 NEW: session.txt is given to the user after login (usable anywhere)
+ 🛑 FIX: STOP PROMO → message becomes "PROMO STOPPED" with RESTART + Menu buttons
+ 🔇 FIX: "Peer id invalid" console spam is silenced (cosmetic noise only)

Install: pip install pyrogram tgcrypto pillow pilmoji requests python-dotenv
Font:    put any .ttf (Poppins/Montserrat) in the bot folder,
         otherwise the default DejaVu font is used
"""

import asyncio
import glob
import io
import json
import os
from dotenv import load_dotenv
load_dotenv()
import re
from datetime import datetime, timedelta

from pyrogram import Client, filters, idle
from pyrogram.errors import (FloodWait, PasswordHashInvalid, PhoneCodeExpired,
                             PhoneCodeInvalid, SessionPasswordNeeded,
                             UserAlreadyParticipant)
from pyrogram.types import (CallbackQuery, InlineKeyboardButton,
                            InlineKeyboardMarkup, Message)

# ===================== PYROGRAM COMPAT SHIM =====================
# Silences the cosmetic "Peer id invalid" tracebacks that Pyrogram's
# update loop prints for chats not yet in its local storage.
# 1) quieter pyrogram logs
# 2) get_peer_type never raises for unknown peers
# 3) handle_updates drops unresolvable-peer updates silently
# 4) asyncio loop handler swallows leftover task noise
import logging as _logging
_logging.getLogger("pyrogram").setLevel(_logging.ERROR)

import pyrogram.utils as _pyro_utils

_orig_get_peer_type = getattr(_pyro_utils, "get_peer_type", None)
if _orig_get_peer_type is not None:
    def _safe_get_peer_type(peer_id):
        try:
            return _orig_get_peer_type(peer_id)
        except ValueError:
            return "channel" if peer_id < 0 else "user"
    _pyro_utils.get_peer_type = _safe_get_peer_type

_QUIET_NOISE = ("Peer id invalid", "ID not found", "Connection lost",
                "ConnectionResetError", "ConnectionClosed",
                "CHANNEL_INVALID", "PEER_ID_INVALID")

try:
    import pyrogram.client as _pyro_client
    _orig_handle_updates = _pyro_client.Client.handle_updates

    async def _safe_handle_updates(self, updates):
        try:
            return await _orig_handle_updates(self, updates)
        except Exception as _e:
            _t = f"{type(_e).__name__}: {_e}"
            if any(_k in _t for _k in _QUIET_NOISE):
                return None
            raise

    _pyro_client.Client.handle_updates = _safe_handle_updates
except Exception:
    pass


def _quiet_exception_handler(loop, context):
    """Swallows Pyrogram's leftover asyncio task noise — cosmetic only."""
    exc = context.get("exception")
    text = f"{type(exc).__name__}: {exc}" if exc else str(context.get("message", ""))
    if any(k in text for k in _QUIET_NOISE):
        return
    loop.default_exception_handler(context)

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

DATA_FILE = "data.json"

# Delays to avoid flooding/bans (seconds)
DELAY_BETWEEN_MSGS = 3
DELAY_BETWEEN_ACCOUNTS = 10

# Chat types allowed in "Promo in ALL GCs" (works on both Pyrogram v1 & v2)
try:
    from pyrogram.enums import ChatType
    _CHAT_TYPES = (ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL)
except Exception:
    _CHAT_TYPES = ("group", "supergroup", "channel")

bot = Client("promo_manager", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

user_state = {}
promo_state = {}

# ===================== SAFE CLIENT STOP =====================
async def safe_stop(client):
    """Stops a client safely — never crashes even if it's already stopped."""
    if client is None:
        return
    try:
        await client.stop()
    except Exception:
        pass

# ===================== DATA STORE (PER-USER) =====================
def data_path(uid=None):
    """Each user gets their own file → nobody sees anyone else's data."""
    return DATA_FILE if uid is None else f"data_{uid}.json"

def load_data(uid=None):
    path = data_path(uid)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"accounts": [], "groups": [], "message": "",
            "time": "", "running": False, "photo": "", "auto_image": True,
            "mode": "once", "interval": 0}

def save_data(uid, data):
    path = data_path(uid)
    with open(path, "w", encoding="utf-8") as f:
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
        [InlineKeyboardButton("🌐 Promo in ALL GCs (auto)", callback_data="promo_all")],
    ])

def back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back")]])

def stop_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🛑 STOP PROMO", callback_data="stop_promo")]])

def stopped_kb():
    """Shown after STOP: restart with the same saved settings + main menu."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 RESTART PROMO", callback_data="restart_promo")],
        [InlineKeyboardButton("🏠 Menu", callback_data="back")],
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
    """Returns international format like +919876543210 or None."""
    t = raw.strip().replace(" ", "")
    if not t.startswith("+"):
        t = "+" + t
    if re.fullmatch(r"\+\d{7,15}", t):
        return t
    return None

def parse_group(raw):
    t = raw.strip()
    # invite link: https://t.me/+xyz or t.me/+xyz
    m = re.search(r"t\.me/\+([A-Za-z0-9_\-]+)", t)
    if m:
        return {"type": "invite", "value": m.group(1), "raw": t, "ids": {}}
    # username: https://t.me/name / t.me/name / @name
    m = re.search(r"t\.me/([A-Za-z0-9_]{5,})", t)
    if m:
        return {"type": "username", "value": m.group(1), "raw": t, "ids": {}}
    m = re.fullmatch(r"@([A-Za-z0-9_]{5,})", t)
    if m:
        return {"type": "username", "value": m.group(1), "raw": t, "ids": {}}
    # numeric ID
    m = re.fullmatch(r"(-?\d{9,15})", t)
    if m:
        return {"type": "id", "value": int(t), "raw": t, "ids": {}}
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

def short_results(results, cap=25):
    """Truncates long result lists so the progress message never
    exceeds Telegram's 4096-char edit limit (which used to kill
    the promo task silently and freeze the message on STOPPING)."""
    out = list(results)
    if len(out) > cap:
        out = out[:cap] + [f"... and {len(results) - cap} more lines"]
    return out

async def safe_edit(chat_id, msg_id, text, kb=None):
    """Edits the progress message without ever crashing the promo task."""
    try:
        await bot.edit_message_text(chat_id, msg_id, text[:4000], reply_markup=kb)
    except Exception:
        pass

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

# ===================== GROUP LOGIC =====================
async def add_group_entry(entry, message):
    uid = message.chat.id
    d = load_data(uid)
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
    save_data(uid, d)

async def resolve_chat_id(user, entry, acc_name):
    """Resolves the group chat ID (joins via username/invite if needed)."""
    if entry["type"] == "id":
        try:
            chat = await user.get_chat(entry["value"])
            return chat.id, None
        except Exception:
            try:
                async for _ in user.get_dialogs(limit=200):
                    pass
            except Exception:
                pass
            try:
                chat = await user.get_chat(entry["value"])
                return chat.id, None
            except Exception as e:
                return None, (f"account cannot access chat {entry['value']} — "
                              f"the account is NOT a member of this chat, or the ID is wrong. "
                              f"Add this group via its invite link instead "
                              f"(accounts auto-join and it works).")
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
        try:
            await user.get_chat(chat_id)
            return chat_id, None
        except Exception:
            pass  # cached ID doesn't resolve in a fresh client → re-join
    try:
        chat = await user.join_chat(f"https://t.me/+{entry['value']}")
        entry["ids"][acc_name] = chat.id
        return chat.id, None
    except UserAlreadyParticipant:
        # already a member but peer cache is empty → pull dialogs to get access_hash
        try:
            async for _ in user.get_dialogs(limit=200):
                pass
        except Exception:
            pass
        cid = entry["ids"].get(acc_name)
        if cid is not None:
            try:
                await user.get_chat(cid)
                return cid, None
            except Exception:
                pass
        return None, ("already a member, but the chat ID could not be resolved — "
                      "remove this group and add it again using the invite link")
    except Exception as e:
        return None, f"join failed: {e}"

async def send_payload(user, chat_id, d, stop_event, force_text=False):
    """
    Sends photo (if set) + full message. The message is never truncated.
    force_text=True → groups added by chat ID get TEXT ONLY (no photo).
    If the photo fails for any reason → automatic fallback to text-only.
    """
    text = d["message"]
    photo = d.get("photo", "") or ""
    auto = d.get("auto_image", True)

    if force_text:
        # group was added by raw chat ID → no photo, text only
        remaining = split_text(text)
    else:
        # ---- Try photo ----
        if photo and os.path.exists(photo):
            caption = text[:1024]            # caption limit is 1024 chars
            rest = text[1024:]
            try:
                await user.send_photo(chat_id, photo, caption=caption)
                remaining = split_text(rest) if rest else []
            except Exception:
                # photo failed (e.g. Peer id invalid) → fall back to plain text
                remaining = split_text(text)
        elif auto:
            try:
                img_path = generate_image_file(text)
                try:
                    await user.send_photo(chat_id, img_path)   # full quote inside the image
                    remaining = split_text(text) if AUTO_SEND_TEXT else []
                except Exception:
                    # photo failed → fall back to plain text
                    remaining = split_text(text)
            except Exception:
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
    force_text = (entry["type"] == "id")   # chat-ID groups: text only, no photo
    try:
        res = await send_payload(user, chat_id, d, stop_event, force_text=force_text)
        return "✅" if res == "✅" else f"❌ {res}"
    except FloodWait as e:
        await asyncio.sleep(min(e.x, 300))
        res = await send_payload(user, chat_id, d, stop_event, force_text=force_text)
        return "✅" if res == "✅" else f"❌ {res}"

# ===================== PROMO IN ALL GCS (NEW) =====================
async def discover_member_groups(user, d, acc_name):
    """
    Finds every group/channel where this account is a member,
    skipping the GCs already present in the user's saved list.
    """
    covered = set()
    for g in d.get("groups", []):
        if g["type"] == "id":
            covered.add(int(g["value"]))
        elif g["type"] == "invite":
            cid = g.get("ids", {}).get(acc_name)
            if cid:
                covered.add(cid)
        elif g["type"] == "username":
            try:
                await user.join_chat(g["value"])
            except Exception:
                pass
            try:
                covered.add((await user.get_chat(g["value"])).id)
            except Exception:
                pass

    targets = []
    try:
        # raise the limit (500) if the account is in more chats
        async for dialog in user.get_dialogs(limit=500):
            c = dialog.chat
            if c.type not in _CHAT_TYPES:
                continue
            if c.id in covered:
                continue
            targets.append(c)
    except Exception:
        pass
    return targets

async def run_promo_all(chat_id, progress_msg_id):
    d = load_data(chat_id)
    accounts = d["accounts"]
    time_str = d["time"]
    mode = d.get("mode", "once")
    interval = int(d.get("interval", 0) or 0)

    ev = asyncio.Event()
    promo_state[chat_id] = ev
    d["running"] = True
    save_data(chat_id, d)

    results = []
    try:
        if mode == "loop":
            wait_until = datetime.now()
            await safe_edit(
                chat_id, progress_msg_id,
                f"🔁 **PROMO TO ALL GCS (LOOP MODE)**\n\n"
                f"📱 Accounts: {len(accounts)}\n"
                f"⏱ Interval: every {interval} min\n"
                f"🌐 Every group/channel where the accounts are members will get the promo.\n"
                f"GCs already in your list are skipped.\n\n"
                f"Tap 🛑 to stop.",
                stop_kb(),
            )
        else:
            wait_until = compute_target(time_str)
            await safe_edit(
                chat_id, progress_msg_id,
                f"⏳ **PROMO TO ALL GCS SCHEDULED**\n\n"
                f"📱 Accounts: {len(accounts)}\n"
                f"⏰ Time: {time_str} ({wait_until.strftime('%H:%M:%S')})\n\n"
                f"Tap 🛑 to stop.",
                stop_kb(),
            )

        run_number = 0
        while True:
            # ---- wait until run time (chunked → STOP stays responsive) ----
            while not ev.is_set():
                delta = (wait_until - datetime.now()).total_seconds()
                if delta <= 0:
                    break
                await asyncio.sleep(min(delta, 5))
            if ev.is_set():
                break

            run_number += 1
            results = []
            for i, acc in enumerate(accounts, 1):
                if ev.is_set():
                    results.append(f"🛑 {acc['name']}: stopped")
                    break
                await safe_edit(
                    chat_id, progress_msg_id,
                    f"🌐 **Run #{run_number}** — {acc['name']} → discovering GCs... ({i}/{len(accounts)})",
                    stop_kb(),
                )
                ok = fail = 0
                try:
                    async with Client(f"pa_{chat_id}_{i}", API_ID, API_HASH,
                                      session_string=acc["session"], in_memory=True) as user:
                        targets = await discover_member_groups(user, d, acc["name"])
                        await safe_edit(
                            chat_id, progress_msg_id,
                            f"🌐 **Run #{run_number}** — {acc['name']} → {len(targets)} new GCs, sending... ({i}/{len(accounts)})",
                            stop_kb(),
                        )
                        for c in targets:
                            if ev.is_set():
                                break
                            try:
                                res = await send_payload(user, c.id, d, ev, force_text=False)
                                if res == "✅":
                                    ok += 1
                                else:
                                    fail += 1
                                    results.append(f"❌ {acc['name']} → {c.title or c.id}: {res}")
                            except Exception as e:
                                fail += 1
                                results.append(f"❌ {acc['name']} → {c.title or c.id}: {e}")
                except Exception as e:
                    fail += 1
                    results.append(f"❌ {acc['name']}: {e}")
                if ok == 0 and fail == 0:
                    results.append(f"ℹ️ {acc['name']}: no new GCs found (all are already in your list)")
                results.append(f"{'✅' if fail == 0 else '⚠️'} {acc['name']}: {ok} ok / {fail} fail")
                await asyncio.sleep(DELAY_BETWEEN_ACCOUNTS)

            # ---- what happens after this run ----
            if mode == "loop" and not ev.is_set():
                next_run = datetime.now() + timedelta(minutes=interval)
                await safe_edit(
                    chat_id, progress_msg_id,
                    f"🔁 **RUN #{run_number} DONE** ✅\n\n" + "\n".join(short_results(results)) +
                    f"\n\n⏱ Next run: **{next_run.strftime('%H:%M:%S')}** (every {interval} min)\n"
                    f"Tap 🛑 to stop the loop.",
                    stop_kb(),
                )
                # sleep in small chunks so the STOP button responds fast
                while datetime.now() < next_run:
                    if ev.is_set():
                        break
                    await asyncio.sleep(5)
            else:
                # one-time mode: finished
                await safe_edit(
                    chat_id, progress_msg_id,
                    f"🏁 **PROMO TO ALL GCS DONE**\n\n" + "\n".join(short_results(results)),
                    main_kb(),
                )
                break

        # stopped mid-run (during wait or sending)
        if ev.is_set():
            txt = "🛑 **PROMO STOPPED**\n\nPromo is no longer sending."
            if results:
                txt += "\n\n" + "\n".join(short_results(results))
            await safe_edit(chat_id, progress_msg_id, txt, stopped_kb())
    finally:
        d = load_data(chat_id)
        d["running"] = False
        save_data(chat_id, d)
        promo_state.pop(chat_id, None)

# ===================== PROMO RUNNER =====================
async def run_promo(chat_id, progress_msg_id):
    d = load_data(chat_id)
    accounts, groups = d["accounts"], d["groups"]
    time_str = d["time"]
    mode = d.get("mode", "once")
    interval = int(d.get("interval", 0) or 0)

    ev = asyncio.Event()
    promo_state[chat_id] = ev
    d["running"] = True
    save_data(chat_id, d)

    results = []
    try:
        if mode == "loop":
            # loop mode: starts immediately, repeats every `interval` minutes
            wait_until = datetime.now()
            await safe_edit(
                chat_id, progress_msg_id,
                f"🔁 **PROMO STARTING (LOOP MODE)**\n\n"
                f"📱 Accounts: {len(accounts)}\n📋 Groups: {len(groups)}\n"
                f"⏱ Interval: every {interval} min\n"
                f"▶️ Runs now, then repeats until you stop it.\n\n"
                f"Tap 🛑 to stop.",
                stop_kb(),
            )
        else:
            wait_until = compute_target(time_str)
            await safe_edit(
                chat_id, progress_msg_id,
                f"⏳ **PROMO SCHEDULED**\n\n"
                f"📱 Accounts: {len(accounts)}\n📋 Groups: {len(groups)}\n"
                f"⏰ Time: {time_str} ({wait_until.strftime('%H:%M:%S')})\n\n"
                f"Tap 🛑 to stop.",
                stop_kb(),
            )

        run_number = 0
        while True:
            # ---- wait until run time (chunked → STOP stays responsive) ----
            while not ev.is_set():
                delta = (wait_until - datetime.now()).total_seconds()
                if delta <= 0:
                    break
                await asyncio.sleep(min(delta, 5))
            if ev.is_set():
                break

            run_number += 1
            results = []
            for i, acc in enumerate(accounts, 1):
                if ev.is_set():
                    results.append(f"🛑 {acc['name']}: stopped")
                    break
                await safe_edit(
                    chat_id, progress_msg_id,
                    f"⏳ **Run #{run_number}** — {acc['name']} → sending... ({i}/{len(accounts)})",
                    stop_kb(),
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

            # ---- what happens after this run ----
            if mode == "loop" and not ev.is_set():
                next_run = datetime.now() + timedelta(minutes=interval)
                await safe_edit(
                    chat_id, progress_msg_id,
                    f"🔁 **RUN #{run_number} DONE** ✅\n\n" + "\n".join(short_results(results)) +
                    f"\n\n⏱ Next run: **{next_run.strftime('%H:%M:%S')}** (every {interval} min)\n"
                    f"Tap 🛑 to stop the loop.",
                    stop_kb(),
                )
                # sleep in small chunks so the STOP button responds fast
                while datetime.now() < next_run:
                    if ev.is_set():
                        break
                    await asyncio.sleep(5)
            else:
                # one-time mode: finished
                await safe_edit(
                    chat_id, progress_msg_id,
                    f"🏁 **PROMO DONE**\n\n" + "\n".join(short_results(results)),
                    main_kb(),
                )
                break

        # stopped mid-run (during wait or sending)
        if ev.is_set():
            txt = "🛑 **PROMO STOPPED**\n\nPromo is no longer sending."
            if results:
                txt += "\n\n" + "\n".join(short_results(results))
            await safe_edit(chat_id, progress_msg_id, txt, stopped_kb())
    finally:
        d = load_data(chat_id)
        d["running"] = False
        save_data(chat_id, d)
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
• Tap ➕ Add Account
• Send your phone number in international format — `+919876543210`
• Send the OTP you receive (enter the 2FA password if enabled)
• Session saved ✅ — you also receive your **session.txt** file
  (use that session in any other Pyrogram tool)
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

**5️⃣ SET TIME — choose a mode**
• Tap ⏰ Set Time → pick one:
• 🕐 **One-Time** — `5` = 5 minutes from now | `14:30` = today at 14:30 (tomorrow if already passed)
• 🔁 **Loop Mode** — send interval in minutes (`10`, `30`, `60`...)
   — promo runs NOW, then repeats every X minutes until you tap 🛑

**6️⃣ START**
• Tap 🚀 **START PROMO** — sends photo + message to your saved GC list 🚀
• Tap 🌐 **Promo in ALL GCs** — automatically finds EVERY group/channel
  where your accounts are members and sends there too
  (GCs already in your list are skipped, no duplicates)
• Tap 🛑 STOP PROMO to stop mid-run (also stops the loop)
• After stopping: **🚀 RESTART PROMO** runs again with the same settings,
  **🏠 Menu** takes you back to all options

**🔐 PRIVACY**
• Your data is stored per-user — nobody else can see your accounts, groups or sessions

**⚠️ NOTE:** Sending too fast may get your Telegram account **banned**.
Delays are set (3s msgs / 10s accounts) — change them at the top of the code.

/cancel — cancel any current step"""
    await message.reply_text(text)

@bot.on_message(filters.command("cancel") & filters.private)
async def cancel_cmd(client, message: Message):
    st = user_state.pop(message.chat.id, None)
    await safe_stop(st.get("temp") if st else None)
    await message.reply_text("❌ Cancelled. Back to main menu:", reply_markup=main_kb())

# ===================== SESSION FILE (NEW) =====================
async def send_session_file(message, phone, session):
    """Sends the session string as a .txt file so the user can reuse it anywhere."""
    try:
        bio = io.BytesIO(session.encode("utf-8"))
        bio.name = f"session_{phone.replace('+', '')}.txt"
        await message.reply_document(
            bio,
            caption="🔑 **Your session string** — save it carefully!\n\n"
                    "⚠️ Anyone who has this string can fully control this account.\n"
                    "✅ You can also use this session in any other Pyrogram tool.",
        )
    except Exception:
        pass

# ===================== CALLBACKS =====================
@bot.on_callback_query()
async def on_cb(client, cb: CallbackQuery):
    data = cb.data
    chat_id = cb.message.chat.id
    d = load_data(chat_id)

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
        save_data(chat_id, d)
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
        save_data(chat_id, d)
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
        save_data(chat_id, d)
        await cb.answer("❌ Photo removed", show_alert=True)
        await cb.message.edit_text("🖼️ **PROMO PHOTO** — photo removed. Auto-generate is active again.",
                                   reply_markup=photo_kb(d))
        return

    if data == "set_time":
        await cb.message.edit_text(
            "⏰ **SET TIME — choose a mode**\n\n"
            "🕐 **One-Time** — runs once at a scheduled time\n"
            "🔁 **Loop Mode** — keeps sending every X minutes until you tap 🛑",
            reply_markup=time_kb(),
        )
        await cb.answer(); return

    if data == "time_once":
        user_state[chat_id] = {"step": "time", "sub": "once"}
        await cb.message.edit_text(
            "🕐 **ONE-TIME SCHEDULE**\n\n`5` = 5 minutes from now\n`14:30` = today at 14:30\n\nCancel: /cancel",
            reply_markup=back_kb(),
        )
        await cb.answer(); return

    if data == "time_loop":
        user_state[chat_id] = {"step": "time", "sub": "loop"}
        await cb.message.edit_text(
            "🔁 **LOOP MODE**\n\n"
            "Send the **interval in minutes** — the promo runs NOW and repeats every X minutes until you tap 🛑.\n\n"
            "Examples: `10`, `30`, `60`, `1440`\n\nCancel: /cancel",
            reply_markup=back_kb(),
        )
        await cb.answer(); return

    if data == "status":
        await cb.message.edit_text(build_status(d), reply_markup=main_kb())
        await cb.answer(); return

    # "start_promo" (main menu) and "restart_promo" (after STOP) do the same thing:
    # launch the promo with the user's saved settings.
    if data in ("start_promo", "restart_promo"):
        missing = []
        if not d["accounts"]: missing.append("accounts")
        if not d["groups"]: missing.append("groups")
        if not d["message"]: missing.append("message")
        mode = d.get("mode", "once")
        if mode == "loop":
            if not d.get("interval"):
                missing.append("loop interval (⏰ Set Time → 🔁 Loop Mode)")
        else:
            if not d["time"]:
                missing.append("time (⏰ Set Time → 🕐 One-Time)")
        if missing:
            await cb.answer(f"❌ Set these first: {', '.join(missing)}", show_alert=True); return
        if promo_state.get(chat_id):
            await cb.answer("⏳ Promo already running!", show_alert=True); return
        if d.get("running"):
            d["running"] = False   # stale flag after a restart
            save_data(chat_id, d)
        msg = await cb.message.edit_text("🚀 **PROMO IS STARTING...**")
        asyncio.create_task(run_promo(chat_id, msg.id))
        await cb.answer(); return

    if data == "promo_all":
        # "Promo in ALL GCs" — no saved GC list needed, groups are auto-discovered
        missing = []
        if not d["accounts"]: missing.append("accounts")
        if not d["message"]: missing.append("message")
        mode = d.get("mode", "once")
        if mode == "loop":
            if not d.get("interval"):
                missing.append("loop interval (⏰ Set Time → 🔁 Loop Mode)")
        else:
            if not d["time"]:
                missing.append("time (⏰ Set Time → 🕐 One-Time)")
        if missing:
            await cb.answer(f"❌ Set these first: {', '.join(missing)}", show_alert=True); return
        if promo_state.get(chat_id):
            await cb.answer("⏳ Promo already running!", show_alert=True); return
        if d.get("running"):
            d["running"] = False   # stale flag after a restart
            save_data(chat_id, d)
        msg = await cb.message.edit_text("🌐 **PROMO TO ALL GCS IS STARTING...**")
        asyncio.create_task(run_promo_all(chat_id, msg.id))
        await cb.answer(); return

    if data == "stop_promo":
        ev = promo_state.get(chat_id)
        if ev:
            ev.set()
            # instant feedback on the message itself
            try:
                await cb.message.edit_text("🛑 **STOPPING PROMO...**", reply_markup=stop_kb())
            except Exception:
                pass
            await cb.answer("🛑 Stopping...")
        else:
            # no runner active → show the stopped state anyway
            try:
                await cb.message.edit_text(
                    "🛑 **PROMO STOPPED**\n\n"
                    "Promo is no longer sending.\n\n"
                    "• 🚀 **RESTART PROMO** — runs again with the same saved settings\n"
                    "• 🏠 **Menu** — back to all options",
                    reply_markup=stopped_kb(),
                )
            except Exception:
                pass
            await cb.answer("No promo is running right now.")
        return

    if data == "back":
        st = user_state.pop(chat_id, None)
        await safe_stop(st.get("temp") if st else None)
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
            if not temp.is_connected:
                await temp.connect()
            await temp.sign_in(st["phone"], st["ph"], text)
        except SessionPasswordNeeded:
            user_state[chat_id]["step"] = "pass"
            await message.reply_text(
                "🔐 This account has **2FA password** enabled — send the password:",
                reply_markup=back_kb(),
            )
            return
        except PhoneCodeInvalid:
            # wrong code — same flow me retry, restart nahi karna padega
            await message.reply_text(
                "❌ Wrong code. Send the **correct code** again (no need to restart):"
            )
            return
        except PhoneCodeExpired:
            # old OTP expired — automatically request a new one
            try:
                sent = await temp.send_code(st["phone"])
                user_state[chat_id]["ph"] = sent.phone_code_hash
                await message.reply_text(
                    "🔄 Old OTP expired. A **new OTP** has been sent — enter it:"
                )
            except FloodWait as e:
                await message.reply_text(f"⚠️ FloodWait: {e.x} sec — wait and try again.")
            except Exception as e:
                await message.reply_text(f"❌ Could not send a new code: {e}\nPress /cancel and try again.")
            return
        except FloodWait as e:
            await message.reply_text(f"⚠️ FloodWait: {e.x} sec — wait.")
            return
        except Exception as e:
            await safe_stop(temp)
            user_state.pop(chat_id, None)
            await message.reply_text(
                f"❌ Error: {e}\n\nPress /start to try again.", reply_markup=main_kb()
            )
            return

        # ---- LOGIN SUCCESS ----
        try:
            session = await temp.export_session_string()
        except Exception as e:
            await safe_stop(temp)
            user_state.pop(chat_id, None)
            await message.reply_text(f"❌ Could not create session: {e}\n\nPress /start to try again.")
            return

        # ---- SAVE FIRST, stop after (so the session can never get lost) ----
        d = load_data(chat_id)
        if any(a["name"] == st["phone"] for a in d["accounts"]):
            user_state.pop(chat_id, None)
            await safe_stop(temp)
            await send_session_file(message, st["phone"], session)
            await message.reply_text(
                f"⚠️ **{st['phone']}** is already added.\n\n"
                f"🔑 Your session file has been sent again above.",
                reply_markup=main_kb()
            )
            return
        d["accounts"].append({"name": st["phone"], "session": session,
                              "added": datetime.now().isoformat()})
        save_data(chat_id, d)
        user_state.pop(chat_id, None)
        await safe_stop(temp)
        await send_session_file(message, st["phone"], session)
        await message.reply_text(
            f"✅ **Account added!**\n\n📱 {st['phone']}\nTotal: {len(d['accounts'])} accounts\n\n"
            f"🔑 Your **session.txt** was sent above — you can reuse it anywhere.\n\n"
            f"Add more via ➕ Add Account, or continue with ➕ Add Group.",
            reply_markup=main_kb()
        )

    elif st["step"] == "pass":
        temp = st["temp"]
        try:
            if not temp.is_connected:
                await temp.connect()
            await temp.check_password(text)
        except PasswordHashInvalid:
            await message.reply_text("❌ Wrong 2FA password. Send it again:")
            return
        except FloodWait as e:
            await message.reply_text(f"⚠️ FloodWait: {e.x} sec — wait.")
            return
        except Exception as e:
            await safe_stop(temp)
            user_state.pop(chat_id, None)
            await message.reply_text(
                f"❌ Error: {e}\n\nPress /start to try again.", reply_markup=main_kb()
            )
            return

        try:
            session = await temp.export_session_string()
        except Exception as e:
            await safe_stop(temp)
            user_state.pop(chat_id, None)
            await message.reply_text(f"❌ Could not create session: {e}\n\nPress /start to try again.")
            return

        # ---- SAVE FIRST, stop after ----
        d = load_data(chat_id)
        if any(a["name"] == st["phone"] for a in d["accounts"]):
            user_state.pop(chat_id, None)
            await safe_stop(temp)
            await send_session_file(message, st["phone"], session)
            await message.reply_text(
                f"⚠️ **{st['phone']}** is already added.\n\n"
                f"🔑 Your session file has been sent again above.",
                reply_markup=main_kb()
            )
            return
        d["accounts"].append({"name": st["phone"], "session": session,
                              "added": datetime.now().isoformat()})
        save_data(chat_id, d)
        user_state.pop(chat_id, None)
        await safe_stop(temp)
        await send_session_file(message, st["phone"], session)
        await message.reply_text(
            f"✅ **Account added!**\n\n📱 {st['phone']}\nTotal: {len(d['accounts'])} accounts\n\n"
            f"🔑 Your **session.txt** was sent above — you can reuse it anywhere.\n\n"
            f"Add more via ➕ Add Account, or continue with ➕ Add Group.",
            reply_markup=main_kb()
        )

    elif st["step"] == "gc":
        entry = parse_group(text)
        if entry is None:
            await message.reply_text("❌ Format not recognized. Send a link/username/ID, or /cancel.")
            return
        user_state.pop(chat_id, None)
        await message.reply_text("⏳ Adding group (accounts are joining via invite link)...")
        await add_group_entry(entry, message)
        d = load_data(chat_id)
        await message.reply_text(
            f"✅ **Group added!**\n\n{entry['raw']}\nTotal groups: {len(d['groups'])}",
            reply_markup=main_kb()
        )

    elif st["step"] == "msg":
        d = load_data(chat_id)
        d["message"] = message.text
        save_data(chat_id, d)
        user_state.pop(chat_id, None)
        preview = message.text[:80] + ("..." if len(message.text) > 80 else "")
        await message.reply_text(
            f"✅ **Message saved!** ({len(message.text)} chars) — sent in full\n\nPreview:\n{preview}",
            reply_markup=main_kb()
        )

    elif st["step"] == "time":
        t = text.replace(" ", "")
        sub = st.get("sub", "once")
        if sub == "loop":
            # 🔁 Loop mode: interval in minutes
            try:
                interval = int(t)
                if interval < 1:
                    raise ValueError
            except ValueError:
                await message.reply_text("❌ Invalid interval. Send a number of **minutes**, e.g. `30`.")
                return
            d = load_data(chat_id)
            d["mode"] = "loop"
            d["interval"] = interval
            save_data(chat_id, d)
            user_state.pop(chat_id, None)
            await message.reply_text(
                f"✅ **Loop Mode set!** 🔁\n\n"
                f"The promo runs **now** and repeats **every {interval} minute(s)** "
                f"until you tap 🛑 STOP PROMO.",
                reply_markup=main_kb()
            )
        else:
            # 🕐 One-time schedule
            try:
                compute_target(t)
            except Exception:
                await message.reply_text("❌ Invalid format. Send `5` (minutes) or `14:30` (time).")
                return
            d = load_data(chat_id)
            d["mode"] = "once"
            d["time"] = t
            save_data(chat_id, d)
            user_state.pop(chat_id, None)
            await message.reply_text(f"✅ Time set: **{t}** (one-time)", reply_markup=main_kb())

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
    d = load_data(chat_id)
    d["photo"] = path
    d["auto_image"] = False
    save_data(chat_id, d)
    user_state.pop(chat_id, None)
    await message.reply_text(
        "🖼️ **Photo set!** ✅\n\n"
        "The promo will send the photo + your message (as caption).\n"
        "Press /start and tap 🚀 START PROMO.",
        reply_markup=main_kb()
    )

# ===================== MAIN =====================
async def main():
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(_quiet_exception_handler)
    await bot.start()
    print("🤖 Promo Bot v2 running — press Ctrl+C to stop.")
    await idle()
    await bot.stop()

if __name__ == "__main__":
    # reset stale "running" flags across all user files after a restart
    for path in glob.glob("data*.json"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                dd = json.load(f)
            if dd.get("running"):
                dd["running"] = False
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(dd, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    print("🤖 Promo Bot v2 starting...")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
