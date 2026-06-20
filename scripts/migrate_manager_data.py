#!/usr/bin/env python3
"""
Migration script to move Manager's favorites and comparisons from user tables to manager tables.

Context:
Manager (id=1, user_id=1) has been adding favorites and comparisons through regular pages
which saved data to USER tables instead of MANAGER tables.

This script migrates:
- favorite_properties → manager_favorite_properties
- favorite_complexes → manager_favorite_complexes  
- user_comparisons → manager_comparisons
"""

import sys
import os

# Add parent directory to path to import app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import (
    FavoriteProperty, FavoriteComplex, ManagerFavoriteProperty, ManagerFavoriteComplex,
    UserComparison, ManagerComparison, ComparisonProperty, ComparisonComplex
)
from datetime import datetime


def migrate_favorite_properties(user_id=1, manager_id=1):
    """
    Migrate favorite properties from user to manager tables.
    
    Args:
        user_id: Source user ID (default 1)
        manager_id: Target manager ID (default 1)
    
    Returns:
        tuple: (migrated_count, skipped_count)
    """
    print(f"\n{'='*60}")
    print(f"MIGRATING FAVORITE PROPERTIES")
    print(f"{'='*60}")
    
    # Get all favorite properties for user_id=1
    user_favorites = FavoriteProperty.query.filter_by(user_id=user_id).all()
    print(f"Found {len(user_favorites)} favorite properties for user_id={user_id}")
    
    # Get existing manager favorites to skip duplicates
    existing_manager_favorites = ManagerFavoriteProperty.query.filter_by(manager_id=manager_id).all()
    existing_property_ids = {fav.property_id for fav in existing_manager_favorites}
    print(f"Manager already has {len(existing_property_ids)} favorite properties")
    
    migrated = 0
    skipped = 0
    
    for user_fav in user_favorites:
        # Skip if already exists in manager favorites
        if user_fav.property_id in existing_property_ids:
            print(f"  ⏭️  SKIP: Property {user_fav.property_id} already in manager favorites")
            skipped += 1
            continue
        
        # Create new manager favorite with all fields
        manager_fav = ManagerFavoriteProperty(
            manager_id=manager_id,
            property_id=user_fav.property_id,
            property_name=user_fav.property_name,
            property_type=user_fav.property_type,
            property_size=user_fav.property_size,
            property_price=user_fav.property_price,
            complex_name=user_fav.complex_name,
            developer_name=user_fav.developer_name,
            property_image=user_fav.property_image,
            property_url=user_fav.property_url,
            cashback_amount=user_fav.cashback_amount,
            cashback_percent=user_fav.cashback_percent,
            created_at=user_fav.created_at
        )
        
        db.session.add(manager_fav)
        print(f"  ✅ MIGRATED: {user_fav.property_name} (ID: {user_fav.property_id})")
        migrated += 1
    
    print(f"\nProperties Migration Summary:")
    print(f"  - Migrated: {migrated}")
    print(f"  - Skipped (duplicates): {skipped}")
    
    return migrated, skipped


def migrate_favorite_complexes(user_id=1, manager_id=1):
    """
    Migrate favorite complexes from user to manager tables.
    
    Args:
        user_id: Source user ID (default 1)
        manager_id: Target manager ID (default 1)
    
    Returns:
        tuple: (migrated_count, skipped_count)
    """
    print(f"\n{'='*60}")
    print(f"MIGRATING FAVORITE COMPLEXES")
    print(f"{'='*60}")
    
    # Get all favorite complexes for user_id=1
    user_favorites = FavoriteComplex.query.filter_by(user_id=user_id).all()
    print(f"Found {len(user_favorites)} favorite complexes for user_id={user_id}")
    
    # Get existing manager favorites to skip duplicates
    existing_manager_favorites = ManagerFavoriteComplex.query.filter_by(manager_id=manager_id).all()
    existing_complex_ids = {fav.complex_id for fav in existing_manager_favorites}
    print(f"Manager already has {len(existing_complex_ids)} favorite complexes")
    
    migrated = 0
    skipped = 0
    
    for user_fav in user_favorites:
        # Skip if already exists in manager favorites
        if user_fav.complex_id in existing_complex_ids:
            print(f"  ⏭️  SKIP: Complex {user_fav.complex_id} already in manager favorites")
            skipped += 1
            continue
        
        # Create new manager favorite with all fields
        manager_fav = ManagerFavoriteComplex(
            manager_id=manager_id,
            complex_id=user_fav.complex_id,
            complex_name=user_fav.complex_name,
            developer_name=user_fav.developer_name,
            complex_address=user_fav.complex_address,
            district=user_fav.district,
            min_price=user_fav.min_price,
            max_price=user_fav.max_price,
            complex_image=user_fav.complex_image,
            complex_url=user_fav.complex_url,
            status=user_fav.status,
            created_at=user_fav.created_at
        )
        
        db.session.add(manager_fav)
        print(f"  ✅ MIGRATED: {user_fav.complex_name} (ID: {user_fav.complex_id})")
        migrated += 1
    
    print(f"\nComplexes Migration Summary:")
    print(f"  - Migrated: {migrated}")
    print(f"  - Skipped (duplicates): {skipped}")
    
    return migrated, skipped


