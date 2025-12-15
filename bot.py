import os
import logging
import warnings
import sys

# ФИКС для Python 3.13+: подменяем отсутствующий модуль imghdr
if sys.version_info >= (3, 13):
    import types
    sys.modules['imghdr'] = types.ModuleType('imghdr')
    sys.modules['imghdr'].what = lambda file, h=None: None
    warnings.filterwarnings('ignore', message='imghdr', category=DeprecationWarning)

# Импорты новой версии PTB (20.7)
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)
from supabase import create_client, Client
from dotenv import load_dotenv

# ========== НАСТРОЙКА ЛОГИРОВАНИЯ ==========
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Загружаем переменные окружения
load_dotenv()

# ========== НАСТРОЙКИ ==========
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not all([SUPABASE_URL, SUPABASE_KEY, TELEGRAM_BOT_TOKEN]):
    logger.error("ОШИБКА: Не все переменные окружения заданы в .env файле!")
    sys.exit(1)

# Подключаемся к Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def ensure_employee(telegram_id: int, employee_code: str) -> tuple:
    """Проверяет и создает/обновляет запись сотрудника в БД."""
    try:
        response = supabase.table("employees").select("*").eq("employee_code", employee_code).execute()
        if response.data:
            employee = response.data[0]
            supabase.table("employees").update({"telegram_id": telegram_id}).eq("id", employee["id"]).execute()
            return employee["id"], employee_code
        else:
            data = {
                "telegram_id": telegram_id,
                "employee_code": employee_code,
                "workplace": "Cake&Breakfast"
            }
            response = supabase.table("employees").insert(data).execute()
            return response.data[0]["id"], employee_code
    except Exception as e:
        logger.error(f"Ошибка при работе с сотрудником: {e}")
        return None, None

# ========== КОМАНДА /START ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await update.message.reply_text(
        f"Привет, {user.first_name}! Я твой тихий помощник на смене.\n"
        f"Для начала введи свой персональный код сотрудника:"
    )
    context.user_data['waiting_for'] = 'employee_code'

