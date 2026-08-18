import os
import asyncio
import logging
from io import BytesIO
from pyrogram import Client, filters
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    Message
)
from pyrogram.errors import (
    SessionPasswordNeeded,
    PhoneCodeInvalid,
    PasswordHashInvalid,
    FloodWait
)

# ------------------------------------------------------------------
# CONFIGURATION (FETCHED FROM RAILWAY ENVIRONMENT VARIABLES)
# ------------------------------------------------------------------
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Initialize Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In-Memory Storage for String Sessions
# Format: {"+123456789": "session_string_here"}
user_sessions = {}

# In-Memory Workflow State Tracker
user_states = {}

# Initialize Admin Bot Client
bot = Client("admin_promo_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ------------------------------------------------------------------
# KEYBOARDS
# ------------------------------------------------------------------
def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Account", callback_data="add_account"),
         InlineKeyboardButton("👤 My Accounts", callback_data="my_accounts")],
        [InlineKeyboardButton("📢 Broadcast Promo", callback_data="broadcast_menu")],
        [InlineKeyboardButton("❌ Cancel / Reset", callback_data="cancel_action")]
    ])

def broadcast_type_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Promo in All GC", callback_data="promo_gc"),
         InlineKeyboardButton("📥 Promo in All DM", callback_data="promo_dm")],
        [InlineKeyboardButton("🚀 Promo in Both (GC + DM)", callback_data="promo_both")],
        [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="main_menu")]
    ])

def media_choice_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🖼️ Yes, Add Photo", callback_data="media_yes"),
         InlineKeyboardButton("📝 Text Only", callback_data="media_no")],
        [InlineKeyboardButton("⬅️ Cancel", callback_data="cancel_action")]
    ])

# ------------------------------------------------------------------
# ACCESS CONTROL FILTER
# ------------------------------------------------------------------
@bot.on_message(~filters.user(ADMIN_ID))
@bot.on_callback_query(~filters.user(ADMIN_ID))
async def restrict_unauthorized_access(client: Client, update):
    if isinstance(update, CallbackQuery):
        await update.answer("⚠️ Access Denied: You are not authorized to use this bot.", show_alert=True)
    elif isinstance(update, Message):
        await update.reply_text("⚠️ **Access Denied:** Private instance.")

# ------------------------------------------------------------------
# ADMIN BOT HANDLERS
# ------------------------------------------------------------------
@bot.on_message(filters.command("start") & filters.user(ADMIN_ID))
async def start_command(client: Client, message: Message):
    user_states.pop(message.from_user.id, None)
    await message.reply_text(
        "👋 **Welcome to Multi-Account Promo Automation Bot**\n\n"
        "Manage your accounts, generate downloadable session files, and execute broadcasts.",
        reply_markup=main_menu_keyboard()
    )

