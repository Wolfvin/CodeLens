"""
Entrypoints Mapping Engine for CodeLens — v3
Maps all execution entry points in the codebase — "Where does this app even start?"

Answers: "What are all the ways this application can be triggered?"
Answers: "Show me every HTTP endpoint this server exposes."
Answers: "What background workers and cron jobs exist?"

Architecture:
- Scans source files for known entrypoint patterns across multiple frameworks
- Extracts metadata (HTTP method, path, handler name, schedule, etc.)
- Builds a lightweight execution graph showing entrypoint → function call chains
- Categorizes entrypoints into 8 types: main, http_handler, event_handler,
  cli_command, cron_job, worker, module_export, test_entry

Each entrypoint includes: type, metadata (method, path, handler, schedule, etc.),
file, line, and optionally a call chain to downstream functions.
"""

import os
import re
from typing import Dict, List, Any, Optional, Set, Tuple
from collections import defaultdict
from utils import DEFAULT_IGNORE_DIRS, logger


# ─── Configuration ─────────────────────────────────────────────

SOURCE_EXTENSIONS = {
    ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".py", ".rs", ".vue", ".svelte",
    ".cc", ".cpp", ".cxx", ".c", ".h", ".hpp", ".hxx",
    ".go", ".dart",
}

# ─── Entrypoint Pattern Definitions ───────────────────────────

