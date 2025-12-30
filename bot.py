# bot.py
import sqlite3
import logging
import random
from datetime import datetime, timedelta
import config
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# === التكوين ===
BOT_TOKEN = config.BOT_TOKEN
ADMIN_IDS = set(config.ADMIN_IDS)
ADMIN_USERNAME = config.ADMIN_USERNAME
CHANNEL_USERNAME = config.CHANNEL_USERNAME
BOT_USERNAME = config.BOT_USERNAME
POINTS_PER_REFERRAL = config.POINTS_PER_REFERRAL
MAX_JOIN_ATTEMPTS = config.MAX_JOIN_ATTEMPTS

CHANNEL_ID = f"@{CHANNEL_USERNAME}"
CHANNEL_LINK = f"https://t.me/{CHANNEL_USERNAME}"

# === تهيئة قاعدة البيانات ===
def initialize_database():
    db_path = 'contest.db'
    conn = sqlite3.connect(db_path, check_same_thread=False)
    cursor = conn.cursor()
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        points INTEGER DEFAULT 0,
        successful_referrals INTEGER DEFAULT 0,
        failed_referrals INTEGER DEFAULT 0,
        referred_by INTEGER,
        banned INTEGER DEFAULT 0,
        join_count INTEGER DEFAULT 1,
        last_join_time TEXT,
        contests_participated INTEGER DEFAULT 0,
        total_wins INTEGER DEFAULT 0,
        has_verified INTEGER DEFAULT 0
    )''')
    
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN has_verified INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS contests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        end_time TEXT NOT NULL,
        status TEXT DEFAULT 'active',
        winner_count INTEGER DEFAULT 3
    )''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS cheat_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cheater1_id INTEGER,
        cheater2_id INTEGER,
        type TEXT DEFAULT 'mutual_referral',
        detected_at TEXT
    )''')
    
    conn.commit()
    return conn

db_connection = initialize_database()

# === وظائف قاعدة البيانات ===
def get_user_data(uid):
    c = db_connection.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (uid,))
    return c.fetchone()

def get_leader_points():
    c = db_connection.cursor()
    c.execute("SELECT MAX(points) FROM users WHERE banned = 0")
    result = c.fetchone()
    return max(result[0] or 1, 1)

def add_new_user(uid, un, fn, ref=None):
    c = db_connection.cursor()
    now = datetime.now().isoformat()
    c.execute("""INSERT OR IGNORE INTO users 
                 (user_id, username, full_name, referred_by, last_join_time, has_verified) 
                 VALUES (?, ?, ?, ?, ?, 0)""",
              (uid, un or 'unknown', fn or 'unknown', ref, now))
    db_connection.commit()

def increment_join_count(uid):
    c = db_connection.cursor()
    c.execute("SELECT join_count, banned, last_join_time FROM users WHERE user_id = ?", (uid,))
    row = c.fetchone()
    if row and not row[1]:
        last_time = datetime.fromisoformat(row[2]) if row[2] else None
        now = datetime.now()
        if last_time and (now - last_time).total_seconds() < 86400:
            new = row[0] + 1
            now_iso = now.isoformat()
            c.execute("UPDATE users SET join_count = ?, last_join_time = ? WHERE user_id = ?", (new, now_iso, uid))
            db_connection.commit()
            if new > MAX_JOIN_ATTEMPTS:
                c.execute("UPDATE users SET banned = 1 WHERE user_id = ?", (uid,))
                db_connection.commit()
                return True
        else:
            c.execute("UPDATE users SET join_count = 1, last_join_time = ? WHERE user_id = ?", (now.isoformat(), uid))
            db_connection.commit()
    return False

def award_points(ref_id):
    c = db_connection.cursor()
    c.execute("UPDATE users SET points = points + ?, successful_referrals = successful_referrals + 1 WHERE user_id = ?", 
              (POINTS_PER_REFERRAL, ref_id))
    db_connection.commit()

def reset_points():
    c = db_connection.cursor()
    c.execute("UPDATE users SET points = 0, successful_referrals = 0, failed_referrals = 0")
    db_connection.commit()

def get_winners(n):
    c = db_connection.cursor()
    c.execute("SELECT user_id, username, full_name, points FROM users WHERE banned = 0 ORDER BY points DESC LIMIT ?", (n,))
    return c.fetchall()

def create_contest(title, desc, end, winner_count):
    c = db_connection.cursor()
    c.execute("INSERT INTO contests (title, description, end_time, winner_count) VALUES (?, ?, ?, ?)", 
              (title, desc, end, winner_count))
    db_connection.commit()
    return c.lastrowid

def get_all_contests():
    c = db_connection.cursor()
    c.execute("SELECT * FROM contests ORDER BY end_time DESC")
    return c.fetchall()

def get_active_contests():
    c = db_connection.cursor()
    c.execute("SELECT * FROM contests WHERE status = 'active'")
    return c.fetchall()

