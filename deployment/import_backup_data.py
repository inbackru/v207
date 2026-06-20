#!/usr/bin/env python3
"""
Script to import backup data from Excel files into PostgreSQL database
Handles all table dependencies and data validation
"""

import os
import sys
import pandas as pd
from datetime import datetime
from app import app, db
from models import (User, Manager, Admin, ResidentialComplex, 
                   BlogPost, BlogCategory, BlogArticle, ExcelProperty,
                   Favorite, Developer, District)

def parse_datetime(value):
    """Parse datetime from various formats"""
    if pd.isna(value) or value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        # Try different datetime formats
        for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%d.%m.%Y', '%d/%m/%Y']:
            try:
                return datetime.strptime(value, fmt)
            except:
                continue
    return None

def import_users(file_path):
    """Import users table"""
    print(f"\n{'='*50}")
    print("IMPORTING USERS")
    print(f"{'='*50}")
    
    df = pd.read_excel(file_path)
    print(f"Found {len(df)} users to import")
    
    imported = 0
    updated = 0
    
    for _, row in df.iterrows():
        try:
            # Check if user exists by email
            user = User.query.filter_by(email=row['email']).first()
            
            if user:
                print(f"Updating user: {row['email']}")
                updated += 1
            else:
                user = User()
                print(f"Creating user: {row['email']}")
                imported += 1
            
            # Set fields
            user.email = row['email']
            user.phone = row.get('phone') if pd.notna(row.get('phone')) else None
            user.telegram_id = row.get('telegram_id') if pd.notna(row.get('telegram_id')) else None
            user.full_name = row.get('full_name') if pd.notna(row.get('full_name')) else None
            user.password_hash = row.get('password_hash') if pd.notna(row.get('password_hash')) else None
            user.is_active = bool(row.get('is_active', True))
            user.is_verified = bool(row.get('is_verified', False))
            user.created_at = parse_datetime(row.get('created_at')) or datetime.utcnow()
            user.updated_at = parse_datetime(row.get('updated_at')) or datetime.utcnow()
            
            # Optional fields
            if pd.notna(row.get('preferred_contact')):
                user.preferred_contact = row['preferred_contact']
            if pd.notna(row.get('client_notes')):
                user.client_notes = row['client_notes']
            if pd.notna(row.get('client_status')):
                user.client_status = row['client_status']
            
            db.session.add(user)
        except Exception as e:
            print(f"Error importing user {row.get('email')}: {e}")
            continue
    
    db.session.commit()
    print(f"✅ Users: {imported} imported, {updated} updated")

def import_admins(file_path):
    """Import admins table"""
    print(f"\n{'='*50}")
    print("IMPORTING ADMINS")
    print(f"{'='*50}")
    
    df = pd.read_excel(file_path)
    print(f"Found {len(df)} admins to import")
    
    imported = 0
    updated = 0
    
    for _, row in df.iterrows():
        try:
            admin = Admin.query.filter_by(email=row['email']).first()
            
            if admin:
                print(f"Updating admin: {row['email']}")
                updated += 1
            else:
                admin = Admin()
                print(f"Creating admin: {row['email']}")
                imported += 1
            
            admin.email = row['email']
            admin.password_hash = row.get('password_hash') if pd.notna(row.get('password_hash')) else None
            admin.full_name = row.get('full_name') if pd.notna(row.get('full_name')) else None
            admin.is_active = bool(row.get('is_active', True))
            admin.is_super_admin = bool(row.get('is_super_admin', False))
            admin.phone = row.get('phone') if pd.notna(row.get('phone')) else None
            admin.created_at = parse_datetime(row.get('created_at')) or datetime.utcnow()
            
            db.session.add(admin)
        except Exception as e:
            print(f"Error importing admin {row.get('email')}: {e}")
            continue
    
    db.session.commit()
    print(f"✅ Admins: {imported} imported, {updated} updated")

def import_managers(file_path):
    """Import managers table"""
    print(f"\n{'='*50}")
    print("IMPORTING MANAGERS")
    print(f"{'='*50}")
    
    df = pd.read_excel(file_path)
    print(f"Found {len(df)} managers to import")
    
    imported = 0
    updated = 0
    
    for _, row in df.iterrows():
        try:
            manager = Manager.query.filter_by(email=row['email']).first()
            
            if manager:
                print(f"Updating manager: {row['email']}")
                updated += 1
            else:
                manager = Manager()
                print(f"Creating manager: {row['email']}")
                imported += 1
            
            manager.email = row['email']
            manager.password_hash = row.get('password_hash') if pd.notna(row.get('password_hash')) else None
            manager.first_name = row.get('first_name') if pd.notna(row.get('first_name')) else None
            manager.last_name = row.get('last_name') if pd.notna(row.get('last_name')) else None
            manager.phone = row.get('phone') if pd.notna(row.get('phone')) else None
            manager.position = row.get('position') if pd.notna(row.get('position')) else None
            manager.is_active = bool(row.get('is_active', True))
            manager.created_at = parse_datetime(row.get('created_at')) or datetime.utcnow()
            
            db.session.add(manager)
        except Exception as e:
            print(f"Error importing manager {row.get('email')}: {e}")
            continue
    
    db.session.commit()
    print(f"✅ Managers: {imported} imported, {updated} updated")

