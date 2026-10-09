# -*- coding: utf-8 -*-
"""
بوت أذكار الصباح والمساء للقنوات (تيليجرام)
═══════════════════════════════════════════
الفكرة : في وقت الصباح والمساء ينشر البوت في قناتك أول ذكر وتحته زر أزرق عليه العدد (مثلاً 100).
          كل ضغطة تُنقص العدد (والعدّاد مشترك بين كل المتابعين)، وعند الوصول إلى 0 ينتقل
          نفس المنشور تلقائياً للذكر التالي حتى تنتهي الأذكار، ثم يتكرر ذلك كل يوم.

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
from datetime import datetime, timedelta, timezone
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
EDIT_INTERVAL = 1.2    # أقل فاصل (ثواني) بين تعديلين لنفس المنشور (لتفادي حدود تيليجرام)
KEEP_DAYS = 3          # مدة الاحتفاظ بجلسات الأيام السابقة في الذاكرة

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
            "morning_on": True, "evening_on": True, "enabled": True, "delete_old": False}


@lru_cache(maxsize=64)
def get_tz(name):
    try:
        return ZoneInfo(name)
    except Exception:
        return None


def now_local():
    tz = get_tz(state.settings["tz"]) or timezone(timedelta(hours=3))
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


class State:
    def __init__(self, folder):
        os.makedirs(folder, exist_ok=True)
        self.dir = folder
        self.path = os.path.join(folder, "adhkar_state.json")
        self.channels, self.sent, self.sessions = [], {}, {}
        self.settings = default_settings()
        self.dirty = False
        data = self._load()
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
            if isinstance(data.get("sent"), dict):
                self.sent = data["sent"]
            for sid, s in (data.get("sessions") or {}).items():
                try:
                    if s["kind"] in KINDS and int(s["chat"]):
                        self.sessions[str(sid)] = {
                            "sid": str(sid), "chat": int(s["chat"]), "kind": s["kind"],
                            "mid": int(s["mid"]) if s.get("mid") else None, "idx": int(s["idx"]),
                            "left": int(s["left"]), "done": bool(s.get("done")), "closed": bool(s.get("closed")),
                            "taps": int(s.get("taps", 0)), "ts": float(s.get("ts", time.time())),
                            "edit": s.get("edit") if s.get("edit") in ("markup", "full") else None}
                except (KeyError, TypeError, ValueError):
                    continue

    def _load(self):
        if not os.path.exists(self.path):
            return None
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            bad = f"{self.path}.corrupt-{int(time.time())}"
            os.replace(self.path, bad)
            log.error("ملف الحالة تالف (%s) — نُقل إلى %s", e, bad)
            return None

    def flush(self):
        if not self.dirty:
            return
        self.dirty = False
        data = {"channels": self.channels, "settings": self.settings, "sent": self.sent, "sessions": self.sessions}
        _atomic_write(self.path, json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def purge(self):
        limit = time.time() - KEEP_DAYS * 86400
        old = [k for k, s in self.sessions.items() if s["ts"] < limit and (s["done"] or s["closed"])]
        for k in old:
            del self.sessions[k]
        if old:
            self.dirty = True


state: State = None   # يُنشأ في main()


def is_admin(uid):
    return uid in ADMIN_IDS


# ══════════════════════════ عرض الأذكار ══════════════════════════
def render_text(s):
    items = ADHKAR[s["kind"]]
    n, title = len(items), TITLES[s["kind"]]
    head = f"<b>{title}</b>"
    sep = "━━━━━━━━━━━━━━"
    if s["done"] and s["closed"]:
        return (f"{head}\n{sep}\nانتهى وقت هذه الجلسة.\nوصلنا إلى الذكر {min(s['idx'] + 1, n)} من {n}.\n"
                f"مجموع التكرارات: <b>{s['taps']}</b>\n\nتقبّل الله منّا ومنكم.")
    if s["done"]:
        return (f"{head}\n{sep}\nتمّت {title} بحمد الله تعالى.\n"
                f"مجموع التكرارات: <b>{s['taps']}</b>\n\nتقبّل الله منّا ومنكم صالح الأعمال.")
    it = items[s["idx"]]
    parts = [f"{head}  •  الذكر {s['idx'] + 1} من {n}", sep, f"<blockquote>{esc(it['text'])}</blockquote>"]
    if it.get("virtue"):
        parts.append(f"<i>{esc(it['virtue'])}</i>")
    parts.append(f"<i>[{esc(it['src'])}]</i>")
    parts.append(f"المطلوب: <b>{it['count']}</b> {'مرة' if it['count'] > 1 else 'مرة واحدة'}")
    if s["idx"] == 0:
        parts.append("\nاضغط الزر عند كل تكرار؛ العدّاد مشترك بيننا جميعاً.")
    return "\n".join(parts)


def render_kb(s):
    if s["done"] or s["closed"]:
        return None
    return InlineKeyboardMarkup([[IBtn(str(s["left"]), callback_data=f"c:{s['sid']}:{s['idx']}", style="primary")]])


def ch_label(c):
    return c.get("title") or (("@" + c["username"]) if c.get("username") else str(c["id"]))


# ══════════════════════════ الجلسات ══════════════════════════
async def close_previous(bot, chat_id, kind):
    """عند نشر جلسة جديدة: احذف جلسة الأمس (إن فُعّل الخيار) أو أغلق الزر إن لم تكتمل."""
    for sid, old in list(state.sessions.items()):
        if old["chat"] != chat_id or old["kind"] != kind:
            continue
        if state.settings["delete_old"] and old.get("mid"):
            try:
                await bot.delete_message(chat_id, old["mid"])
            except TelegramError as e:
                log.info("تعذّر حذف الرسالة القديمة: %s", e)
            del state.sessions[sid]
        elif not old["done"]:
            old["done"] = old["closed"] = True
            old["edit"] = "full"
        state.dirty = True


async def start_session(bot, chat_id, kind):
    await close_previous(bot, chat_id, kind)
    sid = secrets.token_hex(3)
    s = {"sid": sid, "chat": chat_id, "kind": kind, "mid": None, "idx": 0, "left": ADHKAR[kind][0]["count"],
         "done": False, "closed": False, "taps": 0, "ts": time.time(), "edit": None}
    msg = await bot.send_message(chat_id, render_text(s), parse_mode=ParseMode.HTML, reply_markup=render_kb(s))
    s["mid"] = msg.message_id
    state.sessions[sid] = s
    state.dirty = True
    return s


def register_tap(s):
    """ينقص العدّاد بمقدار واحد (متزامن بالكامل لذلك آمن مع تعدد الضغطات). يعيد 'tap' / 'next' / 'done'."""
    items = ADHKAR[s["kind"]]
    s["left"] -= 1
    s["taps"] += 1
    state.dirty = True
    if s["left"] > 0:
        s["edit"] = s["edit"] or "markup"
        return "tap"
    s["idx"] += 1
    if s["idx"] >= len(items):
        s["done"], s["left"] = True, 0
        s["edit"] = "full"
        return "done"
    s["left"] = items[s["idx"]]["count"]
    s["edit"] = "full"
    return "next"


async def on_tap(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    try:
        _, sid, idx = q.data.split(":")
        idx = int(idx)
    except ValueError:
        await _answer(q); return
    s = state.sessions.get(sid)
    if s is None or s["done"] or s["closed"]:
        await _answer(q, "انتهت هذه الجلسة"); return
    if idx != s["idx"]:                          # زر قديم (الذكر تغيّر قبل وصول الضغطة)
        s["edit"] = "full"
        await _answer(q, "انتقلنا إلى الذكر التالي"); return
    res = register_tap(s)
    await _answer(q, "تقبّل الله منك" if res == "done" else None)


async def _answer(q, text=None):
    try:
        await q.answer(text)
    except TelegramError:
        pass                                      # استعلام قديم/منتهٍ — لا يهم


async def edit_pass(bot):
    """يطبّق التعديلات المتراكمة على المنشورات (مرة واحدة لكل منشور بدل تعديل عند كل ضغطة)."""
    for s in list(state.sessions.values()):
        mode = s.get("edit")
        if not mode or not s.get("mid"):
            continue
        s["edit"] = None
        try:
            if mode == "full" or s["done"] or s["closed"]:
                await bot.edit_message_text(chat_id=s["chat"], message_id=s["mid"], text=render_text(s),
                                            parse_mode=ParseMode.HTML, reply_markup=render_kb(s))
            else:
                await bot.edit_message_reply_markup(chat_id=s["chat"], message_id=s["mid"], reply_markup=render_kb(s))
            state.dirty = True
        except RetryAfter as e:
            s["edit"] = "full" if "full" in (mode, s.get("edit")) else "markup"
            log.warning("حد التعديل: انتظار %s ثانية", e.retry_after)
            await asyncio.sleep(float(e.retry_after) + 1)
        except BadRequest as e:
            m = str(e).lower()
            if "not modified" in m:
                pass
            elif "not found" in m or "can't be edited" in m or "message to edit" in m:
                log.warning("المنشور %s لم يعد موجوداً — أُنهيت الجلسة", s["sid"])
                s["done"] = s["closed"] = True
            else:
                log.warning("فشل التعديل: %s", e)
        except Forbidden as e:
            log.warning("لا صلاحية للتعديل في %s: %s", s["chat"], e)
            s["done"] = s["closed"] = True
        except TelegramError as e:                # شبكة/مهلة: أعد المحاولة في الدورة القادمة
            s["edit"] = s["edit"] or mode
            log.warning("خطأ مؤقت أثناء التعديل: %s", e)
        await asyncio.sleep(0.05)


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
    for ch in list(state.channels):
        for kind in KINDS:
            if not st[f"{kind}_on"]:
                continue
            if state.sent.get(str(ch["id"]), {}).get(kind) == today:
                continue
            hh, mm = map(int, st[kind].split(":"))
            target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if not (target <= now < target + timedelta(minutes=GRACE_MIN)):
                continue
            state.sent.setdefault(str(ch["id"]), {})[kind] = today     # يُسجَّل أولاً لمنع التكرار عند الفشل
            state.dirty = True
            try:
                await start_session(bot, ch["id"], kind)
                log.info("نُشرت %s في %s", TITLES[kind], ch_label(ch))
            except TelegramError as e:
                log.error("فشل نشر %s في %s: %s", TITLES[kind], ch_label(ch), e)
                await notify_admins(bot, f"<b>تعذّر نشر {TITLES[kind]}</b> في «{esc(ch_label(ch))}»:\n"
                                         f"{esc(str(e))}\nتأكد أن البوت مشرف ولديه صلاحية نشر الرسائل.")


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
            await asyncio.sleep(EDIT_INTERVAL)
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
            if n % 600 == 0:
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
    return ("<b>لوحة أذكار الصباح والمساء</b>\n━━━━━━━━━━━━━━\n"
            f"القنوات:\n{chans}\n\n"
            f"المنطقة الزمنية: <b>{esc(s['tz'])}</b> (الساعة الآن {now:%H:%M})\n"
            f"الصباح: <b>{s['morning']}</b> — {'يعمل' if s['morning_on'] else 'متوقف'}\n"
            f"المساء: <b>{s['evening']}</b> — {'يعمل' if s['evening_on'] else 'متوقف'}\n"
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
        [IBtn("معاينة الصباح (لي فقط)", callback_data="ad:prev:morning"),
         IBtn("معاينة المساء (لي فقط)", callback_data="ad:prev:evening")],
        [IBtn("نشر الصباح الآن", callback_data="ad:pub:morning", style="success"),
         IBtn("نشر المساء الآن", callback_data="ad:pub:evening", style="success")],
        [IBtn("حالة اليوم", callback_data="ad:status"), IBtn("فحص الصلاحيات", callback_data="ad:check")],
        [IBtn("حذف منشور الأمس: " + ("نعم" if s["delete_old"] else "لا"), callback_data="ad:delold")],
        [IBtn("إيقاف كل شيء" if s["enabled"] else "تشغيل البوت", callback_data="ad:enabled",
              style="danger" if s["enabled"] else "success")],
    ])


def back_kb():
    return InlineKeyboardMarkup([[IBtn("رجوع", callback_data="ad:menu")]])


async def safe_edit(q, text, markup=None):
    try:
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            log.debug("edit failed: %s", e)


def status_text():
    lines = ["<b>حالة اليوم</b>", "━━━━━━━━━━━━━━"]
    if not state.channels:
        return "\n".join(lines + ["لا توجد قنوات."])
    today = now_local().date().isoformat()
    for c in state.channels:
        lines.append(f"\n<b>{esc(ch_label(c))}</b>")
        for kind in KINDS:
            mine = [s for s in state.sessions.values() if s["chat"] == c["id"] and s["kind"] == kind]
            s = max(mine, key=lambda x: x["ts"]) if mine else None
            sent_today = state.sent.get(str(c["id"]), {}).get(kind) == today
            if s is None or not sent_today:
                lines.append(f"{TITLES[kind]}: لم يُنشر اليوم بعد")
            elif s["done"] and not s["closed"]:
                lines.append(f"{TITLES[kind]}: اكتمل — {s['taps']} تكرار")
            elif s["closed"]:
                lines.append(f"{TITLES[kind]}: أُغلق قبل الاكتمال — {s['taps']} تكرار")
            else:
                lines.append(f"{TITLES[kind]}: الذكر {s['idx'] + 1} من {len(ADHKAR[kind])} "
                             f"(المتبقي {s['left']}) — {s['taps']} تكرار")
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
        rows = [[IBtn(lbl, callback_data=f"ad:z:{i}", style="primary") for i, (_, lbl) in enumerate(TZ_CHOICES)][j:j + 3]
                for j in range(0, len(TZ_CHOICES), 3)]
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
    elif act in ("on", "delold", "enabled"):
        key = {"on": f"{parts[2]}_on" if act == "on" else "", "delold": "delete_old", "enabled": "enabled"}[act]
        st[key] = not st[key]
        state.dirty = True
        await safe_edit(q, panel_text(), panel_kb())
    elif act == "prev":
        await start_session(ctx.bot, chat_id, parts[2])
    elif act == "pub":
        kind = parts[2]
        if not state.channels:
            await safe_edit(q, "أضف قناة أولاً.\n\n" + panel_text(), panel_kb()); return
        await safe_edit(q, f"سيُنشر <b>{TITLES[kind]}</b> الآن في {len(state.channels)} قناة. متأكد؟",
                        InlineKeyboardMarkup([[IBtn("نعم، انشر", callback_data=f"ad:pubok:{kind}", style="success")],
                                              [IBtn("إلغاء", callback_data="ad:menu")]]))
    elif act == "pubok":
        kind, ok, bad = parts[2], 0, []
        today = now_local().date().isoformat()
        for c in list(state.channels):
            try:
                await start_session(ctx.bot, c["id"], kind)
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
        lines = ["<b>فحص الصلاحيات</b>", "━━━━━━━━━━━━━━"]
        for c in state.channels:
            info, err = await verify_channel(ctx.bot, c["id"])
            lines.append(f"• {esc(ch_label(c))}: " + ("سليمة" if info else esc(err)))
        if not state.channels:
            lines.append("لا توجد قنوات.")
        await safe_edit(q, "\n".join(lines), back_kb())


def short(t, n=28):
    t = re.sub(r"\s+", " ", str(t)).strip()
    return t if len(t) <= n else t[: n - 1] + "…"


# ══════════════════════════ الرسائل الخاصة ══════════════════════════
async def on_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.pop("mode", None)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("بوت أذكار الصباح والمساء: ينشر الأذكار تلقائياً في القنوات المرتبطة به.")
        return
    await update.message.reply_text(panel_text(), parse_mode=ParseMode.HTML, reply_markup=panel_kb())


async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg, usr = update.message, update.effective_user
    if not is_admin(usr.id):
        return
    mode = ctx.user_data.get("mode")
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
    else:
        await msg.reply_text(panel_text(), parse_mode=ParseMode.HTML, reply_markup=panel_kb())


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
        for aid in ADMIN_IDS:
            await app.bot.set_my_commands([BotCommand("start", "لوحة التحكم")], scope=BotCommandScopeChat(aid))
    except TelegramError as e:
        log.warning("set_my_commands: %s", e)
    app.bot_data["tasks"] = [asyncio.create_task(f(app)) for f in (loop_edit, loop_schedule, loop_flush)]


async def post_shutdown(app: Application):
    for t in app.bot_data.get("tasks", []):
        t.cancel()
    state.flush()


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
    app.add_handler(CallbackQueryHandler(on_tap, pattern=r"^c:"))
    app.add_handler(CallbackQueryHandler(on_admin_cb, pattern=r"^ad:"))
    app.add_handler(CommandHandler("start", on_start, filters=filters.ChatType.PRIVATE))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, on_message))
    app.add_error_handler(on_error)
    start_keepalive()
    log.info("البوت يعمل…")
    app.run_polling(allowed_updates=["message", "callback_query"], drop_pending_updates=True)


if __name__ == "__main__":
    main()
