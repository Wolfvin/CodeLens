"""Module D - circular dep with C."""
from module_c import get_c_value
def process_d_data(data):
    c_val = get_c_value()
    return f"D processed: {data} + {c_val}"
def get_d_value():
    return "value_from_d"
