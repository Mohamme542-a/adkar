# -*- coding: utf-8 -*-
"""
بوت أذكار الصباح والمساء للقنوات (تيليجرام) — متعدد القنوات
═══════════════════════════════════════════════════════════
• أي مستخدم يستطيع إضافة البوت إلى قناته (بشرط أن يكون مشرفاً فيها) والتحكم بها وحدها:
  الأوقات، المنطقة الزمنية، التشغيل والإيقاف، النشر الفوري، نص إضافي، إحصائيات القناة...
• في وقت الصباح والمساء ينشر البوت في كل قناة منشوراً فيه زر «ابدأ الأذكار» يفتح للمستخدم
  محادثة البوت (ويسجّله تلقائياً أول مرة)، وهناك عدّاد خاص به: كل ضغطة تُنقص العدد وعند 0
  ينتقل للذكر التالي حتى تنتهي الأذكار.
• تذكير تلقائي لكل مستخدم مسجَّل (مفعّل افتراضياً ويستطيع إيقافه أو تعديل وقته ومنطقته).
• المدير (ADMIN_IDS) يرى كل القنوات والمستخدمين وإحصاءاتهم، ويرسل رسالة للجميع، ويصدّر CSV.

التثبيت :  pip install -U -r requirements.txt
التشغيل :  BOT_TOKEN=xxxx ADMIN_IDS=123456789 python adhkar_bot.py
"""
import asyncio
import csv
import html
import io
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

BOT_TOKEN = os.getenv("BOT_TOKEN", "8439911839:AAFm25EljzBNvuGjU_eIaAdUDuGOhUd2bic")            # أو: BOT_TOKEN = "123456:ABC..."
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
NOTE_MAX = 200         # أقصى طول للنص الإضافي في منشور القناة
BROADCAST_GAP = 0.05   # فاصل بين رسائل «الرسالة للجميع»
MAX_CHANNELS_PER_USER = int(os.getenv("MAX_CHANNELS_PER_USER", "5"))   # الحد الأقصى لقنوات كل مستخدم (المدير بلا حد)
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

TAHLEEL_100 = {
    "text": "لَا إِلَٰهَ إِلَّا اللَّهُ وَحْدَهُ لَا شَرِيكَ لَهُ، لَهُ الْمُلْكُ وَلَهُ الْحَمْدُ وَهُوَ عَلَى كُلِّ شَيْءٍ قَدِيرٌ",
    "count": 100,
    "virtue": "من قالها في يومٍ مائة مرة كانت له عدل عشر رقاب، وكُتبت له مائة حسنة، ومُحيت عنه مائة سيئة، "
              "وكانت له حرزاً من الشيطان يومه ذلك حتى يُمسي، ولم يأتِ أحدٌ بأفضل مما جاء به إلا رجلٌ عمل أكثر من ذلك.",
    "src": "متفق عليه",
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
    TAHLEEL_100,
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
    TAHLEEL_100,
    ISTIGHFAR_100, SALAWAT,
]

ALL_SURAHS = {
    "text": IKHLAS["text"] + "\n\n" + FALAQ["text"] + "\n\n" + NAS["text"],
    "count": 1,
    "virtue": "كان النبي صلى الله عليه وسلم يأمر بقراءة المعوّذات دبر كل صلاة.",
    "src": "رواه أبو داود والترمذي والنسائي",
}
TASBIH_TEXT = "سُبْحَانَ اللَّهِ"
TAHMID_TEXT = "الْحَمْدُ لِلَّهِ"
TAKBIR_TEXT = "اللَّهُ أَكْبَرُ"

PRAYER = [
    {"text": "أَسْتَغْفِرُ اللَّهَ", "count": 3, "virtue": "", "src": "رواه مسلم"},
    {"text": "اللَّهُمَّ أَنْتَ السَّلَامُ وَمِنْكَ السَّلَامُ، تَبَارَكْتَ يَا ذَا الْجَلَالِ وَالْإِكْرَامِ",
     "count": 1, "virtue": "", "src": "رواه مسلم"},
    {"text": "لَا إِلَٰهَ إِلَّا اللَّهُ وَحْدَهُ لَا شَرِيكَ لَهُ، لَهُ الْمُلْكُ وَلَهُ الْحَمْدُ وَهُوَ عَلَى كُلِّ شَيْءٍ قَدِيرٌ، "
             "اللَّهُمَّ لَا مَانِعَ لِمَا أَعْطَيْتَ، وَلَا مُعْطِيَ لِمَا مَنَعْتَ، وَلَا يَنْفَعُ ذَا الْجَدِّ مِنْكَ الْجَدُّ",
     "count": 1, "virtue": "", "src": "متفق عليه"},
    {"text": "لَا إِلَٰهَ إِلَّا اللَّهُ وَحْدَهُ لَا شَرِيكَ لَهُ، لَهُ الْمُلْكُ وَلَهُ الْحَمْدُ وَهُوَ عَلَى كُلِّ شَيْءٍ قَدِيرٌ، "
             "لَا حَوْلَ وَلَا قُوَّةَ إِلَّا بِاللَّهِ، لَا إِلَٰهَ إِلَّا اللَّهُ، وَلَا نَعْبُدُ إِلَّا إِيَّاهُ، لَهُ النِّعْمَةُ "
             "وَلَهُ الْفَضْلُ وَلَهُ الثَّنَاءُ الْحَسَنُ، لَا إِلَٰهَ إِلَّا اللَّهُ مُخْلِصِينَ لَهُ الدِّينَ وَلَوْ كَرِهَ الْكَافِرُونَ",
     "count": 1, "virtue": "", "src": "رواه مسلم"},
    {"text": TASBIH_TEXT, "count": 33,
     "virtue": "من سبّح الله دبر كل صلاة ثلاثاً وثلاثين، وحمد الله ثلاثاً وثلاثين، وكبّر الله ثلاثاً وثلاثين، "
               "وقال تمام المائة: «لا إله إلا الله وحده لا شريك له، له الملك وله الحمد وهو على كل شيء قدير» "
               "غُفرت خطاياه وإن كانت مثل زبد البحر.",
     "src": "رواه مسلم"},
    {"text": TAHMID_TEXT, "count": 33, "virtue": "", "src": "رواه مسلم"},
    {"text": TAKBIR_TEXT, "count": 33, "virtue": "", "src": "رواه مسلم"},
    {"text": "لَا إِلَٰهَ إِلَّا اللَّهُ وَحْدَهُ لَا شَرِيكَ لَهُ، لَهُ الْمُلْكُ وَلَهُ الْحَمْدُ وَهُوَ عَلَى كُلِّ شَيْءٍ قَدِيرٌ",
     "count": 1, "virtue": "تمام المائة.", "src": "رواه مسلم"},
    dict(KURSI, virtue="من قرأها دبر كل صلاة مكتوبة لم يمنعه من دخول الجنة إلا أن يموت.", src="رواه النسائي"),
    ALL_SURAHS,
]

BAQARAH_END = {
    "text": EVENING[[i for i, x in enumerate(EVENING) if x["text"].startswith("﴿آمَنَ الرَّسُولُ")][0]]["text"],
    "count": 1, "virtue": "من قرأ بالآيتين من آخر سورة البقرة في ليلة كفتاه.", "src": "متفق عليه",
}

SLEEP = [
    {"text": IKHLAS["text"] + "\n\n" + FALAQ["text"] + "\n\n" + NAS["text"], "count": 3,
     "virtue": "كان النبي صلى الله عليه وسلم إذا أوى إلى فراشه جمع كفّيه ثم نفث فيهما فقرأ المعوّذات، ثم مسح بهما "
               "ما استطاع من جسده، يبدأ بهما على رأسه ووجهه وما أقبل من جسده، يفعل ذلك ثلاث مرات.",
     "src": "رواه البخاري"},
    dict(KURSI, virtue="من قرأها إذا أوى إلى فراشه لم يزل عليه من الله حافظ، ولا يقربه شيطان حتى يُصبح.", src="رواه البخاري"),
    BAQARAH_END,
    {"text": "بِاسْمِكَ رَبِّي وَضَعْتُ جَنْبِي، وَبِكَ أَرْفَعُهُ، فَإِنْ أَمْسَكْتَ نَفْسِي فَارْحَمْهَا، "
             "وَإِنْ أَرْسَلْتَهَا فَاحْفَظْهَا بِمَا تَحْفَظُ بِهِ عِبَادَكَ الصَّالِحِينَ",
     "count": 1, "virtue": "", "src": "متفق عليه"},
    {"text": "اللَّهُمَّ إِنَّكَ خَلَقْتَ نَفْسِي وَأَنْتَ تَوَفَّاهَا، لَكَ مَمَاتُهَا وَمَحْيَاهَا، إِنْ أَحْيَيْتَهَا "
             "فَاحْفَظْهَا، وَإِنْ أَمَتَّهَا فَاغْفِرْ لَهَا، اللَّهُمَّ إِنِّي أَسْأَلُكَ الْعَافِيَةَ",
     "count": 1, "virtue": "", "src": "رواه مسلم"},
    {"text": "اللَّهُمَّ قِنِي عَذَابَكَ يَوْمَ تَبْعَثُ عِبَادَكَ", "count": 3, "virtue": "", "src": "رواه أبو داود والترمذي"},
    {"text": "بِاسْمِكَ اللَّهُمَّ أَمُوتُ وَأَحْيَا", "count": 1, "virtue": "", "src": "رواه البخاري"},
    {"text": TASBIH_TEXT, "count": 33,
     "virtue": "قال النبي صلى الله عليه وسلم لعلي وفاطمة رضي الله عنهما: إذا أخذتما مضاجعكما فسبّحا ثلاثاً وثلاثين، "
               "واحمدا ثلاثاً وثلاثين، وكبّرا أربعاً وثلاثين، فهو خير لكما من خادم.",
     "src": "متفق عليه"},
    {"text": TAHMID_TEXT, "count": 33, "virtue": "", "src": "متفق عليه"},
    {"text": TAKBIR_TEXT, "count": 34, "virtue": "", "src": "متفق عليه"},
]

