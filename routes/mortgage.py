"""
Mortgage Blueprint — mortgage/finance redirect pages, sitemap, insurance form.

Endpoints: family_mortgage, it_mortgage, insurance, appraisal, military_mortgage,
           developer_mortgage, maternal_capital, ipoteka, cashback_terms,
           tax_deduction, residential, residential_complexes, map_view,
           sitemap_html, submit_insurance_application
"""
import re
import traceback
from datetime import datetime

from flask import (Blueprint, jsonify, redirect, render_template,
                   request, url_for)
from flask import current_app

mortgage_bp = Blueprint('mortgage', __name__)


def _redirect_to_city_based(endpoint):
    from app import redirect_to_city_based as _r
    return _r(endpoint)


def _send_email(*args, **kwargs):
    from app import send_email
    return send_email(*args, **kwargs)


def _validate_csrf(token):
    from app import validate_csrf
    return validate_csrf(token)


# ─── Mortgage redirect pages ──────────────────────────────────────────────────

@mortgage_bp.route('/semejnaya-ipoteka')
@mortgage_bp.route('/family-mortgage')
def family_mortgage():
    return _redirect_to_city_based('family_mortgage_city')


@mortgage_bp.route('/it-ipoteka')
@mortgage_bp.route('/it-mortgage')
def it_mortgage():
    return _redirect_to_city_based('it_mortgage_city')


@mortgage_bp.route('/strahovanie')
@mortgage_bp.route('/insurance')
def insurance():
    return _redirect_to_city_based('insurance_city')


@mortgage_bp.route('/otsenka')
@mortgage_bp.route('/appraisal')
def appraisal():
    return _redirect_to_city_based('appraisal_city')


@mortgage_bp.route('/voennaya-ipoteka')
@mortgage_bp.route('/military-mortgage')
def military_mortgage():
    return _redirect_to_city_based('military_mortgage_city')


@mortgage_bp.route('/ipoteka-ot-zastrojshchika')
@mortgage_bp.route('/developer-mortgage')
def developer_mortgage():
    return _redirect_to_city_based('developer_mortgage_city')


@mortgage_bp.route('/materinsky-kapital')
@mortgage_bp.route('/maternal-capital')
def maternal_capital():
    return _redirect_to_city_based('maternal_capital_city')


@mortgage_bp.route('/ipoteka')
def ipoteka():
    return _redirect_to_city_based('ipoteka_city')


@mortgage_bp.route('/usloviya-keshbeka')
@mortgage_bp.route('/cashback-terms')
def cashback_terms():
    return _redirect_to_city_based('cashback_terms_city')


@mortgage_bp.route('/nalogovyj-vychet')
@mortgage_bp.route('/tax-deduction')
def tax_deduction():
    return _redirect_to_city_based('tax_deduction_city')


@mortgage_bp.route('/kalkulyator-keshbeka')
def cashback_calculator():
    """Redirect to city-based cashback calculator"""
    return _redirect_to_city_based('city_pages.cashback_calculator_city')


@mortgage_bp.route('/slovar-nedvizhimosti')
@mortgage_bp.route('/glossary')
def glossary():
    """Glossary of real estate terms — topical authority page"""
    from routes.glossary_data import GLOSSARY_TERMS
    from models import City, ResidentialComplex
    city = None
    try:
        from flask import session
        city_id = session.get('city_id')
        if city_id:
            city = City.query.get(city_id)
        if not city:
            city = City.query.filter_by(slug='krasnodar').first()
    except Exception:
        pass
    try:
        complexes_count = ResidentialComplex.query.filter_by(is_active=True).count()
    except Exception:
        complexes_count = 200
    return render_template(
        'glossary.html',
        current_city=city,
        glossary_terms=GLOSSARY_TERMS,
        complexes_count=complexes_count,
    )


# ─── Residential ─────────────────────────────────────────────────────────────

@mortgage_bp.route('/residential')
def residential():
    return render_template('residential.html')


@mortgage_bp.route('/zhilye-kompleksy')
@mortgage_bp.route('/residential-complexes')
def residential_complexes():
    return _redirect_to_city_based('residential_complexes_city')


@mortgage_bp.route('/karta')
@mortgage_bp.route('/map')
def map_view():
    return _redirect_to_city_based('map_city')


# ─── Public HTML sitemap ──────────────────────────────────────────────────────

