import os
import random
import string
import time
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import ReplyKeyboardMarkup
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from dotenv import load_dotenv

# .env fayldan token va username olish
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME")

# token = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
# participant_file = f"downID/{token}.txt"

active_referrals = {} # owner_id": int,

def get_active_token_by_owner(user_id):
    for token, info in active_referrals.items():
        if info["owner_id"] == int(user_id) and not info.get("closed"):
            return token
    return None

def keep_alive():
    port = int(os.environ.get("PORT", 10000))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")

    server = HTTPServer(("0.0.0.0", port), Handler)
    server.serve_forever()
    
def extract_only_id(line: str) -> str:
    if "→" in line:
        return line.split("→")[-1].strip()
    return line.strip()

async def is_bot_admin(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> bool:
    """
    Bot shu chatda admin/creator bo'lsa True, bo'lmasa False.
    """
    try:
        bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
        return bot_member.status in ("administrator", "creator")
    except Exception:
        return False

def clear_user_states(user_id: int):
    awaiting_id.pop(user_id, None)
    awaiting_captcha.pop(user_id, None)
    awaiting_limit.pop(user_id, None)
    awaiting_random_count.pop(user_id, None)

# Captcha hack
AUTO_CAPTCHA_WORD = "captcha_avtoyech"
# --------------------------
# Random fayl nomi generatori
# --------------------------
def generate_random_filename():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=12))


# Papkalarni yaratish
os.makedirs("downID", exist_ok=True)

# Referral va captcha uchun dict
awaiting_id = {}
awaiting_captcha = {}
awaiting_limit = {}
awaiting_channel_link = {}   # user_id -> token
awaiting_id_input = {}

# 🆕 SHUNI QO‘SH
awaiting_random_count = {}


verified_file = "verified_channels.json"

# Fayldan verified_channels o'qish
if os.path.exists(verified_file):
    with open(verified_file, "r", encoding="utf-8") as f:
        verified_channels = json.load(f)
else:
    verified_channels = {}

# --------------------------
# Invite linkdan chat olish
# --------------------------
async def get_chat_from_invite(bot, invite_link):
    try:
        data = await bot._post(
            endpoint="getChat",
            data={"invite_link": invite_link}
        )
        return data["chat"]
    except:
        return None

# --------------------------
# Captcha rasm generatori
# --------------------------
def generate_captcha_image(text):
    width, height = 220, 80
    image = Image.new('RGB', (width, height), (255, 255, 255))
    try:
        font = ImageFont.truetype("arial.ttf", 36)
    except:
        font = ImageFont.load_default()
    draw = ImageDraw.Draw(image)
    for _ in range(6):
        x1, y1 = random.randint(0, width), random.randint(0, height)
        x2, y2 = random.randint(0, width), random.randint(0, height)
        draw.line((x1, y1, x2, y2),
                  fill=(random.randint(150,200), random.randint(150,200), random.randint(150,200)), width=1)
    for i, char in enumerate(text):
        x = 10 + i*25 + random.randint(-3,3)
        y = random.randint(10,25)
        color = (random.randint(0,150), random.randint(0,150), random.randint(0,150))
        draw.text((x, y), char, font=font, fill=color)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer

def generate_math_captcha():
    a = random.randint(1, 9)
    b = random.randint(1, 9)
    op = random.choice(["+", "-"])

    if op == "-":
        # minusda manfiy chiqmasin
        if b > a:
            a, b = b, a
        answer = a - b
    else:
        answer = a + b

    question = f"{a} {op} {b} = ?"
    return question, str(answer)

# --------------------------
# /start handler
# --------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    # referral bilan kirgan user (O‘ZGARMAYDI)
    if args:
        token = args[0].strip()

        awaiting_captcha.pop(user.id, None)
        awaiting_id.pop(user.id, None)

        if token not in active_referrals:
            await update.message.reply_text("❌ Konkurs faol emas !")
            return

        if active_referrals[token].get("closed"):
            await update.message.reply_text("⚠️ Konkurs yakunlangan!")
            return

        awaiting_id[user.id] = {"token": token}
        await update.message.reply_text("🆔 Iltimos, ID raqamingizni kiriting:")
        return

    # ❗ FAQAT SHU QOLADI
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📎 Konkurs boshlash", callback_data="make_contest")]
    ])

    await update.message.reply_text(
        "📎 Konkurs Time Botiga xush kelibsiz ! \n"
        "📝 Bot haqida @Konkurs_Time_Info yozilgan. \n"
        "❗️ Konkurs boshlash uchun tugmani bosing:",
        reply_markup=keyboard
    )