ADHKAR = {"morning": MORNING, "evening": EVENING, "sleep": SLEEP, "prayer": PRAYER}
TITLES = {"morning": "أذكار الصباح", "evening": "أذكار المساء", "sleep": "أذكار النوم", "prayer": "أذكار بعد الصلاة"}
KINDS = ("morning", "evening")            # مجدولة يومياً (قنوات + تذكير) وتُحتسب فيها سلسلة الأيام
EXTRA = ("sleep", "prayer")               # عند الطلب فقط من قائمة البوت
ALL_KINDS = KINDS + EXTRA


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
    """الإعدادات الافتراضية العامة (تُطبَّق على القنوات والمستخدمين الجدد فقط)."""
    return {"tz": DEFAULT_TZ, "morning": DEFAULT_MORNING, "evening": DEFAULT_EVENING, "reminders": True}


@lru_cache(maxsize=64)
def get_tz(name):
    try:
        return ZoneInfo(name)
    except Exception:
        return None


def now_in(tzname):
    tz = get_tz(tzname) or timezone(timedelta(hours=3))
    return datetime.now(tz)


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


def hhmm_passed(now, hhmm):
    hh, mm = map(int, hhmm.split(":"))
    return now >= now.replace(hour=hh, minute=mm, second=0, microsecond=0)


def in_window(now, hhmm):
    hh, mm = map(int, hhmm.split(":"))
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return target <= now < target + timedelta(minutes=GRACE_MIN)


def fmt_ts(ts):
    try:
        return datetime.fromtimestamp(int(ts), get_tz(state.settings["tz"]) or timezone.utc).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return "—"


# ---- المستخدمون ----
def new_user(name="", username=""):
    t = int(time.time())
    return {"name": str(name)[:64], "username": str(username or "")[:64], "started": True, "welcomed": False,
            "joined": t, "last": t, "via": 0,
            "rem": {k: True for k in KINDS},                      # التذكير مفعّل افتراضياً لكل الناس
            "tz": "", "rt": {k: "" for k in KINDS}, "last_rem": {k: "" for k in KINDS},
            "streak": {k: 0 for k in KINDS}, "last_done": {k: "" for k in KINDS}, "days": {k: 0 for k in KINDS},
            "cnt": {k: 0 for k in ALL_KINDS}, "items": 0, "taps": 0}


def clean_user(d):
    u = new_user(d.get("name", ""), d.get("username", ""))
    for k in ("started", "welcomed"):
        if isinstance(d.get(k), bool):
            u[k] = d[k]
    for k in ("joined", "last", "via", "items", "taps"):
        try:
            u[k] = max(0, int(d.get(k, u[k])))
        except (TypeError, ValueError):
            pass
    if isinstance(d.get("tz"), str) and (not d["tz"] or get_tz(d["tz"])):
        u["tz"] = d["tz"]
    for fld, kinds, cast in (("rem", KINDS, bool), ("rt", KINDS, str), ("last_rem", KINDS, str),
                             ("streak", KINDS, int), ("last_done", KINDS, str), ("days", KINDS, int),
                             ("cnt", ALL_KINDS, int)):
        src = d.get(fld) if isinstance(d.get(fld), dict) else {}
        for kd in kinds:
            if kd not in src:
                continue
            try:
                v = cast(src[kd])
                if cast is int:
                    v = max(0, v)
                if fld == "rt" and v and parse_hhmm(v) != v:
                    continue
                u[fld][kd] = v
            except (TypeError, ValueError):
                pass
    return u


# ---- القنوات (كل قناة لها مالك وإعداداتها الخاصة) ----
def new_channel(cid, info, owner):
    s = state.settings
    return {"cid": cid, "id": info["id"], "title": str(info.get("title", "")), "username": str(info.get("username", "")),
            "owner": owner, "added": int(time.time()), "tz": s["tz"], "morning": s["morning"], "evening": s["evening"],
            "morning_on": True, "evening_on": True, "enabled": True, "delete_old": False, "note": "",
            "sent": {}, "posts": {}, "fails": 0, "stats": {"starts": 0, "done": 0, "taps": 0, "users": 0}}


def clean_channel(c, cid, legacy=None, data=None):
    """يقرأ قناة من الملف. إن كانت بصيغة النسخة القديمة (بلا cid) تُرحَّل بإعداداتها العامة القديمة."""
    legacy = legacy or {}
    ch = new_channel(cid, {"id": int(c["id"]), "title": c.get("title", ""), "username": c.get("username", "")},
                     int(c.get("owner", ADMIN_IDS[0] if ADMIN_IDS else 0)))
    src = c if "cid" in c else legacy
    for k in ("tz", "morning", "evening"):
        if isinstance(src.get(k), str) and (k != "tz" and parse_hhmm(src[k]) == src[k] or k == "tz" and get_tz(src[k])):
            ch[k] = src[k]
    for k in ("morning_on", "evening_on", "enabled", "delete_old"):
        if isinstance(src.get(k), bool):
            ch[k] = src[k]
    if isinstance(c.get("note"), str):
        ch["note"] = c["note"][:NOTE_MAX]
    for k in ("added", "fails"):
        try:
            ch[k] = max(0, int(c.get(k, ch[k])))
        except (TypeError, ValueError):
            pass
    if "cid" in c:
        if isinstance(c.get("sent"), dict):
            ch["sent"] = {k: str(v) for k, v in c["sent"].items() if k in KINDS}
        if isinstance(c.get("posts"), dict):
            ch["posts"] = {k: v for k, v in c["posts"].items() if k in KINDS and isinstance(v, dict) and "mid" in v}
        if isinstance(c.get("stats"), dict):
            for k in ch["stats"]:
                try:
                    ch["stats"][k] = max(0, int(c["stats"].get(k, 0)))
                except (TypeError, ValueError):
                    pass
    elif data:                                              # ترحيل من النسخة القديمة
        ch["sent"] = dict((data.get("sent") or {}).get(str(ch["id"]), {}))
        for k in KINDS:
            p = (data.get("posts") or {}).get(f"{ch['id']}:{k}")
            if isinstance(p, dict) and "mid" in p:
                ch["posts"][k] = p
    return ch


def clean_session(sid, s):
    if s["kind"] not in ALL_KINDS:
        raise ValueError("kind")
    uid = int(s["uid"])
    return {"sid": str(sid), "uid": uid, "chat": uid, "kind": s["kind"],
            "mid": int(s["mid"]) if s.get("mid") else None, "idx": int(s["idx"]), "left": int(s["left"]),
            "done": bool(s.get("done")), "closed": bool(s.get("closed")), "taps": int(s.get("taps", 0)),
            "ts": float(s.get("ts", time.time())), "date": str(s.get("date", "")),
            "streak": int(s.get("streak", 0)), "src": int(s["src"]) if s.get("src") else None,
            "edit": s.get("edit") if s.get("edit") in ("markup", "full") else None}


class State:
    def __init__(self, folder):
        os.makedirs(folder, exist_ok=True)
        self.dir = folder
        self.path = os.path.join(folder, "adhkar_state.json")      # الإعدادات العامة والقنوات
        self.upath = os.path.join(folder, "adhkar_users.json")     # المستخدمون وجلساتهم
        self.channels, self.next_cid = [], 1
        self.settings = default_settings()
        self.users, self.sessions, self._idx = {}, {}, {}
        self.dirty = self.udirty = False
        self._last_u = 0.0

        data = self._load(self.path)
        if isinstance(data, dict):
            st = data.get("settings") if isinstance(data.get("settings"), dict) else {}
            for k, dv in self.settings.items():
                if k in st and type(st[k]) is type(dv) and (k != "tz" or get_tz(st[k])):
                    self.settings[k] = st[k]
            try:
                self.next_cid = max(1, int(data.get("next_cid", 1)))
            except (TypeError, ValueError):
                pass
            for c in data.get("channels", []):
                try:
                    if not isinstance(c, dict) or not isinstance(c.get("id"), int):
                        continue
                    cid = int(c["cid"]) if "cid" in c else self.next_cid
                    ch = clean_channel(c, cid, legacy=st, data=data)
                    self.channels.append(ch)
                    self.next_cid = max(self.next_cid, cid + 1)
                except (KeyError, TypeError, ValueError):
                    continue
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

    # ---- القنوات ----
    def channel(self, cid):
        return next((c for c in self.channels if c["cid"] == cid), None)

    def channel_by_chat(self, chat_id):
        return next((c for c in self.channels if c["id"] == chat_id), None)

    def channels_of(self, uid):
        return [c for c in self.channels if c["owner"] == uid]

    def add_channel(self, info, owner):
        ch = new_channel(self.next_cid, info, owner)
        self.next_cid += 1
        self.channels.append(ch)
        self.dirty = True
        return ch

    def remove_channel(self, cid):
        self.channels = [c for c in self.channels if c["cid"] != cid]
        self.dirty = True

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
    def register(self, uid, name, username=""):
        k = str(uid)
        u = self.users.get(k)
        new = u is None
        if new:
            u = self.users[k] = new_user(name or "", username or "")
            sync_rem(u)                                    # لا تذكير فوري لأوقات مضت اليوم
        else:
            if name:
                u["name"] = name[:64]
            u["username"] = (username or "")[:64]
            u["started"] = True
        u["last"] = int(time.time())
        self.udirty = True
        return u, new

    # ---- الحفظ ----
    def flush(self, force=False):
        if self.dirty:
            self.dirty = False
            data = {"channels": self.channels, "settings": self.settings, "next_cid": self.next_cid}
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