# ========== КОМАНДА /FINISH ==========
async def finish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id
    response = supabase.table("employees").select("*").eq("telegram_id", telegram_id).execute()
    
    if not response.data:
        await update.message.reply_text("Сначала нужно зарегистрироваться через команду /start")
        return
    
    keyboard = [
        [InlineKeyboardButton(str(i), callback_data=f"score_{i}") for i in range(1, 6)],
        [InlineKeyboardButton(str(i), callback_data=f"score_{i}") for i in range(6, 11)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Смена подошла к концу! Оцени её по шкале от 1 до 10:",
        reply_markup=reply_markup
    )
    context.user_data['waiting_for'] = 'evening_score'
    context.user_data['employee_id'] = response.data[0]["id"]

# ========== ОБРАБОТЧИК КНОПОК ==========
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_data = context.user_data
    callback_data = query.data
    
    if user_data.get('waiting_for') == 'evening_score' and callback_data.startswith('score_'):
        score = int(callback_data.split('_')[1])
        user_data['evening_score'] = score
        
        mood_keyboard = [
            [
                InlineKeyboardButton("😫 Тяжело", callback_data="mood_bad"),
                InlineKeyboardButton("😐 Нейтрально", callback_data="mood_neutral")
            ],
            [
                InlineKeyboardButton("🙂 Хорошо", callback_data="mood_good"),
                InlineKeyboardButton("🤩 Отлично", callback_data="mood_excellent")
            ]
        ]
        await query.edit_message_text(
            text=f"Оценка {score}/10 принята. Какое настроение после смены?",
            reply_markup=InlineKeyboardMarkup(mood_keyboard)
        )
        user_data['waiting_for'] = 'evening_mood'
        
    elif user_data.get('waiting_for') == 'evening_mood' and callback_data.startswith('mood_'):
        mood_map = {
            'mood_bad': '😫',
            'mood_neutral': '😐', 
            'mood_good': '🙂',
            'mood_excellent': '🤩'
        }
        mood = mood_map.get(callback_data, '😐')
        user_data['evening_mood'] = mood
        
        difficulty_keyboard = [
            [InlineKeyboardButton("Гости", callback_data="diff_guests")],
            [InlineKeyboardButton("Кухня", callback_data="diff_kitchen")],
            [InlineKeyboardButton("Очередь", callback_data="diff_queue")],
            [InlineKeyboardButton("Команда", callback_data="diff_team")],
            [InlineKeyboardButton("Моё состояние", callback_data="diff_self")],
            [InlineKeyboardButton("Всё нормально", callback_data="diff_ok")]
        ]
        await query.edit_message_text(
            text="Выбери главную сложность сегодня:",
            reply_markup=InlineKeyboardMarkup(difficulty_keyboard)
        )
        user_data['waiting_for'] = 'evening_difficulty'
        
    elif user_data.get('waiting_for') == 'evening_difficulty' and callback_data.startswith('diff_'):
        diff_map = {
            'diff_guests': 'Гости',
            'diff_kitchen': 'Кухня',
            'diff_queue': 'Очередь', 
            'diff_team': 'Команда',
            'diff_self': 'Моё состояние',
            'diff_ok': 'Всё нормально'
        }
        difficulty = diff_map.get(callback_data, 'Всё нормально')
        user_data['evening_difficulty'] = difficulty
        
        await query.edit_message_text(
            text="За что ты можешь себя поблагодарить сегодня? Напиши пару слов:"
        )
        user_data['waiting_for'] = 'evening_gratitude'
        
    elif user_data.get('waiting_for') == 'morning_mood' and callback_data.startswith('mood_'):
        mood_map = {
            'mood_bad': '😫',
            'mood_neutral': '😐', 
            'mood_good': '🙂',
            'mood_excellent': '🤩'
        }
        mood = mood_map.get(callback_data, '😐')
        
        try:
            checkin_data = {
                "employee_id": user_data['employee_id'],
                "checkin_type": "morning",
                "mood": mood
            }
            supabase.table("checkins").insert(checkin_data).execute()
            await query.edit_message_text(
                text=f"Настроение '{mood}' сохранено. Хорошей смены! 🍰\n"
                     f"В конце смены напиши /finish"
            )
        except Exception as e:
            logger.error(f"Ошибка при сохранении утреннего чека: {e}")
            await query.edit_message_text(
                text="Произошла ошибка при сохранении. Попробуй ещё раз /start"
            )
        user_data.clear()

# ========== ОБРАБОТЧИК ТЕКСТОВЫХ СООБЩЕНИЙ ==========
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = context.user_data
    message_text = update.message.text
    
    if user_data.get('waiting_for') == 'employee_code':
        employee_code = message_text.strip()
        telegram_id = update.effective_user.id
        employee_id, code = ensure_employee(telegram_id, employee_code)
        
        if employee_id:
            user_data['employee_id'] = employee_id
            user_data['employee_code'] = code
            
            mood_keyboard = [
                [
                    InlineKeyboardButton("😫 Тяжело", callback_data="mood_bad"),
                    InlineKeyboardButton("😐 Нейтрально", callback_data="mood_neutral")
                ],
                [
                    InlineKeyboardButton("🙂 Хорошо", callback_data="mood_good"),
                    InlineKeyboardButton("🤩 Отлично", callback_data="mood_excellent")
                ]
            ]
            await update.message.reply_text(
                f"Код '{code}' принят! Какое у тебя настроение перед сменой?",
                reply_markup=InlineKeyboardMarkup(mood_keyboard)
            )
            user_data['waiting_for'] = 'morning_mood'
        else:
            await update.message.reply_text(
                "Не удалось обработать код. Попробуй ещё раз или обратись к управляющему."
            )
            
    elif user_data.get('waiting_for') == 'evening_gratitude':
        gratitude_text = message_text.strip()
        try:
            checkin_data = {
                "employee_id": user_data['employee_id'],
                "checkin_type": "evening",
                "mood": user_data.get('evening_mood', '😐'),
                "shift_score": user_data.get('evening_score', 5),
                "main_difficulty": user_data.get('evening_difficulty', 'Всё нормально'),
                "gratitude_text": gratitude_text
            }
            supabase.table("checkins").insert(checkin_data).execute()
            await update.message.reply_text(
                "Спасибо за честные ответы! Отдыхай и восстанавливай силы. 🍰\n"
                "Завтра жду снова на /start"
            )
        except Exception as e:
            logger.error(f"Ошибка при сохранении вечернего чека: {e}")
            await update.message.reply_text(
                "Произошла ошибка при сохранении. Попробуй ещё раз /finish"
            )
        user_data.clear()

# ========== ОСНОВНАЯ ФУНКЦИЯ ==========
def main() -> None:
    """Запуск бота."""
    # Создаем Application с токеном
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Регистрируем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("finish", finish))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Запускаем бота
    logger.info("Бот запускается...")
    application.run_polling()

if __name__ == '__main__':
    main()
