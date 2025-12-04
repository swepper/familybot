# src/telegram_api.py
import os
import requests
import logging

logger = logging.getLogger(__name__)

def send_telegram_message(chat_id, text, reply_markup=None, parse_mode='HTML'):
    """Отправка сообщения в Telegram"""
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set")
        return False
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': parse_mode
    }
    
    if reply_markup:
        payload['reply_markup'] = reply_markup
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            return True
        else:
            logger.error("Telegram API error: %s", response.text)
            return False
    except Exception as e:
        logger.error("Error sending message: %s", e)
        return False

def create_inline_keyboard(buttons):
    """Создание inline клавиатуры"""
    keyboard = []
    for button_row in buttons:
        row = []
        for button in button_row:
            row.append({
                'text': button['text'],
                'callback_data': button['callback_data']
            })
        keyboard.append(row)
    
    return {'inline_keyboard': keyboard}