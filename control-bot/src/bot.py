import os
import logging
import requests
import psycopg2
from datetime import datetime, time, date
from src.telegram_api import send_telegram_message, create_inline_keyboard

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Временное хранилище для данных при создании задания
user_temp_data = {}

def get_db_connection():
    """Получить соединение с базой данных"""
    DB_HOST = os.getenv('DB_HOST')
    DB_PORT = os.getenv('DB_PORT', '6432')
    DB_NAME = os.getenv('DB_NAME', 'family_bot')
    DB_USER = os.getenv('DB_USER', 'botuser')
    DB_PASSWORD = os.getenv('DB_PASSWORD')
    
    if not all([DB_HOST, DB_USER, DB_PASSWORD]):
        raise ValueError("Database configuration is missing")
    
    DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?sslmode=require"
    return psycopg2.connect(DATABASE_URL)


def send_telegram_callback_answer(callback_query_id, text=None, show_alert=False):
    """Ответ на callback запрос"""
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    if not BOT_TOKEN:
        return False
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
    
    payload = {
        'callback_query_id': callback_query_id
    }
    
    if text:
        payload['text'] = text
    if show_alert:
        payload['show_alert'] = True
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        logger.error("Error answering callback: %s", e)
        return False

def edit_telegram_message(chat_id, message_id, text, reply_markup=None, parse_mode='HTML'):
    """Редактирование сообщения"""
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    if not BOT_TOKEN:
        return False
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
    
    payload = {
        'chat_id': chat_id,
        'message_id': message_id,
        'text': text,
        'parse_mode': parse_mode
    }
    
    if reply_markup:
        payload['reply_markup'] = reply_markup
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        logger.error("Error editing message: %s", e)
        return False

def process_update_sync(update_data):
    """Основная синхронная обработка обновления"""
    try:
        logger.info("Processing update: %s", update_data.keys())
        
        # Обработка сообщений
        if 'message' in update_data:
            return process_message(update_data['message'])
        
        # Обработка callback запросов
        elif 'callback_query' in update_data:
            return process_callback_query(update_data['callback_query'])
        
        else:
            logger.warning("Unknown update type: %s", update_data.keys())
            return True
            
    except Exception as e:
        logger.error("Error in process_update_sync: %s", e)
        return False

def process_message(message):
    """Обработка входящего сообщения"""
    chat_id = message['chat']['id']
    user_id = message['from']['id']
    text = message.get('text', '').strip()
    
    logger.info("Message from %s: %s", user_id, text)
    
    # Команда /start
    if text == '/start':
        return handle_start(chat_id, user_id, message['from'])
    
    # Команда /admin
    elif text == '/admin':
        return handle_admin(chat_id, user_id)
    
    # Команда /tasks
    elif text == '/tasks':
        return handle_tasks(chat_id, user_id)
    
    # Команда /balance
    elif text == '/balance':
        return handle_balance(chat_id, user_id)
    
    # Обработка текстовых сообщений (для создания заданий и управления балансом)
    elif user_id in user_temp_data:
        return handle_user_input(chat_id, user_id, text)
    
    else:
        send_telegram_message(chat_id, "Неизвестная команда. Используйте /start для начала.")
        return True

def process_callback_query(callback_query):
    """Обработка callback запросов"""
    callback_id = callback_query['id']
    user_id = callback_query['from']['id']
    chat_id = callback_query['message']['chat']['id']
    message_id = callback_query['message']['message_id']
    data = callback_query['data']
    
    logger.info("Callback from %s: %s", user_id, data)

    # Callback'ы возврата заданий (ДОБАВЛЯЕМ В НАЧАЛО!)
    if data.startswith('return_task_'):
        return handle_return_task(chat_id, user_id, message_id, data, callback_id)    
    
    # Административные callback'ы
    elif data.startswith('admin_'):
        return handle_admin_callback(chat_id, user_id, message_id, data, callback_id)
    
    elif data.startswith('task_manage_page_') or \
         data.startswith('task_disable_') or \
         data.startswith('task_enable_') or \
         data.startswith('task_delete_') or \
         data.startswith('task_delete_confirm_'):
        return handle_admin_callback(chat_id, user_id, message_id, data, callback_id)

    # Управление балансами
    elif data.startswith('balance_') or data == 'rewards_settings':
        return handle_balance_callback(chat_id, user_id, message_id, data, callback_id)
    
    elif data == 'balance_cancel':
        return handle_child_selection(chat_id, user_id, message_id, data, callback_id)
          
    # Настройка наград
    elif data.startswith('reward_') or data.startswith('rewards_'):
        return handle_rewards_callback(chat_id, user_id, message_id, data, callback_id)
    
    # Выбор ребенка для операций с балансом
    elif data.startswith('child_'):
        return handle_child_selection(chat_id, user_id, message_id, data, callback_id)
    
    # Callback'ы выполнения заданий
    elif data.startswith('complete_'):
        return handle_complete_task(chat_id, user_id, message_id, data, callback_id)
    
    # Callback'ы создания заданий
    elif data.startswith('task_type_') or data.startswith('day_') or data == 'cancel':
        return handle_task_creation_callback(chat_id, user_id, message_id, data, callback_id)
    
    elif data.startswith('task_status_') or data == 'admin_task_status':
        return handle_admin_callback(chat_id, user_id, message_id, data, callback_id)

    # В функции process_callback_query, добавить в блок обработки:
    elif data.startswith('special_child_') or data in ['special_confirm', 'special_confirm_none', 'special_reset']:
        return handle_special_child_selection(chat_id, user_id, message_id, data, callback_id)

    # Callback'ы для выполненных заданий (ДОБАВЛЯЕМ)
    elif data.startswith('completed_page_'):
        return handle_admin_callback(chat_id, user_id, message_id, data, callback_id)
    
    # Callback'ы возврата из раздела выполненных заданий (ДОБАВЛЯЕМ)
    elif data == 'admin_completed_tasks':
        return handle_admin_callback(chat_id, user_id, message_id, data, callback_id)

    else:
        send_telegram_callback_answer(callback_id, "Неизвестная команда")
        return True

def handle_start(chat_id, user_id, user_data):
    """Обработка команды /start"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Проверяем, есть ли пользователь в БД
        cur.execute("SELECT role FROM users WHERE user_id = %s", (user_id,))
        user = cur.fetchone()

        full_name = user_data.get('first_name', 'User')
        username = user_data.get('username')

        if not user:
            # Новый пользователь, регистрируем как ребенка по умолчанию
            cur.execute(
                "INSERT INTO users (user_id, username, full_name, role, balance) VALUES (%s, %s, %s, 'child', 0)",
                (user_id, username, full_name)
            )
            conn.commit()
            message = (
                f"Привет, {full_name}! 🎉\n"
                f"Ты зарегистрирован как ребенок. Ожидай задания от родителей!\n"
                f"Используй /tasks чтобы посмотреть свои текущие задания."
            )
        else:
            role = user[0]
            if role == 'admin':
                message = (
                    f"Добро пожаловать, {full_name}! 👑\n"
                    f"Вы вошли как администратор.\n"
                    f"Используйте /admin для управления системой."
                )
            else:
                balance = get_user_balance(user_id)
                message = (
                    f"С возвращением, {full_name}! 👋\n"
                    f"Используй /tasks чтобы посмотреть свои задания.\n"
                    f"Твой текущий баланс: {balance} баллов."
                )

        send_telegram_message(chat_id, message)
        return True
        
    except Exception as e:
        logger.error("Error in handle_start: %s", e)
        send_telegram_message(chat_id, "❌ Произошла ошибка при регистрации.")
        return False
    finally:
        cur.close()
        conn.close()

def handle_admin(chat_id, user_id):
    """Обработка команды /admin"""
    if not is_admin(user_id):
        send_telegram_message(chat_id, "❌ У вас нет прав администратора.")
        return True

    keyboard = create_inline_keyboard([
        [
            {'text': '➕ Добавить задание', 'callback_data': 'admin_add_task'},
            {'text': '📋 Список заданий', 'callback_data': 'admin_list_tasks'}
        ],
        [
            {'text': '👨‍👩‍👧‍👦 Список детей', 'callback_data': 'admin_list_children'},
            {'text': '📊 Статистика', 'callback_data': 'admin_stats'}
        ],
        [
            {'text': '💰 Управление балансами', 'callback_data': 'balance_management'},
            {'text': '🔄 Выдать ежедневные задания', 'callback_data': 'admin_assign_daily'}
        ],
        [  
            {'text': '✅ Статус выполнения заданий', 'callback_data': 'admin_task_status'},
            {'text': '⚙️ Управление заданиями', 'callback_data': 'admin_manage_tasks'} 
        ],
        [  
            {'text': '🔄 Выполненные задания', 'callback_data': 'admin_completed_tasks'}
        ]        
    ])
    
    send_telegram_message(chat_id, "👑 Панель администратора:", reply_markup=keyboard)
    return True

def handle_admin_callback(chat_id, user_id, message_id, data, callback_id):
    """Обработка административных callback'ов"""
    if not is_admin(user_id):
        send_telegram_callback_answer(callback_id, "❌ У вас нет прав администратора.", show_alert=True)
        return True

    send_telegram_callback_answer(callback_id)
    
    # Обработка кнопки "Назад" из любого раздела
    if data == 'admin_back':
        return handle_admin(chat_id, user_id)
    
    # Основные админские функции
    elif data == 'admin_add_task':
        return start_add_task(chat_id, user_id, message_id)
    elif data == 'admin_list_tasks':
        return list_tasks(chat_id, user_id, message_id)
    elif data == 'admin_list_children':
        return list_children(chat_id, user_id, message_id)
    elif data == 'admin_stats':
        return show_stats(chat_id, user_id, message_id)
    elif data == 'admin_assign_daily':
        return assign_daily_tasks(chat_id, user_id, message_id)
    elif data == 'balance_management':
        return handle_balance_management(chat_id, user_id)
    elif data == 'admin_task_status':
        return show_task_status(chat_id, user_id, message_id)  
    elif data == 'task_status_today':
        return show_task_status(chat_id, user_id, message_id, 'today')
    elif data == 'task_status_week':
        return show_task_status(chat_id, user_id, message_id, 'week')
    elif data == 'task_status_all':
        return show_task_status(chat_id, user_id, message_id, 'all')   
    elif data == 'admin_manage_tasks':
        return show_task_management(chat_id, user_id, message_id)
    elif data.startswith('task_manage_page_'):
        page = int(data.replace('task_manage_page_', ''))
        return show_task_management(chat_id, user_id, message_id, page)

    elif data.startswith('task_disable_'):
        task_id = int(data.replace('task_disable_', ''))
        return disable_task(chat_id, user_id, message_id, task_id)

    elif data.startswith('task_enable_'):
        task_id = int(data.replace('task_enable_', ''))
        return enable_task(chat_id, user_id, message_id, task_id)

    elif data.startswith('task_delete_'):
        task_id = int(data.replace('task_delete_', ''))
        return confirm_delete_task(chat_id, user_id, message_id, task_id)
    elif data.startswith('task_delete_confirm_'):
        task_id = int(data.replace('task_delete_confirm_', ''))
        return delete_task(chat_id, user_id, message_id, task_id)
    elif data == 'admin_completed_tasks':
        return show_completed_tasks(chat_id, user_id, message_id)

    elif data.startswith('completed_page_'):
        page = int(data.replace('completed_page_', ''))
        return show_completed_tasks(chat_id, user_id, message_id, page)           
    
    return True