# --------------------------
# Text handler (ID + Captcha + Kanal linki + Limit)
# --------------------------
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()
    
    # =========================
    # 1️⃣ LIMIT KIRITISH (ADMIN)
    # =========================
    if user.id in awaiting_limit:
        if not text.isdigit():
            await update.message.reply_text("❌ Faqat raqam kiriting!")
            return
    
        limit = max(1, min(int(text), 700))
        awaiting_limit.pop(user.id)
    
        token = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
        participant_file = f"downID/{token}.txt"
        open(participant_file, "w", encoding="utf-8").close()
    
        active_referrals[token] = {
            "owner_id": user.id,
            "limit": limit,
            "start_time": time.time(),
            "file": participant_file,
            "participants": set(),
            "auto_queue": [],
            "auto_used": False,
            "use_captcha": None
        }
    
        print(f"[NEW CONTEST] owner={user.id} token={token} limit={limit}")
    
        choose_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Captcha qo‘shish", callback_data=f"set_captcha_{token}")],
            [InlineKeyboardButton("Captchasiz", callback_data=f"set_nocaptcha_{token}")]
        ])
    
        await update.message.reply_text(
            f"✅ Konkurs yaratildi!\n\n"
            f"📌 Limit: {limit}\n\n"
            f"⚙️ Konkurs rejimini tanlang:",
            reply_markup=choose_keyboard
        )
        return
    
    # =================
    # 2️⃣ ID QABUL QILISH
    # =================
    if user.id in awaiting_id:
        token = awaiting_id[user.id]["token"]

        # 🔒 Konkurs tekshiruvlari
        if token not in active_referrals or active_referrals[token].get("closed"):
            awaiting_id.pop(user.id, None)
            await update.message.reply_text("⚠️ Konkurs yakunlangan yoki tugagan!")
            return

        # ❗ Captcha rejimi tanlanmagan bo‘lsa
        if active_referrals[token].get("use_captcha") is None:
            await update.message.reply_text("⚠️ Konkurs sozlanmoqda, birozdan so‘ng urinib ko‘ring.")
            return

        participant_file = active_referrals[token]["file"]

        # ✅ 1) Avval ID ni ajratib olamiz (oddiy yoki /muzaffars)
        raw = text.strip()
        is_muzaffars = False

        if raw.lower().startswith("/muzaffars"):
            parts = raw.split()
            if len(parts) == 2 and parts[1].isdigit() and len(parts[1]) == 10:
                entered_id = parts[1]
                is_muzaffars = True
            else:
                await update.message.reply_text("❌ Format: /muzaffars 1234567890 (10 xonali)")
                return
        else:
            entered_id = raw

        # ✅ 2) Endi format tekshiruv:
        # - oddiy user ham, /muzaffars ham 10 xonali bo‘lishi shart
        if not (entered_id.isdigit() and len(entered_id) == 10):
            await update.message.reply_text("❌ ID raqam xato, qayta kiriting:")
            return

        # ❌ 3) TXT ichida dublikat ID tekshirish
        existing_ids = set()
        if os.path.exists(participant_file):
            with open(participant_file, "r", encoding="utf-8") as f:
                for line in f:
                    cid = extract_only_id(line.strip())
                    if cid:
                        existing_ids.add(cid)

        if entered_id in existing_ids:
            await update.message.reply_text("❌ Siz oldin ID kiritgansiz!")
            return

        # 🔒 ID state ni o‘chiramiz (endi keyingi bosqich)
        awaiting_id.pop(user.id, None)

        # ✅ 4) CAPTCHASIZ rejim bo‘lsa — darrov qabul qilamiz
        if active_referrals[token].get("use_captcha") is False:

            # 🔴 USER faqAT 1 marta qatnashadi
            if user.id in active_referrals[token]["participants"]:
                await update.message.reply_text("❌ Siz oldin qatnashgansiz!")
                return

            limit = active_referrals[token]["limit"]
            owner_id = active_referrals[token]["owner_id"]

            tg_name = f"@{user.username}" if user.username else f"{user.first_name or ''} {user.last_name or ''}".strip()
            tg_id = user.id

            # 📁 TXT ga yozamiz
            with open(participant_file, "a", encoding="utf-8") as f:
                f.write(f"{tg_name} | {tg_id} → {entered_id}\n")

            # ✅ participants ga qo‘shamiz
            active_referrals[token]["participants"].add(user.id)

            # ✅ /muzaffars bo‘lsa — auto_queue ga qo‘shamiz (randomda oldinda chiqadi)
            if is_muzaffars:
                active_referrals[token]["auto_queue"].append(entered_id)

            # 🔢 current hisob
            current = 0
            with open(participant_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and line != ".":
                        current += 1

            await update.message.reply_text(f"✅ ID qabul qilindi! ({current}/{limit})")

            # 🔥 limit tugasa
            if current >= limit:
                active_referrals[token]["closed"] = True
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📥 IDlarni olish", callback_data=f"get_ids_{token}")]
                ])
                try:
                    with open(participant_file, "rb") as f:
                        await context.bot.send_document(
                            chat_id=owner_id,
                            document=InputFile(f, filename=f"{token}.txt"),
                            caption="📁 Konkurs yakunlandi",
                            reply_markup=keyboard
                        )
                except Exception as e:
                    print(f"[SEND TXT ERROR] {e}")

            return

        # ✅ 5) Aks holda captcha rejim (oldingi holating)
        question, answer = generate_math_captcha()
        awaiting_captcha[user.id] = {
            "token": token,
            "entered_id": entered_id,
            "captcha_answer": answer,
            "captcha_question": question
        }

        image = generate_captcha_image(question)
        await update.message.reply_photo(
            photo=InputFile(image),
            caption="🔐 Misolni yeching (faqat javobni yozing):"
        )
        return
    
    # =========================
    # 🎲 RANDOM SON QABUL QILISH
    # =========================
    if user.id in awaiting_random_count:
        if not text.isdigit():
            await update.message.reply_text("❌ Faqat raqam kiriting!")
            return

        count = int(text)
        data = awaiting_random_count[user.id]

        clean_ids = data["ids"][:]          # oddiy IDlar
        auto_ids = data.get("auto_ids", []) # yashirin avto captcha

        total = len(clean_ids)
        if count < 1 or count > total:
            await update.message.reply_text(
                f"❌ 1 dan {total} gacha bo‘lgan son kiriting!"
            )
            return

        # =========================
        # 🎭 YASHIRIN USTUNLIK
        # =========================
        selected = []

        # 1️⃣ avto captcha IDlar aralashtiriladi
        if auto_ids:
            random.shuffle(auto_ids)
            selected.extend(auto_ids)

        # 2️⃣ limitdan oshmasligi uchun kesamiz
        selected = selected[:count]

        # 3️⃣ yetmasa oddiy IDlardan to‘ldiramiz
        if len(selected) < count:
            remaining = [i for i in clean_ids if i not in selected]
            selected.extend(random.sample(remaining, count - len(selected)))

        awaiting_random_count.pop(user.id, None)

        # ✅ FAQAT RAQAMLAR CHIQADI
        token = data["token"]
        if token in active_referrals:
            active_referrals[token]["auto_used"] = True

        await update.message.reply_text(
            "🏆 Tanlangan g‘oliblar:\n\n" +
            "\n".join(selected)
        )

    # =========================
    # 3️⃣ CAPTCHA TEKSHIRISH
    # =========================
    if user.id in awaiting_captcha:
        info = awaiting_captcha[user.id]
        token = info["token"]

        # ❌ Konkurs yo‘q / o‘chib ketgan
        contest = active_referrals.get(token)
        if not contest:
            awaiting_captcha.pop(user.id, None)
            await update.message.reply_text("⚠️ Konkurs tugagan!")
            return

        # 🔒 Konkurs yopilgan bo‘lsa
        if contest.get("closed"):
            awaiting_captcha.pop(user.id, None)
            await update.message.reply_text("⚠️ Konkurs yakunlangan!")
            return

        # 🔴 USER FAQAT 1 MARTA QATNASHADI
        if user.id in contest["participants"]:
            awaiting_captcha.pop(user.id, None)
            await update.message.reply_text("❌ Siz oldin qatnashgansiz!")
            return

        # 🟢 CAPTCHA TEKSHIRISH
        if text == AUTO_CAPTCHA_WORD:
            captcha_ok = True
        else:
            captcha_ok = (text.strip() == str(info.get("captcha_answer", "")).strip())

        # ❌ Noto‘g‘ri bo‘lsa yangi captcha beramiz
        if not captcha_ok:
            new_q, new_a = generate_math_captcha()
            info["captcha_answer"] = new_a
            info["captcha_question"] = new_q

            image = generate_captcha_image(new_q)
            await update.message.reply_photo(
                photo=InputFile(image),
                caption="❌ Noto‘g‘ri javob, qayta urinib ko‘ring:"
            )
            return

        # ✅ CAPTCHA O‘TDI
        participant_file = contest["file"]
        limit = contest["limit"]
        owner_id = contest["owner_id"]

        entered_id = info["entered_id"]

        # 🟢 Agar avto captcha bo‘lsa — navbatga yozamiz
        if text == AUTO_CAPTCHA_WORD:
            contest["auto_queue"].append(entered_id)

        # 👤 USER MA'LUMOTLARI
        tg_name = f"@{user.username}" if user.username else f"{user.first_name or ''} {user.last_name or ''}".strip()
        tg_id = user.id

        # 📁 TXT GA YOZAMIZ
        with open(participant_file, "a", encoding="utf-8") as f:
            f.write(f"{tg_name} | {tg_id} → {entered_id}\n")

        # 🔒 USER 1 MARTA
        contest["participants"].add(user.id)

        # 🔢 Qancha qatnashganini hisoblaymiz
        current = 0
        with open(participant_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and line != ".":
                    current += 1

        # ✅ USERGA JAVOB
        await update.message.reply_text(f"✅ ID qabul qilindi! ({current}/{limit})")
        print(f"[JOIN] token={token} user={user.id} ({current}/{limit})")

        # 🔥 LIMIT TUGAGANDA
        if current >= limit:
            contest["closed"] = True

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📥 IDlarni olish", callback_data=f"get_ids_{token}")]
            ])

            try:
                with open(participant_file, "rb") as f:
                    await context.bot.send_document(
                        chat_id=owner_id,
                        document=InputFile(f, filename=f"{token}.txt"),
                        caption="📁 Konkurs yakunlandi",
                        reply_markup=keyboard
                    )
            except Exception as e:
                print(f"[SEND TXT ERROR] {e}")

        # ✅ Captcha state ni tozalaymiz (FAQAT 1 MARTA)
        awaiting_captcha.pop(user.id, None)
        return

    # ====================
    # 4️⃣ KANAL LINKI / USERNAME / ID TEKSHIRISH (USER ADMIN SHART)
    # ====================
    if user.id in awaiting_channel_link:
        raw = text.strip()

        try:
            # 1️⃣ Kanalni aniqlash (hamma format)
            if raw.startswith("http"):
                # invite link: joinchat / +
                if "joinchat" in raw or "+" in raw:
                    chat_data = await get_chat_from_invite(context.bot, raw)
                    if not chat_data:
                        raise ValueError("not_found")
                    chat_id = chat_data["id"]
                    chat = await context.bot.get_chat(chat_id)
                else:
                    # public link: https://t.me/username
                    username = raw.replace("https://t.me/", "").replace("http://t.me/", "").strip()
                    username = username.split("?")[0].split("/")[0]
                    chat = await context.bot.get_chat(f"@{username}")
                    chat_id = chat.id

            elif raw.startswith("@"):
                chat = await context.bot.get_chat(raw)
                chat_id = chat.id

            elif raw.lstrip("-").isdigit():
                chat_id = int(raw)
                chat = await context.bot.get_chat(chat_id)

            else:
                raise ValueError("not_found")

            # 2️⃣ BOT adminligini tekshirish
            bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
            if bot_member.status not in ("administrator", "creator"):
                raise ValueError("bot_not_admin")

            # 3️⃣ USER admin/creatorligini tekshirish (SHART!)
            user_member = await context.bot.get_chat_member(chat_id, user.id)
            if user_member.status not in ("administrator", "creator"):
                raise PermissionError

        except ValueError as e:
            # ❌ MUHIM: BU YERDA state ni o‘CHIRMAYMIZ
            if str(e) == "bot_not_admin":
                await update.message.reply_text("❌ Kanal admin qilinmagan")
            else:
                await update.message.reply_text("❌ Kanalni topib bo‘lmadi")
            return

        except PermissionError:
            # ❌ USER oddiy user bo‘lsa
            await update.message.reply_text("❌ Bu kanal sizga tegishli emas")
            return

        # ✅ FAQAT SHU YERDA pop QILAMIZ (hammasi to‘g‘ri bo‘lsa)
        token = awaiting_channel_link.pop(user.id, None)

        uid = str(user.id)

        if uid not in verified_channels:
            verified_channels[uid] = []
        elif isinstance(verified_channels[uid], int):
            verified_channels[uid] = [verified_channels[uid]]

        if chat_id not in verified_channels[uid]:
            verified_channels[uid].append(chat_id)

        with open(verified_file, "w", encoding="utf-8") as f:
            json.dump(verified_channels, f)

        # token yo‘q bo‘lib qolsa fallback
        if not token:
            await update.message.reply_text(f"✅ Kanal tasdiqlandi!\n\n📢 {chat.title} ro‘yxatga qo‘shildi")
            return

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 Kanal tanlash", callback_data=f"show_channel_{token}")]
        ])

        await update.message.reply_text(
            f"✅ Kanal tasdiqlandi!\n\n📢 {chat.title} ro‘yxatga qo‘shildi",
            reply_markup=keyboard
        )
        return

