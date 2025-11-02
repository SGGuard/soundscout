#!/usr/bin/env python3
"""
SoundScout v4.2
- Telegram бот для скачивания треков с YouTube в MP3
- Кэширование и повторная отправка без повторного скачивания
- Корректные имена файлов и метаданные (UTF-8)
- Поддержка .env для токенов и API-ключей
- Логирование и ограничение размера файлов
"""

import os
import re
import hashlib
import tempfile
import shutil
import logging
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv  # ✅ подключаем dotenv

import yt_dlp
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
# Загружаем переменные окружения из .env
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
GENIUS_TOKEN = os.getenv("GENIUS_TOKEN")

if not BOT_TOKEN:
    raise SystemExit("❌ BOT_TOKEN не найден. Укажи его в .env")

BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / "cache"
CACHE_DIR.mkdir(exist_ok=True)

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
    q = re.sub(r"\s+", " ", q.strip().lower())
    q = "".join(c for c in q if c.isalnum() or c in (" ", "-", "_"))
    return q


def sanitize_filename(name: str) -> str:
    """Очищает имя файла от недопустимых символов и кодирует в UTF-8"""
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    name = name.encode("utf-8", errors="ignore").decode("utf-8")
    return name.strip()


def cache_path(query: str) -> Path:
    h = hashlib.md5(normalize(query).encode()).hexdigest()
    return CACHE_DIR / f"{h}.mp3"


def cleanup(p: Path):
    try:
        shutil.rmtree(p)
    except Exception:
        pass


# ================== COMMANDS ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎧 SoundScout v4.2\n"
        "Отправь название трека, и я пришлю MP3 прямо сюда.\n"
        f"Максимальный размер: {MAX_MB} MB."
    )


async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    files = list(CACHE_DIR.glob("*.mp3"))
    total_size = sum(f.stat().st_size for f in files) / 1024 / 1024
    msg = (
        f"📁 Кэш: {len(files)} файлов\n"
        f"💾 Размер: {total_size:.1f} MB\n"
        f"📦 Путь: {CACHE_DIR}\n"
        f"🔊 yt-dlp: {yt_dlp.__version__}"
    )
    await update.message.reply_text(msg)


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает статистику по скачанным трекам"""
    files = list(CACHE_DIR.glob("*.mp3"))
    total_size = sum(f.stat().st_size for f in files)
    await update.message.reply_text(
        f"📊 Статистика:\n"
        f"Файлов в кэше: {len(files)}\n"
        f"Общий размер: {total_size / 1024 / 1024:.1f} MB"
    )


# ================== CORE ==================
async def download_track(query: str) -> Optional[Path]:
    """Ищет и скачивает трек, возвращает путь к MP3"""
    tmp = Path(tempfile.mkdtemp(prefix="snd_"))
    try:
        log.info(f"Ищу: {query}")

        # Поиск YouTube
        ydl_opts_search = {
            "quiet": True,
            "no_warnings": True,
            "format": "bestaudio/best",
            "default_search": "ytsearch5",
            "skip_download": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts_search) as ydl:
            res = ydl.extract_info(query, download=False)
        entries = res.get("entries", [res])
        if not entries:
            return None

        # Выбираем лучший результат
        best = sorted(
            entries,
            key=lambda e: (e.get("view_count") or 0) - abs((e.get("duration") or 0) - 180),
            reverse=True,
        )[0]

        url = best["webpage_url"]
        title = sanitize_filename(best.get("title", "track"))
        artist = sanitize_filename(best.get("uploader", "Unknown"))

        log.info(f"Нашёл: {title} | {url}")

        # Скачивание и конвертация
        outtmpl = str(tmp / "%(title)s.%(ext)s")
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "format": "bestaudio/best",
            "noplaylist": True,
            "outtmpl": outtmpl,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        mp3s = list(tmp.glob("*.mp3"))
        if not mp3s:
            return None

        mp3 = mp3s[0]
        size = mp3.stat().st_size
        if size > MAX_BYTES:
            log.warning(f"Файл слишком большой: {size / 1024 / 1024:.1f} MB")
            return None

        # Переименование и сохранение
        final_name = f"{title}.mp3"
        final_path = cache_path(query)
        final_human = final_path.with_name(final_name)
        shutil.move(str(mp3), str(final_human))
        cleanup(tmp)
        log.info(f"Готово: {final_human}")
        return final_human

    except Exception as e:
        log.error(f"Ошибка при скачивании: {e}")
        cleanup(tmp)
        return None


# ================== MESSAGE HANDLER ==================
async def handle_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = (update.message.text or "").strip()
    if not query:
        await update.message.reply_text("❌ Введите название трека.")
        return

    cache_file = cache_path(query)
    if cache_file.exists():
        log.info(f"Кэш найден: {cache_file.name}")
        title = sanitize_filename(cache_file.stem)
        await update.message.reply_audio(
            audio=open(cache_file, "rb"),
            caption=f"🎵 {title}",
            title=title,
            performer="SoundScout",
        )
        return

    await update.message.reply_text(f"🔍 Шуршу в недрах: {query}")
    mp3 = await download_track(query)

    if not mp3 or not mp3.exists():
        await update.message.reply_text("❌ Не удалось найти трек.")
        return

    title = sanitize_filename(mp3.stem)
    await update.message.reply_audio(
        audio=open(mp3, "rb"),
        caption=f"🎶 {title}",
        title=title,
        performer="SoundScout",
    )
    log.info(f"Отправлен: {mp3.name}")


# ================== MAIN ==================
def main():
    log.info("🚀 SoundScout v4.2 запущен")

    req = HTTPXRequest(connect_timeout=30, read_timeout=120)
    app = ApplicationBuilder().token(BOT_TOKEN).request(req).build()

    # Команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("info", info))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_query))

    app.run_polling()


if __name__ == "__main__":
    main()