def start_add_task(chat_id, user_id, message_id):
    """Начало процесса добавления задания"""
    user_temp_data[user_id] = {
        'chat_id': chat_id,
        'message_id': message_id,
        'created_by': user_id,
        'step': 'type'
    }
    
    keyboard = create_inline_keyboard([
        [
            {'text': '📅 Ежедневное', 'callback_data': 'task_type_daily'},
            {'text': '🗓️ Еженедельное', 'callback_data': 'task_type_weekly'}
        ],
        [
            {'text': '⭐ Особое', 'callback_data': 'task_type_special'},
            {'text': '❌ Отмена', 'callback_data': 'cancel'}
        ]
    ])
    
    message = (
        "Выберите тип задания:\n\n"
        "📅 <b>Ежедневное</b> - повторяется каждый день\n"
        "🗓️ <b>Еженедельное</b> - выполняется раз в неделю\n"
        "⭐ <b>Особое</b> - разовое задание с индивидуальным сроком"
    )
    
    edit_telegram_message(chat_id, message_id, message, reply_markup=keyboard)
    return True

def handle_task_creation_callback(chat_id, user_id, message_id, data, callback_id):
    """Обработка callback'ов создания заданий"""
    if data == 'cancel':
        if user_id in user_temp_data:
            del user_temp_data[user_id]
        send_telegram_callback_answer(callback_id)
        edit_telegram_message(chat_id, message_id, "❌ Создание задания отменено.")
        return True
    
    if user_id not in user_temp_data:
        send_telegram_callback_answer(callback_id, "❌ Сессия истекла. Начните заново.", show_alert=True)
        return True
    
    send_telegram_callback_answer(callback_id)
    
    if data.startswith('task_type_'):
        task_type = data.replace('task_type_', '')
        user_temp_data[user_id].update({
            'type': task_type,
            'step': 'title'
        })
        
        edit_telegram_message(chat_id, message_id, 
            "✏️ Введите название задания:\n\n"
            "<i>Например: Сделать уроки, Убраться в комнате</i>"
        )
    
    elif data.startswith('day_'):
        day_map = {
            'day_monday': 'monday', 'day_tuesday': 'tuesday', 'day_wednesday': 'wednesday',
            'day_thursday': 'thursday', 'day_friday': 'friday', 'day_saturday': 'saturday',
            'day_sunday': 'sunday'
        }
        user_temp_data[user_id]['due_day'] = day_map[data]
        user_temp_data[user_id]['step'] = 'due_time'
        
        edit_telegram_message(chat_id, message_id,
            "⏰ Введите время, до которого нужно выполнить задание (в формате ЧЧ:ММ):\n\n"
            "<i>Например: 18:00, 20:30</i>"
        )
    
    return True

def handle_user_input(chat_id, user_id, text):
    """Обработка пользовательского ввода при создании задания и управлении балансом"""
    if user_id not in user_temp_data:
        send_telegram_message(chat_id, "❌ Сессия истекла. Начните заново с /admin")
        return True
    
    user_data = user_temp_data[user_id]
    
    # Обработка ввода для управления балансом
    if 'action' in user_data and user_data['step'] == 'enter_amount':
        try:
            amount = int(text)
            if amount <= 0:
                send_telegram_message(chat_id, "❌ Сумма должна быть положительной. Введите снова:")
                return True
            
            child_id = user_data['child_id']
            action = user_data['action']
            
            if action == 'add_balance':
                success = add_balance(child_id, amount, "Начисление администратором")
                message = f"✅ Начислено {amount} баллов ребенку."
            else:
                success = remove_balance(child_id, amount, "Списание администратором")
                message = f"✅ Списано {amount} баллов у ребенка."
            
            if success:
                # Показываем обновленный баланс
                new_balance = get_user_balance(child_id)
                child_name = get_user_name(child_id)
                message += f"\n\n💳 Новый баланс {child_name}: {new_balance} баллов"
            else:
                message = "❌ Ошибка при изменении баланса."
            
            send_telegram_message(chat_id, message)
            del user_temp_data[user_id]
            
        except ValueError:
            send_telegram_message(chat_id, "❌ Введите корректное число:")
        
        return True
    
    # Обработка ввода для создания заданий
    step = user_data.get('step')
    
    if step == 'title':
        user_data['title'] = text
        user_data['step'] = 'description'
        
        send_telegram_message(chat_id,
            "📝 Введите описание задания (или отправьте '-' если описание не нужно):\n\n"
            "<i>Например: Выполнить домашнюю работу по математике и русскому языку</i>"
        )
    
    elif step == 'description':
        if text != '-':
            user_data['description'] = text
        
        task_type = user_data['type']
        
        if task_type == 'special':
            user_data['step'] = 'special_reward'
            send_telegram_message(chat_id,
                "💰 Введите размер награды (в баллах):\n\n"
                "<i>Например: 50, 100, 200</i>"
            )
        else:
            # Стандартные награды
            default_rewards = get_default_rewards()
            user_data['reward'] = default_rewards[task_type]
            
            if task_type == 'daily':
                user_data['step'] = 'due_time'
                send_telegram_message(chat_id,
                    "⏰ Введите время, до которого нужно выполнить задание (в формате ЧЧ:ММ):\n\n"
                    "<i>Например: 18:00, 20:30</i>"
                )
            else:  # weekly
                user_data['step'] = 'due_day'
                keyboard = create_inline_keyboard([
                    [
                        {'text': 'Понедельник', 'callback_data': 'day_monday'},
                        {'text': 'Вторник', 'callback_data': 'day_tuesday'},
                        {'text': 'Среда', 'callback_data': 'day_wednesday'}
                    ],
                    [
                        {'text': 'Четверг', 'callback_data': 'day_thursday'},
                        {'text': 'Пятница', 'callback_data': 'day_friday'},
                        {'text': 'Суббота', 'callback_data': 'day_saturday'}
                    ],
                    [
                        {'text': 'Воскресенье', 'callback_data': 'day_sunday'},
                        {'text': '❌ Отмена', 'callback_data': 'cancel'}
                    ]
                ])
                send_telegram_message(chat_id, "📅 Выберите день недели для выполнения задания:", reply_markup=keyboard)
    
    elif step == 'special_reward':
        try:
            reward = int(text)
            if reward <= 0:
                raise ValueError
            user_data['reward'] = reward
            user_data['step'] = 'custom_due_date'
            
            send_telegram_message(chat_id,
                "📅 Введите дату и время выполнения (в формате ДД.ММ.ГГГГ ЧЧ:ММ):\n\n"
                "<i>Например: 25.12.2024 18:00</i>"
            )
        except ValueError:
            send_telegram_message(chat_id, "❌ Пожалуйста, введите положительное число:")
    
    elif step == 'due_time':
        try:
            due_time = datetime.strptime(text, '%H:%M').time()
            user_data['due_time'] = due_time
            
            # Сохраняем задание в БД
            if save_task_to_db(user_id):
                send_telegram_message(chat_id, "✅ Задание успешно создано!")
                del user_temp_data[user_id]
            else:
                send_telegram_message(chat_id, "❌ Ошибка при создании задания.")
        
        except ValueError:
            send_telegram_message(chat_id, "❌ Неверный формат времени. Введите в формате ЧЧ:ММ:")
    
    elif step == 'custom_due_date':
        try:
            due_date = datetime.strptime(text, '%d.%m.%Y %H:%M')
            if due_date <= datetime.now():
                send_telegram_message(chat_id, "❌ Дата должна быть в будущем. Введите снова:")
            else:
                user_data['custom_due_date'] = due_date
                
                # Получаем список детей текущего администратора
                children = get_children_for_admin(user_id)
                
                if not children:
                    send_telegram_message(chat_id, 
                        "❌ В системе нет детей для назначения задания.\n"
                        "Задание создано, но не назначено никому.")
                    
                    # Сохраняем задание без назначения
                    if save_task_to_db(user_id, assign_to_children=False):
                        send_telegram_message(chat_id, "✅ Особое задание создано!")
                        del user_temp_data[user_id]
                    else:
                        send_telegram_message(chat_id, "❌ Ошибка при создании задания.")
                    return True
                
                # ЛОГИКА: Если ребенок один - назначаем автоматически
                elif len(children) == 1:
                    child_id, child_name, username, balance = children[0]
                    
                    # Автоматически назначаем единственному ребенку
                    if save_task_to_db(user_id, assign_to_children=True, child_ids=[child_id]):
                        # Отправляем уведомление ребенку
                        task_title = user_data['title']
                        reward = user_data['reward']
                        
                        child_message = (
                            f"⭐ <b>Получено новое особое задание!</b>\n\n"
                            f"Привет, {child_name}! 👋\n\n"
                            f"📋 <b>{task_title}</b>\n"
                            f"💰 Награда: <b>{reward} баллов</b>\n"
                            f"📅 Выполнить до: <b>{due_date.strftime('%d.%m.%Y %H:%M')}</b>\n\n"
                            f"Используй команду /tasks чтобы посмотреть задание!\n"
                            f"Удачи! 💪"
                        )
                        send_telegram_message(child_id, child_message)
                        
                        send_telegram_message(chat_id,
                            f"✅ Особое задание создано и автоматически назначено ребенку:\n"
                            f"👤 <b>{child_name}</b>\n\n"
                            f"Ребенок получил уведомление. 📨"
                        )
                        del user_temp_data[user_id]
                    else:
                        send_telegram_message(chat_id, "❌ Ошибка при создании задания.")
                    return True
                
                else:
                    # Детей двое или более - показываем выбор
                    user_data['step'] = 'select_children'
                    
                    # Создаем клавиатуру для выбора детей
                    keyboard_buttons = []
                    for child_id, child_name, username, balance in children:
                        username_display = f" (@{username})" if username else ""
                        keyboard_buttons.append([
                            {'text': f"👤 {child_name}{username_display}", 'callback_data': f'special_child_{child_id}'}
                        ])
                    
                    # Кнопки для выбора всех/отмены
                    keyboard_buttons.append([
                        {'text': '✅ Выбрать всех', 'callback_data': 'special_child_all'},
                        {'text': '❌ Без назначения', 'callback_data': 'special_child_none'}
                    ])
                    
                    keyboard = create_inline_keyboard(keyboard_buttons)
                    
                    send_telegram_message(chat_id,
                        f"👥 <b>Выберите детей для назначения задания:</b>\n\n"
                        f"У вас <b>{len(children)}</b> детей. Можно выбрать одного, нескольких или всех.\n"
                        f"После выбора нажмите 'Готово'.",
                        reply_markup=keyboard
                    )
        
        except ValueError:
            send_telegram_message(chat_id, "❌ Неверный формат. Введите в формате ДД.ММ.ГГГГ ЧЧ:ММ:")
    
    return True

