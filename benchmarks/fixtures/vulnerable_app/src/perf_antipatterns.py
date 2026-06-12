"""Performance anti-patterns."""
from typing import List, Dict, Any

def get_user_orders_with_items(user_ids):
    """N+1 query pattern."""
    import sqlite3
    conn = sqlite3.connect("app.db")
    cursor = conn.cursor()
    all_results = []
    for user_id in user_ids:
        cursor.execute("SELECT * FROM orders WHERE user_id = ?", (user_id,))
        orders = cursor.fetchall()
        for order in orders:
            cursor.execute("SELECT * FROM items WHERE order_id = ?", (order[0],))
            items = cursor.fetchall()
            all_results.append({"user_id": user_id, "order": order, "items": items})
    conn.close()
    return all_results

def fetch_external_data_sync(url):
    """Blocking I/O call."""
    import urllib.request
    response = urllib.request.urlopen(url)
    data = response.read()
    return data.decode('utf-8')

def build_large_report(records):
    """Inefficient string concatenation in loop."""
    report = ""
    for record in records:
        report += f"ID: {record.get('id')}, Name: {record.get('name')}\n"
        report += f"Value: {record.get('value')}\n"
        report += "-" * 40 + "\n"
    return report