@bot.on_callback_query(filters.user(ADMIN_ID))
async def handle_callbacks(client: Client, callback: CallbackQuery):
    data = callback.data
    user_id = callback.from_user.id

    if data == "main_menu":
        user_states.pop(user_id, None)
        await callback.message.edit_text(
            "📍 **Main Menu:** Select an option below.",
            reply_markup=main_menu_keyboard()
        )

    elif data == "cancel_action":
        user_states.pop(user_id, None)
        await callback.message.edit_text(
            "❌ Action cancelled.",
            reply_markup=main_menu_keyboard()
        )

    # --------------------------------------------------------------
    # ACCOUNT MANAGEMENT
    # --------------------------------------------------------------
    elif data == "add_account":
        user_states[user_id] = {"step": "AWAITING_PHONE"}
        await callback.message.edit_text(
            "📱 **Add Telegram Account**\n\n"
            "Please send the phone number in international format (e.g., `+1234567890`)."
        )

    elif data == "my_accounts":
        if not user_sessions:
            await callback.message.edit_text(
                "ℹ️ **No active sessions added yet.**",
                reply_markup=main_menu_keyboard()
            )
            return

        buttons = []
        for phone in list(user_sessions.keys()):
            buttons.append([
                InlineKeyboardButton(f"👤 {phone}", callback_data=f"acc_info_{phone}"),
                InlineKeyboardButton("❌ Remove", callback_data=f"remove_acc_{phone}")
            ])
        buttons.append([InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="main_menu")])

        await callback.message.edit_text(
            f"📋 **Connected Accounts ({len(user_sessions)}):**\n"
            "Click 'Remove' to disconnect and wipe session from memory.",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    elif data.startswith("remove_acc_"):
        phone = data.replace("remove_acc_", "")
        if phone in user_sessions:
            del user_sessions[phone]
            await callback.answer(f"Account {phone} removed successfully!", show_alert=True)
        else:
            await callback.answer("Account not found.", show_alert=True)
        
        await handle_callbacks(client, callback)

    # --------------------------------------------------------------
    # BROADCAST WORKFLOW
    # --------------------------------------------------------------
    elif data == "broadcast_menu":
        if not user_sessions:
            await callback.answer("⚠️ Please add at least one account session first!", show_alert=True)
            return
        
        await callback.message.edit_text(
            "📢 **Select Broadcast Destination:**",
            reply_markup=broadcast_type_keyboard()
        )

    elif data in ["promo_gc", "promo_dm", "promo_both"]:
        target_map = {
            "promo_gc": "Groups & Channels",
            "promo_dm": "Direct Messages (DMs)",
            "promo_both": "Groups, Channels & DMs"
        }
        user_states[user_id] = {
            "step": "AWAITING_MEDIA_CHOICE",
            "target": data
        }
        await callback.message.edit_text(
            f"🎯 **Target:** {target_map[data]}\n\n"
            "❓ **Do you want to add a photo with text?**",
            reply_markup=media_choice_keyboard()
        )

    elif data == "media_yes":
        user_states[user_id]["has_photo"] = True
        user_states[user_id]["step"] = "AWAITING_PHOTO"
        await callback.message.edit_text("📸 Please send the **Photo** you want to attach to your promo message.")

    elif data == "media_no":
        user_states[user_id]["has_photo"] = False
        user_states[user_id]["step"] = "AWAITING_TEXT"
        await callback.message.edit_text("📝 Please send your **Promo Text Message** (Emojis & formatting supported).")

# ------------------------------------------------------------------
# TEXT / MEDIA CAPTURE HANDLER
# ------------------------------------------------------------------
@bot.on_message(filters.user(ADMIN_ID) & ~filters.command("start"))
async def handle_inputs(client: Client, message: Message):
    user_id = message.from_user.id
    state = user_states.get(user_id)

    if not state:
        return

    step = state.get("step")

    # Helper function to generate and send downloadable session document
    async def complete_login_and_send_file(phone: str, session_string: str):
        user_sessions[phone] = session_string

        # Create downloadable file in memory
        file_bytes = BytesIO(session_string.encode("utf-8"))
        file_bytes.name = f"{phone}_string.session"

        await message.reply_document(
            document=file_bytes,
            caption=(
                f"✅ **Session Logged In Successfully!**\n\n"
                f"📱 **Phone:** `{phone}`\n"
                f"📂 **Session File:** Attached above. You can download and use this String Session anywhere.\n\n"
                f"Account is now active under **My Accounts**."
            ),
            reply_markup=main_menu_keyboard()
        )
        user_states.pop(user_id, None)

    # 1. Login Process: Phone Number
    if step == "AWAITING_PHONE":
        phone = message.text.strip()
        temp_client = Client("temp_session", api_id=API_ID, api_hash=API_HASH, in_memory=True)
        await temp_client.connect()
        try:
            code_info = await temp_client.send_code(phone)
            user_states[user_id].update({
                "step": "AWAITING_OTP",
                "phone": phone,
                "phone_code_hash": code_info.phone_code_hash,
                "temp_client": temp_client
            })
            await message.reply_text("📲 **OTP Sent!** Please reply with the login code (format: `1 2 3 4 5` or `12345`).")
        except Exception as e:
            await temp_client.disconnect()
            await message.reply_text(f"❌ Failed to send code: `{str(e)}`", reply_markup=main_menu_keyboard())
            user_states.pop(user_id, None)

    # 2. Login Process: OTP Code
    elif step == "AWAITING_OTP":
        otp = message.text.replace(" ", "").strip()
        temp_client = state["temp_client"]
        phone = state["phone"]
        phone_code_hash = state["phone_code_hash"]

        try:
            await temp_client.sign_in(phone, phone_code_hash, otp)
            session_string = await temp_client.export_session_string()
            await temp_client.disconnect()

            await complete_login_and_send_file(phone, session_string)

        except SessionPasswordNeeded:
            user_states[user_id]["step"] = "AWAITING_2FA"
            await message.reply_text("🔐 This account has **Two-Step Verification (2FA)** enabled. Please enter your password.")

        except PhoneCodeInvalid:
            await message.reply_text("❌ Invalid OTP code. Please try again.")

        except Exception as e:
            await temp_client.disconnect()
            await message.reply_text(f"❌ Login failed: `{str(e)}`", reply_markup=main_menu_keyboard())
            user_states.pop(user_id, None)

    # 3. Login Process: 2FA Password
    elif step == "AWAITING_2FA":
        password = message.text.strip()
        temp_client = state["temp_client"]
        phone = state["phone"]

        try:
            await temp_client.check_password(password)
            session_string = await temp_client.export_session_string()
            await temp_client.disconnect()

            await complete_login_and_send_file(phone, session_string)

        except PasswordHashInvalid:
            await message.reply_text("❌ Incorrect 2FA password. Try again.")

        except Exception as e:
            await temp_client.disconnect()
            await message.reply_text(f"❌ Login failed: `{str(e)}`", reply_markup=main_menu_keyboard())
            user_states.pop(user_id, None)

    # 4. Broadcast Process: Capture Photo
    elif step == "AWAITING_PHOTO":
        if not message.photo:
            await message.reply_text("❌ Please send a valid **photo**.")
            return
        
        user_states[user_id]["photo_file_id"] = message.photo.file_id
        user_states[user_id]["step"] = "AWAITING_TEXT"
        await message.reply_text("📝 Photo saved! Now send your **Promo Text Message / Caption**.")

    # 5. Broadcast Process: Capture Text & Execute
    elif step == "AWAITING_TEXT":
        promo_text = message.text or message.caption or ""
        target = state.get("target")
        photo_file_id = state.get("photo_file_id")

        await message.reply_text("⏳ **Initiating Broadcast Engine across all added accounts...**")

        # Run Background Broadcast Task
        asyncio.create_task(run_broadcast(
            target=target,
            text=promo_text,
            photo_file_id=photo_file_id
        ))

        user_states.pop(user_id, None)
        await message.reply_text("🚀 **Broadcast started in background!** You will be notified when completed.", reply_markup=main_menu_keyboard())

# ------------------------------------------------------------------
# MULTI-ACCOUNT BROADCAST ENGINE
# ------------------------------------------------------------------
async def run_broadcast(target: str, text: str, photo_file_id: str = None):
    total_sent = 0
    total_failed = 0

    local_photo_path = None
    if photo_file_id:
        local_photo_path = await bot.download_media(photo_file_id)

    for phone, session_str in user_sessions.items():
        user_client = Client(f"user_{phone}", api_id=API_ID, api_hash=API_HASH, session_string=session_str)

        try:
            await user_client.start()

            async for dialog in user_client.get_dialogs():
                chat_type = dialog.chat.type.value
                should_send = False

                if target == "promo_gc" and chat_type in ["group", "supergroup", "channel"]:
                    should_send = True
                elif target == "promo_dm" and chat_type == "private":
                    should_send = True
                elif target == "promo_both":
                    should_send = True

                if should_send:
                    try:
                        if local_photo_path:
                            await user_client.send_photo(dialog.chat.id, photo=local_photo_path, caption=text)
                        else:
                            await user_client.send_message(dialog.chat.id, text=text)
                        
                        total_sent += 1
                        await asyncio.sleep(2)  # Delay to avoid FloodWait limits
                    except FloodWait as e:
                        await asyncio.sleep(e.value)
                    except Exception as err:
                        logger.error(f"Failed to send to {dialog.chat.id} via {phone}: {err}")
                        total_failed += 1

            await user_client.stop()

        except Exception as e:
            logger.error(f"Account {phone} execution error: {e}")
            total_failed += 1

    # Send Completion Report
    await bot.send_message(
        ADMIN_ID,
        f"📊 **Broadcast Completed Summary**\n\n"
        f"✅ **Messages Sent:** `{total_sent}`\n"
        f"❌ **Failed Attempts:** `{total_failed}`",
        reply_markup=main_menu_keyboard()
    )

# ------------------------------------------------------------------
# ENTRY POINT
# ------------------------------------------------------------------
if __name__ == "__main__":
    logger.info("Starting Railway Promo Bot Engine...")
    bot.run()