def save_task_to_db(user_id, assign_to_children=True, child_ids=None):
    """Сохранить задание в базу данных и назначить детям"""
    if user_id not in user_temp_data:
        return False
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        task_data = user_temp_data[user_id]
        
        # Сохраняем задание в tasks
        cur.execute("""
            INSERT INTO tasks 
            (title, description, type, reward, due_time, due_day, custom_due_date, created_by, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE)
            RETURNING task_id
        """, (
            task_data['title'],
            task_data.get('description'),
            task_data['type'],
            task_data['reward'],
            task_data.get('due_time'),
            task_data.get('due_day'),
            task_data.get('custom_due_date'),
            task_data['created_by']
        ))
        
        task_id = cur.fetchone()[0]
        
        # Если это special задание и нужно назначить детям
        if task_data['type'] == 'special' and assign_to_children and child_ids:
            for child_id in child_ids:
                # Для special заданий due_date берется из custom_due_date
                due_date = task_data.get('custom_due_date')
                
                cur.execute("""
                    INSERT INTO assigned_tasks 
                    (task_id, child_id, assigned_date, due_date, is_completed)
                    VALUES (%s, %s, CURRENT_DATE, %s, FALSE)
                """, (task_id, child_id, due_date))
        
        conn.commit()
        return True
        
    except Exception as e:
        logger.error("Error saving task to DB: %s", e)
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()

# ФУНКЦИИ ДЛЯ РАБОТЫ С ЗАДАНИЯМИ

