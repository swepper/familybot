import os
import json
import logging
from src.bot import process_update_sync

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def is_telegram_request(event):
    """Простая проверка, что запрос от Telegram"""
    # Проверяем наличие update_id в теле запроса
    if 'body' not in event:
        return False
    
    try:
        body = event['body']
        if event.get('isBase64Encoded', False):
            import base64
            body = base64.b64decode(body).decode('utf-8')
        
        import json
        data = json.loads(body)
        return 'update_id' in data  # Все обновления от Telegram имеют update_id
    except:
        return False

def handler(event, context):
    """
    Синхронный обработчик для Yandex Cloud Functions
    """
    logger.info("Received event")

    # ОБНОВЛЕНИЕ: Обработка cron-вызовов для автоматических заданий
    if event.get('httpMethod') == 'POST' and event.get('path') == '/cron/assign-tasks':
        return handle_cron_assign_tasks(event, context)
    
    # Проверяем, что это запрос от Telegram
    if not is_telegram_request(event):
        logger.warning("Request not from Telegram")
        return {
            'statusCode': 403,
            'body': json.dumps({'error': 'Forbidden'})
        }

    # Получаем тело запроса
    if 'body' in event:
        body = event['body']
        if event.get('isBase64Encoded', False):
            import base64
            body = base64.b64decode(body).decode('utf-8')
        
        try:
            update_data = json.loads(body)
            logger.info("Update data: %s", update_data)
        except json.JSONDecodeError as e:
            logger.error("JSON decode error: %s", e)
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Invalid JSON'})
            }
    else:
        logger.error("No body in request")
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'No body in request'})
        }
    
    # Синхронная обработка обновления
    try:
        success = process_update_sync(update_data)
        
        if success:
            return {
                'statusCode': 200,
                'body': json.dumps({'status': 'ok'})
            }
        else:
            return {
                'statusCode': 500,
                'body': json.dumps({'error': 'Processing failed'})
            }
            
    except Exception as e:
        logger.error("Error processing update: %s", e)
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
    # ОБНОВЛЕНИЕ: Обработка cron-вызовов для автоматических заданий
    if event.get('httpMethod') == 'POST' and event.get('path') == '/cron/assign-tasks':
        return handle_cron_assign_tasks(event, context)
    
    # Проверяем, что это запрос от Telegram
    if not is_telegram_request(event):
        logger.warning("Request not from Telegram")
        return {
            'statusCode': 403,
            'body': json.dumps({'error': 'Forbidden'})
        }
        
def health_check(event, context):
    """
    Health check для мониторинга
    """
    return {
        'statusCode': 200,
        'body': json.dumps({'status': 'healthy'})
    }