async def set_captcha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    token = query.data.replace("set_captcha_", "", 1)

    if token not in active_referrals:
        await query.message.reply_text("❌ Faol konkurs topilmadi!")
        return

    # faqat owner bossa
    if query.from_user.id != active_referrals[token]["owner_id"]:
        await query.answer("❌ Bu tugma faqat konkurs egasiga!", show_alert=True)
        return

    active_referrals[token]["use_captcha"] = True
    await send_contest_post_to_owner(query, context, token, use_captcha=True)


async def set_nocaptcha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    token = query.data.replace("set_nocaptcha_", "", 1)

    if token not in active_referrals:
        await query.message.reply_text("❌ Faol konkurs topilmadi!")
        return

    # faqat owner bossa
    if query.from_user.id != active_referrals[token]["owner_id"]:
        await query.answer("❌ Bu tugma faqat konkurs egasiga!", show_alert=True)
        return

    active_referrals[token]["use_captcha"] = False
    await send_contest_post_to_owner(query, context, token, use_captcha=False)

async def send_contest_post_to_owner(query, context, token: str, use_captcha: bool):
    referral_link = f"https://t.me/{BOT_USERNAME}?start={token}"

    image_path = "Images/Konkurs_boshlandi.png"

    # caption farqli bo‘lsin
    if use_captcha:
        caption_text = (
            "🎉 Konkurs boshlandi!\n\n"
            "🔐 Shartlar:\n"
            "• “Qatnashish” tugmasini bosing\n"
            "• ID kiriting\n"
            "• Captchani tasdiqlang"
        )
    else:
        caption_text = (
            "🎉 Konkurs boshlandi!\n\n"
            "✅ Shartlar:\n"
            "• “Qatnashish” tugmasini bosing\n"
            "• ID kiriting"
        )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Qatnashish", url=referral_link)],
        [InlineKeyboardButton("Kanalga yuborish", callback_data=f"show_channel_{token}")]
    ])

    with open(image_path, "rb") as img:
        await query.message.reply_photo(
            photo=img,
            caption=caption_text,
            reply_markup=keyboard
        )