def list_tasks(chat_id, user_id, message_id):
    """Показать список всех заданий"""
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT task_id, title, type, reward, due_time, due_day, is_active
            FROM tasks 
            WHERE created_by = %s 
            ORDER BY type, is_active DESC, task_id
        """, (user_id,))
        
        tasks = cur.fetchall()

        if not tasks:
            edit_telegram_message(chat_id, message_id, "📝 У вас пока нет созданных заданий.")
            return True

        message_text = "📋 <b>Список ваших заданий:</b>\n\n"
        
        for task in tasks:
            task_id, title, task_type, reward, due_time, due_day, is_active = task
            
            status = "✅ Активно" if is_active else "❌ Неактивно"
            type_emoji = "📅" if task_type == 'daily' else "🗓️" if task_type == 'weekly' else "⭐"
            
            message_text += f"{type_emoji} <b>{title}</b>\n"
            message_text += f"   Тип: {task_type}\n"
            message_text += f"   Награда: {reward} баллов\n"
            
            if due_time:
                message_text += f"   Время: {due_time.strftime('%H:%M')}\n"
            if due_day:
                message_text += f"   День: {due_day}\n"
                
            message_text += f"   Статус: {status}\n\n"

        keyboard = create_inline_keyboard([
            [{'text': '🔄 Обновить', 'callback_data': 'admin_list_tasks'}],
            [{'text': '⬅️ Назад', 'callback_data': 'admin_back'}]
        ])

        edit_telegram_message(chat_id, message_id, message_text, reply_markup=keyboard)
        return True
    except Exception as e:
        logger.error("Error listing tasks: %s", e)
        edit_telegram_message(chat_id, message_id, "❌ Ошибка при получении списка заданий.")
        return False
    finally:
        cur.close()
        conn.close()

def list_children(chat_id, user_id, message_id):
    """Показать список детей и их балансы"""
    children = get_children_list()
    
    if not children:
        edit_telegram_message(chat_id, message_id, "👶 В системе пока нет зарегистрированных детей.")
        return True

    message_text = "👨‍👩‍👧‍👦 <b>Список детей:</b>\n\n"
    
    for child in children:
        user_id, username, full_name, balance = child
        username_display = f"(@{username})" if username else ""
        
        message_text += f"👤 <b>{full_name}</b> {username_display}\n"
        message_text += f"   Баланс: {balance} баллов\n"
        message_text += f"   ID: {user_id}\n\n"

    keyboard = create_inline_keyboard([
        [{'text': '🔄 Обновить', 'callback_data': 'admin_list_children'}],
        [{'text': '⬅️ Назад', 'callback_data': 'admin_back'}]
    ])

    edit_telegram_message(chat_id, message_id, message_text, reply_markup=keyboard)
    return True

def show_stats(chat_id, user_id, message_id):
    """Показать статистику"""
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # Общая статистика
        cur.execute("SELECT COUNT(*) FROM users WHERE role = 'child'")
        children_count = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM tasks WHERE created_by = %s", (user_id,))
        tasks_count = cur.fetchone()[0]

        cur.execute("""
            SELECT COUNT(*) FROM assigned_tasks 
            WHERE is_completed = TRUE 
            AND DATE(completed_at) = CURRENT_DATE
        """)
        completed_today = cur.fetchone()[0]

        cur.execute("SELECT SUM(amount) FROM transactions WHERE type = 'task_reward'")
        total_rewards = cur.fetchone()[0] or 0

        message_text = (
            "📊 <b>Статистика системы:</b>\n\n"
            f"👶 Детей в системе: {children_count}\n"
            f"📝 Создано заданий: {tasks_count}\n"
            f"✅ Выполнено сегодня: {completed_today}\n"
            f"💰 Всего выдано баллов: {total_rewards}\n"
        )

        keyboard = create_inline_keyboard([
            [{'text': '🔄 Обновить', 'callback_data': 'admin_stats'}],
            [{'text': '⬅️ Назад', 'callback_data': 'admin_back'}]
        ])

        edit_telegram_message(chat_id, message_id, message_text, reply_markup=keyboard)
        return True
    except Exception as e:
        logger.error("Error showing stats: %s", e)
        edit_telegram_message(chat_id, message_id, "❌ Ошибка при получении статистики.")
        return False
    finally:
        cur.close()
        conn.close()

def assign_daily_tasks(chat_id, user_id, message_id):
    """Выдать ежедневные задания на СЕГОДНЯ"""
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # Получаем активные ежедневные задания
        cur.execute("""
            SELECT task_id, title, due_time, reward FROM tasks 
            WHERE type = 'daily' AND is_active = TRUE AND created_by = %s
        """, (user_id,))
        
        daily_tasks = cur.fetchall()

        if not daily_tasks:
            edit_telegram_message(chat_id, message_id, 
                "❌ Нет активных ежедневных заданий для выдачи.")
            return True

        # Получаем детей
        cur.execute("""
            SELECT user_id, full_name, username FROM users 
            WHERE role = 'child' 
            AND (parent_id = %s OR parent_id IS NULL)
        """, (user_id,))
        
        children = cur.fetchall()

        if not children:
            edit_telegram_message(chat_id, message_id, 
                "❌ В системе нет детей для выдачи заданий.")
            return True

        assigned_count = 0
        today = date.today()
        
        for child_id, child_name, child_username in children:
            for task in daily_tasks:
                task_id, task_title, due_time, task_reward = task
                
                # ВАЖНО: задание на СЕГОДНЯ до due_time
                due_date = datetime.combine(today, due_time)
                
                # Проверяем, не выдано ли уже задание СЕГОДНЯ
                cur.execute("""
                    SELECT assignment_id FROM assigned_tasks 
                    WHERE task_id = %s AND child_id = %s AND assigned_date = CURRENT_DATE
                """, (task_id, child_id))
                
                if not cur.fetchone():
                    # Выдаем задание на СЕГОДНЯ
                    cur.execute("""
                        INSERT INTO assigned_tasks 
                        (task_id, child_id, assigned_date, due_date, is_completed)
                        VALUES (%s, %s, CURRENT_DATE, %s, FALSE)
                    """, (task_id, child_id, due_date))
                    assigned_count += 1
        
        conn.commit()
        
        if assigned_count > 0:
            message = f"✅ Выдано {assigned_count} заданий на СЕГОДНЯ."
        else:
            message = "ℹ️ Все задания на сегодня уже выданы ранее."
        
        edit_telegram_message(chat_id, message_id, message)
        return True
        
    except Exception as e:
        logger.error("Error in assign_daily_tasks: %s", e)
        edit_telegram_message(chat_id, message_id, "❌ Ошибка при выдаче заданий.")
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()

def send_task_notification(child_id, child_name, tasks_details):
    """Отправить уведомление ребенку о новых заданиях"""
    try:
        if len(tasks_details) == 1:
            # Одно задание
            task = tasks_details[0]
            due_time_str = task['due_time'].strftime('%H:%M') if task['due_time'] else "сегодня"
            
            message = (
                f"📅 <b>Получено новое ежедневное задание!</b>\n\n"
                f"Привет, {child_name}! 👋\n\n"
                f"📋 <b>{task['title']}</b>\n"
                f"💰 Награда: <b>{task['reward']} баллов</b>\n"
                f"⏰ Выполнить до: <b>{due_time_str}</b>\n\n"
                f"Используй команду /tasks чтобы посмотреть все задания!\n"
                f"Удачи! 💪"
            )
        else:
            # Несколько заданий
            message = (
                f"📅 <b>Получены новые ежедневные задания!</b>\n\n"
                f"Привет, {child_name}! 👋\n\n"
                f"📋 <b>Список заданий:</b>\n"
            )
            
            total_reward = 0
            for i, task in enumerate(tasks_details, 1):
                due_time_str = task['due_time'].strftime('%H:%M') if task['due_time'] else ""
                time_info = f" (до {due_time_str})" if due_time_str else ""
                message += f"{i}. <b>{task['title']}</b> - {task['reward']} баллов{time_info}\n"
                total_reward += task['reward']
            
            message += (
                f"\n💰 <b>Всего можно получить: {total_reward} баллов</b>\n\n"
                f"Используй команду /tasks чтобы посмотреть все задания!\n"
                f"Удачи! 💪"
            )
        
        return send_telegram_message(child_id, message)
        
    except Exception as e:
        logger.error("Error sending task notification to %s: %s", child_id, e)
        return False

def handle_tasks(chat_id, user_id):
    """Показать задания для ребенка (все активные, включая special)"""
    # Проверяем, является ли пользователь ребенком
    if is_admin(user_id):
        send_telegram_message(chat_id, "❌ Эта команда только для детей.")
        return True

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # Получаем ВСЕ активные задания ребенка (невыполненные)
        cur.execute("""
            SELECT at.assignment_id, t.title, t.description, t.type, 
                   t.reward, at.due_date, at.is_completed, at.assigned_date
            FROM assigned_tasks at
            JOIN tasks t ON at.task_id = t.task_id
            WHERE at.child_id = %s 
            AND at.is_completed = FALSE
            ORDER BY 
                CASE 
                    WHEN at.due_date < NOW() THEN 0  
                    WHEN t.type = 'special' THEN 1   
                    WHEN t.type = 'daily' THEN 2     
                    ELSE 3
                END,
                at.due_date
        """, (user_id,))
        
        tasks = cur.fetchall()

        if not tasks:
            send_telegram_message(chat_id,
                "🎉 Ура! У тебя нет активных заданий!\n"
                "Отлично поработал! 💪\n\n"
                "Новые задания появятся, когда родитель их выдаст."
            )
            return True

        message_text = "📋 <b>Твои активные задания:</b>\n\n"
        
        keyboard_buttons = []
        now = datetime.now()
        today = date.today()
        
        for task in tasks:
            assignment_id, title, description, task_type, reward, due_date, is_completed, assigned_date = task
            
            type_emoji = "📅" if task_type == 'daily' else "🗓️" if task_type == 'weekly' else "⭐"
            
            # ИСПРАВЛЕНИЕ 1: Проверяем тип assigned_date
            if isinstance(assigned_date, datetime):
                assigned_date_only = assigned_date.date()
            else:
                assigned_date_only = assigned_date
            
            # Для special заданий - особый формат отображения
            if task_type == 'special':
                # ИСПРАВЛЕНИЕ 2: Проверяем тип due_date
                if isinstance(due_date, datetime):
                    due_datetime = due_date
                    due_date_only = due_date.date()
                else:
                    # Если due_date уже date, создаем datetime с началом дня
                    due_datetime = datetime.combine(due_date, time(0, 0))
                    due_date_only = due_date
                
                days_left = (due_date_only - today).days
                
                if days_left < 0:
                    # Просрочено
                    time_display = "❌ Просрочено!"
                    status_emoji = "❌"
                elif days_left == 0:
                    # Сегодня
                    hours_left = (due_datetime - now).total_seconds() / 3600
                    if hours_left > 0:
                        if hours_left < 1:
                            minutes = int(hours_left * 60)
                            time_display = f"⏰ Осталось: {minutes} мин."
                        else:
                            time_display = f"⏰ Осталось: {int(hours_left)} ч."
                        status_emoji = "⚠️"
                    else:
                        time_display = "⚠️ Сегодня последний день!"
                        status_emoji = "⚠️"
                else:
                    # В будущем
                    time_display = f"📅 Осталось дней: {days_left}"
                    status_emoji = "📅"
                    
            else:  # daily или weekly
                # ИСПРАВЛЕНИЕ 3: Проверяем тип due_date для daily/weekly
                if isinstance(due_date, datetime):
                    due_datetime = due_date
                else:
                    # Если due_date уже date, создаем datetime с началом дня
                    due_datetime = datetime.combine(due_date, time(0, 0))
                
                time_left = due_datetime - now
                
                # Проверяем, сегодня ли было выдано задание
                is_today = assigned_date_only == today
                
                if not is_today and task_type == 'daily':
                    # Ежедневное задание не на сегодня - пропускаем
                    continue
                
                if time_left.total_seconds() > 0:
                    # Еще не наступил дедлайн
                    if time_left.total_seconds() < 3600:  # Меньше часа
                        minutes = int(time_left.total_seconds() // 60)
                        time_display = f"⏰ Осталось: {minutes} мин."
                        status_emoji = "⚠️"
                    else:
                        hours = int(time_left.total_seconds() // 3600)
                        time_display = f"⏰ Осталось: {hours} ч."
                        status_emoji = "🕒"
                        
                else:
                    # Дедлайн прошел
                    if is_today:  # Только для сегодняшних заданий
                        end_of_day = datetime.combine(today, time(23, 59, 59))
                        
                        if now <= end_of_day:
                            # Еще сегодня, можно выполнить за 50%
                            hours_left = (end_of_day - now).total_seconds() / 3600
                            if hours_left < 1:
                                minutes_left = int((end_of_day - now).total_seconds() // 60)
                                time_display = f"⚠️ Просрочено! Можно выполнить за 50% награды (осталось {minutes_left} мин.)"
                            else:
                                time_display = f"⚠️ Просрочено! Можно выполнить за 50% награды (до 23:59)"
                            status_emoji = "⏰"
                        else:
                            # Уже завтра, задание неактивно
                            time_display = "❌ Время вышло! Задание больше не доступно."
                            status_emoji = "❌"
                            # Не добавляем кнопку для выполнения
                            continue
                    else:
                        # Не сегодняшнее задание с просрочкой
                        time_display = "❌ Время вышло!"
                        status_emoji = "❌"
                        continue
            
            # Форматируем отображение задания
            message_text += f"{status_emoji} {type_emoji} <b>{title}</b>\n"
            
            if description:
                message_text += f"   📝 {description}\n"
            
            message_text += f"   💰 Награда: {reward} баллов\n"
            message_text += f"   {time_display}\n"
            
            if task_type == 'special':
                # Форматируем дату специального задания
                if isinstance(due_date, datetime):
                    message_text += f"   📅 Выполнить до: {due_date.strftime('%d.%m.%Y %H:%M')}\n"
                else:
                    message_text += f"   📅 Выполнить до: {due_date.strftime('%d.%m.%Y')}\n"
            else:
                if isinstance(due_date, datetime):
                    message_text += f"   📅 До: {due_date.strftime('%H:%M')}\n"
                else:
                    # Если почему-то не datetime, используем due_datetime
                    message_text += f"   📅 До: {due_datetime.strftime('%H:%M')}\n"
            
            message_text += "\n"
            
            # Добавляем кнопку для отметки выполнения
            if status_emoji != "❌":  # Не добавляем для просроченных заданий
                # Ограничиваем длину текста кнопки
                button_text = title[:30] + "..." if len(title) > 30 else title
                keyboard_buttons.append([{
                    'text': f"✅ Выполнил: {button_text}", 
                    'callback_data': f'complete_{assignment_id}'
                }])

        if not keyboard_buttons:
            # Все задания просрочены
            message_text += "\n\n⚠️ <b>Все задания просрочены и больше не доступны для выполнения.</b>"
        
        if keyboard_buttons:
            keyboard = create_inline_keyboard(keyboard_buttons)
            send_telegram_message(chat_id, message_text, reply_markup=keyboard)
        else:
            send_telegram_message(chat_id, message_text)
            
        return True
        
    except Exception as e:
        logger.error("Error showing child tasks: %s", e, exc_info=True)  # Добавим exc_info для деталей
        send_telegram_message(chat_id, "❌ Ошибка при получении заданий.")
        return False
    finally:
        cur.close()
        conn.close()

def handle_complete_task(chat_id, user_id, message_id, data, callback_id):
    """Обработчик выполнения задания (все типы)"""
    assignment_id = int(data.replace("complete_", ""))

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # Получаем информацию о задании (все типы)
        cur.execute("""
            SELECT at.assignment_id, t.title, t.reward, at.due_date, t.type,
                   t.created_by as parent_id, u.full_name as child_name,
                   at.assigned_date
            FROM assigned_tasks at
            JOIN tasks t ON at.task_id = t.task_id
            JOIN users u ON at.child_id = u.user_id
            WHERE at.assignment_id = %s AND at.child_id = %s 
            AND at.is_completed = FALSE
        """, (assignment_id, user_id))
        
        task = cur.fetchone()

        if not task:
            send_telegram_callback_answer(callback_id, 
                "❌ Задание не найдено или уже выполнено!", 
                show_alert=True)
            return True

        assignment_id, title, reward, due_date, task_type, parent_id, child_name, assigned_date = task
        
        now = datetime.now()
        today = date.today()
        
        # РАЗНАЯ ЛОГИКА ДЛЯ РАЗНЫХ ТИПОВ ЗАДАНИЙ:
        
        if task_type == 'special':
            # Special задание - можно выполнить в любое время до due_date
            if now > due_date:
                # Просрочено
                final_reward = reward // 2  # 50% за просрочку
                reward_message = f"⏰ Просрочено! Награда уменьшена до {final_reward} баллов."
                timing_status = "⚠️ Выполнено с опозданием"
            else:
                # Вовремя
                final_reward = reward
                reward_message = f"🎉 Вовремя! Получено {final_reward} баллов!"
                timing_status = "✅ Выполнено вовремя!"
                
        else:  # daily или weekly
            # Для ежедневных/еженедельных - старая логика
            end_of_day = datetime.combine(today, time(23, 59, 59))
            
            # Проверяем возможность выполнения
            if task_type == 'daily' and assigned_date.date() != today:
                # Ежедневное задание не на сегодня
                send_telegram_callback_answer(callback_id,
                    "❌ Это задание уже неактивно!",
                    show_alert=True)
                return True
            
            if now > end_of_day and task_type == 'daily':
                # Уже завтра для ежедневного
                send_telegram_callback_answer(callback_id,
                    "❌ Время выполнения истекло! Задание больше не доступно.",
                    show_alert=True)
                return True
            
            # Рассчитываем награду
            if now <= due_date:
                # Вовремя - 100%
                final_reward = reward
                reward_message = f"🎉 Вовремя! Получено {final_reward} баллов!"
                timing_status = "✅ Выполнено вовремя!"
            else:
                # Просрочено, но еще сегодня - 50% (только для daily)
                if task_type == 'daily' and now <= end_of_day:
                    final_reward = reward // 2
                    reward_message = f"⏰ Просрочено! Награда уменьшена до {final_reward} баллов."
                    timing_status = "⚠️ Выполнено с опозданием"
                else:
                    # Для weekly или полностью просроченных daily
                    final_reward = reward // 2
                    reward_message = f"⏰ Просрочено! Награда уменьшена до {final_reward} баллов."
                    timing_status = "⚠️ Выполнено с опозданием"
        
        # Отмечаем выполненным и начисляем баллы
        cur.execute("""
            UPDATE assigned_tasks 
            SET is_completed = TRUE, completed_at = NOW(), reward_received = %s
            WHERE assignment_id = %s
        """, (final_reward, assignment_id))

        cur.execute("""
            UPDATE users 
            SET balance = balance + %s 
            WHERE user_id = %s
        """, (final_reward, user_id))

        cur.execute("""
            INSERT INTO transactions (child_id, amount, type, description)
            VALUES (%s, %s, 'task_reward', %s)
        """, (user_id, final_reward, f"Выполнение задания '{title}' ({task_type})"))

        conn.commit()

        # Уведомления
        cur.execute("SELECT balance FROM users WHERE user_id = %s", (user_id,))
        new_balance = cur.fetchone()[0]

        send_telegram_callback_answer(callback_id, 
            f"✅ Задание '{title}' выполнено!\n{reward_message}\n"
            f"💰 Новый баланс: {new_balance} баллов", 
            show_alert=True)
        
        if parent_id:
            parent_notification = (
                f"📋 <b>Задание выполнено!</b>\n\n"
                f"👤 Ребенок: {child_name}\n"
                f"✅ Задание: {title}\n"
                f"📊 Тип: {task_type}\n"
                f"💰 Награда: {final_reward} баллов\n"
                f"📈 Статус: {timing_status}\n"
                f"💳 Баланс ребенка: {new_balance} баллов"
            )
            
            # Добавляем кнопку "Вернуть задание"
            keyboard = create_inline_keyboard([
                [{'text': '🔄 Вернуть задание', 'callback_data': f'return_task_{assignment_id}'}]
            ])
            
            send_telegram_message(parent_id, parent_notification, reply_markup=keyboard)
        
        # Обновляем список заданий
        return handle_tasks(chat_id, user_id)
        
    except Exception as e:
        logger.error("Error completing task: %s", e)
        send_telegram_callback_answer(callback_id, "❌ Ошибка!", show_alert=True)
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()

def handle_balance(chat_id, user_id):
    """Показать баланс ребенка"""
    if is_admin(user_id):
        send_telegram_message(chat_id, "❌ Эта команда только для детей.")
        return True

    balance = get_user_balance(user_id)
    send_telegram_message(chat_id,
        f"💰 Твой текущий баланс: <b>{balance} баллов</b>\n\n"
        f"Продолжай в том же духе! 💪"
    )
    return True

# ФУНКЦИИ УПРАВЛЕНИЯ БАЛАНСАМИ И НАГРАДАМИ

def handle_balance_management(chat_id, user_id):
    """Панель управления балансами (только для админов)"""
    if not is_admin(user_id):
        send_telegram_message(chat_id, "❌ У вас нет прав администратора.")
        return True

    keyboard = create_inline_keyboard([
        [
            {'text': '💰 Начислить баллы', 'callback_data': 'balance_add'},
            {'text': '➖ Списать баллы', 'callback_data': 'balance_remove'}
        ],
        [
            {'text': '📊 Балансы детей', 'callback_data': 'balance_list'},
            {'text': '🎁 Настройка наград', 'callback_data': 'rewards_settings'}
        ],
        [
            {'text': '📋 История операций', 'callback_data': 'balance_history'},
            {'text': '⬅️ Назад', 'callback_data': 'admin_back'}
        ]
    ])
    
    send_telegram_message(chat_id, "💰 <b>Управление балансами и наградами:</b>", reply_markup=keyboard)
    return True

def handle_balance_callback(chat_id, user_id, message_id, data, callback_id):
    """Обработка callback'ов управления балансом"""
    if not is_admin(user_id):
        send_telegram_callback_answer(callback_id, "❌ У вас нет прав администратора.", show_alert=True)
        return True

    send_telegram_callback_answer(callback_id)
    if data == 'balance_management':
        return handle_balance_management(chat_id, user_id)    
    elif data == 'balance_add':
        return start_add_balance(chat_id, user_id, message_id)
    elif data == 'balance_remove':
        return start_remove_balance(chat_id, user_id, message_id)
    elif data == 'balance_list':
        return show_children_balances(chat_id, user_id, message_id)
    elif data == 'rewards_settings':
        return show_rewards_settings(chat_id, user_id, message_id)
    elif data == 'balance_history':
        return show_balance_history(chat_id, user_id, message_id)
    elif data == 'admin_back':
        return handle_admin(chat_id, user_id)
    elif data == 'balance_back':
        return handle_balance_management(chat_id, user_id)        
    
    return True

