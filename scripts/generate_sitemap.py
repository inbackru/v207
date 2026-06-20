#!/usr/bin/env python3
"""
Multi-City Sitemap Generator for InBack.ru
Generates comprehensive sitemap with city-based URLs for all 8 cities
"""

import os
import sys

# Add parent directory to path to import Flask app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime


def generate_sitemap():
    """Generate comprehensive sitemap with city-based URLs"""
    
    # Import Flask app and models inside function to avoid circular imports
    from app import app, db
    from models import City, Property, ResidentialComplex
    
    print("🔄 Генерация sitemap с мультигородскими URL...")
    
    base_url = "https://inback.ru"
    today = datetime.now().strftime('%Y-%m-%d')
    
    # Start XML
    sitemap_xml = '''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
'''
    
    url_count = 0
    
    with app.app_context():
        # 1. HOMEPAGE
        print("🏠 Добавление главной страницы...")
        sitemap_xml += f'''  <url>
    <loc>{base_url}/</loc>
    <lastmod>{today}</lastmod>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>
'''
        url_count += 1
        
        # 2. MAIN PAGES (Global, not city-specific)
        print("📄 Добавление основных страниц...")
        main_pages = [
            {'url': '/properties', 'priority': '0.9', 'changefreq': 'daily'},
            {'url': '/residential-complexes', 'priority': '0.9', 'changefreq': 'daily'},
            {'url': '/developers', 'priority': '0.8', 'changefreq': 'weekly'},
            {'url': '/map', 'priority': '0.8', 'changefreq': 'weekly'},
            {'url': '/about', 'priority': '0.8', 'changefreq': 'monthly'},
            {'url': '/how-it-works', 'priority': '0.8', 'changefreq': 'monthly'},
            {'url': '/reviews', 'priority': '0.7', 'changefreq': 'weekly'},
            {'url': '/contacts', 'priority': '0.7', 'changefreq': 'monthly'},
            {'url': '/blog', 'priority': '0.8', 'changefreq': 'daily'},
            {'url': '/news', 'priority': '0.7', 'changefreq': 'daily'},
            {'url': '/ipoteka', 'priority': '0.8', 'changefreq': 'weekly'},
            {'url': '/family-mortgage', 'priority': '0.7', 'changefreq': 'monthly'},
            {'url': '/it-mortgage', 'priority': '0.7', 'changefreq': 'monthly'},
            {'url': '/military-mortgage', 'priority': '0.7', 'changefreq': 'monthly'},
            {'url': '/developer-mortgage', 'priority': '0.7', 'changefreq': 'monthly'},
            {'url': '/maternal-capital', 'priority': '0.7', 'changefreq': 'monthly'},
            {'url': '/comparison', 'priority': '0.6', 'changefreq': 'weekly'},
            {'url': '/complex-comparison', 'priority': '0.6', 'changefreq': 'weekly'},
        ]
        
        for page in main_pages:
            sitemap_xml += f'''  <url>
    <loc>{base_url}{page['url']}</loc>
    <lastmod>{today}</lastmod>
    <changefreq>{page['changefreq']}</changefreq>
    <priority>{page['priority']}</priority>
  </url>
'''
            url_count += 1
        
        # 3. QUERY ALL ACTIVE CITIES FROM DATABASE
        print("🌍 Получение списка активных городов из базы данных...")
        cities = City.query.filter_by(is_active=True).order_by(City.name).all()
        print(f"   Найдено {len(cities)} активных городов")
        
        # 4. CITY-BASED PROPERTIES PAGES (/<city_slug>/properties)
        print("🏘️ Добавление страниц свойств по городам...")
        for city in cities:
            sitemap_xml += f'''  <url>
    <loc>{base_url}/{city.slug}/properties</loc>
    <lastmod>{today}</lastmod>
    <changefreq>daily</changefreq>
    <priority>0.9</priority>
  </url>
'''
            url_count += 1
        
        # 5. CITY-BASED RESIDENTIAL COMPLEXES PAGES (/<city_slug>/residential-complexes)
        print("🏢 Добавление страниц жилых комплексов по городам...")
        for city in cities:
            sitemap_xml += f'''  <url>
    <loc>{base_url}/{city.slug}/residential-complexes</loc>
    <lastmod>{today}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>
'''
            url_count += 1
        
        # 6. INDIVIDUAL PROPERTIES (/<city_slug>/object/<id>)
        print("🏠 Получение всех активных объектов недвижимости...")
        properties = Property.query.filter_by(is_active=True).all()
        print(f"   Найдено {len(properties)} активных объектов")
        
        print("   Добавление URL объектов недвижимости...")
        for prop in properties:
            # Get city slug for the property
            city_slug = prop.city.slug if prop.city else 'krasnodar'
            sitemap_xml += f'''  <url>
    <loc>{base_url}/{city_slug}/object/{prop.id}</loc>
    <lastmod>{today}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.7</priority>
  </url>
'''
            url_count += 1
        
        # 7. INDIVIDUAL RESIDENTIAL COMPLEXES (/<city_slug>/zk/<slug>)
        print("🏗️ Получение всех активных жилых комплексов...")
        complexes = ResidentialComplex.query.filter_by(is_active=True).all()
        print(f"   Найдено {len(complexes)} активных жилых комплексов")
        
        print("   Добавление URL жилых комплексов...")
        for complex in complexes:
            # Get city slug for the complex
            city_slug = complex.city.slug if complex.city else 'krasnodar'
            sitemap_xml += f'''  <url>
    <loc>{base_url}/{city_slug}/zk/{complex.slug}</loc>
    <lastmod>{today}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.7</priority>
  </url>
'''
            url_count += 1
        
        # 8. BLOG CATEGORIES
        print("📝 Добавление категорий блога...")
        blog_categories = ['cashback', 'districts', 'mortgage', 'market', 'legal', 'tips']
        for category in blog_categories:
            sitemap_xml += f'''  <url>
    <loc>{base_url}/blog/category/{category}</loc>
    <lastmod>{today}</lastmod>
    <changefreq>daily</changefreq>
    <priority>0.7</priority>
  </url>
'''
            url_count += 1
    
    # Close XML
    sitemap_xml += '</urlset>'
    
    # Save to file
    print("\n💾 Сохранение sitemap...")
    os.makedirs('static', exist_ok=True)
    sitemap_path = 'static/sitemap.xml'
    
    with open(sitemap_path, 'w', encoding='utf-8') as f:
        f.write(sitemap_xml)
    
    # Print summary
    print("\n" + "="*60)
    print("✅ SITEMAP УСПЕШНО СОЗДАН!")
    print("="*60)
    print(f"📊 Всего URL: {url_count}")
    print(f"🌍 Городов: {len(cities)}")
    print(f"🏠 Объектов недвижимости: {len(properties)}")
    print(f"🏢 Жилых комплексов: {len(complexes)}")
    print(f"📁 Файл: {sitemap_path}")
    print(f"🌐 URL: https://inback.ru/sitemap.xml")
    print("="*60)
    
    # Print city breakdown
    print("\n🌍 ГОРОДА В SITEMAP:")
    with app.app_context():
        for city in cities:
            city_properties = Property.query.filter_by(city_id=city.id, is_active=True).count()
            city_complexes = ResidentialComplex.query.filter_by(city_id=city.id, is_active=True).count()
            print(f"   • {city.name} ({city.slug}): {city_properties} объектов, {city_complexes} ЖК")
    
    return sitemap_xml