@mortgage_bp.route('/karta-sayta')
@mortgage_bp.route('/sitemap-html')
def sitemap_html():
    try:
        from models import City, ResidentialComplex
        cities = City.query.filter_by(is_active=True).order_by(City.id).all()
        try:
            top_complexes = ResidentialComplex.query.filter_by(is_active=True).order_by(
                ResidentialComplex.cashback_rate.desc()
            ).limit(40).all()
        except Exception:
            top_complexes = ResidentialComplex.query.filter_by(is_active=True).limit(40).all()
        return render_template(
            'sitemap_public.html',
            cities=cities,
            top_complexes=top_complexes,
            current_city=None,
        )
    except Exception as e:
        current_app.logger.error(f"ERROR in sitemap_html: {e}")
        return f"<pre>Error: {e}\n{traceback.format_exc()}</pre>", 500


# ─── Insurance application form submission ────────────────────────────────────

@mortgage_bp.route('/submit-insurance-application', methods=['POST'])
def submit_insurance_application():
    """Submit insurance application with CSRF protection and enhanced validation"""
    try:
        try:
            _validate_csrf(request.form.get('csrf_token'))
        except Exception:
            return jsonify({'success': False, 'error': 'CSRF token missing or invalid'}), 400

        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip()
        bank = request.form.get('bank', '').strip()
        credit_amount = request.form.get('credit_amount', '').strip()
        birth_date = request.form.get('birth_date', '').strip()
        gender = request.form.get('gender', '').strip()
        comment = request.form.get('comment', '').strip()

        if not all([name, phone, bank, credit_amount, birth_date, gender]):
            return jsonify({'success': False, 'error': 'Заполните все обязательные поля'}), 400

        if not re.match(r'^[а-яА-ЯёЁa-zA-Z\s]{2,50}$', name):
            return jsonify({'success': False, 'error': 'Некорректное имя'}), 400

        phone_clean = re.sub(r'[^\d]', '', phone)
        if not re.match(r'^[78]\d{10}$', phone_clean):
            return jsonify({'success': False, 'error': 'Некорректный номер телефона'}), 400

        try:
            credit_amount_num = float(re.sub(r'[^\d.]', '', credit_amount))
            if credit_amount_num < 100000 or credit_amount_num > 50000000:
                return jsonify({'success': False,
                                'error': 'Сумма кредита должна быть от 100 000 до 50 000 000 рублей'}), 400
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Некорректная сумма кредита'}), 400

        try:
            birth_dt = datetime.strptime(birth_date, '%Y-%m-%d')
            age = (datetime.now() - birth_dt).days / 365.25
            if age < 18 or age > 100:
                return jsonify({'success': False, 'error': 'Возраст должен быть от 18 до 100 лет'}), 400
        except ValueError:
            return jsonify({'success': False, 'error': 'Некорректная дата рождения'}), 400

        if gender not in ['Мужчина', 'Женщина']:
            return jsonify({'success': False, 'error': 'Некорректный пол'}), 400

        try:
            credit_amount_formatted = f"{int(credit_amount):,}".replace(",", " ") + " ₽"
        except Exception:
            credit_amount_formatted = credit_amount + " ₽"

        current_time = datetime.now().strftime('%d.%m.%Y %H:%M')

        email_success = False
        try:
            email_success = _send_email(
                'bithome@mail.ru',
                f'Новая заявка на страхование от {name}',
                'emails/insurance_application.html',
                name=name, phone=phone, bank=bank,
                credit_amount=credit_amount_formatted,
                birth_date=birth_date, gender=gender, comment=comment,
                submitted_at=datetime.now(), current_time=current_time
            )
        except Exception as email_error:
            current_app.logger.error(f"Insurance application email error: {email_error}")

        telegram_success = False
        try:
            from email_service import send_telegram_insurance_notification
            telegram_success = send_telegram_insurance_notification(
                name=name, phone=phone, bank=bank,
                credit_amount=credit_amount_formatted,
                birth_date=birth_date, gender=gender, comment=comment,
                current_time=current_time
            )
        except Exception as telegram_error:
            current_app.logger.error(f"Insurance application Telegram error: {telegram_error}")

        if email_success and telegram_success:
            return jsonify({'success': True,
                            'message': 'Заявка успешно отправлена на email и в Telegram'})
        elif email_success:
            return jsonify({'success': True,
                            'message': 'Заявка отправлена на email, но не удалось отправить в Telegram',
                            'warning': True})
        elif telegram_success:
            return jsonify({'success': True,
                            'message': 'Заявка отправлена в Telegram, но не удалось отправить на email',
                            'warning': True})
        else:
            return jsonify({'success': False,
                            'error': 'Ошибка отправки заявки и на email, и в Telegram'}), 500

    except Exception as e:
        current_app.logger.error(f"Error in insurance application: {e}")
        return jsonify({'success': False, 'error': 'Внутренняя ошибка сервера'}), 500
