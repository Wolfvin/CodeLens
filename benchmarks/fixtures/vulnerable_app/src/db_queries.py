"""Database query module - SQL injection vulnerabilities."""
import sqlite3
import os

def get_user_by_id(user_id):
    """SQL INJECTION (1) - f-string in query."""
    conn = sqlite3.connect("app.db")
    cursor = conn.cursor()
    query = f"SELECT * FROM users WHERE id = {user_id}"
    cursor.execute(query)
    return cursor.fetchone()

def search_users(search_term):
    """SQL INJECTION (2) - string concat in query."""
    conn = sqlite3.connect("app.db")
    cursor = conn.cursor()
    query = "SELECT * FROM users WHERE name LIKE '%" + search_term + "%'"
    cursor.execute(query)
    return cursor.fetchall()

def filter_orders(status, order_by):
    """SQL INJECTION (3) - f-string in query."""
    conn = sqlite3.connect("app.db")
    cursor = conn.cursor()
    query = f"SELECT * FROM orders WHERE status = '{status}' ORDER BY {order_by}"
    cursor.execute(query)
    return cursor.fetchall()

def get_user_safe(user_id):
    """Safe parameterized query - NOT vulnerable."""
    conn = sqlite3.connect("app.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    return cursor.fetchone()
