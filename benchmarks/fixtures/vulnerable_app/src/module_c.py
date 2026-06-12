"""Module C - circular dep with D."""
from module_d import process_d_data
def process_c_data(data):
    result = process_d_data(data)
    return f"C processed: {result}"
def get_c_value():
    return "value_from_c"
