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
    FloodWait,
    SlowmodeWait,
    MessageNotModified
)

# ------------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------------
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Multi-Tenant In-Memory Storage
user_sessions = {}

# Workflow state tracker per user
user_states = {}

# Active loops tracker: { owner_id: asyncio.Task }
active_loops = {}

# Initialize Main Bot Client
bot = Client("public_promo_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ------------------------------------------------------------------
# KEYBOARDS
# ------------------------------------------------------------------
def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Account", callback_data="add_account"),
         InlineKeyboardButton("👤 My Accounts", callback_data="my_accounts")],
        [InlineKeyboardButton("📢 Broadcast Promo", callback_data="broadcast_menu")],
        [InlineKeyboardButton("🛑 Stop Loop Broadcast", callback_data="stop_loop_broadcast")],
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

def loop_ask_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔁 Yes, Enable Loop", callback_data="loop_yes"),
         InlineKeyboardButton("⚡ No, Send One Time", callback_data="loop_no")],
        [InlineKeyboardButton("⬅️ Cancel", callback_data="cancel_action")]
    ])

def loop_delay_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏱️ 10 Minutes (Standard GC Slow Mode)", callback_data="delay_10")],
        [InlineKeyboardButton("⏱️ 15 Minutes (Safe Interval)", callback_data="delay_15")],
        [InlineKeyboardButton("⏱️ 30 Minutes (Extended Gap)", callback_data="delay_30")],
        [InlineKeyboardButton("✏️ Custom Time (Enter Manually)", callback_data="delay_custom")],
        [InlineKeyboardButton("⬅️ Cancel", callback_data="cancel_action")]
    ])

# ------------------------------------------------------------------
# IGNORE GROUPS FILTER (PRIVATE DM ONLY)
# ------------------------------------------------------------------
@bot.on_message(~filters.private)
async def ignore_groups(client: Client, message: Message):
    return

# ------------------------------------------------------------------
# MAIN BOT COMMANDS & CALLBACKS
# ------------------------------------------------------------------
@bot.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    user_id = message.from_user.id
    user_states.pop(user_id, None)
    await message.reply_text(
        "👋 **Welcome to Multi-Account Promo Automation Bot**\n\n"
        "Here you can connect your Telegram accounts, download session files, "
        "and securely send promotional messages across your joined groups and DMs.\n\n"
        "🔒 **Privacy Guaranteed:** Your added accounts and sessions are visible ONLY to you.",
        reply_markup=main_menu_keyboard()
    )