def create_robots_txt():
    """Create robots.txt file"""
    
    print("\n🤖 Создание robots.txt...")
    
    robots_content = """User-agent: *
Allow: /

# Ограничения для ботов
Disallow: /admin/
Disallow: /manager/
Disallow: /api/
Disallow: /uploads/
Disallow: /static/temp/
Disallow: /login
Disallow: /logout
Disallow: *.pdf$
Disallow: /*?print=*
Disallow: /*?*sort=*
Disallow: /*?*filter=*

# Разрешаем важные ресурсы
Allow: /static/css/
Allow: /static/js/
Allow: /static/images/
Allow: /static/sitemap.xml
Allow: /sitemap.xml

# Время между запросами
Crawl-delay: 1

# Карта сайта
Sitemap: https://inback.ru/sitemap.xml

# Настройки для разных поисковиков
User-agent: Googlebot
Crawl-delay: 1
Allow: /api/properties
Allow: /api/residential-complexes

User-agent: Yandex
Crawl-delay: 1
Allow: /api/properties
Allow: /api/residential-complexes

User-agent: Bingbot  
Crawl-delay: 2

# Блокировка нежелательных ботов
User-agent: SemrushBot
Disallow: /

User-agent: AhrefsBot
Disallow: /

User-agent: MJ12bot
Disallow: /
"""
    
    os.makedirs('static', exist_ok=True)
    with open('static/robots.txt', 'w', encoding='utf-8') as f:
        f.write(robots_content)
    
    print("✅ robots.txt обновлен")


if __name__ == '__main__':
    print("="*60)
    print("🚀 ГЕНЕРАТОР SITEMAP ДЛЯ INBACK.RU")
    print("   Мультигородская поддержка (8 городов)")
    print("="*60)
    print()
    
    try:
        generate_sitemap()
        create_robots_txt()
        print("\n✅ ВСЕ ГОТОВО! Sitemap и robots.txt успешно созданы")
    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
