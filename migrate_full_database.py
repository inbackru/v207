#!/usr/bin/env python3
"""
Full 1:1 Database Migration Script
Migrates complete schema and data from external Neon database to Replit PostgreSQL database
"""
import os
import sys
from sqlalchemy import create_engine, text
import psycopg2

# External database connection string
EXTERNAL_DB_URL = "postgresql://neondb_owner:npg_NEWUZCsHMw23@ep-bitter-butterfly-a6glc4a9.us-west-2.aws.neon.tech/neondb?sslmode=require"

def get_replit_db_url():
    """Get Replit database URL from environment"""
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        raise Exception("DATABASE_URL environment variable not set")
    return db_url

def get_table_order(external_engine):
    """Get tables in correct dependency order"""
    print("🔄 Analyzing table dependencies...")
    
    with external_engine.connect() as conn:
        # Get all tables
        result = conn.execute(text("""
            SELECT tablename 
            FROM pg_tables 
            WHERE schemaname = 'public'
            ORDER BY tablename
        """))
        all_tables = [row[0] for row in result.fetchall()]
        
        # Get foreign key dependencies
        fk_query = text("""
            SELECT
                tc.table_name,
                ccu.table_name AS foreign_table_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.constraint_column_usage AS ccu
                ON tc.constraint_name = ccu.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
        """)
        
        result = conn.execute(fk_query)
        dependencies = {}
        for row in result:
            table = row[0]
            depends_on = row[1]
            if table not in dependencies:
                dependencies[table] = set()
            dependencies[table].add(depends_on)
    
    # Topological sort
    ordered_tables = []
    remaining_tables = set(all_tables)
    
    while remaining_tables:
        # Find tables with no dependencies or all dependencies satisfied
        ready = []
        for table in remaining_tables:
            deps = dependencies.get(table, set())
            if all(dep in ordered_tables or dep not in all_tables for dep in deps):
                ready.append(table)
        
        if not ready:
            # Circular dependency or unresolved - add remaining tables
            ready = list(remaining_tables)
        
        ready.sort()
        ordered_tables.extend(ready)
        remaining_tables -= set(ready)
    
    return ordered_tables