def update_contest_status(contest_id, status):
    c = db_connection.cursor()
    c.execute("UPDATE contests SET status = ? WHERE id = ?", (status, contest_id))
    db_connection.commit()

def get_contest_by_id(contest_id):
    c = db_connection.cursor()
    c.execute("SELECT * FROM contests WHERE id = ?", (contest_id,))
    return c.fetchone()

def get_user_statistics():
    c = db_connection.cursor()
    stats = {}
    c.execute("SELECT COUNT(*) FROM users")
    stats['total_users'] = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users WHERE banned = 1")
    stats['banned_users'] = c.fetchone()[0]
    c.execute("SELECT SUM(points) FROM users")
    stats['total_points'] = c.fetchone()[0] or 0
    c.execute("SELECT COUNT(*) FROM contests")
    stats['total_contests'] = c.fetchone()[0]
    return stats

# === معالجة الغش الثنائي ===
async def handle_cheater_pair(context: ContextTypes.DEFAULT_TYPE, user1_id: int, user2_id: int):
    c = db_connection.cursor()
    c.execute("UPDATE users SET banned = 1 WHERE user_id IN (?, ?)", (user1_id, user2_id))
    c.execute("INSERT INTO cheat_logs (cheater1_id, cheater2_id, detected_at) VALUES (?, ?, ?)",
              (user1_id, user2_id, datetime.now().isoformat()))
    db_connection.commit()
    
    cheat_messages = [
        "🕵️‍♂️ نعرف أنك تحاول، لكن الغش لا يُجدي!",
        "🤖 حسابك مُعلّق لفحص السلوك. هل أنت إنسان حقًا؟",
        "🚫 تم اكتشاف نشاط غير طبيعي. الحساب محظور.",
        "✋ الغش يُفسد روح المنافسة. تم حظرك."
    ]
    msg_to_user = random.choice(cheat_messages)
    
    for uid in [user1_id, user2_id]:
        try:
            await context.bot.send_message(uid, msg_to_user)
        except:
            pass
    
    msg = (
        f"⚠️ تم اكتشاف غش ذاتي!\n"
        f"الحسابان: {user1_id} و {user2_id}\n"
        f"تم حظرهما تلقائيًا."
    )
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, msg)
        except:
            pass

# === وظائف مساعدة ===
async def check_member(ctx, uid):
    try:
        cm = await ctx.bot.get_chat_member(CHANNEL_ID, uid)
        return cm.status in ['member', 'administrator', 'creator']
    except:
        return False

async def broadcast(ctx, msg, btn_txt=None, btn_data=None):
    c = db_connection.cursor()
    c.execute("SELECT user_id FROM users WHERE banned = 0")
    for (uid,) in c.fetchall():
        try:
            if btn_txt and btn_data:
                await ctx.bot.send_message(uid, msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(btn_txt, callback_data=btn_data)]]))
            else:
                await ctx.bot.send_message(uid, msg)
        except:
            pass

def get_ref_link(uid):
    return f"https://t.me/{BOT_USERNAME}?start={uid}"

