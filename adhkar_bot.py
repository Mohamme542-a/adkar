# -*- coding: utf-8 -*-
"""
بوت أذكار الصباح والمساء للقنوات (تيليجرام)
═══════════════════════════════════════════
الفكرة : في وقت الصباح والمساء ينشر البوت في قناتك منشوراً فيه زر «ابدأ الأذكار».
          الضغط على الزر يفتح للمستخدم محادثة البوت (ويسجّله تلقائياً أول مرة)، وهناك يظهر له
          الذكر وتحته زر أزرق عليه العدد (مثلاً 100): كل ضغطة تُنقص العدد، وعند 0 ينتقل للذكر
          التالي حتى تنتهي الأذكار. لكل مستخدم عدّاده الخاص، ويتكرر ذلك تلقائياً كل يوم.

التثبيت :  pip install -U -r requirements.txt
التشغيل :  BOT_TOKEN=xxxx ADMIN_IDS=123456789 python adhkar_bot.py
المطلوب :  أضف البوت «مشرفاً» في قناتك بصلاحية «نشر الرسائل» (ويُفضّل «حذف الرسائل»)،
          ثم افتح البوت في الخاص واضغط «إضافة قناة».
"""
import asyncio
import html
import json
import logging
import os
import re
import secrets
import sys
import threading
import time
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, HTTPServer
from zoneinfo import ZoneInfo

from telegram import (BotCommand, BotCommandScopeChat, InlineKeyboardButton,
                      InlineKeyboardMarkup, Update)
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

# ══════════════════════════ الإعدادات ══════════════════════════
def _ids(s):
    return [int(x) for x in re.split(r"[,\s]+", s or "") if x.strip().lstrip("-").isdigit()]

BOT_TOKEN = os.getenv("BOT_TOKEN", "8439911839:AAFoB40vsbRST5BKz1Y0CLecb2mu61nDDvU")            # أو: BOT_TOKEN = "123456:ABC..."
ADMIN_IDS = [
    # 123456789,      ← اكتب أيدي حسابك هنا (أو استخدم متغير البيئة ADMIN_IDS)
] + _ids(os.getenv("ADMIN_IDS", "8950382997"))

DATA_DIR = os.getenv("DATA_DIR", "data")
DEFAULT_TZ = os.getenv("TIMEZONE", "Asia/Riyadh")         # يمكن تغييرها من لوحة التحكم
DEFAULT_MORNING = os.getenv("MORNING_TIME", "06:00")
DEFAULT_EVENING = os.getenv("EVENING_TIME", "17:00")
ENV_CHANNELS = [x.strip() for x in os.getenv("CHANNELS", "").split(",") if x.strip()]   # مثال: @mychannel

GRACE_MIN = 180        # لو تأخر البوت (عطل/إعادة تشغيل) ينشر خلال هذه المدة بعد الوقت المحدد، وبعدها يتخطى
EDIT_GAP = 0.7         # أقل فاصل (ثواني) بين تعديلين لنفس رسالة المستخدم
EDIT_BATCH = 15        # عدد التعديلات المتزامنة في الدفعة الواحدة (حدود تيليجرام ~30 رسالة/ثانية)
REMIND_GAP = 0.04      # فاصل بين رسائل التذكير الخاص (≈25 رسالة/ثانية)
KEEP_DAYS = 2          # مدة الاحتفاظ بجلسات المستخدمين السابقة

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("adhkar")
esc = html.escape
AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

# ══════════════════════════ الأذكار (من الكتاب والسنة الصحيحة) ══════════════════════════
# text = نص الذكر • count = عدد التكرار • virtue = الفضل (إن ثبت) • src = المصدر
PBUH = "صلى الله عليه وسلم"

KURSI = {
    "text": "﴿اللَّهُ لَا إِلَٰهَ إِلَّا هُوَ الْحَيُّ الْقَيُّومُ لَا تَأْخُذُهُ سِنَةٌ وَلَا نَوْمٌ لَهُ مَا فِي السَّمَاوَاتِ "
            "وَمَا فِي الْأَرْضِ مَنْ ذَا الَّذِي يَشْفَعُ عِنْدَهُ إِلَّا بِإِذْنِهِ يَعْلَمُ مَا بَيْنَ أَيْدِيهِمْ وَمَا خَلْفَهُمْ "
            "وَلَا يُحِيطُونَ بِشَيْءٍ مِنْ عِلْمِهِ إِلَّا بِمَا شَاءَ وَسِعَ كُرْسِيُّهُ السَّمَاوَاتِ وَالْأَرْضَ وَلَا يَئُودُهُ "
            "حِفْظُهُمَا وَهُوَ الْعَلِيُّ الْعَظِيمُ﴾",
    "count": 1,
    "virtue": "من قالها حين يُصبح أُجير من الجنّ حتى يُمسي، ومن قالها حين يُمسي أُجير منهم حتى يُصبح.",
    "src": "رواه الحاكم",
}
IKHLAS = {
    "text": "بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ\n"
            "﴿قُلْ هُوَ اللَّهُ أَحَدٌ\nاللَّهُ الصَّمَدُ\nلَمْ يَلِدْ وَلَمْ يُولَدْ\nوَلَمْ يَكُنْ لَهُ كُفُوًا أَحَدٌ﴾",
    "count": 3,
    "virtue": "من قرأ الإخلاص والمعوّذتين ثلاثاً حين يُصبح وحين يُمسي كفَتْه من كل شيء.",
    "src": "رواه أبو داود والترمذي",
}
FALAQ = {
    "text": "بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ\n"
            "﴿قُلْ أَعُوذُ بِرَبِّ الْفَلَقِ\nمِنْ شَرِّ مَا خَلَقَ\nوَمِنْ شَرِّ غَاسِقٍ إِذَا وَقَبَ\n"
            "وَمِنْ شَرِّ النَّفَّاثَاتِ فِي الْعُقَدِ\nوَمِنْ شَرِّ حَاسِدٍ إِذَا حَسَدَ﴾",
    "count": 3, "virtue": "", "src": "رواه أبو داود والترمذي",
}
NAS = {
    "text": "بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ\n"
            "﴿قُلْ أَعُوذُ بِرَبِّ النَّاسِ\nمَلِكِ النَّاسِ\nإِلَٰهِ النَّاسِ\nمِنْ شَرِّ الْوَسْوَاسِ الْخَنَّاسِ\n"
            "الَّذِي يُوَسْوِسُ فِي صُدُورِ النَّاسِ\nمِنَ الْجِنَّةِ وَالنَّاسِ﴾",
    "count": 3, "virtue": "", "src": "رواه أبو داود والترمذي",
}
SAYYID = {
    "text": "اللَّهُمَّ أَنْتَ رَبِّي لَا إِلَٰهَ إِلَّا أَنْتَ، خَلَقْتَنِي وَأَنَا عَبْدُكَ، وَأَنَا عَلَى عَهْدِكَ "
            "وَوَعْدِكَ مَا اسْتَطَعْتُ، أَعُوذُ بِكَ مِنْ شَرِّ مَا صَنَعْتُ، أَبُوءُ لَكَ بِنِعْمَتِكَ عَلَيَّ، "
            "وَأَبُوءُ بِذَنْبِي فَاغْفِرْ لِي، فَإِنَّهُ لَا يَغْفِرُ الذُّنُوبَ إِلَّا أَنْتَ",
    "count": 1,
    "virtue": "من قالها موقناً بها في النهار فمات من يومه قبل أن يُمسي فهو من أهل الجنة، "
              "ومن قالها موقناً بها في الليل فمات قبل أن يُصبح فهو من أهل الجنة.",
    "src": "رواه البخاري",
}
AFINI = {
    "text": "اللَّهُمَّ عَافِنِي فِي بَدَنِي، اللَّهُمَّ عَافِنِي فِي سَمْعِي، اللَّهُمَّ عَافِنِي فِي بَصَرِي، "
            "لَا إِلَٰهَ إِلَّا أَنْتَ.\nاللَّهُمَّ إِنِّي أَعُوذُ بِكَ مِنَ الْكُفْرِ وَالْفَقْرِ، وَأَعُوذُ بِكَ مِنْ عَذَابِ "
            "الْقَبْرِ، لَا إِلَٰهَ إِلَّا أَنْتَ",
    "count": 3, "virtue": "", "src": "رواه أبو داود",
}
BISMILLAH = {
    "text": "بِسْمِ اللَّهِ الَّذِي لَا يَضُرُّ مَعَ اسْمِهِ شَيْءٌ فِي الْأَرْضِ وَلَا فِي السَّمَاءِ وَهُوَ السَّمِيعُ الْعَلِيمُ",
    "count": 3,
    "virtue": "من قالها ثلاثاً حين يُصبح وثلاثاً حين يُمسي لم يضرّه شيء.",
    "src": "رواه أبو داود والترمذي",
}
RADEETU = {
    "text": f"رَضِيتُ بِاللَّهِ رَبًّا، وَبِالْإِسْلَامِ دِينًا، وَبِمُحَمَّدٍ {PBUH} نَبِيًّا",
    "count": 3,
    "virtue": "من قالها حين يُصبح وحين يُمسي كان حقاً على الله أن يُرضيه يوم القيامة.",
    "src": "رواه أحمد وأبو داود والترمذي",
}
YA_HAYY = {
    "text": "يَا حَيُّ يَا قَيُّومُ بِرَحْمَتِكَ أَسْتَغِيثُ، أَصْلِحْ لِي شَأْنِي كُلَّهُ، وَلَا تَكِلْنِي إِلَى نَفْسِي طَرْفَةَ عَيْنٍ",
    "count": 1, "virtue": "", "src": "رواه الحاكم",
}
ALEM_GHAYB = {
    "text": "اللَّهُمَّ عَالِمَ الْغَيْبِ وَالشَّهَادَةِ، فَاطِرَ السَّمَاوَاتِ وَالْأَرْضِ، رَبَّ كُلِّ شَيْءٍ وَمَلِيكَهُ، "
            "أَشْهَدُ أَنْ لَا إِلَٰهَ إِلَّا أَنْتَ، أَعُوذُ بِكَ مِنْ شَرِّ نَفْسِي، وَمِنْ شَرِّ الشَّيْطَانِ وَشِرْكِهِ، "
            "وَأَنْ أَقْتَرِفَ عَلَى نَفْسِي سُوءًا أَوْ أَجُرَّهُ إِلَى مُسْلِمٍ",
    "count": 1, "virtue": "", "src": "رواه الترمذي وأبو داود",
}
AFWA = {
    "text": "اللَّهُمَّ إِنِّي أَسْأَلُكَ الْعَفْوَ وَالْعَافِيَةَ فِي الدُّنْيَا وَالْآخِرَةِ، اللَّهُمَّ إِنِّي أَسْأَلُكَ "
            "الْعَفْوَ وَالْعَافِيَةَ فِي دِينِي وَدُنْيَايَ وَأَهْلِي وَمَالِي، اللَّهُمَّ اسْتُرْ عَوْرَاتِي وَآمِنْ رَوْعَاتِي، "
            "اللَّهُمَّ احْفَظْنِي مِنْ بَيْنِ يَدَيَّ وَمِنْ خَلْفِي، وَعَنْ يَمِينِي وَعَنْ شِمَالِي وَمِنْ فَوْقِي، "
            "وَأَعُوذُ بِعَظَمَتِكَ أَنْ أُغْتَالَ مِنْ تَحْتِي",
    "count": 1, "virtue": "", "src": "رواه أبو داود وابن ماجه",
}
SUBHAN_100 = {
    "text": "سُبْحَانَ اللَّهِ وَبِحَمْدِهِ",
    "count": 100,
    "virtue": "من قالها مائة مرة حين يُصبح وحين يُمسي لم يأتِ أحدٌ يوم القيامة بأفضل مما جاء به، "
              "إلا أحدٌ قال مثل ما قال أو زاد عليه.",
    "src": "رواه مسلم",
}
ISTIGHFAR_100 = {
    "text": "أَسْتَغْفِرُ اللَّهَ وَأَتُوبُ إِلَيْهِ",
    "count": 100,
    "virtue": f"كان النبي {PBUH} يستغفر الله ويتوب إليه في اليوم أكثر من سبعين مرة، وفي رواية: مائة مرة.",
    "src": "رواه البخاري ومسلم",
}
SALAWAT = {
    "text": "اللَّهُمَّ صَلِّ وَسَلِّمْ عَلَى نَبِيِّنَا مُحَمَّدٍ",
    "count": 10,
    "virtue": "من صلّى عليّ صلاةً صلّى الله عليه بها عشراً.",
    "src": "رواه مسلم",
}