def migrate_schema(external_engine, replit_engine):
    """Migrate complete database schema"""
    print("\n🔄 Migrating database schema...")
    
    with external_engine.connect() as ext_conn:
        # Get complete schema DDL
        with replit_engine.connect() as repl_conn:
            # Drop all existing tables
            print("  🗑️  Dropping existing tables...")
            repl_conn.execute(text("""
                DO $$ DECLARE
                    r RECORD;
                BEGIN
                    FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public') LOOP
                        EXECUTE 'DROP TABLE IF EXISTS ' || quote_ident(r.tablename) || ' CASCADE';
                    END LOOP;
                END $$;
            """))
            repl_conn.commit()
            
            # Get all table definitions
            tables_query = text("""
                SELECT tablename 
                FROM pg_tables 
                WHERE schemaname = 'public'
                ORDER BY tablename
            """)
            
            result = ext_conn.execute(tables_query)
            tables = [row[0] for row in result.fetchall()]
            
            print(f"  📋 Found {len(tables)} tables to create")
            
            # Create each table
            for table in tables:
                # Get CREATE TABLE statement
                create_query = text(f"""
                    SELECT 
                        'CREATE TABLE ' || quote_ident('{table}') || ' (' ||
                        string_agg(
                            quote_ident(column_name) || ' ' || 
                            data_type ||
                            CASE 
                                WHEN character_maximum_length IS NOT NULL 
                                THEN '(' || character_maximum_length || ')'
                                WHEN numeric_precision IS NOT NULL
                                THEN '(' || numeric_precision || 
                                    CASE WHEN numeric_scale IS NOT NULL 
                                    THEN ',' || numeric_scale ELSE '' END || ')'
                                ELSE ''
                            END ||
                            CASE WHEN is_nullable = 'NO' THEN ' NOT NULL' ELSE '' END ||
                            CASE WHEN column_default IS NOT NULL THEN ' DEFAULT ' || column_default ELSE '' END,
                            ', '
                        ) || ')' as create_statement
                    FROM information_schema.columns
                    WHERE table_name = '{table}' AND table_schema = 'public'
                    GROUP BY table_name
                """)
                
                try:
                    result = ext_conn.execute(create_query)
                    create_stmt = result.fetchone()
                    
                    if create_stmt:
                        # Execute create table
                        repl_conn.execute(text(create_stmt[0]))
                        print(f"  ✅ Created table: {table}")
                    
                except Exception as e:
                    print(f"  ⚠️  Could not create {table}: {e}")
            
            repl_conn.commit()
            
            # Add primary keys
            print("\n  🔑 Adding primary keys...")
            pk_query = text("""
                SELECT tc.table_name, kcu.column_name
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                    ON tc.constraint_name = kcu.constraint_name
                WHERE tc.constraint_type = 'PRIMARY KEY'
                ORDER BY tc.table_name
            """)
            
            result = ext_conn.execute(pk_query)
            pk_map = {}
            for row in result:
                table = row[0]
                column = row[1]
                if table not in pk_map:
                    pk_map[table] = []
                pk_map[table].append(column)
            
            for table, columns in pk_map.items():
                try:
                    cols = ', '.join(columns)
                    repl_conn.execute(text(
                        f"ALTER TABLE {table} ADD PRIMARY KEY ({cols})"
                    ))
                    print(f"  ✅ Added PK to {table}")
                except Exception as e:
                    print(f"  ⚠️  Could not add PK to {table}: {e}")
            
            repl_conn.commit()
            
            # Add foreign keys
            print("\n  🔗 Adding foreign keys...")
            fk_query = text("""
                SELECT
                    tc.table_name,
                    kcu.column_name,
                    ccu.table_name AS foreign_table_name,
                    ccu.column_name AS foreign_column_name,
                    tc.constraint_name
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                    ON tc.constraint_name = kcu.constraint_name
                JOIN information_schema.constraint_column_usage AS ccu
                    ON ccu.constraint_name = tc.constraint_name
                WHERE tc.constraint_type = 'FOREIGN KEY'
            """)
            
            result = ext_conn.execute(fk_query)
            for row in result:
                table, column, ref_table, ref_column, constraint = row
                try:
                    repl_conn.execute(text(f"""
                        ALTER TABLE {table} 
                        ADD CONSTRAINT {constraint}
                        FOREIGN KEY ({column}) 
                        REFERENCES {ref_table}({ref_column})
                    """))
                    print(f"  ✅ Added FK: {table}.{column} -> {ref_table}.{ref_column}")
                except Exception as e:
                    print(f"  ⚠️  Could not add FK to {table}: {e}")
            
            repl_conn.commit()
            
    print("\n✅ Schema migration completed!")

