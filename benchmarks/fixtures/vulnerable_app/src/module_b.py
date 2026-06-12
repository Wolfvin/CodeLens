"""Module B - circular dep with A."""
from module_a import get_a_value
def process_b_data(data):
    a_val = get_a_value()
    return f"B processed: {data} + {a_val}"
def get_b_value():
    return "value_from_b"