MORNING = [
    KURSI, IKHLAS, FALAQ, NAS,
    {"text": "أَصْبَحْنَا وَأَصْبَحَ الْمُلْكُ لِلَّهِ، وَالْحَمْدُ لِلَّهِ، لَا إِلَٰهَ إِلَّا اللَّهُ وَحْدَهُ لَا شَرِيكَ لَهُ، "
             "لَهُ الْمُلْكُ وَلَهُ الْحَمْدُ وَهُوَ عَلَى كُلِّ شَيْءٍ قَدِيرٌ، رَبِّ أَسْأَلُكَ خَيْرَ مَا فِي هَذَا الْيَوْمِ "
             "وَخَيْرَ مَا بَعْدَهُ، وَأَعُوذُ بِكَ مِنْ شَرِّ مَا فِي هَذَا الْيَوْمِ وَشَرِّ مَا بَعْدَهُ، رَبِّ أَعُوذُ بِكَ مِنَ "
             "الْكَسَلِ وَسُوءِ الْكِبَرِ، رَبِّ أَعُوذُ بِكَ مِنْ عَذَابٍ فِي النَّارِ وَعَذَابٍ فِي الْقَبْرِ",
     "count": 1, "virtue": "", "src": "رواه مسلم"},
    {"text": "اللَّهُمَّ بِكَ أَصْبَحْنَا، وَبِكَ أَمْسَيْنَا، وَبِكَ نَحْيَا، وَبِكَ نَمُوتُ، وَإِلَيْكَ النُّشُورُ",
     "count": 1, "virtue": "", "src": "رواه الترمذي"},
    SAYYID, AFINI, BISMILLAH, RADEETU, YA_HAYY,
    {"text": f"أَصْبَحْنَا عَلَى فِطْرَةِ الْإِسْلَامِ، وَعَلَى كَلِمَةِ الْإِخْلَاصِ، وَعَلَى دِينِ نَبِيِّنَا مُحَمَّدٍ {PBUH}، "
             "وَعَلَى مِلَّةِ أَبِينَا إِبْرَاهِيمَ حَنِيفًا مُسْلِمًا وَمَا كَانَ مِنَ الْمُشْرِكِينَ",
     "count": 1, "virtue": "", "src": "رواه أحمد"},
    ALEM_GHAYB, AFWA,
    {"text": "سُبْحَانَ اللَّهِ وَبِحَمْدِهِ، عَدَدَ خَلْقِهِ، وَرِضَا نَفْسِهِ، وَزِنَةَ عَرْشِهِ، وَمِدَادَ كَلِمَاتِهِ",
     "count": 3, "virtue": "", "src": "رواه مسلم"},
    SUBHAN_100,
    {"text": "لَا إِلَٰهَ إِلَّا اللَّهُ وَحْدَهُ لَا شَرِيكَ لَهُ، لَهُ الْمُلْكُ وَلَهُ الْحَمْدُ وَهُوَ عَلَى كُلِّ شَيْءٍ قَدِيرٌ",
     "count": 100,
     "virtue": "من قالها في يومٍ مائة مرة كانت له عدل عشر رقاب، وكُتبت له مائة حسنة، ومُحيت عنه مائة سيئة، "
               "وكانت له حرزاً من الشيطان يومه ذلك حتى يُمسي، ولم يأتِ أحدٌ بأفضل مما جاء به إلا رجلٌ عمل أكثر من ذلك.",
     "src": "متفق عليه"},
    ISTIGHFAR_100, SALAWAT,
]

