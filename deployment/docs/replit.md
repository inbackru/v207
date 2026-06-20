# InBack Real Estate Platform

## Overview
InBack is a comprehensive real estate platform for new construction properties in Krasnodar, Russia. It facilitates property purchases with an innovative cashback system, offering up to 500,000₽. The platform features advanced property search, interactive maps, and a robust admin panel. Its business vision is to provide a user-friendly and financially beneficial platform for real estate transactions in the new build market.

## User Preferences
- Follow existing Flask patterns and project structure
- Maintain Russian language for UI/UX
- Keep security best practices (CSRF protection, password hashing)
- Use environment variables for sensitive data
- Maintain existing database schema

## System Architecture

### UI/UX Decisions
The platform features a mobile-responsive design focused on intuitive property search and interactive map integration using Leaflet.js, incorporating a clear visual hierarchy and user-friendly navigation.

### Technical Implementations
The backend is built with Flask 2.3.3 and SQLAlchemy ORM, connecting to a PostgreSQL database. The frontend uses HTML/CSS/JavaScript with Tailwind CSS. Gunicorn serves the Flask application, and Flask-Login handles authentication.

### Feature Specifications
- **Property Search**: Advanced filtering by price, district, developer, and room count, with server-side filtering and sorting.
- **Cashback System**: Automated, dynamic cashback calculation up to 500,000₽, sourced from residential complex rates.
- **Interactive Maps**: Yandex Maps integration with polygon highlighting for districts and polyline visualization for streets. All 53 districts and 1587 streets enriched with geometry data.
- **Admin Panel**: CRM for managing properties, users, applications, and dynamic cashback rates.
- **Notification System**: Integrates with Telegram (multi-recipient via MANAGER_TELEGRAM_IDS) and email (SendGrid). Fixed October 2025: Corrected parse_mode to 'Markdown' and implemented environment variable usage for chat IDs.
- **Blog System**: Features a TinyMCE editor for content creation and SEO optimization.
- **Application Modal System (October 2025)**: Unified modal window for all application forms across the site with counter-based scroll-lock system, thank you screen with green checkmark, and consistent behavior across 10+ template files.
- **Mortgage Programs**: Comprehensive mortgage pages with interactive calculators (blue sliders #3B82F6), bank partner information (ВТБ, Сбер, Альфа-Банк, Дом.рф, Россельхозбанк), and verification features:
  - Family mortgage with smooth scroll to calculator
  - Military mortgage with НИС verification link (https://m.rosvoenipoteka.ru/)
  - IT mortgage with company verification (9,085 companies database from official registry)
  - Developer mortgage with property catalog integration
  - Maternal capital with certificate verification modal (Gosuslugi instructions)
  - Tax deduction with calculator (up to 650,000₽ total: 260,000₽ property + 390,000₽ mortgage interest)
- **IT Company Verification**: Database of 9,085 IT companies (loaded from Excel) with API endpoint `/api/check-it-company` for INN verification to confirm eligibility for IT mortgage program.
- **City Detection (October 2025)**: Automatic city detection by IP address using ipwhois.io API (10,000 free requests/month). Beautiful gradient-styled modal with:
  - Auto-detection shows "Вы из [Город]?" confirmation
  - Two-view system: confirmation screen and city selector screen
  - Searchable list of 49 popular Russian cities with live filtering
  - localStorage persistence (shows once per user)
  - Smooth animations (fadeIn, slideUp) with gradient background overlay
  - Counter-based scroll-lock integration
  - Fallback to Краснодар for localhost/private IPs

### System Design Choices
The application uses a modular Flask structure with dedicated files for core functionalities. Performance is optimized through response caching, image lazy loading, database connection pooling, and optimized SQLAlchemy queries. Server-side pagination and filtering ensure scalability.

**Unified Filtering Architecture (October 2025):**
- Created `build_property_filters()` function as single source of truth for SQL-based property filtering
- Implemented REST API endpoint `/api/properties/filter` for consistent filtering across listing and map views
- Refactored `/properties` route to use unified filtering (eliminated ~280 lines of duplicate code)
- Updated `/map` route and JavaScript to use server-side filtering via API instead of client-side filtering
- Supports all filter parameter name variants for backward compatibility (price_min/priceFrom, area_min/areaFrom, etc.)
- SQL injection protection via parameterized queries
- Consistent behavior: both `/properties` and `/map` now return identical results for same filters
- **Advanced Filters (October 2025)**: Added support for floor options (not_first, not_last) and cashback_only filters in unified system

### SEO Optimization (Completed 100%)
All page templates are fully SEO-optimized with comprehensive meta tags and structured data:

**Page Templates Optimized:**
- **Main Page (Index)**: Homepage fully optimized with 9 Open Graph tags, 5 Twitter Card tags, dynamic canonical URLs, robots meta (index, follow), and Schema.org markup (RealEstateAgent).
- **Street Pages (1,648 pages)**: Unique meta descriptions, Open Graph tags (9 tags), Twitter Card tags (5 tags), canonical URLs, robots meta, and Schema.org markup (BreadcrumbList, WebPage, Place with coordinates).
- **District Pages (53 pages)**: Comprehensive SEO with @graph structure, dynamic URLs via url_for, corrected Twitter Card tags (name vs property), robots meta, and place-specific structured data.
- **Property Pages (~5,000+ pages)**: Property-specific meta tags, dynamic Open Graph and Twitter Card tags with real property images, canonical URLs, and Schema.org markup (@graph with BreadcrumbList, WebPage, and Apartment schemas).
- **Residential Complex Pages (~300+ pages)**: Complex-specific meta tags, dynamic Open Graph and Twitter Card tags with real complex images, canonical URLs, and Schema.org markup (@graph with BreadcrumbList, WebPage, and ApartmentComplex schemas with offers and amenities).
- **Mortgage & Insurance Pages (8 pages)**: All mortgage programs overview, family mortgage, military mortgage, IT mortgage, developer mortgage (installment), maternal capital, tax deduction, and insurance pages fully optimized with 9 Open Graph tags, 5 Twitter Card tags, dynamic canonical URLs, robots meta (index, follow), and Schema.org markup (RealEstateAgent, InsuranceAgency).
- **Header Navigation Pages (10 pages)**: Properties, residential complexes, developers, about, how-it-works, security, reviews, blog, contacts, careers - all fully optimized with 9 Open Graph tags, 5 Twitter Card tags, dynamic canonical URLs, robots meta (index, follow), and Schema.org markup where applicable (RealEstateAgent, HowTo, Reviews, Organization).
- **Blog Pages**: All blog templates fully optimized:
  - Blog main page (/blog) - 9 OG tags, 5 Twitter tags, canonical URL, robots meta
  - Blog articles (/blog/<slug>) - 9 OG tags + article-specific tags, 5 Twitter tags, canonical URL, robots meta
  - Blog categories (/blog/category/<slug>) - Uses optimized blog.html template
  - Blog new articles (/blog-new/<slug>) - 9 OG tags with Schema.org Article markup, 5 Twitter tags, canonical URL, robots meta
  - Blog new categories (/blog-new/category/<slug>) - 9 OG tags, 5 Twitter tags, canonical URL, robots meta

**SEO Features:**
- Dynamic meta descriptions unique to each page
- Open Graph tags (9 per page) for social media sharing
- Twitter Card tags (5 per page) with proper attributes
- Canonical URLs using dynamic url_for with _external=True
- Robots meta tags (index, follow)
- Schema.org structured data including: BreadcrumbList, WebPage, Place, Apartment, ApartmentComplex, Organization
- Real property images in social media previews
- Lazy loading images with descriptive alt tags
- All URLs dynamically generated (no hardcoded links)

## External Dependencies
- **PostgreSQL**: Primary database.
- **Gunicorn**: WSGI HTTP server.
- **Tailwind CSS**: Utility-first CSS framework.
- **Yandex Maps API**: JavaScript library for interactive maps with polygon/polyline visualization.
- **TinyMCE**: Rich text editor.
- **Telegram Bot API**: For sending notifications.
- **SendGrid API**: For email notifications.
- **Yandex Geocoder API**: For enriching district geometry (bounding boxes) and street coordinates.
- **OpenStreetMap Nominatim**: For enriching precise district polygon boundaries (34% coverage).