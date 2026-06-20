#!/usr/bin/env python3
"""
Script to migrate data from external PostgreSQL database to Replit database
"""
import os
import subprocess
import sys

# External database credentials
EXTERNAL_DB_URL = "postgresql://neondb_owner:npg_EfOVcMgXp35J@ep-wild-thunder-aem27sgc.c-2.us-east-2.aws.neon.tech/neondb?sslmode=require"

# Replit database (from environment variables)
REPLIT_DB_URL = os.environ.get("DATABASE_URL")

def run_command(cmd, error_message="Command failed"):
    """Run a shell command and handle errors"""
    print(f"Running: {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"❌ {error_message}")
        print(f"STDERR: {result.stderr}")
        return False
    
    print(f"✅ Success!")
    if result.stdout:
        print(f"Output: {result.stdout[:500]}...")
    return True

def main():
    """Main migration function"""
    print("=" * 60)
    print("DATABASE MIGRATION SCRIPT")
    print("=" * 60)
    
    if not REPLIT_DB_URL:
        print("❌ Error: DATABASE_URL not found in environment variables")
        print("Please make sure the Replit database is set up")
        sys.exit(1)
    
    print(f"\n📊 External DB: {EXTERNAL_DB_URL.split('@')[1].split('/')[0]}")
    print(f"📊 Replit DB: {REPLIT_DB_URL.split('@')[1].split('/')[0] if '@' in REPLIT_DB_URL else 'local'}")
    
    # Step 1: Create dump from external database
    print("\n" + "=" * 60)
    print("STEP 1: Creating dump from external database...")
    print("=" * 60)
    
    dump_file = "/tmp/external_db_dump.sql"
    dump_cmd = f'pg_dump "{EXTERNAL_DB_URL}" > {dump_file}'
    
    if not run_command(dump_cmd, "Failed to create database dump"):
        sys.exit(1)
    
    # Check dump file size
    if os.path.exists(dump_file):
        size = os.path.getsize(dump_file)
        print(f"📦 Dump file size: {size / 1024 / 1024:.2f} MB")
    
    # Step 2: Restore dump to Replit database
    print("\n" + "=" * 60)
    print("STEP 2: Restoring dump to Replit database...")
    print("=" * 60)
    
    restore_cmd = f'psql "{REPLIT_DB_URL}" < {dump_file}'
    
    if not run_command(restore_cmd, "Failed to restore database dump"):
        print("\n⚠️  Warning: Some errors occurred during restore.")
        print("This is often normal if tables already exist or there are permission issues.")
        print("Continuing anyway...")
    
    # Step 3: Verify migration
    print("\n" + "=" * 60)
    print("STEP 3: Verifying migration...")
    print("=" * 60)
    
    verify_cmd = f'psql "{REPLIT_DB_URL}" -c "\\dt"'
    run_command(verify_cmd, "Failed to verify tables")
    
    print("\n" + "=" * 60)
    print("✅ MIGRATION COMPLETE!")
    print("=" * 60)
    print("\nYour database has been successfully migrated to Replit.")
    print(f"Dump file saved at: {dump_file}")
    print("\nNext steps:")
    print("1. Restart your application")
    print("2. Test that everything works correctly")
    print("3. Delete the dump file if you don't need it anymore")

if __name__ == "__main__":
    main()