EVENING = [
    KURSI, IKHLAS, FALAQ, NAS,
    {"text": "أَمْسَيْنَا وَأَمْسَى الْمُلْكُ لِلَّهِ، وَالْحَمْدُ لِلَّهِ، لَا إِلَٰهَ إِلَّا اللَّهُ وَحْدَهُ لَا شَرِيكَ لَهُ، "
             "لَهُ الْمُلْكُ وَلَهُ الْحَمْدُ وَهُوَ عَلَى كُلِّ شَيْءٍ قَدِيرٌ، رَبِّ أَسْأَلُكَ خَيْرَ مَا فِي هَذِهِ اللَّيْلَةِ "
             "وَخَيْرَ مَا بَعْدَهَا، وَأَعُوذُ بِكَ مِنْ شَرِّ مَا فِي هَذِهِ اللَّيْلَةِ وَشَرِّ مَا بَعْدَهَا، رَبِّ أَعُوذُ بِكَ "
             "مِنَ الْكَسَلِ وَسُوءِ الْكِبَرِ، رَبِّ أَعُوذُ بِكَ مِنْ عَذَابٍ فِي النَّارِ وَعَذَابٍ فِي الْقَبْرِ",
     "count": 1, "virtue": "", "src": "رواه مسلم"},
    {"text": "اللَّهُمَّ بِكَ أَمْسَيْنَا، وَبِكَ أَصْبَحْنَا، وَبِكَ نَحْيَا، وَبِكَ نَمُوتُ، وَإِلَيْكَ الْمَصِيرُ",
     "count": 1, "virtue": "", "src": "رواه الترمذي"},
    SAYYID, AFINI, BISMILLAH, RADEETU,
    {"text": "أَعُوذُ بِكَلِمَاتِ اللَّهِ التَّامَّاتِ مِنْ شَرِّ مَا خَلَقَ",
     "count": 3, "virtue": "من قالها ثلاثاً حين يُمسي لم تضرّه حُمَةٌ تلك الليلة.", "src": "رواه أحمد والترمذي"},
    YA_HAYY,
    {"text": f"أَمْسَيْنَا عَلَى فِطْرَةِ الْإِسْلَامِ، وَعَلَى كَلِمَةِ الْإِخْلَاصِ، وَعَلَى دِينِ نَبِيِّنَا مُحَمَّدٍ {PBUH}، "
             "وَعَلَى مِلَّةِ أَبِينَا إِبْرَاهِيمَ حَنِيفًا مُسْلِمًا وَمَا كَانَ مِنَ الْمُشْرِكِينَ",
     "count": 1, "virtue": "", "src": "رواه أحمد"},
    ALEM_GHAYB, AFWA,
    {"text": "﴿آمَنَ الرَّسُولُ بِمَا أُنْزِلَ إِلَيْهِ مِنْ رَبِّهِ وَالْمُؤْمِنُونَ كُلٌّ آمَنَ بِاللَّهِ وَمَلَائِكَتِهِ "
             "وَكُتُبِهِ وَرُسُلِهِ لَا نُفَرِّقُ بَيْنَ أَحَدٍ مِنْ رُسُلِهِ وَقَالُوا سَمِعْنَا وَأَطَعْنَا غُفْرَانَكَ "
             "رَبَّنَا وَإِلَيْكَ الْمَصِيرُ\nلَا يُكَلِّفُ اللَّهُ نَفْسًا إِلَّا وُسْعَهَا لَهَا مَا كَسَبَتْ وَعَلَيْهَا مَا "
             "اكْتَسَبَتْ رَبَّنَا لَا تُؤَاخِذْنَا إِنْ نَسِينَا أَوْ أَخْطَأْنَا رَبَّنَا وَلَا تَحْمِلْ عَلَيْنَا إِصْرًا كَمَا "
             "حَمَلْتَهُ عَلَى الَّذِينَ مِنْ قَبْلِنَا رَبَّنَا وَلَا تُحَمِّلْنَا مَا لَا طَاقَةَ لَنَا بِهِ وَاعْفُ عَنَّا "
             "وَاغْفِرْ لَنَا وَارْحَمْنَا أَنْتَ مَوْلَانَا فَانْصُرْنَا عَلَى الْقَوْمِ الْكَافِرِينَ﴾",
     "count": 1, "virtue": "من قرأ بالآيتين من آخر سورة البقرة في ليلة كفتاه.", "src": "متفق عليه"},
    SUBHAN_100,
    {"text": "لَا إِلَٰهَ إِلَّا اللَّهُ وَحْدَهُ لَا شَرِيكَ لَهُ، لَهُ الْمُلْكُ وَلَهُ الْحَمْدُ وَهُوَ عَلَى كُلِّ شَيْءٍ قَدِيرٌ",
     "count": 10, "virtue": "من قالها عشر مرات كان كمن أعتق أربعة أنفس من ولد إسماعيل.", "src": "رواه مسلم"},
    ISTIGHFAR_100, SALAWAT,
]

ADHKAR = {"morning": MORNING, "evening": EVENING}
TITLES = {"morning": "أذكار الصباح", "evening": "أذكار المساء"}
KINDS = ("morning", "evening")


# ══════════════════════════ الأزرار الملونة ══════════════════════════
_STYLE_SUPPORTED = None


def IBtn(text, style=None, **kw):
    """زر inline. style: primary (أزرق) / success (أخضر) / danger (أحمر).
    إن كانت نسخة المكتبة قديمة لا تدعم الألوان يُنشأ زر عادي بدل أن يتعطل البوت."""
    global _STYLE_SUPPORTED
    if style and _STYLE_SUPPORTED is not False:
        try:
            b = InlineKeyboardButton(text, style=style, **kw)
            _STYLE_SUPPORTED = True
            return b
        except TypeError:
            _STYLE_SUPPORTED = False
    return InlineKeyboardButton(text, **kw)


# ══════════════════════════ الحالة والتخزين ══════════════════════════
def _atomic_write(path, data: bytes):
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def default_settings():
    return {"tz": DEFAULT_TZ, "morning": DEFAULT_MORNING, "evening": DEFAULT_EVENING,
            "morning_on": True, "evening_on": True, "enabled": True, "delete_old": False, "reminders": True}


@lru_cache(maxsize=64)
def get_tz(name):
    try:
        return ZoneInfo(name)
    except Exception:
        return None


def now_local():
    tz = get_tz(state.settings["tz"]) or timezone(timedelta(hours=3))
    return datetime.now(tz)


def today_str():
    return now_local().date().isoformat()


_TIME_RE = re.compile(r"^(\d{1,2})(?:[:\.،](\d{2}))?\s*(am|pm|ص|م)?$", re.I)


def parse_hhmm(text):
    """يقبل 5:30 / 05:30 / 17:30 / 5:30 م / 6 ص ... ويعيد 'HH:MM' أو None."""
    t = str(text).translate(AR_DIGITS).strip().replace("：", ":").lower()
    m = _TIME_RE.match(t)
    if not m:
        return None
    h, mi, suf = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if mi > 59:
        return None
    if suf:
        if not 1 <= h <= 12:
            return None
        h = h % 12 + (12 if suf in ("pm", "م") else 0)
    elif h > 23:
        return None
    return f"{h:02d}:{mi:02d}"


def new_user(name=""):
    t = int(time.time())
    return {"name": str(name)[:64], "started": True, "remind": False, "welcomed": False, "joined": t, "last": t,
            "streak": {k: 0 for k in KINDS}, "last_done": {k: "" for k in KINDS},
            "days": {k: 0 for k in KINDS}, "taps": 0}


def clean_user(d):
    u = new_user(d.get("name", ""))
    for k in ("started", "remind", "welcomed"):
        if isinstance(d.get(k), bool):
            u[k] = d[k]
    for k in ("joined", "last", "taps"):
        try:
            u[k] = max(0, int(d.get(k, u[k])))
        except (TypeError, ValueError):
            pass
    for fld, cast in (("streak", int), ("days", int), ("last_done", str)):
        src = d.get(fld) if isinstance(d.get(fld), dict) else {}
        for kd in KINDS:
            try:
                v = cast(src.get(kd, u[fld][kd]))
                u[fld][kd] = max(0, v) if cast is int else v
            except (TypeError, ValueError):
                pass
    return u


def clean_session(sid, s):
    if s["kind"] not in KINDS:
        raise ValueError("kind")
    uid = int(s["uid"])
    return {"sid": str(sid), "uid": uid, "chat": uid, "kind": s["kind"],
            "mid": int(s["mid"]) if s.get("mid") else None, "idx": int(s["idx"]), "left": int(s["left"]),
            "done": bool(s.get("done")), "closed": bool(s.get("closed")), "taps": int(s.get("taps", 0)),
            "ts": float(s.get("ts", time.time())), "date": str(s.get("date", "")),
            "streak": int(s.get("streak", 0)), "edit": s.get("edit") if s.get("edit") in ("markup", "full") else None}


