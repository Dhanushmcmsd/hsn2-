from __future__ import annotations
import re
from typing import List


def normalize_product_description(text: str) -> str:
    """
    Normalize product description by:
    - Converting to lowercase
    - Expanding common abbreviations
    - Cleaning up formatting
    - Removing extra spaces
    """
    if not text:
        return ""
    
    # Convert to lowercase
    text = text.lower()
    
    # Expand common abbreviations
    abbreviations = {
        'btrm': 'bathroom',
        'clnr': 'cleaner',
        'dtgnt': 'detergent',
        'shamp': 'shampoo',
        'cond': 'conditioner',
        'cookis': 'cookies',
        'cashw': 'cashew',
        'jasmne': 'jasmine',
        'choc': 'chocolate',
        'van': 'vanilla',
        'strbry': 'strawberry',
        'rasbry': 'raspberry',
        'bluebry': 'blueberry',
        'blkbry': 'blackberry',
        'pstr': 'pasta',
        'nood': 'noodle',
        'sauc': 'sauce',
        'ketch': 'ketchup',
        'must': 'mustard',
        'mayo': 'mayonnaise',
        'yog': 'yogurt',
        'chee': 'cheese',
        'butr': 'butter',
        'marg': 'margarine',
        'vin': 'vinegar',
        'jam': 'jam',
        'jelly': 'jelly',
        'marm': 'marmalade',
        'pick': 'pickle',
        'sug': 'sugar',
        'cann': 'canned',
        'bott': 'bottled',
        'cart': 'carton',
        'sach': 'sachet',
        'prem': 'premium',
        'org': 'organic',
        'nat': 'natural',
        'imp': 'imported',
        'loc': 'local',
        'dom': 'domestic',
        'froz': 'frozen',
        'disinftnt': 'disinfectant',
        'btrm': 'bathroom',
        'florl': 'floral',
        'shavng': 'shaving',
        'razr': 'razor',
        'wmn': 'women',
        'sc': 'school',
        'mr': 'maroon',
        'dl': 'ladies',
        'pck': 'pack',
        'pkt': 'packet',
        't.brush': 'toothbrush',
        'puja': 'pooja',
        'esl': 'erasable',
        'vannila': 'vanilla',
        'dubar': 'dubar',
        'nc': 'nice',
        'digestve': 'digestive',
        'iodised': 'iodized',
        'milkrunch': 'milk crunch',
        'safai': 'safai',
        'bigblister': 'big blister',
    }
    
    # Replace abbreviations
    words = text.split()
    expanded_words = []
    for word in words:
        # Remove punctuation at end
        clean_word = word.rstrip('.,')
        expanded_words.append(abbreviations.get(clean_word, word))
    
    text = ' '.join(expanded_words)
    
    # Clean up formatting
    text = re.sub(r'\s+', ' ', text)  # Multiple spaces to single
    text = re.sub(r'\s*[\+\&]\s*', ' ', text)  # Remove + and & with spaces
    text = text.strip()
    
    return text


def extract_pack_size(text: str) -> str:
    """
    Extract pack size information from product description.
    Returns the size part or empty string if not found.
    """
    # Common size patterns - capture the full size including number
    size_patterns = [
        r'\b(\d+(?:\.\d+)?\s*(?:g|kg|ml|l|ltr|pcs|pc|pieces|piece|pack|pkt|sachet|tablet|capsule|strip|sheet|roll|tube|jar|can|tin|bottle|pouch|box|set|gm|gram|litre|liter|no|nos|unit|mg|oz|lb))\b',
    ]
    
    text_lower = text.lower()
    for pattern in size_patterns:
        matches = re.findall(pattern, text_lower, re.IGNORECASE)
        if matches:
            return ' '.join(matches)
    
    return ""