# === تذكيرات المسابقة ===
async def send_contest_reminder(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    contest_id = job_data['contest_id']
    reminder_type = job_data['type']

    contest = get_contest_by_id(contest_id)
    if not contest or contest[4] != 'active':
        return

    if reminder_type == '1h':
        msg = "⏳ تبقى ساعة على انتهاء المسابقة! أكمل إحالاتك الآن!"
    else:  # '10m'
        msg = "🚨 تبقى 10 دقائق فقط! هل أنت في الصدارة؟ 🏆"

    await broadcast(context, msg)

# === معالجات رئيسية ===
async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id

    user_data = get_user_data(uid)
    if user_data and user_data[7] == 1:
        await update.message.reply_text("🚫 تم حظرك من المسابقات نهائياً بسبب الغش.")
        return

    if uid in ADMIN_IDS:
        await show_admin(update, context)
        return

    un = user.username
    fn = user.full_name
    ref = None
    if context.args:
        try:
            r = int(context.args[0])
            if r != uid:
                ref = r
        except:
            pass

    if ref == uid:
        await update.message.reply_text("❌ لا يمكنك استخدام رابطك الخاص!")
        ref = None

    if ref:
        c = db_connection.cursor()
        c.execute("SELECT 1 FROM users WHERE user_id = ? AND referred_by = ?", (ref, uid))
        is_mutual = c.fetchone()
        if is_mutual:
            await handle_cheater_pair(context, uid, ref)
            ref = None

    add_new_user(uid, un, fn, ref)

    if await check_member(context, uid):
        await show_menu(update, context)
    else:
        kb = [
            [InlineKeyboardButton("انضم للقناة", url=CHANNEL_LINK)],
            [InlineKeyboardButton("✅ تحقق من الاشتراك", callback_data="verify")]
        ]
        await update.message.reply_text("🔒 يرجى الاشتراك في القناة أولاً.", reply_markup=InlineKeyboardMarkup(kb))

async def verify_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    user_data = get_user_data(uid)
    if user_data and user_data[7] == 1:
        cheat_messages = [
            "🕵️‍♂️ اكتشاف محاولات غش متكررة!",
            "🤖 سلوكك يشبه البوتات. تم الحظر.",
            "🚫 تم حظرك بسبب تكرار الخروج والدخول."
        ]
        await q.edit_message_text(random.choice(cheat_messages))
        return

    if await check_member(context, uid):
        is_banned = increment_join_count(uid)
        if is_banned:
            cheat_messages = [
                "🕵️‍♂️ اكتشاف محاولات غش متكررة!",
                "🤖 سلوكك يشبه البوتات. تم الحظر.",
                "🚫 تم حظرك بسبب تكرار الخروج والدخول."
            ]
            await q.edit_message_text(random.choice(cheat_messages))
            return

        c = db_connection.cursor()
        c.execute("SELECT referred_by, has_verified FROM users WHERE user_id = ?", (uid,))
        row = c.fetchone()
        if row:
            ref_by = row[0]
            already_verified = row[1]
            if not already_verified:
                c.execute("UPDATE users SET has_verified = 1 WHERE user_id = ?", (uid,))
                db_connection.commit()

                if ref_by and ref_by != uid:
                    award_points(ref_by)
                    try:
                        ref_user = get_user_data(ref_by)
                        if ref_user:
                            current_points = ref_user[3]
                            msg = f"🎉 تم انضمام شخص جديد من خلال رابطك!\nرصيدك الآن: {current_points} نقطة."
                            await context.bot.send_message(ref_by, msg)
                    except Exception as e:
                        logging.error(f"فشل إرسال إشعار إحالة: {e}")

        await show_menu(update, context)
    else:
        await q.edit_message_text(
            "❌ لست مشتركًا!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("انضم للقناة", url=CHANNEL_LINK)],
                [InlineKeyboardButton("🔄 تحقق", callback_data="verify")]
            ])
        )

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u = get_user_data(uid)
    if not u or u[7]:
        cheat_messages = [
            "🕵️‍♂️ اكتشاف محاولات غش متكررة!",
            "🤖 سلوكك يشبه البوتات. تم الحظر.",
            "🚫 تم حظرك بسبب تكرار الخروج والدخول."
        ]
        await update.effective_message.reply_text(random.choice(cheat_messages))
        return

    display_username = f"@{u[1]}" if u[1] != 'unknown' else "غير متوفر"

    msg = (
        "✨ مرحباً بك في بوت العرين الذهبي للمسابقات ✨\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 اسمك: {u[2]}\n"
        f"🆔 آيديك: {u[0]}\n"
        f"🏷️ يوزرك: {display_username}\n"
        f"⭐ نقاطك: {u[3]}\n"
        f"✅ الإحالات الناجحة: {u[4]}\n"
        f"❌ الإحالات الفاشلة: {u[5]}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🏆 حالتك: لم يتم استبعادك"
    )
    kb = [
        [InlineKeyboardButton("🏆 المسابقات الحالية", callback_data="view_active_contests")],
        [InlineKeyboardButton("👤 ملفي", callback_data="view_profile")],
        [InlineKeyboardButton("🛠️ الدعم الفني", callback_data="support"),
         InlineKeyboardButton("💎 تجميع النقاط", callback_data="earn_points")]
    ]
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.effective_message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb))

# === 🌟 ملفي: يعرض نسبة مقارنة بالمتصدر ===
async def view_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    u = get_user_data(uid)
    if not u or u[7]:
        await q.edit_message_text("🚫 تم حظرك من المسابقات نهائياً بسبب الغش.")
        return

    user_points = u[3]
    leader_points = get_leader_points()
    percentage = min(100.0, (user_points / leader_points) * 100)
    bar_length = 10
    filled = int((percentage / 100) * bar_length)
    bar = "█" * filled + "░" * (bar_length - filled)

    c = db_connection.cursor()
    c.execute("""
        SELECT username, full_name, points 
        FROM users 
        WHERE user_id != ? AND banned = 0 AND points > ? 
        ORDER BY points ASC 
        LIMIT 1
    """, (uid, user_points))
    next_competitor = c.fetchone()
    competitor_msg = ""
    if next_competitor:
        diff = next_competitor[2] - user_points
        un = f"@{next_competitor[0]}" if next_competitor[0] != 'unknown' else next_competitor[1]
        competitor_msg = f"\n🏃 أقرب منافس: {un} (يتفوق عليك بـ {diff} نقطة)"
    else:
        competitor_msg = "\n🏆 أنت في الصدارة!"

    profile_msg = (
        f"👤 **ملفك الشخصي**\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"الاسم: {u[2]}\n"
        f"اليوزر: {f'@{u[1]}' if u[1] != 'unknown' else 'غير متوفر'}\n"
        f"النقاط: {user_points}\n"
        f"الإحالات الناجحة: {u[4]}\n"
        f"المسابقات المشاركة: {u[9]}\n"
        f"الانتصارات: {u[10]}\n"
        f"\n📊 **لوحة الأداء**\n"
        f"مقارنًا بالمتصدر: {bar} {percentage:.1f}%\n"
        f"{competitor_msg}"
    )

    await q.edit_message_text(
        profile_msg,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]])
    )