class State:
    def __init__(self, folder):
        os.makedirs(folder, exist_ok=True)
        self.dir = folder
        self.path = os.path.join(folder, "adhkar_state.json")      # القنوات والإعدادات
        self.upath = os.path.join(folder, "adhkar_users.json")     # المستخدمون وجلساتهم
        self.channels, self.sent, self.posts, self.reminded = [], {}, {}, {}
        self.settings = default_settings()
        self.users, self.sessions, self._idx = {}, {}, {}
        self.dirty = self.udirty = False
        self._last_u = 0.0

        data = self._load(self.path)
        if isinstance(data, dict):
            for c in data.get("channels", []):
                if isinstance(c, dict) and isinstance(c.get("id"), int):
                    self.channels.append({"id": c["id"], "title": str(c.get("title", "")),
                                          "username": str(c.get("username", ""))})
            st = data.get("settings", {})
            if isinstance(st, dict):
                for k, dv in self.settings.items():
                    if k in st and type(st[k]) is type(dv):
                        self.settings[k] = st[k]
            for fld in ("sent", "posts", "reminded"):
                if isinstance(data.get(fld), dict):
                    setattr(self, fld, data[fld])
        ud = self._load(self.upath)
        if isinstance(ud, dict):
            for uid, d in (ud.get("users") or {}).items():
                if str(uid).lstrip("-").isdigit() and isinstance(d, dict):
                    self.users[str(uid)] = clean_user(d)
            for sid, s in (ud.get("sessions") or {}).items():
                try:
                    self.sessions[str(sid)] = clean_session(sid, s)
                except (KeyError, TypeError, ValueError):
                    continue
        self._reindex()

    def _load(self, path):
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            bad = f"{path}.corrupt-{int(time.time())}"
            os.replace(path, bad)
            log.error("ملف تالف %s (%s) — نُقل إلى %s", path, e, bad)
            return None

    # ---- فهرسة الجلسات: (مستخدم، نوع) ← جلسة واحدة ----
    def _reindex(self):
        self._idx = {}
        for sid, s in sorted(self.sessions.items(), key=lambda kv: kv[1]["ts"]):
            self._idx[(s["uid"], s["kind"])] = sid

    def find(self, uid, kind):
        return self.sessions.get(self._idx.get((uid, kind)))

    def add_session(self, s):
        self.sessions[s["sid"]] = s
        self._idx[(s["uid"], s["kind"])] = s["sid"]
        self.udirty = True

    def remove_session(self, sid):
        s = self.sessions.pop(sid, None)
        if s and self._idx.get((s["uid"], s["kind"])) == sid:
            del self._idx[(s["uid"], s["kind"])]
        self.udirty = True

    # ---- المستخدمون ----
    def register(self, uid, name):
        k = str(uid)
        u = self.users.get(k)
        new = u is None
        if new:
            u = self.users[k] = new_user(name or "")
        else:
            if name:
                u["name"] = name[:64]
            u["started"] = True
        u["last"] = int(time.time())
        self.udirty = True
        return u, new

    # ---- الحفظ ----
    def flush(self, force=False):
        if self.dirty:
            self.dirty = False
            data = {"channels": self.channels, "settings": self.settings, "sent": self.sent,
                    "posts": self.posts, "reminded": self.reminded}
            _atomic_write(self.path, json.dumps(data, ensure_ascii=False).encode("utf-8"))
        if self.udirty and (force or time.time() - self._last_u >= 5):
            self.udirty = False
            self._last_u = time.time()
            sess = {sid: {k: v for k, v in s.items() if not k.startswith("_")} for sid, s in self.sessions.items()}
            _atomic_write(self.upath, json.dumps({"users": self.users, "sessions": sess},
                                                 ensure_ascii=False).encode("utf-8"))

    def purge(self):
        limit = time.time() - KEEP_DAYS * 86400
        for sid in [k for k, s in self.sessions.items() if s["ts"] < limit]:
            self.remove_session(sid)


state: State = None   # يُنشأ في main()


def is_admin(uid):
    return uid in ADMIN_IDS


def effective_streak(u, kind):
    """عدد الأيام المتتالية الحالي (يُصفَّر إن فاتك أمس واليوم)."""
    last = u["last_done"].get(kind, "")
    try:
        gap = (now_local().date() - date.fromisoformat(last)).days
    except ValueError:
        return 0
    return u["streak"].get(kind, 0) if 0 <= gap <= 1 else 0


# ══════════════════════════ عرض الأذكار ══════════════════════════
SEP = "━━━━━━━━━━━━━━"


def render_text(s):
    items = ADHKAR[s["kind"]]
    n, title = len(items), TITLES[s["kind"]]
    head = f"<b>{title}</b>"
    if s["done"] and s["closed"]:
        return f"{head}\n{SEP}\nتم إيقاف هذه الجلسة. ابدأ من جديد من القائمة."
    if s["done"]:
        extra = f"\nعدد الأيام المتتالية: <b>{s['streak']}</b>" if s.get("streak", 0) >= 2 else ""
        return (f"{head}\n{SEP}\nتمّت {title} بحمد الله تعالى.\n"
                f"عدد التكرارات: <b>{s['taps']}</b>{extra}\n\nتقبّل الله منك صالح الأعمال.")
    it = items[s["idx"]]
    parts = [f"{head}  •  الذكر {s['idx'] + 1} من {n}", SEP, f"<blockquote>{esc(it['text'])}</blockquote>"]
    if it.get("virtue"):
        parts.append(f"<i>{esc(it['virtue'])}</i>")
    parts.append(f"<i>[{esc(it['src'])}]</i>")
    parts.append(f"المطلوب: <b>{it['count']}</b> {'مرة' if it['count'] > 1 else 'مرة واحدة'}")
    if s["idx"] == 0:
        parts.append("\nاضغط الزر الأزرق عند كل تكرار، وسينتقل للذكر التالي عند الوصول إلى 0.")
    return "\n".join(parts)


def render_kb(s):
    if s["done"] or s["closed"]:
        return None
    return InlineKeyboardMarkup([
        [IBtn(str(s["left"]), callback_data=f"c:{s['sid']}:{s['idx']}", style="primary")],
        [IBtn("تخطي هذا الذكر", callback_data=f"k:{s['sid']}:{s['idx']}")]])


def ch_label(c):
    return c.get("title") or (("@" + c["username"]) if c.get("username") else str(c["id"]))


def short(t, n=28):
    t = re.sub(r"\s+", " ", str(t)).strip()
    return t if len(t) <= n else t[: n - 1] + "…"


# ══════════════════════════ الجلسات (لكل مستخدم عدّاده الخاص) ══════════════════════════
async def retire(bot, chat, mid):
    """يزيل رسالة جلسة قديمة من محادثة المستخدم: حذف، أو إزالة الأزرار إن تعذّر الحذف."""
    if not mid:
        return
    try:
        await bot.delete_message(chat, mid)
    except TelegramError:
        try:
            await bot.edit_message_reply_markup(chat_id=chat, message_id=mid, reply_markup=None)
        except TelegramError:
            pass


async def send_session_message(bot, s):
    msg = await bot.send_message(s["chat"], render_text(s), parse_mode=ParseMode.HTML, reply_markup=render_kb(s))
    s["mid"] = msg.message_id
    s["_msg_ts"] = time.time()
    state.udirty = True


async def start_user_session(bot, uid, kind):
    old = state.find(uid, kind)
    s = {"sid": secrets.token_hex(4), "uid": uid, "chat": uid, "kind": kind, "mid": None, "idx": 0,
         "left": ADHKAR[kind][0]["count"], "done": False, "closed": False, "taps": 0, "ts": time.time(),
         "date": today_str(), "streak": 0, "edit": None}
    await send_session_message(bot, s)            # إن فشل الإرسال (مثلاً حظر البوت) تبقى الجلسة القديمة كما هي
    if old:
        if not old["done"]:
            await retire(bot, old["chat"], old["mid"])
        state.remove_session(old["sid"])
    state.add_session(s)
    return s


async def begin(bot, uid, kind, force=False):
    """يبدأ/يتابع أذكار المستخدم في محادثته الخاصة. يعيد: new / resumed / dup / done."""
    old = state.find(uid, kind)
    if old and not old["closed"] and old["date"] == today_str() and not force:
        if old["done"]:
            await bot.send_message(
                uid, f"أتممت {TITLES[kind]} اليوم بحمد الله.\nتقبّل الله منك. هل تريد إعادتها؟",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[IBtn("أعد الأذكار", callback_data=f"r:{kind}", style="primary")],
                                                   [IBtn("القائمة", callback_data="m:menu")]]))
            return "done"
        if time.time() - old.get("_msg_ts", 0) < 8:       # ضغطتان متتاليتان (زر القناة + رابط البداية)
            return "dup"
        old_mid = old["mid"]
        await send_session_message(bot, old)               # يعيد إرسال الذكر الحالي في أسفل المحادثة
        await retire(bot, uid, old_mid)
        return "resumed"
    await start_user_session(bot, uid, kind)
    return "new"


def _advance(s):
    items = ADHKAR[s["kind"]]
    s["idx"] += 1
    s["edit"] = "full"
    state.udirty = True
    if s["idx"] >= len(items):
        s["done"], s["left"] = True, 0
        mark_completed(s)
        return "done"
    s["left"] = items[s["idx"]]["count"]
    return "next"