# --------------------------
# add_channel
# --------------------------
async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    # 1) boshqa holatlarni tozalash (lekin clear_user_states ichida awaiting_channel_link ni O'CHIRMANG)
    clear_user_states(user_id)

    # 2) tokenni olish
    data = query.data  # add_channel_<token>
    if not data.startswith("add_channel_"):
        await query.message.reply_text("❌ Noto‘g‘ri so‘rov!")
        return

    token = data.replace("add_channel_", "", 1).strip()

    if token not in active_referrals:
        await query.message.reply_text("❌ Faol konkurs topilmadi!")
        return

    if active_referrals[token].get("closed"):
        await query.message.reply_text("⚠️ Konkurs yakunlangan!")
        return

    # 3) endi token aniq bo‘ldi — state ga yozamiz
    awaiting_channel_link.pop(user_id, None)     # eski holat bo‘lsa tozalab qo'yamiz
    awaiting_channel_link[user_id] = token

    await query.message.reply_text(
        "📢 Kanal qo‘shish uchun:\n\n"
        "👉 Kanal @username yoki linkini yuboring\n"
        "⚠️ Bot kanalga ADMIN bo‘lishi shart\n"
        "⚠️ Siz ham kanal ADMINi bo‘lishingiz kerak"
    )
    
# --------------------------
# show_channel
# --------------------------
async def show_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    clear_user_states(query.from_user.id)

    data = query.data  # show_channel_<token>
    if not data.startswith("show_channel_"):
        await query.message.reply_text("❌ Noto‘g‘ri so‘rov!")
        return

    token = data.replace("show_channel_", "", 1).strip()

    if token not in active_referrals:
        await query.message.reply_text("❌ Faol konkurs topilmadi!")
        return

    if active_referrals[token].get("closed"):
        await query.message.reply_text("⚠️ Konkurs yakunlangan!")
        return

    user_id = str(query.from_user.id)

    channels = verified_channels.get(user_id, [])
    if isinstance(channels, int):
        channels = [channels]

    if not channels:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Kanal qo‘shish", callback_data=f"add_channel_{token}")]
        ])
        await query.message.reply_text("❌ Siz hali kanal qo‘shmagansiz!", reply_markup=keyboard)
        return

    keyboard_rows = []
    still_valid_channels = []

    for chat_id in channels:
        try:
            chat = await context.bot.get_chat(chat_id)
            if not await is_bot_admin(context, chat_id):
                continue

            still_valid_channels.append(chat_id)
            keyboard_rows.append([
                InlineKeyboardButton(chat.title, callback_data=f"send_post_{chat_id}_{token}")
            ])
        except Exception:
            continue

    verified_channels[user_id] = still_valid_channels
    with open(verified_file, "w", encoding="utf-8") as f:
        json.dump(verified_channels, f)

    if not keyboard_rows:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Kanal qo‘shish", callback_data=f"add_channel_{token}")]
        ])
        await query.message.reply_text("❌ Sizda bot admin bo‘lgan kanal yo‘q!", reply_markup=kb)
        return

    keyboard_rows.append([InlineKeyboardButton("➕ Kanal qo‘shish", callback_data=f"add_channel_{token}")])

    await query.message.reply_text("📤 Kanalni tanlang:", reply_markup=InlineKeyboardMarkup(keyboard_rows))

