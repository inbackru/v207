"""
Main Blueprint — simple info/utility redirect pages and standalone pages.

Endpoints: wallet, about, how_it_works, reviews, contacts, referral_landing,
           comparison, comparison_new, thank_you, complex_comparison, favorites
"""
import os

from flask import (Blueprint, redirect, render_template, request,
                   session, url_for)
from flask_login import current_user

from app import db
from sqlalchemy import text

main_bp = Blueprint('main', __name__)


def _resolve_city_context(**kwargs):
    from app import resolve_city_context
    return resolve_city_context(**kwargs)


def _redirect_to_city_based(endpoint):
    from app import redirect_to_city_based as _r
    return _r(endpoint)


# ─── Wallet ───────────────────────────────────────────────────────────────────

@main_bp.route('/wallet')
def wallet():
    """Wallet page with cashback information and benefits"""
    from models import Property
    current_city = _resolve_city_context(
        city_id=request.args.get('city_id'),
        city_slug=request.args.get('city')
    )
    user_property_count = 0
    if current_user.is_authenticated:
        user_property_count = Property.query.filter_by(user_id=current_user.id).count()
    return render_template('wallet.html',
                           current_city=current_city,
                           user_property_count=user_property_count)


# ─── Info redirect pages ──────────────────────────────────────────────────────

@main_bp.route('/o-kompanii')
@main_bp.route('/about')
def about():
    return _redirect_to_city_based('about_city')


@main_bp.route('/kak-eto-rabotaet')
@main_bp.route('/how-it-works')
def how_it_works():
    return _redirect_to_city_based('how_it_works_city')


@main_bp.route('/otzyvy')
@main_bp.route('/reviews')
def reviews():
    return _redirect_to_city_based('reviews_city')


@main_bp.route('/kontakty')
@main_bp.route('/contacts')
def contacts():
    return _redirect_to_city_based('contacts_city')


# ─── Referral ─────────────────────────────────────────────────────────────────

@main_bp.route('/referral')
@main_bp.route('/referral/')
def referral_landing():
    from datetime import datetime
    from models import Property, City
    total_properties = Property.query.filter_by(is_active=True).count()
    total_cities = City.query.filter(City.id.in_(
        db.session.query(Property.city_id).filter(Property.is_active == True).distinct()
    )).count()
    return render_template('referral.html',
                           current_year=datetime.now().year,
                           total_properties=total_properties,
                           total_cities=total_cities)


# ─── Comparison ───────────────────────────────────────────────────────────────

@main_bp.route('/sravnenie')
@main_bp.route('/comparison')
def comparison():
    return _redirect_to_city_based('comparison_city')


@main_bp.route('/comparison-new')
def comparison_new():
    current_city = _resolve_city_context(
        city_id=request.args.get('city_id'),
        city_slug=request.args.get('city')
    )
    return render_template('comparison_new.html')


@main_bp.route('/complex-comparison')
def complex_comparison():
    current_city = _resolve_city_context(
        city_id=request.args.get('city_id'),
        city_slug=request.args.get('city')
    )
    return render_template('complex_comparison.html', current_city=current_city)


# ─── Misc ─────────────────────────────────────────────────────────────────────

@main_bp.route('/thank-you')
def thank_you():
    return render_template('thank_you.html')


@main_bp.route('/izbrannoe')
@main_bp.route('/favorites')
def favorites():
    return _redirect_to_city_based('favorites_city')