def user_tz(u):
    return (u.get("tz") if u else "") or state.settings["tz"]


def user_time(u, kind):
    return u["rt"].get(kind) or state.settings[kind]


def user_today(u):
    return now_in(user_tz(u)).date().isoformat()


def sync_rem(u):
    """بعد التسجيل أو تغيير الوقت/المنطقة: ما مضى وقته اليوم لا يُرسل له تذكير فوري، وما لم يأتِ بعد يُرسل في موعده."""
    now = now_in(user_tz(u))
    today = now.date().isoformat()
    for k in KINDS:
        u["last_rem"][k] = today if hhmm_passed(now, user_time(u, k)) else ""
    state.udirty = True


def effective_streak(u, kind):
    """عدد الأيام المتتالية الحالي (يُصفَّر إن فاتك أمس واليوم)."""
    last = u["last_done"].get(kind, "")
    try:
        gap = (now_in(user_tz(u)).date() - date.fromisoformat(last)).days
    except ValueError:
        return 0
    return u["streak"].get(kind, 0) if 0 <= gap <= 1 else 0


def uname(u, uid=None):
    n = esc(u.get("name") or "مستخدم")
    return n + (f" (@{esc(u['username'])})" if u.get("username") else "")


def ch_label(c):
    return c.get("title") or (("@" + c["username"]) if c.get("username") else str(c["id"]))


def short(t, n=28):
    t = re.sub(r"\s+", " ", str(t)).strip()
    return t if len(t) <= n else t[: n - 1] + "…"


def owner_name(ch):
    u = state.users.get(str(ch["owner"]))
    return (u.get("name") if u else "") or str(ch["owner"])


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


async def start_user_session(bot, uid, kind, src=None):
    old = state.find(uid, kind)
    u = state.users.get(str(uid))
    s = {"sid": secrets.token_hex(4), "uid": uid, "chat": uid, "kind": kind, "mid": None, "idx": 0,
         "left": ADHKAR[kind][0]["count"], "done": False, "closed": False, "taps": 0, "ts": time.time(),
         "date": user_today(u), "streak": 0, "src": src, "edit": None}
    await send_session_message(bot, s)            # إن فشل الإرسال (مثلاً حظر البوت) تبقى الجلسة القديمة كما هي
    if old:
        if not old["done"]:
            await retire(bot, old["chat"], old["mid"])
        state.remove_session(old["sid"])
    state.add_session(s)
    ch = state.channel(src) if src else None
    if ch:
        ch["stats"]["starts"] += 1
        state.dirty = True
    return s


async def begin(bot, uid, kind, force=False, src=None):
    """يبدأ/يتابع أذكار المستخدم في محادثته الخاصة. يعيد: new / resumed / dup / done."""
    u = state.users.get(str(uid))
    old = state.find(uid, kind)
    if old and not old["closed"] and old["date"] == user_today(u) and not force:
        if old["done"]:
            if kind in KINDS:                       # الصباح/المساء: مرة يومياً، ويُسأل هل يعيدها
                await bot.send_message(
                    uid, f"أتممت {TITLES[kind]} اليوم بحمد الله.\nتقبّل الله منك. هل تريد إعادتها؟",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[IBtn("أعد الأذكار", callback_data=f"r:{kind}", style="primary")],
                                                       [IBtn("القائمة", callback_data="m:menu")]]))
                return "done"
        else:
            if time.time() - old.get("_msg_ts", 0) < 8:    # ضغطتان متتاليتان (زر القناة + رابط البداية)
                return "dup"
            old_mid = old["mid"]
            await send_session_message(bot, old)           # يعيد إرسال الذكر الحالي في أسفل المحادثة
            await retire(bot, uid, old_mid)
            return "resumed"
    await start_user_session(bot, uid, kind, src)
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
    ch = state.channel(s["src"]) if s.get("src") else None
    if ch:
        ch["stats"]["taps"] += 1
        state.dirty = True
    if s["left"] > 0:
        s["edit"] = s["edit"] or "markup"
        return "tap"
    if u:
        u["items"] += 1                                   # أتمّ ذكراً كاملاً
    return _advance(s)


def mark_completed(s):
    """يسجّل إتمام الجلسة. للصباح/المساء تُحدَّث سلسلة الأيام (إن ضغط ما لا يقل عن نصف التكرارات)."""
    s["streak"] = 0
    ch = state.channel(s["src"]) if s.get("src") else None
    if ch:
        ch["stats"]["done"] += 1
        state.dirty = True
    u = state.users.get(str(s["uid"]))
    if not u:
        return
    kind, d = s["kind"], s["date"]
    u["cnt"][kind] += 1
    if kind not in KINDS:
        return
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


async def _answer(q, text=None, url=None, alert=False):
    try:
        if url:
            await q.answer(url=url)
        elif alert:
            await q.answer(text, show_alert=True)
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
            u["started"] = False
            for k in KINDS:
                u["rem"][k] = False
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
BG = set()          # مهام الخلفية (الرسالة للجميع...) لحفظ مرجعها


def spawn(coro):
    t = asyncio.create_task(coro)
    BG.add(t)
    t.add_done_callback(BG.discard)
    return t


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


async def notify(bot, uid, text):
    try:
        await bot.send_message(uid, text, parse_mode=ParseMode.HTML)
        return True
    except TelegramError:
        return False


async def notify_admins(bot, text):
    for aid in ADMIN_IDS:
        await notify(bot, aid, text)


def announce_text(kind, note=""):
    t = (f"<b>{TITLES[kind]}</b>\n{SEP}\n"
         "﴿وَسَبِّحْ بِحَمْدِ رَبِّكَ بِالْعَشِيِّ وَالْإِبْكَارِ﴾\n\n"
         f"حان وقت {TITLES[kind]}.\n"
         "اضغط الزر ليفتح لك البوت مباشرة، والعدّاد خاص بك وحدك.\n"
         "<i>إن كانت أول مرة تفتح فيها البوت فاضغط START في أسفل المحادثة وسيُسجَّل حسابك فوراً.</i>")
    return t + (f"\n\n{esc(note)}" if note else "")


async def post_announcement(bot, ch, kind):
    """ينشر في القناة منشوراً بزر رابط مباشر للبوت (يفتح المحادثة لأي شخص، مسجَّلاً كان أو لا)."""
    url = f"https://t.me/{await bot_username(bot)}?start={kind}_c{ch['cid']}"
    kb = InlineKeyboardMarkup([[IBtn(f"ابدأ {TITLES[kind]}", url=url, style="primary")]])
    msg = await bot.send_message(ch["id"], announce_text(kind, ch.get("note", "")), parse_mode=ParseMode.HTML,
                                 reply_markup=kb)
    old = ch["posts"].get(kind)
    ch["posts"][kind] = {"mid": msg.message_id, "date": now_in(ch["tz"]).date().isoformat()}
    state.dirty = True
    if old and ch["delete_old"]:
        try:
            await bot.delete_message(ch["id"], old["mid"])
        except TelegramError as e:
            log.info("تعذّر حذف منشور الأمس: %s", e)
    return msg


