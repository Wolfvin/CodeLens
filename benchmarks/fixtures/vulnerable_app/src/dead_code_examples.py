"""Dead code examples - various types of unused/unreachable code."""
import os
import sys
from typing import List, Optional

# DEAD CODE 1: Unused import
import json

# DEAD CODE 2: Unused variable
UNUSED_GLOBAL_CONFIG = {"debug": True, "verbose": False}

def process_data(data):
    """Contains unreachable code after return."""
    if not data:
        return None
    result = sum(data)
    return result
    # DEAD CODE 3: Unreachable after return
    print("This never executes")
    extra = result * 2
    return extra

# DEAD CODE 4: Unused function
def old_formatter(text, width=80):
    """Legacy formatter - replaced by new_formatter."""
    lines = text.split('\n')
    formatted = []
    for line in lines:
        while len(line) > width:
            formatted.append(line[:width])
            line = line[width:]
        formatted.append(line)
    return '\n'.join(formatted)

# DEAD CODE 5: Unused function
def deprecated_api_call(endpoint, params):
    """Deprecated API - migrated to v2."""
    import urllib.request
    url = f"https://api.example.com/v1/{endpoint}"
    response = urllib.request.urlopen(url)
    return response.read()

# DEAD CODE 6: Unused class
class OldDataProcessor:
    """Legacy processor - replaced by DataPipeline."""
    def __init__(self, source):
        self.source = source
    def run(self):
        data = self.source.read()
        return data.upper()

def new_formatter(text, width=80):
    """Modern formatter - replaces old_formatter."""
    import textwrap
    return textwrap.fill(text, width=width)

def main():
    """Main - only calls new_formatter."""
    data = [1, 2, 3, 4, 5]
    result = process_data(data)
    text = "Hello world"
    formatted = new_formatter(text)
    print(formatted)
    return result

# DEAD CODE 7: Unused variable
UNUSED_CACHE = {}

# DEAD CODE 8: Unused function
def unused_helper(x, y):
    """Nobody uses this."""
    return x + y

# DEAD CODE 9: Unused import
from collections import OrderedDict

# DEAD CODE 10: Unreachable code
def validate_input(value):
    """Validate input values."""
    if isinstance(value, str):
        return value.strip()
    elif isinstance(value, int):
        return value
    elif isinstance(value, float):
        return value
    else:
        return str(value)
        print("never reached")

if __name__ == "__main__":
    main()
