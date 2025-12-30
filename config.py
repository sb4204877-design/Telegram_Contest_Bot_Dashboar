# config.py
import os

# توكن البوت
BOT_TOKEN = os.getenv("BOT_TOKEN") or "8355769575:AAG8V02ooaK_0QY-redqMHyZ59gO7jxgN-0"

# آيديات الأدمن (تُعرّف هنا — البوت يعرفهم تلقائيًا)
ADMIN_IDS = [int(x) for x in (os.getenv("ADMIN_IDS") or "8352203207").split(",") if x.strip().isdigit()]

# يوزر الأدمن (مع @) — يظهر في زر الدعم
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME") or "@SignalXProsupport1"

# اسم القناة بدون @
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME") or "SignalXProOfficial1"

# اسم البوت بدون @
BOT_USERNAME = os.getenv("BOT_USERNAME") or "GoldenDen_OfficialBot"

# إعدادات النظام
POINTS_PER_REFERRAL = int(os.getenv("POINTS_PER_REFERRAL", "5"))
MAX_JOIN_ATTEMPTS = int(os.getenv("MAX_JOIN_ATTEMPTS", "2"))

