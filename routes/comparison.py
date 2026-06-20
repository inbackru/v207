"""
Comparison, Collections & Recommendations Blueprint
Routes: /api/user/collections, /api/user/recommendations,
        /api/user/comparison/*, /api/manager/comparison/*,
        /api/recommendations/*, /api/manager/recommendation-categories,
        /api/manager/deals, /api/manager/generate-comparison-pdf,
        /api/manager/dashboard-stats, /api/manager/top-clients
"""
import json
import io
import os
import logging
from datetime import datetime

from flask import Blueprint, jsonify, request, session, redirect, url_for, current_app
from flask_login import current_user, login_required

from app import db, csrf, cache, manager_required, admin_required, resolve_city_context
from models import Manager

logger = logging.getLogger(__name__)

comparison_bp = Blueprint('comparison', __name__)

@comparison_bp.route('/api/user/collections', methods=['GET'])
@login_required
def api_user_get_collections():
    """Get collections assigned to current user"""
    from models import Collection
    import json
    from zoneinfo import ZoneInfo
    
    try:
        collections = Collection.query.filter_by(
            assigned_to_user_id=current_user.id
        ).order_by(Collection.created_at.desc()).all()
        
        collections_data = []
        for collection in collections:
            # Get manager info
            manager = collection.created_by
            manager_name = manager.full_name if manager else 'Менеджер'
            # Use manager's profile image if available, otherwise use first letter
            # Use manager's profile image if available and not randomuser.me, otherwise use first letter
            if manager and manager.profile_image and 'randomuser.me' not in manager.profile_image:
                # Convert relative path to absolute URL
                if manager.profile_image.startswith('http'):
                    manager_avatar = manager.profile_image
                else:
                    base_url = request.host_url.rstrip('/')
                    manager_avatar = f"{base_url}{manager.profile_image}"
            else:
                manager_avatar = manager_name[0].upper() if manager_name else 'М'
            
            # ✅ MIGRATED: Get properties with images from normalized tables
            from repositories.property_repository import PropertyRepository as _PropRepo
            properties_data = []
            for prop in collection.properties[:4]:
                # Load property - try by ID first, then by inner_id for consistency
                property_obj = _PropRepo.get_by_id(prop.property_id)
                if not property_obj:
                    from models import Property as PropertyModel
                    property_obj = PropertyModel.query.filter_by(inner_id=prop.property_id).first()
                if property_obj:
                    # Get first photo from photos array
                    image_url = ''
                    if property_obj.gallery_images:
                        try:
                            photos_list = json.loads(property_obj.gallery_images) if isinstance(property_obj.gallery_images, str) else property_obj.gallery_images
                            image_url = photos_list[0] if photos_list and len(photos_list) > 0 else ''
                        except Exception as photo_error:
                            print(f"DEBUG: Error parsing photos for property {prop.property_id}: {photo_error}")
                    
                    # Build title from property data
                    rooms_text = f"{property_obj.rooms}-комн" if property_obj.rooms and property_obj.rooms > 0 else "Студия"
                    area_text = f"{property_obj.area} м²" if property_obj.area else ""
                    title = f"{rooms_text}, {area_text}".strip(', ')
                    
                    properties_data.append({
                        'id': prop.property_id,
                        'image': image_url,
                        'title': title
                    })
            
            collections_data.append({
                'id': collection.id,
                'title': collection.title,
                'description': collection.description,
                'status': collection.status,
                'created_at': collection.created_at.replace(tzinfo=ZoneInfo('UTC')).astimezone(ZoneInfo('Europe/Moscow')).strftime('%d.%m.%Y в %H:%M'),
                'manager_name': manager_name,
                'manager_avatar': manager_avatar,
                'properties_count': len(collection.properties),
                'properties': properties_data,
                'unique_url': collection.unique_url
            })
        
        print(f"🎯 Collections API: returning {len(collections_data)} collections")
        
        return jsonify({
            'success': True,
            'collections': collections_data
        })
        
    except Exception as e:
        print(f"❌ Error loading collections: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 400

@login_required
def api_user_get_saved_searches():
    """Get saved searches for current user"""
    from models import SavedSearch
    
    try:
        # Get regular saved searches
        saved_searches = SavedSearch.query.filter_by(
            user_id=current_user.id
        ).order_by(SavedSearch.created_at.desc()).all()
        
        # Get sent searches from managers
        from models import SentSearch
        sent_searches = SentSearch.query.filter_by(
            client_id=current_user.id
        ).order_by(SentSearch.sent_at.desc()).all()
        
        searches_data = []
        
        # Add regular saved searches
        for search in saved_searches:
            filters = {}
            if search.filters:
                import json
                filters = json.loads(search.filters) if isinstance(search.filters, str) else search.filters
            
            searches_data.append({
                'id': search.id,
                'name': search.name,
                'filters': filters,
                'created_at': search.created_at.strftime('%d.%m.%Y'),
                'last_used': search.last_used.strftime('%d.%m.%Y') if search.last_used else None,
                'type': 'saved'
            })
        
        # Add sent searches from managers
        for search in sent_searches:
            filters = {}
            if search.additional_filters:
                import json
                filters = json.loads(search.additional_filters) if isinstance(search.additional_filters, str) else search.additional_filters
            
            searches_data.append({
                'id': search.id,
                'name': search.name,
                'filters': filters,
                'created_at': search.sent_at.strftime('%d.%m.%Y') if search.sent_at else 'Не указано',
                'last_used': search.applied_at.strftime('%d.%m.%Y') if search.applied_at else None,
                'type': 'sent',
                'from_manager': True
            })
        
        return jsonify({
            'success': True,
            'searches': searches_data
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@comparison_bp.route('/api/user/recommendations', methods=['GET'])
@login_required
def api_user_get_recommendations():
    """Get recommendations for current user"""
    from models import Recommendation, SentSearch
    from datetime import datetime
    
    try:
        print(f"DEBUG: Loading recommendations for user ID: {current_user.id}")
        
        # Get traditional recommendations
        recommendations = Recommendation.query.filter_by(
            client_id=current_user.id
        ).order_by(Recommendation.sent_at.desc()).all()
        
        print(f"DEBUG: Found {len(recommendations)} recommendations for user {current_user.id}")
        
        recommendations_data = []
        for rec in recommendations:
            rec_data = rec.to_dict()
            rec_data['manager_name'] = f"{rec.manager.first_name} {rec.manager.last_name}" if rec.manager else 'Менеджер'
            recommendations_data.append(rec_data)
        
        # Get sent searches from managers as recommendations  
        sent_searches = SentSearch.query.filter_by(client_id=current_user.id).order_by(SentSearch.sent_at.desc()).all()
        
        # Convert sent searches to recommendation format
        for search in sent_searches:
            search_rec = {
                'id': f'search_{search.id}',
                'title': f'Подбор недвижимости: {search.name}',
                'description': search.description or 'Персональный подбор от вашего менеджера',
                'recommendation_type': 'search',
                'item_id': str(search.id),
                'item_name': search.name,
                'manager_notes': f'Ваш менеджер {search.manager.name} подготовил персональный подбор недвижимости',
                'priority_level': 'high',
                'status': search.status,
                'viewed_at': search.viewed_at.isoformat() if search.viewed_at else None,
                'created_at': search.sent_at.isoformat() if search.sent_at else None,
                'sent_at': search.sent_at.isoformat() if search.sent_at else None,
                'manager_name': search.manager.name,
                'search_filters': search.additional_filters,
                'search_id': search.id
            }
            recommendations_data.append(search_rec)
        
        # Sort by creation date 
        recommendations_data.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        
        return jsonify({
            'success': True, 
            'recommendations': recommendations_data
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@comparison_bp.route('/api/saved-searches/<int:search_id>')
@login_required
def get_saved_search_details(search_id):
    """Get saved search details for applying filters"""
    from models import SavedSearch
    
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'error': 'User not authenticated'}), 401
        
        # Get the saved search
        saved_search = SavedSearch.query.filter_by(id=search_id, user_id=user_id).first()
        if not saved_search:
            return jsonify({'success': False, 'error': 'Поиск не найден'}), 404
        
        return jsonify({
            'success': True,
            'search': {
                'id': saved_search.id,
                'name': saved_search.name,
                'description': saved_search.description,
                'additional_filters': saved_search.additional_filters,
                'created_at': saved_search.created_at.isoformat() if saved_search.created_at else None
            }
        })
        
    except Exception as e:
        print(f"Error getting saved search details: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400

@comparison_bp.route('/api/sent-searches')
@login_required
def get_sent_searches():
    """Get sent searches from managers as recommendations"""
    from models import SentSearch
    
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'error': 'User not authenticated'}), 401
        
        # Get sent searches
        sent_searches = SentSearch.query.filter_by(client_id=user_id).order_by(SentSearch.sent_at.desc()).all()
        
        # Format as recommendation-like objects
        search_list = []
        
        for search in sent_searches:
            search_list.append({
                'id': search.id,
                'name': search.name or 'Поиск от менеджера',
                'title': search.name or 'Поиск от менеджера',
                'description': search.description,
                'status': search.status or 'sent',
                'sent_at': search.sent_at.isoformat() if search.sent_at else None,
                'created_at': search.sent_at.isoformat() if search.sent_at else None,
                'search_filters': search.additional_filters,
                'manager_id': search.manager_id,
                'recommendation_type': 'search'
            })
        
        return jsonify({
            'success': True,
            'sent_searches': search_list
        })
        
    except Exception as e:
        print(f"Error getting sent searches: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400

@comparison_bp.route('/api/manager/sent-search/<int:search_id>')
@login_required
def get_sent_search_detail(search_id):
    """Get details of a specific sent search from manager"""
    from models import SentSearch
    import json
    
    try:
        # Get the specific sent search for this client using current_user from Flask-Login
        sent_search = SentSearch.query.filter_by(id=search_id, client_id=current_user.id).first()
        
        if not sent_search:
            return jsonify({'success': False, 'error': 'Поиск не найден'}), 404
        
        # Parse additional_filters if it's a JSON string
        filters = sent_search.additional_filters
        if isinstance(filters, str):
            try:
                filters = json.loads(filters)
            except json.JSONDecodeError:
                filters = {}
        elif filters is None:
            filters = {}
        
        return jsonify({
            'success': True,
            'search': {
                'id': sent_search.id,
                'name': sent_search.name or 'Поиск от менеджера',
                'description': sent_search.description,
                'additional_filters': filters,
                'status': sent_search.status or 'sent',
                'sent_at': sent_search.sent_at.isoformat() if sent_search.sent_at else None,
                'manager_id': sent_search.manager_id
            }
        })
        
    except Exception as e:
        print(f"Error getting sent search detail: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400

@comparison_bp.route('/api/recommendations/<rec_id>/viewed', methods=['POST'])
@login_required  
def api_mark_recommendation_viewed(rec_id):
    """Mark recommendation as viewed"""
    from models import Recommendation, SentSearch
    from datetime import datetime
    
    try:
        # Handle search recommendations
        if str(rec_id).startswith('search_'):
            search_id = int(rec_id.replace('search_', ''))
            sent_search = SentSearch.query.filter_by(
                id=search_id, 
                client_id=current_user.id
            ).first()
            
            if not sent_search:
                return jsonify({'success': False, 'error': 'Поиск не найден'}), 404
                
            if sent_search.status == 'sent':
                sent_search.status = 'viewed'
                sent_search.viewed_at = datetime.utcnow()
                db.session.commit()
            
            return jsonify({'success': True})
        
        # Handle traditional recommendations
        recommendation = Recommendation.query.filter_by(
            id=int(rec_id), 
            client_id=current_user.id
        ).first()
        
        if not recommendation:
            return jsonify({'success': False, 'error': 'Рекомендация не найдена'}), 404
            
        if recommendation.status == 'sent':
            recommendation.status = 'viewed'
            recommendation.viewed_at = datetime.utcnow()
            db.session.commit()
        
        return jsonify({'success': True})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400

@comparison_bp.route('/api/recommendations/<int:rec_id>/dismiss', methods=['POST'])
@login_required
def api_dismiss_recommendation(rec_id):
    """Dismiss/hide recommendation"""
    from models import Recommendation
    from datetime import datetime
    
    try:
        recommendation = Recommendation.query.filter_by(
            id=rec_id, 
            client_id=current_user.id
        ).first()
        
        if not recommendation:
            return jsonify({'success': False, 'error': 'Рекомендация не найдена'}), 404
            
        # Mark as dismissed
        recommendation.status = 'dismissed'
        recommendation.viewed_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({'success': True})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400

@comparison_bp.route('/api/recommendations/<rec_id>/apply', methods=['POST'])
@login_required  
def api_apply_search_recommendation(rec_id):
    """Apply search recommendation - redirect to properties with filters"""
    from models import SentSearch
    from datetime import datetime
    import json
    
    try:
        # Handle search recommendations only
        if not str(rec_id).startswith('search_'):
            return jsonify({'success': False, 'error': 'Только поиски можно применить'}), 400
            
        search_id = int(rec_id.replace('search_', ''))
        sent_search = SentSearch.query.filter_by(
            id=search_id, 
            client_id=current_user.id
        ).first()
        
        if not sent_search:
            return jsonify({'success': False, 'error': 'Поиск не найден'}), 404
        
        # Update search status
        sent_search.applied_at = datetime.utcnow()
        if sent_search.status == 'sent':
            sent_search.status = 'applied'
        db.session.commit()
        
        # Parse filters from the search and normalize keys
        raw_filters = {}
        if sent_search.additional_filters:
            try:
                raw_filters = json.loads(sent_search.additional_filters)
            except json.JSONDecodeError:
                pass

        filters = {}
        rooms_val = raw_filters.get('rooms')
        if rooms_val:
            filters['rooms'] = rooms_val if isinstance(rooms_val, list) else [str(rooms_val)]
        elif hasattr(sent_search, 'property_type') and sent_search.property_type:
            filters['rooms'] = [str(r) for r in sent_search.property_type.split(',') if r.strip()]
        filters['priceFrom'] = raw_filters.get('priceFrom') or raw_filters.get('price_min') or (getattr(sent_search, 'price_min', '') or '')
        filters['priceTo'] = raw_filters.get('priceTo') or raw_filters.get('price_max') or (getattr(sent_search, 'price_max', '') or '')
        filters['areaFrom'] = raw_filters.get('areaFrom') or raw_filters.get('area_min') or (getattr(sent_search, 'size_min', '') or '')
        filters['areaTo'] = raw_filters.get('areaTo') or raw_filters.get('area_max') or (getattr(sent_search, 'size_max', '') or '')
        filters['district'] = raw_filters.get('district') or (getattr(sent_search, 'location', '') or '')
        filters['complex_name'] = raw_filters.get('complex_name') or raw_filters.get('complex') or (getattr(sent_search, 'complex_name', '') or '')
        filters['districts'] = raw_filters.get('districts', [])
        filters['developers'] = raw_filters.get('developers', [])

        return jsonify({
            'success': True, 
            'filters': filters
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400

@comparison_bp.route('/api/user/recommendation-categories', methods=['GET'])
@login_required
def api_user_get_categories():
    """Get all categories that have recommendations for current user"""
    from models import RecommendationCategory
    
    try:
        categories = RecommendationCategory.query.filter_by(
            client_id=current_user.id
        ).filter(RecommendationCategory.recommendations_count > 0).all()
        
        categories_data = []
        for category in categories:
            categories_data.append({
                'id': category.id,
                'name': category.name,
                'description': category.description,
                'color': category.color,
                'recommendations_count': category.recommendations_count
            })
        
        return jsonify({
            'success': True,
            'categories': categories_data
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

# User Comparison Count API Endpoints
@comparison_bp.route('/api/user/comparison/properties/count')
def api_user_comparison_properties_count():
    """Get count of properties in comparison for current user"""
    from models import ComparisonProperty, UserComparison
    from services.guest_session import get_guest_comparison_properties
    
    try:
        if not current_user.is_authenticated:
            guest_props = get_guest_comparison_properties()
            return jsonify({'success': True, 'count': len(guest_props)})
        
        user_comparison = UserComparison.query.filter_by(
            user_id=current_user.id,
            is_active=True
        ).first()
        
        if not user_comparison:
            return jsonify({'success': True, 'count': 0})
        
        count = ComparisonProperty.query.filter_by(
            user_comparison_id=user_comparison.id
        ).count()
        
        return jsonify({'success': True, 'count': count})
        
    except Exception as e:
        print(f"Error getting user comparison properties count: {e}")
        return jsonify({'success': False, 'error': str(e), 'count': 0}), 500

@comparison_bp.route('/api/user/comparison/complexes/count')
def api_user_comparison_complexes_count():
    """Get count of complexes in comparison for current user"""
    from models import ComparisonComplex, UserComparison
    from services.guest_session import get_guest_comparison_complexes
    
    try:
        if not current_user.is_authenticated:
            guest_complexes = get_guest_comparison_complexes()
            return jsonify({'success': True, 'count': len(guest_complexes)})
        
        user_comparison = UserComparison.query.filter_by(
            user_id=current_user.id,
            is_active=True
        ).first()
        
        if not user_comparison:
            return jsonify({'success': True, 'count': 0})
        
        count = ComparisonComplex.query.filter_by(
            user_comparison_id=user_comparison.id
        ).count()
        
        return jsonify({'success': True, 'count': count})
        
    except Exception as e:
        print(f"Error getting user comparison complexes count: {e}")
        return jsonify({'success': False, 'error': str(e), 'count': 0}), 500

# ========================================
# USER COMPARISON ENDPOINTS
# ========================================

@comparison_bp.route('/api/user/comparison/property/add', methods=['POST'])
def api_user_comparison_property_add():
    """Add property to user's comparison - works for both authenticated and guest users"""
    from models import UserComparison, ComparisonProperty
    from services.guest_session import add_guest_comparison_property
    
    try:
        data = request.get_json()
        property_id = str(data.get('property_id'))
        
        if not current_user.is_authenticated:
            success, message, count = add_guest_comparison_property(property_id)
            return jsonify({'success': success, 'message': message, 'count': count})  # ✅ Конвертируем в строку
        
        if not property_id:
            return jsonify({'success': False, 'message': 'Property ID is required'}), 400
        
        # Find or create active user comparison
        user_comparison = UserComparison.query.filter_by(
            user_id=current_user.id,
            is_active=True
        ).first()
        
        if not user_comparison:
            user_comparison = UserComparison(
                user_id=current_user.id,
                name='Мое сравнение',
                is_active=True
            )
            db.session.add(user_comparison)
            db.session.flush()
        
        # Check if property already in comparison
        existing = ComparisonProperty.query.filter_by(
            user_comparison_id=user_comparison.id,
            property_id=property_id
        ).first()
        
        if existing:
            count = ComparisonProperty.query.filter_by(
                user_comparison_id=user_comparison.id
            ).count()
            return jsonify({
                'success': True,
                'message': 'Объект уже в сравнении',
                'count': count
            })
        
        # Check maximum limit
        current_count = ComparisonProperty.query.filter_by(
            user_comparison_id=user_comparison.id
        ).count()
        
        if current_count >= 4:
            return jsonify({
                'success': False,
                'message': 'Максимум 4 объекта в сравнении',
                'count': current_count
            }), 400
        
        # Add property to comparison
        comparison_property = ComparisonProperty(
            user_comparison_id=user_comparison.id,
            property_id=property_id,
            property_name=data.get('property_name'),
            property_price=data.get('property_price'),
            complex_name=data.get('complex_name'),
            cashback=data.get('cashback', 0),
            area=data.get('area'),
            rooms=data.get('rooms'),
            order_index=current_count
        )
        db.session.add(comparison_property)
        db.session.commit()
        
        new_count = current_count + 1
        return jsonify({
            'success': True,
            'message': 'Объект добавлен в сравнение',
            'count': new_count
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error adding property to user comparison: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@comparison_bp.route('/api/user/comparison/property/remove', methods=['POST'])
@csrf.exempt
def api_user_comparison_property_remove():
    """Remove property from user's comparison - works for both authenticated and guest users"""
    from models import UserComparison, ComparisonProperty
    from services.guest_session import remove_guest_comparison_property
    
    try:
        data = request.get_json()
        property_id = str(data.get('property_id'))
        
        if not current_user.is_authenticated:
            success, message, count = remove_guest_comparison_property(property_id)
            return jsonify({'success': success, 'message': message, 'count': count})  # ✅ Конвертируем в строку
        
        if not property_id:
            return jsonify({'success': False, 'message': 'Property ID is required'}), 400
        
        # Find active user comparison
        user_comparison = UserComparison.query.filter_by(
            user_id=current_user.id,
            is_active=True
        ).first()
        
        if not user_comparison:
            return jsonify({
                'success': True,
                'message': 'Сравнение пусто',
                'count': 0
            })
        
        # Find and delete property
        comparison_property = ComparisonProperty.query.filter_by(
            user_comparison_id=user_comparison.id,
            property_id=property_id
        ).first()
        
        if comparison_property:
            db.session.delete(comparison_property)
            db.session.commit()
        
        # Get updated count
        count = ComparisonProperty.query.filter_by(
            user_comparison_id=user_comparison.id
        ).count()
        
        return jsonify({
            'success': True,
            'message': 'Объект удален из сравнения',
            'count': count
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error removing property from user comparison: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@comparison_bp.route('/api/user/comparison/complex/add', methods=['POST'])
def api_user_comparison_complex_add():
    """Add residential complex to user's comparison - works for both authenticated and guest users"""
    from models import UserComparison, ComparisonComplex
    from services.guest_session import add_guest_comparison_complex
    
    try:
        data = request.get_json()
        complex_id = data.get('complex_id')
        
        if not current_user.is_authenticated:
            success, message, count = add_guest_comparison_complex(complex_id)
            return jsonify({'success': success, 'message': message, 'count': count})
        
        print(f'🔵 DEBUG USER: Добавление ЖК - complex_id={complex_id}, data={data}')
        
        if not complex_id:
            return jsonify({'success': False, 'message': 'Complex ID is required'}), 400
        
        # Find or create active user comparison
        user_comparison = UserComparison.query.filter_by(
            user_id=current_user.id,
            is_active=True
        ).first()
        
        if not user_comparison:
            user_comparison = UserComparison(
                user_id=current_user.id,
                name='Мое сравнение',
                is_active=True
            )
            db.session.add(user_comparison)
            db.session.flush()
            print(f'✅ DEBUG USER: Создан новый UserComparison id={user_comparison.id}')
        else:
            print(f'✅ DEBUG USER: Найден UserComparison id={user_comparison.id}')
        
        # Check if complex already in comparison
        existing = ComparisonComplex.query.filter_by(
            user_comparison_id=user_comparison.id,
            complex_id=complex_id
        ).first()
        
        if existing:
            count = ComparisonComplex.query.filter_by(
                user_comparison_id=user_comparison.id
            ).count()
            print(f'⚠️ DEBUG USER: ЖК уже в сравнении, count={count}')
            return jsonify({
                'success': True,
                'message': 'ЖК уже в сравнении',
                'count': count
            })
        
        # Check maximum limit
        current_count = ComparisonComplex.query.filter_by(
            user_comparison_id=user_comparison.id
        ).count()
        
        if current_count >= 4:
            print(f'⚠️ DEBUG USER: Превышен лимит, count={current_count}')
            return jsonify({
                'success': False,
                'message': 'Максимум 4 ЖК в сравнении',
                'count': current_count
            }), 400
        
        # Add complex to comparison
        comparison_complex = ComparisonComplex(
            user_comparison_id=user_comparison.id,
            complex_id=complex_id,
            complex_name=data.get('complex_name'),
            developer_name=data.get('developer_name'),
            min_price=data.get('min_price'),
            max_price=data.get('max_price'),
            district=data.get('district'),
            photo=data.get('photo'),
            buildings_count=data.get('buildings_count'),
            apartments_count=data.get('apartments_count'),
            completion_date=data.get('completion_date'),
            status=data.get('status'),
            complex_class=data.get('complex_class'),
            cashback_rate=data.get('cashback_rate', 5.0),
            order_index=current_count
        )
        db.session.add(comparison_complex)
        db.session.commit()
        
        print(f'✅ DEBUG USER: ЖК добавлен в БД - id={comparison_complex.id}, complex_id={comparison_complex.complex_id}')
        
        new_count = current_count + 1
        return jsonify({
            'success': True,
            'message': 'ЖК добавлен в сравнение',
            'count': new_count
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error adding complex to user comparison: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500
@comparison_bp.route('/api/user/comparison/complex/remove', methods=['POST'])
@csrf.exempt
def api_user_comparison_complex_remove():
    """Remove residential complex from user's comparison - works for both authenticated and guest users"""
    from models import UserComparison, ComparisonComplex
    from services.guest_session import remove_guest_comparison_complex
    
    try:
        data = request.get_json()
        complex_id = data.get('complex_id')
        
        if not current_user.is_authenticated:
            success, message, count = remove_guest_comparison_complex(complex_id)
            return jsonify({'success': success, 'message': message, 'count': count})
        
        if not complex_id:
            return jsonify({'success': False, 'message': 'Complex ID is required'}), 400
        
        # Find active user comparison
        user_comparison = UserComparison.query.filter_by(
            user_id=current_user.id,
            is_active=True
        ).first()
        
        if not user_comparison:
            return jsonify({
                'success': True,
                'message': 'Сравнение пусто',
                'count': 0
            })
        
        # Find and delete complex
        comparison_complex = ComparisonComplex.query.filter_by(
            user_comparison_id=user_comparison.id,
            complex_id=complex_id
        ).first()
        
        if comparison_complex:
            db.session.delete(comparison_complex)
            db.session.commit()
        
        # Get updated count
        count = ComparisonComplex.query.filter_by(
            user_comparison_id=user_comparison.id
        ).count()
        
        return jsonify({
            'success': True,
            'message': 'ЖК удален из сравнения',
            'count': count
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error removing complex from user comparison: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@comparison_bp.route('/api/user/comparison/load')
def api_user_comparison_load():
    """Load all comparisons for current user from database with is_sold status check"""
    from models import UserComparison, ComparisonProperty, ComparisonComplex, Property
    from services.guest_session import get_guest_comparison_properties, get_guest_comparison_complexes
    
    try:
        if not current_user.is_authenticated:
            guest_props = get_guest_comparison_properties()
            guest_complexes = get_guest_comparison_complexes()
            properties_data = [{'property_id': pid} for pid in guest_props]
            return jsonify({
                'success': True,
                'properties': properties_data,
                'complexes': guest_complexes,
                'properties_count': len(guest_props),
                'complexes_count': len(guest_complexes)
            })
        
        # Find active user comparison
        user_comparison = UserComparison.query.filter_by(
            user_id=current_user.id,
            is_active=True
        ).first()
        
        if not user_comparison:
            return jsonify({
                'success': True,
                'properties': [],
                'complexes': [],
                'properties_count': 0,
                'complexes_count': 0
            })
        
        # Get all comparison properties
        comparison_properties = ComparisonProperty.query.filter_by(
            user_comparison_id=user_comparison.id
        ).all()
        
        # Batch-загрузка Property объектов для проверки актуальности (избегаем N+1 запросов)
        property_ids = []
        for cp in comparison_properties:
            if cp.property_id:
                try:
                    # ComparisonProperty.property_id может быть как inner_id (string), так и database ID (int)
                    property_ids.append(int(cp.property_id))
                except (ValueError, TypeError):
                    # Если не удалось преобразовать в int, пропускаем
                    pass
        
        # Загружаем все Property объекты одним запросом
        live_properties = {}
        if property_ids:
            properties_query = Property.query.filter(Property.id.in_(property_ids)).all()
            live_properties = {p.id: p for p in properties_query}
        
        # Обогащаем данные флагом is_sold и status_label
        properties_data = []
        for cp in comparison_properties:
            cp_dict = cp.to_dict()
            
            # Получаем актуальный Property объект
            try:
                prop_id = int(cp.property_id) if cp.property_id else None
            except (ValueError, TypeError):
                prop_id = None
            
            live_prop = live_properties.get(prop_id) if prop_id else None
            
            # Добавляем флаги актуальности
            cp_dict['is_sold'] = not live_prop.is_active if live_prop else True
            cp_dict['status_label'] = 'НЕ В ПРОДАЖЕ' if cp_dict['is_sold'] else ''
            
            # Опционально: обновляем денормализованные данные если объект актуален
            if live_prop and live_prop.is_active:
                cp_dict['current_price'] = live_prop.price
                cp_dict['current_area'] = live_prop.area
            
            properties_data.append(cp_dict)
        
        # Get all complex IDs
        complexes = ComparisonComplex.query.filter_by(
            user_comparison_id=user_comparison.id
        ).all()
        complex_ids = [comp.complex_id for comp in complexes]
        
        return jsonify({
            'success': True,
            'properties': properties_data,
            'complexes': complex_ids,
            'properties_count': len(properties_data),
            'complexes_count': len(complex_ids)
        })
        
    except Exception as e:
        print(f"Error loading user comparison: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@comparison_bp.route('/api/comparison/clear', methods=['POST'])
def api_comparison_clear():
    """Clear all comparisons for current user"""
    from models import UserComparison, ComparisonProperty, ComparisonComplex
    from services.guest_session import clear_guest_comparison
    
    try:
        if not current_user.is_authenticated:
            clear_guest_comparison()
            return jsonify({
                'success': True,
                'message': 'Сравнения очищены'
            })
        
        # Find active user comparison
        user_comparison = UserComparison.query.filter_by(
            user_id=current_user.id,
            is_active=True
        ).first()
        
        if user_comparison:
            # Delete all properties
            ComparisonProperty.query.filter_by(
                user_comparison_id=user_comparison.id
            ).delete()
            
            # Delete all complexes
            ComparisonComplex.query.filter_by(
                user_comparison_id=user_comparison.id
            ).delete()
            
            db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Все сравнения очищены'
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error clearing comparisons: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ========================================
# PUBLIC COMPARISON DELETE ENDPOINTS (No Auth Required)
# ========================================

@comparison_bp.route('/api/comparison/remove-property', methods=['POST', 'DELETE'])
@csrf.exempt
def api_comparison_remove_property():
    """Remove property from comparison (works for both authenticated and unauthenticated users)"""
    from models import UserComparison, ManagerComparison, ComparisonProperty
    
    try:
        # Get property_id from request
        if request.method == 'DELETE':
            data = request.get_json() or {}
        else:
            data = request.get_json() or {}
        
        property_id = data.get('property_id')
        
        if not property_id:
            return jsonify({'success': False, 'error': 'Property ID is required'}), 400
        
        # Try to remove from database if user is authenticated
        deleted = False
        
        # Check if regular user is authenticated
        if current_user.is_authenticated:
            user_comparison = UserComparison.query.filter_by(
                user_id=current_user.id,
                is_active=True
            ).first()
            
            if user_comparison:
                comparison_property = ComparisonProperty.query.filter_by(
                    user_comparison_id=user_comparison.id,
                    property_id=property_id
                ).first()
                
                if comparison_property:
                    db.session.delete(comparison_property)
                    db.session.commit()
                    deleted = True
        
        # Check if manager is authenticated
        if isinstance(current_user._get_current_object(), Manager) and not deleted:
            current_manager = current_user
            manager_comparison = ManagerComparison.query.filter_by(
                manager_id=current_manager.id,
                is_active=True
            ).first()
            
            if manager_comparison:
                comparison_property = ComparisonProperty.query.filter_by(
                    manager_comparison_id=manager_comparison.id,
                    property_id=property_id
                ).first()
                
                if comparison_property:
                    db.session.delete(comparison_property)
                    db.session.commit()
                    deleted = True
        
        # Return success even if not in database (frontend will handle localStorage)
        return jsonify({
            'success': True,
            'message': 'Квартира удалена из сравнения',
            'deleted_from_db': deleted
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error removing property from comparison: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@comparison_bp.route('/api/comparison/remove-complex', methods=['POST', 'DELETE'])
@csrf.exempt
def api_comparison_remove_complex():
    """Remove complex from comparison (works for both authenticated and unauthenticated users)"""
    from models import UserComparison, ManagerComparison, ComparisonComplex
    
    try:
        # Get complex_id from request
        if request.method == 'DELETE':
            data = request.get_json() or {}
        else:
            data = request.get_json() or {}
        
        complex_id = data.get('complex_id')
        
        if not complex_id:
            return jsonify({'success': False, 'error': 'Complex ID is required'}), 400
        
        # Try to remove from database if user is authenticated
        deleted = False
        
        # Check if regular user is authenticated
        if current_user.is_authenticated:
            user_comparison = UserComparison.query.filter_by(
                user_id=current_user.id,
                is_active=True
            ).first()
            
            if user_comparison:
                comparison_complex = ComparisonComplex.query.filter_by(
                    user_comparison_id=user_comparison.id,
                    complex_id=complex_id
                ).first()
                
                if comparison_complex:
                    db.session.delete(comparison_complex)
                    db.session.commit()
                    deleted = True
        
        # Check if manager is authenticated
        if isinstance(current_user._get_current_object(), Manager) and not deleted:
            current_manager = current_user
            manager_comparison = ManagerComparison.query.filter_by(
                manager_id=current_manager.id,
                is_active=True
            ).first()
            
            if manager_comparison:
                comparison_complex = ComparisonComplex.query.filter_by(
                    manager_comparison_id=manager_comparison.id,
                    complex_id=complex_id
                ).first()
                
                if comparison_complex:
                    db.session.delete(comparison_complex)
                    db.session.commit()
                    deleted = True
        
        # Return success even if not in database (frontend will handle localStorage)
        return jsonify({
            'success': True,
            'message': 'ЖК удален из сравнения',
            'deleted_from_db': deleted
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error removing complex from comparison: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ========================================
# MANAGER COMPARISON ENDPOINTS
# ========================================

@comparison_bp.route('/api/manager/comparison/property/add', methods=['POST'])
@manager_required
def api_manager_comparison_property_add():
    """Add property to manager's comparison"""
    from models import ManagerComparison, ComparisonProperty
    
    try:
        data = request.get_json()
        property_id = data.get('property_id')
        print(f'🔍 DEBUG: property/add called with data: {data}')
        print(f'🔍 DEBUG: property_id type: {type(property_id)}, value: {property_id}')
        
        # ✅ ИСПРАВЛЕНО: Конвертируем в строку, т.к. в БД property_id - VARCHAR
        property_id = str(property_id)
        print(f'✅ DEBUG: Converted property_id to string: {property_id}')
        
        if not property_id:
            return jsonify({'success': False, 'message': 'Property ID is required'}), 400
        
        current_manager = current_user
        
        # Find or create active manager comparison
        manager_comparison = ManagerComparison.query.filter_by(
            manager_id=current_manager.id,
            is_active=True
        ).first()
        
        if not manager_comparison:
            manager_comparison = ManagerComparison(
                manager_id=current_manager.id,
                name='Сравнение для клиента',
                is_active=True
            )
            db.session.add(manager_comparison)
            db.session.flush()
        
        # Check if property already in comparison
        existing = ComparisonProperty.query.filter_by(
            manager_comparison_id=manager_comparison.id,
            property_id=property_id
        ).first()
        
        if existing:
            count = ComparisonProperty.query.filter_by(
                manager_comparison_id=manager_comparison.id
            ).count()
            return jsonify({
                'success': True,
                'message': 'Объект уже в сравнении',
                'count': count
            })
        
        # Check maximum limit
        current_count = ComparisonProperty.query.filter_by(
            manager_comparison_id=manager_comparison.id
        ).count()
        
        if current_count >= 4:
            return jsonify({
                'success': False,
                'message': 'Максимум 4 объекта в сравнении',
                'count': current_count
            }), 400
        
        # ✅ Get property inner_id for consistency with favorites system
        from models import Property
        property = Property.query.filter_by(id=property_id).first()
        
        if not property:
            return jsonify({
                'success': False,
                'message': 'Объект не найден'
            }), 404
        
        # Add property to comparison using Property.id
        comparison_property = ComparisonProperty(
            manager_comparison_id=manager_comparison.id,
            property_id=str(property.id),  # ✅ Use Property.id для консистентности с фронтендом
            property_name=data.get('property_name'),
            property_price=data.get('property_price'),
            complex_name=data.get('complex_name'),
            cashback=data.get('cashback', 0),
            area=data.get('area'),
            rooms=data.get('rooms'),
            order_index=current_count
        )
        db.session.add(comparison_property)
        db.session.commit()
        
        print(f"✅ Added property {property_id} (inner_id: {property.inner_id}) to comparison")
        
        new_count = current_count + 1
        return jsonify({
            'success': True,
            'message': 'Объект добавлен в сравнение',
            'count': new_count
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error adding property to manager comparison: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
@comparison_bp.route('/api/manager/comparison/property/remove', methods=['POST'])
@manager_required
def api_manager_comparison_property_remove():
    """Remove property from manager's comparison"""
    from models import ManagerComparison, ComparisonProperty, Property
    
    try:
        data = request.get_json()
        property_id_or_inner_id = str(data.get('property_id'))  # ✅ Может быть inner_id или id
        
        if not property_id_or_inner_id:
            return jsonify({'success': False, 'message': 'Property ID is required'}), 400
        
        current_manager = current_user
        
        # Find active manager comparison
        manager_comparison = ManagerComparison.query.filter_by(
            manager_id=current_manager.id,
            is_active=True
        ).first()
        
        if not manager_comparison:
            return jsonify({
                'success': True,
                'message': 'Сравнение пусто',
                'count': 0
            })
        
        # ВАЖНО: Конвертируем inner_id в Property.id если нужно
        # Сначала пробуем найти напрямую по property_id
        print(f'🔍 DEBUG: Received property_id={property_id_or_inner_id}')
        comparison_property = ComparisonProperty.query.filter_by(
            manager_comparison_id=manager_comparison.id,
            property_id=property_id_or_inner_id
        ).first()
        
        # Если не нашли, значит пришел inner_id - конвертируем в id
        if not comparison_property:
            print(f'🔍 DEBUG: Not found by direct ID, trying to convert inner_id to Property.id')
            property_obj = Property.query.filter_by(inner_id=property_id_or_inner_id).first()
            if property_obj:
                actual_property_id = str(property_obj.id)
                print(f'✅ DEBUG: Converted inner_id {property_id_or_inner_id} to Property.id {actual_property_id}')
                comparison_property = ComparisonProperty.query.filter_by(
                    manager_comparison_id=manager_comparison.id,
                    property_id=actual_property_id
                ).first()
            else:
                print(f'❌ DEBUG: Property not found with inner_id={property_id_or_inner_id}')
        
        print(f'🔍 DEBUG: Найдена запись? {comparison_property is not None}')
        if comparison_property:
            print(f'🔍 DEBUG: Удаляем запись id={comparison_property.id}, property_id={comparison_property.property_id}')
            db.session.delete(comparison_property)
            db.session.commit()
            print(f'✅ DEBUG: Запись удалена и commit выполнен')
        else:
            print(f'❌ DEBUG: Запись НЕ найдена для удаления!')
        
        # Get updated count
        count = ComparisonProperty.query.filter_by(
            manager_comparison_id=manager_comparison.id
        ).count()
        
        return jsonify({
            'success': True,
            'message': 'Объект удален из сравнения',
            'count': count
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error removing property from manager comparison: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@comparison_bp.route('/api/manager/comparison/clear', methods=['DELETE', 'POST'])
@csrf.exempt
@manager_required
def api_manager_comparison_clear():
    """Clear all items from manager's comparison"""
    from models import ManagerComparison, ComparisonProperty, ComparisonComplex
    
    try:
        current_manager = current_user
        print(f"🗑️ DEBUG: /api/manager/comparison/clear called by manager {current_manager.id}")
        
        # Find ALL active manager comparisons (not just first one!)
        manager_comparisons = ManagerComparison.query.filter_by(
            manager_id=current_manager.id,
            is_active=True
        ).all()
        
        if not manager_comparisons:
            print(f"ℹ️ DEBUG: No active comparison found for manager {current_manager.id}")
            return jsonify({
                'success': True,
                'message': 'Сравнение уже пусто',
                'deleted_properties': 0,
                'deleted_complexes': 0
            })
        
        print(f"🔍 DEBUG: Found {len(manager_comparisons)} active comparison(s), deleting items...")
        
        # Delete all properties and complexes from ALL active comparisons
        deleted_properties = 0
        deleted_complexes = 0
        
        for manager_comparison in manager_comparisons:
            deleted_properties += ComparisonProperty.query.filter_by(
                manager_comparison_id=manager_comparison.id
            ).delete()
            
            deleted_complexes += ComparisonComplex.query.filter_by(
                manager_comparison_id=manager_comparison.id
            ).delete()
        
        db.session.commit()
        
        print(f"✅ DEBUG: Cleared {deleted_properties} properties and {deleted_complexes} complexes")
        
        return jsonify({
            'success': True,
            'message': f'Сравнение очищено: {deleted_properties} квартир и {deleted_complexes} ЖК',
            'deleted_properties': deleted_properties,
            'deleted_complexes': deleted_complexes
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error clearing manager comparison: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@comparison_bp.route('/api/manager/comparison/complex/add', methods=['POST'])
@manager_required
def api_manager_comparison_complex_add():
    """Add residential complex to manager's comparison"""
    from models import ManagerComparison, ComparisonComplex
    
    try:
        data = request.get_json()
        complex_id = data.get('complex_id')
        print(f'🔍 DEBUG: complex/add called with data: {data}')
        print(f'🔍 DEBUG: complex_id type: {type(complex_id)}, value: {complex_id}')
        
        # Convert string ID to integer if needed
        try:
            complex_id = int(complex_id)
            print(f'✅ DEBUG: Converted complex_id to integer: {complex_id}')
        except (ValueError, TypeError) as e:
            print(f'❌ DEBUG: Failed to convert complex_id to integer: {e}')
            return jsonify({'success': False, 'message': 'Invalid complex ID format'}), 400
        
        if not complex_id:
            return jsonify({'success': False, 'message': 'Complex ID is required'}), 400
        
        current_manager = current_user
        
        # Find or create active manager comparison
        manager_comparison = ManagerComparison.query.filter_by(
            manager_id=current_manager.id,
            is_active=True
        ).first()
        
        if not manager_comparison:
            manager_comparison = ManagerComparison(
                manager_id=current_manager.id,
                name='Сравнение для клиента',
                is_active=True
            )
            db.session.add(manager_comparison)
            db.session.flush()
        
        # Check if complex already in comparison
        existing = ComparisonComplex.query.filter_by(
            manager_comparison_id=manager_comparison.id,
            complex_id=complex_id
        ).first()
        
        if existing:
            count = ComparisonComplex.query.filter_by(
                manager_comparison_id=manager_comparison.id
            ).count()
            return jsonify({
                'success': True,
                'message': 'ЖК уже в сравнении',
                'count': count
            })
        
        # Check maximum limit
        current_count = ComparisonComplex.query.filter_by(
            manager_comparison_id=manager_comparison.id
        ).count()
        
        if current_count >= 4:
            return jsonify({
                'success': False,
                'message': 'Максимум 4 ЖК в сравнении',
                'count': current_count
            }), 400
        
        # Add complex to comparison
        comparison_complex = ComparisonComplex(
            manager_comparison_id=manager_comparison.id,
            complex_id=complex_id,
            complex_name=data.get('complex_name'),
            developer_name=data.get('developer_name'),
            min_price=data.get('min_price'),
            max_price=data.get('max_price'),
            district=data.get('district'),
            photo=data.get('photo'),
            buildings_count=data.get('buildings_count'),
            apartments_count=data.get('apartments_count'),
            completion_date=data.get('completion_date'),
            status=data.get('status'),
            complex_class=data.get('complex_class'),
            cashback_rate=data.get('cashback_rate', 5.0),
            order_index=current_count
        )
        db.session.add(comparison_complex)
        db.session.commit()
        
        new_count = current_count + 1
        return jsonify({
            'success': True,
            'message': 'ЖК добавлен в сравнение',
            'count': new_count
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error adding complex to manager comparison: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@comparison_bp.route('/api/manager/comparison/complex/remove', methods=['POST'])
@manager_required
def api_manager_comparison_complex_remove():
    """Remove residential complex from manager's comparison"""
    from models import ManagerComparison, ComparisonComplex
    
    try:
        data = request.get_json()
        complex_id = str(data.get('complex_id'))  # ✅ Конвертируем в строку
        
        if not complex_id:
            return jsonify({'success': False, 'message': 'Complex ID is required'}), 400
        
        current_manager = current_user
        
        # Find active manager comparison
        manager_comparison = ManagerComparison.query.filter_by(
            manager_id=current_manager.id,
            is_active=True
        ).first()
        
        if not manager_comparison:
            return jsonify({
                'success': True,
                'message': 'Сравнение пусто',
                'count': 0
            })
        
        # Find and delete complex
        print(f'🔍 DEBUG: Поиск ЖК для удаления - manager_comparison_id={manager_comparison.id}, complex_id={complex_id} (type={type(complex_id)})')
        comparison_complex = ComparisonComplex.query.filter_by(
            manager_comparison_id=manager_comparison.id,
            complex_id=complex_id
        ).first()
        
        print(f'🔍 DEBUG: Найдена запись ЖК? {comparison_complex is not None}')
        if comparison_complex:
            print(f'🔍 DEBUG: Удаляем ЖК id={comparison_complex.id}, complex_id={comparison_complex.complex_id}')
            db.session.delete(comparison_complex)
            db.session.commit()
            print(f'✅ DEBUG: ЖК удален и commit выполнен')
        else:
            print(f'❌ DEBUG: Запись ЖК НЕ найдена для удаления!')
        
        # Get updated count
        count = ComparisonComplex.query.filter_by(
            manager_comparison_id=manager_comparison.id
        ).count()
        
        return jsonify({
            'success': True,
            'message': 'ЖК удален из сравнения',
            'count': count
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error removing complex from manager comparison: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@comparison_bp.route('/api/manager/comparison/load')
def api_manager_comparison_load():
    """Load all comparisons for current manager from database with is_sold status check"""
    from models import ManagerComparison, ComparisonProperty, ComparisonComplex, Manager, Property
    
    try:
        # ИСПРАВЛЕНО: правильная проверка типа менеджера
        if not current_user.is_authenticated or not isinstance(current_user._get_current_object(), Manager):
            print(f"⚠️ DEBUG: User not authenticated or not a manager - returning empty comparison")
            return jsonify({
                'success': True,
                'properties': [],
                'complexes': [],
                'properties_count': 0,
                'complexes_count': 0
            })
        
        current_manager = current_user
        print(f"🔍 DEBUG: Loading comparisons from MANAGER_COMPARISONS table for manager {current_manager.id}")
        
        # ✅ ИСПРАВЛЕНО: Find ALL active manager comparisons (not just first one!)
        manager_comparisons = ManagerComparison.query.filter_by(
            manager_id=current_manager.id,
            is_active=True
        ).all()
        
        if not manager_comparisons:
            print(f"ℹ️ DEBUG: No active comparisons found")
            return jsonify({
                'success': True,
                'properties': [],
                'complexes': [],
                'properties_count': 0,
                'complexes_count': 0
            })
        
        print(f"🔍 DEBUG: Found {len(manager_comparisons)} active comparison(s)")
        
        # ✅ Collect all comparison properties and complexes from ALL active comparisons
        all_comparison_properties = []
        all_comparison_complexes = []
        seen_complex_ids = set()
        
        for manager_comparison in manager_comparisons:
            properties = ComparisonProperty.query.filter_by(
                manager_comparison_id=manager_comparison.id
            ).all()
            all_comparison_properties.extend(properties)
            
            complexes = ComparisonComplex.query.filter_by(
                manager_comparison_id=manager_comparison.id
            ).all()
            for comp in complexes:
                if comp.complex_id not in seen_complex_ids:
                    seen_complex_ids.add(comp.complex_id)
                    all_comparison_complexes.append(comp)
        
        # Batch-загрузка Property объектов для проверки актуальности (избегаем N+1 запросов)
        property_ids = []
        for cp in all_comparison_properties:
            if cp.property_id:
                try:
                    # ComparisonProperty.property_id может быть как inner_id (string), так и database ID (int)
                    property_ids.append(int(cp.property_id))
                except (ValueError, TypeError):
                    # Если не удалось преобразовать в int, пропускаем
                    pass
        
        # Загружаем все Property объекты одним запросом
        live_properties = {}
        if property_ids:
            properties_query = Property.query.filter(Property.id.in_(property_ids)).all()
            live_properties = {p.id: p for p in properties_query}
        
        # Обогащаем данные флагом is_sold и status_label
        properties_data = []
        for cp in all_comparison_properties:
            cp_dict = cp.to_dict()
            
            # Получаем актуальный Property объект
            try:
                prop_id = int(cp.property_id) if cp.property_id else None
            except (ValueError, TypeError):
                prop_id = None
            
            live_prop = live_properties.get(prop_id) if prop_id else None
            
            # Добавляем флаги актуальности
            cp_dict['is_sold'] = not live_prop.is_active if live_prop else True
            cp_dict['status_label'] = 'НЕ В ПРОДАЖЕ' if cp_dict['is_sold'] else ''
            
            # ОБОГАЩАЕМ данными из live Property для полного отображения в сравнении
            if live_prop:
                cp_dict["property_name"] = live_prop.title or cp_dict.get("property_name", "")
                cp_dict["property_price"] = live_prop.price or cp_dict.get("property_price", 0)
                cp_dict["area"] = live_prop.area or cp_dict.get("area", 0)
                cp_dict["rooms"] = live_prop.rooms if live_prop.rooms is not None else cp_dict.get("rooms")
                # Get complex name from relationship
                rc = live_prop.residential_complex
                if rc and hasattr(rc, "name"):
                    cp_dict["complex_name"] = rc.name or cp_dict.get("complex_name", "")
                else:
                    cp_dict["complex_name"] = cp_dict.get("complex_name", "")
                cp_dict["floor"] = live_prop.floor
                cp_dict["total_floors"] = live_prop.total_floors
                if live_prop.developer and hasattr(live_prop.developer, "name"):
                    cp_dict["developer_name"] = live_prop.developer.name or "Не указан"
                else:
                    cp_dict["developer_name"] = "Не указан"
                cp_dict["district"] = live_prop.district or ""
                cp_dict["property_type"] = live_prop.property_type or "Квартира"
                cp_dict["building_type"] = live_prop.building_type or ""
                cp_dict["building_number"] = live_prop.building_number or ""
                # Класс жилья из ЖК
                if hasattr(live_prop, "residential_complex") and live_prop.residential_complex:
                    rc = live_prop.residential_complex
                    if hasattr(rc, "object_class_display_name"):
                        cp_dict["housing_class"] = rc.object_class_display_name or ""
                    else:
                        cp_dict["housing_class"] = ""
                else:
                    cp_dict["housing_class"] = ""
                cp_dict["address"] = live_prop.address or ""
                
                # Get property image from main_image or gallery_images
                prop_image = live_prop.main_image
                if not prop_image and live_prop.gallery_images:
                    try:
                        import json
                        gallery = json.loads(live_prop.gallery_images)
                        if isinstance(gallery, list) and len(gallery) > 0:
                            prop_image = gallery[0]
                    except:
                        pass
                cp_dict["property_image"] = prop_image or "/static/images/no-photo.svg"
                
                cashback_rate = 5.0
                if live_prop.price:
                    cp_dict["cashback"] = int(live_prop.price * cashback_rate / 100)
                
                # Delivery date and housing class from residential complex
                if hasattr(live_prop, 'residential_complex') and live_prop.residential_complex:
                    rc = live_prop.residential_complex
                    if rc.end_build_year and rc.end_build_quarter:
                        cp_dict["delivery_date"] = f"{rc.end_build_quarter} кв. {rc.end_build_year} г."
                    elif rc.end_build_year:
                        cp_dict["delivery_date"] = f"{rc.end_build_year} г."
                    else:
                        cp_dict["delivery_date"] = ""
                    cp_dict["housing_class"] = rc.object_class_display_name or ""
                else:
                    cp_dict["delivery_date"] = ""
            
            properties_data.append(cp_dict)
        
        # Enrich complex data from ResidentialComplex table
        complexes_data = []
        rc_ids = [c.complex_id for c in all_comparison_complexes]
        from models import ResidentialComplex as RC
        live_complexes = {}
        if rc_ids:
            rc_query = RC.query.filter(RC.id.in_(rc_ids)).all()
            live_complexes = {rc.id: rc for rc in rc_query}
        
        for cc in all_comparison_complexes:
            cc_dict = cc.to_dict()
            live_rc = live_complexes.get(cc.complex_id)
            if live_rc:
                cc_dict['complex_name'] = live_rc.name or cc_dict.get('complex_name', '')
                from models import Property as PriceProps
                price_stats = db.session.query(
                    func.min(PriceProps.price),
                    func.max(PriceProps.price)
                ).filter(
                    PriceProps.complex_id == live_rc.id,
                    PriceProps.is_active == True,
                    PriceProps.price > 0
                ).first()
                cc_dict['min_price'] = (price_stats[0] or 0) if price_stats else 0
                cc_dict['max_price'] = (price_stats[1] or 0) if price_stats else 0
                if live_rc.developer:
                    cc_dict['developer_name'] = live_rc.developer.name or ''
                cc_dict['district'] = live_rc.address or cc_dict.get('district', '')
                cc_dict['photo'] = cc_dict.get('photo') or live_rc.main_image or '/static/images/no-photo.svg'
                from models import Property as PropModel
                bldg_count = db.session.query(func.count(func.distinct(PropModel.complex_building_name))).filter(
                    PropModel.complex_id == live_rc.id,
                    PropModel.complex_building_name.isnot(None),
                    PropModel.complex_building_name != ''
                ).scalar() or 0
                if bldg_count > 0:
                    cc_dict['buildings_count'] = bldg_count
                elif live_rc.buildings_count and live_rc.buildings_count > 0:
                    cc_dict['buildings_count'] = live_rc.buildings_count
                else:
                    cc_dict['buildings_count'] = None
                cc_dict['complex_class'] = cc_dict.get('complex_class') or live_rc.object_class_display_name or ''
                if live_rc.end_build_year and live_rc.end_build_quarter:
                    cc_dict['completion_date'] = cc_dict.get('completion_date') or f"{live_rc.end_build_quarter} кв. {live_rc.end_build_year} г."
                elif live_rc.end_build_year:
                    cc_dict['completion_date'] = cc_dict.get('completion_date') or f"{live_rc.end_build_year} г."
                cc_dict['cashback_rate'] = live_rc.cashback_rate or 5.0
                # Count apartments from properties
                from models import Property as Prop
                apt_count = Prop.query.filter_by(complex_id=live_rc.id, is_active=True).count()
                cc_dict['apartments_count'] = cc_dict.get('apartments_count') or apt_count
            complexes_data.append(cc_dict)
        
        print(f"✅ DEBUG: Loaded {len(properties_data)} properties and {len(complexes_data)} complexes")
        
        return jsonify({
            'success': True,
            'properties': properties_data,
            'complexes': complexes_data,
            'properties_count': len(properties_data),
            'complexes_count': len(complexes_data)
        })
        
    except Exception as e:
        print(f"Error loading manager comparison: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500



@comparison_bp.route('/api/comparison/replace-property', methods=['POST'])
@csrf.exempt
@login_required
def replace_comparison_property():
    """Replace a sold property in comparison with a similar one"""
    from models import ComparisonProperty, Property
    
    try:
        data = request.get_json()
        old_property_id = data.get('old_property_id')  # ID to replace
        new_property_id = data.get('new_property_id')  # Replacement ID
        comparison_id = data.get('comparison_id')
        
        if not all([old_property_id, new_property_id, comparison_id]):
            return jsonify({'success': False, 'error': 'Missing required parameters'}), 400
        
        # Find the comparison property to replace
        cp = ComparisonProperty.query.filter_by(
            user_comparison_id=comparison_id,
            property_id=str(old_property_id)
        ).first()
        
        if not cp:
            return jsonify({'success': False, 'error': 'Property not found in comparison'}), 404
        
        # Get the new property data
        new_prop = Property.query.filter_by(id=int(new_property_id)).first()
        if not new_prop:
            # Try by inner_id if database ID doesn't work
            new_prop = Property.query.filter_by(inner_id=str(new_property_id)).first()
        
        if not new_prop or not new_prop.is_active:
            return jsonify({'success': False, 'error': 'New property not found or inactive'}), 404
        
        # Update the comparison property with new data
        cp.property_id = str(new_prop.id)
        cp.property_name = f"{new_prop.rooms if new_prop.rooms else 'Студия'}, {new_prop.area} м²"
        cp.property_price = new_prop.price
        cp.area = new_prop.area
        cp.rooms = str(new_prop.rooms) if new_prop.rooms else '0'
        
        # Update complex name if available
        if new_prop.residential_complex:
            cp.complex_name = new_prop.residential_complex.name
        
        # Calculate cashback if available
        if new_prop.residential_complex and new_prop.price:
            cashback_rate = new_prop.residential_complex.cashback_rate or 5.0
            cp.cashback = int(new_prop.price * cashback_rate / 100)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Property replaced successfully',
            'new_property': {
                'id': new_prop.id,
                'property_id': str(new_prop.id),
                'property_name': cp.property_name,
                'property_price': cp.property_price,
                'area': cp.area,
                'complex_name': cp.complex_name,
                'cashback': cp.cashback,
                'is_sold': False,
                'status_label': ''
            }
        })
    
    except Exception as e:
        db.session.rollback()
        print(f"Error replacing property: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@comparison_bp.route('/api/user/phone/send-verification', methods=['POST'])
@login_required
def send_phone_verification():
    """Send verification code to user's phone"""
    from models import User
    import random
    from datetime import datetime, timedelta
    from scripts.sms_service import send_verification_code_sms
    
    try:
        data = request.get_json()
        phone = data.get('phone')
        
        if not phone:
            return jsonify({'success': False, 'message': 'Номер телефона обязателен'}), 400
        
        # Generate 6-digit verification code
        code = ''.join([str(random.randint(0, 9)) for _ in range(6)])
        
        # Save code and expiration to user
        current_user.phone = phone
        current_user.phone_verification_code = code
        current_user.phone_verification_expires = datetime.utcnow() + timedelta(minutes=10)
        db.session.commit()
        
        # Send SMS
        sms_sent = send_verification_code_sms(phone, code)
        
        if sms_sent:
            return jsonify({
                'success': True,
                'message': 'Код отправлен на ваш номер'
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Ошибка отправки SMS. Попробуйте позже.'
            }), 500
            
    except Exception as e:
        db.session.rollback()
        print(f"Error sending verification code: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@comparison_bp.route('/api/user/phone/verify-code', methods=['POST'])
@login_required
def verify_phone_code():
    """Verify phone number with code"""
    from models import User
    from datetime import datetime
    
    try:
        data = request.get_json()
        code = data.get('code')
        
        if not code:
            return jsonify({'success': False, 'message': 'Код обязателен'}), 400
        
        # Check if code matches and not expired
        if not current_user.phone_verification_code:
            return jsonify({'success': False, 'message': 'Код не был отправлен'}), 400
        
        if current_user.phone_verification_expires < datetime.utcnow():
            return jsonify({'success': False, 'message': 'Код истек. Запросите новый.'}), 400
        
        if current_user.phone_verification_code != code:
            return jsonify({'success': False, 'message': 'Неверный код'}), 400
        
        # Mark phone as verified
        current_user.phone_verified = True
        current_user.phone_verification_code = None
        current_user.phone_verification_expires = None
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Телефон успешно подтвержден!'
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error verifying phone code: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# ========================================
# PRESENTATION SHARING (Manager to Client)
# ========================================

@comparison_bp.route('/api/manager/collection/<int:collection_id>/assign-client', methods=['POST'])
@manager_required
def assign_client_to_presentation(collection_id):
    """Assign client to presentation"""
    from models import Collection, User
    
    try:
        current_manager = current_user
        data = request.get_json()
        
        if not data or 'client_id' not in data:
            return jsonify({'success': False, 'error': 'ID клиента не указан'}), 400
        
        client_id = data['client_id']
        
        # Get collection
        collection = Collection.query.filter_by(
            id=collection_id,
            created_by_manager_id=current_manager.id
        ).first()
        
        if not collection:
            return jsonify({'success': False, 'error': 'Презентация не найдена'}), 404
        
        # Verify client exists and is assigned to this manager
        client = User.query.filter_by(id=client_id, assigned_manager_id=current_manager.id).first()
        
        if not client:
            return jsonify({'success': False, 'error': 'Клиент не найден или не закреплен за вами'}), 404
        
        # Assign client to presentation
        collection.assigned_to_user_id = client_id
        collection.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Клиент {client.full_name} назначен презентации'
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error assigning client to presentation: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@comparison_bp.route('/api/manager/collection/<int:collection_id>/send-to-client', methods=['POST'])
@manager_required
def send_presentation_to_client(collection_id):
    """Send presentation from manager to client's personal dashboard"""
    from models import Collection, User, UserNotification
    
    try:
        current_manager = current_user
        
        # Get collection
        collection = Collection.query.filter_by(
            id=collection_id,
            created_by_manager_id=current_manager.id
        ).first()
        
        if not collection:
            return jsonify({'success': False, 'error': 'Презентация не найдена'}), 404
        
        if not collection.assigned_to_user_id:
            return jsonify({'success': False, 'error': 'Клиент не назначен'}), 400
        
        if len(collection.properties) == 0:
            return jsonify({'success': False, 'error': 'В презентации нет объектов'}), 400
        
        # Update collection status
        collection.status = 'Отправлена'
        collection.sent_at = datetime.utcnow()
        collection.updated_at = datetime.utcnow()
        
        # Create notification for client
        notification = UserNotification(
            user_id=collection.assigned_to_user_id,
            title='📦 Новая презентация от менеджера',
            message=f'Менеджер отправил вам презентацию "{collection.title}" с {len(collection.properties)} объектами',
            notification_type='success',
            icon='fas fa-gift',
            action_url=f'/dashboard#presentations'
        )
        db.session.add(notification)
        
        # Логируем отправку презентации
        from models import UserActivity
        UserActivity.log_activity(
            user_id=collection.assigned_to_user_id,
            activity_type='presentation_received',
            description=f'Получена новая презентация от менеджера: {collection.title} ({len(collection.properties)} объектов)'
        )
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Презентация отправлена клиенту'
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error sending presentation to client: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@comparison_bp.route('/api/user/presentation/<int:presentation_id>/delete', methods=['DELETE'])
@login_required
@csrf.exempt  # CSRF disabled for user DELETE actions
def delete_user_presentation(presentation_id):
    """Delete presentation from user's dashboard"""
    from models import Collection, PresentationView, CollectionProperty
    
    try:
        # Get collection
        collection = Collection.query.filter_by(
            id=presentation_id,
            assigned_to_user_id=current_user.id
        ).first()
        
        if not collection:
            return jsonify({'success': False, 'error': 'Презентация не найдена'}), 404
        
        # Delete dependent records first (PresentationView has NOT NULL FK on collection_id)
        PresentationView.query.filter_by(collection_id=collection.id).delete()
        
        # Delete the collection (CollectionProperty cascades via relationship)
        db.session.delete(collection)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Презентация удалена'
        })
        
    except Exception as e:
        db.session.rollback()
        print(f"Error deleting presentation: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@comparison_bp.route('/api/manager/deals')
def api_manager_deals_count():
    """Get deals data for manager with count - used for preloading deals tab counter"""
    from models import Deal
    
    try:
        # Check if current user is a manager
        if not current_user.is_authenticated or not isinstance(current_user._get_current_object(), Manager):
            return jsonify({
                'success': True,
                'deals': [],
                'total': 0,
                'is_manager': False
            })
        
        current_manager = current_user
        
        # Get all deals for this manager
        deals = Deal.query.filter_by(manager_id=current_manager.id).all()
        
        deals_data = []
        for deal in deals:
            deals_data.append({
                'id': deal.id,
                'deal_number': deal.deal_number,
                'client_name': deal.client.full_name if deal.client else 'Unknown',
                'property_description': deal.property_description,
                'property_price': deal.property_price,
                'cashback_amount': deal.cashback_amount,
                'status': deal.status,
                'created_at': deal.created_at.isoformat() if deal.created_at else None
            })
        
        return jsonify({
            'success': True,
            'deals': deals_data,
            'total': len(deals_data),
            'is_manager': True
        })
        
    except Exception as e:
        print(f"Error getting deals count: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@comparison_bp.route('/api/manager/comparison/count')
def api_manager_comparison_count():
    """Get count of items in manager comparison for navigation counter"""
    from models import ManagerComparison, ComparisonProperty, ComparisonComplex
    
    try:
        # Check if current user is a manager
        if not current_user.is_authenticated or not isinstance(current_user._get_current_object(), Manager):
            return jsonify({
                'success': True,
                'properties_count': 0,
                'complexes_count': 0,
                'total_count': 0
            })
        
        current_manager = current_user
        
        # Find active manager comparison
        manager_comparison = ManagerComparison.query.filter_by(
            manager_id=current_manager.id,
            is_active=True
        ).first()
        
        if not manager_comparison:
            return jsonify({
                'success': True,
                'properties_count': 0,
                'complexes_count': 0,
                'total_count': 0
            })
        
        # Count properties and complexes
        properties_count = ComparisonProperty.query.filter_by(
            manager_comparison_id=manager_comparison.id
        ).count()
        
        complexes_count = ComparisonComplex.query.filter_by(
            manager_comparison_id=manager_comparison.id
        ).count()
        
        total_count = properties_count + complexes_count
        
        return jsonify({
            'success': True,
            'properties_count': properties_count,
            'complexes_count': complexes_count,
            'total_count': total_count
        })
        
    except Exception as e:
        print(f"Error getting manager comparison count: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@comparison_bp.route('/api/manager/generate-comparison-pdf', methods=['POST'])
@csrf.exempt
@manager_required
def api_manager_generate_comparison_pdf():
    """Generate HTML comparison document for manager to send to client"""
    try:
        from models import Manager
        from datetime import datetime
        
        data = request.get_json()
        
        recipient_name = data.get('recipient_name', 'Клиент')
        message_notes = data.get('message_notes', '')
        hide_complex_names = data.get('hide_complex_names', False)
        hide_developer_names = data.get('hide_developer_names', False)
        hide_addresses = data.get('hide_addresses', False)
        properties = data.get('properties', [])
        complexes = data.get('complexes', [])
        
        # Base URL for absolute image paths
        base_url = request.host_url.rstrip('/')
        
        def make_absolute_url(url):
            if not url or url == '/static/images/no-photo.svg':
                return f"{base_url}/static/images/no-photo.svg"
            if url.startswith('http'):
                return url
            return f"{base_url}{url}"
        
        # Get current manager info
        manager = current_user if current_user.is_authenticated and isinstance(current_user._get_current_object(), Manager) else None
        manager_name = manager.full_name if manager else "InBack Менеджер"
        manager_phone = manager.phone if manager else "8 (862) 266-62-16"
        manager_email = manager.email if manager else "info@inback.ru"
        
        # Get manager avatar with full URL for downloadable HTML
        if manager and manager.profile_image:
            manager_avatar = make_absolute_url(manager.profile_image)
        else:
            manager_avatar = f"{base_url}/static/images/no-photo.svg"
        
        # Get current date and time
        now = datetime.now()
        date_str = now.strftime('%d.%m.%Y')
        time_str = now.strftime('%H:%M')
        
        print(f"📄 Generating comparison PDF: {len(properties)} properties, {len(complexes)} complexes")
        
        # Build HTML document for comparison
        html_content = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Сравнение недвижимости - {recipient_name}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Arial', 'Helvetica', sans-serif;
            line-height: 1.6;
            color: #000;
            background: #fff;
            padding: 40px 20px;
            max-width: 1200px;
            margin: 0 auto;
        }}
        
        /* Print styles */
        @media print {{
            body {{
                padding: 20px;
            }}
            .no-print {{
                display: none !important;
            }}
            .page-break {{
                page-break-after: always;
            }}
        }}
        
        /* Header */
        .header {{
            text-align: center;
            margin-bottom: 40px;
            padding-bottom: 20px;
            border-bottom: 3px solid #000;
        }}
        
        .header h1 {{
            font-size: 28px;
            font-weight: bold;
            margin-bottom: 5px;
        }}
        
        .header .subtitle {{
            font-size: 18px;
            color: #555;
            margin-bottom: 20px;
        }}
        
        /* Manager info */
        .manager-info {{
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 20px;
            margin: 30px 0;
            padding: 20px;
            background: #f8f8f8;
            border-radius: 8px;
        }}
        
        .manager-avatar {{
            width: 80px;
            height: 80px;
            border-radius: 50%;
            object-fit: cover;
            border: 3px solid #333;
        }}
        
        .manager-details {{
            text-align: left;
        }}
        
        .manager-details p {{
            margin: 5px 0;
            font-size: 14px;
        }}
        
        .manager-details strong {{
            font-weight: bold;
        }}
        
        /* Recipient info */
        .recipient-info {{
            text-align: center;
            margin: 20px 0;
            padding: 15px;
            font-size: 16px;
        }}
        
        .recipient-info strong {{
            font-weight: bold;
        }}
        
        /* Notes */
        .notes {{
            margin: 20px 0;
            padding: 15px;
            background: #f0f0f0;
            border-left: 4px solid #333;
        }}
        
        .notes strong {{
            display: block;
            margin-bottom: 10px;
            font-weight: bold;
        }}
        
        /* Section title */
        .section-title {{
            font-size: 20px;
            font-weight: bold;
            margin: 30px 0 15px 0;
            padding: 10px 0;
            border-bottom: 2px solid #000;
        }}
        
        /* Table */
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
            font-size: 12px;
        }}
        
        table th {{
            background: #f0f0f0;
            border: 1px solid #ddd;
            padding: 10px;
            text-align: left;
            font-weight: bold;
        }}
        
        table td {{
            border: 1px solid #ddd;
            padding: 10px;
            vertical-align: top;
        }}
        
        table tr:nth-child(even) {{
            background: #f9f9f9;
        }}
        
        table .label-col {{
            font-weight: bold;
            background: #f5f5f5;
            width: 180px;
        }}
        
        /* Footer */
        .footer {{
            text-align: center;
            margin-top: 50px;
            padding-top: 20px;
            border-top: 2px solid #000;
            font-size: 14px;
        }}
        
        .footer p {{
            margin: 5px 0;
        }}
        
        /* Print button */
        .print-btn {{
            position: fixed;
            top: 20px;
            right: 20px;
            background: #000;
            color: #fff;
            border: none;
            padding: 12px 24px;
            font-size: 16px;
            cursor: pointer;
            border-radius: 5px;
            z-index: 1000;
        }}
        
        .print-btn:hover {{
            background: #333;
        }}
        
        /* Sold property styles */
        .sold-property {{
            opacity: 0.6;
            background-color: #f3f4f6 !important;
        }}
        .sold-badge {{
            background: #dc2626;
            color: white;
            padding: 4px 12px;
            border-radius: 6px;
            font-weight: 600;
            display: inline-block;
            margin-left: 10px;
        }}
        .sold-text {{
            text-decoration: line-through;
            color: #6b7280;
        }}
        
    </style>
</head>
<body>
    <button onclick="window.print()" class="print-btn no-print">🖨️ Печать</button>
    
    <div class="header">
        <h1>InBack Недвижимость</h1>
        <div class="subtitle">Сравнение объектов недвижимости</div>
    </div>
    
    <div class="manager-info">
        <img src="{manager_avatar}" alt="Фото менеджера" class="manager-avatar">
        <div class="manager-details">
            <p><strong>Ваш персональный менеджер: {manager_name}</strong></p>
            <p>Телефон: {manager_phone}</p>
            <p>Email: {manager_email}</p>
        </div>
    </div>
    
    <div class="recipient-info">
        <p><strong>Подготовлено для: {recipient_name}</strong></p>
        <p>Дата: {date_str} в {time_str}</p>
    </div>
"""
        
        # Add notes if provided
        if message_notes:
            html_content += f"""
    <div class="notes">
        <strong>Заметки:</strong>
        <p>{message_notes}</p>
    </div>
"""
        
        # Add properties comparison table (vertical layout)
        if properties and len(properties) > 0:
            html_content += """
    <h2 class="section-title">Сравнение квартир</h2>
    <table>
        <thead>
            <tr>
                <th class="label-col">Характеристика</th>"""
            
            # Add column headers for each property
            for i, prop in enumerate(properties, 1):
                is_sold = prop.get('is_sold', False)
                header_text = f"Объект {i}"
                if is_sold:
                    header_text += ' <span class="sold-badge">ПРОДАН</span>'
                html_content += f"\n                <th>{header_text}</th>"
            
            html_content += """
            </tr>
        </thead>
        <tbody>
"""
            

            # Row: Фото
            html_content += """
            <tr>
                <td class="label-col">Фото</td>"""
            for prop in properties:
                image_url = make_absolute_url(prop.get('property_image', ''))
                html_content += f'''
                <td><img src="{image_url}" alt="Фото объекта" style="max-width:150px; max-height:100px; object-fit:cover; border-radius:8px;"></td>'''
            html_content += "\n            </tr>"
            
            # Row: Название
            html_content += """
            <tr>
                <td class="label-col">Название</td>"""
            for prop in properties:
                name = prop.get('property_name', 'Не указано')
                is_sold = prop.get('is_sold', False)
                if is_sold:
                    html_content += f"\n                <td class=\"sold-text\">{name}</td>"
                else:
                    html_content += f"\n                <td>{name}</td>"
            html_content += "\n            </tr>"
            
            # Row: ЖК (if not hidden)
            if not hide_complex_names:
                html_content += """
            <tr>
                <td class="label-col">ЖК</td>"""
                for prop in properties:
                    html_content += f"\n                <td>{prop.get('complex_name', 'Не указано')}</td>"
                html_content += "\n            </tr>"
            
            # Row: Цена
            html_content += """
            <tr>
                <td class="label-col">Цена</td>"""
            for prop in properties:
                price = prop.get('property_price', 0)
                is_sold = prop.get('is_sold', False)
                if is_sold:
                    html_content += f"\n                <td class=\"sold-text\">{price:,.0f} ₽</td>"
                else:
                    html_content += f"\n                <td>{price:,.0f} ₽</td>"
            html_content += "\n            </tr>"

            # Row: Кешбек (highlight max)
            cashback_amounts = []
            for prop in properties:
                price = prop.get('property_price', 0)
                cashback_rate = prop.get('cashback_rate', 5.0)
                if not cashback_rate:
                    cashback_rate = 5.0
                cashback_amounts.append(int(price * cashback_rate / 100))
            max_cashback = max(cashback_amounts) if cashback_amounts else 0
            
            html_content += """
            <tr>
                <td class="label-col">Кешбек</td>"""
            for idx, prop in enumerate(properties):
                price = prop.get('property_price', 0)
                cashback_rate = prop.get('cashback_rate', 5.0)
                if not cashback_rate:
                    cashback_rate = 5.0
                cashback_amount = cashback_amounts[idx]
                is_sold = prop.get('is_sold', False)
                is_max = cashback_amount == max_cashback and len(properties) > 1 and cashback_amount > 0
                if is_sold:
                    html_content += f"\n                <td class=\"sold-text\">{cashback_amount:,} ₽ ({cashback_rate}%)</td>"
                elif is_max:
                    html_content += f"\n                <td style=\"color:#059669; font-weight:700; background:#ecfdf5; border:2px solid #10b981;\">{cashback_amount:,} ₽ ({cashback_rate}%)</td>"
                else:
                    html_content += f"\n                <td style=\"color:#059669; font-weight:600;\">{cashback_amount:,} ₽ ({cashback_rate}%)</td>"
            html_content += "\n            </tr>"
            
            # Row: Площадь
            html_content += """
            <tr>
                <td class="label-col">Площадь</td>"""
            for prop in properties:
                size = prop.get('property_size', 'Не указано')
                html_content += f"\n                <td>{size} м²</td>"
            html_content += "\n            </tr>"
            
            # Row: Комнаты
            html_content += """
            <tr>
                <td class="label-col">Комнаты</td>"""
            for prop in properties:
                rooms = prop.get('rooms', 'Не указано')
                # Show "Студия" instead of "0"
                if rooms == 0 or rooms == '0':
                    rooms_display = 'Студия'
                else:
                    rooms_display = rooms
                html_content += f"\n                <td>{rooms_display}</td>"
            html_content += "\n            </tr>"
            
            # Row: Этаж
            html_content += """
            <tr>
                <td class="label-col">Этаж</td>"""
            for prop in properties:
                floor = prop.get('floor', 'Не указано')
                html_content += f"\n                <td>{floor}</td>"
            html_content += "\n            </tr>"
            
            # Row: Всего этажей
            html_content += """
            <tr>
                <td class="label-col">Всего этажей</td>"""
            for prop in properties:
                total_floors = prop.get('total_floors', 'Не указано')
                html_content += f"\n                <td>{total_floors}</td>"
            html_content += "\n            </tr>"
            
            # Row: Застройщик (if not hidden)
            if not hide_developer_names:
                html_content += """
            <tr>
                <td class="label-col">Застройщик</td>"""
                for prop in properties:
                    developer = prop.get('developer_name', 'Не указано')
                    html_content += f"\n                <td>{developer}</td>"
                html_content += "\n            </tr>"
            
            # Row: Адрес (if not hidden)
            if not hide_addresses:
                html_content += """
            <tr>
                <td class="label-col">Адрес</td>"""
                for prop in properties:
                    address = prop.get('address', 'Не указано')
                    html_content += f"\n                <td>{address}</td>"
                html_content += "\n            </tr>"
            
            html_content += """
        </tbody>
    </table>
"""
        
        # Add complexes comparison table (vertical layout)
        if complexes and len(complexes) > 0:
            html_content += """
    <div class="page-break"></div>
    <h2 class="section-title">Сравнение жилых комплексов</h2>
    <table>
        <thead>
            <tr>
                <th class="label-col">Характеристика</th>"""
            
            # Add column headers for each complex
            for i, complex_data in enumerate(complexes, 1):
                is_sold = complex_data.get('is_sold', False)
                header_text = f"ЖК {i}"
                if is_sold:
                    header_text += ' <span class="sold-badge">ПРОДАН</span>'
                html_content += f"\n                <th>{header_text}</th>"
            
            html_content += """
            </tr>
        </thead>
        <tbody>
"""
            
            # Row: Фото ЖК
            html_content += """
            <tr>
                <td class="label-col">Фото</td>"""
            for complex_data in complexes:
                image_url = make_absolute_url(complex_data.get('photo', complex_data.get('image', '')))
                html_content += f'''
                <td><img src="{image_url}" alt="Фото ЖК" style="max-width:150px; max-height:100px; object-fit:cover; border-radius:8px;"></td>'''
            html_content += "\n            </tr>"
            
            # Row: Название ЖК
            if not hide_complex_names:
                html_content += """
            <tr>
                <td class="label-col">Название ЖК</td>"""
                for complex_data in complexes:
                    name = complex_data.get('name', 'Не указано')
                    is_sold = complex_data.get('is_sold', False)
                    if is_sold:
                        html_content += f"\n                <td class=\"sold-text\"><strong>{name}</strong></td>"
                    else:
                        html_content += f"\n                <td><strong>{name}</strong></td>"
                html_content += "\n            </tr>"
            
            # Row: Класс жилья
            html_content += """
            <tr>
                <td class="label-col">Класс жилья</td>"""
            for complex_data in complexes:
                obj_class = complex_data.get('object_class') or complex_data.get('housing_class') or complex_data.get('class') or 'Не указано'
                html_content += f"\n                <td>{obj_class}</td>"
            html_content += "\n            </tr>"
            
            # Row: Цена от
            html_content += """
            <tr>
                <td class="label-col">Цена от</td>"""
            for complex_data in complexes:
                min_price = complex_data.get('min_price', 0)
                is_sold = complex_data.get('is_sold', False)
                if is_sold:
                    html_content += f"\n                <td class=\"sold-text\">{min_price:,.0f} ₽</td>"
                else:
                    html_content += f"\n                <td>{min_price:,.0f} ₽</td>"
            html_content += "\n            </tr>"
            
            # Row: Цена до
            html_content += """
            <tr>
                <td class="label-col">Цена до</td>"""
            for complex_data in complexes:
                max_price = complex_data.get('max_price', 0)
                is_sold = complex_data.get('is_sold', False)
                if is_sold:
                    html_content += f"\n                <td class=\"sold-text\">{max_price:,.0f} ₽</td>"
                else:
                    html_content += f"\n                <td>{max_price:,.0f} ₽</td>"
            html_content += "\n            </tr>"
            
            # Row: Срок сдачи
            html_content += """
            <tr>
                <td class="label-col">Срок сдачи</td>"""
            for complex_data in complexes:
                completion = complex_data.get('completion_date', 'Не указано')
                html_content += f"\n                <td>{completion}</td>"
            html_content += "\n            </tr>"
            
            # Row: Кешбек
            html_content += """
            <tr>
                <td class="label-col">Кешбек</td>"""
            for complex_data in complexes:
                cashback_rate = complex_data.get('cashback_rate', 0)
                html_content += f"\n                <td>{cashback_rate}%</td>"
            html_content += "\n            </tr>"
            
            # Row: Застройщик (if not hidden)
            if not hide_developer_names:
                html_content += """
            <tr>
                <td class="label-col">Застройщик</td>"""
                for complex_data in complexes:
                    developer = complex_data.get('developer', 'Не указано')
                    html_content += f"\n                <td>{developer}</td>"
                html_content += "\n            </tr>"
            
            # Row: Адрес (if not hidden)
            if not hide_addresses:
                html_content += """
            <tr>
                <td class="label-col">Адрес</td>"""
                for complex_data in complexes:
                    address = complex_data.get('address', 'Не указано')
                    html_content += f"\n                <td>{address}</td>"
                html_content += "\n            </tr>"
            
            html_content += """
        </tbody>
    </table>
"""
        
        # Add footer
        html_content += f"""
    <div class="footer">
        <p><strong>InBack.ru</strong> - ваш кешбек за новостройки</p>
        <p>Документ создан {date_str} в {time_str}</p>
    </div>
</body>
</html>
"""
        
        # Return HTML for download
        from flask import current_app
        response = current_app.response_class(
            response=html_content,
            status=200,
            mimetype='text/html; charset=utf-8'
        )
        
        # Set download filename with safe ASCII characters
        from datetime import datetime
        from unidecode import unidecode
        timestamp = datetime.now().strftime('%Y-%m-%d')
        # Convert recipient name to ASCII to avoid encoding issues
        safe_name = unidecode(recipient_name).replace(' ', '_')
        ascii_filename = f'Sravnenie_{safe_name}_{timestamp}.html'
        
        response.headers['Content-Disposition'] = f'attachment; filename="{ascii_filename}"'
        
        print(f"✅ Comparison HTML generated successfully")
        return response
        
    except Exception as e:
        print(f"❌ Error generating comparison PDF: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Failed to generate comparison document', 'details': str(e)}), 500

@comparison_bp.route('/api/recommendations/<int:rec_id>/respond', methods=['POST'])
@login_required
def api_respond_to_recommendation(rec_id):
    """Client responds to recommendation with interest/not interested"""
    from models import Recommendation
    from datetime import datetime
    
    try:
        data = request.get_json()
        response_type = data.get('response')  # 'interested' or 'not_interested'
        
        if response_type not in ['interested', 'not_interested']:
            return jsonify({'success': False, 'error': 'Неверный тип ответа'}), 400
            
        recommendation = Recommendation.query.filter_by(
            id=rec_id,
            client_id=current_user.id
        ).first()
        
        if not recommendation:
            return jsonify({'success': False, 'error': 'Рекомендация не найдена'}), 404
            
        recommendation.status = response_type
        recommendation.client_response = response_type
        recommendation.responded_at = datetime.utcnow()
        
        db.session.commit()
        
        # Notify manager about client response
        if recommendation.manager:
            try:
                from email_service import send_notification
                subject = f"Ответ клиента на рекомендацию: {recommendation.title}"
                message = f"""
Клиент {current_user.full_name} ответил на вашу рекомендацию:

Рекомендация: {recommendation.title}
Объект: {recommendation.item_name}
Ответ: {'Интересно' if response_type == 'interested' else 'Не интересно'}

Время ответа: {datetime.now().strftime('%d.%m.%Y %H:%M')}
"""
                send_notification(
                    recommendation.manager.email,
                    subject,
                    message,
                    notification_type="client_response"
                )
            except Exception as e:
                print(f"Error sending notification to manager: {e}")
        
        return jsonify({'success': True})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400


@comparison_bp.route('/api/manager/recommendation-categories/<int:client_id>', methods=['GET'])
def api_get_recommendation_categories(client_id):
    """Get recommendation categories for a specific client"""
    from models import RecommendationCategory
    
    # Check if user is authenticated as manager
    if not current_user.is_authenticated or not isinstance(current_user._get_current_object(), Manager):
        return jsonify({'success': False, 'error': 'Требуется авторизация менеджера'}), 401
    
    current_manager = current_user
    
    try:
        categories = RecommendationCategory.query.filter_by(
            manager_id=current_manager.id,
            client_id=client_id,
            is_active=True
        ).order_by(RecommendationCategory.last_used.desc()).all()
        
        categories_data = []
        for category in categories:
            categories_data.append({
                'id': category.id,
                'name': category.name,
                'description': category.description,
                'color': category.color,
                'recommendations_count': category.recommendations_count,
                'last_used': category.last_used.strftime('%d.%m.%Y') if category.last_used else '',
                'created_at': category.created_at.strftime('%d.%m.%Y') if category.created_at else ''
            })
        
        return jsonify({
            'success': True,
            'categories': categories_data
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@comparison_bp.route('/api/manager/recommendation-categories', methods=['POST'])
def api_create_recommendation_category():
    """Create new recommendation category"""
    from models import RecommendationCategory
    
    # Check if user is authenticated as manager
    if not current_user.is_authenticated or not isinstance(current_user._get_current_object(), Manager):
        return jsonify({'success': False, 'error': 'Требуется авторизация менеджера'}), 401
    
    current_manager = current_user
    
    try:
        data = request.get_json()
        category_name = data.get('name', '').strip()
        client_id = data.get('client_id')
        description = data.get('description', '').strip()
        color = data.get('color', 'blue')
        
        if not category_name or not client_id:
            return jsonify({'success': False, 'error': 'Название категории и клиент обязательны'}), 400
        
        # Check if category with this name already exists for this client
        existing = RecommendationCategory.query.filter_by(
            manager_id=current_manager.id,
            client_id=client_id,
            name=category_name,
            is_active=True
        ).first()
        
        if existing:
            return jsonify({'success': False, 'error': 'Категория с таким названием уже существует'}), 400
        
        # Create new category
        category = RecommendationCategory(
            name=category_name,
            description=description,
            manager_id=current_manager.id,
            client_id=client_id,
            color=color
        )
        
        db.session.add(category)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'category': {
                'id': category.id,
                'name': category.name,
                'description': category.description,
                'color': category.color,
                'recommendations_count': 0,
                'created_at': category.created_at.strftime('%d.%m.%Y')
            }
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 400

@comparison_bp.route('/api/manager/all-categories', methods=['GET'])
def api_manager_all_categories():
    """Get all categories created by this manager"""
    from models import RecommendationCategory, User
    
    # Check if user is authenticated as manager
    if not current_user.is_authenticated or not isinstance(current_user._get_current_object(), Manager):
        return jsonify({'success': False, 'error': 'Требуется авторизация менеджера'}), 401
    
    current_manager = current_user
    
    try:
        categories = db.session.query(
            RecommendationCategory, 
            User.email.label('client_email')
        ).outerjoin(
            User, RecommendationCategory.client_id == User.id
        ).filter(
            RecommendationCategory.manager_id == current_manager.id
        ).order_by(
            RecommendationCategory.last_used.desc().nulls_last(),
            RecommendationCategory.created_at.desc()
        ).all()
        
        category_data = []
        for category, client_email in categories:
            category_data.append({
                'id': category.id,
                'name': category.name,
                'description': category.description,
                'client_email': client_email or 'Общая категория',
                'recommendations_count': category.recommendations_count,
                'is_active': category.is_active,
                'last_used': category.last_used.isoformat() if category.last_used else None,
                'created_at': category.created_at.isoformat()
            })
        
        return jsonify({
            'success': True,
            'categories': category_data
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@comparison_bp.route('/api/manager/categories/global', methods=['POST'])
def api_manager_create_global_category():
    """Create a new global category template"""
    from models import RecommendationCategory
    
    # Check if user is authenticated as manager
    if not current_user.is_authenticated or not isinstance(current_user._get_current_object(), Manager):
        return jsonify({'success': False, 'error': 'Требуется авторизация менеджера'}), 401
    
    current_manager = current_user
    
    data = request.get_json()
    name = data.get('name', '').strip()
    description = data.get('description', '').strip()
    
    if not name:
        return jsonify({'success': False, 'error': 'Укажите название категории'}), 400
    
    try:
        # Create a template category without specific client
        category = RecommendationCategory(
            name=name,
            description=description,
            manager_id=current_manager.id,
            client_id=None,  # Global template
            is_template=True,
            recommendations_count=0
        )
        
        db.session.add(category)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'category': {
                'id': category.id,
                'name': category.name,
                'description': category.description
            }
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@comparison_bp.route('/api/manager/categories/<int:category_id>/toggle', methods=['POST'])
def api_manager_toggle_category(category_id):
    """Toggle category active status"""
    from models import RecommendationCategory
    
    # Check if user is authenticated as manager
    if not current_user.is_authenticated or not isinstance(current_user._get_current_object(), Manager):
        return jsonify({'success': False, 'error': 'Требуется авторизация менеджера'}), 401
    
    current_manager = current_user
    
    data = request.get_json()
    is_active = data.get('is_active', True)
    
    try:
        category = RecommendationCategory.query.filter_by(
            id=category_id,
            manager_id=current_manager.id
        ).first()
        
        if not category:
            return jsonify({'success': False, 'error': 'Категория не найдена'}), 404
        
        category.is_active = is_active
        db.session.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

# Manager Dashboard API endpoints
@comparison_bp.route('/api/manager/welcome-message', methods=['GET'])
@manager_required
def api_manager_welcome_message():
    """Get adaptive welcome message based on recent activity"""
    from models import User, Recommendation, Collection, SavedSearch, Manager
    from sqlalchemy import func, desc
    from datetime import datetime, timedelta
    
    current_manager = current_user
    
    if not current_manager:
        return jsonify({'success': False, 'error': 'Менеджер не найден'}), 404
    
    try:
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=7)
        
        # Get recent activity counts
        recent_recommendations = Recommendation.query.filter(
            Recommendation.manager_id == current_manager.id,
            Recommendation.created_at >= week_start
        ).count()
        
        today_recommendations = Recommendation.query.filter(
            Recommendation.manager_id == current_manager.id,
            Recommendation.created_at >= today_start
        ).count()
        
        recent_collections = Collection.query.filter(
            Collection.created_by_manager_id == current_manager.id,
            Collection.created_at >= week_start
        ).count()
        
        total_clients = User.query.filter_by(assigned_manager_id=current_manager.id).count()
        
        new_clients_today = User.query.filter(
            User.assigned_manager_id == current_manager.id,
            User.created_at >= today_start
        ).count()
        
        # Get last activity time (use created_at if last_login_at doesn't exist)
        last_activity = getattr(current_manager, 'last_login_at', None) or current_manager.created_at
        hours_since_last_login = (now - last_activity).total_seconds() / 3600 if last_activity else 0
        
        # Get most recent activity
        latest_recommendation = Recommendation.query.filter_by(manager_id=current_manager.id).order_by(desc(Recommendation.created_at)).first()
        latest_collection = Collection.query.filter_by(created_by_manager_id=current_manager.id).order_by(desc(Collection.created_at)).first()
        
        # Generate adaptive message based on activity patterns
        messages = []
        
        # Time-based greeting
        hour = now.hour
        if 5 <= hour < 12:
            time_greeting = "Доброе утро"
        elif 12 <= hour < 18:
            time_greeting = "Добрый день"
        elif 18 <= hour < 23:
            time_greeting = "Добрый вечер"
        else:
            time_greeting = "Доброй ночи"
        
        first_name = current_manager.full_name.split()[0] if current_manager.full_name else 'Коллега'
        
        # Activity-based messages
        if hours_since_last_login >= 24:
            messages.append(f"{time_greeting}, {first_name}! Рады видеть вас снова.")
            if recent_recommendations > 0:
                messages.append(f"За время вашего отсутствия было отправлено {recent_recommendations} рекомендаций.")
        elif hours_since_last_login >= 8:
            messages.append(f"{time_greeting}, {first_name}! Добро пожаловать обратно.")
        else:
            messages.append(f"{time_greeting}, {first_name}!")
        
        # Recent activity highlights
        if today_recommendations > 0:
            messages.append(f"Сегодня вы уже отправили {today_recommendations} рекомендаций - отличная работа!")
        elif recent_recommendations > 0:
            messages.append(f"На этой неделе вы отправили {recent_recommendations} рекомендаций клиентам.")
        
        if new_clients_today > 0:
            messages.append(f"У вас {new_clients_today} новых клиентов сегодня.")
        
        if recent_collections > 0:
            messages.append(f"Создано {recent_collections} новых подборок на этой неделе.")
        
        # Motivational suggestions based on activity
        if recent_recommendations == 0 and recent_collections == 0:
            messages.append("Готовы создать новую подборку для клиентов?")
        elif total_clients > 0 and recent_recommendations < 3:
            messages.append("Возможно, стоит отправить рекомендации активным клиентам?")
        
        # Default fallback
        if len(messages) == 1:  # Only greeting
            messages.append("Панель управления менеджера недвижимости готова к работе.")
        
        # Activity context for additional UI hints
        activity_context = {
            'has_recent_activity': recent_recommendations > 0 or recent_collections > 0,
            'needs_attention': total_clients > 0 and recent_recommendations == 0,
            'high_activity': recent_recommendations >= 5 or recent_collections >= 3,
            'new_day': hours_since_last_login >= 8,
            'latest_recommendation_date': latest_recommendation.created_at.strftime('%d.%m.%Y') if latest_recommendation else None,
            'latest_collection_date': latest_collection.created_at.strftime('%d.%m.%Y') if latest_collection else None
        }
        
        return jsonify({
            'success': True,
            'messages': messages,
            'context': activity_context,
            'stats': {
                'recent_recommendations': recent_recommendations,
                'today_recommendations': today_recommendations,
                'recent_collections': recent_collections,
                'total_clients': total_clients,
                'new_clients_today': new_clients_today
            }
        })
        
    except Exception as e:
        print(f"Error generating welcome message: {e}")
        return jsonify({
            'success': True,
            'messages': [f"{time_greeting}, {first_name}!", "Панель управления менеджера недвижимости"],
            'context': {'has_recent_activity': False},
            'stats': {}
        })

@comparison_bp.route('/api/manager/dashboard-stats', methods=['GET'])
@login_required
@manager_required
def api_manager_dashboard_stats():
    """Get manager dashboard statistics"""
    from models import User, Recommendation
    from sqlalchemy import func
    
    current_manager = current_user
    
    try:
        # Count clients assigned to this manager
        clients_count = User.query.filter_by(assigned_manager_id=current_manager.id).count()
        
        # Count recommendations sent by this manager
        recommendations_count = Recommendation.query.filter_by(manager_id=current_manager.id).count()
        
        # Count recommendations sent this month
        from datetime import datetime
        month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        monthly_recommendations = Recommendation.query.filter(
            Recommendation.manager_id == current_manager.id,
            Recommendation.sent_at >= month_start
        ).count()
        
        # Collections count (placeholder for now)
        collections_count = 5
        
        return jsonify({
            'success': True,
            'clients_count': clients_count,
            'recommendations_count': monthly_recommendations,
            'total_recommendations': recommendations_count,
            'collections_count': collections_count
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@comparison_bp.route('/api/manager/activity-feed', methods=['GET'])
@manager_required
def api_manager_activity_feed():
    """Get manager activity feed"""
    from models import Recommendation, User, ManagerNotification
    from datetime import datetime, timedelta
    
    current_manager = current_user
    
    try:
        # Get recent activities (recommendations sent)
        from sqlalchemy.orm import joinedload
        recent_recommendations = Recommendation.query.filter_by(
            manager_id=current_manager.id
        ).options(joinedload(Recommendation.client)).order_by(Recommendation.sent_at.desc()).limit(10).all()
        
        # Получаем последние уведомления менеджера
        recent_notifications = ManagerNotification.query.filter_by(
            manager_id=current_manager.id
        ).order_by(ManagerNotification.created_at.desc()).limit(15).all()
        
        # Функция для форматирования времени
        def format_time_ago(timestamp):
            time_diff = datetime.utcnow() - timestamp
            if time_diff.days > 0:
                return f"{time_diff.days} дн. назад"
            elif time_diff.seconds > 3600:
                return f"{time_diff.seconds // 3600} ч. назад"
            else:
                return f"{time_diff.seconds // 60} мин. назад"
        
        # Создаем общий список с временными метками для сортировки
        all_activities = []
        
        # Добавляем уведомления
        for notification in recent_notifications:
            icon = 'eye'
            ntype = 'notification'
            if notification.notification_type == 'presentation_view':
                icon = 'eye'
                ntype = 'presentation_view'
            elif notification.notification_type == 'deal_update':
                icon = 'briefcase'
                ntype = 'deal_update'
            elif notification.notification_type == 'task_update':
                icon = 'clipboard'
                ntype = 'task_update'
            elif notification.notification_type == 'task_reminder':
                icon = 'clock'
                ntype = 'task_reminder'
            all_activities.append({
                'timestamp': notification.created_at,
                'activity': {
                    'title': notification.title,
                    'description': notification.message,
                    'time_ago': format_time_ago(notification.created_at),
                    'icon': icon,
                    'color': 'blue',
                    'is_read': notification.is_read,
                    'notification_id': notification.id,
                    'type': ntype
                }
            })
        
        # Добавляем рекомендации
        for rec in recent_recommendations:
            client_name = rec.client.full_name if rec.client and hasattr(rec.client, 'full_name') else 'Клиент'
            all_activities.append({
                'timestamp': rec.sent_at,
                'activity': {
                    'title': f'Отправлена рекомендация',
                    'description': f'{rec.title} для {client_name}',
                    'time_ago': format_time_ago(rec.sent_at),
                    'icon': 'paper-plane',
                    'color': 'blue',
                    'type': 'recommendation'
                }
            })
        
        # Добавляем активности по сделкам (DealHistory)
        from models import DealHistory, Deal
        recent_deal_history = DealHistory.query.filter_by(
            author_id=current_manager.id
        ).order_by(DealHistory.created_at.desc()).limit(10).all()
        
        for dh in recent_deal_history:
            deal = Deal.query.get(dh.deal_id)
            deal_label = f'Сделка #{deal.deal_number}' if deal else 'Сделка'
            icon = 'briefcase'
            ntype = 'deal_update'
            desc = dh.description or ''
            if dh.action == 'stage_change':
                desc = f'{deal_label}: этап изменен' + (f' → {dh.new_value}' if dh.new_value else '')
            elif dh.action == 'task_created':
                icon = 'clipboard'
                ntype = 'task_update'
                desc = f'{deal_label}: создана задача'
            elif dh.action == 'task_completed':
                icon = 'clipboard'
                ntype = 'task_update'
                desc = f'{deal_label}: задача выполнена'
            elif dh.action == 'comment_added':
                icon = 'chat'
                ntype = 'comment'
                desc = f'{deal_label}: добавлен комментарий'
            elif dh.action == 'field_update':
                desc = f'{deal_label}: обновлено поле {dh.field_name or ""}'
            elif dh.action == 'deal_created':
                desc = f'{deal_label} создана'
            
            all_activities.append({
                'timestamp': dh.created_at,
                'activity': {
                    'title': DealHistory.ACTION_LABELS.get(dh.action, dh.action),
                    'description': desc,
                    'time_ago': format_time_ago(dh.created_at),
                    'icon': icon,
                    'color': 'blue',
                    'type': ntype
                }
            })
        
        # Сортируем по времени и берем только активности
        all_activities.sort(key=lambda x: x['timestamp'], reverse=True)
        activities = [item['activity'] for item in all_activities[:10]]
        
        # Добавляем демо активности только если реальных активностей мало
        if len(activities) < 2:
            activities.extend([
                {
                    'title': 'Новый клиент добавлен',
                    'description': 'Демо Клиентов зарегистрировался в системе',
                    'time_ago': '2 ч. назад',
                    'icon': 'user-plus',
                    'color': 'green'
                },
                {
                    'title': 'Начните работу',
                    'description': 'Создайте сделку или подборку для клиента',
                    'time_ago': '',
                    'icon': 'briefcase',
                    'color': 'blue'
                }
            ])
        
        return jsonify({
            'success': True,
            'activities': activities
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@comparison_bp.route('/api/manager/dashboard/all', methods=['GET'])
@manager_required
def api_manager_dashboard_all():
    """Агрегированный endpoint для быстрой загрузки панели менеджера - все данные за один запрос"""
    from models import (User, Recommendation, ManagerSavedSearch, Deal, ManagerComparison, 
                       ComparisonProperty, ComparisonComplex, ManagerFavoriteProperty, ManagerFavoriteComplex,
                       ManagerNotification, Manager)
    from sqlalchemy import func
    from datetime import datetime, timedelta
    
    current_manager = current_user
    
    try:
        # ===== 1. CLIENTS =====
        clients = User.query.filter_by(assigned_manager_id=current_manager.id).all()
        clients_data = [{
            'id': client.id,
            'full_name': client.full_name,
            'email': client.email,
            'phone': client.phone or '',
            'profile_image': client.profile_image or '',
            'status': client.status if hasattr(client, 'status') else 'active',
            'search_preferences': client.search_preferences if hasattr(client, 'search_preferences') else None,
            'created_at': client.created_at.isoformat() if client.created_at else None
        } for client in clients]
        
        # ===== 2. WELCOME MESSAGE =====
        import pytz
        moscow_tz = pytz.timezone('Europe/Moscow')
        now_utc = datetime.utcnow()
        now_moscow = now_utc.replace(tzinfo=pytz.UTC).astimezone(moscow_tz)
        hour = now_moscow.hour
        
        if 5 <= hour < 12:
            time_greeting = "Доброе утро"
        elif 12 <= hour < 18:
            time_greeting = "Добрый день"
        else:
            time_greeting = "Добрый вечер"
        
        first_name = current_manager.full_name.split()[0] if current_manager.full_name else 'Менеджер'
        
        today = datetime.utcnow().date()
        week_ago = datetime.utcnow() - timedelta(days=7)
        
        recent_recommendations = Recommendation.query.filter(
            Recommendation.manager_id == current_manager.id,
            Recommendation.sent_at >= week_ago
        ).count()
        
        today_recommendations = Recommendation.query.filter(
            Recommendation.manager_id == current_manager.id,
            func.date(Recommendation.sent_at) == today
        ).count()
        
        total_clients = len(clients_data)
        new_clients_today = User.query.filter(
            User.assigned_manager_id == current_manager.id,
            func.date(User.created_at) == today
        ).count()
        
        messages = [f"{time_greeting}, {first_name}! Рады видеть вас снова."]
        
        if new_clients_today > 0:
            messages.append(f"У вас {new_clients_today} новых клиентов сегодня!")
        elif recent_recommendations == 0:
            messages.append("Готовы создать новую подборку для клиентов?")
        elif today_recommendations > 0:
            messages.append(f"Отлично! Сегодня отправлено {today_recommendations} рекомендаций.")
        else:
            messages.append(f"На этой неделе отправлено {recent_recommendations} рекомендаций.")
        
        # ===== 3. ACTIVITY FEED =====
        from sqlalchemy.orm import joinedload
        recent_recs = Recommendation.query.filter_by(
            manager_id=current_manager.id
        ).options(joinedload(Recommendation.client)).order_by(Recommendation.sent_at.desc()).limit(10).all()
        
        recent_notifications = ManagerNotification.query.filter_by(
            manager_id=current_manager.id
        ).order_by(ManagerNotification.created_at.desc()).limit(15).all()
        
        def format_time_ago(timestamp):
            time_diff = datetime.utcnow() - timestamp
            if time_diff.days > 0:
                return f"{time_diff.days} дн. назад"
            elif time_diff.seconds > 3600:
                return f"{time_diff.seconds // 3600} ч. назад"
            else:
                return f"{time_diff.seconds // 60} мин. назад"
        
        all_activities = []
        
        for notification in recent_notifications:
            icon = 'eye'
            ntype = 'notification'
            if notification.notification_type == 'presentation_view':
                icon = 'eye'
                ntype = 'presentation_view'
            elif notification.notification_type == 'deal_update':
                icon = 'briefcase'
                ntype = 'deal_update'
            elif notification.notification_type == 'task_update':
                icon = 'clipboard'
                ntype = 'task_update'
            elif notification.notification_type == 'task_reminder':
                icon = 'clock'
                ntype = 'task_reminder'
            all_activities.append({
                'timestamp': notification.created_at,
                'activity': {
                    'title': notification.title,
                    'description': notification.message,
                    'time_ago': format_time_ago(notification.created_at),
                    'icon': icon,
                    'color': 'blue',
                    'is_read': notification.is_read,
                    'notification_id': notification.id,
                    'type': ntype
                }
            })
        
        for rec in recent_recs:
            client_name = rec.client.full_name if rec.client and hasattr(rec.client, 'full_name') else 'Клиент'
            all_activities.append({
                'timestamp': rec.sent_at,
                'activity': {
                    'title': 'Отправлена рекомендация',
                    'description': f'{rec.title} для {client_name}',
                    'time_ago': format_time_ago(rec.sent_at),
                    'icon': 'paper-plane',
                    'color': 'blue',
                    'type': 'recommendation'
                }
            })
        
        # Добавляем активности по сделкам
        from models import DealHistory, Deal
        recent_deal_history = DealHistory.query.filter_by(
            author_id=current_manager.id
        ).order_by(DealHistory.created_at.desc()).limit(10).all()
        
        for dh in recent_deal_history:
            deal = Deal.query.get(dh.deal_id)
            deal_label = f'Сделка #{deal.deal_number}' if deal else 'Сделка'
            icon = 'briefcase'
            ntype = 'deal_update'
            desc = dh.description or ''
            if dh.action == 'stage_change':
                desc = f'{deal_label}: этап изменен' + (f' → {dh.new_value}' if dh.new_value else '')
            elif dh.action == 'task_created':
                icon = 'clipboard'
                ntype = 'task_update'
                desc = f'{deal_label}: создана задача'
            elif dh.action == 'task_completed':
                icon = 'clipboard'
                ntype = 'task_update'
                desc = f'{deal_label}: задача выполнена'
            elif dh.action == 'comment_added':
                icon = 'chat'
                ntype = 'comment'
                desc = f'{deal_label}: добавлен комментарий'
            elif dh.action == 'field_update':
                desc = f'{deal_label}: обновлено поле {dh.field_name or ""}'
            elif dh.action == 'deal_created':
                desc = f'{deal_label} создана'
            
            all_activities.append({
                'timestamp': dh.created_at,
                'activity': {
                    'title': DealHistory.ACTION_LABELS.get(dh.action, dh.action),
                    'description': desc,
                    'time_ago': format_time_ago(dh.created_at),
                    'icon': icon,
                    'color': 'blue',
                    'type': ntype
                }
            })
        
        all_activities.sort(key=lambda x: x['timestamp'], reverse=True)
        activities = [item['activity'] for item in all_activities[:10]]
        
        if len(activities) < 2:
            activities.extend([
                {
                    'title': 'Новый клиент добавлен',
                    'description': 'Демо Клиентов зарегистрировался в системе',
                    'time_ago': '2 ч. назад',
                    'icon': 'user-plus',
                    'color': 'green'
                },
                {
                    'title': 'Начните работу',
                    'description': 'Создайте сделку или подборку для клиента',
                    'time_ago': '',
                    'icon': 'briefcase',
                    'color': 'blue'
                }
            ])
        
        # ===== 4. FAVORITES COUNT =====
        properties_count = ManagerFavoriteProperty.query.filter_by(manager_id=current_manager.id).count()
        complexes_count = ManagerFavoriteComplex.query.filter_by(manager_id=current_manager.id).count()
        
        # ===== 5. SAVED SEARCHES =====
        saved_searches = ManagerSavedSearch.query.filter_by(manager_id=current_manager.id).order_by(ManagerSavedSearch.created_at.desc()).all()
        searches_data = [{
            'id': search.id,
            'name': search.name,
            'filters': json.loads(search.additional_filters) if search.additional_filters else {},
            'created_at': search.created_at.strftime('%d.%m.%Y')
        } for search in saved_searches]
        
        # ===== 6. RECOMMENDATIONS =====
        recommendations = Recommendation.query.filter_by(manager_id=current_manager.id).order_by(Recommendation.sent_at.desc()).limit(10).all()
        recs_data = []
        for rec in recommendations:
            client = User.query.get(rec.client_id) if rec.client_id else None
            recs_data.append({
                'id': rec.id,
                'title': rec.title,
                'client_name': client.full_name if client else 'Клиент удален',
                'sent_at': rec.sent_at.strftime('%d.%m.%Y в %H:%M'),
                'status': rec.status,
                'properties_count': len(rec.properties) if hasattr(rec, 'properties') else 0
            })
        
        # ===== 7. DEALS COUNT =====
        deals_count = Deal.query.filter_by(manager_id=current_manager.id).count()
        
        # ===== 8. COMPARISON COUNT =====
        manager_comparison = ManagerComparison.query.filter_by(
            manager_id=current_manager.id,
            is_active=True
        ).first()
        
        comparison_props = 0
        comparison_complexes = 0
        if manager_comparison:
            comparison_props = ComparisonProperty.query.filter_by(manager_comparison_id=manager_comparison.id).count()
            comparison_complexes = ComparisonComplex.query.filter_by(manager_comparison_id=manager_comparison.id).count()
        
        return jsonify({
            'success': True,
            'clients': clients_data,
            'welcome': {
                'messages': messages,
                'stats': {
                    'recent_recommendations': recent_recommendations,
                    'today_recommendations': today_recommendations,
                    'total_clients': total_clients,
                    'new_clients_today': new_clients_today
                }
            },
            'activities': activities,
            'favorites': {
                'properties_count': properties_count,
                'complexes_count': complexes_count,
                'total_count': properties_count + complexes_count
            },
            'saved_searches': {
                'count': len(searches_data),
                'searches': searches_data
            },
            'recommendations': recs_data,
            'deals_count': deals_count,
            'comparison': {
                'properties_count': comparison_props,
                'complexes_count': comparison_complexes,
                'total_count': comparison_props + comparison_complexes
            }
        })
        
    except Exception as e:
        import traceback
        print(f"Error loading manager dashboard data: {e}")
        print(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500


@comparison_bp.route('/api/manager/top-clients', methods=['GET'])
@login_required
@manager_required
def api_manager_top_clients():
    """Get top clients by interactions"""
    from models import User, Recommendation
    from sqlalchemy import func
    
    current_manager = current_user
    
    try:
        # Get clients with most interactions (recommendations received)
        top_clients = db.session.query(
            User,
            func.count(Recommendation.id).label('interactions_count')
        ).join(
            Recommendation, User.id == Recommendation.client_id
        ).filter(
            Recommendation.manager_id == current_manager.id
        ).group_by(User.id).order_by(
            func.count(Recommendation.id).desc()
        ).limit(5).all()
        
        clients_data = []
        for user, count in top_clients:
            clients_data.append({
                'id': user.id,
                'full_name': user.full_name,
                'email': user.email,
                'interactions_count': count
            })
        
        # Add demo clients if not enough data
        if len(clients_data) < 3:
            demo_clients = [
                {'id': 999, 'full_name': 'Демо Клиентов', 'email': 'demo@inback.ru', 'interactions_count': 8},
                {'id': 998, 'full_name': 'Анна Покупателева', 'email': 'buyer@test.ru', 'interactions_count': 5},
                {'id': 997, 'full_name': 'Петр Инвесторов', 'email': 'investor@test.ru', 'interactions_count': 3}
            ]
            clients_data.extend(demo_clients[:3-len(clients_data)])
        
        return jsonify({
            'success': True,
            'clients': clients_data
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400
