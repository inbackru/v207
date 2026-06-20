"""
SEO ZK Blueprint — dynamic SEO landing pages for each residential complex.

Route: /zk-<slug>
Every active ЖК in the DB automatically gets an SEO page at /zk-<slug>.
E.g. /zk-narodnye-kvartaly, /zk-dom-101, etc.
"""

from flask import Blueprint, abort, redirect, render_template, request, url_for
from sqlalchemy import text

from app import db, cache, CANONICAL_BASE_URL

seo_zk_bp = Blueprint('seo_zk', __name__)


def _get_city_forms(city_name: str) -> dict:
    """Return genitive/prepositional forms for known cities, fallback to name."""
    CITY_FORMS = {
        'Краснодар': {'gen': 'Краснодара', 'prep': 'Краснодаре'},
        'Сочи':      {'gen': 'Сочи',       'prep': 'Сочи'},
        'Анапа':     {'gen': 'Анапы',      'prep': 'Анапе'},
        'Новороссийск': {'gen': 'Новороссийска', 'prep': 'Новороссийске'},
        'Геленджик': {'gen': 'Геленджика', 'prep': 'Геленджике'},
        'Майкоп':    {'gen': 'Майкопа',    'prep': 'Майкопе'},
        'Армавир':   {'gen': 'Армавира',   'prep': 'Армавире'},
    }
    return CITY_FORMS.get(city_name, {'gen': city_name, 'prep': city_name})


def _build_faq(complex_name: str, city_name: str, city_forms: dict,
               min_price: int, max_price: int, cashback_rate: int,
               prop_count: int, end_year: int, object_class: str) -> list:
    """Auto-generate FAQ for a complex based on its data."""
    city_gen  = city_forms['gen']
    city_prep = city_forms['prep']
    cr = cashback_rate or 4
    price_str = f'{min_price // 1_000_000:.0f} млн ₽' if min_price and min_price > 0 else 'уточняйте у менеджера'
    cashback_sum = int((min_price or 5_000_000) * cr / 100) if min_price else 200_000
    cashback_str = f'{cashback_sum:,}'.replace(',', ' ')
    year_str = f'{end_year} году' if end_year else 'ближайшее время'
    cls_str = object_class or 'комфорт'

    return [
        {
            'q': f'Сколько стоят квартиры в ЖК {complex_name}?',
            'a': (
                f'Цены на квартиры в ЖК {complex_name} в {city_prep} начинаются от {price_str}. '
                f'На платформе InBack доступно {prop_count} вариантов с актуальными ценами от застройщика. '
                f'При покупке через InBack вы получаете кэшбек {cr}% — это {cashback_str} ₽ реальными деньгами.'
            ),
        },
        {
            'q': f'Как получить кэшбек при покупке квартиры в ЖК {complex_name}?',
            'a': (
                f'Оставьте заявку на InBack, выберите квартиру в ЖК {complex_name} и оформите сделку через нашего менеджера. '
                f'После регистрации ДДУ кэшбек {cr}% перечисляется вам на карту. '
                f'Никаких скрытых условий — цена квартиры та же, что у застройщика.'
            ),
        },
        {
            'q': f'Когда сдаётся ЖК {complex_name}?',
            'a': (
                f'По данным застройщика, ЖК {complex_name} планируется к сдаче в {year_str}. '
                f'Актуальные сроки уточняйте у менеджера InBack — мы работаем с застройщиком напрямую '
                f'и знаем точные даты по каждому корпусу.'
            ),
        },
        {
            'q': f'Доступна ли ипотека на квартиры в ЖК {complex_name}?',
            'a': (
                f'Да. На квартиры в ЖК {complex_name} распространяются льготные ипотечные программы: '
                f'семейная ипотека от 3,5%, IT-ипотека от 3,5%, военная ипотека и стандартные программы банков. '
                f'Менеджер InBack бесплатно помогает подобрать условия и подать заявку одновременно в несколько банков.'
            ),
        },
        {
            'q': f'Что такое ЖК {complex_name} — жилой класс, застройщик, район?',
            'a': (
                f'ЖК {complex_name} — жилой комплекс {cls_str}-класса в {city_prep}. '
                f'Подробное описание, галерея, документы и квартиры доступны на странице ЖК на InBack. '
                f'Наши менеджеры проводили экскурсии на объект и могут ответить на любые вопросы.'
            ),
        },
    ]


