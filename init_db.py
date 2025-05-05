import sqlite3

DB_FILE = "currency.db" 

conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS currency (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER DEFAULT 100
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS stats (
    user_id INTEGER PRIMARY KEY,
    games_played INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    total_earned INTEGER DEFAULT 0,
    most_common_symbol TEXT DEFAULT '{}',
    largest_win INTEGER DEFAULT 0
)
""")

conn.commit()
conn.close()

print("Database initialized with tables")