ENTRYPOINT_PATTERNS = {
    # ═══════════════════════════════════════════════════════════
    # 1. MAIN — Application entry points
    # ═══════════════════════════════════════════════════════════
    "main": {
        "patterns": [
            # Python
            {
                "regex": r'if\s+__name__\s*==\s*["\']__main__["\']\s*:',
                "language": {".py"},
                "extract": "none",
                "label": "python_main_guard",
            },
            {
                "regex": r'def\s+main\s*\([^)]*\)\s*:',
                "language": {".py"},
                "extract": "handler",
                "handler_group": 1,
                "label": "python_main_fn",
            },
            # JS/TS
            {
                "regex": r'function\s+main\s*\(',
                "language": {".js", ".mjs", ".cjs", ".ts", ".tsx"},
                "extract": "handler",
                "handler_group": 0,
                "label": "js_main_fn",
            },
            {
                "regex": r'(?:const|let|var)\s+main\s*=\s*(?:async\s+)?\(',
                "language": {".js", ".mjs", ".cjs", ".ts", ".tsx"},
                "extract": "handler",
                "handler_group": 0,
                "label": "js_main_arrow",
            },
            # Rust
            {
                "regex": r'fn\s+main\s*\(',
                "language": {".rs"},
                "extract": "handler",
                "handler_group": 0,
                "label": "rust_main_fn",
            },
            # C / C++
            {
                "regex": r'int\s+main\s*\(\s*(?:int\s+argc\s*,\s*char\s*\*\s*argv\[\])?\s*\)',
                "language": {".cc", ".cpp", ".cxx", ".c"},
                "extract": "handler",
                "handler_group": 0,
                "label": "cpp_main_fn",
            },
            {
                "regex": r'int\s+main\s*\(',
                "language": {".cc", ".cpp", ".cxx", ".c"},
                "extract": "handler",
                "handler_group": 0,
                "label": "cpp_main_short",
            },
            # Go
            {
                "regex": r'func\s+main\s*\(\s*\)',
                "language": {".go"},
                "extract": "handler",
                "handler_group": 0,
                "label": "go_main_fn",
            },
            # Dart/Flutter
            {
                "regex": r'(?:void|Future<void>)\s+main\s*\(',
                "language": {".dart"},
                "extract": "handler",
                "handler_group": 0,
                "label": "dart_main_fn",
            },
            # index.ts / index.js as entry (detected by filename)
            {
                "regex": r'export\s+default\s+(?:function\s+)?(\w+)',
                "language": {".js", ".mjs", ".cjs", ".ts", ".tsx"},
                "extract": "handler",
                "handler_group": 1,
                "label": "js_default_export_main",
                "filename_filter": {"index.ts", "index.js", "index.tsx", "main.ts", "main.js"},
            },
        ],
    },

    # ═══════════════════════════════════════════════════════════
    # 2. HTTP HANDLERS — Route handlers
    # ═══════════════════════════════════════════════════════════
    "http_handler": {
        "patterns": [
            # Express.js: app.get/post/put/delete/patch
            {
                "regex": r'(?:app|router|server)\.(get|post|put|delete|patch|head|options|all)\s*\(\s*["\']([^"\']+)["\']',
                "language": {".js", ".mjs", ".cjs", ".ts", ".tsx"},
                "extract": "http_route",
                "method_group": 1,
                "path_group": 2,
                "label": "express_route",
            },
            # Express with route()
            {
                "regex": r'\.route\s*\(\s*["\']([^"\']+)["\']\s*\)\.(get|post|put|delete|patch)\s*\(',
                "language": {".js", ".mjs", ".cjs", ".ts", ".tsx"},
                "extract": "http_route_reverse",
                "method_group": 2,
                "path_group": 1,
                "label": "express_chained_route",
            },
            # Koa router
            {
                "regex": r'(?:router|Router)\.(get|post|put|delete|patch|head|options)\s*\(\s*["\']([^"\']+)["\']',
                "language": {".js", ".mjs", ".cjs", ".ts", ".tsx"},
                "extract": "http_route",
                "method_group": 1,
                "path_group": 2,
                "label": "koa_route",
            },
            # Hono
            {
                "regex": r'(?:app|hone|Hono)\.(get|post|put|delete|patch|head|options)\s*\(\s*["\']([^"\']+)["\']',
                "language": {".js", ".mjs", ".cjs", ".ts", ".tsx"},
                "extract": "http_route",
                "method_group": 1,
                "path_group": 2,
                "label": "hono_route",
            },
            # Fastify
            {
                "regex": r'fastify\.(get|post|put|delete|patch|head|options)\s*\(\s*["\']([^"\']+)["\']',
                "language": {".js", ".mjs", ".cjs", ".ts", ".tsx"},
                "extract": "http_route",
                "method_group": 1,
                "path_group": 2,
                "label": "fastify_route",
            },
            # Flask @app.route
            {
                "regex": r'@app\.route\s*\(\s*["\']([^"\']+)["\'](?:\s*,\s*methods\s*=\s*\[([^\]]+)\])?',
                "language": {".py"},
                "extract": "flask_route",
                "path_group": 1,
                "methods_group": 2,
                "label": "flask_route",
            },
            # FastAPI @app.get/post/etc
            {
                "regex": r'@app\.(get|post|put|delete|patch|head|options)\s*\(\s*["\']([^"\']+)["\']',
                "language": {".py"},
                "extract": "http_route",
                "method_group": 1,
                "path_group": 2,
                "label": "fastapi_route",
            },
            # FastAPI @router.get/post/etc
            {
                "regex": r'@router\.(get|post|put|delete|patch|head|options)\s*\(\s*["\']([^"\']+)["\']',
                "language": {".py"},
                "extract": "http_route",
                "method_group": 1,
                "path_group": 2,
                "label": "fastapi_router_route",
            },
            # Django URL patterns
            {
                "regex": r'path\s*\(\s*["\']([^"\']+)["\']\s*,\s*(\w+)',
                "language": {".py"},
                "extract": "django_path",
                "path_group": 1,
                "handler_group": 2,
                "label": "django_path",
            },
            # Django re_path
            {
                "regex": r're_path\s*\(\s*["\']([^"\']+)["\']\s*,\s*(\w+)',
                "language": {".py"},
                "extract": "django_path",
                "path_group": 1,
                "handler_group": 2,
                "label": "django_re_path",
            },
            # Next.js API route handlers (app directory)
            {
                "regex": r'export\s+async\s+function\s+(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s*\(',
                "language": {".ts", ".tsx", ".js", ".jsx"},
                "extract": "next_api_route",
                "method_group": 1,
                "label": "nextjs_api_handler",
            },
            # Next.js pages API route
            {
                "regex": r'export\s+default\s+(?:async\s+)?function\s+handler\s*\(',
                "language": {".ts", ".tsx", ".js", ".jsx"},
                "extract": "handler_only",
                "handler_group": 0,
                "label": "nextjs_pages_api",
            },
            # Spring Boot @RequestMapping family
            {
                "regex": r'@(?:Get|Post|Put|Delete|Patch|Request)Mapping\s*\(\s*(?:value\s*=\s*)?["\']([^"\']+)["\']',
                "language": {".java"},  # Spring Boot is Java, not Python
                "extract": "spring_route",
                "label": "spring_mapping",
            },
            # Nitro / Nuxt server routes
            {
                "regex": r'(?:export\s+)?default\s+defineEventHandler\s*\(',
                "language": {".ts", ".js"},
                "extract": "handler_only",
                "handler_group": 0,
                "label": "nitro_event_handler",
            },
            # tRPC routers
            {
                "regex": r'\.mutation\s*\(\s*["\']([^"\']+)["\']',
                "language": {".ts", ".tsx"},
                "extract": "trpc_procedure",
                "path_group": 1,
                "label": "trpc_mutation",
            },
            {
                "regex": r'\.query\s*\(\s*["\']([^"\']+)["\']',
                "language": {".ts", ".tsx"},
                "extract": "trpc_procedure",
                "path_group": 1,
                "label": "trpc_query",
            },
            # Go HTTP handlers — net/http
            {
                "regex": r'http\.HandleFunc\s*\(\s*["\']([^"\']+)["\']',
                "language": {".go"},
                "extract": "go_http_route",
                "path_group": 1,
                "label": "go_http_handlefunc",
            },
            {
                "regex": r'http\.Handle\s*\(\s*["\']([^"\']+)["\']',
                "language": {".go"},
                "extract": "go_http_route",
                "path_group": 1,
                "label": "go_http_handle",
            },
            # Go Gin framework
            {
                "regex": r'(?:r|router|engine)\.(?:GET|POST|PUT|DELETE|PATCH)\s*\(\s*["\']([^"\']+)["\']',
                "language": {".go"},
                "extract": "go_gin_route",
                "path_group": 1,
                "label": "go_gin_handler",
            },
            # Go Echo framework
            {
                "regex": r'e\.(?:GET|POST|PUT|DELETE|PATCH)\s*\(\s*["\']([^"\']+)["\']',
                "language": {".go"},
                "extract": "go_echo_route",
                "path_group": 1,
                "label": "go_echo_handler",
            },
            # C++ crow/drogon HTTP handlers
            {
                "regex": r'CROW_ROUTE\s*\([^,]+,\s*["\']([^"\']+)["\']',
                "language": {".cc", ".cpp", ".cxx", ".h", ".hpp"},
                "extract": "cpp_crow_route",
                "path_group": 1,
                "label": "cpp_crow_handler",
            },
            # NestJS @Controller + @Get/@Post/etc
            {
                "regex": r'@(Get|Post|Put|Delete|Patch|Head|Options|All)\s*\(\s*["\']([^"\']*)["\']\s*\)',
                "language": {".ts", ".js", ".tsx"},
                "extract": "nestjs_route",
                "method_group": 1,
                "path_group": 2,
                "label": "nestjs_http_handler",
            },
            # NestJS @Controller with no method path
            {
                "regex": r'@(Get|Post|Put|Delete|Patch|Head|Options|All)\s*\(\s*\)',
                "language": {".ts", ".js", ".tsx"},
                "extract": "nestjs_route",
                "method_group": 1,
                "path_group": None,
                "label": "nestjs_http_handler_no_path",
            },
        ],
    },

    # ═══════════════════════════════════════════════════════════
    # 3. EVENT HANDLERS — Event listeners
    # ═══════════════════════════════════════════════════════════
    "event_handler": {
        "patterns": [
            # DOM addEventListener
            {
                "regex": r'(?:document|window|element)\.addEventListener\s*\(\s*["\'](\w+)["\']',
                "language": {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"},
                "extract": "event_name",
                "event_group": 1,
                "label": "dom_event_listener",
            },
            # .on() event binding
            {
                "regex": r'\.on\s*\(\s*["\'](\w+)["\']',
                "language": {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".py"},
                "extract": "event_name",
                "event_group": 1,
                "label": "on_event_binding",
            },
            # Node.js EventEmitter
            {
                "regex": r'(?:emitter|ee|eventEmitter|this)\.on\s*\(\s*["\']([^"\']+)["\']',
                "language": {".js", ".mjs", ".cjs", ".ts", ".tsx"},
                "extract": "event_name",
                "event_group": 1,
                "label": "node_event_emitter",
            },
            # window.onload
            {
                "regex": r'window\.onload\s*=',
                "language": {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"},
                "extract": "handler_only",
                "handler_group": 0,
                "label": "window_onload",
            },
            # DOMContentLoaded
            {
                "regex": r'addEventListener\s*\(\s*["\']DOMContentLoaded["\']',
                "language": {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"},
                "extract": "event_name",
                "event_group": 0,
                "label": "dom_content_loaded",
            },
            # process.on (Node.js)
            {
                "regex": r'process\.on\s*\(\s*["\']([^"\']+)["\']',
                "language": {".js", ".mjs", ".cjs", ".ts"},
                "extract": "event_name",
                "event_group": 1,
                "label": "node_process_event",
            },
            # Python signal handler
            {
                "regex": r'signal\.signal\s*\(\s*(?:signal\.\w+|SIG\w+)\s*,\s*(\w+)',
                "language": {".py"},
                "extract": "handler_only",
                "handler_group": 1,
                "label": "python_signal_handler",
            },
            # RxJS subscribe
            {
                "regex": r'\.subscribe\s*\(',
                "language": {".js", ".mjs", ".cjs", ".ts", ".tsx"},
                "extract": "handler_only",
                "handler_group": 0,
                "label": "rxjs_subscribe",
            },
            # Vue mounted/lifecycle hooks
            {
                "regex": r'(?:mounted|created|onMounted|onCreated|beforeCreate|beforeMount)\s*\(',
                "language": {".js", ".mjs", ".cjs", ".ts", ".tsx", ".vue"},
                "extract": "handler_only",
                "handler_group": 0,
                "label": "vue_lifecycle",
            },
            # React useEffect
            {
                "regex": r'useEffect\s*\(',
                "language": {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"},
                "extract": "handler_only",
                "handler_group": 0,
                "label": "react_effect",
            },
            # Svelte onMount
            {
                "regex": r'onMount\s*\(',
                "language": {".js", ".mjs", ".cjs", ".ts", ".svelte"},
                "extract": "handler_only",
                "handler_group": 0,
                "label": "svelte_onmount",
            },
        ],
    },

    # ═══════════════════════════════════════════════════════════
    # 4. CLI COMMANDS — Command-line interface definitions
    # ═══════════════════════════════════════════════════════════
    "cli_command": {
        "patterns": [
            # Commander.js
            {
                "regex": r'\.command\s*\(\s*["\']([^"\']+)["\']',
                "language": {".js", ".mjs", ".cjs", ".ts"},
                "extract": "cli_command",
                "command_group": 1,
                "label": "commander_command",
            },
            # Yargs
            {
                "regex": r'yargs\s*\.\s*command\s*\(\s*["\']([^"\']+)["\']',
                "language": {".js", ".mjs", ".cjs", ".ts"},
                "extract": "cli_command",
                "command_group": 1,
                "label": "yargs_command",
            },
            # Python argparse
            {
                "regex": r'add_argument\s*\(\s*["\'](-{1,2}[\w-]+)["\']',
                "language": {".py"},
                "extract": "cli_command",
                "command_group": 1,
                "label": "argparse_argument",
            },
            # Python argparse subparser
            {
                "regex": r'add_subparsers\s*\(\s*(?:.*?)add_parser\s*\(\s*["\']([^"\']+)["\']',
                "language": {".py"},
                "extract": "cli_command",
                "command_group": 1,
                "label": "argparse_subparser",
            },
            # Click @click.command / @click.group
            {
                "regex": r'@click\.(?:command|group)\s*\((?:\s*name\s*=\s*["\']([^"\']+)["\'])?',
                "language": {".py"},
                "extract": "click_command",
                "command_group": 1,
                "label": "click_command",
            },
            # Typer
            {
                "regex": r'app\s*=\s*typer\.Typer\s*\(',
                "language": {".py"},
                "extract": "handler_only",
                "handler_group": 0,
                "label": "typer_app",
            },
            # Rust clap
            {
                "regex": r'#\[derive\((?:Parser|Subcommand|Args)\)\]',
                "language": {".rs"},
                "extract": "handler_only",
                "handler_group": 0,
                "label": "clap_parser",
            },
            # Rust structopt
            {
                "regex": r'#\[derive\((?:StructOpt)\)\]',
                "language": {".rs"},
                "extract": "handler_only",
                "handler_group": 0,
                "label": "structopt_parser",
            },
        ],
    },

    # ═══════════════════════════════════════════════════════════
    # 5. CRON JOBS — Scheduled tasks
    # ═══════════════════════════════════════════════════════════
    "cron_job": {
        "patterns": [
            # node-cron
            {
                "regex": r'cron\.schedule\s*\(\s*["\']([^"\']+)["\']',
                "language": {".js", ".mjs", ".cjs", ".ts"},
                "extract": "cron_schedule",
                "schedule_group": 1,
                "label": "node_cron",
            },
            # node-schedule
            {
                "regex": r'schedule\.scheduleJob\s*\(\s*["\']([^"\']+)["\']',
                "language": {".js", ".mjs", ".cjs", ".ts"},
                "extract": "cron_schedule",
                "schedule_group": 1,
                "label": "node_schedule",
            },
            # setInterval (could be a recurring task)
            {
                "regex": r'setInterval\s*\(\s*(?:async\s+)?(?:function\s+)?(\w+)',
                "language": {".js", ".mjs", ".cjs", ".ts", ".tsx"},
                "extract": "handler_only",
                "handler_group": 1,
                "label": "set_interval",
            },
            # Python APScheduler
            {
                "regex": r'(?:@scheduler\.(?:schedule|cron_job|interval_job)|scheduler\.add_job)\s*\(',
                "language": {".py"},
                "extract": "handler_only",
                "handler_group": 0,
                "label": "apscheduler",
            },
            # Celery beat schedule
            {
                "regex": r'CELERY_BEAT_SCHEDULE\s*=',
                "language": {".py"},
                "extract": "handler_only",
                "handler_group": 0,
                "label": "celery_beat",
            },
            # crontab literals in Python
            {
                "regex": r'["\']((?:\*\s*,?){0,5}(?:\d+|\*)\s+(?:\d+|\*)\s+(?:\d+|\*)\s+(?:\d+|\*)\s+(?:\d+|\*))["\']',
                "language": {".py", ".js", ".mjs", ".cjs", ".ts"},
                "extract": "cron_schedule",
                "schedule_group": 1,
                "label": "cron_literal",
            },
            # Rust cron / tokio-cron-scheduler
            {
                "regex": r'Job::new_async\s*\(\s*["\']([^"\']+)["\']',
                "language": {".rs"},
                "extract": "cron_schedule",
                "schedule_group": 1,
                "label": "rust_cron",
            },
        ],
    },

    # ═══════════════════════════════════════════════════════════
    # 6. WORKERS — Background workers and queue processors
    # ═══════════════════════════════════════════════════════════
    "worker": {
        "patterns": [
            # Worker threads (Node.js)
            {
                "regex": r'new\s+Worker\s*\(\s*["\']([^"\']+)["\']',
                "language": {".js", ".mjs", ".cjs", ".ts"},
                "extract": "worker_file",
                "path_group": 1,
                "label": "node_worker_thread",
            },
            # Bull / BullMQ queue processors
            {
                "regex": r'(?:Queue|FlowProducer)\s*\(\s*["\']([^"\']+)["\']',
                "language": {".js", ".mjs", ".cjs", ".ts"},
                "extract": "queue_name",
                "name_group": 1,
                "label": "bull_queue",
            },
            # BullMQ process
            {
                "regex": r'\.process\s*\(\s*(?:async\s+)?\(',
                "language": {".js", ".mjs", ".cjs", ".ts"},
                "extract": "handler_only",
                "handler_group": 0,
                "label": "bull_processor",
            },
            # Kafka consumers
            {
                "regex": r'(?:Kafka|Consumer)\s*\(\s*(?:\{[^}]*groupId\s*:\s*["\']([^"\']+)["\'])?',
                "language": {".js", ".mjs", ".cjs", ".ts", ".py"},
                "extract": "consumer_group",
                "name_group": 1,
                "label": "kafka_consumer",
            },
            # RabbitMQ consumers
            {
                "regex": r'(?:channel|amqp)\.consume\s*\(\s*["\']([^"\']+)["\']',
                "language": {".js", ".mjs", ".cjs", ".ts", ".py"},
                "extract": "queue_name",
                "name_group": 1,
                "label": "rabbitmq_consumer",
            },
            # Celery @app.task
            {
                "regex": r'@app\.task\s*(?:\([^)]*\))?\s*\ndef\s+(\w+)',
                "language": {".py"},
                "extract": "handler",
                "handler_group": 1,
                "label": "celery_task",
            },
            # Celery @shared_task
            {
                "regex": r'@shared_task\s*(?:\([^)]*\))?\s*\ndef\s+(\w+)',
                "language": {".py"},
                "extract": "handler",
                "handler_group": 1,
                "label": "celery_shared_task",
            },
            # Python threading / multiprocessing
            {
                "regex": r'(?:Thread|Process)\s*\(\s*target\s*=\s*(\w+)',
                "language": {".py"},
                "extract": "handler",
                "handler_group": 1,
                "label": "python_thread",
            },
            # Python asyncio.create_task
            {
                "regex": r'(?:asyncio\.)?create_task\s*\(\s*(\w+)',
                "language": {".py"},
                "extract": "handler",
                "handler_group": 1,
                "label": "asyncio_task",
            },
            # Rust tokio::spawn
            {
                "regex": r'tokio::spawn\s*\(',
                "language": {".rs"},
                "extract": "handler_only",
                "handler_group": 0,
                "label": "tokio_spawn",
            },
            # AWS Lambda handler
            {
                "regex": r'(?:exports\.handler|export\s+(?:async\s+)?function\s+handler)\s*=',
                "language": {".js", ".mjs", ".cjs", ".ts"},
                "extract": "handler_only",
                "handler_group": 0,
                "label": "lambda_handler",
            },
            # GCP Cloud Function
            {
                "regex": r'(?:exports\.\w+|export\s+(?:async\s+)?function\s+\w+)\s*=\s*(?:async\s+)?\(',
                "language": {".js", ".mjs", ".cjs", ".ts"},
                "extract": "handler_only",
                "handler_group": 0,
                "label": "gcp_function",
            },
        ],
    },

    # ═══════════════════════════════════════════════════════════
    # 7. MODULE EXPORTS — Module entry points
    # ═══════════════════════════════════════════════════════════
    "module_export": {
        "patterns": [
            # ES module default export
            {
                "regex": r'export\s+default\s+(?:function\s+)?(\w+)',
                "language": {".js", ".mjs", ".cjs", ".ts", ".tsx"},
                "extract": "handler",
                "handler_group": 1,
                "label": "es_default_export",
            },
            # CommonJS module.exports
            {
                "regex": r'module\.exports\s*=\s*(\w+)',
                "language": {".js", ".mjs", ".cjs", ".ts"},
                "extract": "handler",
                "handler_group": 1,
                "label": "commonjs_export",
            },
            # CommonJS module.exports = { ... }
            {
                "regex": r'module\.exports\s*=\s*\{',
                "language": {".js", ".mjs", ".cjs", ".ts"},
                "extract": "handler_only",
                "handler_group": 0,
                "label": "commonjs_object_export",
            },
            # Rust pub fn that looks like a primary API
            {
                "regex": r'pub\s+(?:async\s+)?fn\s+(\w+)\s*\(',
                "language": {".rs"},
                "extract": "handler",
                "handler_group": 1,
                "label": "rust_pub_fn",
            },
            # Python __all__ export list
            {
                "regex": r'__all__\s*=\s*\[([^\]]+)\]',
                "language": {".py"},
                "extract": "handler_only",
                "handler_group": 0,
                "label": "python_all_export",
            },
        ],
    },

    # ═══════════════════════════════════════════════════════════
    # 8. TEST ENTRIES — Test entry points
    # ═══════════════════════════════════════════════════════════
    "test_entry": {
        "patterns": [
            # Jest / Vitest describe()
            {
                "regex": r'(?:describe|context|suite)\s*\(\s*["\']([^"\']+)["\']',
                "language": {".js", ".mjs", ".cjs", ".ts", ".tsx"},
                "extract": "test_name",
                "name_group": 1,
                "label": "jest_describe",
            },
            # Jest / Vitest it() / test()
            {
                "regex": r'(?:it|test|specify)\s*\(\s*["\']([^"\']+)["\']',
                "language": {".js", ".mjs", ".cjs", ".ts", ".tsx"},
                "extract": "test_name",
                "name_group": 1,
                "label": "jest_it",
            },
            # Python pytest
            {
                "regex": r'def\s+(test_\w+)\s*\(',
                "language": {".py"},
                "extract": "handler",
                "handler_group": 1,
                "label": "pytest_fn",
            },
            # Python unittest
            {
                "regex": r'class\s+(Test\w+)\s*\(\s*(?:unittest\.TestCase|TestCase)\s*\)',
                "language": {".py"},
                "extract": "test_name",
                "name_group": 1,
                "label": "unittest_class",
            },
            # Rust #[test]
            {
                "regex": r'#\[test\]\s*(?:\n\s*#\[.*\]\s*)*\n\s*(?:pub\s+)?(?:async\s+)?fn\s+(\w+)',
                "language": {".rs"},
                "extract": "handler",
                "handler_group": 1,
                "label": "rust_test",
            },
            # Rust #[tokio::test]
            {
                "regex": r'#\[tokio::test\]\s*(?:\n\s*#\[.*\]\s*)*\n\s*(?:pub\s+)?(?:async\s+)?fn\s+(\w+)',
                "language": {".rs"},
                "extract": "handler",
                "handler_group": 1,
                "label": "rust_tokio_test",
            },
            # Rust #[cfg(test)] module
            {
                "regex": r'#\[cfg\(test\)\]\s*\n\s*mod\s+(\w+)',
                "language": {".rs"},
                "extract": "test_name",
                "name_group": 1,
                "label": "rust_test_module",
            },
        ],
    },
}


def map_entrypoints(
    workspace: str,
    entry_type: Optional[str] = None,
    config: Optional[Dict] = None,
    max_files: int = 5000
) -> Dict[str, Any]:
    """
    Map all execution entry points in the codebase.

    Scans for HTTP routes, CLI commands, event handlers, cron jobs,
    background workers, module exports, and test entries.

    Args:
        workspace: Absolute path to workspace
        entry_type: Optional filter: "main", "http_handler", "event_handler",
                   "cli_command", "cron_job", "worker", "module_export", "test_entry"
        config: CodeLens config
        max_files: Maximum number of files to scan (default: 5000)

    Returns:
        Dict with entrypoints, execution graph, stats, and recommendations
    """
    workspace = os.path.abspath(workspace)

    valid_types = {
        "main", "http_handler", "event_handler", "cli_command",
        "cron_job", "worker", "module_export", "test_entry"
    }

    if entry_type and entry_type not in valid_types:
        entry_type = None

    types_to_scan = {entry_type} if entry_type else valid_types

    entrypoints: List[Dict[str, Any]] = []
    files_scanned = 0

    # ─── Phase 1: Scan files for entrypoints ──────────────────
    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
        if '.codelens' in root:
            dirs.clear()
            continue

        for filename in filenames:
            if files_scanned >= max_files:
                break

            ext = os.path.splitext(filename)[1].lower()
            if ext not in SOURCE_EXTENSIONS:
                continue

            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, workspace)

            # v6: Skip config/build files that are NOT real entry points.
            # Files like playwright.config.ts, vitest.config.ts, turbo.json,
            # etc. contain "export default" but are not app entry points.
            config_file_patterns = (
                '.config.', 'config.ts', 'config.js', 'config.mjs',
                'vitest.', 'playwright.', 'jest.', 'eslint.', 'prettier.',
                'tsconfig.', 'turbo.json', '.eslintrc', '.prettierrc',
                'biome.json', 'lint-staged.', 'postcss.config',
                'tailwind.config', 'next.config', 'vite.config',
                'webpack.config', 'rollup.config', 'babel.config',
                'i18n.config', 'i18n.json', 'i18n-unused.config',
                # Additional config/rc file patterns (v6.2)
                '.lintstagedrc', '.babelrc', '.stylelintrc',
                '.commitlintrc', '.huskyrc', '.lintstagedrc.json',
                '.lintstagedrc.js', '.lintstagedrc.cjs',
                'commitlint.', 'husky.', 'stylelint.',
                'jest.config.', 'karma.conf', 'protractor.conf',
                'angular.json', '.browserslistrc', '.editorconfig',
                '.nvmrc', '.npmrc', '.yarnrc', 'lerna.json',
                'nx.json', 'workspace.json', 'tsup.config',
                'esbuild.', 'rollup.', 'terser.config',
                'docker-compose', 'Dockerfile', '.env.',
            )
            is_config_file = any(p in filename for p in config_file_patterns)

            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except IOError:
                continue

            files_scanned += 1

            # Check each requested entrypoint type
            for ep_type in types_to_scan:
                if ep_type not in ENTRYPOINT_PATTERNS:
                    continue

                # v6: Skip config files — they contain "export default" and
                # other patterns but are NOT application entry points.
                if is_config_file:
                    continue

                type_def = ENTRYPOINT_PATTERNS[ep_type]

                for pattern_def in type_def["patterns"]:
                    # Check language filter
                    if ext not in pattern_def.get("language", SOURCE_EXTENSIONS):
                        continue

                    # Check filename filter
                    filename_filter = pattern_def.get("filename_filter")
                    if filename_filter and filename not in filename_filter:
                        continue

                    # Scan for matches
                    file_entrypoints = _extract_entrypoints(
                        content, rel_path, ext, ep_type, pattern_def
                    )
                    entrypoints.extend(file_entrypoints)

    # ─── Phase 2: Deduplicate ─────────────────────────────────
    entrypoints = _deduplicate_entrypoints(entrypoints)

    # ─── Phase 3: Build execution graph ───────────────────────
    execution_graph = _build_execution_graph(workspace, entrypoints)

    # ─── Phase 4: Compute stats ───────────────────────────────
    stats = _compute_stats(entrypoints)

    # ─── Phase 5: Generate recommendations ────────────────────
    recommendations = _generate_recommendations(entrypoints, stats)

    return {
        "status": "ok",
        "workspace": workspace,
        "entry_type_filter": entry_type,
        "stats": stats,
        "entrypoints": entrypoints[:300],  # Cap to avoid explosion
        "execution_graph": execution_graph,
        "recommendations": recommendations,
    }


# ─── Entrypoint Extraction ─────────────────────────────────────

def _extract_entrypoints(
    content: str,
    rel_path: str,
    ext: str,
    ep_type: str,
    pattern_def: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Extract entrypoints from file content based on pattern definition."""
    results = []
    regex = pattern_def["regex"]
    extract_type = pattern_def.get("extract", "handler_only")

    try:
        for match in re.finditer(regex, content):
            line_num = content[:match.start()].count('\n') + 1

            entrypoint = {
                "type": ep_type,
                "file": rel_path,
                "line": line_num,
                "label": pattern_def.get("label", ep_type),
            }

            # Extract metadata based on the pattern type
            if extract_type == "http_route":
                method_group = pattern_def.get("method_group")
                path_group = pattern_def.get("path_group")
                entrypoint["method"] = match.group(method_group).upper() if method_group and match.lastindex is not None and match.lastindex >= method_group else "GET"
                entrypoint["path"] = match.group(path_group) if path_group and match.lastindex is not None and match.lastindex >= path_group else "/"
                entrypoint["handler"] = _find_handler_name(content, line_num, ext)

            elif extract_type == "http_route_reverse":
                method_group = pattern_def.get("method_group")
                path_group = pattern_def.get("path_group")
                entrypoint["method"] = match.group(method_group).upper() if method_group and match.lastindex is not None and match.lastindex >= method_group else "GET"
                entrypoint["path"] = match.group(path_group) if path_group and match.lastindex is not None and match.lastindex >= path_group else "/"
                entrypoint["handler"] = _find_handler_name(content, line_num, ext)

            elif extract_type == "flask_route":
                path_group = pattern_def.get("path_group")
                methods_group = pattern_def.get("methods_group")
                entrypoint["path"] = match.group(path_group) if path_group and match.lastindex is not None and match.lastindex >= path_group else "/"
                if methods_group and match.lastindex is not None and match.lastindex >= methods_group and match.group(methods_group):
                    methods_str = match.group(methods_group)
                    entrypoint["method"] = methods_str.strip().strip("'\"")
                else:
                    entrypoint["method"] = "GET"
                entrypoint["handler"] = _find_handler_after_decorator(content, line_num, ext)

            elif extract_type == "django_path":
                path_group = pattern_def.get("path_group")
                handler_group = pattern_def.get("handler_group")
                entrypoint["path"] = match.group(path_group) if path_group and match.lastindex is not None and match.lastindex >= path_group else "/"
                entrypoint["method"] = "ANY"
                entrypoint["handler"] = match.group(handler_group) if handler_group and match.lastindex is not None and match.lastindex is not None and match.lastindex >= handler_group else "unknown"

            elif extract_type == "next_api_route":
                method_group = pattern_def.get("method_group")
                entrypoint["method"] = match.group(method_group).upper() if method_group and match.lastindex is not None and match.lastindex >= method_group else "GET"
                # Path is derived from file location
                entrypoint["path"] = _path_from_file(rel_path)
                entrypoint["handler"] = match.group(method_group).upper() if method_group else "handler"

            elif extract_type == "trpc_procedure":
                path_group = pattern_def.get("path_group")
                entrypoint["method"] = "MUTATION" if "mutation" in pattern_def.get("label", "") else "QUERY"
                entrypoint["path"] = match.group(path_group) if path_group and match.lastindex is not None and match.lastindex >= path_group else "/"
                entrypoint["handler"] = _find_handler_name(content, line_num, ext)

            elif extract_type == "spring_route":
                path_group = pattern_def.get("path_group")
                entrypoint["method"] = _method_from_spring_label(pattern_def.get("label", ""))
                entrypoint["path"] = match.group(path_group) if path_group and match.lastindex is not None and match.lastindex >= path_group else "/"

            elif extract_type == "event_name":
                event_group = pattern_def.get("event_group")
                entrypoint["event"] = match.group(event_group) if event_group and match.lastindex is not None and match.lastindex >= event_group else "unknown"
                entrypoint["handler"] = _find_handler_name(content, line_num, ext)

            elif extract_type == "cli_command":
                command_group = pattern_def.get("command_group")
                entrypoint["command"] = match.group(command_group) if command_group and match.lastindex is not None and match.lastindex >= command_group else "unknown"

            elif extract_type == "cron_schedule":
                schedule_group = pattern_def.get("schedule_group")
                entrypoint["schedule"] = match.group(schedule_group) if schedule_group and match.lastindex is not None and match.lastindex >= schedule_group else "* * * * *"
                entrypoint["handler"] = _find_handler_name(content, line_num, ext)

            elif extract_type == "handler":
                handler_group = pattern_def.get("handler_group")
                entrypoint["handler"] = match.group(handler_group) if handler_group and match.lastindex is not None and match.lastindex is not None and match.lastindex >= handler_group else "unknown"

            elif extract_type == "handler_only":
                entrypoint["handler"] = "anonymous"

            elif extract_type == "worker_file":
                path_group = pattern_def.get("path_group")
                entrypoint["worker_file"] = match.group(path_group) if path_group and match.lastindex is not None and match.lastindex >= path_group else "unknown"

            elif extract_type == "queue_name" or extract_type == "consumer_group":
                name_group = pattern_def.get("name_group")
                entrypoint["name"] = match.group(name_group) if name_group and match.lastindex is not None and match.lastindex >= name_group else "unknown"

            elif extract_type == "test_name":
                name_group = pattern_def.get("name_group")
                test_name = match.group(name_group) if name_group and match.lastindex is not None and match.lastindex >= name_group else "unknown"
                # Filter out empty/whitespace-only test names (e.g., it(\n...) matches)
                if test_name.strip() and test_name.strip() not in ('\\n', '\\r', '\\t'):
                    entrypoint["test_name"] = test_name.strip()
                else:
                    continue  # Skip this match — empty test name

            elif extract_type == "click_command":
                command_group = pattern_def.get("command_group")
                entrypoint["command"] = match.group(command_group) if command_group and match.lastindex is not None and match.lastindex >= command_group else None
                if not entrypoint.get("command"):
                    # Get from next def line
                    entrypoint["command"] = _find_click_command_name(content, line_num)

            results.append(entrypoint)

    except re.error:
        pass

    return results


# ─── Handler Name Extraction ───────────────────────────────────

def _find_handler_name(content: str, line_num: int, ext: str) -> str:
    """Try to find the handler function name near a given line.

    Looks at the current line and a few lines after for a function reference.
    """
    lines = content.split('\n')
    start = max(0, line_num - 1)
    end = min(len(lines), line_num + 5)

    for i in range(start, end):
        if i >= len(lines):
            break
        line = lines[i].strip()

        # Look for function reference in handler position
        # Pattern: ...route(..., handlerName) or ...route(..., handlerName, ...)
        m = re.search(r'(?:,\s*|\s+)(\w+)\s*(?:,\s*|\s*\))', line)
        if m:
            name = m.group(1)
            if name not in ('async', 'function', 'await', 'next', 'err', 'error', 'req', 'res', 'ctx'):
                return name

        # Look for inline arrow function or async function
        m = re.search(r'(?:async\s+)?(?:function\s+)?(\w+)\s*(?:=>|\{)', line)
        if m:
            name = m.group(1)
            if name not in ('async', 'function', 'await', 'const', 'let', 'var'):
                return name

    return "anonymous"


def _find_handler_after_decorator(content: str, line_num: int, ext: str) -> str:
    """Find the function name after a Python decorator (for Flask/FastAPI)."""
    lines = content.split('\n')

    # Look at the next few lines after the decorator for the function definition
    for i in range(line_num, min(line_num + 5, len(lines))):
        line = lines[i].strip()
        m = re.match(r'(?:async\s+)?def\s+(\w+)', line)
        if m:
            return m.group(1)

    return "anonymous"


def _find_click_command_name(content: str, line_num: int) -> str:
    """Find the function name decorated with @click.command()."""
    lines = content.split('\n')

    for i in range(line_num - 1, min(line_num + 3, len(lines))):
        line = lines[i].strip()
        m = re.match(r'def\s+(\w+)', line)
        if m:
            return m.group(1)

    return "unknown"


def _path_from_file(rel_path: str) -> str:
    """Derive an API path from a file path (for Next.js app directory)."""
    # Convert src/app/api/users/route.ts -> /api/users
    parts = rel_path.replace('\\', '/').split('/')
    api_idx = -1
    for i, part in enumerate(parts):
        if part == 'api':
            api_idx = i
            break

    if api_idx >= 0:
        path_parts = parts[api_idx:-1]  # Remove route.ts/index.ts
        # Remove (group) segments
        path_parts = [p for p in path_parts if not p.startswith('(') and not p.endswith(')')]
        return '/' + '/'.join(path_parts)

    return '/' + os.path.splitext(os.path.basename(rel_path))[0]


def _method_from_spring_label(label: str) -> str:
    """Derive HTTP method from a Spring-style label."""
    if "get" in label.lower():
        return "GET"
    elif "post" in label.lower():
        return "POST"
    elif "put" in label.lower():
        return "PUT"
    elif "delete" in label.lower():
        return "DELETE"
    elif "patch" in label.lower():
        return "PATCH"
    return "ANY"


# ─── Execution Graph Builder ───────────────────────────────────

def _build_execution_graph(
    workspace: str,
    entrypoints: List[Dict[str, Any]]
) -> Dict[str, List[str]]:
    """Build a lightweight execution graph: entrypoint → called functions.

    For HTTP handlers, format: "METHOD /path → handler → [func1, func2]"
    For other types, format: "type:label → handler → [func1, func2]"
    """
    graph: Dict[str, List[str]] = {}

    # Group by file for efficient scanning
    files_to_scan: Set[str] = {ep["file"] for ep in entrypoints}

    # Read file contents
    file_contents: Dict[str, str] = {}
    for rel_path in files_to_scan:
        full_path = os.path.join(workspace, rel_path)
        try:
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                file_contents[rel_path] = f.read()
        except IOError:
            continue

    for ep in entrypoints:
        # Build the entrypoint key
        if ep["type"] == "http_handler":
            key = f"{ep.get('method', 'ANY')} {ep.get('path', '/')}"
        elif ep["type"] == "test_entry":
            key = f"test: {ep.get('test_name', ep.get('handler', 'unknown'))}"
        elif ep["type"] == "cli_command":
            key = f"cli: {ep.get('command', ep.get('handler', 'unknown'))}"
        elif ep["type"] == "cron_job":
            key = f"cron: {ep.get('schedule', '?')} ({ep.get('handler', 'unknown')})"
        elif ep["type"] == "event_handler":
            key = f"event: {ep.get('event', 'unknown')}"
        elif ep["type"] == "worker":
            key = f"worker: {ep.get('name', ep.get('handler', ep.get('label', 'unknown')))}"
        else:
            key = f"{ep['type']}: {ep.get('handler', 'unknown')}"

        # Find functions called by the handler
        handler_name = ep.get("handler", "")
        called_functions = []

        if handler_name and handler_name != "anonymous" and ep["file"] in file_contents:
            called_functions = _find_called_functions(
                file_contents[ep["file"]], handler_name
            )

        graph_key = f"{key} -> {handler_name or 'anonymous'}"
        graph[graph_key] = called_functions[:10]  # Cap to avoid noise

    return graph


def _find_called_functions(content: str, handler_name: str) -> List[str]:
    """Find functions called within a handler function's body.

    Uses a simple heuristic: find the handler definition, then look for
    function calls until the next function definition at the same indentation level.
    """
    lines = content.split('\n')
    called: List[str] = []
    in_handler = False
    handler_indent = 0

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Skip comments and empty lines
        if not stripped or stripped.startswith('//') or stripped.startswith('#') or stripped.startswith('/*'):
            continue

        # Detect handler start
        if not in_handler:
            if re.search(r'\b' + re.escape(handler_name) + r'\b', stripped):
                # Check if this looks like a function definition or assignment
                if re.match(r'(?:def|function|const|let|var|async\s+function)\s+' + re.escape(handler_name), stripped) \
                   or re.search(re.escape(handler_name) + r'\s*(?:=|:)\s*(?:async\s+)?(?:function|\()', stripped) \
                   or re.match(r'def\s+' + re.escape(handler_name), stripped):
                    in_handler = True
                    handler_indent = len(line) - len(line.lstrip())
                    continue
        else:
            current_indent = len(line) - len(line.lstrip()) if stripped else handler_indent + 1

            # If we're back at the same or lower indentation, handler is done
            if current_indent <= handler_indent and stripped and not stripped.startswith(('return', 'pass', 'else:', 'elif', 'except', 'finally')):
                break

            # Look for function calls
            for m in re.finditer(r'(\w+)\s*\(', stripped):
                fn_name = m.group(1)
                # Skip keywords and common non-function patterns
                skip = {
                    'if', 'for', 'while', 'switch', 'catch', 'try', 'with',
                    'return', 'throw', 'new', 'typeof', 'instanceof', 'await',
                    'console', 'print', 'self', 'super', 'class', 'import',
                    'from', 'require', 'assert', 'raise', 'except', 'def',
                    'function', 'const', 'let', 'var', 'async', 'yield',
                }
                if fn_name not in skip and fn_name != handler_name and fn_name not in called:
                    called.append(fn_name)

    return called


# ─── Deduplication ─────────────────────────────────────────────

def _deduplicate_entrypoints(entrypoints: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicate entrypoints (same type, file, line)."""
    seen: Set[Tuple[str, str, int]] = set()
    unique = []

    for ep in entrypoints:
        key = (ep.get("type", ""), ep.get("file", ""), ep.get("line", 0))
        if key not in seen:
            seen.add(key)
            unique.append(ep)

    return unique


# ─── Stats Computation ─────────────────────────────────────────

def _compute_stats(entrypoints: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute statistics from entrypoint list."""
    by_type: Dict[str, int] = defaultdict(int)

    for ep in entrypoints:
        by_type[ep.get("type", "unknown")] += 1

    return {
        "total_entrypoints": len(entrypoints),
        "by_type": dict(by_type),
    }


# ─── Recommendations ───────────────────────────────────────────

def _generate_recommendations(
    entrypoints: List[Dict[str, Any]],
    stats: Dict[str, Any]
) -> List[str]:
    """Generate actionable recommendations based on entrypoint findings."""
    recs = []

    by_type = stats.get("by_type", {})

    if not entrypoints:
        recs.append("No entrypoints detected. Is this a library/module without an application entry?")
        return recs

    # Main entry point
    main_eps = [ep for ep in entrypoints if ep["type"] == "main"]
    if not main_eps:
        recs.append(
            "No main entry point detected (no main(), __name__=='__main__', or fn main()). "
            "If this is an application, consider adding a clear entry point."
        )
    elif len(main_eps) > 1:
        files = set(ep["file"] for ep in main_eps)
        if len(files) > 1:
            recs.append(
                f"Multiple main entry points found across {len(files)} files. "
                f"Ensure each service/app has exactly one clear entry point. "
                f"Files: {', '.join(list(files)[:5])}"
            )

    # HTTP handlers
    http_eps = [ep for ep in entrypoints if ep["type"] == "http_handler"]
    if http_eps:
        # Check for missing HTTP methods
        methods = set(ep.get("method", "") for ep in http_eps)
        if "DELETE" not in methods and "PUT" not in methods and "PATCH" not in methods:
            recs.append(
                "Only read-type HTTP handlers detected (GET/POST). "
                "If this is a REST API, ensure DELETE/PUT/PATCH handlers exist where needed."
            )

        # Check for overly broad routes
        broad_routes = [ep for ep in http_eps if ep.get("path") in ("/", "/*", "/*.*")]
        if broad_routes:
            recs.append(
                f"Found {len(broad_routes)} catch-all route(s). "
                f"Consider using more specific paths for better routing and debugging."
            )

        # Check for unparameterized routes that might need params
        recs.append(
            f"Found {len(http_eps)} HTTP endpoint(s). "
            f"Ensure all endpoints have proper authentication and input validation."
        )

    # Event handlers
    event_eps = [ep for ep in entrypoints if ep["type"] == "event_handler"]
    if event_eps:
        # Check for error event handlers
        has_error_handler = any(
            ep.get("event", "").lower() in ('error', 'unhandledrejection', 'uncaughtexception', 'sigterm', 'sigint')
            for ep in event_eps
        )
        if not has_error_handler:
            recs.append(
                "No global error event handlers detected. "
                "Consider adding process.on('uncaughtException') or window.addEventListener('error') handlers."
            )

    # Cron jobs
    cron_eps = [ep for ep in entrypoints if ep["type"] == "cron_job"]
    if cron_eps:
        recs.append(
            f"Found {len(cron_eps)} scheduled task(s). "
            f"Ensure cron jobs have proper error handling and logging, "
            f"and that they are idempotent to handle re-runs."
        )

    # Workers
    worker_eps = [ep for ep in entrypoints if ep["type"] == "worker"]
    if worker_eps:
        recs.append(
            f"Found {len(worker_eps)} background worker(s). "
            f"Ensure workers have proper retry logic and dead-letter queue handling."
        )

    # CLI commands
    cli_eps = [ep for ep in entrypoints if ep["type"] == "cli_command"]
    if cli_eps:
        recs.append(
            f"Found {len(cli_eps)} CLI command(s). "
            f"Ensure commands have --help documentation and proper argument validation."
        )

    # Test entries
    test_eps = [ep for ep in entrypoints if ep["type"] == "test_entry"]
    http_count = len(http_eps)
    test_count = len(test_eps)
    if http_count > 0 and test_count == 0:
        recs.append(
            f"Found {http_count} HTTP endpoint(s) but no test entries. "
            f"Add API integration tests to verify endpoint behavior."
        )
    elif http_count > 0 and test_count < http_count * 0.5:
        recs.append(
            f"Low test-to-endpoint ratio ({test_count} tests for {http_count} endpoints). "
            f"Consider adding more API tests."
        )

    return recs