def start_add_balance(chat_id, user_id, message_id):
    """Начало процесса начисления баллов"""
    user_temp_data[user_id] = {
        'chat_id': chat_id,
        'message_id': message_id,
        'action': 'add_balance',
        'step': 'select_child'
    }
    
    return show_children_selection(chat_id, user_id, message_id, "👤 Выберите ребенка для начисления баллов:")

def start_remove_balance(chat_id, user_id, message_id):
    """Начало процесса списания баллов"""
    user_temp_data[user_id] = {
        'chat_id': chat_id,
        'message_id': message_id,
        'action': 'remove_balance',
        'step': 'select_child'
    }
    
    return show_children_selection(chat_id, user_id, message_id, "👤 Выберите ребенка для списания баллов:")

def show_children_selection(chat_id, user_id, message_id, message_text):
    """Показать список детей для выбора"""
    children = get_children_list()
    if not children:
        edit_telegram_message(chat_id, message_id, "❌ В системе нет зарегистрированных детей.")
        return True
    
    keyboard_buttons = []
    for child in children:
        child_id, full_name, username, balance = child
        username_display = f" (@{username})" if username else ""
        keyboard_buttons.append([
            {'text': f"👤 {full_name}{username_display} ({balance} баллов)", 'callback_data': f'child_{child_id}'}
        ])
    
    keyboard_buttons.append([{'text': '❌ Отмена', 'callback_data': 'balance_cancel'}])
    
    keyboard = create_inline_keyboard(keyboard_buttons)
    edit_telegram_message(chat_id, message_id, message_text, reply_markup=keyboard)
    return True

def handle_child_selection(chat_id, user_id, message_id, data, callback_id):
    """Обработка выбора ребенка"""
    if not is_admin(user_id):
        send_telegram_callback_answer(callback_id, "❌ У вас нет прав администратора.", show_alert=True)
        return True

    if data == 'balance_cancel':
        send_telegram_callback_answer(callback_id)
        edit_telegram_message(chat_id, message_id, "❌ Операция отменена.")
        if user_id in user_temp_data:
            del user_temp_data[user_id]
        return True

    send_telegram_callback_answer(callback_id)
    
    if user_id not in user_temp_data:
        edit_telegram_message(chat_id, message_id, "❌ Сессия истекла. Начните заново.")
        return True
    
    child_id = int(data.replace('child_', ''))
    user_temp_data[user_id]['child_id'] = child_id
    user_temp_data[user_id]['step'] = 'enter_amount'
    
    action = user_temp_data[user_id]['action']
    child_name = get_user_name(child_id)
    
    if action == 'add_balance':
        message = f"💰 Введите сумму для начисления ребенку <b>{child_name}</b>:"
    else:
        message = f"➖ Введите сумму для списания у ребенка <b>{child_name}</b>:"
    
    edit_telegram_message(chat_id, message_id, message)
    return True

def show_rewards_settings(chat_id, user_id, message_id):
    """Панель настройки наград"""
    if not is_admin(user_id):
        edit_telegram_message(chat_id, message_id, "❌ У вас нет прав администратора.")
        return True

    # Получаем текущие настройки наград
    rewards = get_default_rewards()
    
    message = (
        "🎁 <b>Настройка стандартных наград:</b>\n\n"
        f"📅 <b>Ежедневные задания:</b> {rewards['daily']} баллов\n"
        f"🗓️ <b>Еженедельные задания:</b> {rewards['weekly']} баллов\n\n"
        "Вы можете изменить стандартные награды для заданий:"
    )
    
    keyboard = create_inline_keyboard([
        [
            {'text': f'📅 Ежедневные: {rewards["daily"]}🔺', 'callback_data': 'reward_daily_up'},
            {'text': f'📅 Ежедневные: {rewards["daily"]}🔻', 'callback_data': 'reward_daily_down'}
        ],
        [
            {'text': f'🗓️ Еженедельные: {rewards["weekly"]}🔺', 'callback_data': 'reward_weekly_up'},
            {'text': f'🗓️ Еженедельные: {rewards["weekly"]}🔻', 'callback_data': 'reward_weekly_down'}
        ],
        [
            {'text': '💾 Сохранить', 'callback_data': 'rewards_save'},
            {'text': '❌ Сбросить', 'callback_data': 'rewards_reset'}
        ],
        [
            {'text': '⬅️ Назад', 'callback_data': 'balance_back'}
        ]
    ])
    
    edit_telegram_message(chat_id, message_id, message, reply_markup=keyboard)
    return True

def handle_rewards_callback(chat_id, user_id, message_id, data, callback_id):
    """Обработка callback'ов настройки наград"""
    if not is_admin(user_id):
        send_telegram_callback_answer(callback_id, "❌ У вас нет прав администратора.", show_alert=True)
        return True

    send_telegram_callback_answer(callback_id)
    
    if user_id not in user_temp_data:
        user_temp_data[user_id] = {
            'rewards': get_default_rewards().copy(),
            'chat_id': chat_id,
            'message_id': message_id
        }
    
    rewards = user_temp_data[user_id]['rewards']
    
    if data == 'reward_daily_up':
        rewards['daily'] += 5
    elif data == 'reward_daily_down' and rewards['daily'] > 5:
        rewards['daily'] -= 5
    elif data == 'reward_weekly_up':
        rewards['weekly'] += 10
    elif data == 'reward_weekly_down' and rewards['weekly'] > 10:
        rewards['weekly'] -= 10
    elif data == 'rewards_save':
        if save_default_rewards(rewards):
            send_telegram_message(chat_id, "✅ Настройки наград сохранены!")
        else:
            send_telegram_message(chat_id, "❌ Ошибка при сохранении настроек.")
        del user_temp_data[user_id]
        return True
    elif data == 'rewards_reset':
        rewards = get_default_rewards()
    elif data == 'balance_back':
        del user_temp_data[user_id]
        return handle_balance_management(chat_id, user_id)
    
    # Обновляем сообщение с новыми значениями
    user_temp_data[user_id]['rewards'] = rewards
    return show_rewards_settings(chat_id, user_id, message_id)

def show_children_balances(chat_id, user_id, message_id):
    """Показать балансы всех детей"""
    children = get_children_list()
    
    if not children:
        edit_telegram_message(chat_id, message_id, "👶 В системе нет зарегистрированных детей.")
        return True
    
    message = "💳 <b>Балансы детей:</b>\n\n"
    total_balance = 0
    
    for child in children:
        child_id, full_name, username, balance = child
        username_display = f" (@{username})" if username else ""
        message += f"👤 <b>{full_name}</b>{username_display}\n"
        message += f"   💰 Баланс: {balance} баллов\n"
        message += f"   🆔 ID: <code>{child_id}</code>\n\n"
        total_balance += balance
    
    message += f"📊 <b>Общий баланс системы:</b> {total_balance} баллов"
    
    keyboard = create_inline_keyboard([
        [{'text': '🔄 Обновить', 'callback_data': 'balance_list'}],
        [{'text': '⬅️ Назад', 'callback_data': 'balance_back'}]
    ])
    
    edit_telegram_message(chat_id, message_id, message, reply_markup=keyboard)
    return True

def show_balance_history(chat_id, user_id, message_id):
    """Показать историю операций"""
    history = get_recent_transactions(10)
    
    if not history:
        edit_telegram_message(chat_id, message_id, "📝 История операций пуста.")
        return True
    
    message = "📋 <b>Последние операции:</b>\n\n"
    
    for transaction in history:
        trans_id, child_id, amount, trans_type, description, created_at = transaction
        child_name = get_user_name(child_id)
        amount_display = f"+{amount}" if amount > 0 else str(amount)
        emoji = "🟢" if amount > 0 else "🔴"
        
        message += f"{emoji} <b>{child_name}</b>\n"
        message += f"   💰 {amount_display} баллов\n"
        message += f"   📝 {description}\n"
        message += f"   🕒 {created_at.strftime('%d.%m.%Y %H:%M')}\n\n"
    
    keyboard = create_inline_keyboard([
        [{'text': '🔄 Обновить', 'callback_data': 'balance_history'}],
        [{'text': '⬅️ Назад', 'callback_data': 'balance_back'}]
    ])
    
    edit_telegram_message(chat_id, message_id, message, reply_markup=keyboard)
    return True

# БАЗОВЫЕ ФУНКЦИИ РАБОТЫ С БАЗОЙ ДАННЫХ

def get_user_balance(user_id):
    """Получить баланс пользователя"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT balance FROM users WHERE user_id = %s", (user_id,))
        result = cur.fetchone()
        return result[0] if result else 0
    except Exception as e:
        logger.error("Error getting user balance: %s", e)
        return 0
    finally:
        cur.close()
        conn.close()

def is_admin(user_id):
    """Проверить, является ли пользователь администратором"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT role FROM users WHERE user_id = %s", (user_id,))
        result = cur.fetchone()
        return result and result[0] == 'admin'
    except Exception as e:
        logger.error("Error checking admin: %s", e)
        return False
    finally:
        cur.close()
        conn.close()

def get_children_list():
    """Получить список детей"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT user_id, full_name, username, balance 
            FROM users 
            WHERE role = 'child' 
            ORDER BY full_name
        """)
        return cur.fetchall()
    except Exception as e:
        logger.error("Error getting children list: %s", e)
        return []
    finally:
        cur.close()
        conn.close()