def register_tap(s):
    """ينقص العدّاد بمقدار واحد. يعيد 'tap' / 'next' / 'done'. (متزامن بالكامل ⇒ آمن مع الضغطات المتزامنة)"""
    s["left"] -= 1
    s["taps"] += 1
    state.udirty = True
    u = state.users.get(str(s["uid"]))
    if u:
        u["taps"] += 1
    if s["left"] > 0:
        s["edit"] = s["edit"] or "markup"
        return "tap"
    return _advance(s)


def mark_completed(s):
    """يسجّل إتمام اليوم ويحدّث سلسلة الأيام المتتالية (تُحتسب فقط إن ضغط ما لا يقل عن نصف التكرارات)."""
    s["streak"] = 0
    u = state.users.get(str(s["uid"]))
    if not u:
        return
    kind, d = s["kind"], s["date"]
    required = sum(i["count"] for i in ADHKAR[kind])
    if s["taps"] * 2 < required:
        return
    last = u["last_done"].get(kind, "")
    if last != d:
        try:
            prev = (date.fromisoformat(d) - timedelta(days=1)).isoformat()
        except ValueError:
            prev = ""
        u["streak"][kind] = u["streak"].get(kind, 0) + 1 if last == prev else 1
        u["last_done"][kind] = d
        u["days"][kind] += 1
    s["streak"] = u["streak"][kind]


async def _answer(q, text=None, url=None):
    try:
        if url:
            await q.answer(url=url)
        else:
            await q.answer(text)
    except TelegramError:
        pass                                      # استعلام قديم/منتهٍ — لا يهم


async def on_tap(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """c: = ضغطة عدّاد • k: = تخطي الذكر. لكل مستخدم جلسته الخاصة."""
    q = update.callback_query
    try:
        act, sid, idx = q.data.split(":")
        idx = int(idx)
    except ValueError:
        await _answer(q); return
    s = state.sessions.get(sid)
    if s is None or s["done"] or s["closed"] or s["uid"] != q.from_user.id:
        await _answer(q, "انتهت هذه الجلسة"); return
    if idx != s["idx"]:                          # زر قديم (الذكر تغيّر قبل وصول الضغطة)
        s["edit"] = "full"
        await _answer(q, "انتقلنا إلى الذكر التالي"); return
    res = register_tap(s) if act == "c" else _advance(s)
    await _answer(q, "تقبّل الله منك" if res == "done" else None)


# ══════════════════════════ التعديل المتراكم (يحمي من حدود تيليجرام) ══════════════════════════
_pause_until = 0.0


async def _edit_one(bot, s):
    global _pause_until
    mode = s.get("edit")
    s["edit"] = None
    s["_last"] = time.time()
    try:
        if mode == "full" or s["done"] or s["closed"]:
            await bot.edit_message_text(chat_id=s["chat"], message_id=s["mid"], text=render_text(s),
                                        parse_mode=ParseMode.HTML, reply_markup=render_kb(s))
        else:
            await bot.edit_message_reply_markup(chat_id=s["chat"], message_id=s["mid"], reply_markup=render_kb(s))
        state.udirty = True
    except RetryAfter as e:
        s["edit"] = "full" if "full" in (mode, s.get("edit")) else "markup"
        _pause_until = max(_pause_until, time.time() + float(e.retry_after) + 1)
        log.warning("حد التعديل: إيقاف مؤقت %s ثانية", e.retry_after)
    except BadRequest as e:
        m = str(e).lower()
        if "not modified" in m:
            pass
        elif "not found" in m or "can't be edited" in m or "message to edit" in m:
            s["done"] = s["closed"] = True                 # حذف المستخدم الرسالة
        else:
            log.warning("فشل التعديل: %s", e)
    except Forbidden:
        s["done"] = s["closed"] = True                     # حظر المستخدم البوت
        u = state.users.get(str(s["uid"]))
        if u:
            u["started"] = u["remind"] = False
    except TelegramError as e:                             # شبكة/مهلة: أعد المحاولة لاحقاً
        s["edit"] = s["edit"] or mode
        log.warning("خطأ مؤقت أثناء التعديل: %s", e)


async def edit_pass(bot):
    """تعديلات متزامنة على دفعات (الجلسات كثيرة، لكل مستخدم رسالته) مع فاصل لكل رسالة."""
    if time.time() < _pause_until:
        return
    now = time.time()
    due = [s for s in state.sessions.values() if s.get("edit") and s.get("mid") and now - s.get("_last", 0) >= EDIT_GAP]
    for i in range(0, len(due), EDIT_BATCH):
        await asyncio.gather(*(_edit_one(bot, s) for s in due[i:i + EDIT_BATCH]))
        if i + EDIT_BATCH < len(due):
            await asyncio.sleep(0.5)


# ══════════════════════════ منشورات القنوات والتذكير ══════════════════════════
_USERNAME = None


async def bot_username(bot):
    global _USERNAME
    if not _USERNAME:
        try:
            _USERNAME = bot.username
        except Exception:
            _USERNAME = None
        if not _USERNAME:
            _USERNAME = (await bot.get_me()).username
    return _USERNAME


def announce_text(kind):
    return (f"<b>{TITLES[kind]}</b>\n{SEP}\n"
            "﴿وَسَبِّحْ بِحَمْدِ رَبِّكَ بِالْعَشِيِّ وَالْإِبْكَارِ﴾\n\n"
            f"حان وقت {TITLES[kind]}.\n"
            "اضغط الزر لتبدأ في محادثة البوت، والعدّاد خاص بك وحدك.\n"
            "<i>إن كانت أول مرة تفتح فيها البوت فسيحوّلك إليه، اضغط START في أسفل المحادثة.</i>")


async def post_announcement(bot, chat_id, kind):
    """ينشر في القناة رسالة بها زر واحد «ابدأ الأذكار» (لا عدّاد مشترك)."""
    kb = InlineKeyboardMarkup([[IBtn(f"ابدأ {TITLES[kind]}", callback_data=f"j:{kind}", style="primary")]])
    msg = await bot.send_message(chat_id, announce_text(kind), parse_mode=ParseMode.HTML, reply_markup=kb)
    key = f"{chat_id}:{kind}"
    old = state.posts.get(key)
    state.posts[key] = {"mid": msg.message_id, "date": today_str()}
    state.dirty = True
    if old and state.settings["delete_old"]:
        try:
            await bot.delete_message(chat_id, old["mid"])
        except TelegramError as e:
            log.info("تعذّر حذف منشور الأمس: %s", e)
    return msg


async def on_join(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """زر القناة: المسجَّل يصله الذكر مباشرة في الخاص، وغير المسجَّل يُحوَّل لفتح البوت (start تلقائي)."""
    q = update.callback_query
    usr = q.from_user
    kind = q.data[2:]
    if kind not in KINDS:
        await _answer(q); return
    url = f"https://t.me/{await bot_username(ctx.bot)}?start={kind}"
    u = state.users.get(str(usr.id))
    if u and u.get("started"):
        try:
            await begin(ctx.bot, usr.id, kind)
        except Forbidden:                          # كان قد حظر البوت
            u["started"] = u["remind"] = False
            state.udirty = True
        except TelegramError as e:
            log.warning("تعذّر إرسال الأذكار إلى %s: %s", usr.id, e)
    await _answer(q, url=url)


async def send_reminders(bot, kind):
    """تذكير خاص لمن فعّله فقط، بوتيرة آمنة، ويتخطى من أتمّ أذكاره اليوم."""
    today, sent = today_str(), 0
    for uid, u in list(state.users.items()):
        if not (u.get("started") and u.get("remind")):
            continue
        s = state.find(int(uid), kind)
        if s and s["date"] == today and s["done"] and not s["closed"]:
            continue
        try:
            await bot.send_message(
                int(uid), f"<b>{TITLES[kind]}</b>\nحان وقت {TITLES[kind]}، فلا تغفل عنها.",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[IBtn(f"ابدأ {TITLES[kind]}", callback_data=f"m:{kind}", style="primary")]]))
            sent += 1
        except Forbidden:
            u["started"] = u["remind"] = False
            state.udirty = True
        except RetryAfter as e:
            await asyncio.sleep(float(e.retry_after) + 1)
        except TelegramError:
            pass
        await asyncio.sleep(REMIND_GAP)
    return sent


# ══════════════════════════ الجدولة ══════════════════════════
async def notify_admins(bot, text):
    for aid in ADMIN_IDS:
        try:
            await bot.send_message(aid, text, parse_mode=ParseMode.HTML)
        except TelegramError:
            pass


