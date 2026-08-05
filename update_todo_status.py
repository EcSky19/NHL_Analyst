import sqlite3

DB_PATH = "data/processed/nhl_research.db"

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# Check if todos table exists
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='todos'")
if cursor.fetchone():
    # Update the feature-engineering-v2 todo to done
    cursor.execute("""
        UPDATE todos 
        SET status = 'done'
        WHERE id = 'feature-engineering-v2'
    """)
    
    conn.commit()
    
    # Verify the update
    cursor.execute("SELECT id, status FROM todos WHERE id = 'feature-engineering-v2'")
    result = cursor.fetchone()
    
    if result:
        print(f"[SUCCESS] Updated todo: {result[0]} -> {result[1]}")
    else:
        print("[WARNING] Todo not found in database")
        print("Creating todo entry...")
        cursor.execute("""
            INSERT OR IGNORE INTO todos (id, title, description, status)
            VALUES ('feature-engineering-v2', 'Feature Engineering v2', 
                    'Design and implement advanced feature families', 'done')
        """)
        conn.commit()
        print("[SUCCESS] Todo created and marked as done")
else:
    print("[ERROR] todos table does not exist in database")

conn.close()
print("\nTask completion status updated!")