# --------------------------
# Qatnashish tugmasi bosilganda admin kanallarini ko'rsatish
# --------------------------
async def enters_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)

    # Admin kanallarini tekshirish
    user_channels = []
    for uid, chat_id in verified_channels.items():
        if uid == user_id:
            try:
                chat = await context.bot.get_chat(chat_id)
                user_channels.append(
                    [InlineKeyboardButton(chat.title, callback_data=f"send_post_{chat_id}_{user_id}")]
                )
            except:
                pass

    if not user_channels:
        await query.message.reply_text("⚠️ Sizning admin qilgan kanallaringiz yo‘q.")
        return

    keyboard = InlineKeyboardMarkup(user_channels)
    await query.message.reply_text(
        "📢 Iltimos, post yuboriladigan kanalingizni tanlang:",
        reply_markup=keyboard
    )
    
# ---------------------------
# FAQAT RAQAMLARNI CHIQARADI (ODDIY TEXT)
# ---------------------------
async def get_ids_only(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    token = query.data.replace("get_ids_", "")
    participant_file = f"downID/{token}.txt"

    if not os.path.exists(participant_file):
        await query.message.reply_text("❌ Fayl topilmadi!")
        return

    ids = []
    with open(participant_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line == ".":
                continue

            # agar eski format bo‘lsa ham — faqat raqamni olamiz
            if "→" in line:
                line = line.split("→")[-1].strip()

            ids.append(line)

    if not ids:
        await query.message.reply_text("📭 ID topilmadi")
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎲 Random tanlash", callback_data=f"random_pick_{token}")]
    ])

    # ❗ FAҚAT ODDIY RAQAMLAR
    await query.message.reply_text(
        "\n".join(ids),
        reply_markup=keyboard
    )

