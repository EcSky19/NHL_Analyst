import sqlite3

conn = sqlite3.connect('data/processed/nhl_research.db')
cursor = conn.cursor()

# Get schema for backtest_features_last5
print('backtest_features_last5 schema:')
cursor.execute("PRAGMA table_info(backtest_features_last5)")
for col in cursor.fetchall():
    print(f'  {col[1]}: {col[2]}')
    
print('\nbacktest_features_last5 column count:', len(cursor.fetchall()))

# Check historical_games_last5
print('\nhistorical_games_last5 schema:')
cursor.execute("PRAGMA table_info(historical_games_last5)")
cols = cursor.fetchall()
for col in cols:
    print(f'  {col[1]}: {col[2]}')
    
cursor.execute("SELECT COUNT(*) FROM historical_games_last5")
count = cursor.fetchone()[0]
print(f"  Total games: {count}")

# Sample game record
print("\nSample game record:")
cursor.execute("SELECT * FROM historical_games_last5 LIMIT 1")
cols_info = cursor.description
row = cursor.fetchone()
if row:
    for i, col in enumerate(cols_info):
        print(f"  {col[0]}: {row[i]}")
    
conn.close()
