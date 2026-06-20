"""
routes/city_pages.py — Simple /<city_slug>/X redirect pages (extracted from app.py)

These thin pages set city context in session and render a template,
or redirect to the canonical non-city URL if the city_slug is invalid.
"""
from flask import Blueprint, redirect, render_template, request, session, url_for

from app import db
from sqlalchemy import text

bp = Blueprint('city_pages', __name__)


def _resolve_city_context(**kwargs):
    from app import resolve_city_context as _rcc
    return _rcc(**kwargs)


def _render_map_page(current_city):
    from routes.public_api import _render_map_page as _rmp
    return _rmp(current_city)


# CITY-BASED SEO-FRIENDLY ROUTES
# ==========================================
# These routes provide city-specific URLs for better SEO
# Format: /<city_slug>/properties, /<city_slug>/object/123, etc.

@bp.route('/<city_slug>/ipoteka')
def ipoteka_city(city_slug):
    """City-based ipoteka page"""
    current_city = _resolve_city_context(city_slug=city_slug)
    if not current_city:
        return redirect(url_for('mortgage.ipoteka'))
    if 'city_id' not in session or session.get('city_id') != current_city.id:
        session['city_id'] = current_city.id
        session['city_slug'] = current_city.slug
    return render_template('ipoteka.html', current_city=current_city)

@bp.route('/<city_slug>/semejnaya-ipoteka')
def family_mortgage_city(city_slug):
    """City-based family mortgage page"""
    current_city = _resolve_city_context(city_slug=city_slug)
    if not current_city:
        return redirect(url_for('mortgage.family_mortgage'))
    if 'city_id' not in session or session.get('city_id') != current_city.id:
        session['city_id'] = current_city.id
        session['city_slug'] = current_city.slug
    return render_template('family_mortgage.html', current_city=current_city)

@bp.route('/<city_slug>/it-ipoteka')
def it_mortgage_city(city_slug):
    """City-based IT mortgage page"""
    current_city = _resolve_city_context(city_slug=city_slug)
    if not current_city:
        return redirect(url_for('mortgage.it_mortgage'))
    if 'city_id' not in session or session.get('city_id') != current_city.id:
        session['city_id'] = current_city.id
        session['city_slug'] = current_city.slug
    return render_template('it_mortgage.html', current_city=current_city)

@bp.route('/<city_slug>/voennaya-ipoteka')
def military_mortgage_city(city_slug):
    """City-based military mortgage page"""
    current_city = _resolve_city_context(city_slug=city_slug)
    if not current_city:
        return redirect(url_for('mortgage.military_mortgage'))
    if 'city_id' not in session or session.get('city_id') != current_city.id:
        session['city_id'] = current_city.id
        session['city_slug'] = current_city.slug
    return render_template('military_mortgage.html', current_city=current_city)

@bp.route('/<city_slug>/ipoteka-ot-zastrojshchika')
def developer_mortgage_city(city_slug):
    """City-based developer mortgage page"""
    current_city = _resolve_city_context(city_slug=city_slug)
    if not current_city:
        return redirect(url_for('mortgage.developer_mortgage'))
    if 'city_id' not in session or session.get('city_id') != current_city.id:
        session['city_id'] = current_city.id
        session['city_slug'] = current_city.slug
    return render_template('developer_mortgage.html', current_city=current_city)

@bp.route('/<city_slug>/materinsky-kapital')
def maternal_capital_city(city_slug):
    """City-based maternal capital page"""
    current_city = _resolve_city_context(city_slug=city_slug)
    if not current_city:
        return redirect(url_for('mortgage.maternal_capital'))
    if 'city_id' not in session or session.get('city_id') != current_city.id:
        session['city_id'] = current_city.id
        session['city_slug'] = current_city.slug
    return render_template('maternal_capital.html', current_city=current_city)

@bp.route('/<city_slug>/nalogovyj-vychet')
def tax_deduction_city(city_slug):
    """City-based tax deduction page"""
    current_city = _resolve_city_context(city_slug=city_slug)
    if not current_city:
        return redirect(url_for('mortgage.tax_deduction'))
    if 'city_id' not in session or session.get('city_id') != current_city.id:
        session['city_id'] = current_city.id
        session['city_slug'] = current_city.slug
    return render_template('tax_deduction.html', current_city=current_city)