@seo_zk_bp.route('/zk-<slug>')
def zk_seo_page(slug: str):
    """Dynamic SEO landing page for a residential complex at /zk-<slug>."""
    try:
        row = db.session.execute(
            text("""
                SELECT
                    rc.id, rc.name, rc.slug, rc.description, rc.detailed_description,
                    rc.cashback_rate, rc.object_class_display_name,
                    rc.end_build_year, rc.end_build_quarter,
                    rc.start_build_year, rc.start_build_quarter,
                    rc.sales_address, rc.latitude, rc.longitude,
                    rc.main_image, rc.gallery_images, rc.advantages,
                    rc.ceiling_height, rc.finishing_type, rc.floors_min, rc.floors_max,
                    rc.is_active,
                    c.id   AS city_id,
                    c.name AS city_name,
                    c.slug AS city_slug,
                    d.name AS developer_name,
                    d.slug AS developer_slug,
                    di.name AS district_name,
                    di.slug AS district_slug
                FROM residential_complexes rc
                LEFT JOIN cities      c  ON c.id  = rc.city_id
                LEFT JOIN developers  d  ON d.id  = rc.developer_id
                LEFT JOIN districts   di ON di.id = rc.district_id
                WHERE rc.slug = :slug
                LIMIT 1
            """),
            {'slug': slug}
        ).fetchone()
    except Exception as e:
        abort(500)

    if not row:
        abort(404)

    if not row.is_active:
        city_slug = row.city_slug or 'krasnodar'
        return redirect(
            url_for('complexes.residential_complex_by_slug_city',
                    city_slug=city_slug, slug=slug),
            code=301
        )

    complex_id  = row.id
    complex_name = row.name or slug
    city_name   = row.city_name or 'Краснодар'
    city_slug   = row.city_slug or 'krasnodar'
    cashback_rate = row.cashback_rate or 4
    city_forms  = _get_city_forms(city_name)

    try:
        stats = db.session.execute(
            text("""
                SELECT
                    COUNT(*)            AS total,
                    MIN(price)          AS min_price,
                    MAX(price)          AS max_price,
                    MIN(area)           AS min_area,
                    MAX(area)           AS max_area
                FROM properties
                WHERE complex_id = :cid AND is_active = true
            """),
            {'cid': complex_id}
        ).fetchone()
    except Exception:
        stats = None

    prop_count = stats.total    if stats else 0
    min_price  = stats.min_price if stats else None
    max_price  = stats.max_price if stats else None

    try:
        properties = db.session.execute(
            text("""
                SELECT id, rooms, area, price, floor, floors_total,
                       image_url, is_active
                FROM properties
                WHERE complex_id = :cid AND is_active = true
                ORDER BY price ASC NULLS LAST
                LIMIT 6
            """),
            {'cid': complex_id}
        ).fetchall()
    except Exception:
        properties = []

    city_gen  = city_forms['gen']
    city_prep = city_forms['prep']
    object_class = row.object_class_display_name or 'Комфорт'

    seo_title = (
        f'ЖК {complex_name} в {city_prep} — квартиры с кэшбеком до 500 000 ₽ | InBack'
    )
    seo_description = (
        f'Квартиры в ЖК {complex_name} в {city_prep}: {prop_count} вариантов от застройщика. '
        f'Кэшбек {cashback_rate}% при покупке через InBack. Актуальные цены, планировки, ипотека.'
    )
    seo_h1 = f'ЖК {complex_name}'
    canonical_url = f'{CANONICAL_BASE_URL}/zk-{slug}'

    faq = _build_faq(
        complex_name=complex_name,
        city_name=city_name,
        city_forms=city_forms,
        min_price=int(min_price) if min_price else None,
        max_price=int(max_price) if max_price else None,
        cashback_rate=cashback_rate,
        prop_count=int(prop_count),
        end_year=row.end_build_year,
        object_class=object_class,
    )

    price_from_str = ''
    if min_price and min_price > 0:
        price_from_str = f'от {int(min_price) // 1_000_000:.0f} млн ₽'

    breadcrumbs = [
        {'title': 'Главная',          'url': f'/{city_slug}'},
        {'title': 'Новостройки',      'url': f'/{city_slug}/zhilye-kompleksy'},
        {'title': complex_name,       'url': None},
    ]

    return render_template(
        'seo/zk_landing.html',
        complex=row,
        complex_name=complex_name,
        complex_id=complex_id,
        city_name=city_name,
        city_slug=city_slug,
        city_gen=city_gen,
        city_prep=city_prep,
        object_class=object_class,
        cashback_rate=cashback_rate,
        prop_count=prop_count,
        min_price=int(min_price) if min_price else None,
        max_price=int(max_price) if max_price else None,
        price_from_str=price_from_str,
        properties=properties,
        faq=faq,
        seo_title=seo_title,
        seo_description=seo_description,
        seo_h1=seo_h1,
        canonical_url=canonical_url,
        breadcrumbs=breadcrumbs,
    )