def migrate_comparisons(user_id=1, manager_id=1):
    """
    Migrate comparisons from user to manager tables.
    
    Args:
        user_id: Source user ID (default 1)
        manager_id: Target manager ID (default 1)
    
    Returns:
        tuple: (migrated_comparisons, migrated_properties, migrated_complexes)
    """
    print(f"\n{'='*60}")
    print(f"MIGRATING COMPARISONS")
    print(f"{'='*60}")
    
    # Get all user comparisons
    user_comparisons = UserComparison.query.filter_by(user_id=user_id).all()
    print(f"Found {len(user_comparisons)} comparisons for user_id={user_id}")
    
    migrated_comparisons = 0
    migrated_properties = 0
    migrated_complexes = 0
    
    for user_comp in user_comparisons:
        print(f"\n  Processing comparison: '{user_comp.name}' (ID: {user_comp.id})")
        
        # Count items in this comparison
        properties_count = len(user_comp.comparison_properties)
        complexes_count = len(user_comp.comparison_complexes)
        print(f"    - {properties_count} properties")
        print(f"    - {complexes_count} complexes")
        
        # Create new manager comparison
        manager_comp = ManagerComparison(
            manager_id=manager_id,
            name=user_comp.name,
            client_name="Migrated from user",
            is_active=user_comp.is_active,
            created_at=user_comp.created_at,
            updated_at=user_comp.updated_at
        )
        db.session.add(manager_comp)
        db.session.flush()  # Get the ID
        
        # Migrate comparison properties
        for prop in user_comp.comparison_properties:
            manager_prop = ComparisonProperty(
                manager_comparison_id=manager_comp.id,
                property_id=prop.property_id,
                property_name=prop.property_name,
                property_price=prop.property_price,
                complex_name=prop.complex_name,
                cashback=prop.cashback,
                area=prop.area,
                rooms=prop.rooms,
                order_index=prop.order_index,
                added_at=prop.added_at
            )
            db.session.add(manager_prop)
            migrated_properties += 1
        
        # Migrate comparison complexes
        for comp in user_comp.comparison_complexes:
            manager_comp_complex = ComparisonComplex(
                manager_comparison_id=manager_comp.id,
                complex_id=comp.complex_id,
                complex_name=comp.complex_name,
                developer_name=comp.developer_name,
                min_price=comp.min_price,
                max_price=comp.max_price,
                district=comp.district,
                photo=comp.photo,
                buildings_count=comp.buildings_count,
                apartments_count=comp.apartments_count,
                completion_date=comp.completion_date,
                status=comp.status,
                complex_class=comp.complex_class
            )
            db.session.add(manager_comp_complex)
            migrated_complexes += 1
        
        print(f"  ✅ MIGRATED: Comparison '{user_comp.name}'")
        migrated_comparisons += 1
    
    print(f"\nComparisons Migration Summary:")
    print(f"  - Migrated comparisons: {migrated_comparisons}")
    print(f"  - Migrated properties in comparisons: {migrated_properties}")
    print(f"  - Migrated complexes in comparisons: {migrated_complexes}")
    
    return migrated_comparisons, migrated_properties, migrated_complexes


def main():
    """Main migration function"""
    print("\n" + "="*60)
    print("MANAGER DATA MIGRATION SCRIPT")
    print("="*60)
    print("\nMigrating data from user_id=1 to manager_id=1")
    print("This will migrate:")
    print("  - favorite_properties → manager_favorite_properties")
    print("  - favorite_complexes → manager_favorite_complexes")
    print("  - user_comparisons → manager_comparisons")
    
    try:
        with app.app_context():
            # Start transaction
            print("\nStarting migration transaction...")
            
            # Migrate favorite properties
            prop_migrated, prop_skipped = migrate_favorite_properties()
            
            # Migrate favorite complexes
            comp_migrated, comp_skipped = migrate_favorite_complexes()
            
            # Migrate comparisons
            comparisons, comp_properties, comp_complexes = migrate_comparisons()
            
            # Commit all changes
            db.session.commit()
            print(f"\n{'='*60}")
            print("✅ MIGRATION COMPLETED SUCCESSFULLY")
            print(f"{'='*60}")
            
            # Print final summary
            print("\nFINAL SUMMARY:")
            print(f"  Favorite Properties:")
            print(f"    - Migrated: {prop_migrated}")
            print(f"    - Skipped: {prop_skipped}")
            print(f"  Favorite Complexes:")
            print(f"    - Migrated: {comp_migrated}")
            print(f"    - Skipped: {comp_skipped}")
            print(f"  Comparisons:")
            print(f"    - Migrated: {comparisons}")
            print(f"    - Properties in comparisons: {comp_properties}")
            print(f"    - Complexes in comparisons: {comp_complexes}")
            print(f"\nTotal items migrated: {prop_migrated + comp_migrated + comparisons + comp_properties + comp_complexes}")
            print(f"{'='*60}\n")
            
    except Exception as e:
        print(f"\n{'='*60}")
        print("❌ MIGRATION FAILED")
        print(f"{'='*60}")
        print(f"Error: {str(e)}")
        print("\nRolling back all changes...")
        db.session.rollback()
        print("Rollback completed.")
        raise


if __name__ == "__main__":
    main()