@bp.route('/<city_slug>/strahovanie')
def insurance_city(city_slug):
    """City-based insurance page"""
    current_city = _resolve_city_context(city_slug=city_slug)
    if not current_city:
        return redirect(url_for('mortgage.insurance'))
    if 'city_id' not in session or session.get('city_id') != current_city.id:
        session['city_id'] = current_city.id
        session['city_slug'] = current_city.slug
    return render_template('insurance.html', current_city=current_city)

@bp.route('/<city_slug>/otsenka')
def appraisal_city(city_slug):
    """City-based appraisal page"""
    current_city = _resolve_city_context(city_slug=city_slug)
    if not current_city:
        return redirect(url_for('mortgage.appraisal'))
    if 'city_id' not in session or session.get('city_id') != current_city.id:
        session['city_id'] = current_city.id
        session['city_slug'] = current_city.slug
    return render_template('appraisal.html', current_city=current_city)

@bp.route('/<city_slug>/o-kompanii')
def about_city(city_slug):
    """City-based about page"""
    current_city = _resolve_city_context(city_slug=city_slug)
    if not current_city:
        return redirect(url_for('main.about'))
    if 'city_id' not in session or session.get('city_id') != current_city.id:
        session['city_id'] = current_city.id
        session['city_slug'] = current_city.slug
    return render_template('about.html', current_city=current_city)

@bp.route('/<city_slug>/kak-eto-rabotaet')
def how_it_works_city(city_slug):
    """City-based how-it-works page"""
    current_city = _resolve_city_context(city_slug=city_slug)
    if not current_city:
        return redirect(url_for('main.how_it_works'))
    if 'city_id' not in session or session.get('city_id') != current_city.id:
        session['city_id'] = current_city.id
        session['city_slug'] = current_city.slug
    return render_template('how-it-works.html', current_city=current_city)

@bp.route('/<city_slug>/kontakty')
def contacts_city(city_slug):
    """City-based contacts page"""
    current_city = _resolve_city_context(city_slug=city_slug)
    if not current_city:
        return redirect(url_for('main.contacts'))
    if 'city_id' not in session or session.get('city_id') != current_city.id:
        session['city_id'] = current_city.id
        session['city_slug'] = current_city.slug
    return render_template('contacts.html', current_city=current_city)

@bp.route('/<city_slug>/otzyvy')
def reviews_city(city_slug):
    """City-based reviews page"""
    current_city = _resolve_city_context(city_slug=city_slug)
    if not current_city:
        return redirect(url_for('main.reviews'))
    if 'city_id' not in session or session.get('city_id') != current_city.id:
        session['city_id'] = current_city.id
        session['city_slug'] = current_city.slug
    return render_template('reviews.html', current_city=current_city)

@bp.route('/<city_slug>/security')
def security_city(city_slug):
    """City-based security page"""
    current_city = _resolve_city_context(city_slug=city_slug)
    if not current_city:
        return redirect(url_for('security'))
    if 'city_id' not in session or session.get('city_id') != current_city.id:
        session['city_id'] = current_city.id
        session['city_slug'] = current_city.slug
    return render_template('security.html', current_city=current_city)

@bp.route('/<city_slug>/karta')
@bp.route('/<city_slug>/map')
def map_city(city_slug):
    """City-based map page — redirect to complexes page with map"""
    return redirect(url_for('complexes.residential_complexes_city', city_slug=city_slug), 301)

@bp.route('/<city_slug>/sravnenie')
def comparison_city(city_slug):
    """City-based comparison page"""
    current_city = _resolve_city_context(city_slug=city_slug)
    if not current_city:
        return redirect(url_for('main.comparison'))
    if 'city_id' not in session or session.get('city_id') != current_city.id:
        session['city_id'] = current_city.id
        session['city_slug'] = current_city.slug
    return render_template('comparison.html', current_city=current_city)

