import os
import logging
from datetime import datetime, time, date, timedelta
from src.database import get_db_connection
from src.telegram_api import send_telegram_message, create_inline_keyboard

logger = logging.getLogger(__name__)

class TaskScheduler:
    @staticmethod
    def assign_daily_tasks():
        """Автоматическая выдача ежедневных заданий всем детям"""
        conn = get_db_connection()
        cur = conn.cursor()
        
        try:
            logger.info("Starting daily tasks assignment...")
            
            # Получаем всех активных администраторов, у которых есть ежедневные задания
            cur.execute("""
                SELECT DISTINCT t.created_by, u.full_name as admin_name
                FROM tasks t
                JOIN users u ON t.created_by = u.user_id
                WHERE t.type = 'daily' 
                AND t.is_active = TRUE
                AND u.role = 'admin'
            """)
            admins = cur.fetchall()
            
            if not admins:
                logger.info("No admins with active daily tasks found")
                return 0
            
            total_assigned = 0
            admin_results = []
            today = date.today()
            
            for admin_id, admin_name in admins:
                try:
                    assigned, children_notified = TaskScheduler._assign_admin_daily_tasks(admin_id, admin_name, cur, today)
                    total_assigned += assigned
                    
                    if assigned > 0:
                        admin_results.append({
                            'admin_id': admin_id,
                            'admin_name': admin_name,
                            'tasks_assigned': assigned,
                            'children_notified': children_notified
                        })
                        
                        logger.info(f"Admin {admin_name} ({admin_id}): {assigned} tasks assigned, {children_notified} children notified")
                        
                except Exception as e:
                    logger.error(f"Error assigning tasks for admin {admin_id} ({admin_name}): {e}")
            
            # Логируем общий результат (если таблица существует)
            try:
                cur.execute("""
                    INSERT INTO task_assignment_logs 
                    (task_type, assigned_count, success_count, error_count)
                    VALUES ('daily', %s, %s, %s)
                """, (total_assigned, len(admin_results), len(admins) - len(admin_results)))
            except Exception as e:
                logger.warning(f"Could not log to task_assignment_logs (table might not exist): {e}")
            
            conn.commit()
            logger.info(f"Daily tasks assignment completed: {total_assigned} tasks assigned by {len(admin_results)}/{len(admins)} admins")
            
            # Отправляем отчет администраторам
            if admin_results:
                TaskScheduler._notify_admins_about_assignment(admin_results, 'daily')
            
            return total_assigned
            
        except Exception as e:
            logger.error(f"Error in assign_daily_tasks: {e}")
            conn.rollback()
            return 0
        finally:
            cur.close()
            conn.close()
    
    @staticmethod
    def _assign_admin_daily_tasks(admin_id, admin_name, cursor, today_date):
        """Выдать ежедневные задания от конкретного администратора"""
        # Получаем активные ежедневные задания администратора
        cursor.execute("""
            SELECT task_id, title, due_time, reward 
            FROM tasks 
            WHERE type = 'daily' 
            AND is_active = TRUE 
            AND created_by = %s
        """, (admin_id,))
        
        daily_tasks = cursor.fetchall()
        
        if not daily_tasks:
            return 0, 0
        
        # Получаем всех детей этого администратора
        cursor.execute("""
            SELECT user_id, full_name, username 
            FROM users 
            WHERE role = 'child' 
            AND (parent_id = %s OR parent_id IS NULL)
        """, (admin_id,))
        
        children = cursor.fetchall()
        
        if not children:
            return 0, 0
        
        assigned_count = 0
        children_notified = set()  # Множество для отслеживания детей, получивших уведомления
        
        for child_id, child_name, child_username in children:
            child_assigned = 0
            
            for task_id, task_title, due_time, task_reward in daily_tasks:
                # Рассчитываем due_date (сегодня + due_time)
                due_date = datetime.combine(today_date, due_time)
                
                # Проверяем, не выдано ли уже задание сегодня
                cursor.execute("""
                    SELECT assignment_id FROM assigned_tasks 
                    WHERE task_id = %s 
                    AND child_id = %s 
                    AND assigned_date = CURRENT_DATE
                """, (task_id, child_id))
                
                if not cursor.fetchone():
                    # Выдаем задание
                    cursor.execute("""
                        INSERT INTO assigned_tasks 
                        (task_id, child_id, assigned_date, due_date, is_completed)
                        VALUES (%s, %s, CURRENT_DATE, %s, FALSE)
                    """, (task_id, child_id, due_date))
                    assigned_count += 1
                    child_assigned += 1
            
            # Если ребенку назначили хотя бы одно задание, отправляем уведомление
            if child_assigned > 0:
                if TaskScheduler._notify_child_about_new_tasks(child_id, child_name, daily_tasks, 'daily'):
                    children_notified.add(child_id)
        
        return assigned_count, len(children_notified)
    
    @staticmethod
    def assign_weekly_tasks():
        """Автоматическая выдача еженедельных заданий"""
        conn = get_db_connection()
        cur = conn.cursor()
        
        try:
            logger.info("Starting weekly tasks assignment...")
            
            # Проверяем, какой сегодня день недели (0=понедельник, 6=воскресенье)
            today_weekday = datetime.now().weekday()
            weekday_map = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
            today_day_name = weekday_map[today_weekday]
            
            # Получаем еженедельные задания на сегодня с информацией об администраторе
            cur.execute("""
                SELECT DISTINCT t.created_by, u.full_name as admin_name, 
                       t.task_id, t.title, t.due_time, t.reward
                FROM tasks t
                JOIN users u ON t.created_by = u.user_id
                WHERE t.type = 'weekly' 
                AND t.is_active = TRUE
                AND t.due_day = %s
                AND u.role = 'admin'
            """, (today_day_name,))
            
            weekly_tasks = cur.fetchall()
            
            if not weekly_tasks:
                logger.info(f"No weekly tasks scheduled for {today_day_name}")
                return 0
            
            total_assigned = 0
            task_results = {}
            today = date.today()
            
            # Группируем задания по администраторам
            for admin_id, admin_name, task_id, task_title, due_time, task_reward in weekly_tasks:
                if admin_id not in task_results:
                    task_results[admin_id] = {
                        'admin_name': admin_name,
                        'tasks': [],
                        'total_assigned': 0,
                        'children_notified': set()
                    }
                
                task_results[admin_id]['tasks'].append({
                    'task_id': task_id,
                    'title': task_title,
                    'due_time': due_time,
                    'reward': task_reward
                })
            
            # Выдаем задания для каждого администратора
            for admin_id, admin_data in task_results.items():
                try:
                    assigned, children_notified = TaskScheduler._assign_admin_weekly_tasks(
                        admin_id, admin_data['admin_name'], admin_data['tasks'], cur, today
                    )
                    
                    admin_data['total_assigned'] = assigned
                    admin_data['children_notified'] = children_notified
                    total_assigned += assigned
                    
                    logger.info(f"Admin {admin_data['admin_name']} ({admin_id}): {assigned} weekly tasks assigned, {len(children_notified)} children notified")
                    
                except Exception as e:
                    logger.error(f"Error assigning weekly tasks for admin {admin_id}: {e}")
            
            # Логируем общий результат
            try:
                cur.execute("""
                    INSERT INTO task_assignment_logs 
                    (task_type, assigned_count, success_count, error_count)
                    VALUES ('weekly', %s, %s, %s)
                """, (total_assigned, len([a for a in task_results.values() if a['total_assigned'] > 0]), 0))
            except Exception as e:
                logger.warning(f"Could not log to task_assignment_logs: {e}")
            
            conn.commit()
            logger.info(f"Weekly tasks assignment completed: {total_assigned} tasks assigned")
            
            # Отправляем отчет администраторам
            successful_admins = [data for data in task_results.values() if data['total_assigned'] > 0]
            if successful_admins:
                TaskScheduler._notify_admins_about_assignment(successful_admins, 'weekly')
            
            return total_assigned
            
        except Exception as e:
            logger.error(f"Error in assign_weekly_tasks: {e}")
            conn.rollback()
            return 0
        finally:
            cur.close()
            conn.close()
    
    @staticmethod
    def _assign_admin_weekly_tasks(admin_id, admin_name, tasks, cursor, today_date):
        """Выдать еженедельные задания от конкретного администратора"""
        # Получаем детей этого администратора
        cursor.execute("""
            SELECT user_id, full_name, username 
            FROM users 
            WHERE role = 'child' 
            AND (parent_id = %s OR parent_id IS NULL)
        """, (admin_id,))
        
        children = cursor.fetchall()
        
        if not children:
            return 0, set()
        
        assigned_count = 0
        children_notified = set()
        
        for child_id, child_name, child_username in children:
            child_assigned = 0
            child_tasks = []
            
            for task in tasks:
                task_id = task['task_id']
                
                # Проверяем, не выдано ли уже задание на этой неделе
                cursor.execute("""
                    SELECT assignment_id FROM assigned_tasks 
                    WHERE task_id = %s 
                    AND child_id = %s 
                    AND assigned_date >= DATE_TRUNC('week', CURRENT_DATE)
                    AND assigned_date < DATE_TRUNC('week', CURRENT_DATE) + INTERVAL '1 week'
                """, (task_id, child_id))
                
                if not cursor.fetchone():
                    # Рассчитываем due_date (сегодня + due_time)
                    due_date = datetime.combine(today_date, task['due_time'])
                    
                    # Выдаем задание
                    cursor.execute("""
                        INSERT INTO assigned_tasks 
                        (task_id, child_id, assigned_date, due_date, is_completed)
                        VALUES (%s, %s, CURRENT_DATE, %s, FALSE)
                    """, (task_id, child_id, due_date))
                    assigned_count += 1
                    child_assigned += 1
                    child_tasks.append(task)
            
            # Если ребенку назначили задания, отправляем уведомление
            if child_assigned > 0:
                if TaskScheduler._notify_child_about_new_tasks(child_id, child_name, child_tasks, 'weekly'):
                    children_notified.add(child_id)
        
        return assigned_count, children_notified
    
    @staticmethod
    def _notify_child_about_new_tasks(child_id, child_name, tasks, task_type):
        """Отправить уведомление ребенку о новых заданиях"""
        try:
            if task_type == 'daily':
                task_emoji = "📅"
                task_type_text = "ежедневные"
                greeting = f"Привет, {child_name}! 👋"
            else:  # weekly
                task_emoji = "🗓️"
                task_type_text = "еженедельные"
                greeting = f"С началом новой недели, {child_name}! ✨"
            
            if len(tasks) == 1:
                task = tasks[0]
                if isinstance(task, tuple):
                    # Старый формат (task_id, title, due_time, reward)
                    task_id, title, due_time, reward = task
                    due_time_str = due_time.strftime('%H:%M') if due_time else "сегодня"
                    message = (
                        f"{greeting}\n\n"
                        f"{task_emoji} <b>У тебя новое {task_type_text} задание!</b>\n\n"
                        f"📋 <b>{title}</b>\n"
                        f"💰 Награда: <b>{reward} баллов</b>\n"
                        f"⏰ Выполнить до: <b>{due_time_str}</b>\n\n"
                        f"Используй команду /tasks чтобы посмотреть все свои задания!\n"
                        f"Удачи! 💪"
                    )
                else:
                    # Новый формат (словарь)
                    title = task.get('title', 'Задание')
                    reward = task.get('reward', 0)
                    due_time = task.get('due_time')
                    due_time_str = due_time.strftime('%H:%M') if due_time else "сегодня"
                    message = (
                        f"{greeting}\n\n"
                        f"{task_emoji} <b>У тебя новое {task_type_text} задание!</b>\n\n"
                        f"📋 <b>{title}</b>\n"
                        f"💰 Награда: <b>{reward} баллов</b>\n"
                        f"⏰ Выполнить до: <b>{due_time_str}</b>\n\n"
                        f"Используй команду /tasks чтобы посмотреть все свои задания!\n"
                        f"Удачи! 💪"
                    )
            else:
                # Несколько заданий
                message = (
                    f"{greeting}\n\n"
                    f"{task_emoji} <b>У тебя новые {task_type_text} задания!</b>\n\n"
                    f"📋 <b>Список заданий:</b>\n"
                )
                
                for i, task in enumerate(tasks, 1):
                    if isinstance(task, tuple):
                        task_id, title, due_time, reward = task
                        due_time_str = due_time.strftime('%H:%M') if due_time else ""
                    else:
                        title = task.get('title', f'Задание {i}')
                        reward = task.get('reward', 0)
                        due_time = task.get('due_time')
                        due_time_str = due_time.strftime('%H:%M') if due_time else ""
                    
                    message += f"{i}. <b>{title}</b> - {reward} баллов"
                    if due_time_str:
                        message += f" (до {due_time_str})"
                    message += "\n"
                
                message += (
                    f"\n💰 <b>Всего можно получить: {sum(t[3] if isinstance(t, tuple) else t.get('reward', 0) for t in tasks)} баллов</b>\n\n"
                    f"Используй команду /tasks чтобы посмотреть все свои задания!\n"
                    f"Удачи! 💪"
                )
            
            return send_telegram_message(child_id, message)
            
        except Exception as e:
            logger.error(f"Error notifying child {child_id} about new tasks: {e}")
            return False
    
    @staticmethod
    def _notify_admins_about_assignment(admin_results, task_type):
        """Отправить отчет администраторам о выданных заданиях"""
        try:
            for admin_data in admin_results:
                if isinstance(admin_data, dict):
                    admin_id = admin_data.get('admin_id')
                    admin_name = admin_data.get('admin_name', 'Администратор')
                    tasks_assigned = admin_data.get('tasks_assigned', 0)
                    children_notified = admin_data.get('children_notified', 0)
                    
                    if task_type == 'daily':
                        emoji = "📅"
                        task_text = "ежедневные"
                    else:
                        emoji = "🗓️"
                        task_text = "еженедельные"
                    
                    if tasks_assigned > 0:
                        message = (
                            f"{emoji} <b>Отчет о выдаче {task_text} заданий</b>\n\n"
                            f"✅ Задания успешно выданы!\n\n"
                            f"📊 <b>Статистика:</b>\n"
                            f"📝 Выдано заданий: {tasks_assigned}\n"
                            f"👶 Детей получили задания: {children_notified}\n\n"
                            f"Дети получили уведомления о новых заданиях. 📨"
                        )
                        
                        # Добавляем кнопку для просмотра заданий
                        keyboard = create_inline_keyboard([
                            [{'text': '📋 Посмотреть задания', 'callback_data': 'admin_list_tasks'}]
                        ])
                        
                        send_telegram_message(admin_id, message, reply_markup=keyboard)
                        
        except Exception as e:
            logger.error(f"Error notifying admins about assignment: {e}")
    
    @staticmethod
    def run_scheduled_tasks():
        """Запустить все запланированные задачи (ежедневные + еженедельные)"""
        logger.info("Starting scheduled tasks assignment...")
        
        daily_count = TaskScheduler.assign_daily_tasks()
        weekly_count = TaskScheduler.assign_weekly_tasks()
        
        total_count = daily_count + weekly_count
        
        logger.info(f"Scheduled tasks completed: {daily_count} daily, {weekly_count} weekly, total: {total_count}")
        
        return {
            'daily': daily_count,
            'weekly': weekly_count,
            'total': total_count
        }
    
    @staticmethod
    def get_assignment_stats(days=7):
        """Получить статистику выдачи заданий за последние N дней"""
        conn = get_db_connection()
        cur = conn.cursor()
        
        try:
            cur.execute("""
                SELECT 
                    task_type,
                    COUNT(*) as assignment_count,
                    SUM(assigned_count) as total_tasks_assigned,
                    AVG(assigned_count) as avg_tasks_per_day,
                    MIN(created_at) as first_date,
                    MAX(created_at) as last_date
                FROM task_assignment_logs 
                WHERE created_at >= CURRENT_DATE - INTERVAL '%s days'
                GROUP BY task_type
                ORDER BY task_type
            """, (days,))
            
            stats = cur.fetchall()
            
            result = {}
            for task_type, count, total, avg, first_date, last_date in stats:
                result[task_type] = {
                    'assignment_count': count,
                    'total_tasks_assigned': total,
                    'avg_tasks_per_day': float(avg) if avg else 0,
                    'period': {
                        'first_date': first_date,
                        'last_date': last_date
                    }
                }
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting assignment stats: {e}")
            return {}
        finally:
            cur.close()
            conn.close()