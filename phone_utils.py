"""
Phone number utilities for consistent formatting and normalization across the application.

Canonical phone format in database: +7-XXX-XXX-XX-XX
PhoneVerification uses raw digits: 79XXXXXXXXX (for consistency with SMS API)
"""

def normalize_phone(phone):
    """
    Normalize phone to digits-only format: 79XXXXXXXXX
    
    Args:
        phone (str): Phone in any format
        
    Returns:
        str: Normalized phone (digits only, 11 digits starting with 7)
        
    Raises:
        ValueError: If phone format is invalid
    """
    # Remove all non-digits
    phone_clean = ''.join(filter(str.isdigit, phone))
    
    # Add +7 prefix if needed
    if phone_clean.startswith('8'):
        phone_clean = '7' + phone_clean[1:]
    elif phone_clean.startswith('9'):
        phone_clean = '7' + phone_clean
    
    # Validate: must be exactly 11 digits starting with 7
    if len(phone_clean) != 11 or not phone_clean.startswith('7'):
        raise ValueError(f'Неверный формат номера телефона: {phone}')
    
    return phone_clean


def format_phone_for_db(phone):
    """
    Format phone for database storage in canonical format: +7-XXX-XXX-XX-XX
    
    Args:
        phone (str): Phone in any format
        
    Returns:
        str: Formatted phone in canonical format
        
    Raises:
        ValueError: If phone format is invalid
    """
    phone_digits = normalize_phone(phone)  # Will raise ValueError if invalid
    
    # Format: +7-XXX-XXX-XX-XX
    return f"+7-{phone_digits[1:4]}-{phone_digits[4:7]}-{phone_digits[7:9]}-{phone_digits[9:11]}"


def format_phone_for_display(phone):
    """
    Format phone for user display: +7 (XXX) XXX-XX-XX
    
    Args:
        phone (str): Phone in any format (from DB or input)
        
    Returns:
        str: Formatted phone for display
    """
    try:
        phone_digits = normalize_phone(phone)
        return f"+7 ({phone_digits[1:4]}) {phone_digits[4:7]}-{phone_digits[7:9]}-{phone_digits[9:11]}"
    except ValueError:
        # If normalization fails, return original
        return phone


def get_sql_phone_normalization_filter(model_phone_column, phone_input):
    """
    Get SQLAlchemy filter for finding phones with normalization.
    
    This handles the fact that database stores phones as "+7-XXX-XXX-XX-XX"
    while queries may come in various formats.
    
    Args:
        model_phone_column: SQLAlchemy column (e.g., User.phone)
        phone_input (str): Phone number to search for (any format)
        
    Returns:
        SQLAlchemy filter expression
        
    Example:
        from sqlalchemy import func
        filter_expr = get_sql_phone_normalization_filter(User.phone, "+79521234567")
        user = User.query.filter(filter_expr).first()
    """
    from sqlalchemy import func
    
    phone_digits = normalize_phone(phone_input)  # Will raise ValueError if invalid
    
    # SQL: REPLACE(REPLACE(REPLACE(phone, '-', ''), ' ', ''), '+', '') = phone_digits
    return func.replace(
        func.replace(
            func.replace(model_phone_column, '-', ''),
            ' ', ''
        ),
        '+', ''
    ) == phone_digits
