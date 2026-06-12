"""High-complexity functions for benchmarking."""
from typing import Optional, List, Dict, Any

def process_order(order):
    """Cyclomatic ~22."""
    if not order:
        return {"status": "error", "message": "Empty order"}
    items = order.get("items", [])
    customer = order.get("customer", {})
    payment = order.get("payment", {})
    if not items:
        return {"status": "error", "message": "No items"}
    if not customer:
        return {"status": "error", "message": "No customer"}
    if not payment:
        return {"status": "error", "message": "No payment"}
    for item in items:
        if not item.get("sku"):
            return {"status": "error", "message": "Missing SKU"}
        if item.get("quantity", 0) <= 0:
            return {"status": "error", "message": "Invalid quantity"}
        if item.get("price", 0) < 0:
            return {"status": "error", "message": "Invalid price"}
    subtotal = sum(i.get("price", 0) * i.get("quantity", 1) for i in items)
    if subtotal > 1000:
        discount = subtotal * 0.1
    elif subtotal > 500:
        discount = subtotal * 0.05
    elif subtotal > 100:
        discount = subtotal * 0.02
    else:
        discount = 0
    region = customer.get("region", "")
    if region == "CA":
        tax_rate = 0.0975
    elif region == "NY":
        tax_rate = 0.08875
    elif region == "TX":
        tax_rate = 0.0625
    elif region == "WA":
        tax_rate = 0.096
    elif region == "FL":
        tax_rate = 0.06
    else:
        tax_rate = 0.07
    tax = subtotal * tax_rate
    if customer.get("membership") == "premium":
        shipping = 0
    elif subtotal > 75:
        shipping = 0
    elif order.get("shipping_method") == "express":
        shipping = 25.99
    elif order.get("shipping_method") == "overnight":
        shipping = 45.99
    else:
        shipping = 9.99
    pay_type = payment.get("type", "")
    if pay_type == "credit_card":
        if not payment.get("card_number"):
            return {"status": "error", "message": "Missing card number"}
    elif pay_type == "paypal":
        if not payment.get("paypal_email"):
            return {"status": "error", "message": "Missing PayPal email"}
    elif pay_type == "bank_transfer":
        if not payment.get("routing_number"):
            return {"status": "error", "message": "Missing routing number"}
    else:
        return {"status": "error", "message": "Unsupported payment"}
    total = subtotal - discount + tax + shipping
    return {"status": "success", "total": total}

def evaluate_feature_flags(user, flags):
    """Cyclomatic ~18."""
    result = {}
    for flag_name, flag_config in flags.items():
        if not flag_config.get("enabled", True):
            result[flag_name] = False
            continue
        rollout = flag_config.get("rollout_percentage", 100)
        if rollout < 100:
            if hash(user.get("id", "")) % 100 >= rollout:
                result[flag_name] = False
                continue
        segments = flag_config.get("segments", [])
        if segments:
            if user.get("segment", "") not in segments:
                result[flag_name] = False
                continue
        regions = flag_config.get("regions", [])
        if regions:
            if user.get("region", "") not in regions:
                result[flag_name] = False
                continue
        devices = flag_config.get("devices", [])
        if devices:
            if user.get("device", "") not in devices:
                result[flag_name] = False
                continue
        min_version = flag_config.get("min_version")
        if min_version:
            if user.get("app_version", "0.0.0") < min_version:
                result[flag_name] = False
                continue
        exclude_users = flag_config.get("exclude_users", [])
        if user.get("id") in exclude_users:
            result[flag_name] = False
            continue
        result[flag_name] = True
    return result