def import_blog_categories(file_path):
    """Import blog categories table"""
    print(f"\n{'='*50}")
    print("IMPORTING BLOG CATEGORIES")
    print(f"{'='*50}")
    
    df = pd.read_excel(file_path)
    print(f"Found {len(df)} blog categories to import")
    
    imported = 0
    updated = 0
    
    for _, row in df.iterrows():
        try:
            category = BlogCategory.query.filter_by(slug=row['slug']).first()
            
            if category:
                print(f"Updating category: {row['name']}")
                updated += 1
            else:
                category = BlogCategory()
                print(f"Creating category: {row['name']}")
                imported += 1
            
            category.name = row['name']
            category.slug = row['slug']
            category.description = row.get('description') if pd.notna(row.get('description')) else None
            category.color = row.get('color') if pd.notna(row.get('color')) else 'blue'
            category.icon = row.get('icon') if pd.notna(row.get('icon')) else None
            category.is_active = bool(row.get('is_active', True))
            category.created_at = parse_datetime(row.get('created_at')) or datetime.utcnow()
            
            db.session.add(category)
        except Exception as e:
            print(f"Error importing category {row.get('name')}: {e}")
            continue
    
    db.session.commit()
    print(f"✅ Blog Categories: {imported} imported, {updated} updated")

def import_blog_posts(file_path):
    """Import blog posts table"""
    print(f"\n{'='*50}")
    print("IMPORTING BLOG POSTS")
    print(f"{'='*50}")
    
    df = pd.read_excel(file_path)
    print(f"Found {len(df)} blog posts to import")
    
    imported = 0
    updated = 0
    
    for _, row in df.iterrows():
        try:
            post = BlogPost.query.filter_by(slug=row['slug']).first()
            
            if post:
                print(f"Updating post: {row['title']}")
                updated += 1
            else:
                post = BlogPost()
                print(f"Creating post: {row['title']}")
                imported += 1
            
            post.title = row['title']
            post.slug = row['slug']
            post.content = row.get('content') if pd.notna(row.get('content')) else ''
            post.excerpt = row.get('excerpt') if pd.notna(row.get('excerpt')) else ''
            post.status = row.get('status', 'draft')
            post.featured_image = row.get('featured_image') if pd.notna(row.get('featured_image')) else None
            post.meta_title = row.get('meta_title') if pd.notna(row.get('meta_title')) else None
            post.meta_description = row.get('meta_description') if pd.notna(row.get('meta_description')) else None
            
            # Handle category
            if pd.notna(row.get('category_id')):
                category = BlogCategory.query.get(int(row['category_id']))
                if category:
                    post.category_id = category.id
            
            # Handle author_id - required field, default to first admin if not set
            if pd.notna(row.get('author_id')):
                post.author_id = int(row['author_id'])
            else:
                # Use first admin as default author
                first_admin = Admin.query.first()
                if first_admin:
                    post.author_id = first_admin.id
                else:
                    print(f"  ⚠️  No admin found for author, skipping post")
                    continue
            
            post.created_at = parse_datetime(row.get('created_at')) or datetime.utcnow()
            post.published_at = parse_datetime(row.get('published_at'))
            
            db.session.add(post)
        except Exception as e:
            print(f"Error importing blog post {row.get('title')}: {e}")
            continue
    
    db.session.commit()
    print(f"✅ Blog Posts: {imported} imported, {updated} updated")

