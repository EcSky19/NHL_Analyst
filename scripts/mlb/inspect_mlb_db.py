import sqlite3
con = sqlite3.connect(r'data\mlb\mlb_research.db')
print('tables/views')
for row in con.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table','view') ORDER BY name"):
    print(row)
print('\nschemas')
for (name,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
    print('\n' + name)
    for col in con.execute(f'PRAGMA table_info({name})'):
        print(col)
    print('count', con.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0])
