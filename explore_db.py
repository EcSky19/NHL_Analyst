import sqlite3

conn = sqlite3.connect('data/processed/nhl_research.db')
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = cursor.fetchall()
print('Tables in nhl_research.db:')
for row in tables:
    print(f'  - {row[0]}')
    
# Get schema for backtest_features
try:
    cursor.execute("PRAGMA table_info(backtest_features)")
    print('\nbacktest_features schema:')
    for col in cursor.fetchall():
        print(f'  {col[1]}: {col[2]}')
except Exception as e:
    print(f"backtest_features not found: {e}")
    
# Look at games table
try:
    cursor.execute("PRAGMA table_info(games)")
    print('\ngames schema:')
    for col in cursor.fetchall():
        print(f'  {col[1]}: {col[2]}')
    cursor.execute("SELECT COUNT(*) FROM games")
    count = cursor.fetchone()[0]
    print(f"  Total games: {count}")
except Exception as e:
    print(f"games table: {e}")
    
conn.close()