@bot.on_callback_query()
async def handle_callbacks(client: Client, callback: CallbackQuery):
    data = callback.data
    user_id = callback.from_user.id

    try:
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

        elif data == "stop_loop_broadcast":
            if user_id in active_loops:
                active_loops[user_id].cancel()
                del active_loops[user_id]
                await callback.answer("🛑 Loop Broadcast Stopped successfully!", show_alert=True)
                await callback.message.edit_text("🛑 **Loop broadcast cancelled.**", reply_markup=main_menu_keyboard())
            else:
                await callback.answer("ℹ️ No active loop broadcast found.", show_alert=True)

        # --------------------------------------------------------------
        # MY ACCOUNTS (USER SPECIFIC ONLY)
        # --------------------------------------------------------------
        elif data == "add_account":
            user_states[user_id] = {"step": "AWAITING_PHONE"}
            await callback.message.edit_text(
                "📱 **Add Telegram Account**\n\n"
                "Please send the phone number in international format (e.g., `+1234567890`)."
            )

        elif data == "my_accounts":
            my_accs = user_sessions.get(user_id, {})
            if not my_accs:
                await callback.message.edit_text(
                    "ℹ️ **You have no active accounts added.**",
                    reply_markup=main_menu_keyboard()
                )
                return

            buttons = []
            for phone in list(my_accs.keys()):
                buttons.append([
                    InlineKeyboardButton(f"👤 {phone}", callback_data=f"acc_info_{phone}"),
                    InlineKeyboardButton("❌ Remove", callback_data=f"remove_acc_{phone}")
                ])
            buttons.append([InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="main_menu")])

            await callback.message.edit_text(
                f"📋 **Your Connected Accounts ({len(my_accs)}):**\n"
                "Click 'Remove' to delete your session.",
                reply_markup=InlineKeyboardMarkup(buttons)
            )

        elif data.startswith("remove_acc_"):
            phone = data.replace("remove_acc_", "")
            if user_id in user_sessions and phone in user_sessions[user_id]:
                del user_sessions[user_id][phone]
                await callback.answer(f"Account {phone} removed successfully!", show_alert=True)
            else:
                await callback.answer("Account not found.", show_alert=True)
            
            # Refresh My Accounts view directly without recursive callback calling
            my_accs = user_sessions.get(user_id, {})
            if not my_accs:
                await callback.message.edit_text(
                    "ℹ️ **You have no active accounts added.**",
                    reply_markup=main_menu_keyboard()
                )
            else:
                buttons = []
                for p in list(my_accs.keys()):
                    buttons.append([
                        InlineKeyboardButton(f"👤 {p}", callback_data=f"acc_info_{p}"),
                        InlineKeyboardButton("❌ Remove", callback_data=f"remove_acc_{p}")
                    ])
                buttons.append([InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="main_menu")])
                await callback.message.edit_text(
                    f"📋 **Your Connected Accounts ({len(my_accs)}):**\n"
                    "Click 'Remove' to delete your session.",
                    reply_markup=InlineKeyboardMarkup(buttons)
                )

        # --------------------------------------------------------------
        # BROADCAST WORKFLOW (USER SPECIFIC ONLY)
        # --------------------------------------------------------------
        elif data == "broadcast_menu":
            my_accs = user_sessions.get(user_id, {})
            if not my_accs:
                await callback.answer("⚠️ Please add at least one account first!", show_alert=True)
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
                "❓ **Do you want to add a photo with your message?**",
                reply_markup=media_choice_keyboard()
            )

        elif data == "media_yes":
            if user_id in user_states:
                user_states[user_id]["has_photo"] = True
                user_states[user_id]["step"] = "AWAITING_PHOTO"
                await callback.message.edit_text("📸 Send the **Photo** you want to attach.")

        elif data == "media_no":
            if user_id in user_states:
                user_states[user_id]["has_photo"] = False
                user_states[user_id]["step"] = "AWAITING_TEXT"
                await callback.message.edit_text("📝 Send your **Promo Text Message** (Emojis & formatting supported).")

        # --------------------------------------------------------------
        # LOOP & TIME INTERVAL SELECTION
        # --------------------------------------------------------------
        elif data == "loop_no":
            if user_id in user_states:
                state = user_states[user_id]
                target = state.get("target")
                promo_text = state.get("promo_text")
                photo_file_id = state.get("photo_file_id")

                await callback.message.edit_text("⏳ **Starting One-Time Broadcast...**")
                
                task = asyncio.create_task(run_user_broadcast(
                    owner_id=user_id,
                    target=target,
                    text=promo_text,
                    photo_file_id=photo_file_id,
                    interval_minutes=0
                ))
                active_loops[user_id] = task
                user_states.pop(user_id, None)

        elif data == "loop_yes":
            if user_id in user_states:
                await callback.message.edit_text(
                    "⏱️ **Select Delay Interval for Continuous Loop Broadcast:**\n\n"
                    "• **10 Minutes:** Ideal interval to bypass Standard Slow Mode.\n"
                    "• **15 Minutes:** Safer spacing between consecutive posts.\n"
                    "• **30 Minutes:** Extended gap to prevent flood restrictions.\n"
                    "• **Custom Time:** Enter delay manually in minutes.",
                    reply_markup=loop_delay_keyboard()
                )

        elif data.startswith("delay_"):
            delay_type = data.replace("delay_", "")
            if delay_type == "custom":
                user_states[user_id]["step"] = "AWAITING_CUSTOM_DELAY"
                await callback.message.edit_text("✏️ Please type the delay time in minutes (e.g. `10`, `20`, `60`):")
            else:
                interval_min = int(delay_type)
                state = user_states[user_id]
                target = state.get("target")
                promo_text = state.get("promo_text")
                photo_file_id = state.get("photo_file_id")

                await callback.message.edit_text(
                    f"🚀 **Loop Broadcast Initiated!**\n"
                    f"⏱️ **Interval:** Every `{interval_min}` minutes.\n"
                    f"You can stop it anytime from the Main Menu.",
                    reply_markup=main_menu_keyboard()
                )

                task = asyncio.create_task(run_user_broadcast(
                    owner_id=user_id,
                    target=target,
                    text=promo_text,
                    photo_file_id=photo_file_id,
                    interval_minutes=interval_min
                ))
                active_loops[user_id] = task
                user_states.pop(user_id, None)

    except MessageNotModified:
        # Ignore error if message content is identical
        pass

