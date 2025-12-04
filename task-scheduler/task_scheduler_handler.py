# task_scheduler_handler.py - handler для отдельной функции
import os
import json
import logging
from datetime import datetime
from src.task_scheduler import TaskScheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def handler(event, context):
    """
    Обработчик для отдельной cron-функции выдачи заданий
    Вызывается автоматически каждый день в заданное время
    """
    logger.info("Task scheduler function started")
    
    try:
        # Проверка секретного ключа
        cron_secret = os.getenv('CRON_SECRET')
        
        if cron_secret:
            headers = event.get('headers', {})
            received_secret = headers.get('X-Cron-Secret')
            
            if received_secret != cron_secret:
                logger.warning(f"Invalid cron secret. Received: {received_secret}")
                return {
                    'statusCode': 403,
                    'body': json.dumps({'error': 'Forbidden'})
                }
        
        # Выполняем выдачу заданий
        logger.info("Starting task assignment...")
        result = TaskScheduler.run_scheduled_tasks()
        
        # Формируем ответ
        response = {
            'status': 'success',
            'timestamp': datetime.now().isoformat(),
            'results': result,
            'message': f"Assigned {result.get('total', 0)} tasks total"
        }
        
        logger.info(f"Task scheduler completed: {response}")
        
        return {
            'statusCode': 200,
            'body': json.dumps(response, ensure_ascii=False, default=str)
        }
        
    except Exception as e:
        logger.error(f"Error in task scheduler: {e}", exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps({
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            })
        }