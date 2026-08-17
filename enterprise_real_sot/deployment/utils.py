from typing import Dict, Any

def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively merges override dictionary into base dictionary.
    Overwrites atomic values and merges nested dictionaries.
    """
    # Create a shallow copy of the base dictionary so the original base object remains unmutated.
    merged = base.copy()
    for key, value in override.items():
        # Check if the key exists in both dictionaries and both values are sub-dictionaries.
        # If so, recursively merge sub-dictionaries to retain nested configuration keys.
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            # Overwrite scalar values (strings, numbers, lists) with the override dictionary's value.
            merged[key] = value
    return merged

