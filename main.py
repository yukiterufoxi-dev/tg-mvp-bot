# main.py
import asyncio, os, sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, Location
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from dotenv import load_dotenv
import aiosmtplib

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
FROM_EMAIL = os.getenv("FROM_EMAIL", ADMIN_EMAIL)

DATA_DIR = Path("data"); DATA_DIR.mkdir(exist_ok=True)
DB_PATH = Path("storage.db")

SCHEMA = '''CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  username TEXT,
  description TEXT NOT NULL,
  photo_path TEXT NOT NULL,
  lat REAL,
  lon REAL,
  created_at TEXT NOT NULL,
  email_status TEXT NOT NULL
);'''

def db_init():
    with closing(sqlite3.connect(DB_PATH)) as con:
        con.execute(SCHEMA); con.commit()

def db_add_report(user_id, username, description, photo_path, lat, lon, email_status):
    with closing(sqlite3.connect(DB_PATH)) as con:
        con.execute("INSERT INTO reports(user_id, username, description, photo_path, lat, lon, created_at, email_status) VALUES(?,?,?,?,?,?,?,?)",
                    (user_id, username, description, photo_path, lat, lon, datetime.utcnow().isoformat(), email_status))
        con.commit()

def db_last_reports(user_id, limit=5):
    with closing(sqlite3.connect(DB_PATH)) as con:
        cur = con.execute("SELECT id, description, lat, lon, created_at, email_status FROM reports WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit))
        return cur.fetchall()

class ReportFlow(StatesGroup):
    wait_photo = State(); wait_description = State(); wait_location = State()

@dataclass
class ReportDraft:
    photo_path: str|None=None; description: str|None=None; lat: float|None=None; lon: float|None=None

async def send_mail(subject, html_body, to_email, attachment_path:Path|None):
    msg = MIMEMultipart(); msg['From']=FROM_EMAIL; msg['To']=to_email; msg['Subject']=subject
    msg.attach(MIMEText(html_body, 'html', _charset='utf-8'))
    if attachment_path and attachment_path.exists():
        with open(attachment_path,'rb') as f:
            part = MIMEBase('application','octet-stream'); part.set_payload(f.read())
        encoders.encode_base64(part); part.add_header('Content-Disposition', f'attachment; filename="{attachment_path.name}"'); msg.attach(part)
    try:
        await aiosmtplib.send(msg, hostname=SMTP_HOST, port=SMTP_PORT, start_tls=True, username=SMTP_USER, password=SMTP_PASS)
        return 'sent'
    except Exception as e:
        return f'error: {e.__class__.__name__}: {e}'

assert BOT_TOKEN and ADMIN_EMAIL, "Set BOT_TOKEN and ADMIN_EMAIL in .env"
bot = Bot(BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher(storage=MemoryStorage())

def main_kb():
    kb = ReplyKeyboardBuilder(); kb.button(text='Отправить жалобу'); kb.button(text='Мои заявки'); kb.adjust(2)
    return kb.as_markup(resize_keyboard=True)

@dp.message(CommandStart())
async def start(m: Message, state: FSMContext):
    await state.clear()
    await m.answer('Здравствуйте! Нажмите <b>Отправить жалобу</b> и следуйте шагам.', reply_markup=main_kb())

@dp.message(F.text == 'Мои заявки')
async def my_reports(m: Message):
    rows = db_last_reports(m.from_user.id, 10)
    if not rows: return await m.answer('У вас пока нет заявок.')
    lines=['<b>Последние заявки</b>']
    for rid, desc, lat, lon, created, status in rows:
        loc = f' (📍{lat:.5f},{lon:.5f})' if lat and lon else ''
        lines.append(f'#{rid} — {desc[:80]}{loc}\nСтатус отправки: <i>{status}</i>\nДата: {created}')
    await m.answer('\n\n'.join(lines))

@dp.message(F.text == 'Отправить жалобу')
async def start_report(m: Message, state: FSMContext):
    await state.set_state(ReportFlow.wait_photo); await state.update_data(draft=ReportDraft().__dict__)
    await m.answer('Пришлите <b>фото проблемы</b> одним сообщением (как фото, не как файл).')

@dp.message(ReportFlow.wait_photo, F.photo)
async def got_photo(m: Message, state: FSMContext):
    file = await bot.get_file(m.photo[-1].file_id)
    file_path = DATA_DIR / f"{m.from_user.id}_{file.file_unique_id}.jpg"
    await bot.download_file(file.file_path, destination=file_path)
    d = (await state.get_data())['draft']; draft = ReportDraft(**d); draft.photo_path=str(file_path)
    await state.update_data(draft=draft.__dict__)
    await state.set_state(ReportFlow.wait_description)
    await m.answer('Коротко опишите проблему (до 300 символов).')

@dp.message(ReportFlow.wait_photo)
async def need_photo(m: Message): await m.answer('Пожалуйста, отправьте фото.')

@dp.message(ReportFlow.wait_description, F.text)
async def got_desc(m: Message, state: FSMContext):
    d = (await state.get_data())['draft']; draft = ReportDraft(**d); draft.description=m.text.strip()[:300]
    await state.update_data(draft=draft.__dict__)
    kb = ReplyKeyboardBuilder(); kb.button(text='Отправить геопозицию', request_location=True); kb.button(text='Пропустить'); kb.adjust(1,1)
    await state.set_state(ReportFlow.wait_location)
    await m.answer('Прикрепите геопозицию (или нажмите Пропустить).', reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(ReportFlow.wait_location, F.location)
async def got_loc(m: Message, state: FSMContext):
    d = (await state.get_data())['draft']; draft = ReportDraft(**d); loc:Location = m.location
    draft.lat, draft.lon = loc.latitude, loc.longitude; await state.update_data(draft=draft.__dict__)
    await finalize_and_send(m, state)

@dp.message(ReportFlow.wait_location, F.text.casefold() == 'пропустить')
async def skip_loc(m: Message, state: FSMContext): await finalize_and_send(m, state)

async def finalize_and_send(m: Message, state: FSMContext):
    d = (await state.get_data())['draft']; draft = ReportDraft(**d)
    subject = 'Сообщение о нарушении благоустройства'
    place = f"\nКоординаты: {draft.lat:.5f}, {draft.lon:.5f}" if draft.lat and draft.lon else ''
    html = (f'<p>Добрый день! Направляю обращение гражданина.</p>'
            f'<p><b>Описание:</b> {draft.description}</p>'
            f"<p><b>Дата/время:</b> {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>"
            f"<p><b>Отправитель:</b> @{m.from_user.username or m.from_user.id}</p>"
            f"<p><b>Локация:</b> {('см. ниже' if place else 'не указана')}{place}</p>"
            '<p>Фото во вложении.</p>')
    status = await send_mail(subject, html, ADMIN_EMAIL, Path(draft.photo_path))
    db_add_report(m.from_user.id, m.from_user.username, draft.description or '', draft.photo_path or '', draft.lat, draft.lon, status)
    await state.clear(); await m.answer('Спасибо! Обращение отправлено: <b>' + ('успешно' if status=='sent' else status) + '</b>.', reply_markup=main_kb())

async def run():
    db_init(); print('Bot started'); await dp.start_polling(bot)
if __name__ == '__main__':
    asyncio.run(run())
