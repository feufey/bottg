import sqlite3
from datetime import datetime

# Подключаемся к старой и новой базам данных
old_db = sqlite3.connect('user_stats.db')
new_db = sqlite3.connect('database.sqlite')

# Создаем курсоры для выполнения SQL-запросов
old_cursor = old_db.cursor()
new_cursor = new_db.cursor()

# Выполняем запрос к старой базе данных
old_cursor.execute("SELECT user_id, balik, refka FROM user_stats")
rows = old_cursor.fetchall()

# Переносим данные в новую базу данных
for row in rows:
    user_id, balance, referal_id = row
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        new_cursor.execute("INSERT INTO user (user_id, balance, referral_id, timestamp) VALUES (?, ?, ?, ?)",
                           (user_id, balance, referal_id, timestamp))
    except sqlite3.IntegrityError:
        print(f"User with id {user_id} already exists. Skipping...")

# Сохраняем изменения и закрываем соединения
new_db.commit()
old_db.close()
new_db.close()