# ------------------------------------------------------------------
# INPUT CAPTURE HANDLER
# ------------------------------------------------------------------
@bot.on_message(filters.private & ~filters.command("start"))
async def handle_inputs(client: Client, message: Message):
    user_id = message.from_user.id
    state = user_states.get(user_id)

    if not state:
        return

    step = state.get("step")

    # Helper function to assign session to specific user and send file
    async def complete_login_and_send_file(phone: str, session_string: str):
        if user_id not in user_sessions:
            user_sessions[user_id] = {}
        
        user_sessions[user_id][phone] = session_string

        # Generate downloadable file
        file_bytes = BytesIO(session_string.encode("utf-8"))
        file_bytes.name = f"{phone}_session.string"

        await message.reply_document(
            document=file_bytes,
            caption=(
                f"✅ **Account Logged In Successfully!**\n\n"
                f"📱 **Phone:** `{phone}`\n"
                f"📂 **Session File:** Attached above. You can download and save it.\n\n"
                f"Your account is now ready to use under **My Accounts**."
            ),
            reply_markup=main_menu_keyboard()
        )
        user_states.pop(user_id, None)

    # 1. Add Phone
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
            await message.reply_text("📲 **OTP Sent!** Please enter the code (format: `12345` or `1 2 3 4 5`).")
        except Exception as e:
            await temp_client.disconnect()
            await message.reply_text(f"❌ Failed to send OTP: `{str(e)}`", reply_markup=main_menu_keyboard())
            user_states.pop(user_id, None)

    # 2. Add OTP Code
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
            await message.reply_text("🔐 **Two-Step Verification (2FA)** enabled. Enter your password.")

        except PhoneCodeInvalid:
            await message.reply_text("❌ Invalid OTP code. Please re-enter.")

        except Exception as e:
            await temp_client.disconnect()
            await message.reply_text(f"❌ Login failed: `{str(e)}`", reply_markup=main_menu_keyboard())
            user_states.pop(user_id, None)

    # 3. Add 2FA Password
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

    # 4. Capture Photo
    elif step == "AWAITING_PHOTO":
        if not message.photo:
            await message.reply_text("❌ Please send a valid **photo**.")
            return
        
        user_states[user_id]["photo_file_id"] = message.photo.file_id
        user_states[user_id]["step"] = "AWAITING_TEXT"
        await message.reply_text("📝 Photo saved! Now send your **Promo Text Message / Caption**.")

    # 5. Capture Text & Ask Loop Preference
    elif step == "AWAITING_TEXT":
        promo_text = message.text or message.caption or ""
        user_states[user_id]["promo_text"] = promo_text
        user_states[user_id]["step"] = "AWAITING_LOOP_CHOICE"

        await message.reply_text(
            "🔁 **Loop Settings:**\n\n"
            "Do you want to send this broadcast on a **continuous loop / scheduled delay**, or send it **one-time only**?",
            reply_markup=loop_ask_keyboard()
        )

    # 6. Custom Delay Input
    elif step == "AWAITING_CUSTOM_DELAY":
        if not message.text.isdigit() or int(message.text) <= 0:
            await message.reply_text("❌ Invalid duration! Please enter a positive number in minutes (e.g., `12`).")
            return

        interval_min = int(message.text)
        target = state.get("target")
        promo_text = state.get("promo_text")
        photo_file_id = state.get("photo_file_id")

        await message.reply_text(
            f"🚀 **Loop Broadcast Initiated!**\n"
            f"⏱️ **Interval:** Every `{interval_min}` minutes.\n"
            f"You can stop it anytime from the Main Menu.",
            reply_markup=main_menu_keyboard()
        )

        task = asyncio.create_task(run_user_broadcast(
            owner_id=user_id,
            target=target,
            text=promo_text,
            photo_file_id=photo_file_id,
            interval_minutes=interval_min
        ))
        active_loops[user_id] = task
        user_states.pop(user_id, None)

