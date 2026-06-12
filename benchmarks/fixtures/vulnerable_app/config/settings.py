"""Configuration - hardcoded secrets (SAFE PLACEHOLDERS for benchmark testing)."""
import os

# SECRET 1: AWS API Key (placeholder)
AWS_ACCESS_KEY_ID = "AKIAEXAMPLEPLACEHOLDER"
# SECRET 2: AWS Secret Key (placeholder)
AWS_SECRET_ACCESS_KEY = "EXAMPLEPLACEHOLDERSECRETKEY1234567890ABCD"
# SECRET 3: Database password (placeholder)
DATABASE_URL = "postgresql://admin:ExamplePlaceholder123@db.example.com:5432/production"
# SECRET 4: Stripe API key (placeholder)
STRIPE_API_KEY = "sk_test_PLACEHOLDER_EXAMPLE_KEY_NOT_REAL"
# SECRET 5: JWT secret (placeholder)
JWT_SECRET = "example-placeholder-jwt-key-for-testing-only"

def get_database_config():
    return {"url": DATABASE_URL, "pool_size": 10}

def get_stripe_config():
    return {"api_key": STRIPE_API_KEY, "currency": "usd"}