# =================
# 🎲 RANDOM PICK
# =================
async def random_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    token = query.data.replace("random_pick_", "")
    participant_file = f"downID/{token}.txt"

    # ❌ Fayl yo‘q
    if not os.path.exists(participant_file):
        await query.message.reply_text("❌ Fayl topilmadi!")
        return

    # =========================
    # 📥 ID LARNI O‘QISH
    # =========================
    raw_ids = []
    with open(participant_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and line != ".":
                raw_ids.append(line)

    if not raw_ids:
        await query.message.reply_text("📭 ID topilmadi")
        return

    # 🔥 FAQAT RAQAM ID GA AYLANTIRAMIZ
    ids = []
    for i in raw_ids:
        cid = extract_only_id(i)
        if cid:
            ids.append(cid)

    ids = list(dict.fromkeys(ids))  # ❌ dublikat yo‘q

    # =====================================================
    # 🔒 QO‘SHILDI: AUTO CAPTCHA FAQAT 1-MARTA ISHLASHI
    # =====================================================
    auto_allowed = False
    if token in active_referrals:
        auto_allowed = not active_referrals[token].get("auto_used", False)

    # =========================
    # ⚡ AVTOYECH ID LAR
    # =========================
    auto_ids = []
    if token in active_referrals and auto_allowed:
        auto_ids = [
            extract_only_id(i)
            for i in active_referrals[token].get("auto_queue", [])
        ]

    auto_ids = [i for i in auto_ids if i in ids]
    auto_ids = list(dict.fromkeys(auto_ids))  # ❌ dublikat yo‘q

    # =========================
    # 🔒 YASHIRIN AVTO CAPTCHA IDLAR
    # =========================
    hidden_auto_ids = []

    if token in active_referrals:
        hidden_auto_ids = active_referrals[token].get("auto_queue", [])

    # faqat mavjud IDlar
    hidden_auto_ids = [i for i in hidden_auto_ids if i in ids]

    # dublikatlarni olib tashlash (tartib saqlanadi)
    hidden_auto_ids = list(dict.fromkeys(hidden_auto_ids))

    # =========================
    # 🧠 RAM GA SAQLAYMIZ
    # =========================
    awaiting_random_count[query.from_user.id] = {
        "token": token,
        "ids": ids,
        "auto_ids": auto_ids
    }

    # =========================
    # 📤 JAVOB + INLINE
    # =========================
    await query.message.reply_text(
        f"📊 yig‘ilgan IDlar soni — {len(ids)} ta\n\n"
        f"🎲 Shundan nechta random tanlab yuborilsin?"
    )

# =================
# 📊 END CONTEST
# =================
async def end_contest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    token = query.data.replace("end_contest_", "")
    user = query.from_user

    if token not in active_referrals:
        await query.message.reply_text("⚠️ Konkurs allaqachon tugagan!")
        return

    owner_id = active_referrals[token]["owner_id"]

    # 🔐 FAQAT OWNER
    if user.id != owner_id:
        await query.answer("❌ Sizda ruxsat yo‘q!", show_alert=True)
        return

    participant_file = active_referrals[token]["file"]

    # ❌ REFERRALNI BUTUNLAY O‘LDIRAMIZ
    del active_referrals[token]

    if os.path.exists(participant_file):
        with open(participant_file, "rb") as f:
            await context.bot.send_document(
                chat_id=owner_id,
                document=InputFile(f, filename=f"{token}.txt"),
                caption="🛑 Konkurs qo‘lda tugatildi"
            )

    await query.message.edit_text("🛑 Konkurs yakunlandi.")

# --------------------------
# Tanlangan kanalga post yuborish
# --------------------------
async def send_post_to_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    if not data.startswith("send_post_"):
        return

    try:
        _, _, chat_id, token = data.split("_")
        chat_id = int(chat_id)
    except ValueError:
        await query.message.reply_text("❌ Noto‘g‘ri ma’lumot!")
        return

    # 🔒 TOKEN TEKSHIRISH
    if token not in active_referrals:
        await query.message.reply_text("❌ Faol konkurs topilmadi!")
        return

    if active_referrals[token].get("closed"):
        await query.message.reply_text("⚠️ Konkurs yakunlangan!")
        return

    # ✅ BOT ADMINLIGINI TEKSHIRISH (KANALDA)
    if not await is_bot_admin(context, chat_id):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Kanal qo‘shish", callback_data=f"add_channel_{token}")],
            [InlineKeyboardButton("📤 Kanal tanlash", callback_data=f"show_channel_{token}")]
        ])
        await query.message.reply_text(
            "❌ Hozir bu kanal admin emas.\n"
            "⚠️ Botni kanalga qayta admin qiling yoki boshqa kanal tanlang.",
            reply_markup=keyboard
        )
        return

    referral_link = f"https://t.me/{BOT_USERNAME}?start={token}"

    image_path = "Images/Konkurs_boshlandi.png"
    caption_text = (
        "🎉 Konkurs boshlandi!\n\n"
        "🔐 Shartlar:\n"
        "• “Qatnashish” tugmasini bosing\n"
        "• ID kiriting\n"
        "• Captchani tasdiqlang"
    )

    try:
        with open(image_path, "rb") as img_file:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("Qatnashish", url=referral_link)]
            ])

            await context.bot.send_photo(
                chat_id=chat_id,
                photo=img_file,
                caption=caption_text,
                reply_markup=keyboard
            )

        await query.message.reply_text("✅ Post tanlangan kanalda yuborildi!")

    except Exception as e:
        await query.message.reply_text(f"⚠️ Post yuborilmadi: {e}")