def import_blog_articles(file_path):
    """Import blog articles table"""
    print(f"\n{'='*50}")
    print("IMPORTING BLOG ARTICLES")
    print(f"{'='*50}")
    
    df = pd.read_excel(file_path)
    print(f"Found {len(df)} blog articles to import")
    
    imported = 0
    updated = 0
    
    for _, row in df.iterrows():
        try:
            article = BlogArticle.query.filter_by(slug=row['slug']).first()
            
            if article:
                print(f"Updating article: {row['title']}")
                updated += 1
            else:
                article = BlogArticle()
                print(f"Creating article: {row['title']}")
                imported += 1
            
            article.title = row['title']
            article.slug = row['slug']
            article.content = row.get('content') if pd.notna(row.get('content')) else ''
            article.excerpt = row.get('excerpt') if pd.notna(row.get('excerpt')) else ''
            article.status = row.get('status', 'draft')
            article.featured_image = row.get('featured_image') if pd.notna(row.get('featured_image')) else None
            article.author_name = row.get('author_name') if pd.notna(row.get('author_name')) else 'InBack'
            
            # Handle category - required field
            if pd.notna(row.get('category_id')):
                category = BlogCategory.query.get(int(row['category_id']))
                if category:
                    article.category_id = category.id
                else:
                    # Use first category as fallback
                    first_category = BlogCategory.query.first()
                    if first_category:
                        article.category_id = first_category.id
                    else:
                        print(f"  ⚠️  No category found, skipping article")
                        continue
            else:
                # Use first category as fallback
                first_category = BlogCategory.query.first()
                if first_category:
                    article.category_id = first_category.id
                else:
                    print(f"  ⚠️  No category found, skipping article")
                    continue
            
            # Handle author_id - required field, FK to managers table
            if pd.notna(row.get('author_id')):
                author_id = int(row['author_id'])
                manager = Manager.query.get(author_id)
                if manager:
                    article.author_id = author_id
                else:
                    # Use first manager as fallback
                    first_manager = Manager.query.first()
                    if first_manager:
                        article.author_id = first_manager.id
                    else:
                        print(f"  ⚠️  No manager found for author, skipping article")
                        continue
            else:
                # Use first manager as default author
                first_manager = Manager.query.first()
                if first_manager:
                    article.author_id = first_manager.id
                else:
                    print(f"  ⚠️  No manager found for author, skipping article")
                    continue
            
            article.created_at = parse_datetime(row.get('created_at')) or datetime.utcnow()
            article.published_at = parse_datetime(row.get('published_at'))
            
            db.session.add(article)
        except Exception as e:
            print(f"Error importing blog article {row.get('title')}: {e}")
            continue
    
    db.session.commit()
    print(f"✅ Blog Articles: {imported} imported, {updated} updated")

def import_residential_complexes(file_path):
    """Import residential complexes table"""
    print(f"\n{'='*50}")
    print("IMPORTING RESIDENTIAL COMPLEXES")
    print(f"{'='*50}")
    
    df = pd.read_excel(file_path)
    print(f"Found {len(df)} residential complexes to import")
    
    imported = 0
    updated = 0
    skipped = 0
    
    for _, row in df.iterrows():
        try:
            complex_obj = ResidentialComplex.query.filter_by(slug=row['slug']).first()
            
            if complex_obj:
                print(f"Updating complex: {row['name']}")
                updated += 1
            else:
                complex_obj = ResidentialComplex()
                print(f"Creating complex: {row['name']}")
                imported += 1
            
            complex_obj.name = row['name']
            complex_obj.slug = row['slug']
            complex_obj.cashback_rate = float(row.get('cashback_rate', 0)) if pd.notna(row.get('cashback_rate')) else 0
            complex_obj.is_active = bool(row.get('is_active', True))
            
            # Handle foreign keys - only set if they exist in database
            if pd.notna(row.get('district_id')):
                district_id = int(row['district_id'])
                # Check if district exists
                district = District.query.get(district_id)
                if district:
                    complex_obj.district_id = district_id
                else:
                    print(f"  ⚠️  District {district_id} not found, skipping FK")
            
            if pd.notna(row.get('developer_id')):
                developer_id = int(row['developer_id'])
                # Check if developer exists
                developer = Developer.query.get(developer_id)
                if developer:
                    complex_obj.developer_id = developer_id
                else:
                    print(f"  ⚠️  Developer {developer_id} not found, skipping FK")
            
            # Optional fields
            if pd.notna(row.get('complex_phone')):
                complex_obj.complex_phone = row['complex_phone']
            if pd.notna(row.get('sales_phone')):
                complex_obj.sales_phone = row['sales_phone']
            if pd.notna(row.get('sales_address')):
                complex_obj.sales_address = row['sales_address']
            
            complex_obj.created_at = parse_datetime(row.get('created_at')) or datetime.utcnow()
            
            db.session.add(complex_obj)
            db.session.flush()  # Flush to catch errors early
        except Exception as e:
            print(f"Error importing complex {row.get('name')}: {e}")
            db.session.rollback()
            skipped += 1
            continue
    
    try:
        db.session.commit()
        print(f"✅ Residential Complexes: {imported} imported, {updated} updated, {skipped} skipped")
    except Exception as e:
        print(f"Error committing complexes: {e}")
        db.session.rollback()