async def schedule_tick(bot):
    st = state.settings
    if not st["enabled"]:
        return
    now = now_local()
    today = now.date().isoformat()
    for kind in KINDS:
        if not st[f"{kind}_on"]:
            continue
        hh, mm = map(int, st[kind].split(":"))
        target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if not (target <= now < target + timedelta(minutes=GRACE_MIN)):
            continue
        for ch in list(state.channels):
            if state.sent.get(str(ch["id"]), {}).get(kind) == today:
                continue
            state.sent.setdefault(str(ch["id"]), {})[kind] = today     # يُسجَّل أولاً لمنع التكرار عند الفشل
            state.dirty = True
            try:
                await post_announcement(bot, ch["id"], kind)
                log.info("نُشرت %s في %s", TITLES[kind], ch_label(ch))
            except TelegramError as e:
                log.error("فشل نشر %s في %s: %s", TITLES[kind], ch_label(ch), e)
                await notify_admins(bot, f"<b>تعذّر نشر {TITLES[kind]}</b> في «{esc(ch_label(ch))}»:\n"
                                         f"{esc(str(e))}\nتأكد أن البوت مشرف ولديه صلاحية نشر الرسائل.")
        if st["reminders"] and state.reminded.get(kind) != today:
            state.reminded[kind] = today
            state.dirty = True
            n = await send_reminders(bot, kind)
            if n:
                log.info("أُرسل %d تذكير خاص (%s)", n, TITLES[kind])


def next_run_text():
    st, now = state.settings, now_local()
    best = None
    for kind in KINDS:
        if not st[f"{kind}_on"]:
            continue
        hh, mm = map(int, st[kind].split(":"))
        t = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if t <= now:
            t += timedelta(days=1)
        if best is None or t < best[0]:
            best = (t, kind)
    if not best:
        return "لا يوجد موعد (الصباح والمساء متوقفان)"
    t, kind = best
    return f"{TITLES[kind]} {t:%H:%M} ({'اليوم' if t.date() == now.date() else 'غداً'})"


async def loop_edit(app):
    while True:
        try:
            await asyncio.sleep(0.35)
            await edit_pass(app.bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("edit loop")


async def loop_schedule(app):
    while True:
        try:
            await schedule_tick(app.bot)
            await asyncio.sleep(15)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("schedule loop")
            await asyncio.sleep(15)


async def loop_flush(app):
    n = 0
    while True:
        try:
            await asyncio.sleep(3)
            state.flush()
            n += 1
            if n % 200 == 0:
                state.purge()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("flush loop")


# ══════════════════════════ القنوات ══════════════════════════
async def verify_channel(bot, ref):
    """يتحقق أن القناة موجودة وأن البوت مشرف فيها ويستطيع النشر. يعيد (معلومات, رسالة_خطأ)."""
    try:
        chat = await bot.get_chat(ref)
    except TelegramError:
        return None, ("لم أجد هذه القناة. تأكد من المعرف (مثل @mychannel)، وأن البوت مضاف فيها كمشرف. "
                      "للقنوات الخاصة حوّل لي رسالة منها.")
    if chat.type not in ("channel", "supergroup", "group"):
        return None, "هذه ليست قناة أو مجموعة."
    try:
        me = await bot.get_chat_member(chat.id, bot.id)
    except TelegramError:
        return None, "تعذّر فحص صلاحيات البوت في هذه القناة. تأكد أنه مشرف فيها."
    if me.status != "administrator":
        return None, "البوت ليس مشرفاً في هذه القناة. أضفه كمشرف بصلاحية «نشر الرسائل» ثم أعد المحاولة."
    if chat.type == "channel" and not getattr(me, "can_post_messages", False):
        return None, "البوت مشرف لكن ينقصه صلاحية «نشر الرسائل». فعّلها من إعدادات المشرفين."
    return {"id": chat.id, "title": chat.title or "", "username": chat.username or ""}, None


def parse_channel_ref(text):
    t = text.strip()
    t = re.sub(r"^https?://t\.me/", "", t, flags=re.I).strip("/ ")
    if re.fullmatch(r"-?\d{5,}", t):
        return int(t)
    if t.startswith("+") or t.lower().startswith("joinchat"):
        return None                                  # رابط دعوة خاص لا يمكن حلّه
    t = t.lstrip("@")
    return "@" + t if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,}", t) else None


def forwarded_chat(msg):
    fo = getattr(msg, "forward_origin", None)
    if fo is not None and getattr(fo, "chat", None) is not None:
        return fo.chat
    return getattr(msg, "forward_from_chat", None)


def add_channel(info):
    for c in state.channels:
        if c["id"] == info["id"]:
            c.update(info); state.dirty = True
            return False
    state.channels.append(info)
    state.dirty = True
    return True


async def safe_edit(q, text, markup=None):
    try:
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            log.debug("edit failed: %s", e)


# ══════════════════════════ واجهة المستخدم (الخاص) ══════════════════════════
def welcome_text(u):
    return (f"<b>تم تسجيلك بنجاح</b>\n{SEP}\n"
            f"أهلاً بك {esc(u['name'] or 'أخي الكريم')}.\n"
            "من الآن تستطيع قراءة أذكار الصباح والمساء هنا، والعدّاد خاص بك وحدك.\n\n"
            "اضغط على الأذكار التي تريد البدء بها:")


def kind_buttons(first=None):
    order = sorted(KINDS, key=lambda k: 0 if k == first else 1)
    return [[IBtn(f"ابدأ {TITLES[k]}", callback_data=f"m:{k}", style="primary")] for k in order]


def menu_text(u):
    return (f"<b>أذكار الصباح والمساء</b>\n{SEP}\n"
            "اختر الأذكار التي تريد قراءتها. العدّاد خاص بك وحدك، وتستطيع المتابعة من حيث توقفت.")


def menu_kb(uid, u):
    today, rows = today_str(), []
    for kind in KINDS:
        s = state.find(uid, kind)
        if s and s["date"] == today and not s["closed"]:
            label = f"{TITLES[kind]} (تمّت اليوم)" if s["done"] else f"متابعة {TITLES[kind]}"
        else:
            label = f"ابدأ {TITLES[kind]}"
        rows.append([IBtn(label, callback_data=f"m:{kind}", style="primary")])
    row = [IBtn("إحصائياتي", callback_data="m:stats")]
    if state.settings["reminders"]:
        row.append(IBtn("التذكير الخاص: " + ("مفعّل" if u.get("remind") else "متوقف"), callback_data="m:remind",
                        style="success" if u.get("remind") else None))
    rows.append(row)
    if is_admin(uid):
        rows.append([IBtn("لوحة التحكم", callback_data="ad:menu")])
    return InlineKeyboardMarkup(rows)


def stats_text(u):
    lines = [f"<b>إحصائياتي</b>\n{SEP}"]
    for k in KINDS:
        lines.append(f"{TITLES[k]}: أتممتها <b>{u['days'][k]}</b> يوماً • الأيام المتتالية: <b>{effective_streak(u, k)}</b>")
    lines.append(f"مجموع التكرارات: <b>{u['taps']}</b>")
    return "\n".join(lines)


async def on_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.pop("mode", None)
    usr, msg = update.effective_user, update.message
    arg = (ctx.args[0].lower() if getattr(ctx, "args", None) else "")
    u, new = state.register(usr.id, usr.first_name or usr.username or "")
    if new or not u["welcomed"]:                   # أول مرة: تسجيل + ترحيب ثم يضغط الزر بنفسه
        u["welcomed"] = True
        await msg.reply_text(welcome_text(u), parse_mode=ParseMode.HTML,
                             reply_markup=InlineKeyboardMarkup(kind_buttons(arg if arg in KINDS else None)))
        return
    if arg in KINDS:                               # مسجَّل مسبقاً: ابدأ مباشرة بلا خطوات إضافية
        await begin(ctx.bot, usr.id, arg)
        return
    await msg.reply_text(menu_text(u), parse_mode=ParseMode.HTML, reply_markup=menu_kb(usr.id, u))


async def on_user_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    usr, data = q.from_user, q.data
    u, _ = state.register(usr.id, usr.first_name or usr.username or "")
    if data.startswith("r:"):
        kind = data[2:]
        await _answer(q)
        if kind in KINDS:
            await begin(ctx.bot, usr.id, kind, force=True)
        return
    act = data[2:]
    await _answer(q)
    if act in KINDS:
        await begin(ctx.bot, usr.id, act)
    elif act == "menu":
        await safe_edit(q, menu_text(u), menu_kb(usr.id, u))
    elif act == "stats":
        await safe_edit(q, stats_text(u), InlineKeyboardMarkup([[IBtn("رجوع", callback_data="m:menu")]]))
    elif act == "remind":
        u["remind"] = not u.get("remind")
        state.udirty = True
        await safe_edit(q, menu_text(u), menu_kb(usr.id, u))