@bp.route('/<city_slug>/sdelki')
def deals_city(city_slug):
    """City-based deals page"""
    from flask_login import current_user
    from flask import redirect
    if not current_user.is_authenticated:
        return redirect(url_for('auth.login', next=f'/{city_slug}/sdelki'))
    current_city = _resolve_city_context(city_slug=city_slug)
    if not current_city:
        return redirect(url_for('dashboard') + '#deals')
    if 'city_id' not in session or session.get('city_id') != current_city.id:
        session['city_id'] = current_city.id
        session['city_slug'] = current_city.slug
    return render_template('sdelki.html', current_city=current_city, city_slug=city_slug)


@bp.route('/<city_slug>/rekomendatsii')
def recommendations_city(city_slug):
    """City-based recommendations page"""
    from flask_login import current_user
    from flask import redirect
    if not current_user.is_authenticated:
        return redirect(url_for('auth.login', next=f'/{city_slug}/rekomendatsii'))
    current_city = _resolve_city_context(city_slug=city_slug)
    if not current_city:
        return redirect(url_for('dashboard') + '#recommendations')
    if 'city_id' not in session or session.get('city_id') != current_city.id:
        session['city_id'] = current_city.id
        session['city_slug'] = current_city.slug
    return render_template('rekomendatsii.html', current_city=current_city, city_slug=city_slug)


@bp.route('/<city_slug>/balans')
def balance_city(city_slug):
    """City-based balance page"""
    from flask_login import current_user
    from flask import redirect
    if not current_user.is_authenticated:
        return redirect(url_for('auth.login', next=f'/{city_slug}/balans'))
    current_city = _resolve_city_context(city_slug=city_slug)
    if not current_city:
        return redirect(url_for('dashboard') + '?tab=balance')
    if 'city_id' not in session or session.get('city_id') != current_city.id:
        session['city_id'] = current_city.id
        session['city_slug'] = current_city.slug
    return render_template('balans.html', current_city=current_city, city_slug=city_slug)


@bp.route('/<city_slug>/nastrojki')
def settings_city(city_slug):
    """City-based profile settings page"""
    from flask_login import current_user
    from flask import redirect
    if not current_user.is_authenticated:
        return redirect(url_for('auth.login', next=f'/{city_slug}/nastrojki'))
    current_city = _resolve_city_context(city_slug=city_slug)
    if not current_city:
        return redirect(url_for('dashboard') + '#settings')
    if 'city_id' not in session or session.get('city_id') != current_city.id:
        session['city_id'] = current_city.id
        session['city_slug'] = current_city.slug
    assigned_manager = None
    try:
        if current_user.assigned_manager_id:
            from models import User
            assigned_manager = User.query.get(current_user.assigned_manager_id)
    except Exception:
        pass
    return render_template('nastrojki.html', current_city=current_city, city_slug=city_slug,
                           assigned_manager=assigned_manager)


@bp.route('/<city_slug>/partnerka')
def referral_city(city_slug):
    """City-based partner/referral page"""
    from flask_login import current_user
    from flask import redirect
    if not current_user.is_authenticated:
        return redirect(url_for('auth.login', next=f'/{city_slug}/partnerka'))
    current_city = _resolve_city_context(city_slug=city_slug)
    if not current_city:
        return redirect(url_for('dashboard') + '#referral')
    if 'city_id' not in session or session.get('city_id') != current_city.id:
        session['city_id'] = current_city.id
        session['city_slug'] = current_city.slug
    return render_template('partnerka.html', current_city=current_city, city_slug=city_slug)


@bp.route('/<city_slug>/izbrannoe')
def favorites_city(city_slug):
    """City-based favorites page"""
    current_city = _resolve_city_context(city_slug=city_slug)
    if not current_city:
        return redirect(url_for('main.favorites'))
    if 'city_id' not in session or session.get('city_id') != current_city.id:
        session['city_id'] = current_city.id
        session['city_slug'] = current_city.slug
    return render_template('favorites.html', current_city=current_city)

@bp.route('/<city_slug>/usloviya-keshbeka')
def cashback_terms_city(city_slug):
    """City-based cashback terms page"""
    current_city = _resolve_city_context(city_slug=city_slug)
    if not current_city:
        return redirect(url_for('mortgage.cashback_terms'))
    if 'city_id' not in session or session.get('city_id') != current_city.id:
        session['city_id'] = current_city.id
        session['city_slug'] = current_city.slug
    return render_template('cashback_terms.html', current_city=current_city)

