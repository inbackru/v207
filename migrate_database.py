#!/usr/bin/env python3
"""
Database Migration Script
Migrates data from external Neon database to Replit PostgreSQL database
"""
import os
import sys
from sqlalchemy import create_engine, text
from app import app, db
import models

# External database connection string
EXTERNAL_DB_URL = "postgresql://neondb_owner:npg_NEWUZCsHMw23@ep-bitter-butterfly-a6glc4a9.us-west-2.aws.neon.tech/neondb?sslmode=require"

def migrate_database():
    """Migrate data from external database to Replit database"""
    
    print("=" * 60)
    print("DATABASE MIGRATION SCRIPT")
    print("=" * 60)
    print()
    
    # Get current Replit database URL
    replit_db_url = os.environ.get('DATABASE_URL')
    if not replit_db_url:
        print("❌ ERROR: DATABASE_URL environment variable not set")
        return False
    
    print(f"✅ Source (External): Neon Database")
    print(f"✅ Target (Replit): {replit_db_url.split('@')[1].split('/')[0]}")
    print()
    
    try:
        # Create engine for external database
        print("🔄 Connecting to external database...")
        external_engine = create_engine(EXTERNAL_DB_URL)
        
        # Test connection
        with external_engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.fetchone()[0]
            print(f"✅ Connected to external database: {version.split(',')[0]}")
        
        # Create all tables in new database
        print("\n🔄 Creating tables in Replit database...")
        with app.app_context():
            db.create_all()
            print("✅ Tables created successfully")
        
        # Get list of tables to migrate
        print("\n🔄 Getting table list from external database...")
        with external_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT tablename 
                FROM pg_tables 
                WHERE schemaname = 'public'
                ORDER BY tablename
            """))
            tables = [row[0] for row in result.fetchall()]
            print(f"✅ Found {len(tables)} tables to migrate")
        
        # Migrate each table
        print("\n" + "=" * 60)
        print("MIGRATING DATA")
        print("=" * 60)
        
        migrated_count = 0
        skipped_count = 0
        
        for table in tables:
            # Skip alembic version table if it exists
            if table == 'alembic_version':
                print(f"⏭️  Skipping {table}")
                skipped_count += 1
                continue
            
            try:
                # Get row count from external database
                with external_engine.connect() as ext_conn:
                    count_result = ext_conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                    row_count = count_result.fetchone()[0]
                
                if row_count == 0:
                    print(f"⏭️  {table}: No data to migrate")
                    skipped_count += 1
                    continue
                
                # Read data from external database
                with external_engine.connect() as ext_conn:
                    data = ext_conn.execute(text(f"SELECT * FROM {table}"))
                    rows = data.fetchall()
                    columns = data.keys()
                
                # Insert data into Replit database
                replit_engine = create_engine(replit_db_url)
                with replit_engine.connect() as repl_conn:
                    # Start transaction
                    trans = repl_conn.begin()
                    try:
                        # Truncate target table first
                        repl_conn.execute(text(f"TRUNCATE TABLE {table} CASCADE"))
                        
                        # Insert rows
                        for row in rows:
                            # Build insert statement
                            cols = ', '.join(columns)
                            placeholders = ', '.join([f":{col}" for col in columns])
                            insert_sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"
                            
                            # Create dict for parameters
                            row_dict = dict(zip(columns, row))
                            repl_conn.execute(text(insert_sql), row_dict)
                        
                        trans.commit()
                        print(f"✅ {table}: Migrated {row_count} rows")
                        migrated_count += 1
                    except Exception as e:
                        trans.rollback()
                        print(f"❌ {table}: Error - {str(e)}")
                        skipped_count += 1
                
            except Exception as e:
                print(f"❌ {table}: Error - {str(e)}")
                skipped_count += 1
        
        # Summary
        print("\n" + "=" * 60)
        print("MIGRATION SUMMARY")
        print("=" * 60)
        print(f"✅ Successfully migrated: {migrated_count} tables")
        print(f"⏭️  Skipped: {skipped_count} tables")
        print(f"📊 Total tables: {len(tables)}")
        print()
        
        if migrated_count > 0:
            print("🎉 Migration completed successfully!")
            print()
            print("Next steps:")
            print("1. The DATABASE_URL environment variable is already set to the Replit database")
            print("2. Your application will now use the Replit PostgreSQL database")
            print("3. You can safely remove the external database credentials")
            return True
        else:
            print("⚠️  No tables were migrated. Please check the errors above.")
            return False
        
    except Exception as e:
        print(f"\n❌ FATAL ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("\n⚠️  WARNING: This will overwrite all data in the Replit database!")
    print("Make sure you have a backup of your data before proceeding.")
    print()
    response = input("Do you want to continue? (yes/no): ")
    
    if response.lower() in ['yes', 'y', 'да']:
        success = migrate_database()
        sys.exit(0 if success else 1)
    else:
        print("\n❌ Migration cancelled by user")
        sys.exit(0)