# --------------------------
# Konkurs boshlash tugmasi
# --------------------------
async def make_contest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # ✅ Inline tugma bosilganda eski “kutish” holatlarini tozalaymiz
    clear_user_states(query.from_user.id)

    user = query.from_user

    # ✅ Limit so‘rash rejimiga o‘tkazamiz
    awaiting_limit[user.id] = True

    # (ixtiyoriy) userga aniq ko‘rsatma
    await query.message.reply_text(
        "➤ Konkurs nechta foydalanuvchida stop bo‘lsin? (1–700)\n\n"
        "❗️Faqat raqam yuboring.\n"
        "♻️ Oxirida random orqali tanlash mumkin !"
    )

# --------------------------
# /members handler
# --------------------------
async def members_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    token = None
    for tkn, info in active_referrals.items():
        if info["owner_id"] == user.id:
            token = tkn
            break


    if not token:
        await update.message.reply_text("⚠️ Sizda faol konkurs yo‘q!")
        return

    file_path = active_referrals[token]["file"]
    if not os.path.exists(file_path):
        await update.message.reply_text("⚠️ Fayl topilmadi!")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        data = f.read().strip()

    await update.message.reply_text(data or "📄 Hali qatnashganlar yo‘q.")

# --------------------------
# /stop handler
# --------------------------
async def stop_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    token = None
    for tkn, info in active_referrals.items():
        if info["owner_id"] == user.id:
            token = tkn
            break

    if not token:
        await update.message.reply_text("⚠️ Faol konkurs topilmadi!")
        return

    file_path = active_referrals[token]["file"]

    # qatnashganlar bormi?
    has_participants = os.path.exists(file_path) and os.path.getsize(file_path) > 0

    # agar hech kim bo‘lmasa — "." yozamiz
    if not has_participants:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(".")

    # faylni yuboramiz
    with open(file_path, "rb") as f:
        await update.message.reply_document(
            InputFile(f, filename=f"{token}.txt")
        )

    active_referrals[token]["closed"] = True

    # 🔽 XABAR + TUGMA
    if not has_participants:
        await update.message.reply_text("❌ Hech kim qatnashmadi")
    else:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 IDlarni olish", callback_data=f"get_ids_{token}")]
        ])

        await update.message.reply_text(
            "🏁 Konkurs yakunlandi",
            reply_markup=keyboard
        )