@bp.route('/<city_slug>/kalkulyator-keshbeka')
def cashback_calculator_city(city_slug):
    """Programmatic cashback calculator — SEO page with SoftwareApplication schema"""
    from models import ResidentialComplex
    current_city = _resolve_city_context(city_slug=city_slug)
    if not current_city:
        return redirect(url_for('mortgage.cashback_calculator'))
    if 'city_id' not in session or session.get('city_id') != current_city.id:
        session['city_id'] = current_city.id
        session['city_slug'] = current_city.slug
    try:
        total_complexes = ResidentialComplex.query.filter_by(
            is_active=True, city_id=current_city.id
        ).count()
        from sqlalchemy import func
        avg_price_row = db.session.query(func.avg(ResidentialComplex.price_from)).filter(
            ResidentialComplex.is_active == True,
            ResidentialComplex.city_id == current_city.id,
            ResidentialComplex.price_from.isnot(None),
            ResidentialComplex.price_from > 0
        ).scalar()
        avg_price = int(avg_price_row) if avg_price_row else 6_000_000
    except Exception:
        total_complexes = 200
        avg_price = 6_000_000
    return render_template(
        'cashback_calculator.html',
        current_city=current_city,
        city_slug=city_slug,
        total_complexes=total_complexes,
        avg_price=avg_price,
    )


@bp.route('/<city_slug>/cashback-kvartiry')
def cashback_kvartiry_city(city_slug):
    """SEO landing page: cashback for apartments"""
    current_city = _resolve_city_context(city_slug=city_slug, default_if_none=True)
    if not current_city:
        current_city = _resolve_city_context()
    if current_city and ('city_id' not in session or session.get('city_id') != current_city.id):
        session['city_id'] = current_city.id
        session['city_slug'] = current_city.slug
    # Get stats for the page
    try:
        from models import ResidentialComplex, Property
        total_complexes = db.session.query(ResidentialComplex).filter(
            ResidentialComplex.city_id == current_city.id if current_city else True
        ).count() if current_city else 0
        avg_cashback = 3.5
        max_cashback = 500000
    except Exception:
        total_complexes = 0
        avg_cashback = 3.5
        max_cashback = 500000
    return render_template('seo_cashback.html',
                           current_city=current_city,
                           total_complexes=total_complexes,
                           avg_cashback=avg_cashback,
                           max_cashback=max_cashback)


@bp.route('/<city_slug>/slovar-nedvizhimosti')
def glossary_city(city_slug):
    """City-based real estate glossary page"""
    current_city = _resolve_city_context(city_slug=city_slug)
    if not current_city:
        from flask import redirect as _redir
        return _redir('/slovar-nedvizhimosti')
    if 'city_id' not in session or session.get('city_id') != current_city.id:
        session['city_id'] = current_city.id
        session['city_slug'] = current_city.slug
    from routes.glossary_data import GLOSSARY_TERMS
    from models import ResidentialComplex
    try:
        complexes_count = ResidentialComplex.query.filter_by(
            is_active=True, city_id=current_city.id
        ).count()
    except Exception:
        complexes_count = 200
    return render_template(
        'glossary.html',
        current_city=current_city,
        glossary_terms=GLOSSARY_TERMS,
        complexes_count=complexes_count,
    )


@bp.route('/<city_slug>/ulitsy')
@bp.route('/<city_slug>/streets')
def streets_city(city_slug):
    """City-based streets page"""
    current_city = _resolve_city_context(city_slug=city_slug)
    if not current_city:
        return redirect(url_for('streets.streets'))
    if 'city_id' not in session or session.get('city_id') != current_city.id:
        session['city_id'] = current_city.id
        session['city_slug'] = current_city.slug
    from routes.streets import _render_streets_page
    return _render_streets_page(current_city)

@bp.route('/<city_slug>/')
def city_home(city_slug):
    """City-based homepage - shows index page with city context"""
    from models import City
    city = City.query.filter(
        db.func.lower(City.slug) == city_slug.lower()
    ).first()
    if not city:
        abort(404)
    from routes.public_api import index
    return index(city_slug=city_slug)


# ───────────────────────────────────────────────
# SEO PROGRAMMATIC LANDING PAGES (filter-slug URLs)
