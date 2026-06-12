"""Clean app main - calls all functions, no dead code."""
from src.db_queries import get_user_by_id, search_users, create_user, delete_user
from src.utils import format_text, process_data, validate_input, DataProcessor, calculate_discount, merge_configs
from src.system_ops import ping_host, run_backup, list_directory, run_git_status
from config.settings import get_aws_credentials, get_database_url, get_stripe_config, get_jwt_config, is_debug_mode
import logging
logger = logging.getLogger(__name__)

def main():
    user = get_user_by_id(1)
    users = search_users("alice")
    new_id = create_user("Charlie", "charlie@example.com")
    deleted = delete_user(2)
    formatted = format_text("Hello world", width=40)
    total = process_data([1, 2, 3, 4, 5])
    validated = validate_input(42)
    processor = DataProcessor("test_source")
    result = processor.process("test data")
    processor.clear_cache()
    discount = calculate_discount(100.0, "gold")
    merged = merge_configs({"a": 1}, {"b": 2})
    status = ping_host("localhost")
    backup = run_backup("/data")
    files = list_directory("/tmp")
    git_out = run_git_status("/repo")
    aws = get_aws_credentials()
    db_url = get_database_url()
    stripe = get_stripe_config()
    jwt = get_jwt_config()
    debug = is_debug_mode()
    logger.info("Application started successfully")
    return {"user": user, "total": total, "discount": discount}

if __name__ == "__main__":
    main()
