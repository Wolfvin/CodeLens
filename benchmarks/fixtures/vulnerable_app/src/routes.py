"""Routes with debug leaks."""
from typing import Dict, Any

def handle_request(request):
    """Handle request - has debug print statements."""
    # DEBUG LEAK 1: print statement
    print(f"Received request: {request}")
    path = request.get("path", "")
    method = request.get("method", "GET")
    if path == "/api/users":
        users = get_users()
        # DEBUG LEAK 2: print statement
        print(f"Users found: {len(users)}")
        return {"status": "ok", "data": users}
    elif path == "/api/orders":
        orders = get_orders()
        return {"status": "ok", "data": orders}
    elif path == "/api/health":
        return {"status": "ok", "health": "healthy"}
    return {"status": "not_found", "message": f"Path {path} not found"}

def get_users():
    users = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
    return users

def get_orders():
    # DEBUG LEAK 3: debugger statement
    import pdb; pdb.set_trace()
    orders = [{"id": 1, "total": 99.99}, {"id": 2, "total": 49.99}]
    return orders

def process_payment(payment_data):
    # DEBUG LEAK 4: TODO/FIXME markers
    # TODO: Implement proper payment validation
    # FIXME: This is a placeholder
    amount = payment_data.get("amount", 0)
    return {"status": "success", "amount": amount}