# ══════════════════════════ لوحة التحكم ══════════════════════════
TZ_CHOICES = [("Asia/Riyadh", "الرياض"), ("Asia/Damascus", "دمشق"), ("Asia/Amman", "عمّان"),
              ("Asia/Beirut", "بيروت"), ("Asia/Baghdad", "بغداد"), ("Asia/Dubai", "دبي"),
              ("Asia/Kuwait", "الكويت"), ("Africa/Cairo", "القاهرة"), ("Africa/Khartoum", "الخرطوم"),
              ("Africa/Tunis", "تونس"), ("Africa/Algiers", "الجزائر"), ("Africa/Casablanca", "الدار البيضاء"),
              ("Europe/Istanbul", "إسطنبول")]
QUICK = {"morning": ["04:30", "05:00", "05:30", "06:00", "06:30", "07:00", "07:30", "08:00", "09:00"],
         "evening": ["15:00", "16:00", "16:30", "17:00", "17:30", "18:00", "19:00", "20:00", "21:00"]}


def panel_text():
    s, now = state.settings, now_local()
    chans = "\n".join(f"• {esc(ch_label(c))}" for c in state.channels) or "لا توجد قنوات بعد — اضغط «إضافة قناة»"
    return ("<b>لوحة أذكار الصباح والمساء</b>\n" + SEP + "\n"
            f"القنوات:\n{chans}\n\n"
            f"المستخدمون المسجَّلون: <b>{len(state.users)}</b>\n"
            f"المنطقة الزمنية: <b>{esc(s['tz'])}</b> (الساعة الآن {now:%H:%M})\n"
            f"الصباح: <b>{s['morning']}</b> — {'يعمل' if s['morning_on'] else 'متوقف'}\n"
            f"المساء: <b>{s['evening']}</b> — {'يعمل' if s['evening_on'] else 'متوقف'}\n"
            f"التذكير الخاص (لمن فعّله): {'يعمل' if s['reminders'] else 'متوقف'}\n"
            f"حذف منشور الأمس عند نشر الجديد: {'نعم' if s['delete_old'] else 'لا'}\n"
            f"الحالة العامة: <b>{'تعمل' if s['enabled'] else 'متوقفة'}</b>\n"
            f"الموعد القادم: {next_run_text()}")


def panel_kb():
    s = state.settings
    return InlineKeyboardMarkup([
        [IBtn("إضافة قناة", callback_data="ad:chadd", style="primary"),
         IBtn("قنواتي", callback_data="ad:chlist", style="primary")],
        [IBtn("وقت الصباح", callback_data="ad:time:morning", style="primary"),
         IBtn("وقت المساء", callback_data="ad:time:evening", style="primary")],
        [IBtn("المنطقة الزمنية", callback_data="ad:tz", style="primary")],
        [IBtn("الصباح: " + ("يعمل" if s["morning_on"] else "متوقف"), callback_data="ad:on:morning",
              style="success" if s["morning_on"] else "danger"),
         IBtn("المساء: " + ("يعمل" if s["evening_on"] else "متوقف"), callback_data="ad:on:evening",
              style="success" if s["evening_on"] else "danger")],
        [IBtn("جرّب الصباح (لي فقط)", callback_data="ad:prev:morning"),
         IBtn("جرّب المساء (لي فقط)", callback_data="ad:prev:evening")],
        [IBtn("انشر الصباح الآن", callback_data="ad:pub:morning", style="success"),
         IBtn("انشر المساء الآن", callback_data="ad:pub:evening", style="success")],
        [IBtn("حالة اليوم", callback_data="ad:status"), IBtn("فحص الصلاحيات", callback_data="ad:check")],
        [IBtn("التذكير الخاص: " + ("يعمل" if s["reminders"] else "متوقف"), callback_data="ad:rem"),
         IBtn("حذف منشور الأمس: " + ("نعم" if s["delete_old"] else "لا"), callback_data="ad:delold")],
        [IBtn("إيقاف كل شيء" if s["enabled"] else "تشغيل البوت", callback_data="ad:enabled",
              style="danger" if s["enabled"] else "success")],
        [IBtn("قائمة الأذكار (كمستخدم)", callback_data="m:menu")],
    ])


def back_kb():
    return InlineKeyboardMarkup([[IBtn("رجوع", callback_data="ad:menu")]])


def status_text():
    today = today_str()
    lines = ["<b>حالة اليوم</b>", SEP,
             f"المسجَّلون: {len(state.users)} (مفعّلو التذكير: {sum(1 for u in state.users.values() if u.get('remind'))})"]
    for kind in KINDS:
        ss = [s for s in state.sessions.values() if s["kind"] == kind and s["date"] == today]
        lines.append(f"{TITLES[kind]}: بدأها <b>{len(ss)}</b> • أتمّها <b>{sum(1 for s in ss if s['done'] and not s['closed'])}</b>"
                     f" • تكرارات <b>{sum(s['taps'] for s in ss)}</b>")
    for c in state.channels:
        flags = " | ".join(f"{TITLES[k]}: {'نُشر' if state.sent.get(str(c['id']), {}).get(k) == today else 'لم يُنشر'}" for k in KINDS)
        lines.append(f"\n<b>{esc(ch_label(c))}</b>\n{flags}")
    return "\n".join(lines)


async def on_admin_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    if not is_admin(uid):
        await _answer(q, "هذا الأمر لمدير البوت فقط"); return
    await _answer(q)
    parts = q.data.split(":")
    act = parts[1]
    st = state.settings
    chat_id = q.message.chat_id

    if act == "menu":
        ctx.user_data.pop("mode", None)
        await safe_edit(q, panel_text(), panel_kb())
    elif act == "chadd":
        ctx.user_data["mode"] = "add_channel"
        await safe_edit(q, "<b>إضافة قناة</b>\n1) أضف البوت مشرفاً في القناة بصلاحية «نشر الرسائل».\n"
                           "2) أرسل لي هنا معرّف القناة مثل <code>@mychannel</code> أو رقمها، "
                           "أو <b>حوّل لي أي رسالة</b> من القناة (الأنسب للقنوات الخاصة).", back_kb())
    elif act == "chlist":
        rows = [[IBtn("حذف: " + short(ch_label(c)), callback_data=f"ad:chdel:{c['id']}", style="danger")]
                for c in state.channels]
        rows.append([IBtn("رجوع", callback_data="ad:menu")])
        await safe_edit(q, "<b>قنواتي</b>\n" + ("\n".join(f"• {esc(ch_label(c))}" for c in state.channels)
                                                 or "لا توجد قنوات."), InlineKeyboardMarkup(rows))
    elif act == "chdel":
        cid = int(parts[2])
        state.channels = [c for c in state.channels if c["id"] != cid]
        state.sent.pop(str(cid), None)
        for k in KINDS:
            state.posts.pop(f"{cid}:{k}", None)
        state.dirty = True
        await safe_edit(q, "تم حذف القناة من القائمة.\n\n" + panel_text(), panel_kb())
    elif act == "time":
        kind = parts[2]
        rows = [[IBtn(t, callback_data=f"ad:t:{kind}:{t.replace(':', '')}", style="primary") for t in QUICK[kind][i:i + 3]]
                for i in range(0, 9, 3)]
        rows.append([IBtn("وقت آخر (اكتبه)", callback_data=f"ad:tc:{kind}")])
        rows.append([IBtn("رجوع", callback_data="ad:menu")])
        await safe_edit(q, f"<b>وقت {TITLES[kind]}</b>\nالحالي: <b>{st[kind]}</b>\nاختر وقتاً (نظام 24 ساعة):",
                        InlineKeyboardMarkup(rows))
    elif act == "t":
        kind, hhmm = parts[2], parts[3]
        st[kind] = f"{hhmm[:2]}:{hhmm[2:]}"
        state.dirty = True
        await safe_edit(q, f"تم ضبط وقت {TITLES[kind]} على {st[kind]}.\n\n" + panel_text(), panel_kb())
    elif act == "tc":
        ctx.user_data["mode"] = ("time", parts[2])
        await safe_edit(q, "اكتب الوقت مثل <code>05:30</code> أو <code>5:30 ص</code> أو <code>17:45</code>", back_kb())
    elif act == "tz":
        btns = [IBtn(lbl, callback_data=f"ad:z:{i}", style="primary") for i, (_, lbl) in enumerate(TZ_CHOICES)]
        rows = [btns[j:j + 3] for j in range(0, len(btns), 3)]
        rows.append([IBtn("منطقة أخرى (اكتبها)", callback_data="ad:zc")])
        rows.append([IBtn("رجوع", callback_data="ad:menu")])
        await safe_edit(q, f"<b>المنطقة الزمنية</b>\nالحالية: <b>{esc(st['tz'])}</b> (الآن {now_local():%H:%M})\n"
                           "اختر مدينتك:", InlineKeyboardMarkup(rows))
    elif act == "z":
        st["tz"] = TZ_CHOICES[int(parts[2])][0]
        state.dirty = True
        await safe_edit(q, f"تم ضبط المنطقة الزمنية على {st['tz']}.\n\n" + panel_text(), panel_kb())
    elif act == "zc":
        ctx.user_data["mode"] = "tz"
        await safe_edit(q, "اكتب اسم المنطقة الزمنية بصيغة IANA مثل <code>Asia/Hebron</code> أو <code>Europe/London</code>",
                        back_kb())
    elif act in ("on", "delold", "enabled", "rem"):
        key = {"on": f"{parts[2]}_on" if act == "on" else "", "delold": "delete_old",
               "enabled": "enabled", "rem": "reminders"}[act]
        st[key] = not st[key]
        state.dirty = True
        await safe_edit(q, panel_text(), panel_kb())
    elif act == "prev":                              # تجربة حقيقية في محادثة الأدمن فقط
        await begin(ctx.bot, uid, parts[2], force=True)
    elif act == "pub":
        kind = parts[2]
        if not state.channels:
            await safe_edit(q, "أضف قناة أولاً.\n\n" + panel_text(), panel_kb()); return
        await safe_edit(q, f"سيُنشر منشور <b>{TITLES[kind]}</b> الآن في {len(state.channels)} قناة. متأكد؟",
                        InlineKeyboardMarkup([[IBtn("نعم، انشر", callback_data=f"ad:pubok:{kind}", style="success")],
                                              [IBtn("إلغاء", callback_data="ad:menu")]]))
    elif act == "pubok":
        kind, ok, bad = parts[2], 0, []
        today = today_str()
        for c in list(state.channels):
            try:
                await post_announcement(ctx.bot, c["id"], kind)
                state.sent.setdefault(str(c["id"]), {})[kind] = today
                ok += 1
            except TelegramError as e:
                bad.append(f"{esc(ch_label(c))}: {esc(str(e))}")
        state.dirty = True
        await safe_edit(q, f"تم النشر في {ok} قناة." + ("\nفشل:\n" + "\n".join(bad) if bad else "") +
                        "\n\n" + panel_text(), panel_kb())
    elif act == "status":
        await safe_edit(q, status_text(), back_kb())
    elif act == "check":
        lines = ["<b>فحص الصلاحيات</b>", SEP]
        for c in state.channels:
            info, err = await verify_channel(ctx.bot, c["id"])
            lines.append(f"• {esc(ch_label(c))}: " + ("سليمة" if info else esc(err)))
        if not state.channels:
            lines.append("لا توجد قنوات.")
        await safe_edit(q, "\n".join(lines), back_kb())