def add_balance(child_id, amount, description):
    """Начислить баллы ребенку"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Обновляем баланс
        cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (amount, child_id))
        
        # Записываем транзакцию
        cur.execute("""
            INSERT INTO transactions (child_id, amount, type, description)
            VALUES (%s, %s, 'manual_add', %s)
        """, (child_id, amount, description))
        
        conn.commit()
        return True
    except Exception as e:
        logger.error("Error adding balance: %s", e)
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()

def remove_balance(child_id, amount, description):
    """Списать баллы у ребенка"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Проверяем текущий баланс
        cur.execute("SELECT balance FROM users WHERE user_id = %s", (child_id,))
        current_balance = cur.fetchone()[0]
        
        if current_balance < amount:
            return False  # Недостаточно средств
        
        # Списание
        cur.execute("UPDATE users SET balance = balance - %s WHERE user_id = %s", (amount, child_id))
        
        # Записываем транзакцию
        cur.execute("""
            INSERT INTO transactions (child_id, amount, type, description)
            VALUES (%s, %s, 'manual_remove', %s)
        """, (child_id, -amount, description))
        
        conn.commit()
        return True
    except Exception as e:
        logger.error("Error removing balance: %s", e)
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()

def get_recent_transactions(limit=10):
    """Получить последние транзакции"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT transaction_id, child_id, amount, type, description, created_at
            FROM transactions 
            ORDER BY created_at DESC 
            LIMIT %s
        """, (limit,))
        return cur.fetchall()
    except Exception as e:
        logger.error("Error getting transactions: %s", e)
        return []
    finally:
        cur.close()
        conn.close()