# ------------------------------------------------------------------
# BROADCAST ENGINE (FIXED FOR TOPICS/FORUMS & CHAT PERMISSIONS)
# ------------------------------------------------------------------

async def run_user_broadcast(owner_id: int, target: str, text: str, photo_file_id: str = None, interval_minutes: int = 0):
    try:
        while True:
            my_accounts = user_sessions.get(owner_id, {})
            total_sent = 0
            total_failed = 0

            local_photo_path = None
            if photo_file_id:
                try:
                    local_photo_path = await bot.download_media(photo_file_id)
                except Exception as e:
                    logger.error(f"Failed to download media: {e}")

            for phone, session_str in my_accounts.items():
                user_client = Client(f"user_{phone}", api_id=API_ID, api_hash=API_HASH, session_string=session_str)

                try:
                    await user_client.start()

                    async for dialog in user_client.get_dialogs():
                        chat = dialog.chat
                        chat_type = str(chat.type).lower()
                        
                        is_group_or_channel = any(k in chat_type for k in ["group", "supergroup", "channel"])
                        is_private_dm = "private" in chat_type

                        should_send = False

                        if target == "promo_gc" and is_group_or_channel:
                            should_send = True
                        elif target == "promo_dm" and is_private_dm:
                            should_send = True
                        elif target == "promo_both" and (is_group_or_channel or is_private_dm):
                            should_send = True

                        if should_send:
                            try:
                                if local_photo_path:
                                    await user_client.send_photo(chat.id, photo=local_photo_path, caption=text)
                                else:
                                    await user_client.send_message(chat.id, text=text)
                                
                                total_sent += 1
                                await asyncio.sleep(2)  # Delay between chats to prevent flood
                            
                            except SlowmodeWait as e:
                                logger.info(f"Slow Mode active in {chat.id}. Waiting for {e.value}s")
                                await asyncio.sleep(e.value)
                                try:
                                    if local_photo_path:
                                        await user_client.send_photo(chat.id, photo=local_photo_path, caption=text)
                                    else:
                                        await user_client.send_message(chat.id, text=text)
                                    total_sent += 1
                                except Exception:
                                    total_failed += 1
                            
                            except FloodWait as e:
                                logger.info(f"FloodWait hit. Waiting {e.value}s")
                                await asyncio.sleep(e.value)
                            
                            except Exception as err:
                                # Skips chats where posting isn't allowed (e.g. admin-only channels or closed groups)
                                logger.error(f"Failed to send to {chat.title or chat.id} via {phone}: {err}")
                                total_failed += 1

                    await user_client.stop()

                except Exception as e:
                    logger.error(f"Execution error for account {phone}: {e}")
                    total_failed += 1

            if local_photo_path and os.path.exists(local_photo_path):
                os.remove(local_photo_path)

            await bot.send_message(
                owner_id,
                f"📊 **Broadcast Completed Round Summary**\n\n"
                f"✅ **Messages Sent:** `{total_sent}`\n"
                f"❌ **Failed Attempts:** `{total_failed}`\n"
                f"{f'🔁 **Next Round in:** `{interval_minutes}` minutes.' if interval_minutes > 0 else ''}",
                reply_markup=main_menu_keyboard()
            )

            if interval_minutes <= 0:
                break

            await asyncio.sleep(interval_minutes * 60)

    except asyncio.CancelledError:
        logger.info(f"Broadcast loop stopped for user {owner_id}")

# ------------------------------------------------------------------
# ENTRY POINT
# ------------------------------------------------------------------
if __name__ == "__main__":
    logger.info("Starting Multi-Tenant Public Promo Bot...")
    bot.run()