# === عرض تفاصيل المسابقة (للمستخدمين) ===
async def view_contest_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    try:
        contest_id = int(q.data.split('_')[2])
        contest = get_contest_by_id(contest_id)
        if contest:
            msg = f"📌 {contest[1]}\n\n{contest[2]}\n\n⏰ تنتهي: {contest[3]}"
        else:
            msg = "❌ لم يتم العثور على المسابقة."
    except (IndexError, ValueError):
        msg = "❌ خطأ في تحميل تفاصيل المسابقة."
    await q.edit_message_text(
        msg,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]])
    )

# === معالجات القوائم ===
async def view_active_contests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    contests = get_active_contests()
    if not contests:
        await q.edit_message_text(
            "📭 لا توجد مسابقات حالياً.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]])
        )
        return

    for contest in contests:
        msg = f"📌 {contest[1]}\n{contest[2]}\n⏰ تنتهي: {contest[3]}"
        kb = [[InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]]
        await q.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb))
    
    await q.delete_message()

async def earn_points_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    ref_link = get_ref_link(uid)
    await q.edit_message_text(
        f"💎 كل إحالة ناجحة = {POINTS_PER_REFERRAL} نقاط!\n"
        f"🔗 رابطك: {ref_link}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]])
    )

async def support_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        f"🛠️ للدعم الفني، راسل الأدمن: {ADMIN_USERNAME}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]])
    )

# === معالجات الأدمن ===
async def show_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.effective_message.reply_text("🚫 غير مصرح لك.")
        return
    kb = [
        [InlineKeyboardButton("📢 إدارة المسابقات", callback_data="manage_contests")],
        [InlineKeyboardButton("📊 الإحصائيات", callback_data="view_statistics")],
        [InlineKeyboardButton("🛡️ مكافحة الغش", callback_data="anti_cheat_menu")],
        [InlineKeyboardButton("🏅 إدارة الفائزين", callback_data="manage_winners")],
    ]
    if update.callback_query:
        await update.callback_query.edit_message_text("👑 لوحة الأدمن", reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.effective_message.reply_text("👑 لوحة الأدمن", reply_markup=InlineKeyboardMarkup(kb))

async def manage_contests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    kb = [
        [InlineKeyboardButton("➕ نشر مسابقة", callback_data="new_contest")],
        [InlineKeyboardButton("📋 النشطة", callback_data="view_active_contests_admin")],
        [InlineKeyboardButton("⏳ المؤجلة", callback_data="view_postponed_contests")],
        [InlineKeyboardButton("🏁 المنتهية", callback_data="view_finished_contests")],
        [InlineKeyboardButton("❌ الملغاة", callback_data="view_cancelled_contests")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_admin")]
    ]
    await q.edit_message_text("📁 إدارة المسابقات", reply_markup=InlineKeyboardMarkup(kb))

async def view_active_contests_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    contests = get_active_contests()
    if not contests:
        await q.edit_message_text(
            "📭 لا توجد مسابقات نشطة.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="manage_contests")]])
        )
        return
    for contest in contests:
        msg = f"✅ {contest[1]}\n{contest[2]}\n⏰ تنتهي: {contest[3]}"
        kb = [
            [InlineKeyboardButton("🗑️ حذف", callback_data=f"delete_{contest[0]}"),
             InlineKeyboardButton("🚫 إلغاء", callback_data=f"cancel_{contest[0]}")],
            [InlineKeyboardButton("⏳ تأجيل", callback_data=f"postpone_{contest[0]}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="manage_contests")]
        ]
        await q.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb))
    await q.delete_message()

async def view_cancelled_contests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    c = db_connection.cursor()
    c.execute("SELECT * FROM contests WHERE status = 'cancelled'")
    contests = c.fetchall()
    if not contests:
        await q.edit_message_text(
            "<tool_call> لا توجد مسابقات ملغاة.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="manage_contests")]])
        )
        return
    for contest in contests:
        msg = f"❌ [ملغاة] {contest[1]}\n{contest[2]}\n⏰ كان ينتهي: {contest[3]}"
        await q.message.reply_text(msg)
    await q.edit_message_text("عرض المسابقات الملغاة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="manage_contests")]]))

async def new_contest_step1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("أرسل وصف المسابقة الكامل:")
    context.user_data['admin_step'] = 'desc'

async def handle_desc_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    context.user_data['desc'] = update.message.text
    kb = [
        [InlineKeyboardButton("⏱️ بالساعات", callback_data="unit_hours")],
        [InlineKeyboardButton("📅 بالأيام", callback_data="unit_days")]
    ]
    await update.message.reply_text("اختر وحدة المدة:", reply_markup=InlineKeyboardMarkup(kb))

async def handle_unit_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "unit_hours":
        context.user_data['unit'] = 'hours'
        await q.edit_message_text("أدخل عدد الساعات:")
    else:
        context.user_data['unit'] = 'days'
        await q.edit_message_text("أدخل عدد الأيام:")
    context.user_data['admin_step'] = 'duration'

async def handle_duration_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    try:
        num = int(update.message.text)
        if num <= 0:
            raise ValueError
        context.user_data['duration_num'] = num
        await update.message.reply_text("أدخل عدد الفائزين (أي رقم موجب):")
        context.user_data['admin_step'] = 'winner_count_input'
    except:
        await update.message.reply_text("❌ أدخل رقمًا صحيحًا.")

async def handle_winner_count_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    try:
        winner_count = int(update.message.text)
        if winner_count <= 0:
            raise ValueError
        
        unit = context.user_data['unit']
        duration_num = context.user_data['duration_num']
        desc = context.user_data['desc']
        
        now = datetime.now()
        if unit == 'hours':
            end = (now + timedelta(hours=duration_num)).strftime("%Y-%m-%d %H:%M")
            title_suffix = f"{duration_num} ساعة"
        else:
            end = (now + timedelta(days=duration_num)).strftime("%Y-%m-%d %H:%M")
            title_suffix = f"{duration_num} يوم"
        
        title = f"مسابقة {now.strftime('%d/%m')} ({title_suffix})"
        
        reset_points()
        contest_id = create_contest(title, desc, end, winner_count)
        
        await broadcast(context, "🧹 تم تصفير النقاط بسبب بدء مسابقة جديدة.")
        await broadcast(context, "🎉 تم بدء مسابقة جديدة!", "عرض التفاصيل", f"view_contest_{contest_id}")

        # === جدولة التذكيرات ===
        end_time = datetime.strptime(end, "%Y-%m-%d %H:%M")
        now_dt = datetime.now()
        job_queue = context.application.bot_data['job_queue']

        if (end_time - now_dt).total_seconds() > 3600:
            job_queue.run_once(
                send_contest_reminder,
                when=end_time - timedelta(hours=1),
                data={'contest_id': contest_id, 'type': '1h'}
            )
        if (end_time - now_dt).total_seconds() > 600:
            job_queue.run_once(
                send_contest_reminder,
                when=end_time - timedelta(minutes=10),
                data={'contest_id': contest_id, 'type': '10m'}
            )
        
        await update.message.reply_text(
            f"✅ تم نشر المسابقة!\nعدد الفائزين: {winner_count}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للوحة التحكم", callback_data="back_admin")]])
        )
    except Exception as e:
        logging.error(f"Error in winner count input: {e}")
        await update.message.reply_text("❌ أدخل رقمًا صحيحًا (أي رقم موجب).")
    finally:
        context.user_data.clear()

