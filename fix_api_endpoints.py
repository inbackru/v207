#!/usr/bin/env python3
"""
Script to fix API endpoint violations
Replaces incorrect endpoints with correct ones according to spec
"""

# Read the file
with open('app.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Correct endpoints to insert
correct_endpoints = '''@app.route('/api/user/alert-settings', methods=['GET'])
@login_required
def get_user_alert_settings():
    """Get all user's saved searches with alert settings"""
    from models import SavedSearch, PropertyAlert
    
    searches = db.session.query(SavedSearch)\\
        .filter_by(user_id=current_user.id)\\
        .order_by(SavedSearch.last_used.desc())\\
        .all()
    
    # Enrich each search with alert count
    result = []
    for search in searches:
        search_dict = search.to_dict()
        alert_count = db.session.query(PropertyAlert)\\
            .filter_by(saved_search_id=search.id)\\
            .count()
        search_dict['alert_count'] = alert_count
        result.append(search_dict)
    
    return jsonify({'success': True, 'searches': result})

@app.route('/api/user/alert-settings', methods=['POST'])
@login_required
@require_json_csrf
def update_user_alert_settings():
    """Update alert settings for a specific saved search"""
    data = request.get_json()
    search_id = data.get('search_id')
    
    if not search_id:
        return jsonify({'success': False, 'error': 'search_id required'}), 400
    
    search = db.session.query(SavedSearch)\\
        .filter_by(id=search_id, user_id=current_user.id)\\
        .first()
    
    if not search:
        return jsonify({'success': False, 'error': 'Поиск не найден'}), 404
    
    # Update fields
    if 'alert_enabled' in data:
        search.alert_enabled = bool(data['alert_enabled'])
    
    if 'alert_frequency' in data:
        freq = data['alert_frequency']
        if freq not in ['instant', 'daily', 'weekly', 'never']:
            return jsonify({'success': False, 'error': 'Invalid frequency'}), 400
        search.alert_frequency = freq
    
    if 'alert_channels' in data:
        channels = data['alert_channels']
        if not isinstance(channels, list):
            return jsonify({'success': False, 'error': 'Channels must be array'}), 400
        import json
        search.alert_channels = json.dumps(channels)
    
    db.session.commit()
    return jsonify({'success': True, 'search': search.to_dict()})

@app.route('/api/user/unsubscribe/<token>', methods=['GET'])
def unsubscribe_from_alerts(token):
    """Unsubscribe from alerts using token"""
    import jwt
    
    try:
        payload = jwt.decode(token, app.secret_key, algorithms=['HS256'])
        user_id = payload.get('user_id')
        search_id = payload.get('search_id')
        
        search = db.session.query(SavedSearch)\\
            .filter_by(id=search_id, user_id=user_id)\\
            .first()
        
        if search:
            search.alert_enabled = False
            db.session.commit()
            return render_template('unsubscribe_success.html', search_name=search.name)
        
        return render_template('unsubscribe_error.html', error='Поиск не найден'), 404
        
    except Exception as e:
        return render_template('unsubscribe_error.html', error='Недействительная ссылка'), 400

'''

# Delete first incorrect endpoint (lines 16209-16292, 0-indexed: 16208-16291)
# Keep lines before 16208
new_lines = lines[:16208]

# Add correct endpoints
new_lines.extend(correct_endpoints.split('\n'))
new_lines.append('\n')

# Skip lines 16208-16291 (first incorrect endpoint)
# Continue from line 16292 (0-indexed: 16291)
new_lines.extend(lines[16292:16385])

# Skip lines 16386-16462 (second incorrect endpoint, 0-indexed: 16385-16461)
# Continue from line 16463 (0-indexed: 16462)
new_lines.extend(lines[16462:])

# Write back
with open('app.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("✅ Successfully replaced incorrect endpoints with correct ones")
print("   - Deleted: POST /api/user/saved-search/<id>/alert-settings")
print("   - Deleted: GET /api/user/saved-searches/with-alerts")
print("   - Added: GET /api/user/alert-settings")
print("   - Added: POST /api/user/alert-settings")
print("   - Added: GET /api/user/unsubscribe/<token>")