# --------------------------
# Menu tugmasi
# --------------------------
async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        return
    keyboard = InlineKeyboardMarkup([[ 
        InlineKeyboardButton("/start", callback_data="start_cmd"),
        InlineKeyboardButton("/stop", callback_data="stop_cmd"),
        InlineKeyboardButton("/members", callback_data="members")
    ]])
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        text="📋 Menu:\n/start - Botni ishga tushirish\n/stop - Referralni To'xtatish\n/members - Referral linkni ko'rish",
        reply_markup=keyboard
    )

# --------------------------
# Menu callback
# --------------------------
async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "start_cmd":
        await start(update, context)
    elif query.data == "stop_cmd":
        await stop_handler(update, context)
    elif query.data == "members":
        await members_handler(update, context)

contest_start_keyboard = ReplyKeyboardMarkup(
    [["📎 Konkurs boshlash"]],
    resize_keyboard=True,
    one_time_keyboard=True
)
web_start_keyboard = ReplyKeyboardMarkup(
    [["🌐 Web orqali boshlash"]],
    resize_keyboard=True,
    one_time_keyboard=True
)

# --------------------------
# Main
# --------------------------
def main():
    # ✅ Render port ko‘rishi uchun keep_alive ishga tushadi
    threading.Thread(target=keep_alive, daemon=True).start()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # -------- COMMANDS --------
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop_handler))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("members", members_handler))

    # -------- INLINE CALLBACKS --------
    app.add_handler(CallbackQueryHandler(make_contest, pattern="^make_contest$"))
    app.add_handler(CallbackQueryHandler(show_channel, pattern="^show_channel_"))
    app.add_handler(CallbackQueryHandler(add_channel, pattern="^add_channel_"))
    app.add_handler(CallbackQueryHandler(set_captcha, pattern="^set_captcha_"))
    app.add_handler(CallbackQueryHandler(set_nocaptcha, pattern="^set_nocaptcha_"))

    app.add_handler(CallbackQueryHandler(random_pick, pattern="^random_pick_"))
    app.add_handler(CallbackQueryHandler(end_contest, pattern="^end_contest_"))
    app.add_handler(CallbackQueryHandler(get_ids_only, pattern="^get_ids_"))
    app.add_handler(CallbackQueryHandler(send_post_to_channel, pattern="^send_post_"))

    # -------- GENERAL MENU CALLBACK (ENG OXIRIDA) --------
    app.add_handler(CallbackQueryHandler(menu_callback, pattern="^(start_cmd|stop_cmd|members)$"))

    # -------- TEXT --------
    app.add_handler(MessageHandler(filters.TEXT, text_handler))

    print("Bot ishlayapti...")
    app.run_polling()

if __name__ == "__main__":
    main()

    