# === التأجيل ===
async def handle_postpone_step1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    contest_id = int(q.data.split('_')[1])
    context.user_data['postpone_contest_id'] = contest_id

    kb = [
        [InlineKeyboardButton("⏱️ بالساعات", callback_data="postpone_unit_hours")],
        [InlineKeyboardButton("📅 بالأيام", callback_data="postpone_unit_days")]
    ]
    await q.edit_message_text("كم تريد التأجيل؟", reply_markup=InlineKeyboardMarkup(kb))

async def handle_postpone_unit_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    unit = 'hours' if 'hours' in q.data else 'days'
    context.user_data['postpone_unit'] = unit
    msg = "أدخل عدد الساعات:" if unit == 'hours' else "أدخل عدد الأيام:"
    await q.edit_message_text(msg)
    context.user_data['admin_step'] = 'postpone_duration'

async def handle_postpone_duration_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    try:
        num = int(update.message.text)
        if num <= 0:
            raise ValueError
        
        contest_id = context.user_data['postpone_contest_id']
        unit = context.user_data['postpone_unit']
        contest = get_contest_by_id(contest_id)
        if not contest:
            await update.message.reply_text("❌ المسابقة غير موجودة.")
            return

        current_end = datetime.strptime(contest[3], "%Y-%m-%d %H:%M")
        if unit == 'hours':
            new_end = current_end + timedelta(hours=num)
            msg_to_users = f"⏳ تم تأجيل المسابقة لمدة {num} ساعة."
        else:
            new_end = current_end + timedelta(days=num)
            msg_to_users = f"⏳ تم تأجيل المسابقة لمدة {num} يوم."

        new_end_str = new_end.strftime("%Y-%m-%d %H:%M")

        c = db_connection.cursor()
        c.execute("UPDATE contests SET end_time = ?, status = 'postponed' WHERE id = ?", (new_end_str, contest_id))
        db_connection.commit()

        await broadcast(context, msg_to_users)

        await update.message.reply_text(
            f"✅ تم التأجيل بنجاح حتى {new_end_str}.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للوحة التحكم", callback_data="back_admin")]])
        )
    except:
        await update.message.reply_text("❌ أدخل رقمًا صحيحًا.")
    finally:
        context.user_data.clear()

