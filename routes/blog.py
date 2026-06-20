"""
Blog Blueprint — public blog, news, articles.
Endpoints: blog, blog_city, blog_category, blog_post, news,
           blog_new, blog_article_new, blog_category_new.
"""
import math

from flask import (Blueprint, abort, flash, redirect, render_template,
                   request, session, url_for)
from flask_login import current_user

from app import db

blog_bp = Blueprint('blog', __name__)


# ─── helpers imported lazily to avoid circular imports ───────────────────────

def _resolve_city_context(**kwargs):
    from app import resolve_city_context
    return resolve_city_context(**kwargs)


def _redirect_to_city_based(endpoint):
    from app import redirect_to_city_based
    return redirect_to_city_based(endpoint)


# ─── Blog main ───────────────────────────────────────────────────────────────

@blog_bp.route('/blog', strict_slashes=False)
def blog():
    """Redirect to city-based URL"""
    return _redirect_to_city_based('blog.blog_city')


def _render_blog_page(current_city):
    """Internal blog rendering logic"""
    from models import BlogPost, Category
    from sqlalchemy import func

    search_query = request.args.get('search', '').strip()
    category_filter = request.args.get('category', '').strip()
    sort_order = request.args.get('sort', 'date_desc')
    if sort_order not in ('date_desc', 'date_asc'):
        sort_order = 'date_desc'
    page = max(1, int(request.args.get('page', 1)))
    per_page = 24

    # Build category id→name map efficiently
    all_categories = Category.query.filter_by(is_active=True).order_by(
        Category.sort_order, Category.name
    ).all()
    # Filter out junk categories (empty name or numeric-only slugs)
    all_categories = [c for c in all_categories if c.name and len(c.name.strip()) > 2
                      and not c.name.strip().isdigit()]
    cat_map = {c.id: c.name for c in all_categories}

    # Article counts per category for tabs
    cat_counts = {}
    try:
        rows = (db.session.query(BlogPost.category_id, func.count(BlogPost.id))
                .filter(BlogPost.status == 'published', BlogPost.category_id.isnot(None))
                .group_by(BlogPost.category_id).all())
        cat_counts = {row[0]: row[1] for row in rows}
    except Exception:
        pass

    # Build query
    q = BlogPost.query.filter_by(status='published')

    if search_query:
        like = f'%{search_query.lower()}%'
        q = q.filter(
            func.lower(BlogPost.title).like(like) |
            func.lower(BlogPost.excerpt).like(like) |
            func.lower(BlogPost.content).like(like)
        )

    active_cat_obj = None
    if category_filter:
        active_cat_obj = Category.query.filter(
            (Category.slug == category_filter) | (Category.name.ilike(f'%{category_filter}%'))
        ).filter_by(is_active=True).first()
        if active_cat_obj:
            q = q.filter(BlogPost.category_id == active_cat_obj.id)

    if sort_order == 'date_asc':
        q = q.order_by(BlogPost.published_at.asc().nullsfirst(), BlogPost.created_at.asc())
    else:
        q = q.order_by(BlogPost.published_at.desc().nullslast(), BlogPost.created_at.desc())

    total_articles = q.count()
    total_pages = math.ceil(total_articles / per_page) if total_articles else 1
    posts = q.offset((page - 1) * per_page).limit(per_page).all()

    def _serialize(post):
        return {
            'id': post.id,
            'title': post.title,
            'slug': post.slug,
            'excerpt': post.excerpt or '',
            'featured_image': post.featured_image,
            'published_at': post.published_at or post.created_at,
            'created_at': post.created_at,
            'reading_time': getattr(post, 'reading_time', None) or max(3, len(post.content or '') // 1200),
            'category_id': post.category_id,
            'category_name': cat_map.get(post.category_id, ''),
            'category_slug': next((c.slug for c in all_categories if c.id == post.category_id), ''),
            'url': f'/blog/{post.slug}',
            'views_count': post.views_count or 0,
        }

    articles_page = [_serialize(p) for p in posts]

    # Hero/featured: most-viewed article (only when on page 1 with no filters)
    hero_article = None
    if page == 1 and not search_query and not category_filter:
        try:
            hero_post = (BlogPost.query.filter_by(status='published')
                         .order_by(BlogPost.views_count.desc().nullslast())
                         .first())
            if hero_post:
                hero_article = _serialize(hero_post)
        except Exception:
            pass

    return render_template(
        'blog.html',
        current_city=current_city,
        articles=articles_page,
        hero_article=hero_article,
        all_categories=all_categories,
        cat_counts=cat_counts,
        search_query=search_query,
        category_filter=active_cat_obj.slug if active_cat_obj else category_filter,
        sort_order=sort_order,
        current_page=page,
        total_articles=total_articles,
        total_pages=total_pages,
        show_category_sections=False,
    )


@blog_bp.route('/blog/category/<category_slug>')
def blog_category(category_slug):
    """Blog category page with search functionality"""
    from models import BlogPost, Category
    from sqlalchemy import or_, func

    current_city = _resolve_city_context(
        city_id=request.args.get('city_id'),
        city_slug=request.args.get('city')
    )

    try:
        article = BlogPost.query.filter_by(slug=category_slug, status='published').first()
        if article:
            return redirect(url_for('blog.blog_post', slug=category_slug))

        category = Category.query.filter(
            (Category.slug == category_slug) |
            (Category.name.ilike(f'%{category_slug}%'))
        ).first()

        if not category:
            return redirect(url_for('blog.blog'))

        search_query = request.args.get('q', '').strip()
        sort_order = request.args.get('sort', 'date_desc')
        page = max(1, int(request.args.get('page', 1)))
        per_page = 24

        all_categories = Category.query.filter_by(is_active=True).order_by(
            Category.sort_order, Category.name
        ).all()
        all_categories = [c for c in all_categories if c.name and len(c.name.strip()) > 2
                          and not c.name.strip().isdigit()]
        cat_map = {c.id: c.name for c in all_categories}

        cat_counts = {}
        try:
            rows = (db.session.query(BlogPost.category_id, func.count(BlogPost.id))
                    .filter(BlogPost.status == 'published', BlogPost.category_id.isnot(None))
                    .group_by(BlogPost.category_id).all())
            cat_counts = {row[0]: row[1] for row in rows}
        except Exception:
            pass

        articles_query = BlogPost.query.filter_by(status='published', category_id=category.id)

        if search_query:
            search_filter = f"%{search_query.lower()}%"
            articles_query = articles_query.filter(
                or_(
                    func.lower(BlogPost.title).like(search_filter),
                    func.lower(BlogPost.excerpt).like(search_filter),
                    func.lower(BlogPost.content).like(search_filter)
                )
            )

        if sort_order == 'date_asc':
            articles_query = articles_query.order_by(BlogPost.published_at.asc().nullsfirst(), BlogPost.created_at.asc())
        else:
            articles_query = articles_query.order_by(BlogPost.published_at.desc().nullslast(), BlogPost.created_at.desc())

        total_articles = articles_query.count()
        total_pages = math.ceil(total_articles / per_page) if total_articles else 1
        posts = articles_query.offset((page - 1) * per_page).limit(per_page).all()

        def _ser(post):
            return {
                'id': post.id,
                'title': post.title,
                'slug': post.slug,
                'excerpt': post.excerpt or '',
                'featured_image': post.featured_image,
                'published_at': post.published_at or post.created_at,
                'created_at': post.created_at,
                'reading_time': max(3, len(post.content or '') // 1200),
                'category_id': post.category_id,
                'category_name': cat_map.get(post.category_id, ''),
                'category_slug': next((c.slug for c in all_categories if c.id == post.category_id), ''),
                'url': f'/blog/{post.slug}',
                'views_count': post.views_count or 0,
            }

        return render_template(
            'blog.html',
            current_city=current_city,
            articles=[_ser(p) for p in posts],
            hero_article=None,
            all_categories=all_categories,
            cat_counts=cat_counts,
            current_category=category,
            search_query=search_query,
            sort_order=sort_order,
            category_filter=category.slug,
            current_page=page,
            total_pages=total_pages,
            total_articles=total_articles,
            show_category_sections=False,
        )
    except Exception as e:
        import traceback
        print(f"[ERROR] Exception in blog_category ({category_slug}): {str(e)}")
        print(f"[ERROR] Traceback: {traceback.format_exc()}")
        flash('Произошла ошибка при загрузке категории. Попробуйте позже.', 'error')
        return redirect(url_for('blog.blog'))


@blog_bp.route('/news')
def news():
    """News article page"""
    current_city = _resolve_city_context(
        city_id=request.args.get('city_id'),
        city_slug=request.args.get('city')
    )
    return render_template('news.html', current_city=current_city)


# ─── City-based blog ─────────────────────────────────────────────────────────

@blog_bp.route('/<city_slug>/blog')
def blog_city(city_slug):
    """City-based blog page"""
    current_city = _resolve_city_context(city_slug=city_slug)
    if not current_city:
        return redirect(url_for('blog.blog'))
    if 'city_id' not in session or session.get('city_id') != current_city.id:
        session['city_id'] = current_city.id
        session['city_slug'] = current_city.slug
    return _render_blog_page(current_city)


# ─── Legacy /blog-new routes ─────────────────────────────────────────────────

@blog_bp.route('/blog-new')
def blog_new():
    """Public blog page (legacy)"""
    from models import BlogArticle, Category
    try:
        articles = BlogArticle.query.filter_by(status='published').order_by(
            BlogArticle.published_at.desc()
        ).all()
        categories = Category.query.filter_by(is_active=True).order_by(Category.name).all()
        return render_template(
            'blog.html',
            articles=articles,
            categories=categories,
            total_pages=1, current_page=1,
            has_prev=False, has_next=False,
            prev_num=None, next_num=None,
            search_query='', category_filter=None,
        )
    except Exception as e:
        print(f"Blog error: {str(e)}")
        import traceback; traceback.print_exc()
        try:
            return render_template('blog.html', articles=[], categories=[])
        except Exception:
            return "Временные проблемы с блогом. Попробуйте позже.", 500


@blog_bp.route('/blog-new/<slug>')
def blog_article_new(slug):
    """View single blog article (legacy)"""
    from models import BlogArticle
    try:
        article = BlogArticle.query.filter_by(slug=slug, status='published').first_or_404()
        article.views_count += 1
        db.session.commit()
        related_articles = BlogArticle.query.filter_by(
            category_id=article.category_id, status='published'
        ).filter(BlogArticle.id != article.id).order_by(
            BlogArticle.published_at.desc()
        ).limit(3).all()
        return render_template('blog_article.html',
                               article=article, related_articles=related_articles)
    except Exception:
        flash('Статья не найдена', 'error')
        return redirect(url_for('blog.blog_new'))


@blog_bp.route('/blog-new/category/<slug>')
def blog_category_new(slug):
    """View articles by category (legacy)"""
    from models import Category, BlogArticle
    try:
        category = Category.query.filter_by(slug=slug, is_active=True).first_or_404()
        articles = BlogArticle.query.filter_by(
            category_id=category.id, status='published'
        ).order_by(BlogArticle.published_at.desc()).all()
        return render_template('blog_category.html', category=category, articles=articles)
    except Exception:
        flash('Категория не найдена', 'error')
        return redirect(url_for('blog.blog_new'))


# ─── Blog post ───────────────────────────────────────────────────────────────

@blog_bp.route('/blog/<slug>')
def blog_post(slug):
    """Display single blog post by slug"""
    from sqlalchemy import text
    try:
        result = db.session.execute(text("""
            SELECT id, title, slug, content, excerpt, category, featured_image,
                   views_count, created_at, '' as author_name
            FROM blog_posts
            WHERE slug = :slug AND status = 'published'
        """), {'slug': slug}).fetchone()

        if not result:
            flash('Статья не найдена', 'error')
            return redirect(url_for('blog.blog'))

        post = {
            'id': result[0], 'title': result[1], 'slug': result[2],
            'content': result[3], 'excerpt': result[4], 'category': result[5],
            'featured_image': result[6], 'views_count': result[7] or 0,
            'created_at': result[8], 'author_name': result[9] or 'InBack',
        }

        try:
            db.session.execute(text(
                "UPDATE blog_posts SET views_count = COALESCE(views_count, 0) + 1 WHERE id = :id"
            ), {'id': post['id']})
            db.session.commit()
            post['views_count'] += 1
        except Exception:
            db.session.rollback()

        related_results = db.session.execute(text("""
            SELECT id, title, slug, excerpt, featured_image, created_at
            FROM blog_posts
            WHERE category = :category AND status = 'published' AND id != :id
            ORDER BY created_at DESC LIMIT 3
        """), {'category': post['category'], 'id': post['id']}).fetchall()

        related_posts = [
            {'id': r[0], 'title': r[1], 'slug': r[2],
             'excerpt': r[3], 'featured_image': r[4], 'created_at': r[5]}
            for r in related_results
        ]

        _thin_slugs = {'fyvfyv', '123', 'novaya-statya', 'bez-lishney-ploskosti'}
        _content = post.get('content') or ''
        is_thin_post = post['slug'] in _thin_slugs or len(_content.strip()) < 200
        return render_template('blog_post.html', post=post, related_posts=related_posts,
                               noindex=is_thin_post)
    except Exception:
        flash('Ошибка загрузки статьи', 'error')
        return redirect(url_for('blog.blog'))
