import os
import re
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
    MessageNotModified,
    UserAlreadyParticipant,
    InviteHashExpired,
    InviteHashInvalid
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
user_sessions = {}      # { user_id: { phone: session_string } }
user_custom_gcs = {}    # { user_id: [ chat_id_or_username_or_link, ... ] }

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
        [InlineKeyboardButton("➕ Add Custom GC", callback_data="add_gc"),
         InlineKeyboardButton("📋 My Selected GCs", callback_data="my_gcs")],
        [InlineKeyboardButton("📢 Broadcast Promo", callback_data="broadcast_menu")],
        [InlineKeyboardButton("🛑 Stop Loop Broadcast", callback_data="stop_loop_broadcast")],
        [InlineKeyboardButton("❌ Cancel / Reset", callback_data="cancel_action")]
    ])

def broadcast_type_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯 Selected Groups Only", callback_data="promo_custom")],
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
        [InlineKeyboardButton("⏱️ 10 Minutes", callback_data="delay_10")],
        [InlineKeyboardButton("⏱️ 15 Minutes", callback_data="delay_15")],
        [InlineKeyboardButton("⏱️ 30 Minutes", callback_data="delay_30")],
        [InlineKeyboardButton("✏️ Custom Time", callback_data="delay_custom")],
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
        "Here you can connect your Telegram accounts, add specific target groups, "
        "and broadcast messages across your groups and DMs.\n\n"
        "🔒 **Privacy Guaranteed:** Your accounts and saved groups are visible ONLY to you.",
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
        # MY ACCOUNTS
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
                await callback.answer(f"Account {phone} removed!", show_alert=True)
            else:
                await callback.answer("Account not found.", show_alert=True)
            
            my_accs = user_sessions.get(user_id, {})
            if not my_accs:
                await callback.message.edit_text("ℹ️ **You have no active accounts added.**", reply_markup=main_menu_keyboard())
            else:
                buttons = []
                for p in list(my_accs.keys()):
                    buttons.append([
                        InlineKeyboardButton(f"👤 {p}", callback_data=f"acc_info_{p}"),
                        InlineKeyboardButton("❌ Remove", callback_data=f"remove_acc_{p}")
                    ])
                buttons.append([InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="main_menu")])
                await callback.message.edit_text(
                    f"📋 **Your Connected Accounts ({len(my_accs)}):**\nClick 'Remove' to delete your session.",
                    reply_markup=InlineKeyboardMarkup(buttons)
                )

        # --------------------------------------------------------------
        # ADD & MANAGE CUSTOM TARGET GROUPS
        # --------------------------------------------------------------
        elif data == "add_gc":
            user_states[user_id] = {"step": "AWAITING_GC_INPUT"}
            await callback.message.edit_text(
                "➕ **Add Target Group**\n\n"
                "Send the Group details in any of the following formats:\n"
                "1. **Username:** `@mygroupusername`\n"
                "2. **Invite Link:** `https://t.me/+AbCdEfGhIjKlMnOp`\n"
                "3. **Chat ID:** `-1001234567890`"
            )

        elif data == "my_gcs":
            my_gcs = user_custom_gcs.get(user_id, [])
            if not my_gcs:
                await callback.message.edit_text(
                    "ℹ️ **You have no custom groups added.**",
                    reply_markup=main_menu_keyboard()
                )
                return

            buttons = []
            for idx, gc_item in enumerate(my_gcs):
                buttons.append([
                    InlineKeyboardButton(f"👥 {gc_item}", callback_data=f"gc_info_{idx}"),
                    InlineKeyboardButton("❌ Remove", callback_data=f"remove_gc_{idx}")
                ])
            buttons.append([InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="main_menu")])

            await callback.message.edit_text(
                f"📋 **Your Selected Target Groups ({len(my_gcs)}):**\n"
                "Click 'Remove' to delete a group from your broadcast list.",
                reply_markup=InlineKeyboardMarkup(buttons)
            )

        elif data.startswith("remove_gc_"):
            idx = int(data.replace("remove_gc_", ""))
            if user_id in user_custom_gcs and 0 <= idx < len(user_custom_gcs[user_id]):
                removed_item = user_custom_gcs[user_id].pop(idx)
                await callback.answer(f"Removed {removed_item}!", show_alert=True)
            
            my_gcs = user_custom_gcs.get(user_id, [])
            if not my_gcs:
                await callback.message.edit_text("ℹ️ **You have no custom groups added.**", reply_markup=main_menu_keyboard())
            else:
                buttons = []
                for i, gc_item in enumerate(my_gcs):
                    buttons.append([
                        InlineKeyboardButton(f"👥 {gc_item}", callback_data=f"gc_info_{i}"),
                        InlineKeyboardButton("❌ Remove", callback_data=f"remove_gc_{i}")
                    ])
                buttons.append([InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="main_menu")])
                await callback.message.edit_text(
                    f"📋 **Your Selected Target Groups ({len(my_gcs)}):**",
                    reply_markup=InlineKeyboardMarkup(buttons)
                )

        # --------------------------------------------------------------
        # BROADCAST WORKFLOW
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

        elif data in ["promo_custom", "promo_gc", "promo_dm", "promo_both"]:
            if data == "promo_custom" and not user_custom_gcs.get(user_id):
                await callback.answer("⚠️ You haven't added any custom groups yet! Click 'Add Custom GC' first.", show_alert=True)
                return

            target_map = {
                "promo_custom": "Selected Groups Only",
                "promo_gc": "All Joined Groups & Channels",
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
        # LOOP & TIME SELECTION
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
                    "⏱️ **Select Delay Interval for Continuous Loop Broadcast:**",
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

    # Helper function to save session string
    async def complete_login_and_send_file(phone: str, session_string: str):
        if user_id not in user_sessions:
            user_sessions[user_id] = {}
        
        user_sessions[user_id][phone] = session_string

        file_bytes = BytesIO(session_string.encode("utf-8"))
        file_bytes.name = f"{phone}_session.string"

        await message.reply_document(
            document=file_bytes,
            caption=(
                f"✅ **Account Logged In Successfully!**\n\n"
                f"📱 **Phone:** `{phone}`\n"
                f"📂 **Session File:** Attached above.\n\n"
                f"Your account is now ready to use."
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

    # 4. Add Custom Target Group
    elif step == "AWAITING_GC_INPUT":
        gc_input = message.text.strip()
        if user_id not in user_custom_gcs:
            user_custom_gcs[user_id] = []

        if gc_input in user_custom_gcs[user_id]:
            await message.reply_text("⚠️ This group is already in your selected list!", reply_markup=main_menu_keyboard())
        else:
            user_custom_gcs[user_id].append(gc_input)
            await message.reply_text(
                f"✅ **Target Group Added Successfully!**\n\n"
                f"📌 **Target:** `{gc_input}`\n"
                f"Total Saved Groups: `{len(user_custom_gcs[user_id])}`",
                reply_markup=main_menu_keyboard()
            )
        user_states.pop(user_id, None)

    # 5. Capture Photo
    elif step == "AWAITING_PHOTO":
        if not message.photo:
            await message.reply_text("❌ Please send a valid **photo**.")
            return
        
        user_states[user_id]["photo_file_id"] = message.photo.file_id
        user_states[user_id]["step"] = "AWAITING_TEXT"
        await message.reply_text("📝 Photo saved! Now send your **Promo Text Message / Caption**.")

    # 6. Capture Text
    elif step == "AWAITING_TEXT":
        promo_text = message.text or message.caption or ""
        user_states[user_id]["promo_text"] = promo_text
        user_states[user_id]["step"] = "AWAITING_LOOP_CHOICE"

        await message.reply_text(
            "🔁 **Loop Settings:**\n\n"
            "Do you want to send this broadcast on a **continuous loop / scheduled delay**, or send it **one-time only**?",
            reply_markup=loop_ask_keyboard()
        )

    # 7. Custom Delay Input
    elif step == "AWAITING_CUSTOM_DELAY":
        if not message.text.isdigit() or int(message.text) <= 0:
            await message.reply_text("❌ Invalid duration! Please enter a positive number in minutes (e.g. `12`).")
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
# AUTO-JOIN HELPER FOR CUSTOM GROUPS
# ------------------------------------------------------------------
async def ensure_group_joined(client: Client, gc_target: str) -> str:
    """Checks if the account is in the group. If not, auto-joins via link/username."""
    target_clean = gc_target.strip()
    
    # 1. Invite Link Handling (e.g., https://t.me/+AbCdEf... or https://t.me/joinchat/...)
    if "joinchat/" in target_clean or "t.me/+" in target_clean or "t.me/joinchat/" in target_clean:
        try:
            chat = await client.join_chat(target_clean)
            return chat.id
        except UserAlreadyParticipant:
            # Get entity ID if already joined
            chat = await client.get_chat(target_clean)
            return chat.id
        except Exception as e:
            logger.error(f"Failed to join via invite link {target_clean}: {e}")
            raise e

    # 2. Username or Chat ID Handling
    else:
        # Convert numeric string to integer chat_id if applicable
        if target_clean.startswith("-100") or target_clean.lstrip('-').isdigit():
            target_clean = int(target_clean)

        try:
            chat = await client.get_chat(target_clean)
            return chat.id
        except Exception:
            # If get_chat fails, try joining if it's a username
            try:
                chat = await client.join_chat(target_clean)
                return chat.id
            except Exception as join_err:
                logger.error(f"Failed to fetch/join target {target_clean}: {join_err}")
                raise join_err

# ------------------------------------------------------------------
# BROADCAST ENGINE
# ------------------------------------------------------------------
async def run_user_broadcast(owner_id: int, target: str, text: str, photo_file_id: str = None, interval_minutes: int = 0):
    try:
        while True:
            my_accounts = user_sessions.get(owner_id, {})
            custom_gcs = user_custom_gcs.get(owner_id, [])
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

                    # ------------------------------------------------------
                    # MODE A: SELECTED GROUPS ONLY (MANUAL TARGETING)
                    # ------------------------------------------------------
                    if target == "promo_custom":
                        for gc_item in custom_gcs:
                            try:
                                target_chat_id = await ensure_group_joined(user_client, gc_item)

                                if local_photo_path:
                                    await user_client.send_photo(target_chat_id, photo=local_photo_path, caption=text)
                                else:
                                    await user_client.send_message(target_chat_id, text=text)

                                total_sent += 1
                                await asyncio.sleep(2)

                            except SlowmodeWait as e:
                                logger.info(f"Slow Mode active in {gc_item}. Waiting {e.value}s")
                                await asyncio.sleep(e.value)
                                try:
                                    if local_photo_path:
                                        await user_client.send_photo(target_chat_id, photo=local_photo_path, caption=text)
                                    else:
                                        await user_client.send_message(target_chat_id, text=text)
                                    total_sent += 1
                                except Exception:
                                    total_failed += 1

                            except FloodWait as e:
                                logger.info(f"FloodWait hit. Waiting {e.value}s")
                                await asyncio.sleep(e.value)

                            except Exception as err:
                                logger.error(f"Failed sending to {gc_item} via {phone}: {err}")
                                total_failed += 1

                    # ------------------------------------------------------
                    # MODE B: ALL JOINED DIALOGS (GC / DM / BOTH)
                    # ------------------------------------------------------
                    else:
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
                                    await asyncio.sleep(2)
                                
                                except SlowmodeWait as e:
                                    logger.info(f"Slow Mode active in {chat.id}. Waiting {e.value}s")
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
                                    logger.error(f"Failed sending to {chat.title or chat.id} via {phone}: {err}")
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