async def view_postponed_contests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    c = db_connection.cursor()
    c.execute("SELECT * FROM contests WHERE status = 'postponed'")
    contests = c.fetchall()
    
    if not contests:
        await q.edit_message_text(
            "<tool_call> لا توجد مسابقات مؤجلة.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="manage_contests")]])
        )
        return

    for contest in contests:
        msg = f"⏳ [مؤجلة] {contest[1]}\n{contest[2]}\n⏰ تنتهي الآن: {contest[3]}"
        kb = [
            [InlineKeyboardButton("⏹️ إنهاء التأجيل", callback_data=f"resume_contest_{contest[0]}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="manage_contests")]
        ]
        await q.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb))
    await q.delete_message()

async def resume_contest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    contest_id = int(q.data.split('_')[2])
    update_contest_status(contest_id, 'active')
    await broadcast(context, "▶️ تم استئناف المسابقة!")
    await q.edit_message_text(
        "✅ تم إنهاء التأجيل واستئناف المسابقة.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="manage_contests")]])
    )

# === المسابقات المنتهية ===
async def view_finished_contests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    c = db_connection.cursor()
    c.execute("SELECT * FROM contests WHERE status = 'finished' ORDER BY end_time DESC")
    contests = c.fetchall()
    
    if not contests:
        await q.edit_message_text(
            "<tool_call> لا توجد مسابقات منتهية.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="manage_contests")]])
        )
        return

    for contest in contests:
        msg = f"🏁 [منتهية] {contest[1]}\n{contest[2]}\n⏰ انتهت في: {contest[3]}\n🏅 عدد الفائزين: {contest[5]}"
        kb = [
            [InlineKeyboardButton("👁️ عرض الفائزين", callback_data=f"view_winners_of_{contest[0]}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="manage_contests")]
        ]
        await q.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb))
    await q.delete_message()

async def view_winners_of_contest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    try:
        contest_id = int(q.data.split('_')[4])
        contest = get_contest_by_id(contest_id)
        if not contest:
            raise ValueError
        
        winner_count = contest[5]
        winners = get_winners(winner_count)
        
        if not winners:
            await q.edit_message_text(
                "<tool_call> لا يوجد فائزون مسجلون.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="manage_contests")]])
            )
            return

        msg = f"🏆 فائزون في: {contest[1]}\n\n"
        for i, w in enumerate(winners, 1):
            un = f"@{w[1]}" if w[1] != 'unknown' else "غير متوفر"
            msg += f"{i}. {w[2]} ({un}) — النقاط: {w[3]}\n"

        await q.edit_message_text(
            msg,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="manage_contests")]])
        )
    except:
        await q.edit_message_text(
            "❌ خطأ في تحميل الفائزين.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="manage_contests")]])
        )

# === ⭐ إدارة الفائزين ===
async def manage_winners(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    c = db_connection.cursor()
    c.execute("SELECT id, title, end_time, winner_count FROM contests WHERE status = 'finished' ORDER BY end_time DESC")
    contests = c.fetchall()
    
    if not contests:
        await q.edit_message_text(
            "<tool_call> لا توجد مسابقات منتهية لإعلان فائزين.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_admin")]])
        )
        return

    kb = []
    for contest in contests:
        kb.append([InlineKeyboardButton(f"{contest[1]} ({contest[2][:10]})", callback_data=f"announce_winners_{contest[0]}")])
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_admin")])
    
    await q.edit_message_text("🎯 اختر مسابقة لإعلان فائزيها:", reply_markup=InlineKeyboardMarkup(kb))

async def announce_winners(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    try:
        contest_id = int(q.data.split('_')[2])
        contest = get_contest_by_id(contest_id)
        if not contest or contest[4] != 'finished':
            await q.edit_message_text("❌ هذه المسابقة غير منتهية.")
            return

        winner_count = contest[5]
        winners = get_winners(winner_count)

        if not winners:
            await q.edit_message_text("<tool_call> لا يوجد مستخدمون مؤهلون للفوز.")
            return

        msg = f"🏆 فائزون في: {contest[1]}\n(إجمالي: {winner_count} فائز)\n\n"
        winner_ids = []
        for i, w in enumerate(winners, 1):
            un = f"@{w[1]}" if w[1] != 'unknown' else "غير متوفر"
            msg += f"{i}. {w[2]} ({un}) — النقاط: {w[3]}\n"
            winner_ids.append(w[0])

        kb = [
            [InlineKeyboardButton("📤 إرسال إشعارات الفائزين", callback_data=f"notify_winners_{contest_id}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="manage_winners")]
        ]
        context.user_data['current_winner_ids'] = winner_ids
        context.user_data['current_contest_id'] = contest_id
        await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb))
    except Exception as e:
        logging.error(f"خطأ في announce_winners: {e}")
        await q.edit_message_text("❌ خطأ في تحميل الفائزين.")

async def notify_winners(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    contest_id = context.user_data.get('current_contest_id')
    winner_ids = context.user_data.get('current_winner_ids', [])
    
    if not contest_id or not winner_ids:
        await q.edit_message_text("❌ لا توجد بيانات كافية.")
        return

    for uid in winner_ids:
        try:
            await context.bot.send_message(uid, "🎉 تهانينا! أنت من الفائزين! 🏆\n\nشكرًا لمشاركتك ودعمك!")
        except:
            pass

    placeholders = ','.join('?' * len(winner_ids))
    c = db_connection.cursor()
    c.execute(f"SELECT user_id FROM users WHERE banned = 0 AND user_id NOT IN ({placeholders})", winner_ids)
    non_winners = [row[0] for row in c.fetchall()]

    winners = get_winners(len(winner_ids))
    winners_text = "🏆 تم اختيار الفائزين في المسابقة الأخيرة:\n\n"
    for i, w in enumerate(winners, 1):
        un = f"@{w[1]}" if w[1] != 'unknown' else w[2]
        winners_text += f"{i}. {un}\n"

    for uid in non_winners:
        try:
            await context.bot.send_message(uid, winners_text)
        except:
            pass

    await q.edit_message_text("✅ تم إرسال إشعارات الفائزين بنجاح!", 
                              reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="manage_winners")]]))