# ══════════════════════════ رسائل الأدمن ══════════════════════════
async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    ctx.user_data.pop("mode", None)
    await update.message.reply_text(panel_text(), parse_mode=ParseMode.HTML, reply_markup=panel_kb())


async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg, usr = update.message, update.effective_user
    mode = ctx.user_data.get("mode") if is_admin(usr.id) else None
    text = (msg.text or "").strip()

    if mode == "add_channel":
        fc = forwarded_chat(msg)
        ref = fc.id if fc is not None else parse_channel_ref(text)
        if ref is None:
            await msg.reply_text("لم أفهم المعرّف. أرسل مثل @mychannel أو رقم القناة، أو حوّل رسالة منها."); return
        info, err = await verify_channel(ctx.bot, ref)
        if err:
            await msg.reply_text(err); return
        new = add_channel(info)
        ctx.user_data.pop("mode", None)
        await msg.reply_text(f"{'تمت إضافة' if new else 'تم تحديث'} «{esc(ch_label(info))}» بنجاح.\n\n" + panel_text(),
                             parse_mode=ParseMode.HTML, reply_markup=panel_kb())
    elif isinstance(mode, tuple) and mode[0] == "time":
        t = parse_hhmm(text)
        if not t:
            await msg.reply_text("صيغة غير صحيحة. اكتب مثل 05:30 أو 5:30 ص أو 17:45."); return
        state.settings[mode[1]] = t
        state.dirty = True
        ctx.user_data.pop("mode", None)
        await msg.reply_text(f"تم ضبط وقت {TITLES[mode[1]]} على {t}.\n\n" + panel_text(),
                             parse_mode=ParseMode.HTML, reply_markup=panel_kb())
    elif mode == "tz":
        if get_tz(text) is None:
            await msg.reply_text("منطقة زمنية غير معروفة. مثال صحيح: Asia/Hebron أو Europe/London"); return
        state.settings["tz"] = text
        state.dirty = True
        ctx.user_data.pop("mode", None)
        await msg.reply_text(f"تم ضبط المنطقة الزمنية على {esc(text)}.\n\n" + panel_text(),
                             parse_mode=ParseMode.HTML, reply_markup=panel_kb())
    else:                                            # أي رسالة أخرى: القائمة (أو الترحيب لمن لم يُسجَّل بعد)
        await on_start(update, ctx)


async def on_error(update, ctx: ContextTypes.DEFAULT_TYPE):
    log.error("خطأ غير متوقع", exc_info=ctx.error)


# ══════════════════════════ التشغيل ══════════════════════════
async def post_init(app: Application):
    IBtn("x", style="primary", callback_data="x")      # فحص دعم الألوان
    log.info("الأزرار الملونة: %s", "مدعومة" if _STYLE_SUPPORTED else "غير مدعومة — نفّذ: pip install -U python-telegram-bot")
    if get_tz(state.settings["tz"]) is None:
        log.warning("المنطقة الزمنية %s غير متاحة (ثبّت tzdata) — سيُستخدم UTC+3", state.settings["tz"])
    for ref in ENV_CHANNELS:
        r = parse_channel_ref(ref)
        if r is not None:
            info, err = await verify_channel(app.bot, r)
            if info:
                add_channel(info)
            else:
                log.warning("القناة %s من الإعدادات: %s", ref, err)
    try:
        await app.bot.set_my_commands([BotCommand("start", "القائمة الرئيسية")])
        for aid in ADMIN_IDS:
            await app.bot.set_my_commands([BotCommand("start", "القائمة الرئيسية"), BotCommand("admin", "لوحة التحكم")],
                                          scope=BotCommandScopeChat(aid))
    except TelegramError as e:
        log.warning("set_my_commands: %s", e)
    app.bot_data["tasks"] = [asyncio.create_task(f(app)) for f in (loop_edit, loop_schedule, loop_flush)]


async def post_shutdown(app: Application):
    for t in app.bot_data.get("tasks", []):
        t.cancel()
    state.flush(force=True)


def start_keepalive():
    """خادم ويب صغير للاستضافات التي تتطلب منفذاً (يعمل فقط إن وُجد متغير PORT)."""
    port = os.getenv("PORT")
    if not port:
        return

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"OK")
        do_HEAD = do_GET

        def log_message(self, *a):
            pass

    srv = HTTPServer(("0.0.0.0", int(port)), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()


def main():
    global state
    if not BOT_TOKEN:
        sys.exit("ضع توكن البوت في BOT_TOKEN (متغير بيئة أو داخل الملف).")
    if not ADMIN_IDS:
        sys.exit("حدّد أيدي حسابك في ADMIN_IDS (متغير بيئة أو داخل الملف).")
    state = State(DATA_DIR)
    app = (Application.builder().token(BOT_TOKEN).concurrent_updates(True)
           .post_init(post_init).post_shutdown(post_shutdown).build())
    app.add_handler(CallbackQueryHandler(on_join, pattern=r"^j:"))
    app.add_handler(CallbackQueryHandler(on_tap, pattern=r"^[ck]:"))
    app.add_handler(CallbackQueryHandler(on_user_cb, pattern=r"^[mr]:"))
    app.add_handler(CallbackQueryHandler(on_admin_cb, pattern=r"^ad:"))
    app.add_handler(CommandHandler("start", on_start, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("admin", cmd_admin, filters=filters.ChatType.PRIVATE))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, on_message))
    app.add_error_handler(on_error)
    start_keepalive()
    log.info("البوت يعمل…")
    app.run_polling(allowed_updates=["message", "callback_query"], drop_pending_updates=True)


if __name__ == "__main__":
    main()
