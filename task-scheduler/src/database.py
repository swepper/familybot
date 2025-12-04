import os
import psycopg2
from dotenv import load_dotenv
import logging

load_dotenv()

logger = logging.getLogger(__name__)

def get_db_connection():
    """Получить соединение с базой данных"""
    DATABASE_URL = os.getenv('DATABASE_URL')
    
    if not DATABASE_URL:
        # Формируем URL для Yandex Managed PostgreSQL
        db_host = os.getenv('DB_HOST')
        db_port = os.getenv('DB_PORT', '6432')
        db_name = os.getenv('DB_NAME', 'family_bot')
        db_user = os.getenv('DB_USER', 'botuser')
        db_password = os.getenv('DB_PASSWORD')
        
        if db_host and db_user and db_password:
            DATABASE_URL = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}?sslmode=require"
        else:
            raise ValueError("Database configuration is missing")
    
    return psycopg2.connect(DATABASE_URL)

def init_db():
    """Инициализировать базу данных"""
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # Создаем таблицы
        with open('schema.sql', 'r') as f:
            schema_sql = f.read()
            cur.execute(schema_sql)

        conn.commit()
        logger.info("Database initialized successfully!")
        
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        conn.rollback()
        
    finally:
        cur.close()
        conn.close()