# === الفائزين (من الأدمن) ===
async def show_winners_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    contests = get_all_contests()
    if not contests:
        await q.edit_message_text("<tool_call> لا توجد مسابقات.", 
                                  reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_admin")]]))
        return
    
    latest_contest = contests[-1]
    if latest_contest[4] != 'finished':
        update_contest_status(latest_contest[0], 'finished')

    winner_count = latest_contest[5]
    winners = get_winners(winner_count)
    
    if not winners:
        await q.edit_message_text("<tool_call> لا يوجد مستخدمون مؤهلون.", 
                                  reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_admin")]]))
        return
    
    msg = f"🏆 الفائزون (أفضل {winner_count}):\n\n"
    for i, w in enumerate(winners, 1):
        un = f"@{w[1]}" if w[1] != 'unknown' else "غير متوفر"
        msg += f"{i}. {w[2]} ({un}) — النقاط: {w[3]}\n"
    
    kb = [
        [InlineKeyboardButton("📢 إرسال: تم إنهاء المسابقة!", callback_data="send_ended")],
        [InlineKeyboardButton("🏆 إرسال: من هم الفائزون؟", callback_data="send_winners_q")],
        [InlineKeyboardButton("🔙 رجوع للوحة التحكم", callback_data="back_admin")]
    ]
    await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb))

async def send_winners_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    
    contests = get_all_contests()
    if not contests:
        await q.edit_message_text("<tool_call> لا توجد مسابقات.")
        return
    
    latest_contest = contests[-1]
    winner_count = latest_contest[5]
    winners = get_winners(winner_count)
    
    if not winners:
        await broadcast(context, "🏅 لم يتم تحديد فائزون بعد.")
        await q.edit_message_text("✅ تم الإرسال.")
        return
    
    winners_list = []
    winner_ids = [w[0] for w in winners]
    for i, w in enumerate(winners, 1):
        un = f"@{w[1]}" if w[1] != 'unknown' else "غير متوفر"
        winners_list.append(f"{i}. {w[2]} ({un}) — النقاط: {w[3]}")
    
    winners_text = "🏆 الفائزون:\n\n" + "\n".join(winners_list)
    
    cursor = db_connection.cursor()
    cursor.execute("SELECT user_id FROM users WHERE banned = 0")
    for (user_id,) in cursor.fetchall():
        try:
            if user_id in winner_ids:
                await context.bot.send_message(user_id, "🎉 أنت من الفائزين! تهانينا 🏆")
            else:
                await context.bot.send_message(user_id, winners_text)
        except:
            pass
    
    await q.edit_message_text(
        "✅ تم إرسال قائمة الفائزين لجميع المستخدمين.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_admin")]])
    )

async def send_contest_ended(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await broadcast(context, "🏆 تم إنهاء المسابقة! شكرًا للمشاركة.")
    await q.edit_message_text(
        "✅ تم الإرسال.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_admin")]])
    )

# === الإحصائيات ===
async def view_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    stats = get_user_statistics()
    msg = (
        "📊 إحصائيات النظام:\n"
        "━━━━━━━━━━━━━━━━\n"
        f"👥 إجمالي المستخدمين: {stats['total_users']}\n"
        f"🚫 المحظورون: {stats['banned_users']}\n"
        f"⭐ إجمالي النقاط: {stats['total_points']}\n"
        f"🏆 عدد المسابقات: {stats['total_contests']}"
    )
    await q.edit_message_text(
        msg,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_admin")]])
    )

# === تصفير النقاط ===
async def reset_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    kb = [
        [InlineKeyboardButton("نعم", callback_data="do_reset"),
         InlineKeyboardButton("لا", callback_data="back_admin")]
    ]
    await q.edit_message_text(
        "⚠️ تأكيد تصفير النقاط؟",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def do_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    reset_points()
    await broadcast(context, "🧹 تم تصفير النقاط.")
    await q.edit_message_text(
        "✅ تم التصفير.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_admin")]])
    )

