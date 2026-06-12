"""Module A - circular dep with B."""
from module_b import process_b_data
def process_a_data(data):
    result = process_b_data(data)
    return f"A processed: {result}"
def get_a_value():
    return "value_from_a"
