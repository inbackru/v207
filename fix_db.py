
  import os
  from sqlalchemy import create_engine, text

  db_url = os.environ.get('DATABASE_URL')
  if db_url:
      engine = create_engine(db_url)
      with engine.connect() as conn:
          try:
              conn.execute(text("ALTER TABLE managers ADD COLUMN IF NOT EXISTS show_on_index BOOLEAN DEFAULT FALSE"))
              conn.commit()
              print("Successfully added column show_on_index to managers table")
          except Exception as e:
              print(f"Error adding column: {e}")
  