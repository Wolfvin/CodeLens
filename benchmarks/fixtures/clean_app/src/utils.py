"""Clean utilities - no dead code, low complexity."""
from typing import List, Optional, Dict, Any

def format_text(text: str, width: int = 80) -> str:
    import textwrap
    return textwrap.fill(text, width=width)

def process_data(data: List[int]) -> Optional[int]:
    if not data:
        return None
    return sum(data)

def validate_input(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    return str(value)

class DataProcessor:
    def __init__(self, source_name: str):
        self.source_name = source_name
        self._cache = {}
    def process(self, data):
        key = str(data)
        if key not in self._cache:
            self._cache[key] = self._transform(data)
        return self._cache[key]
    def _transform(self, data):
        if isinstance(data, str):
            return data.upper()
        if isinstance(data, (list, tuple)):
            return [self._transform(item) for item in data]
        return data
    def clear_cache(self):
        self._cache.clear()

def calculate_discount(subtotal: float, tier: str = "basic") -> float:
    rates = {"basic": 0.0, "silver": 0.05, "gold": 0.10, "platinum": 0.15}
    return subtotal * rates.get(tier, 0.0)

def merge_configs(base: Dict, override: Dict) -> Dict:
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_configs(result[key], value)
        else:
            result[key] = value
    return result
