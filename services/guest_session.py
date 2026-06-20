from flask import session


def get_guest_favorites():
    return list(session.get('guest_favorites', []))


def toggle_guest_favorite(property_id):
    fav_list = list(session.get('guest_favorites', []))
    prop_id = str(property_id)
    if prop_id in fav_list:
        fav_list.remove(prop_id)
        session['guest_favorites'] = fav_list
        session.modified = True
        return 'removed', False
    else:
        fav_list.append(prop_id)
        session['guest_favorites'] = fav_list
        session.modified = True
        return 'added', True


def get_guest_favorite_count():
    props = len(session.get('guest_favorites', []))
    complexes = len(session.get('guest_favorite_complexes', []))
    return props, complexes


def toggle_guest_favorite_complex(complex_id):
    fav_list = list(session.get('guest_favorite_complexes', []))
    cid = str(complex_id)
    if cid in fav_list:
        fav_list.remove(cid)
        session['guest_favorite_complexes'] = fav_list
        session.modified = True
        return 'removed', False
    else:
        fav_list.append(cid)
        session['guest_favorite_complexes'] = fav_list
        session.modified = True
        return 'added', True


def get_guest_comparison_properties():
    return list(session.get('guest_comparison_properties', []))


def get_guest_comparison_complexes():
    return list(session.get('guest_comparison_complexes', []))


def add_guest_comparison_property(property_id):
    comp_list = list(session.get('guest_comparison_properties', []))
    prop_id = str(property_id)
    if prop_id in comp_list:
        return False, 'Объект уже в сравнении', len(comp_list)
    if len(comp_list) >= 4:
        return False, 'Максимум 4 объекта в сравнении', len(comp_list)
    comp_list.append(prop_id)
    session['guest_comparison_properties'] = comp_list
    session.modified = True
    return True, 'Объект добавлен в сравнение', len(comp_list)


def remove_guest_comparison_property(property_id):
    comp_list = list(session.get('guest_comparison_properties', []))
    prop_id = str(property_id)
    if prop_id in comp_list:
        comp_list.remove(prop_id)
        session['guest_comparison_properties'] = comp_list
        session.modified = True
        return True, 'Объект удален из сравнения', len(comp_list)
    return True, 'Объект не найден в сравнении', len(comp_list)


def add_guest_comparison_complex(complex_id):
    comp_list = list(session.get('guest_comparison_complexes', []))
    cid = str(complex_id)
    if cid in comp_list:
        return False, 'ЖК уже в сравнении', len(comp_list)
    if len(comp_list) >= 4:
        return False, 'Максимум 4 ЖК в сравнении', len(comp_list)
    comp_list.append(cid)
    session['guest_comparison_complexes'] = comp_list
    session.modified = True
    return True, 'ЖК добавлен в сравнение', len(comp_list)


def remove_guest_comparison_complex(complex_id):
    comp_list = list(session.get('guest_comparison_complexes', []))
    cid = str(complex_id)
    if cid in comp_list:
        comp_list.remove(cid)
        session['guest_comparison_complexes'] = comp_list
        session.modified = True
        return True, 'ЖК удален из сравнения', len(comp_list)
    return True, 'ЖК не найден в сравнении', len(comp_list)


def clear_guest_comparison():
    session.pop('guest_comparison_properties', None)
    session.pop('guest_comparison_complexes', None)
    session.modified = True


def clear_guest_favorites():
    session.pop('guest_favorites', None)
    session.pop('guest_favorite_complexes', None)
    session.modified = True


def merge_guest_to_user(user_id, db_session):
    from models import FavoriteProperty, FavoriteComplex, UserComparison, ComparisonProperty, ComparisonComplex

    guest_favs = session.get('guest_favorites', [])
    if guest_favs:
        for prop_id in guest_favs:
            existing = FavoriteProperty.query.filter_by(
                user_id=user_id, property_id=str(prop_id)
            ).first()
            if not existing:
                fav = FavoriteProperty(
                    user_id=user_id,
                    property_id=str(prop_id),
                    property_name='',
                    property_type='',
                    property_size=0,
                    property_price=0,
                    complex_name='',
                    developer_name=''
                )
                db_session.add(fav)
        db_session.commit()
        session.pop('guest_favorites', None)

    guest_fav_complexes = session.get('guest_favorite_complexes', [])
    if guest_fav_complexes:
        for cid in guest_fav_complexes:
            existing = FavoriteComplex.query.filter_by(
                user_id=user_id, complex_id=str(cid)
            ).first()
            if not existing:
                fav = FavoriteComplex(
                    user_id=user_id,
                    complex_id=str(cid),
                    complex_name='',
                    developer_name='',
                    complex_address='',
                    district='',
                    complex_image='',
                    complex_url='',
                    status=''
                )
                db_session.add(fav)
        db_session.commit()
        session.pop('guest_favorite_complexes', None)

    guest_comps = session.get('guest_comparison_properties', [])
    if guest_comps:
        user_comparison = UserComparison.query.filter_by(
            user_id=user_id, is_active=True
        ).first()
        if not user_comparison:
            user_comparison = UserComparison(
                user_id=user_id, name='Мое сравнение', is_active=True
            )
            db_session.add(user_comparison)
            db_session.flush()

        for prop_id in guest_comps:
            existing = ComparisonProperty.query.filter_by(
                user_comparison_id=user_comparison.id,
                property_id=str(prop_id)
            ).first()
            if not existing:
                current_count = ComparisonProperty.query.filter_by(
                    user_comparison_id=user_comparison.id
                ).count()
                if current_count < 4:
                    cp = ComparisonProperty(
                        user_comparison_id=user_comparison.id,
                        property_id=str(prop_id),
                        order_index=current_count
                    )
                    db_session.add(cp)
        db_session.commit()
        session.pop('guest_comparison_properties', None)

    guest_comp_complexes = session.get('guest_comparison_complexes', [])
    if guest_comp_complexes:
        user_comparison = UserComparison.query.filter_by(
            user_id=user_id, is_active=True
        ).first()
        if not user_comparison:
            user_comparison = UserComparison(
                user_id=user_id, name='Мое сравнение', is_active=True
            )
            db_session.add(user_comparison)
            db_session.flush()

        for cid in guest_comp_complexes:
            existing = ComparisonComplex.query.filter_by(
                user_comparison_id=user_comparison.id,
                complex_id=str(cid)
            ).first()
            if not existing:
                current_count = ComparisonComplex.query.filter_by(
                    user_comparison_id=user_comparison.id
                ).count()
                if current_count < 4:
                    cc = ComparisonComplex(
                        user_comparison_id=user_comparison.id,
                        complex_id=str(cid),
                        order_index=current_count
                    )
                    db_session.add(cc)
        db_session.commit()
        session.pop('guest_comparison_complexes', None)

    session.modified = True
