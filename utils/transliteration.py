"""
Unified transliteration utilities for creating SEO-friendly slugs
Used across the entire application and all import scripts
"""

import re


def create_slug(name):
    """
    Base transliteration function - converts Russian text to Latin slug WITHOUT removing prefixes
    
    Args:
        name (str): Name in Russian or mixed text
        
    Returns:
        str: Transliterated slug in Latin characters (lowercase, hyphen-separated)
        
    Examples:
        >>> create_slug("ЖК Лестория")
        'zhk-lestoriya'
        >>> create_slug("СЗ КАСКАД")
        'sz-kaskad'
        >>> create_slug("СПЕЦИАЛИЗИРОВАННЫЙ ЗАСТРОЙЩИК КОРОНА")
        'spetsializirovannyy-zastroyschik-korona'
    
    Note:
        This is the BASE function - it does NOT remove "ЖК" or other prefixes.
        Use create_complex_slug() for residential complexes to remove "ЖК" prefix.
        Use create_developer_slug() for developers (same as create_slug).
    """
    if not name:
        return "unknown"
    
    # Transliteration table for Russian to Latin (BGN/PCGN romanization)
    translit_map = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
        # Uppercase variants
        'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Е': 'E', 'Ё': 'Yo',
        'Ж': 'Zh', 'З': 'Z', 'И': 'I', 'Й': 'Y', 'К': 'K', 'Л': 'L', 'М': 'M',
        'Н': 'N', 'О': 'O', 'П': 'P', 'Р': 'R', 'С': 'S', 'Т': 'T', 'У': 'U',
        'Ф': 'F', 'Х': 'Kh', 'Ц': 'Ts', 'Ч': 'Ch', 'Ш': 'Sh', 'Щ': 'Sch',
        'Ъ': '', 'Ы': 'Y', 'Ь': '', 'Э': 'E', 'Ю': 'Yu', 'Я': 'Ya'
    }
    
    # Remove quotes only (NOT "ЖК" prefix - that's handled in create_complex_slug)
    name = re.sub(r'["\']', '', name)
    
    # Transliterate Cyrillic to Latin
    slug = ''
    for char in name:
        if char in translit_map:
            slug += translit_map[char]
        else:
            slug += char
    
    # Clean up: remove special characters except spaces and hyphens
    slug = re.sub(r'[^\w\s-]', '', slug)
    # Replace spaces/multiple hyphens with single hyphen
    slug = re.sub(r'[-\s]+', '-', slug)
    
    return slug.lower().strip('-')


def create_developer_slug(name):
    """
    Create slug specifically for developer names
    Alias for create_slug() for clarity
    """
    return create_slug(name)


def create_complex_slug(name):
    """
    Create slug specifically for residential complex names
    Removes "ЖК" prefix automatically
    
    Args:
        name (str): Complex name in Russian (may include "ЖК" prefix)
        
    Returns:
        str: Transliterated slug WITHOUT "ЖК" prefix
        
    Examples:
        >>> create_complex_slug("ЖК Лестория")
        'lestoriya'
        >>> create_complex_slug("ЖК 'Солнечный'")
        'solnechnyy'
    """
    if not name:
        return "unknown"
    
    # Remove "ЖК" prefix and quotes before transliteration
    name = re.sub(r'^ЖК\s*["\']?', '', name, flags=re.IGNORECASE)
    
    # Use base create_slug for transliteration (without prefix removal)
    return create_slug(name)