async def on_join(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """للمنشورات القديمة التي نُشرت بزر رد (callback): يحوّل أي شخص إلى البوت. المنشورات الجديدة تستعمل زر رابط."""
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
        except Forbidden:
            u["started"] = False
            state.udirty = True
        except TelegramError as e:
            log.warning("تعذّر إرسال الأذكار إلى %s: %s", usr.id, e)
    await _answer(q, url=url)


async def send_due_reminders(bot):
    """تذكير خاص لكل مستخدم في وقته ومنطقته الزمنية (مفعّل افتراضياً)، ويتخطى من أتمّ أذكاره اليوم."""
    nows, sent = {}, 0
    for uid, u in list(state.users.items()):
        if not u.get("started"):
            continue
        tzn = user_tz(u)
        now = nows.get(tzn) or nows.setdefault(tzn, now_in(tzn))
        today = now.date().isoformat()
        for kind in KINDS:
            if not u["rem"].get(kind) or u["last_rem"].get(kind) == today or not in_window(now, user_time(u, kind)):
                continue
            u["last_rem"][kind] = today
            state.udirty = True
            s = state.find(int(uid), kind)
            if s and s["date"] == today and s["done"] and not s["closed"]:
                continue
            for attempt in range(2):
                try:
                    await bot.send_message(
                        int(uid), f"<b>{TITLES[kind]}</b>\nحان وقت {TITLES[kind]}، فلا تغفل عنها.\n"
                                  "<i>لإيقاف التذكير: القائمة ← التذكير.</i>",
                        parse_mode=ParseMode.HTML,
                        reply_markup=InlineKeyboardMarkup(
                            [[IBtn(f"ابدأ {TITLES[kind]}", callback_data=f"m:{kind}", style="primary")]]))
                    sent += 1
                    break
                except Forbidden:
                    u["started"] = False
                    for k in KINDS:
                        u["rem"][k] = False
                    break
                except RetryAfter as e:
                    await asyncio.sleep(float(e.retry_after) + 1)
                except TelegramError:
                    break
            await asyncio.sleep(REMIND_GAP)
            if not u["started"]:
                break
    return sent


# ══════════════════════════ الجدولة ══════════════════════════
async def schedule_tick(bot):
    """ينشر في كل قناة وفق إعداداتها الخاصة (وقتها ومنطقتها)، ثم يرسل التذكيرات الخاصة المستحقة."""
    for ch in list(state.channels):
        if not ch["enabled"]:
            continue
        now = now_in(ch["tz"])
        today = now.date().isoformat()
        for kind in KINDS:
            if not ch[f"{kind}_on"] or ch["sent"].get(kind) == today or not in_window(now, ch[kind]):
                continue
            ch["sent"][kind] = today                                  # يُسجَّل أولاً لمنع التكرار عند الفشل
            state.dirty = True
            try:
                await post_announcement(bot, ch, kind)
                ch["fails"] = 0
                log.info("نُشرت %s في %s", TITLES[kind], ch_label(ch))
            except TelegramError as e:
                ch["fails"] += 1
                log.error("فشل نشر %s في %s: %s", TITLES[kind], ch_label(ch), e)
                msg = (f"<b>تعذّر نشر {TITLES[kind]}</b> في «{esc(ch_label(ch))}»:\n{esc(str(e))}\n"
                       "تأكد أن البوت ما زال مشرفاً في القناة ولديه صلاحية «نشر الرسائل».")
                if ch["fails"] >= 3:
                    ch["enabled"] = False
                    msg += "\n\nتم إيقاف النشر في هذه القناة بعد 3 أيام من الفشل. أعد تشغيله من «قنواتي» بعد إصلاح الصلاحيات."
                if not ch["owner"] or not await notify(bot, ch["owner"], msg):
                    await notify_admins(bot, msg)
    if state.settings["reminders"]:
        n = await send_due_reminders(bot)
        if n:
            log.info("أُرسل %d تذكير خاص", n)


def next_run_text(ch):
    now = now_in(ch["tz"])
    best = None
    for kind in KINDS:
        if not ch[f"{kind}_on"]:
            continue
        hh, mm = map(int, ch[kind].split(":"))
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


# ══════════════════════════ التحقق من القنوات ══════════════════════════
async def verify_channel(bot, ref, user_id=None):
    """يتحقق أن القناة موجودة وأن البوت مشرف فيها ويستطيع النشر، وأن المستخدم نفسه مشرف فيها
    (المدير مستثنى). يعيد (معلومات, رسالة_خطأ)."""
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
    if user_id is not None and not is_admin(user_id):
        try:
            m = await bot.get_chat_member(chat.id, user_id)
        except TelegramError:
            return None, "تعذّر التحقق من أنك مشرف في هذه القناة."
        if m.status not in ("creator", "administrator"):
            return None, "يجب أن تكون مالك القناة أو مشرفاً فيها لتضيفها."
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


async def safe_edit(q, text, markup=None):
    try:
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            log.debug("edit failed: %s", e)


# ══════════════════════════ أدوات واجهة مشتركة ══════════════════════════
TZ_CHOICES = [("Asia/Riyadh", "الرياض"), ("Asia/Damascus", "دمشق"), ("Asia/Amman", "عمّان"),
              ("Asia/Beirut", "بيروت"), ("Asia/Baghdad", "بغداد"), ("Asia/Dubai", "دبي"),
              ("Asia/Kuwait", "الكويت"), ("Africa/Cairo", "القاهرة"), ("Africa/Khartoum", "الخرطوم"),
              ("Africa/Tunis", "تونس"), ("Africa/Algiers", "الجزائر"), ("Africa/Casablanca", "الدار البيضاء"),
              ("Europe/Istanbul", "إسطنبول")]
QUICK = {"morning": ["04:30", "05:00", "05:30", "06:00", "06:30", "07:00", "07:30", "08:00", "09:00"],
         "evening": ["15:00", "16:00", "16:30", "17:00", "17:30", "18:00", "19:00", "20:00", "21:00"]}
PAGE = 8


def time_picker_kb(kind, cb_set, cb_custom, cb_back):
    rows = [[IBtn(t, callback_data=cb_set(kind, t.replace(":", "")), style="primary") for t in QUICK[kind][i:i + 3]]
            for i in range(0, 9, 3)]
    if cb_custom:
        rows.append([IBtn("وقت آخر (اكتبه)", callback_data=cb_custom)])
    rows.append([IBtn("رجوع", callback_data=cb_back)])
    return InlineKeyboardMarkup(rows)


def tz_picker_kb(cb_set, cb_custom, cb_back):
    btns = [IBtn(lbl, callback_data=cb_set(i), style="primary") for i, (_, lbl) in enumerate(TZ_CHOICES)]
    rows = [btns[j:j + 3] for j in range(0, len(btns), 3)]
    if cb_custom:
        rows.append([IBtn("منطقة أخرى (اكتبها)", callback_data=cb_custom)])
    rows.append([IBtn("رجوع", callback_data=cb_back)])
    return InlineKeyboardMarkup(rows)


def paginate(seq, page):
    pages = max(1, (len(seq) + PAGE - 1) // PAGE)
    page = min(max(page, 0), pages - 1)
    return seq[page * PAGE:(page + 1) * PAGE], page, pages


def nav_row(prefix, page, pages):
    row = []
    if page > 0:
        row.append(IBtn("السابق", callback_data=f"{prefix}:{page - 1}"))
    if page < pages - 1:
        row.append(IBtn("التالي", callback_data=f"{prefix}:{page + 1}"))
    return row


# ══════════════════════════ واجهة المستخدم (الخاص) ══════════════════════════
_START_RE = re.compile(r"^(morning|evening|sleep|prayer)(?:_c(\d+))?$")


def parse_start_arg(arg):
    m = _START_RE.match((arg or "").lower())
    return (m.group(1), int(m.group(2)) if m.group(2) else None) if m else (None, None)


def welcome_text(u):
    rem = ""
    if state.settings["reminders"]:
        rem = (f"تم تفعيل <b>التذكير التلقائي</b>: الصباح {user_time(u, 'morning')} والمساء {user_time(u, 'evening')} "
               f"({esc(user_tz(u))}). تستطيع إيقافه أو تعديل وقته ومنطقتك الزمنية من زر «التذكير».\n\n")
    return (f"<b>تم تسجيلك بنجاح</b>\n{SEP}\n"
            f"أهلاً بك {esc(u['name'] or 'أخي الكريم')}.\n"
            "من الآن تستطيع قراءة الأذكار هنا، والعدّاد خاص بك وحدك.\n\n"
            f"{rem}اضغط على الأذكار التي تريد البدء بها:")


def welcome_kb(first=None, cid=None):
    order = sorted(KINDS, key=lambda k: 0 if k == first else 1)
    suffix = f":{cid}" if cid else ""
    rows = [[IBtn(f"ابدأ {TITLES[k]}", callback_data=f"m:{k}{suffix}", style="primary")] for k in order]
    if state.settings["reminders"]:
        rows.append([IBtn("التذكير", callback_data="m:rem")])
    return InlineKeyboardMarkup(rows)


def menu_text(u):
    return (f"<b>أذكار الصباح والمساء</b>\n{SEP}\n"
            "اختر الأذكار التي تريد قراءتها. العدّاد خاص بك وحدك، وتستطيع المتابعة من حيث توقفت.")


def kind_label(uid, u, kind):
    s = state.find(uid, kind)
    if s and not s["closed"] and s["date"] == user_today(u):
        if not s["done"]:
            return f"متابعة {TITLES[kind]}"
        if kind in KINDS:
            return f"{TITLES[kind]} (تمّت اليوم)"
    return f"ابدأ {TITLES[kind]}" if kind in KINDS else TITLES[kind]


def menu_kb(uid, u):
    rows = [[IBtn(kind_label(uid, u, k), callback_data=f"m:{k}", style="primary")] for k in KINDS]
    rows.append([IBtn(kind_label(uid, u, k), callback_data=f"m:{k}", style="primary") for k in EXTRA])
    rows.append([IBtn("إحصائياتي", callback_data="m:stats"), IBtn("التذكير", callback_data="m:rem")])
    rows.append([IBtn("قنواتي", callback_data="cp:list"), IBtn("مشاركة البوت", callback_data="m:share")])
    if is_admin(uid):
        rows.append([IBtn("لوحة المدير", callback_data="ad:menu")])
    return InlineKeyboardMarkup(rows)


def stats_text(u):
    lines = [f"<b>إحصائياتي</b>\n{SEP}",
             f"أكملت <b>{u['items']}</b> ذكراً • مجموع التكرارات <b>{u['taps']}</b>"]
    for k in KINDS:
        lines.append(f"{TITLES[k]}: أتممتها <b>{u['days'][k]}</b> يوماً • الأيام المتتالية: <b>{effective_streak(u, k)}</b>")
    lines.append("جلسات مكتملة: " + " • ".join(f"{TITLES[k]} {u['cnt'][k]}" for k in EXTRA))
    return "\n".join(lines)


def rem_text(u):
    lines = [f"<b>التذكير التلقائي</b>\n{SEP}"]
    if not state.settings["reminders"]:
        lines.append("التذكير متوقف حالياً من إدارة البوت.")
    for k in KINDS:
        lines.append(f"{TITLES[k]}: <b>{'مفعّل' if u['rem'][k] else 'متوقف'}</b> — {user_time(u, k)}")
    tzn = user_tz(u)
    lines.append(f"المنطقة الزمنية: <b>{esc(tzn)}</b> (الآن {now_in(tzn):%H:%M})")
    lines.append("\nيصلك تذكير في الوقت المحدد، ولا يصلك إن كنت قد أتممت أذكار ذلك اليوم. أوقفه متى شئت.")
    return "\n".join(lines)


def rem_kb(u):
    return InlineKeyboardMarkup([
        [IBtn(f"{TITLES[k]}: " + ("مفعّل" if u["rem"][k] else "متوقف"), callback_data=f"m:rt:{k}",
              style="success" if u["rem"][k] else "danger") for k in KINDS],
        [IBtn("وقت الصباح", callback_data="m:rtime:morning", style="primary"),
         IBtn("وقت المساء", callback_data="m:rtime:evening", style="primary")],
        [IBtn("المنطقة الزمنية", callback_data="m:rtz", style="primary")],
        [IBtn("رجوع", callback_data="m:menu")]])


async def on_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.pop("mode", None)
    usr, msg = update.effective_user, update.message
    kind, cid = parse_start_arg(ctx.args[0] if getattr(ctx, "args", None) else "")
    u, new = state.register(usr.id, usr.first_name or usr.username or "", usr.username or "")
    ch = state.channel(cid) if cid else None
    if new and ch:                                  # تسجيل جديد جاء عبر قناة معيّنة
        u["via"] = ch["cid"]
        ch["stats"]["users"] += 1
        state.dirty = True
    if new or not u["welcomed"]:                   # أول مرة: تسجيل + ترحيب ثم يضغط الزر بنفسه
        u["welcomed"] = True
        await msg.reply_text(welcome_text(u), parse_mode=ParseMode.HTML,
                             reply_markup=welcome_kb(kind if kind in KINDS else None, ch["cid"] if ch else None))
        return
    if kind:                                       # مسجَّل مسبقاً: ابدأ مباشرة بلا خطوات إضافية
        await begin(ctx.bot, usr.id, kind, src=ch["cid"] if ch else None)
        return
    await msg.reply_text(menu_text(u), parse_mode=ParseMode.HTML, reply_markup=menu_kb(usr.id, u))


async def on_user_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    usr, data = q.from_user, q.data
    u, _ = state.register(usr.id, usr.first_name or usr.username or "", usr.username or "")
    await _answer(q)
    parts = data.split(":")
    if parts[0] == "r":
        if len(parts) > 1 and parts[1] in ALL_KINDS:
            await begin(ctx.bot, usr.id, parts[1], force=True)
        return
    act = parts[1] if len(parts) > 1 else ""
    if act in ALL_KINDS:
        src = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
        await begin(ctx.bot, usr.id, act, src=src)
    elif act == "menu":
        ctx.user_data.pop("mode", None)
        await safe_edit(q, menu_text(u), menu_kb(usr.id, u))
    elif act == "stats":
        await safe_edit(q, stats_text(u), InlineKeyboardMarkup([[IBtn("رجوع", callback_data="m:menu")]]))
    elif act == "share":
        await ctx.bot.send_message(usr.id, "شارك البوت مع أحبابك ليكون لهم أجر الدلالة على الخير:\n"
                                           f"https://t.me/{await bot_username(ctx.bot)}")
    elif act == "rem":
        await safe_edit(q, rem_text(u), rem_kb(u))
    elif act == "rt" and len(parts) > 2 and parts[2] in KINDS:
        u["rem"][parts[2]] = not u["rem"][parts[2]]
        state.udirty = True
        await safe_edit(q, rem_text(u), rem_kb(u))
    elif act == "rtime" and len(parts) > 2 and parts[2] in KINDS:
        await safe_edit(q, f"<b>وقت تذكير {TITLES[parts[2]]}</b>\nالحالي: <b>{user_time(u, parts[2])}</b>\n"
                           "اختر وقتاً (نظام 24 ساعة):",
                        time_picker_kb(parts[2], lambda k, t: f"m:rset:{k}:{t}", f"m:rtc:{parts[2]}", "m:rem"))
    elif act == "rset" and len(parts) > 3 and parts[2] in KINDS and len(parts[3]) == 4:
        u["rt"][parts[2]] = f"{parts[3][:2]}:{parts[3][2:]}"
        sync_rem(u)
        await safe_edit(q, rem_text(u), rem_kb(u))
    elif act == "rtc" and len(parts) > 2 and parts[2] in KINDS:
        ctx.user_data["mode"] = ("rtime", parts[2])
        await safe_edit(q, "اكتب الوقت مثل <code>05:30</code> أو <code>5:30 ص</code> أو <code>17:45</code>",
                        InlineKeyboardMarkup([[IBtn("رجوع", callback_data="m:rem")]]))
    elif act == "rtz":
        await safe_edit(q, f"<b>منطقتك الزمنية</b>\nالحالية: <b>{esc(user_tz(u))}</b> (الآن {now_in(user_tz(u)):%H:%M})\n"
                           "اختر مدينتك:", tz_picker_kb(lambda i: f"m:rz:{i}", "m:rzc", "m:rem"))
    elif act == "rz" and len(parts) > 2 and parts[2].isdigit() and int(parts[2]) < len(TZ_CHOICES):
        u["tz"] = TZ_CHOICES[int(parts[2])][0]
        sync_rem(u)
        await safe_edit(q, rem_text(u), rem_kb(u))
    elif act == "rzc":
        ctx.user_data["mode"] = ("rtz",)
        await safe_edit(q, "اكتب اسم منطقتك الزمنية بصيغة IANA مثل <code>Asia/Hebron</code> أو <code>Europe/London</code>",
                        InlineKeyboardMarkup([[IBtn("رجوع", callback_data="m:rem")]]))


# ══════════════════════════ قنوات المستخدم (كل مالك يتحكم بقنواته فقط) ══════════════════════════
NOTE_PROMPT = "أرسل النص الإضافي الذي يظهر في منشورك (حتى {n} حرف)، أو أرسل <code>-</code> لحذفه."


def can_manage(uid, ch):
    return ch is not None and (is_admin(uid) or ch["owner"] == uid)


def chan_text(ch, viewer):
    st = ch["stats"]
    lines = [f"<b>{esc(ch_label(ch))}</b>" + (f" (@{esc(ch['username'])})" if ch["username"] and ch["title"] else ""), SEP,
             f"الحالة: <b>{'تعمل' if ch['enabled'] else 'متوقفة'}</b>",
             f"المنطقة الزمنية: <b>{esc(ch['tz'])}</b> (الآن {now_in(ch['tz']):%H:%M})",
             f"الصباح: <b>{ch['morning']}</b> — {'يعمل' if ch['morning_on'] else 'متوقف'}",
             f"المساء: <b>{ch['evening']}</b> — {'يعمل' if ch['evening_on'] else 'متوقف'}",
             f"حذف منشور الأمس عند نشر الجديد: {'نعم' if ch['delete_old'] else 'لا'}",
             f"نص إضافي: {esc(short(ch['note'], 60)) if ch['note'] else 'لا يوجد'}",
             f"الموعد القادم: {next_run_text(ch)}", SEP,
             f"عبر قناتك: <b>{st['users']}</b> مسجَّل جديد • <b>{st['starts']}</b> جلسة • أتمّها <b>{st['done']}</b> "
             f"• <b>{st['taps']}</b> تكرار"]
    if is_admin(viewer) and ch["owner"] != viewer:
        lines.append(f"المالك: {esc(owner_name(ch))} ({ch['owner']})")
    return "\n".join(lines)


def chan_kb(ch, viewer):
    c = ch["cid"]
    back = "cp:list" if ch["owner"] == viewer or not is_admin(viewer) else "ad:ch:0"
    return InlineKeyboardMarkup([
        [IBtn("وقت الصباح", callback_data=f"cp:{c}:t:morning", style="primary"),
         IBtn("وقت المساء", callback_data=f"cp:{c}:t:evening", style="primary")],
        [IBtn("الصباح: " + ("يعمل" if ch["morning_on"] else "متوقف"), callback_data=f"cp:{c}:on:morning",
              style="success" if ch["morning_on"] else "danger"),
         IBtn("المساء: " + ("يعمل" if ch["evening_on"] else "متوقف"), callback_data=f"cp:{c}:on:evening",
              style="success" if ch["evening_on"] else "danger")],
        [IBtn("المنطقة الزمنية", callback_data=f"cp:{c}:z", style="primary"),
         IBtn("نص إضافي", callback_data=f"cp:{c}:note", style="primary")],
        [IBtn("جرّب الصباح (لي فقط)", callback_data=f"cp:{c}:prev:morning"),
         IBtn("جرّب المساء (لي فقط)", callback_data=f"cp:{c}:prev:evening")],
        [IBtn("انشر الصباح الآن", callback_data=f"cp:{c}:pub:morning", style="success"),
         IBtn("انشر المساء الآن", callback_data=f"cp:{c}:pub:evening", style="success")],
        [IBtn("فحص الصلاحيات", callback_data=f"cp:{c}:chk"),
         IBtn("حذف منشور الأمس: " + ("نعم" if ch["delete_old"] else "لا"), callback_data=f"cp:{c}:do")],
        [IBtn("إيقاف النشر" if ch["enabled"] else "تشغيل النشر", callback_data=f"cp:{c}:en",
              style="danger" if ch["enabled"] else "success")],
        [IBtn("حذف القناة من البوت", callback_data=f"cp:{c}:rm", style="danger")],
        [IBtn("رجوع", callback_data=back)]])


def mychans_view(uid):
    mine = state.channels_of(uid)
    text = ("<b>قنواتي</b>\n" + SEP + "\n" +
            ("\n".join(f"• {esc(ch_label(c))} — {'تعمل' if c['enabled'] else 'متوقفة'}" for c in mine)
             if mine else "لا توجد قنوات بعد. أضف قناتك لينشر البوت فيها الأذكار تلقائياً."))
    rows = [[IBtn(short(ch_label(c)), callback_data=f"cp:{c['cid']}", style="primary")] for c in mine]
    rows.append([IBtn("إضافة قناة", callback_data="cp:add", style="success")])
    rows.append([IBtn("رجوع", callback_data="m:menu")])
    return text, InlineKeyboardMarkup(rows)


def mark_passed_sent(ch):
    now = now_in(ch["tz"])
    for k in KINDS:
        if hhmm_passed(now, ch[k]):
            ch["sent"][k] = now.date().isoformat()


async def handle_add_channel(update, ctx):
    msg, usr = update.message, update.effective_user
    text = (msg.text or "").strip()
    fc = forwarded_chat(msg)
    ref = fc.id if fc is not None else parse_channel_ref(text)
    if ref is None:
        await msg.reply_text("لم أفهم المعرّف. أرسل مثل @mychannel أو رقم القناة، أو حوّل رسالة منها."); return
    info, err = await verify_channel(ctx.bot, ref, usr.id)
    if err:
        await msg.reply_text(err); return
    existing = state.channel_by_chat(info["id"])
    if existing and existing["owner"] != usr.id and not is_admin(usr.id):
        await msg.reply_text("هذه القناة مضافة بالفعل بواسطة مشرف آخر. اطلب منه التحكم بها أو إزالتها أولاً."); return
    if existing:
        existing.update({"title": info["title"], "username": info["username"]})
        ch, new = existing, False
        state.dirty = True
    else:
        if not is_admin(usr.id) and len(state.channels_of(usr.id)) >= MAX_CHANNELS_PER_USER:
            await msg.reply_text(f"وصلت للحد الأقصى ({MAX_CHANNELS_PER_USER} قنوات). احذف قناة لإضافة أخرى."); return
        ch, new = state.add_channel(info, usr.id), True
        mark_passed_sent(ch)
        if not is_admin(usr.id):
            u = state.users.get(str(usr.id), {})
            await notify_admins(ctx.bot, "<b>قناة جديدة أُضيفت</b>\n"
                                         f"القناة: {esc(ch_label(ch))}" + (f" (@{esc(ch['username'])})" if ch["username"] else "") +
                                         f"\nالمالك: {uname(u) if u else esc(usr.first_name or '')} [{usr.id}]")
    ctx.user_data.pop("mode", None)
    await msg.reply_text(f"{'تمت إضافة' if new else 'تم تحديث'} «{esc(ch_label(ch))}» بنجاح.\n"
                         "سينشر البوت الأذكار فيها تلقائياً في الأوقات التالية، وتستطيع تعديل كل شيء من هنا:\n\n"
                         + chan_text(ch, usr.id), parse_mode=ParseMode.HTML, reply_markup=chan_kb(ch, usr.id))


async def on_chan_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    state.register(uid, q.from_user.first_name or q.from_user.username or "", q.from_user.username or "")
    parts = q.data.split(":")
    head = parts[1] if len(parts) > 1 else ""
    if head == "list":
        await _answer(q)
        ctx.user_data.pop("mode", None)
        text, kb = mychans_view(uid)
        await safe_edit(q, text, kb); return
    if head == "add":
        await _answer(q)
        ctx.user_data["mode"] = ("add",)
        await safe_edit(q, "<b>إضافة قناة</b>\n1) أضف البوت مشرفاً في قناتك بصلاحية «نشر الرسائل».\n"
                           "2) أرسل لي هنا معرّف القناة مثل <code>@mychannel</code> أو رقمها، "
                           "أو <b>حوّل لي أي رسالة</b> من القناة (الأنسب للقنوات الخاصة).\n"
                           "يجب أن تكون مالك القناة أو مشرفاً فيها.",
                        InlineKeyboardMarkup([[IBtn("رجوع", callback_data="cp:list")]])); return
    ch = state.channel(int(head)) if head.isdigit() else None
    if not can_manage(uid, ch):
        await _answer(q, "هذه القناة ليست قناتك", alert=True); return
    await _answer(q)
    act = parts[2] if len(parts) > 2 else "menu"
    c = ch["cid"]
    back_here = InlineKeyboardMarkup([[IBtn("رجوع", callback_data=f"cp:{c}")]])

    async def show(prefix=""):
        await safe_edit(q, prefix + chan_text(ch, uid), chan_kb(ch, uid))

    if act == "menu":
        ctx.user_data.pop("mode", None)
        await show()
    elif act == "t" and len(parts) > 3 and parts[3] in KINDS:
        k = parts[3]
        await safe_edit(q, f"<b>وقت {TITLES[k]}</b>\nالحالي: <b>{ch[k]}</b>\nاختر وقتاً (نظام 24 ساعة):",
                        time_picker_kb(k, lambda kk, t: f"cp:{c}:s:{kk}:{t}", f"cp:{c}:tc:{k}", f"cp:{c}"))
    elif act == "s" and len(parts) > 4 and parts[3] in KINDS and len(parts[4]) == 4:
        ch[parts[3]] = f"{parts[4][:2]}:{parts[4][2:]}"
        state.dirty = True
        await show(f"تم ضبط وقت {TITLES[parts[3]]} على {ch[parts[3]]}.\n\n")
    elif act == "tc" and len(parts) > 3 and parts[3] in KINDS:
        ctx.user_data["mode"] = ("ctime", c, parts[3])
        await safe_edit(q, "اكتب الوقت مثل <code>05:30</code> أو <code>5:30 ص</code> أو <code>17:45</code>", back_here)
    elif act == "z":
        await safe_edit(q, f"<b>المنطقة الزمنية للقناة</b>\nالحالية: <b>{esc(ch['tz'])}</b> (الآن {now_in(ch['tz']):%H:%M})\n"
                           "اختر المدينة:", tz_picker_kb(lambda i: f"cp:{c}:zs:{i}", f"cp:{c}:zc", f"cp:{c}"))
    elif act == "zs" and len(parts) > 3 and parts[3].isdigit() and int(parts[3]) < len(TZ_CHOICES):
        ch["tz"] = TZ_CHOICES[int(parts[3])][0]
        state.dirty = True
        await show(f"تم ضبط المنطقة الزمنية على {ch['tz']}.\n\n")
    elif act == "zc":
        ctx.user_data["mode"] = ("ctz", c)
        await safe_edit(q, "اكتب اسم المنطقة الزمنية بصيغة IANA مثل <code>Asia/Hebron</code> أو <code>Europe/London</code>",
                        back_here)
    elif act == "on" and len(parts) > 3 and parts[3] in KINDS:
        ch[f"{parts[3]}_on"] = not ch[f"{parts[3]}_on"]
        state.dirty = True
        await show()
    elif act == "en":
        ch["enabled"] = not ch["enabled"]
        if ch["enabled"]:
            ch["fails"] = 0
        state.dirty = True
        await show()
    elif act == "do":
        ch["delete_old"] = not ch["delete_old"]
        state.dirty = True
        await show()
    elif act == "note":
        ctx.user_data["mode"] = ("cnote", c)
        await safe_edit(q, NOTE_PROMPT.format(n=NOTE_MAX) + (f"\n\nالحالي:\n{esc(ch['note'])}" if ch["note"] else ""), back_here)
    elif act == "prev" and len(parts) > 3 and parts[3] in KINDS:
        await begin(ctx.bot, uid, parts[3], force=True)
    elif act == "pub" and len(parts) > 3 and parts[3] in KINDS:
        await safe_edit(q, f"سيُنشر منشور <b>{TITLES[parts[3]]}</b> الآن في «{esc(ch_label(ch))}». متأكد؟",
                        InlineKeyboardMarkup([[IBtn("نعم، انشر", callback_data=f"cp:{c}:pubok:{parts[3]}", style="success")],
                                              [IBtn("إلغاء", callback_data=f"cp:{c}")]]))
    elif act == "pubok" and len(parts) > 3 and parts[3] in KINDS:
        try:
            await post_announcement(ctx.bot, ch, parts[3])
            ch["sent"][parts[3]] = now_in(ch["tz"]).date().isoformat()
            ch["fails"] = 0
            state.dirty = True
            await show(f"تم نشر {TITLES[parts[3]]} في القناة.\n\n")
        except TelegramError as e:
            await show(f"<b>تعذّر النشر:</b> {esc(str(e))}\n\n")
    elif act == "chk":
        info, err = await verify_channel(ctx.bot, ch["id"], None)
        await safe_edit(q, f"<b>فحص صلاحيات «{esc(ch_label(ch))}»</b>\n{SEP}\n" + ("سليمة، البوت يستطيع النشر." if info else esc(err)),
                        back_here)
    elif act == "rm":
        await safe_edit(q, f"سيتوقف البوت عن النشر في «{esc(ch_label(ch))}» وتُحذف إعداداتها. متأكد؟",
                        InlineKeyboardMarkup([[IBtn("نعم، احذف القناة", callback_data=f"cp:{c}:rmok", style="danger")],
                                              [IBtn("إلغاء", callback_data=f"cp:{c}")]]))
    elif act == "rmok":
        state.remove_channel(c)
        text, kb = mychans_view(uid)
        await safe_edit(q, "تم حذف القناة.\n\n" + text, kb)


# ══════════════════════════ لوحة المدير (يرى كل شيء) ══════════════════════════
def overview_text():
    now = now_in(state.settings["tz"])
    today = now.date().isoformat()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    users = list(state.users.values())
    ss = [s for s in state.sessions.values() if s["date"] == today]
    return ("<b>لوحة المدير</b>\n" + SEP + "\n"
            f"المستخدمون: <b>{len(users)}</b> (جدد اليوم {sum(1 for u in users if u['joined'] >= midnight)} • "
            f"نشطون اليوم {sum(1 for u in users if u['last'] >= midnight)} • "
            f"بالتذكير {sum(1 for u in users if u['started'] and any(u['rem'].values()))})\n"
            f"القنوات: <b>{len(state.channels)}</b> (تعمل {sum(1 for c in state.channels if c['enabled'])})\n"
            f"اليوم: بدأ <b>{len(ss)}</b> جلسة • أتمّ <b>{sum(1 for s in ss if s['done'] and not s['closed'])}</b> "
            f"• <b>{sum(s['taps'] for s in ss)}</b> تكرار\n"
            f"الإجمالي: <b>{sum(u['items'] for u in users)}</b> ذكراً مكتملاً • <b>{sum(u['taps'] for u in users)}</b> تكرار\n"
            f"الإعدادات الافتراضية: {esc(state.settings['tz'])} — صباح {state.settings['morning']} • مساء {state.settings['evening']}\n"
            f"التذكير العام: <b>{'يعمل' if state.settings['reminders'] else 'متوقف'}</b>\n"
            f"الأزرار الملونة: {'مدعومة' if _STYLE_SUPPORTED else 'غير مدعومة (حدّث المكتبة)'}")


def admin_kb():
    s = state.settings
    return InlineKeyboardMarkup([
        [IBtn(f"القنوات ({len(state.channels)})", callback_data="ad:ch:0", style="primary"),
         IBtn(f"المستخدمون ({len(state.users)})", callback_data="ad:u:0", style="primary")],
        [IBtn("رسالة للجميع", callback_data="ad:bc", style="primary"),
         IBtn("تصدير CSV", callback_data="ad:export", style="success")],
        [IBtn("الإعدادات الافتراضية", callback_data="ad:def"),
         IBtn("التذكير العام: " + ("يعمل" if s["reminders"] else "متوقف"), callback_data="ad:rem",
              style="success" if s["reminders"] else "danger")],
        [IBtn("قائمة المستخدم", callback_data="m:menu")]])


def admin_channels_view(page):
    chans = sorted(state.channels, key=lambda c: -c["added"])
    chunk, page, pages = paginate(chans, page)
    text = (f"<b>كل القنوات</b> ({len(chans)})\nصفحة {page + 1} من {pages}\n{SEP}\n" +
            ("\n".join(f"• {esc(ch_label(c))} — {esc(owner_name(c))} — {'تعمل' if c['enabled'] else 'متوقفة'}" for c in chunk)
             if chans else "لا توجد قنوات بعد."))
    rows = [[IBtn(short(f"{ch_label(c)} • {owner_name(c)}", 34), callback_data=f"cp:{c['cid']}", style="primary")] for c in chunk]
    nav = nav_row("ad:ch", page, pages)
    if nav:
        rows.append(nav)
    rows.append([IBtn("رجوع", callback_data="ad:menu")])
    return text, InlineKeyboardMarkup(rows)


def admin_users_view(page):
    users = sorted(state.users.items(), key=lambda kv: -kv[1]["last"])
    chunk, page, pages = paginate(users, page)
    text = f"<b>كل المستخدمين</b> ({len(users)})\nصفحة {page + 1} من {pages}\n{SEP}\n" + \
           ("\n".join(f"• {uname(u)} — <b>{u['items']}</b> ذكراً • {u['taps']} تكرار" for _, u in chunk)
            if users else "لا يوجد مستخدمون بعد.")
    rows = [[IBtn(short(f"{u['name'] or 'مستخدم'} • {u['items']} ذكر", 34), callback_data=f"ad:ud:{uid}", style="primary")]
            for uid, u in chunk]
    nav = nav_row("ad:u", page, pages)
    if nav:
        rows.append(nav)
    rows.append([IBtn("رجوع", callback_data="ad:menu")])
    return text, InlineKeyboardMarkup(rows)


def admin_user_detail(uid):
    u = state.users.get(str(uid))
    if not u:
        return "المستخدم غير موجود.", InlineKeyboardMarkup([[IBtn("رجوع", callback_data="ad:u:0")]])
    chans = state.channels_of(int(uid))
    lines = [f"<b>{uname(u)}</b>", SEP, f"المعرّف: <code>{uid}</code>",
             f"انضم: {fmt_ts(u['joined'])} • آخر نشاط: {fmt_ts(u['last'])}",
             f"الحالة: {'يتلقى الرسائل' if u['started'] else 'حظر البوت'}",
             f"المنطقة الزمنية: {esc(user_tz(u))}",
             "التذكير: " + " • ".join(f"{TITLES[k]} {'مفعّل ' + user_time(u, k) if u['rem'][k] else 'متوقف'}" for k in KINDS),
             f"أكمل <b>{u['items']}</b> ذكراً • <b>{u['taps']}</b> تكرار",
             "أيام الالتزام: " + " • ".join(f"{TITLES[k]} {u['days'][k]} (متتالية {effective_streak(u, k)})" for k in KINDS),
             "جلسات مكتملة: " + " • ".join(f"{TITLES[k]} {u['cnt'][k]}" for k in ALL_KINDS)]
    if u.get("via"):
        via = state.channel(u["via"])
        lines.append(f"سجّل عبر قناة: {esc(ch_label(via)) if via else u['via']}")
    if chans:
        lines.append("قنواته: " + "، ".join(esc(ch_label(c)) for c in chans))
    return "\n".join(lines), InlineKeyboardMarkup([[IBtn("رجوع", callback_data="ad:u:0")]])


def build_csv(kind):
    buf = io.StringIO()
    w = csv.writer(buf)
    if kind == "users":
        w.writerow(["id", "name", "username", "joined", "last_active", "receiving", "tz", "remind_morning", "remind_evening",
                    "items_completed", "taps", "morning_days", "evening_days", "morning_streak", "evening_streak",
                    "sessions_morning", "sessions_evening", "sessions_sleep", "sessions_prayer", "via_channel"])
        for uid, u in state.users.items():
            w.writerow([uid, u["name"], u["username"], fmt_ts(u["joined"]), fmt_ts(u["last"]), int(u["started"]),
                        user_tz(u), int(u["rem"]["morning"]), int(u["rem"]["evening"]), u["items"], u["taps"],
                        u["days"]["morning"], u["days"]["evening"], effective_streak(u, "morning"),
                        effective_streak(u, "evening"), *[u["cnt"][k] for k in ALL_KINDS], u["via"]])
    else:
        w.writerow(["cid", "chat_id", "title", "username", "owner_id", "owner_name", "added", "enabled", "tz", "morning",
                    "evening", "morning_on", "evening_on", "users", "starts", "done", "taps"])
        for c in state.channels:
            st = c["stats"]
            w.writerow([c["cid"], c["id"], c["title"], c["username"], c["owner"], owner_name(c), fmt_ts(c["added"]),
                        int(c["enabled"]), c["tz"], c["morning"], c["evening"], int(c["morning_on"]), int(c["evening_on"]),
                        st["users"], st["starts"], st["done"], st["taps"]])
    return ("\ufeff" + buf.getvalue()).encode("utf-8")


async def run_broadcast(bot, admin_id, text):
    sent = failed = 0
    body = f"<b>رسالة من إدارة البوت</b>\n{SEP}\n{esc(text)}"
    for uid, u in list(state.users.items()):
        if not u.get("started"):
            continue
        for attempt in range(2):
            try:
                await bot.send_message(int(uid), body, parse_mode=ParseMode.HTML)
                sent += 1
                break
            except Forbidden:
                u["started"] = False
                for k in KINDS:
                    u["rem"][k] = False
                state.udirty = True
                failed += 1
                break
            except RetryAfter as e:
                await asyncio.sleep(float(e.retry_after) + 1)
                if attempt == 1:
                    failed += 1
            except TelegramError:
                failed += 1
                break
        await asyncio.sleep(BROADCAST_GAP)
    await notify(bot, admin_id, f"انتهى الإرسال: وصلت الرسالة إلى <b>{sent}</b> مستخدم، وتعذّر <b>{failed}</b>.")


async def on_admin_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    if not is_admin(uid):
        await _answer(q, "هذا الأمر لمدير البوت فقط", alert=True); return
    await _answer(q)
    parts = q.data.split(":")
    act = parts[1]
    st = state.settings
    chat_id = q.message.chat_id

    if act == "menu":
        ctx.user_data.pop("mode", None)
        await safe_edit(q, overview_text(), admin_kb())
    elif act == "ch":
        text, kb = admin_channels_view(int(parts[2]) if len(parts) > 2 and parts[2].lstrip("-").isdigit() else 0)
        await safe_edit(q, text, kb)
    elif act == "u":
        text, kb = admin_users_view(int(parts[2]) if len(parts) > 2 and parts[2].lstrip("-").isdigit() else 0)
        await safe_edit(q, text, kb)
    elif act == "ud" and len(parts) > 2:
        text, kb = admin_user_detail(parts[2])
        await safe_edit(q, text, kb)
    elif act == "rem":
        st["reminders"] = not st["reminders"]
        state.dirty = True
        await safe_edit(q, overview_text(), admin_kb())
    elif act == "export":
        stamp = f"{datetime.now():%Y-%m-%d}"
        await ctx.bot.send_document(chat_id, document=io.BytesIO(build_csv("users")), filename=f"users_{stamp}.csv",
                                    caption=f"المستخدمون: {len(state.users)}")
        await ctx.bot.send_document(chat_id, document=io.BytesIO(build_csv("channels")), filename=f"channels_{stamp}.csv",
                                    caption=f"القنوات: {len(state.channels)}")
    elif act == "bc":
        ctx.user_data["mode"] = ("bc",)
        await safe_edit(q, "اكتب الرسالة التي تريد إرسالها لكل المستخدمين (نص عادي). ستراها أولاً قبل الإرسال.",
                        InlineKeyboardMarkup([[IBtn("رجوع", callback_data="ad:menu")]]))
    elif act == "bcok":
        text = ctx.application.bot_data.get("bc", {}).pop(uid, None)
        if not text:
            await safe_edit(q, "انتهت صلاحية الرسالة، أعد كتابتها.", InlineKeyboardMarkup([[IBtn("رجوع", callback_data="ad:menu")]])); return
        n = sum(1 for u in state.users.values() if u.get("started"))
        spawn(run_broadcast(ctx.bot, uid, text))
        await safe_edit(q, f"بدأ الإرسال إلى {n} مستخدم. سأخبرك عند الانتهاء.", InlineKeyboardMarkup([[IBtn("رجوع", callback_data="ad:menu")]]))
    elif act == "bcno":
        ctx.application.bot_data.get("bc", {}).pop(uid, None)
        await safe_edit(q, overview_text(), admin_kb())
    elif act == "def":
        await safe_edit(q, f"<b>الإعدادات الافتراضية</b>\nتُطبَّق على القنوات والمستخدمين الجدد فقط ولا تغيّر الموجودين.\n{SEP}\n"
                           f"المنطقة الزمنية: <b>{esc(st['tz'])}</b>\nالصباح: <b>{st['morning']}</b> • المساء: <b>{st['evening']}</b>",
                        InlineKeyboardMarkup([[IBtn("المنطقة الزمنية", callback_data="ad:dtz", style="primary")],
                                              [IBtn("وقت الصباح", callback_data="ad:dt:morning", style="primary"),
                                               IBtn("وقت المساء", callback_data="ad:dt:evening", style="primary")],
                                              [IBtn("رجوع", callback_data="ad:menu")]]))
    elif act == "dtz":
        await safe_edit(q, "اختر المنطقة الزمنية الافتراضية:", tz_picker_kb(lambda i: f"ad:dz:{i}", None, "ad:def"))
    elif act == "dz" and len(parts) > 2 and parts[2].isdigit() and int(parts[2]) < len(TZ_CHOICES):
        st["tz"] = TZ_CHOICES[int(parts[2])][0]
        state.dirty = True
        await safe_edit(q, overview_text(), admin_kb())
    elif act == "dt" and len(parts) > 2 and parts[2] in KINDS:
        await safe_edit(q, f"اختر وقت {TITLES[parts[2]]} الافتراضي:",
                        time_picker_kb(parts[2], lambda k, t: f"ad:ds:{k}:{t}", None, "ad:def"))
    elif act == "ds" and len(parts) > 3 and parts[2] in KINDS and len(parts[3]) == 4:
        st[parts[2]] = f"{parts[3][:2]}:{parts[3][2:]}"
        state.dirty = True
        await safe_edit(q, overview_text(), admin_kb())


# ══════════════════════════ الرسائل النصية ══════════════════════════
async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    ctx.user_data.pop("mode", None)
    await update.message.reply_text(overview_text(), parse_mode=ParseMode.HTML, reply_markup=admin_kb())


async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg, usr = update.message, update.effective_user
    mode = ctx.user_data.get("mode")
    text = (msg.text or "").strip()
    state.register(usr.id, usr.first_name or usr.username or "", usr.username or "") if state.users.get(str(usr.id)) else None
    kind = mode[0] if isinstance(mode, tuple) else None

    if kind == "add":
        await handle_add_channel(update, ctx)
    elif kind == "rtime":
        t = parse_hhmm(text)
        if not t:
            await msg.reply_text("صيغة غير صحيحة. اكتب مثل 05:30 أو 5:30 ص أو 17:45."); return
        u = state.users[str(usr.id)]
        u["rt"][mode[1]] = t
        sync_rem(u)
        ctx.user_data.pop("mode", None)
        await msg.reply_text(rem_text(u), parse_mode=ParseMode.HTML, reply_markup=rem_kb(u))
    elif kind == "rtz":
        if get_tz(text) is None:
            await msg.reply_text("منطقة زمنية غير معروفة. مثال صحيح: Asia/Hebron أو Europe/London"); return
        u = state.users[str(usr.id)]
        u["tz"] = text
        sync_rem(u)
        ctx.user_data.pop("mode", None)
        await msg.reply_text(rem_text(u), parse_mode=ParseMode.HTML, reply_markup=rem_kb(u))
    elif kind in ("ctime", "ctz", "cnote"):
        ch = state.channel(mode[1])
        if not can_manage(usr.id, ch):
            ctx.user_data.pop("mode", None)
            await msg.reply_text("هذه القناة ليست قناتك."); return
        if kind == "ctime":
            t = parse_hhmm(text)
            if not t:
                await msg.reply_text("صيغة غير صحيحة. اكتب مثل 05:30 أو 5:30 ص أو 17:45."); return
            ch[mode[2]] = t
        elif kind == "ctz":
            if get_tz(text) is None:
                await msg.reply_text("منطقة زمنية غير معروفة. مثال صحيح: Asia/Hebron أو Europe/London"); return
            ch["tz"] = text
        else:
            if len(text) > NOTE_MAX:
                await msg.reply_text(f"النص أطول من {NOTE_MAX} حرفاً. اختصره وأعد الإرسال."); return
            ch["note"] = "" if text == "-" else text
        state.dirty = True
        ctx.user_data.pop("mode", None)
        await msg.reply_text("تم الحفظ.\n\n" + chan_text(ch, usr.id), parse_mode=ParseMode.HTML, reply_markup=chan_kb(ch, usr.id))
    elif kind == "bc" and is_admin(usr.id):
        if not text:
            await msg.reply_text("أرسل نصاً."); return
        ctx.application.bot_data.setdefault("bc", {})[usr.id] = text
        ctx.user_data.pop("mode", None)
        n = sum(1 for u in state.users.values() if u.get("started"))
        await msg.reply_text(f"<b>معاينة الرسالة</b>\n{SEP}\n{esc(text)}\n{SEP}\nستُرسل إلى <b>{n}</b> مستخدم. متأكد؟",
                             parse_mode=ParseMode.HTML,
                             reply_markup=InlineKeyboardMarkup([[IBtn("نعم، أرسل للجميع", callback_data="ad:bcok", style="success")],
                                                                [IBtn("إلغاء", callback_data="ad:bcno", style="danger")]]))
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
    for ref in ENV_CHANNELS:                           # قنوات من متغير CHANNELS تُسجَّل باسم أول مدير
        r = parse_channel_ref(ref)
        if r is not None:
            info, err = await verify_channel(app.bot, r, None)
            if info and not state.channel_by_chat(info["id"]):
                mark_passed_sent(state.add_channel(info, ADMIN_IDS[0]))
            elif err:
                log.warning("القناة %s من الإعدادات: %s", ref, err)
    try:
        await app.bot.set_my_commands([BotCommand("start", "القائمة الرئيسية")])
        for aid in ADMIN_IDS:
            await app.bot.set_my_commands([BotCommand("start", "القائمة الرئيسية"), BotCommand("admin", "لوحة المدير")],
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
    app.add_handler(CallbackQueryHandler(on_chan_cb, pattern=r"^cp:"))
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
