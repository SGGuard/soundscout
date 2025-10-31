import os
import yt_dlp
import requests
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- Загружаем .env ---
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

# --- Поиск видео на YouTube ---
def search_youtube(query):
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "part": "snippet",
        "q": query,
        "key": YOUTUBE_API_KEY,
        "maxResults": 1,
        "type": "video"
    }

    response = requests.get(url, params=params)
    data = response.json()

    if "items" not in data or not data["items"]:
        return None

    item = data["items"][0]
    video_id = item["id"]["videoId"]
    title = item["snippet"]["title"]
    link = f"https://www.youtube.com/watch?v={video_id}"

    return {"title": title, "link": link}

# --- Модуль загрузки аудио ---
def download_audio(url, output_dir="downloads"):
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "%(title)s.%(ext)s")

    strategies = [
        # 1️⃣ стандартный способ
        {
            "format": "bestaudio/best",
            "outtmpl": output_path,
            "quiet": True,
            "noprogress": True,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        },
        # 2️⃣ webmusic client (обход SABR)
        {
            "format": "bestaudio/best",
            "outtmpl": output_path,
            "quiet": True,
            "noprogress": True,
            "http_headers": {"User-Agent": "Mozilla/5.0 (Music YouTube Client)"},
            "extractor_args": {"youtube": {"player_client": ["webmusic"]}},
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        },
        # 3️⃣ fallback с generic extractor (на крайний случай)
        {
            "format": "bestaudio/best",
            "outtmpl": output_path,
            "quiet": True,
            "noprogress": True,
            "geo_bypass": True,
            "force_generic_extractor": True,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        }
    ]

    for opts in strategies:
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                base, _ = os.path.splitext(filename)
                mp3_path = f"{base}.mp3"
                if os.path.exists(mp3_path):
                    return mp3_path
        except Exception as e:
            print(f"⚠️ Ошибка при попытке загрузки: {e}")

    return None

# --- Telegram обработчики ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎧 Привет! Отправь название песни — я найду и скачаю её для тебя!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    if not query:
        await update.message.reply_text("⚠️ Введи название трека.")
        return

    await update.message.reply_text("🔎 Ищу трек...")

    video = search_youtube(query)
    if not video:
        await update.message.reply_text("❌ Не удалось найти трек на YouTube.")
        return

    await update.message.reply_text(f"🎶 Нашёл: {video['title']}\n⏳ Загружаю аудио...")

    audio_file = download_audio(video["link"])
    if not audio_file or not os.path.exists(audio_file):
        await update.message.reply_text("⚠️ Не удалось скачать этот трек. Попробуй другой запрос.")
        return

    try:
        await update.message.reply_audio(audio=open(audio_file, "rb"), title=video["title"])
    except Exception as e:
        await update.message.reply_text(f"⚠️ Ошибка при отправке файла: {e}")
    finally:
        if os.path.exists(audio_file):
            os.remove(audio_file)

# --- Главная функция ---
def main():
    if not BOT_TOKEN:
        print("❌ Ошибка: не найден BOT_TOKEN в .env")
        return

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ SoundScout запущен и готов принимать запросы...")
    app.run_polling()

if __name__ == "__main__":
    main()
