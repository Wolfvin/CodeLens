"""Clean config - uses environment variables."""
import os

def get_aws_credentials():
    return {"access_key_id": os.environ.get("AWS_ACCESS_KEY_ID", ""),
            "secret_access_key": os.environ.get("AWS_SECRET_ACCESS_KEY", "")}

def get_database_url():
    return os.environ.get("DATABASE_URL", "sqlite:///default.db")

def get_stripe_config():
    return {"api_key": os.environ.get("STRIPE_API_KEY", ""), "currency": "usd"}

def get_jwt_config():
    return {"secret": os.environ.get("JWT_SECRET", ""), "algorithm": "HS256", "expiry_hours": 24}

def is_debug_mode():
    return os.environ.get("DEBUG", "false").lower() == "true"
