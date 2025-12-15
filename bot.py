import os
import logging
import warnings
import sys
import random

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

def get_main_menu_keyboard():
    """Создает клавиатуру главного меню."""
    keyboard = [
        [InlineKeyboardButton("🌅 Начать смену", callback_data="menu_start_shift")],
        [InlineKeyboardButton("🌇 Завершить смену", callback_data="menu_finish_shift")],
        [
            InlineKeyboardButton("🆘 Мне сейчас тяжело", callback_data="menu_hard_time"),
            InlineKeyboardButton("❓ Помощь / Ситуации", callback_data="menu_help")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, message_text="Чем могу помочь?"):
    """Отправляет или обновляет сообщение с главным меню."""
    keyboard = get_main_menu_keyboard()
    # Если update - это сообщение (команда /menu)
    if update.message:
        await update.message.reply_text(message_text, reply_markup=keyboard)
    # Если update - это callback_query (нажатие кнопки)
    elif update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(message_text, reply_markup=keyboard)

# ========== КОМАНДА /START И /MENU ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start - показывает главное меню."""
    user = update.effective_user
    welcome_text = (
        f"Привет, {user.first_name}! Я твой тихий помощник на смене.\n"
        f"Выбери действие:"
    )
    await show_main_menu(update, context, welcome_text)
    # Очищаем состояние пользователя, если оно было
    context.user_data.clear()

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /menu."""
    await show_main_menu(update, context, "Главное меню:")

# ========== ОБРАБОТЧИК КНОПОК ==========
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_data = context.user_data
    callback_data = query.data
    
    # --- ОБРАБОТКА ГЛАВНОГО МЕНЮ ---
    if callback_data.startswith('menu_'):
        if callback_data == 'menu_start_shift':
            # ВСЕГДА запрашиваем код сотрудника
            await query.edit_message_text(
                "Для начала введи свой персональный код сотрудника:"
            )
            user_data['waiting_for'] = 'employee_code'
            return
            
        elif callback_data == 'menu_finish_shift':
            # Логика завершения смены
            telegram_id = update.effective_user.id
            response = supabase.table("employees").select("*").eq("telegram_id", telegram_id).execute()
            
            if not response.data:
                await query.edit_message_text(
                    "Сначала нужно начать смену!",
                    reply_markup=get_main_menu_keyboard()
                )
                return
            
            # Показываем оценку смены
            keyboard = [
                [InlineKeyboardButton(str(i), callback_data=f"score_{i}") for i in range(1, 6)],
                [InlineKeyboardButton(str(i), callback_data=f"score_{i}") for i in range(6, 11)]
            ]
            await query.edit_message_text(
                "Смена подошла к концу! Оцени её по шкале от 1 до 10:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            user_data['waiting_for'] = 'evening_score'
            user_data['employee_id'] = response.data[0]["id"]
            return
            
        elif callback_data == 'menu_hard_time':
            # Кнопка "Мне сейчас тяжело" - с реальной помощью
            hard_time_practices = [
                "🔹 **Техника 5-4-3-2-1**: Назови 5 вещей, которые видишь, 4 которых касаешься, 3 слышишь, 2 чувствуешь по запаху, 1 на вкус. Помогает вернуться в настоящее.",
                "🔹 **Микроперерыв**: Уйди на 2 минуты в тихое место. Просто постой и подыши. Не нужно ничего решать прямо сейчас.",
                "🔹 **Напиши и выбрось**: Возьми бумажку, напиши всё, что давит, скомкай и выбрось. Символически отпускаешь напряжение.",
                "🔹 **Стакан воды**: Выпей медленно стакан воды, концентрируясь на каждом глотке. Простое действие, которое перезагружает.",
                "🔹 **Заземление**: Поставь обе ступни плотно на пол, почувствуй опору. Ты здесь, ты в безопасности."
            ]
            
            random_help = random.choice(hard_time_practices)
            
            await query.edit_message_text(
                f"Я с тобой. Вот практика, которая может помочь прямо сейчас:\n\n{random_help}\n\n"
                f"Попробуй это, а потом возвращайся к работе. Ты справишься. 💪",
                reply_markup=get_main_menu_keyboard()
            )
            return
            
        elif callback_data == 'menu_help':
            # Кнопка "Помощь / Ситуации"
            await query.edit_message_text(
                "Раздел помощи и карточек ситуаций в разработке...",
                reply_markup=get_main_menu_keyboard()
            )
            return
    
    # --- СТАРАЯ ЛОГИКА ЧЕК-ИНОВ ---
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
        
    # ========== БЛОК УТРЕННЕГО ЧЕК-ИНА С МИКРО-ПРАКТИКОЙ ==========
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
            
            # Список микро-практик
            morning_practices = [
                "Сегодняшний фокус: будь как солнце для гостя — согрей вниманием.",
                "Микро-практика: сделай три глубоких вдоха перед началом смены. Ты на месте.",
                "Настрой на день: найди один момент тишины за барной стойкой и улыбнись.",
                "Практика: поблагодари коллегу за одну мелочь в течение часа.",
                "Сегодня: обращай внимание не на проблему, а на человека перед тобой."
            ]
            random_practice = random.choice(morning_practices)
            
            # Формируем финальное сообщение с практикой
            final_message = (
                f"Настроение '{mood}' сохранено. Хорошей смены! 🍰\n\n"
                f"💡 **Микро-практика на сегодня:**\n"
                f"{random_practice}\n\n"
                f"В конце смены нажми 'Завершить смену' в меню (/menu)"
            )
            # Отправляем ТОЛЬКО сообщение с практикой, НЕ показываем меню
            await query.edit_message_text(text=final_message)
            
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
            
            # Сразу показываем выбор настроения, а НЕ меню
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
            
            # Показываем меню после завершения смены
            await show_main_menu(
                update,
                context,
                "Спасибо за честные ответы! Отдыхай и восстанавливай силы. 🍰\n"
                "Завтра жду снова!"
            )
        except Exception as e:
            logger.error(f"Ошибка при сохранении вечернего чека: {e}")
            await update.message.reply_text(
                "Произошла ошибка при сохранении. Попробуй ещё раз через меню"
            )
        user_data.clear()

# ========== ОСНОВНАЯ ФУНКЦИЯ ==========
def main() -> None:
    """Запуск бота."""
    # Создаем Application с токеном
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Регистрируем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Запускаем бота
    logger.info("Бот запускается...")
    application.run_polling()

if __name__ == '__main__':
    main()