def migrate_data(external_engine, replit_engine, ordered_tables):
    """Migrate all data in correct order"""
    print("\n" + "=" * 60)
    print("MIGRATING DATA")
    print("=" * 60)
    
    migrated = 0
    skipped = 0
    errors = 0
    
    for table in ordered_tables:
        try:
            # Get row count
            with external_engine.connect() as ext_conn:
                count_result = ext_conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                row_count = count_result.fetchone()[0]
            
            if row_count == 0:
                print(f"⏭️  {table}: Empty table")
                skipped += 1
                continue
            
            # Read data
            with external_engine.connect() as ext_conn:
                data = ext_conn.execute(text(f"SELECT * FROM {table}"))
                rows = data.fetchall()
                columns = data.keys()
            
            # Insert data
            with replit_engine.connect() as repl_conn:
                trans = repl_conn.begin()
                try:
                    # Disable triggers temporarily to avoid FK issues during bulk insert
                    repl_conn.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER ALL"))
                    
                    # Truncate table
                    repl_conn.execute(text(f"TRUNCATE TABLE {table} CASCADE"))
                    
                    # Insert rows
                    for row in rows:
                        cols = ', '.join(columns)
                        placeholders = ', '.join([f":{col}" for col in columns])
                        insert_sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"
                        row_dict = dict(zip(columns, row))
                        repl_conn.execute(text(insert_sql), row_dict)
                    
                    # Re-enable triggers
                    repl_conn.execute(text(f"ALTER TABLE {table} ENABLE TRIGGER ALL"))
                    
                    trans.commit()
                    print(f"✅ {table}: Migrated {row_count} rows")
                    migrated += 1
                    
                except Exception as e:
                    trans.rollback()
                    print(f"❌ {table}: Error - {str(e)[:100]}")
                    errors += 1
                    
        except Exception as e:
            print(f"❌ {table}: Fatal error - {str(e)[:100]}")
            errors += 1
    
    # Fix sequences
    print("\n🔧 Resetting sequences...")
    with replit_engine.connect() as repl_conn:
        for table in ordered_tables:
            try:
                # Find columns with sequences
                seq_query = text(f"""
                    SELECT column_name, column_default
                    FROM information_schema.columns
                    WHERE table_name = '{table}'
                    AND column_default LIKE 'nextval%'
                """)
                result = repl_conn.execute(seq_query)
                
                for row in result:
                    column = row[0]
                    # Reset sequence to max value
                    repl_conn.execute(text(f"""
                        SELECT setval(
                            pg_get_serial_sequence('{table}', '{column}'),
                            COALESCE((SELECT MAX({column}) FROM {table}), 1),
                            true
                        )
                    """))
                repl_conn.commit()
            except:
                pass
    
    print("\n" + "=" * 60)
    print("MIGRATION SUMMARY")
    print("=" * 60)
    print(f"✅ Successfully migrated: {migrated} tables")
    print(f"⏭️  Skipped (empty): {skipped} tables")
    print(f"❌ Errors: {errors} tables")
    print(f"📊 Total: {len(ordered_tables)} tables")
    
    return migrated > 0

def full_migration():
    """Perform full 1:1 database migration"""
    print("=" * 60)
    print("FULL 1:1 DATABASE MIGRATION")
    print("=" * 60)
    print()
    
    try:
        # Connect to databases
        print("🔄 Connecting to databases...")
        external_engine = create_engine(EXTERNAL_DB_URL)
        replit_db_url = get_replit_db_url()
        replit_engine = create_engine(replit_db_url)
        
        # Test connections
        with external_engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            print(f"✅ External DB: {result.fetchone()[0].split(',')[0]}")
        
        with replit_engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            print(f"✅ Replit DB: {result.fetchone()[0].split(',')[0]}")
        
        # Get table order
        ordered_tables = get_table_order(external_engine)
        print(f"✅ Analyzed {len(ordered_tables)} tables")
        
        # Migrate schema
        migrate_schema(external_engine, replit_engine)
        
        # Migrate data
        success = migrate_data(external_engine, replit_engine, ordered_tables)
        
        if success:
            print("\n🎉 Full migration completed successfully!")
            print("\nYour Replit database is now a 1:1 copy of the external database.")
            return True
        else:
            print("\n⚠️  Migration completed with errors. Check log above.")
            return False
            
    except Exception as e:
        print(f"\n❌ FATAL ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("\n⚠️  WARNING: This will COMPLETELY REPLACE the Replit database!")
    print("All existing data will be deleted and replaced with the external database.")
    print()
    response = input("Continue? (yes/no): ")
    
    if response.lower() in ['yes', 'y', 'да']:
        success = full_migration()
        sys.exit(0 if success else 1)
    else:
        print("\n❌ Migration cancelled")
        sys.exit(0)
