import os
import asyncio
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError

# --- الإعدادات (ضع بياناتك هنا) ---
API_ID = '35980161'             # ضع API_ID
API_HASH = 'd879538c1b65ee6aa57ac3b4ce4b63d3'     # ضع API_HASH
BOT_TOKEN = '8615971361:AAHI51Wd-fj5xKcUwbqyJxbgA7CuuSjebIY'   # ضع توكن البوت
ADMIN_ID = '8718973896'         # ضع ايديك (رقمك) هنا لتتحدث مع البوت

bot = TelegramClient('bot_manager', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# قواميس لحفظ الحسابات وحالات التسجيل
user_clients = {}
login_states = {}
is_waiting_for_code = False

# إنشاء مجلد لحفظ الجلسات
os.makedirs('sessions', exist_ok=True)

# --- دالة لتحميل الجلسات القديمة عند تشغيل البوت ---
async def load_saved_sessions():
    for filename in os.listdir('sessions'):
        if filename.endswith('.txt'):
            phone = filename.replace('.txt', '')
            with open(f'sessions/{filename}', 'r') as f:
                session_str = f.read().strip()
            
            client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
            await client.connect()
            if await client.is_user_authorized():
                user_clients[phone] = client
                register_otp_listener(client, phone)
                print(f"✅ تم تحميل الجلسة بنجاح: {phone}")

# --- دالة التقاط الرمز (تعمل على كل حساب مسجل) ---
def register_otp_listener(client, phone):
    @client.on(events.NewMessage(from_users=777000))
    async def otp_interceptor(event):
        global is_waiting_for_code
        if is_waiting_for_code:
            code = event.raw_text
            await bot.send_message(
                ADMIN_ID, 
                f"🔑 **وصل الرمز يا سيدي لحساب:** `{phone}`\n\n"
                f"**الرمز:**\n`{code}`\n\n"
                f"قم بنسخه فوراً."
            )
            is_waiting_for_code = False # إيقاف الانتظار بعد استلام الرمز

# --- أوامر البوت ---
@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    if event.sender_id != ADMIN_ID: return
    buttons = [
        [Button.inline("➕ تسجيل حساب جديد", data=b"add_account")],
        [Button.inline("⏳ انتظار رمز الدخول (رادار)", data=b"wait_otp")]
    ]
    await event.respond("أهلاً بك يا سيدي في خزنة الجلسات.\nماذا تريد أن تفعل؟", buttons=buttons)

@bot.on(events.CallbackQuery(data=b"add_account"))
async def add_account_handler(event):
    login_states[event.sender_id] = {'state': 'waiting_phone'}
    await event.edit("أرسل رقم هاتفك مع رمز الدولة (مثال: +213xxxxxxxx):")

@bot.on(events.CallbackQuery(data=b"wait_otp"))
async def wait_otp_handler(event):
    global is_waiting_for_code
    if not user_clients:
        await event.answer("لا توجد حسابات مسجلة بعد!", alert=True)
        return
    
    is_waiting_for_code = True
    await event.edit("✅ **الرادار يعمل الآن...**\nاذهب لهاتفك وأدخل رقمك، وبمجرد وصول الكود سأرسله لك هنا.")

# --- معالجة الرسائل (لتسجيل الحساب) ---
@bot.on(events.NewMessage())
async def message_handler(event):
    if event.sender_id != ADMIN_ID or event.raw_text.startswith('/'): return
    
    state_data = login_states.get(event.sender_id)
    if not state_data: return

    state = state_data.get('state')
    text = event.raw_text.strip()

    if state == 'waiting_phone':
        phone = text
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        await client.connect()
        try:
            await client.send_code_request(phone)
            login_states[event.sender_id] = {'state': 'waiting_code', 'phone': phone, 'client': client}
            await event.respond("✅ تم إرسال الكود لهاتفك. أرسل الكود هنا الآن:")
        except Exception as e:
            await event.respond(f"❌ خطأ: {e}")
            del login_states[event.sender_id]

    elif state == 'waiting_code':
        code = text
        phone = state_data['phone']
        client = state_data['client']
        try:
            await client.sign_in(phone, code)
            session_str = StringSession.save(client.session)
            with open(f'sessions/{phone}.txt', 'w') as f:
                f.write(session_str)
            
            user_clients[phone] = client
            register_otp_listener(client, phone)
            
            await event.respond(f"🔥 تم تسجيل الدخول وحفظ الجلسة بنجاح!\nالحساب الآن محفوظ في الخزنة.")
            del login_states[event.sender_id]
            
        except SessionPasswordNeededError:
            login_states[event.sender_id]['state'] = 'waiting_password'
            await event.respond("🔐 الحساب محمي بكلمة مرور (2FA). أرسل كلمة المرور:")
        except Exception as e:
            await event.respond(f"❌ كود خاطئ: {e}")

    elif state == 'waiting_password':
        password = text
        phone = state_data['phone']
        client = state_data['client']
        try:
            await client.sign_in(password=password)
            session_str = StringSession.save(client.session)
            with open(f'sessions/{phone}.txt', 'w') as f:
                f.write(session_str)
            
            user_clients[phone] = client
            register_otp_listener(client, phone)
            
            await event.respond("🔥 تم تسجيل الدخول وحفظ الجلسة بنجاح (مع 2FA)!")
            del login_states[event.sender_id]
        except Exception as e:
            await event.respond(f"❌ كلمة مرور خاطئة: {e}")

# --- التشغيل (متوافق مع Pydroid 3) ---
if __name__ == '__main__':
    print("جاري تشغيل النظام...")
    bot.loop.run_until_complete(load_saved_sessions())
    print("النظام يعمل الآن. اذهب للبوت واكتب /start")
    bot.run_until_disconnected()
