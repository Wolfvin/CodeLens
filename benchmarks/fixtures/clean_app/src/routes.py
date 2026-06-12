"""Clean routes - proper logging, no debug leaks."""
import logging
from typing import Dict, Any
logger = logging.getLogger(__name__)

def handle_request(request: Dict[str, Any]) -> Dict[str, Any]:
    path = request.get("path", "")
    method = request.get("method", "GET")
    logger.debug("Received request: %s %s", method, path)
    if path == "/api/users":
        return {"status": "ok", "data": get_users()}
    elif path == "/api/orders":
        return {"status": "ok", "data": get_orders()}
    elif path == "/api/health":
        return {"status": "ok", "health": "healthy"}
    return {"status": "not_found", "message": f"Path {path} not found"}

def get_users():
    return [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]

def get_orders():
    return [{"id": 1, "total": 99.99}, {"id": 2, "total": 49.99}]

def process_payment(payment_data: Dict[str, Any]) -> Dict[str, Any]:
    amount = payment_data.get("amount", 0)
    if amount <= 0:
        return {"status": "error", "message": "Invalid amount"}
    return {"status": "success", "amount": amount}