def get_user_name(user_id):
    """Получить имя пользователя"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT full_name FROM users WHERE user_id = %s", (user_id,))
        result = cur.fetchone()
        return result[0] if result else "Неизвестный"
    except Exception as e:
        logger.error("Error getting user name: %s", e)
        return "Неизвестный"
    finally:
        cur.close()
        conn.close()

def show_task_status(chat_id, user_id, message_id, filter_type='today'):
    """Показать статус выполнения заданий"""
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # Определяем фильтр по дате
        if filter_type == 'today':
            date_filter = "AND at.assigned_date = CURRENT_DATE"
            title = "📊 <b>Статус заданий на сегодня:</b>"
        elif filter_type == 'week':
            date_filter = "AND at.assigned_date >= DATE_TRUNC('week', CURRENT_DATE)"
            title = "📊 <b>Статус заданий на этой неделе:</b>"
        elif filter_type == 'all':
            date_filter = ""
            title = "📊 <b>Статус всех заданий:</b>"
        else:
            date_filter = "AND at.assigned_date = CURRENT_DATE"
            title = "📊 <b>Статус заданий на сегодня:</b>"

        # Получаем статистику по заданиям
        sql_query = f"""
            SELECT 
                at.assignment_id,
                t.title as task_title,
                u.full_name as child_name,
                at.assigned_date,
                at.due_date,
                at.is_completed,
                at.completed_at,
                at.reward_received,
                t.type as task_type,
                CASE 
                    WHEN at.is_completed THEN '✅ Выполнено'
                    WHEN at.due_date < NOW() THEN '❌ Просрочено'
                    ELSE '⏳ В процессе'
                END as status,
                CASE 
                    WHEN at.is_completed THEN '🟢'
                    WHEN at.due_date < NOW() THEN '🔴'
                    ELSE '🟡'
                END as status_emoji
            FROM assigned_tasks at
            JOIN tasks t ON at.task_id = t.task_id
            JOIN users u ON at.child_id = u.user_id
            WHERE t.created_by = %s
            {date_filter}
            ORDER BY at.assigned_date DESC, at.is_completed, at.due_date
            LIMIT 15
        """
        
        cur.execute(sql_query, (user_id,))
        
        tasks = cur.fetchall()

        if not tasks:
            message = f"{title}\n\n📭 Нет заданий для отображения."
            
            # Создаем клавиатуру с фильтрами
            keyboard = create_inline_keyboard([
                [
                    {'text': '📅 Сегодня', 'callback_data': 'task_status_today'},
                    {'text': '📅 Неделя', 'callback_data': 'task_status_week'},
                    {'text': '📅 Все', 'callback_data': 'task_status_all'}
                ],
                [
                    {'text': '🔄 Обновить', 'callback_data': 'admin_task_status'},
                    {'text': '⬅️ Назад', 'callback_data': 'admin_back'}
                ]
            ])

            edit_telegram_message(chat_id, message_id, message, reply_markup=keyboard)
            return True
        
        message = f"{title}\n\n"
        
        completed_count = 0
        overdue_count = 0
        in_progress_count = 0
        
        # Для хранения кнопок возврата выполненных заданий
        return_buttons = []
        
        current_date = None
        for task in tasks:
            assignment_id, task_title, child_name, assigned_date, due_date, is_completed, completed_at, reward_received, task_type, status, status_emoji = task
            
            # Группируем по дате
            if current_date != assigned_date:
                current_date = assigned_date
                message += f"\n📅 <b>{assigned_date.strftime('%d.%m.%Y')}:</b>\n"
            
            # Считаем статистику
            if is_completed:
                completed_count += 1
            elif due_date and datetime.now() > due_date:
                overdue_count += 1
            else:
                in_progress_count += 1
            
            # Формируем строку задания
            message += f"{status_emoji} <b>{task_title}</b>\n"
            message += f"   👤 {child_name}\n"
            message += f"   📊 {status}\n"
            
            if is_completed and completed_at:
                message += f"   ⏱️ Выполнено: {completed_at.strftime('%H:%M')}\n"
                if reward_received:
                    message += f"   💰 Баллов: {reward_received}\n"
                    
                    # Для выполненных заданий добавляем кнопку возврата (только если задание выполнено сегодня или вчера)
                    time_since_completion = datetime.now() - completed_at
                    if time_since_completion.days <= 1:  # Можно возвращать только за последние 24 часа
                        # Создаем короткое название для кнопки
                        short_title = task_title[:15] + "..." if len(task_title) > 15 else task_title
                        return_buttons.append([
                            {'text': f'🔄 Вернуть: {short_title}', 'callback_data': f'return_task_{assignment_id}'}
                        ])
                    
            elif due_date:
                time_left = due_date - datetime.now()
                if time_left.total_seconds() > 0:
                    hours = int(time_left.total_seconds() // 3600)
                    if hours < 1:
                        minutes = int((time_left.total_seconds() % 3600) // 60)
                        message += f"   ⏰ Осталось: {minutes} мин.\n"
                    else:
                        message += f"   ⏰ Осталось: {hours} ч.\n"
            
            message += "\n"
        
        # Добавляем общую статистику
        message += f"\n📈 <b>Общая статистика:</b>\n"
        message += f"✅ Выполнено: {completed_count}\n"
        message += f"⏳ В процессе: {in_progress_count}\n"
        message += f"❌ Просрочено: {overdue_count}\n"
        message += f"📊 Всего: {len(tasks)}\n"
        
        # Создаем клавиатуру
        keyboard_buttons = []
        
        # Добавляем кнопки возврата выполненных заданий (если есть)
        if return_buttons:
            message += f"\n🔄 <i>Доступно для возврата: {len(return_buttons)} заданий</i>\n"
            keyboard_buttons.extend(return_buttons)
        
        # Кнопки фильтров
        filter_buttons = [
            {'text': '📅 Сегодня', 'callback_data': 'task_status_today'},
            {'text': '📅 Неделя', 'callback_data': 'task_status_week'},
            {'text': '📅 Все', 'callback_data': 'task_status_all'}
        ]
        
        # Добавляем кнопку для просмотра всех выполненных заданий
        if completed_count > 0:
            filter_buttons.append({'text': '✅ Все выполненные', 'callback_data': 'admin_completed_tasks'})
        
        keyboard_buttons.append(filter_buttons)
        
        # Кнопки навигации
        nav_buttons = [
            {'text': '🔄 Обновить', 'callback_data': 'admin_task_status'},
            {'text': '⬅️ Назад', 'callback_data': 'admin_back'}
        ]
        keyboard_buttons.append(nav_buttons)

        keyboard = create_inline_keyboard(keyboard_buttons)

        edit_telegram_message(chat_id, message_id, message, reply_markup=keyboard)
        return True
        
    except Exception as e:
        logger.error("Error showing task status: %s", e)
        edit_telegram_message(chat_id, message_id, "❌ Ошибка при получении статуса заданий.")
        return False
    finally:
        cur.close()
        conn.close()

def get_children_for_admin(admin_id):
    """Получить список детей для конкретного администратора"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT user_id, full_name, username, balance 
            FROM users 
            WHERE role = 'child' 
            AND (parent_id = %s OR parent_id IS NULL)
            ORDER BY full_name
        """, (admin_id,))
        return cur.fetchall()
    except Exception as e:
        logger.error("Error getting children for admin: %s", e)
        return []
    finally:
        cur.close()
        conn.close()

def handle_special_child_selection(chat_id, user_id, message_id, data, callback_id):
    """Обработка выбора детей для special задания"""
    if user_id not in user_temp_data:
        send_telegram_callback_answer(callback_id, "❌ Сессия истекла.", show_alert=True)
        return True
    
    send_telegram_callback_answer(callback_id)
    
    # Получаем список детей для проверки
    children = get_children_for_admin(user_id)
    
    if data == 'special_child_all':
        # Выбираем всех детей
        child_ids = [child[0] for child in children]
        user_temp_data[user_id]['selected_children'] = child_ids
        
        # Показываем подтверждение
        children_names = [child[1] for child in children]
        message = f"✅ Выбраны все дети ({len(children_names)}):\n" + "\n".join([f"• {name}" for name in children_names])
        
        keyboard = create_inline_keyboard([
            [{'text': '✅ Готово', 'callback_data': 'special_confirm'}],
            [{'text': '🔄 Выбрать заново', 'callback_data': 'special_reset'}]
        ])
        
    elif data == 'special_child_none':
        # Не назначаем никому
        user_temp_data[user_id]['selected_children'] = []
        message = "ℹ️ Задание не будет назначено детям. Вы можете назначить его позже."
        
        keyboard = create_inline_keyboard([
            [{'text': '✅ Создать без назначения', 'callback_data': 'special_confirm_none'}],
            [{'text': '🔄 Выбрать детей', 'callback_data': 'special_reset'}]
        ])
        
    elif data == 'special_confirm':
        # Сохраняем задание с выбранными детьми
        child_ids = user_temp_data[user_id].get('selected_children', [])
        
        if save_task_to_db(user_id, assign_to_children=True, child_ids=child_ids):
            message = f"✅ Особое задание создано и назначено {len(child_ids)} детям!"
            
            # Отправляем уведомления детям
            for child_id in child_ids:
                child_name = get_user_name(child_id)
                task_title = user_temp_data[user_id]['title']
                reward = user_temp_data[user_id]['reward']
                due_date = user_temp_data[user_id]['custom_due_date']
                
                child_message = (
                    f"⭐ <b>Получено новое особое задание!</b>\n\n"
                    f"Привет, {child_name}! 👋\n\n"
                    f"📋 <b>{task_title}</b>\n"
                    f"💰 Награда: <b>{reward} баллов</b>\n"
                    f"📅 Выполнить до: <b>{due_date.strftime('%d.%m.%Y %H:%M')}</b>\n\n"
                    f"Используй команду /tasks чтобы посмотреть задание!\n"
                    f"Удачи! 💪"
                )
                send_telegram_message(child_id, child_message)
            
            del user_temp_data[user_id]
        else:
            message = "❌ Ошибка при создании задания."
        
        edit_telegram_message(chat_id, message_id, message)
        return True
        
    elif data == 'special_confirm_none':
        # Сохраняем без назначения
        if save_task_to_db(user_id, assign_to_children=False):
            message = "✅ Особое задание создано (без назначения детям)."
            del user_temp_data[user_id]
        else:
            message = "❌ Ошибка при создании задания."
        
        edit_telegram_message(chat_id, message_id, message)
        return True
        
    elif data == 'special_reset':
        # Сброс выбора
        if 'selected_children' in user_temp_data[user_id]:
            del user_temp_data[user_id]['selected_children']
        
        # Показываем список детей заново
        children = get_children_for_admin(user_id)
        keyboard_buttons = []
        
        for child_id, child_name, username, balance in children:
            username_display = f" (@{username})" if username else ""
            is_selected = child_id in user_temp_data[user_id].get('selected_children', [])
            prefix = "✅ " if is_selected else "⬜ "
            keyboard_buttons.append([
                {'text': f"{prefix}{child_name}{username_display}", 'callback_data': f'special_child_{child_id}'}
            ])
        
        selected_count = len(user_temp_data[user_id].get('selected_children', []))
        keyboard_buttons.append([
            {'text': f'✅ Готово ({selected_count} выбрано)', 'callback_data': 'special_confirm'},
            {'text': '❌ Без назначения', 'callback_data': 'special_child_none'}
        ])
        
        keyboard = create_inline_keyboard(keyboard_buttons)
        
        message = f"👥 <b>Выберите детей:</b>\n"
        message += f"✅ Выбрано: {selected_count} из {len(children)}\n\n"
        message += "Продолжайте выбирать или нажмите 'Готово':"
        
        edit_telegram_message(chat_id, message_id, message, reply_markup=keyboard)
        return True
    
    else:
        # Выбор конкретного ребенка (special_child_123)
        child_id = int(data.replace('special_child_', ''))
        
        if 'selected_children' not in user_temp_data[user_id]:
            user_temp_data[user_id]['selected_children'] = []
        
        if child_id in user_temp_data[user_id]['selected_children']:
            # Убираем из выбранных
            user_temp_data[user_id]['selected_children'].remove(child_id)
            action = "❌ Убран"
        else:
            # Добавляем в выбранных
            user_temp_data[user_id]['selected_children'].append(child_id)
            action = "✅ Добавлен"
        
        child_name = get_user_name(child_id)
        selected_count = len(user_temp_data[user_id]['selected_children'])
        
        # Показываем обновленный список
        keyboard_buttons = []
        
        for c_id, c_name, username, balance in children:
            username_display = f" (@{username})" if username else ""
            is_selected = c_id in user_temp_data[user_id]['selected_children']
            prefix = "✅ " if is_selected else "⬜ "
            keyboard_buttons.append([
                {'text': f"{prefix}{c_name}{username_display}", 'callback_data': f'special_child_{c_id}'}
            ])
        
        keyboard_buttons.append([
            {'text': f'✅ Готово ({selected_count} выбрано)', 'callback_data': 'special_confirm'},
            {'text': '❌ Без назначения', 'callback_data': 'special_child_none'}
        ])
        
        keyboard = create_inline_keyboard(keyboard_buttons)
        
        message = f"{action} ребенок: <b>{child_name}</b>\n"
        message += f"✅ Выбрано детей: {selected_count} из {len(children)}\n\n"
        message += "Продолжайте выбирать или нажмите 'Готово':"
        
        edit_telegram_message(chat_id, message_id, message, reply_markup=keyboard)
        return True
    
    edit_telegram_message(chat_id, message_id, message, reply_markup=keyboard)
    return True

def show_task_management(chat_id, user_id, message_id, page=0):
    """Показать управление заданиями с пагинацией"""
    if not is_admin(user_id):
        edit_telegram_message(chat_id, message_id, "❌ У вас нет прав администратора.")
        return True
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Получаем общее количество заданий
        cur.execute("SELECT COUNT(*) FROM tasks WHERE created_by = %s", (user_id,))
        total_tasks = cur.fetchone()[0]
        
        if total_tasks == 0:
            edit_telegram_message(chat_id, message_id, 
                "📝 У вас пока нет созданных заданий.\n\n"
                "Используйте кнопку '➕ Добавить задание' для создания.")
            return True
        
        # Пагинация: 5 заданий на страницу
        limit = 5
        offset = page * limit
        
        # Получаем задания с пагинацией
        cur.execute("""
            SELECT task_id, title, type, reward, due_time, due_day, custom_due_date, is_active,
                   (SELECT COUNT(*) FROM assigned_tasks WHERE task_id = tasks.task_id AND is_completed = FALSE) as active_assignments
            FROM tasks 
            WHERE created_by = %s 
            ORDER BY is_active DESC, task_id DESC
            LIMIT %s OFFSET %s
        """, (user_id, limit, offset))
        
        tasks = cur.fetchall()
        
        message = "⚙️ <b>Управление заданиями</b>\n\n"
        
        for task in tasks:
            task_id, title, task_type, reward, due_time, due_day, custom_due_date, is_active, active_assignments = task
            
            # Эмодзи типа задания
            type_emoji = "📅" if task_type == 'daily' else "🗓️" if task_type == 'weekly' else "⭐"
            
            # Статус
            status = "✅ Активно" if is_active else "❌ Неактивно"
            status_color = "🟢" if is_active else "🔴"
            
            # Активные назначения
            assignments_info = f" ({active_assignments} активных)" if active_assignments > 0 else ""
            
            message += f"{status_color} {type_emoji} <b>{title}</b>\n"
            message += f"   Тип: {task_type}\n"
            message += f"   Награда: {reward} баллов\n"
            
            if task_type == 'daily' and due_time:
                message += f"   Время: {due_time.strftime('%H:%M')}\n"
            elif task_type == 'weekly' and due_day:
                message += f"   День: {due_day}\n"
            elif task_type == 'special' and custom_due_date:
                message += f"   Срок: {custom_due_date.strftime('%d.%m.%Y %H:%M')}\n"
            
            message += f"   Статус: {status}{assignments_info}\n"
            message += f"   ID: <code>{task_id}</code>\n\n"
        
        # Информация о пагинации
        total_pages = (total_tasks + limit - 1) // limit
        message += f"📄 Страница {page + 1} из {total_pages}\n"
        message += f"📊 Всего заданий: {total_tasks}"
        
        # Создаем клавиатуру с действиями
        keyboard_buttons = []
        
        # Кнопки для каждого задания
        for task in tasks:
            task_id = task[0]
            task_title = task[1][:20] + "..." if len(task[1]) > 20 else task[1]
            is_active = task[7]
            
            if is_active:
                keyboard_buttons.append([
                    {'text': f"❌ Отключить: {task_title}", 'callback_data': f'task_disable_{task_id}'},
                    {'text': f"🗑️ Удалить: {task_title}", 'callback_data': f'task_delete_{task_id}'}
                ])
            else:
                keyboard_buttons.append([
                    {'text': f"✅ Включить: {task_title}", 'callback_data': f'task_enable_{task_id}'},
                    {'text': f"🗑️ Удалить: {task_title}", 'callback_data': f'task_delete_{task_id}'}
                ])
        
        # Кнопки пагинации
        nav_buttons = []
        if page > 0:
            nav_buttons.append({'text': '⬅️ Назад', 'callback_data': f'task_manage_page_{page-1}'})
        
        nav_buttons.append({'text': '🔄 Обновить', 'callback_data': f'task_manage_page_{page}'})
        
        if page < total_pages - 1:
            nav_buttons.append({'text': 'Вперед ➡️', 'callback_data': f'task_manage_page_{page+1}'})
        
        keyboard_buttons.append(nav_buttons)
        
        # Кнопки основных действий
        keyboard_buttons.append([
            {'text': '➕ Создать задание', 'callback_data': 'admin_add_task'},
            {'text': '📋 Список заданий', 'callback_data': 'admin_list_tasks'}
        ])
        
        keyboard_buttons.append([
            {'text': '⬅️ В админку', 'callback_data': 'admin_back'}
        ])
        
        keyboard = create_inline_keyboard(keyboard_buttons)
        
        edit_telegram_message(chat_id, message_id, message, reply_markup=keyboard)
        return True
        
    except Exception as e:
        logger.error("Error in show_task_management: %s", e)
        edit_telegram_message(chat_id, message_id, "❌ Ошибка при получении списка заданий.")
        return False
    finally:
        cur.close()
        conn.close()

def disable_task(chat_id, user_id, message_id, task_id):
    """Отключить задание"""
    if not is_admin(user_id):
        edit_telegram_message(chat_id, message_id, "❌ У вас нет прав администратора.")
        return True
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Проверяем, принадлежит ли задание администратору
        cur.execute("SELECT title FROM tasks WHERE task_id = %s AND created_by = %s", (task_id, user_id))
        task = cur.fetchone()
        
        if not task:
            edit_telegram_message(chat_id, message_id, "❌ Задание не найдено или у вас нет прав.")
            return True
        
        task_title = task[0]
        
        # Отключаем задание
        cur.execute("UPDATE tasks SET is_active = FALSE WHERE task_id = %s", (task_id,))
        
        conn.commit()
        
        message = f"✅ Задание '<b>{task_title}</b>' отключено.\n\n"
        message += "⚠️ <i>Задание больше не будет выдаваться автоматически.\n"
        message += "Существующие назначения остаются активными.</i>"
        
        edit_telegram_message(chat_id, message_id, message)
        
        # Обновляем список через 2 секунды
        import time
        time.sleep(2)
        return show_task_management(chat_id, user_id, message_id)
        
    except Exception as e:
        logger.error("Error disabling task: %s", e)
        edit_telegram_message(chat_id, message_id, "❌ Ошибка при отключении задания.")
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()

def enable_task(chat_id, user_id, message_id, task_id):
    """Включить задание"""
    if not is_admin(user_id):
        edit_telegram_message(chat_id, message_id, "❌ У вас нет прав администратора.")
        return True
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Проверяем, принадлежит ли задание администратору
        cur.execute("SELECT title FROM tasks WHERE task_id = %s AND created_by = %s", (task_id, user_id))
        task = cur.fetchone()
        
        if not task:
            edit_telegram_message(chat_id, message_id, "❌ Задание не найдено или у вас нет прав.")
            return True
        
        task_title = task[0]
        
        # Включаем задание
        cur.execute("UPDATE tasks SET is_active = TRUE WHERE task_id = %s", (task_id,))
        
        conn.commit()
        
        message = f"✅ Задание '<b>{task_title}</b>' включено.\n\n"
        message += "🔄 <i>Задание снова будет выдаваться автоматически по расписанию.</i>"
        
        edit_telegram_message(chat_id, message_id, message)
        
        # Обновляем список через 2 секунды
        import time
        time.sleep(2)
        return show_task_management(chat_id, user_id, message_id)
        
    except Exception as e:
        logger.error("Error enabling task: %s", e)
        edit_telegram_message(chat_id, message_id, "❌ Ошибка при включении задания.")
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()

def confirm_delete_task(chat_id, user_id, message_id, task_id):
    """Подтверждение удаления задания"""
    if not is_admin(user_id):
        edit_telegram_message(chat_id, message_id, "❌ У вас нет прав администратора.")
        return True
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Получаем информацию о задании
        cur.execute("""
            SELECT title, type, 
                   (SELECT COUNT(*) FROM assigned_tasks WHERE task_id = %s AND is_completed = FALSE) as active_assignments
            FROM tasks 
            WHERE task_id = %s AND created_by = %s
        """, (task_id, task_id, user_id))
        
        task = cur.fetchone()
        
        if not task:
            edit_telegram_message(chat_id, message_id, "❌ Задание не найдено или у вас нет прав.")
            return True
        
        task_title, task_type, active_assignments = task
        
        message = f"🗑️ <b>Подтверждение удаления задания</b>\n\n"
        message += f"📋 <b>{task_title}</b>\n"
        message += f"📊 Тип: {task_type}\n"
        
        if active_assignments > 0:
            message += f"⚠️ <b>Внимание!</b> У задания есть <b>{active_assignments}</b> активных назначений.\n\n"
            message += "При удалении задания:\n"
            message += "• Все активные назначения будут отменены\n"
            message += "• Дети больше не смогут выполнить эти задания\n"
            message += "• Действие необратимо\n\n"
        else:
            message += "✅ У задания нет активных назначений.\n\n"
        
        message += "Вы уверены, что хотите удалить это задание?"
        
        keyboard = create_inline_keyboard([
            [
                {'text': '✅ Да, удалить', 'callback_data': f'task_delete_confirm_{task_id}'},
                {'text': '❌ Нет, отмена', 'callback_data': f'task_manage_page_0'}
            ]
        ])
        
        edit_telegram_message(chat_id, message_id, message, reply_markup=keyboard)
        return True
        
    except Exception as e:
        logger.error("Error confirming task deletion: %s", e)
        edit_telegram_message(chat_id, message_id, "❌ Ошибка при получении информации о задании.")
        return False
    finally:
        cur.close()
        conn.close()

def delete_task(chat_id, user_id, message_id, task_id):
    """Удалить задание"""
    if not is_admin(user_id):
        edit_telegram_message(chat_id, message_id, "❌ У вас нет прав администратора.")
        return True
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Получаем название задания для уведомления
        cur.execute("SELECT title FROM tasks WHERE task_id = %s AND created_by = %s", (task_id, user_id))
        task = cur.fetchone()
        
        if not task:
            edit_telegram_message(chat_id, message_id, "❌ Задание не найдено или у вас нет прав.")
            return True
        
        task_title = task[0]
        
        # Получаем детей, у которых есть активные назначения этого задания
        cur.execute("""
            SELECT DISTINCT child_id FROM assigned_tasks 
            WHERE task_id = %s AND is_completed = FALSE
        """, (task_id,))
        
        affected_children = cur.fetchall()
        
        # Удаляем задание (каскадное удаление должно быть настроено в БД)
        cur.execute("DELETE FROM tasks WHERE task_id = %s", (task_id,))
        
        conn.commit()
        
        # Уведомляем администратора
        message = f"✅ Задание '<b>{task_title}</b>' удалено.\n\n"
        
        if affected_children:
            message += f"📢 Отменены назначения для {len(affected_children)} детей.\n"
        
        edit_telegram_message(chat_id, message_id, message)
        
        # Обновляем список через 2 секунды
        import time
        time.sleep(2)
        return show_task_management(chat_id, user_id, message_id)
        
    except Exception as e:
        logger.error("Error deleting task: %s", e)
        edit_telegram_message(chat_id, message_id, "❌ Ошибка при удалении задания.")
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()

def get_default_rewards():
    """Получить стандартные награды"""
    # Временное решение - можно перенести в таблицу settings в БД
    return {
        'daily': 10,
        'weekly': 50
    }

def save_default_rewards(rewards):
    """Сохранить стандартные награды (заглушка - можно реализовать в БД)"""
    # TODO: Реализовать сохранение в таблицу settings
    logger.info("Rewards settings saved: %s", rewards)
    return True

def show_completed_tasks(chat_id, user_id, message_id, page=0):
    """Показать выполненные задания с возможностью возврата"""
    if not is_admin(user_id):
        edit_telegram_message(chat_id, message_id, "❌ У вас нет прав администратора.")
        return True
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Получаем выполненные задания
        limit = 5
        offset = page * limit
        
        cur.execute("""
            SELECT at.assignment_id, t.title, t.type, at.completed_at, 
                   at.reward_received, u.full_name as child_name,
                   at.child_id
            FROM assigned_tasks at
            JOIN tasks t ON at.task_id = t.task_id
            JOIN users u ON at.child_id = u.user_id
            WHERE at.is_completed = TRUE
            AND t.created_by = %s
            AND at.completed_at >= CURRENT_DATE - INTERVAL '7 days'  -- За последние 7 дней
            ORDER BY at.completed_at DESC
            LIMIT %s OFFSET %s
        """, (user_id, limit, offset))
        
        tasks = cur.fetchall()
        
        if not tasks:
            message = "📝 <b>Выполненные задания</b>\n\n"
            message += "За последние 7 дней выполненных заданий нет."
            
            keyboard = create_inline_keyboard([
                [{'text': '🔄 Обновить', 'callback_data': 'admin_completed_tasks'}],
                [{'text': '⬅️ В админку', 'callback_data': 'admin_back'}]
            ])
            
            edit_telegram_message(chat_id, message_id, message, reply_markup=keyboard)
            return True
        
        message = "✅ <b>Выполненные задания (последние 7 дней):</b>\n\n"
        
        keyboard_buttons = []
        
        for task in tasks:
            assignment_id, title, task_type, completed_at, reward_received, child_name, child_id = task
            
            type_emoji = "📅" if task_type == 'daily' else "🗓️" if task_type == 'weekly' else "⭐"
            time_ago = (datetime.now() - completed_at).total_seconds() / 3600
            
            if time_ago < 1:
                time_str = f"{int(time_ago * 60)} мин. назад"
            elif time_ago < 24:
                time_str = f"{int(time_ago)} ч. назад"
            else:
                time_str = f"{int(time_ago / 24)} дн. назад"
            
            message += f"{type_emoji} <b>{title}</b>\n"
            message += f"   👤 {child_name}\n"
            message += f"   📊 {task_type}\n"
            message += f"   ⏱️ {completed_at.strftime('%H:%M')} ({time_str})\n"
            message += f"   💰 {reward_received} баллов\n\n"
            
            # Кнопка возврата для каждого задания
            keyboard_buttons.append([
                {'text': f"🔄 Вернуть: {title[:15]}...", 'callback_data': f'return_task_{assignment_id}'}
            ])
        
        # Кнопки навигации
        nav_buttons = []
        if page > 0:
            nav_buttons.append({'text': '⬅️ Назад', 'callback_data': f'completed_page_{page-1}'})
        
        nav_buttons.append({'text': '🔄 Обновить', 'callback_data': f'completed_page_{page}'})
        
        # Предполагаем, что есть следующая страница, если получили limit записей
        if len(tasks) == limit:
            nav_buttons.append({'text': 'Вперед ➡️', 'callback_data': f'completed_page_{page+1}'})
        
        keyboard_buttons.append(nav_buttons)
        keyboard_buttons.append([{'text': '⬅️ В админку', 'callback_data': 'admin_back'}])
        
        keyboard = create_inline_keyboard(keyboard_buttons)
        
        edit_telegram_message(chat_id, message_id, message, reply_markup=keyboard)
        return True
        
    except Exception as e:
        logger.error("Error showing completed tasks: %s", e)
        edit_telegram_message(chat_id, message_id, "❌ Ошибка при получении выполненных заданий.")
        return False
    finally:
        cur.close()
        conn.close()

def handle_return_task(chat_id, user_id, message_id, data, callback_id):
    """Обработка возврата задания родителем"""
    if not is_admin(user_id):
        send_telegram_callback_answer(callback_id, "❌ Только администратор может вернуть задание.", show_alert=True)
        return True
    
    send_telegram_callback_answer(callback_id)
    
    assignment_id = int(data.replace('return_task_', ''))
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Получаем информацию о выполненном задании
        cur.execute("""
            SELECT at.assignment_id, at.child_id, at.reward_received,
                   t.title, t.type, t.created_by as parent_id,
                   u.full_name as child_name
            FROM assigned_tasks at
            JOIN tasks t ON at.task_id = t.task_id
            JOIN users u ON at.child_id = u.user_id
            WHERE at.assignment_id = %s 
            AND at.is_completed = TRUE
            AND t.created_by = %s
        """, (assignment_id, user_id))
        
        task = cur.fetchone()
        
        if not task:
            edit_telegram_message(chat_id, message_id, 
                "❌ Задание не найдено, уже не выполнено или у вас нет прав.")
            return True
        
        assignment_id, child_id, reward_received, title, task_type, parent_id, child_name = task
        
        # Проверяем, что задание действительно выполнено и награда получена
        if not reward_received or reward_received <= 0:
            edit_telegram_message(chat_id, message_id, 
                "❌ За задание не было начислено баллов или оно еще не выполнено.")
            return True
        
        # 1. Возвращаем задание в статус "не выполнено"
        cur.execute("""
            UPDATE assigned_tasks 
            SET is_completed = FALSE, completed_at = NULL, reward_received = NULL
            WHERE assignment_id = %s
        """, (assignment_id,))
        
        # 2. Вычитаем баллы у ребенка
        cur.execute("""
            UPDATE users 
            SET balance = balance - %s 
            WHERE user_id = %s
        """, (reward_received, child_id))
        
        # 3. Записываем транзакцию на возврат
        cur.execute("""
            INSERT INTO transactions (child_id, amount, type, description)
            VALUES (%s, %s, 'task_return', %s)
        """, (child_id, -reward_received, f"Возврат задания '{title}' ({task_type})"))
        
        conn.commit()
        
        # Получаем новый баланс ребенка
        cur.execute("SELECT balance FROM users WHERE user_id = %s", (child_id,))
        new_balance = cur.fetchone()[0]
        
        # Уведомляем родителя
        message = (
            f"🔄 <b>Задание возвращено!</b>\n\n"
            f"👤 Ребенок: {child_name}\n"
            f"📋 Задание: {title}\n"
            f"📊 Тип: {task_type}\n"
            f"💰 Возвращено баллов: {reward_received}\n"
            f"💳 Новый баланс ребенка: {new_balance} баллов\n\n"
            f"✅ Задание снова доступно ребенку для выполнения."
        )
        
        edit_telegram_message(chat_id, message_id, message)
        
        # Уведомляем ребенка
        child_message = (
            f"⚠️ <b>Задание возвращено на доработку</b>\n\n"
            f"Привет, {child_name}! 👋\n\n"
            f"📋 <b>{title}</b>\n"
            f"🔄 Статус: <b>Требует доработки</b>\n"
            f"💰 Возвращено баллов: {reward_received}\n"
            f"💳 Твой баланс: {new_balance} баллов\n\n"
            f"<i>Родитель проверил задание и вернул его на доработку.</i>\n"
            f"Пожалуйста, выполни задание заново качественно!\n\n"
            f"Используй команду /tasks чтобы увидеть задание."
        )
        
        send_telegram_message(child_id, child_message)
        
        return True
        
    except Exception as e:
        logger.error("Error returning task: %s", e)
        edit_telegram_message(chat_id, message_id, "❌ Ошибка при возврате задания.")
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()