# === إدارة الغش ===
async def anti_cheat_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    kb = [
        [InlineKeyboardButton("👁️ عرض السجل", callback_data="view_cheat_logs")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_admin")]
    ]
    await q.edit_message_text("🛡️ لوحة مكافحة الغش", reply_markup=InlineKeyboardMarkup(kb))

async def view_cheat_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    c = db_connection.cursor()
    c.execute("SELECT * FROM cheat_logs ORDER BY detected_at DESC LIMIT 20")
    logs = c.fetchall()
    if not logs:
        await q.edit_message_text(
            "✅ لا توجد سجلات غش.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="anti_cheat_menu")]])
        )
        return
    msg = "⚠️ سجل محاولات الغش الأخيرة:\n\n"
    for log in logs:
        msg += f"📅 {log[4][:16]} | {log[1]} ↔ {log[2]}\n"
    await q.edit_message_text(
        msg,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="anti_cheat_menu")]])
    )

# === معالجة الإجراءات على المسابقات ===
async def handle_contest_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    contest_id = int(data.split('_')[1])
    
    if 'delete' in data:
        c = db_connection.cursor()
        c.execute("DELETE FROM contests WHERE id = ?", (contest_id,))
        db_connection.commit()
        msg = "🗑️ تم حذف المسابقة."
    elif 'cancel' in data:
        update_contest_status(contest_id, 'cancelled')
        msg = "🚫 تم إلغاء المسابقة."
    else:
        msg = "❌ خيار غير معروف."
    
    await q.edit_message_text(
        msg,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="manage_contests")]])
    )

# === معالجات العودة ===
async def back_main_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_menu(update, context)

async def back_admin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_admin(update, context)

# === معالج الأزرار الرئيسي ===
async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data

    if data == "back_main":
        await back_main_handler(update, context)
        return
    elif data == "back_admin":
        await back_admin_handler(update, context)
        return
    elif data == "manage_contests":
        await manage_contests(update, context)
        return
    elif data == "anti_cheat_menu":
        await anti_cheat_menu(update, context)
        return
    elif data == "view_cheat_logs":
        await view_cheat_logs(update, context)
        return
    elif data == "manage_winners":
        await manage_winners(update, context)
        return

    handlers = {
        "verify": verify_handler,
        "view_active_contests": view_active_contests,
        "view_active_contests_admin": view_active_contests_admin,
        "view_cancelled_contests": view_cancelled_contests,
        "view_profile": view_profile,
        "support": support_handler,
        "earn_points": earn_points_handler,
        "new_contest": new_contest_step1,
        "unit_hours": handle_unit_selection,
        "unit_days": handle_unit_selection,
        "reset_confirm": reset_confirm,
        "do_reset": do_reset,
        "show_winners_admin": show_winners_admin,
        "send_ended": send_contest_ended,
        "send_winners_q": send_winners_question,
        "view_statistics": view_statistics,
        "view_postponed_contests": view_postponed_contests,
        "view_finished_contests": view_finished_contests,
    }

    if data.startswith("view_contest_"):
        await view_contest_details(update, context)
        return
    elif data.startswith("postpone_") and not data.startswith("postpone_unit"):
        await handle_postpone_step1(update, context)
        return
    elif data.startswith("postpone_unit"):
        await handle_postpone_unit_selection(update, context)
        return
    elif data.startswith("resume_contest_"):
        await resume_contest(update, context)
        return
    elif data.startswith("view_winners_of_"):
        await view_winners_of_contest(update, context)
        return
    elif data.startswith("announce_winners_"):
        await announce_winners(update, context)
        return
    elif data.startswith("notify_winners_"):
        await notify_winners(update, context)
        return
    elif data.startswith(("delete_", "cancel_")):
        await handle_contest_action(update, context)
        return

    handler = handlers.get(data)
    if handler:
        await handler(update, context)
    else:
        await q.answer("❌ خيار غير معروف.")

# === معالجة النصوص من الأدمن ===
async def handle_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    step = context.user_data.get('admin_step')
    if step == 'desc':
        await handle_desc_input(update, context)
    elif step == 'duration':
        await handle_duration_input(update, context)
    elif step == 'winner_count_input':
        await handle_winner_count_input(update, context)
    elif step == 'postpone_duration':
        await handle_postpone_duration_input(update, context)

# === التشغيل ===
def main():
    logging.basicConfig(level=logging.WARNING)
    app = Application.builder().token(BOT_TOKEN).build()

    # معالج أخطاء
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
        logging.error("Exception while handling an update:", exc_info=context.error)
    app.add_error_handler(error_handler)

    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(MessageHandler(filters.TEXT & filters.User(user_id=list(ADMIN_IDS)), handle_admin_text))
    app.add_handler(CallbackQueryHandler(button_router))

    # تفعيل JobQueue
    app.bot_data['job_queue'] = app.job_queue

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