def validate_registration(data):
    """Cyclomatic ~27."""
    errors = []
    username = data.get("username", "")
    if not username:
        errors.append("Username required")
    elif len(username) < 3:
        errors.append("Username too short")
    elif len(username) > 30:
        errors.append("Username too long")
    elif not username[0].isalpha():
        errors.append("Username must start with letter")
    elif not all(c.isalnum() or c == '_' for c in username):
        errors.append("Username invalid chars")
    email = data.get("email", "")
    if not email:
        errors.append("Email required")
    elif '@' not in email:
        errors.append("Invalid email")
    elif email.count('@') > 1:
        errors.append("Invalid email")
    else:
        local, domain = email.split('@', 1)
        if not local:
            errors.append("Invalid email")
        elif not domain:
            errors.append("Invalid email")
        elif '.' not in domain:
            errors.append("Invalid email domain")
    password = data.get("password", "")
    if not password:
        errors.append("Password required")
    elif len(password) < 8:
        errors.append("Password too short")
    else:
        if not any(c.isupper() for c in password):
            errors.append("Need uppercase")
        if not any(c.islower() for c in password):
            errors.append("Need lowercase")
        if not any(c.isdigit() for c in password):
            errors.append("Need digit")
        if not any(c in "!@#$%^&*" for c in password):
            errors.append("Need special char")
    age = data.get("age")
    if age is None:
        errors.append("Age required")
    elif not isinstance(age, int):
        errors.append("Age must be number")
    elif age < 13:
        errors.append("Must be 13+")
    elif age > 150:
        errors.append("Invalid age")
    if not data.get("terms_accepted"):
        errors.append("Must accept terms")
    if not data.get("privacy_accepted"):
        errors.append("Must accept privacy")
    return errors

def handle_http_response(status_code, headers, body):
    """Cyclomatic ~20."""
    result = {"should_retry": False, "action": ""}
    if 200 <= status_code < 300:
        result["action"] = "success"
        if status_code == 201:
            result["action"] = "created"
        elif status_code == 204:
            result["action"] = "no_content"
    elif 300 <= status_code < 400:
        if headers.get("Location"):
            result["action"] = "redirect"
            if status_code == 301:
                result["redirect_type"] = "permanent"
            elif status_code == 302:
                result["redirect_type"] = "temporary"
        else:
            result["action"] = "redirect_no_location"
    elif status_code == 400:
        result["action"] = "bad_request"
    elif status_code == 401:
        result["action"] = "unauthorized"
        result["should_retry"] = True
    elif status_code == 403:
        result["action"] = "forbidden"
    elif status_code == 404:
        result["action"] = "not_found"
    elif status_code == 429:
        result["action"] = "rate_limited"
        result["should_retry"] = True
    elif 500 <= status_code < 600:
        result["should_retry"] = True
        if status_code == 500:
            result["action"] = "server_error"
        elif status_code == 502:
            result["action"] = "bad_gateway"
        elif status_code == 503:
            result["action"] = "service_unavailable"
        else:
            result["action"] = "server_error"
    return result

def transform_record(record, schema, options=None):
    """Cyclomatic ~24."""
    if options is None:
        options = {}
    result = {}
    errors = []
    for field_name, field_spec in schema.items():
        value = record.get(field_name)
        if value is None:
            if field_spec.get("required", False):
                default = field_spec.get("default")
                if default is not None:
                    result[field_name] = default
                else:
                    errors.append(f"Missing: {field_name}")
            continue
        field_type = field_spec.get("type", "string")
        if field_type == "string":
            if isinstance(value, str):
                result[field_name] = value.strip()
            else:
                result[field_name] = str(value)
        elif field_type == "integer":
            try:
                int_val = int(value)
                min_val = field_spec.get("minimum")
                max_val = field_spec.get("maximum")
                if min_val is not None and int_val < min_val:
                    errors.append(f"{field_name} below min")
                elif max_val is not None and int_val > max_val:
                    errors.append(f"{field_name} above max")
                else:
                    result[field_name] = int_val
            except (ValueError, TypeError):
                errors.append(f"{field_name} not integer")
        elif field_type == "boolean":
            if isinstance(value, bool):
                result[field_name] = value
            elif isinstance(value, str):
                if value.lower() in ("true", "1", "yes"):
                    result[field_name] = True
                elif value.lower() in ("false", "0", "no"):
                    result[field_name] = False
                else:
                    errors.append(f"{field_name} not boolean")
            else:
                result[field_name] = bool(value)
        elif field_type == "enum":
            allowed = field_spec.get("values", [])
            if value in allowed:
                result[field_name] = value
            else:
                errors.append(f"{field_name} not in enum")
    if errors:
        result["_errors"] = errors
    return result
