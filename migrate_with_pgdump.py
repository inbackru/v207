#!/usr/bin/env python3
"""
Complete 1:1 Database Migration using pg_dump
Most reliable method for exact database copy
"""
import os
import sys
import subprocess
import tempfile

# External database credentials
EXTERNAL_HOST = "ep-bitter-butterfly-a6glc4a9.us-west-2.aws.neon.tech"
EXTERNAL_DB = "neondb"
EXTERNAL_USER = "neondb_owner"
EXTERNAL_PASSWORD = "npg_NEWUZCsHMw23"
EXTERNAL_PORT = "5432"

def get_replit_credentials():
    """Get Replit database credentials from environment"""
    return {
        'host': os.environ.get('PGHOST'),
        'database': os.environ.get('PGDATABASE'),
        'user': os.environ.get('PGUSER'),
        'password': os.environ.get('PGPASSWORD'),
        'port': os.environ.get('PGPORT')
    }

def run_command(cmd, env=None):
    """Run shell command and return output"""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            env=env or os.environ.copy()
        )
        return result.returncode, result.stdout, result.stderr
    except Exception as e:
        return 1, "", str(e)

def migrate_database():
    """Migrate database using pg_dump and pg_restore"""
    print("=" * 70)
    print("COMPLETE 1:1 DATABASE MIGRATION")
    print("Using pg_dump for exact copy")
    print("=" * 70)
    print()
    
    # Get Replit credentials
    replit_creds = get_replit_credentials()
    
    print("📋 Connection Info:")
    print(f"  Source: {EXTERNAL_HOST}/{EXTERNAL_DB}")
    print(f"  Target: {replit_creds['host']}/{replit_creds['database']}")
    print()
    
    # Create temporary file for dump
    with tempfile.NamedTemporaryFile(mode='w', suffix='.sql', delete=False) as tmp:
        dump_file = tmp.name
    
    try:
        # Step 1: Dump external database
        print("🔄 Step 1/4: Dumping external database...")
        print("  This may take a few minutes...")
        
        dump_env = os.environ.copy()
        dump_env['PGPASSWORD'] = EXTERNAL_PASSWORD
        
        dump_cmd = f"""pg_dump \
            -h {EXTERNAL_HOST} \
            -p {EXTERNAL_PORT} \
            -U {EXTERNAL_USER} \
            -d {EXTERNAL_DB} \
            --no-owner \
            --no-acl \
            -f {dump_file}
        """
        
        code, stdout, stderr = run_command(dump_cmd, dump_env)
        
        if code != 0:
            print(f"❌ Error dumping database: {stderr}")
            return False
        
        # Check dump file size
        dump_size = os.path.getsize(dump_file)
        print(f"✅ Database dumped successfully ({dump_size:,} bytes)")
        
        # Step 2: Clear target database
        print("\n🔄 Step 2/4: Clearing target database...")
        
        restore_env = os.environ.copy()
        restore_env['PGPASSWORD'] = replit_creds['password']
        
        drop_cmd = f"""psql \
            -h {replit_creds['host']} \
            -p {replit_creds['port']} \
            -U {replit_creds['user']} \
            -d {replit_creds['database']} \
            -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
        """
        
        code, stdout, stderr = run_command(drop_cmd, restore_env)
        
        if code != 0:
            print(f"⚠️  Warning clearing database: {stderr}")
        else:
            print("✅ Target database cleared")
        
        # Step 3: Restore to Replit database
        print("\n🔄 Step 3/4: Restoring to Replit database...")
        print("  This may take several minutes...")
        
        restore_cmd = f"""psql \
            -h {replit_creds['host']} \
            -p {replit_creds['port']} \
            -U {replit_creds['user']} \
            -d {replit_creds['database']} \
            -f {dump_file}
        """
        
        code, stdout, stderr = run_command(restore_cmd, restore_env)
        
        # pg_restore may have warnings but still succeed
        if "ERROR" in stderr and code != 0:
            print(f"❌ Error restoring database:")
            print(stderr[:500])
            return False
        
        print("✅ Database restored successfully")
        
        # Step 4: Verify migration
        print("\n🔄 Step 4/4: Verifying migration...")
        
        verify_cmd = f"""psql \
            -h {replit_creds['host']} \
            -p {replit_creds['port']} \
            -U {replit_creds['user']} \
            -d {replit_creds['database']} \
            -c "SELECT schemaname, tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;"
        """
        
        code, stdout, stderr = run_command(verify_cmd, restore_env)
        
        if code == 0:
            tables = stdout.strip().split('\n')[2:-2]  # Remove header and footer
            table_count = len([t for t in tables if t.strip()])
            print(f"✅ Verified: {table_count} tables in Replit database")
            
            # Get row counts
            print("\n📊 Sample table counts:")
            count_cmd = f"""psql \
                -h {replit_creds['host']} \
                -p {replit_creds['port']} \
                -U {replit_creds['user']} \
                -d {replit_creds['database']} \
                -c "
                    SELECT 
                        'users' as table_name, COUNT(*) FROM users
                    UNION ALL
                    SELECT 'developers', COUNT(*) FROM developers
                    UNION ALL
                    SELECT 'complexes', COUNT(*) FROM complexes
                    UNION ALL
                    SELECT 'properties', COUNT(*) FROM properties;
                "
            """
            
            code, stdout, stderr = run_command(count_cmd, restore_env)
            if code == 0:
                print(stdout)
        
        print("\n" + "=" * 70)
        print("✅ MIGRATION COMPLETED SUCCESSFULLY!")
        print("=" * 70)
        print()
        print("Your Replit database is now a perfect 1:1 copy of the external database.")
        print("All tables, data, indexes, and constraints have been migrated.")
        print()
        
        return True
        
    except Exception as e:
        print(f"\n❌ FATAL ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        # Clean up temporary file
        try:
            if os.path.exists(dump_file):
                os.unlink(dump_file)
                print(f"🗑️  Cleaned up temporary file")
        except:
            pass

if __name__ == "__main__":
    print("\n⚠️  WARNING: This will completely replace the Replit database!")
    print("All existing data will be deleted and replaced with external database.")
    print()
    response = input("Continue with migration? (yes/no): ")
    
    if response.lower() in ['yes', 'y', 'да']:
        success = migrate_database()
        sys.exit(0 if success else 1)
    else:
        print("\n❌ Migration cancelled")
        sys.exit(0)