def import_excel_properties(file_path):
    """Import excel properties table"""
    print(f"\n{'='*50}")
    print("IMPORTING EXCEL PROPERTIES")
    print(f"{'='*50}")
    
    df = pd.read_excel(file_path)
    print(f"Found {len(df)} properties to import")
    
    imported = 0
    updated = 0
    skipped = 0
    
    for _, row in df.iterrows():
        try:
            # Check if property exists by inner_id
            inner_id = row.get('inner_id')
            if pd.isna(inner_id):
                skipped += 1
                continue
                
            prop = ExcelProperty.query.filter_by(inner_id=int(inner_id)).first()
            
            if prop:
                updated += 1
            else:
                prop = ExcelProperty()
                imported += 1
            
            # Set all available fields
            prop.inner_id = int(inner_id)
            
            # String fields
            for field in ['complex_name', 'developer_name', 'address_display_name', 
                         'renovation_type', 'deal_type', 'placement_type', 'description']:
                if field in row and pd.notna(row[field]):
                    setattr(prop, field, str(row[field]))
            
            # Numeric fields
            for field in ['object_rooms', 'object_area', 'price', 'object_min_floor', 
                         'object_max_floor', 'square_price', 'mortgage_price', 
                         'max_price', 'min_price']:
                if field in row and pd.notna(row[field]):
                    try:
                        setattr(prop, field, float(row[field]))
                    except:
                        pass
            
            # Location fields
            if pd.notna(row.get('address_position_lat')):
                prop.address_position_lat = float(row['address_position_lat'])
            if pd.notna(row.get('address_position_lon')):
                prop.address_position_lon = float(row['address_position_lon'])
            
            # JSON/Array fields
            if pd.notna(row.get('photos')):
                prop.photos = str(row['photos'])
            
            db.session.add(prop)
            
            # Commit every 100 records for better performance
            if (imported + updated) % 100 == 0:
                db.session.commit()
                print(f"  Processed {imported + updated} properties...")
        
        except Exception as e:
            print(f"Error importing property {row.get('inner_id')}: {e}")
            skipped += 1
            continue
    
    db.session.commit()
    print(f"✅ Excel Properties: {imported} imported, {updated} updated, {skipped} skipped")

def import_favorite_complexes(file_path):
    """Import favorite complexes (many-to-many relationship)"""
    print(f"\n{'='*50}")
    print("IMPORTING FAVORITE COMPLEXES")
    print(f"{'='*50}")
    
    df = pd.read_excel(file_path)
    print(f"Found {len(df)} favorite complexes to import")
    
    imported = 0
    skipped = 0
    
    for _, row in df.iterrows():
        try:
            user_id = row.get('user_id')
            complex_id = row.get('complex_id')
            
            if pd.isna(user_id) or pd.isna(complex_id):
                skipped += 1
                continue
            
            # Check if relationship already exists
            user = User.query.get(int(user_id))
            if not user:
                print(f"User {user_id} not found, skipping")
                skipped += 1
                continue
            
            # Create Favorite record
            fav = Favorite.query.filter_by(
                user_id=int(user_id),
                complex_id=int(complex_id)
            ).first()
            
            if not fav:
                fav = Favorite()
                fav.user_id = int(user_id)
                fav.complex_id = int(complex_id)
                fav.complex_name = row.get('complex_name') if pd.notna(row.get('complex_name')) else ''
                fav.created_at = parse_datetime(row.get('created_at')) or datetime.utcnow()
                
                db.session.add(fav)
                imported += 1
            
        except Exception as e:
            print(f"Error importing favorite: {e}")
            skipped += 1
            continue
    
    db.session.commit()
    print(f"✅ Favorite Complexes: {imported} imported, {skipped} skipped")

def main():
    """Main import function"""
    print("\n" + "="*70)
    print("  НАЧАЛО ИМПОРТА ДАННЫХ ИЗ EXCEL В БАЗУ ДАННЫХ")
    print("="*70)
    
    with app.app_context():
        try:
            # Import in dependency order
            import_files = [
                ('attached_assets/users (10)_1759270443225.xlsx', import_users),
                ('attached_assets/admins (10)_1759270443230.xlsx', import_admins),
                ('attached_assets/managers (10)_1759270443227.xlsx', import_managers),
                ('attached_assets/blog_categories (6)_1759270443229.xlsx', import_blog_categories),
                ('attached_assets/residential_complexes (8)_1759270443227.xlsx', import_residential_complexes),
                ('attached_assets/blog_posts (8)_1759270443229.xlsx', import_blog_posts),
                ('attached_assets/blog_articles (5)_1759270443229.xlsx', import_blog_articles),
                ('attached_assets/excel_properties (5)_1759270443229.xlsx', import_excel_properties),
                ('attached_assets/favorite_complexes (2)_1759270443228.xlsx', import_favorite_complexes),
            ]
            
            for file_path, import_func in import_files:
                if os.path.exists(file_path):
                    import_func(file_path)
                else:
                    print(f"\n⚠️  File not found: {file_path}")
            
            print("\n" + "="*70)
            print("  ✅ ИМПОРТ ЗАВЕРШЕН УСПЕШНО!")
            print("="*70)
            
        except Exception as e:
            print(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

if __name__ == "__main__":
    main()
