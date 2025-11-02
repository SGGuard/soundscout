"""
SoundScout v4.4
- Telegram бот для скачивания треков с YouTube в MP3
- Кэширование и повторная отправка без повторного скачивания
- Поддержка .env для токенов и API-ключей
- Логирование, стабильность и улучшенный поиск
"""

import os
import re
import hashlib
import tempfile
import shutil
import logging
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

import yt_dlp
import requests
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.request import HTTPXRequest


# ================== CONFIG ==================
BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / "cache"
CACHE_DIR.mkdir(exist_ok=True)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

if not BOT_TOKEN:
    raise SystemExit("❌ BOT_TOKEN не найден. Укажи его в .env")

MAX_MB = 45
MAX_BYTES = MAX_MB * 1024 * 1024

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("SoundScout")


# ================== HELPERS ==================
def normalize(q: str) -> str:
    return re.sub(r"\s+", " ", q.strip().lower())


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    return name.strip()


def cache_path(query: str) -> Path:
    h = hashlib.md5(normalize(query).encode()).hexdigest()
    return CACHE_DIR / f"{h}.mp3"


# ================== CORE ==================
def search_youtube(query: str) -> Optional[dict]:
    """Ищет видео на YouTube и возвращает {title, link}"""
    if not YOUTUBE_API_KEY:
        log.warning("⚠️ Нет YOUTUBE_API_KEY, поиск может быть ограничен")
        return None

    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "part": "snippet",
        "q": query,
        "key": YOUTUBE_API_KEY,
        "maxResults": 1,
        "type": "video",
    }
    response = requests.get(url, params=params)
    data = response.json()
    if "items" not in data or not data["items"]:
        return None

    item = data["items"][0]
    return {
        "title": item["snippet"]["title"],
        "link": f"https://www.youtube.com/watch?v={item['id']['videoId']}",
    }


async def download_track(url: str, query: str) -> Optional[Path]:
    """Скачивает трек с YouTube в MP3"""
    tmp = Path(tempfile.mkdtemp(prefix="snd_"))
    try:
        outtmpl = str(tmp / "%(title)s.%(ext)s")
        ydl_opts = {
            "quiet": True,
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            base, _ = os.path.splitext(filename)
            mp3_path = Path(f"{base}.mp3")

        if mp3_path.exists():
            final = cache_path(query)
            shutil.move(mp3_path, final)
            return final
    except Exception as e:
        log.error(f"Ошибка загрузки: {e}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return None


# ================== COMMANDS ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎧 SoundScout v4.4\n"
        "Отправь название трека — я пришлю MP3 прямо сюда.\n"
        f"Максимальный размер: {MAX_MB} MB."
    )


async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    files = list(CACHE_DIR.glob("*.mp3"))
    total_size = sum(f.stat().st_size for f in files) / 1024 / 1024
    msg = (
        f"📁 Кэш: {len(files)} файлов\n"
        f"💾 Размер: {total_size:.1f} MB\n"
        f"📦 Путь: {CACHE_DIR}"
    )
    await update.message.reply_text(msg)


async def handle_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = (update.message.text or "").strip()
    if not query:
        await update.message.reply_text("⚠️ Введи название трека.")
        return

    cached = cache_path(query)
    if cached.exists():
        log.info(f"Кэш найден: {cached.name}")
        await update.message.reply_audio(
            audio=open(cached, "rb"),
            caption=f"🎶 {cached.stem}",
        )
        return

    await update.message.reply_text("🔎 Ищу трек...")
    video = search_youtube(query)
    if not video:
        await update.message.reply_text("❌ Не удалось найти трек на YouTube.")
        return

    await update.message.reply_text(f"🎶 Нашёл: {video['title']}\n⏳ Загружаю аудио...")
    mp3 = await download_track(video["link"], query)

    if not mp3 or not mp3.exists():
        await update.message.reply_text("⚠️ Ошибка при загрузке. Попробуй другой трек.")
        return

    await update.message.reply_audio(
        audio=open(mp3, "rb"),
        caption=f"🎵 {video['title']}",
    )
    log.info(f"Отправлен: {mp3.name}")


# ================== MAIN ==================
def main():
    log.info("🚀 SoundScout v4.4 запущен")

    req = HTTPXRequest(connect_timeout=30, read_timeout=120)
    app = ApplicationBuilder().token(BOT_TOKEN).request(req).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("info", info))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_query))

    app.run_polling()


if __name__ == "__main__":
    main()
