"""
Secrets Detection Engine for CodeLens — v3
Detects hardcoded secrets, API keys, tokens, passwords, and connection strings
in source code that should never be committed.

Answers: "Are there any secrets or credentials hardcoded in the codebase?"
Answers: "Are .env files properly excluded from version control?"

Architecture:
- Pattern-based detection: regex patterns for known secret formats
- Entropy-based detection: flag high-entropy strings that look like secrets
- .env file scanner: read all .env files and report every secret variable
- .gitignore check: verify .env files are excluded from version control

Secret Categories (by severity):
- critical: private_key, password, connection_string
- high:     api_key, token, secret_key, oauth
- medium:   webhook

Each finding includes masked value (first 4 chars + "***") to prevent
the engine itself from becoming a secret-leaking vector.
"""

import os
import re
import math
import concurrent.futures
from typing import Dict, List, Any, Optional, Set, Tuple
from collections import defaultdict
from utils import DEFAULT_IGNORE_DIRS, logger

# ─── Safety Limits ──────────────────────────────────────────────

# Maximum file size to scan (1MB). Files larger than this are skipped
# to prevent catastrophic regex backtracking on minified/generated files.
MAX_FILE_SIZE_BYTES = 1_000_000

# Per-file regex timeout in seconds. If regex matching takes longer,
# the file is skipped.
PER_FILE_REGEX_TIMEOUT = 5


class _RegexTimeout(Exception):
    """Raised when regex matching exceeds the time limit."""
    pass


# Code-file extensions that also qualify for entropy-based scanning.
# Centralised here so the timeout helper below is the single source of truth.
_ENTROPY_EXTENSIONS = frozenset(
    {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".py", ".rs"}
)


def _scan_file_with_timeout(content, rel_path, ext, is_test):
    """Run pattern + entropy scanning for one file with a hard timeout.

    Uses a worker thread via ``concurrent.futures.ThreadPoolExecutor`` so the
    timeout works on Windows as well as POSIX. ``signal.SIGALRM`` is
    POSIX-only and raises ``AttributeError`` on Windows, which previously
    crashed ``codelens secrets`` on that platform. If scanning exceeds
    ``PER_FILE_REGEX_TIMEOUT`` seconds, ``_RegexTimeout`` is raised and the
    caller skips the file. The worker thread is a daemon on Python 3.9+ and
    self-terminates when the (slow) regex eventually completes, so it does
    not block process exit on modern Python.
    """
    def _do_scan():
        file_findings = _scan_file_patterns(content, rel_path, ext, is_test)
        if ext in _ENTROPY_EXTENSIONS:
            file_findings = file_findings + _scan_file_entropy(
                content, rel_path, ext, is_test
            )
        return file_findings

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_do_scan)
    try:
        return future.result(timeout=PER_FILE_REGEX_TIMEOUT)
    except concurrent.futures.TimeoutError:
        raise _RegexTimeout()
    finally:
        executor.shutdown(wait=False)

# ─── Configuration ─────────────────────────────────────────────

SOURCE_EXTENSIONS = {
    ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".py", ".rs", ".php", ".env", ".yaml", ".yml",
    ".json", ".toml", ".cfg", ".ini", ".conf", ".zig",
}

# ─── Secret Pattern Definitions ────────────────────────────────

SECRET_PATTERNS = {
    # ── API Keys ────────────────────────────────────────────────
    "api_key": {
        "severity": "high",
        "category": "api_key",
        "patterns": [
            # Generic API key assignments
            r'(?i)(?:api[_-]?key|apikey)\s*(?:=|:|\s)\s*["\']([A-Za-z0-9_\-]{16,})["\']',
            r'(?i)["\']X-API-Key["\']\s*(?:=|:)\s*["\']([A-Za-z0-9_\-]{16,})["\']',
            # OpenAI-style keys (sk-...) — require word boundary to avoid matching
            # "zendesk-webhook-signature" and similar compound words
            r'(?:^|(?<=[\s"\':=,;(]))sk-[A-Za-z0-9_\-]{20,}',
            # Stripe-style keys (pk_*, sk_*)
            r'["\']?(pk_(?:test|live)_[A-Za-z0-9]{24,})["\']?',
            r'["\']?(sk_(?:test|live)_[A-Za-z0-9]{24,})["\']?',
            # GitHub personal access tokens (ghp_*) — require word boundary
            r'(?:^|(?<=[\s"\':=,;(]))ghp_[A-Za-z0-9]{36,}',
            # GitHub OAuth tokens (gho_*) — require word boundary
            r'(?:^|(?<=[\s"\':=,;(]))gho_[A-Za-z0-9]{36,}',
            # GitHub fine-grained tokens (github_pat_*) — require word boundary
            r'(?:^|(?<=[\s"\':=,;(]))github_pat_[A-Za-z0-9_]{22,}',
            # Google API keys (AIza...)
            r'["\']?(AIza[A-Za-z0-9_\-]{35})["\']?',
            # AWS access key IDs (AKIA...)
            r'["\']?(AKIA[A-Z0-9]{16})["\']?',
            # AWS secret access keys (40-char base64 after known key)
            r'(?i)aws[_\-]?secret[_\-]?access[_\-]?key\s*(?:=|:)\s*["\']([A-Za-z0-9/+=]{40,})["\']',
            # SendGrid API keys (SG.) — require word boundary
            r'(?:^|(?<=[\s"\':=,;(]))SG\.[A-Za-z0-9_\-]{22,}\.[A-Za-z0-9_\-]{43,}',
            # Twilio API keys
            r'(?i)twilio[_\-]?api[_\-]?key\s*(?:=|:)\s*["\']([A-Za-z0-9]{32,})["\']',
            # Mailgun API keys
            r'(?i)mailgun[_\-]?api[_\-]?key\s*(?:=|:)\s*["\']([A-Za-z0-9\-]{32,})["\']',
            # Slack API tokens (xoxb-*, xoxp-*) — require word boundary
            r'(?:^|(?<=[\s"\':=,;(]))xox[bpas]-[A-Za-z0-9\-]{10,}',
            # Heroku API keys
            r'(?i)heroku[_\-]?api[_\-]?key\s*(?:=|:)\s*["\']([A-Za-z0-9\-]{36,})["\']',
        ],
    },

    # ── Passwords ───────────────────────────────────────────────
    "password": {
        "severity": "critical",
        "category": "password",
        "patterns": [
            # Generic password assignments
            r'(?i)(?:password|passwd|pwd)\s*(?:=|:)\s*["\']([^"\']{6,})["\']',
            # Environment variable style
            r'(?i)(?:DB_PASSWORD|DATABASE_PASSWORD|MYSQL_PASSWORD|POSTGRES_PASSWORD|PG_PASSWORD|MONGO_PASSWORD|REDIS_PASSWORD)\s*(?:=|:)\s*["\']?([^\s"\'`]{6,})["\']?',
            # URL-embedded passwords: user:pass@
            # Exclude '/' from capture group to prevent false positives from URI schemes
            # like "sidecar://content_id/thumbs/grid@2x.webp" being matched as passwords.
            # The '/' separator only appears in URI paths, never in real passwords.
            r'(?i)[\w+\-\.]+:([^\s/@"\']{4,})@[A-Za-z0-9\-\.]+\.[A-Za-z]{2,}',
            # Config-style password
            r'(?i)["\']password["\']\s*:\s*["\']([^"\']{6,})["\']',
            # Python-style
            r'(?i)password\s*=\s*["\']([^"\']{6,})["\']',
            # Java properties style
            r'(?i)(?:spring\.datasource\.password|jdbc\.password)\s*=\s*([^\s]{6,})',
            # YAML-style passwords — ONLY match when value is a quoted string or a bare literal.
            # Avoid false positives from JS/TS object property assignments like:
            #   password: videoRef.meetingPassword,
            #   password: user.password,
            # Match: password: "literal" or password: 'literal' or password: literal_value
            # Skip: password: something.property or password: something?.optional
            r'(?i)password:\s*["\']([^"\']{6,})["\']',
            # PHP-style
            r"(?i)(?:DB_PASS|DB_PASSWORD|DATABASE_PASS)\s*(?:=|:)\s*[\"']([^\"']{6,})[\"']",
        ],
    },

    # ── Tokens ──────────────────────────────────────────────────
    "token": {
        "severity": "high",
        "category": "token",
        "patterns": [
            # Generic token assignments
            r'(?i)(?:token|access_token|refresh_token|auth_token|bearer_token)\s*(?:=|:)\s*["\']([A-Za-z0-9_\-\.]{20,})["\']',
            # Bearer tokens in headers
            r'(?i)(?:Authorization|Bearer)\s*(?::|=>|=)\s*["\']?(?:Bearer\s+)?([A-Za-z0-9_\-\.]{20,})["\']?',
            # JWT tokens (eyJ...)
            r'["\']?(eyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+)["\']?',
            # OAuth access tokens
            r'(?i)access[_\-]?token\s*(?:=|:)\s*["\']([A-Za-z0-9_\-]{20,})["\']',
            # Refresh tokens
            r'(?i)refresh[_\-]?token\s*(?:=|:)\s*["\']([A-Za-z0-9_\-]{20,})["\']',
            # GitLab tokens
            r'(?i)gitlab[_\-]?token\s*(?:=|:)\s*["\']([A-Za-z0-9_\-]{20,})["\']',
            # DigitalOcean tokens — require word boundary
            r'(?:^|(?<=[\s"\':=,;(]))dop_v1_[A-Za-z0-9]{40,}',
            # Shopify tokens
            r'(?i)shopify[_\-]?token\s*(?:=|:)\s*["\']([A-Za-z0-9]{32,})["\']',
            # NuGet API keys
            r'(?i)nuget[_\-]?api[_\-]?key\s*(?:=|:)\s*["\']([A-Za-z0-9]{32,})["\']',
        ],
    },

    # ── Connection Strings ──────────────────────────────────────
    "connection_string": {
        "severity": "critical",
        "category": "connection_string",
        "patterns": [
            # MongoDB connection strings with credentials
            r'["\']?(mongodb(?:\+srv)?://[^\s"\']{10,})["\']?',
            # PostgreSQL connection strings
            r'["\']?(postgresql?://[^\s"\']{10,})["\']?',
            # MySQL connection strings
            r'["\']?(mysql://[^\s"\']{10,})["\']?',
            # Redis connection strings with auth
            r'["\']?(redis://[^\s"\']{10,})["\']?',
            # AMQP/RabbitMQ
            r'["\']?(amqp://[^\s"\']{10,})["\']?',
            # JDBC connection strings
            r'(?i)jdbc:[A-Za-z]+://[^\s"\']{10,}',
            # SQLAlchemy-style
            r'(?i)(?:SQLALCHEMY_DATABASE_URL|DATABASE_URL)\s*(?:=|:)\s*["\']([^\s"\']{10,})["\']',
            # Django DATABASES style
            r"(?i)DATABASES\s*=\s*\{[^}]*?['\"]PASSWORD['\"]\s*:\s*['\"]([^'\"]+?)['\"]",
        ],
    },

    # ── Private Keys ────────────────────────────────────────────
    "private_key": {
        "severity": "critical",
        "category": "private_key",
        "patterns": [
            # RSA private key header
            r'-----BEGIN\s+RSA\s+PRIVATE\s+KEY-----',
            # EC private key header
            r'-----BEGIN\s+EC\s+PRIVATE\s+KEY-----',
            # DSA private key header
            r'-----BEGIN\s+DSA\s+PRIVATE\s+KEY-----',
            # Generic private key header
            r'-----BEGIN\s+PRIVATE\s+KEY-----',
            # OpenSSH private key
            r'-----BEGIN\s+OPENSSH\s+PRIVATE\s+KEY-----',
            # PGP private key
            r'-----BEGIN\s+PGP\s+PRIVATE\s+KEY\s+BLOCK-----',
            # PKCS#8 encrypted private key
            r'-----BEGIN\s+ENCRYPTED\s+PRIVATE\s+KEY-----',
        ],
    },

    # ── Secret Keys ─────────────────────────────────────────────
    "secret_key": {
        "severity": "high",
        "category": "secret_key",
        "patterns": [
            # Generic SECRET_KEY assignments
            r'(?i)(?:SECRET_KEY|secretKey|secret_key)\s*(?:=|:)\s*["\']([^"\']{8,})["\']',
            # Flask SECRET_KEY
            r'(?i)(?:app\.config\[["\']SECRET_KEY["\']\]|SECRET_KEY)\s*=\s*["\']([^"\']{8,})["\']',
            # Django SECRET_KEY
            r'(?i)SECRET_KEY\s*=\s*["\']([^"\']{8,})["\']',
            # NextAuth SECRET
            r'(?i)NEXTAUTH_SECRET\s*(?:=|:)\s*["\']([^"\']{8,})["\']',
            # Auth0 secret
            r'(?i)AUTH0[_\-]?CLIENT[_\-]?SECRET\s*(?:=|:)\s*["\']([^"\']{8,})["\']',
            # Rails secret_key_base
            r'(?i)secret_key_base\s*(?:=|:)\s*["\']([^"\']{8,})["\']',
            # Laravel APP_KEY
            r'(?i)APP_KEY\s*(?:=|:)\s*["\']?(base64:[A-Za-z0-9+/=]{20,})["\']?',
            # Express session secret
            r'(?i)(?:session\s*\(\s*\{[^}]*secret|cookieParser\s*\(\s*["\'])([^"\']{8,})',
            # JWT secret
            r'(?i)JWT[_\-]?SECRET\s*(?:=|:)\s*["\']([^"\']{8,})["\']',
            # Encryption key
            r'(?i)(?:ENCRYPTION_KEY|encrypt[_-]?key)\s*(?:=|:)\s*["\']([A-Fa-f0-9]{16,})["\']',
            # Signing key
            r'(?i)(?:SIGNING_KEY|sign[_-]?key)\s*(?:=|:)\s*["\']([^"\']{8,})["\']',
        ],
    },

    # ── OAuth ───────────────────────────────────────────────────
    "oauth": {
        "severity": "high",
        "category": "oauth",
        "patterns": [
            # OAuth client secrets
            r'(?i)client[_\-]?secret\s*(?:=|:)\s*["\']([^"\']{10,})["\']',
            # OAuth tokens
            r'(?i)oauth[_\-]?token\s*(?:=|:)\s*["\']([A-Za-z0-9_\-]{20,})["\']',
            # OAuth consumer secrets
            r'(?i)consumer[_\-]?secret\s*(?:=|:)\s*["\']([^"\']{10,})["\']',
            # Facebook app secret
            r'(?i)(?:FACEBOOK_APP_SECRET|FB_APP_SECRET)\s*(?:=|:)\s*["\']([A-Fa-f0-9]{32})["\']',
            # Google OAuth client secret
            r'(?i)(?:GOOGLE_CLIENT_SECRET|GOOGLE_OAUTH_SECRET)\s*(?:=|:)\s*["\']([A-Za-z0-9_\-]{20,})["\']',
            # Twitter consumer secret
            r'(?i)(?:TWITTER_CONSUMER_SECRET|TWITTER_API_SECRET)\s*(?:=|:)\s*["\']([A-Za-z0-9]{30,})["\']',
            # LinkedIn client secret
            r'(?i)(?:LINKEDIN_CLIENT_SECRET)\s*(?:=|:)\s*["\']([A-Za-z0-9]{20,})["\']',
        ],
    },

    # ── Webhooks ────────────────────────────────────────────────
    "webhook": {
        "severity": "medium",
        "category": "webhook",
        "patterns": [
            # Slack webhook URLs
            r'["\']?(https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+)["\']?',
            # Discord webhook URLs
            r'["\']?(https://(?:discord\.com|discordapp\.com)/api/webhooks/\d+/[A-Za-z0-9_\-]+)["\']?',
            # Stripe webhook endpoint secrets
            r'(?i)(?:STRIPE_WEBHOOK_SECRET|whsec_[A-Za-z0-9]+)\s*(?:=|:)\s*["\']([A-Za-z0-9]{20,})["\']',
            # GitHub webhook secrets
            r'(?i)(?:GITHUB_WEBHOOK_SECRET|WEBHOOK_SECRET)\s*(?:=|:)\s*["\']([^"\']{10,})["\']',
            # Generic webhook URLs with tokens
            r'(?i)webhook[_\-]?url\s*(?:=|:)\s*["\'](https?://[^\s"\']+)["\']',
        ],
    },
}

# ─── Known safe / false-positive patterns ──────────────────────

SAFE_VALUE_PATTERNS = [
    r'(?i)^(example|test|mock|dummy|fake|placeholder|xxx|changeme|your[_-]?key|insert[_-]?key|replace[_-]?me|todo|sample)(?:[_\-\s]|$)',
    r'(?i)^(process\.env|os\.environ|os\.getenv|env\()',
    r'(?i)^import\.meta\.env',
    r'^\$\{',  # Template variable ${...}
    r'^=\{\{\$?',  # n8n template expression ={{$... or ={{ $
    r'^\{\{',   # Mustache/Handlebars {{...}}
    r'^\{%\s',  # Django/Jinja2 {% ... %}
    r'^<%=',     # ERB <%= ... %>
    r'(?i)^(true|false|null|none|undefined|nil)$',
    r'^\*+$',   # All asterisks
    r'(?i)^(password|secret|token|key)$',  # Just the word itself
    # Variable references (not hardcoded strings) — common in JS/TS object properties
    # e.g., "password: videoRef.meetingPassword" or "password: config.secret"
    # These contain dots (property access) or optional chaining (?.)
    r'(?i)^[a-zA-Z_$][\w$]*(\.[a-zA-Z_$][\w$]*|\?\.[a-zA-Z_$][\w$]*)+',
    # ALL_CAPS identifiers (env var names, not actual secrets)
    # IMPORTANT: Must contain at least one underscore to distinguish from AWS keys (AKIA...)
    r'^[A-Z][A-Z0-9]*_[A-Z0-9_]+$',
    # Angle-bracket placeholders: <USER>, <PASS>, <YOUR_API_KEY>, <CLIENT_ID>
    r'^<[A-Za-z_]+>$',
    # URL placeholder patterns: s3://ACCESSKEY:SECRETKEY@...
    r'(?i)^[A-Z][A-Z0-9_]+:[A-Z][A-Z0-9_]+@',
    # Common example domain patterns
    r'(?i)^(from:|to:|subject:|has:|label:|newer_than:)',
    # HTML entities and escaped content
    r'(?i)^&[a-z]+;',
    # Angular template expressions
    r'^\{\{\s*[\w.]+\s*\|',  # {{ value | pipe }}
    # Regex/syntax patterns that look like secrets but aren't
    r'^[\[\(]',  # Starts with bracket (regex, array)
    r'(?i)^rfc822msgid',
    # Common placeholder password patterns used in example/sample configs
    r'(?i)^(SuperSecret|MySecret|SecretKey|Password123|ChangeMe|MyPassword|AdminPassword|TestPassword|DefaultPassword)',
    r'(?i)^(your[_-]?password|your[_-]?secret|your[_-]?key|your[_-]?token)',
    # Angle-bracket placeholders (broader version): <YOUR_API_KEY_HERE>, <replace-me>
    r'(?i)^<[^>]+>$',
]

# ─── Template Expression Patterns (line-level) ──────────────────
# These patterns are checked against the FULL LINE context to detect
# template expressions that indicate a value is a placeholder, not a hardcoded secret.

TEMPLATE_LINE_PATTERNS = [
    re.compile(r'=\{\{\$'),           # n8n: ={{$credentials.password}}
    re.compile(r'=\{\{\s*\$'),        # n8n: ={{ $credentials.password }}
    re.compile(r'\{\{[\w.$]+\}\}'),   # Mustache/Handlebars: {{apiKey}}, {{config.value}}
    re.compile(r'\{%[-\s]'),           # Django/Jinja2: {% ... %}
    re.compile(r'\{\{\s*[\w.]'),      # Jinja2 output: {{ variable }}
    re.compile(r'<%='),                # ERB: <%= ... %>
    re.compile(r'\$\{[\w.]+\}'),      # Shell/JS template: ${VAR}, ${env.KEY}
]

# ─── Environment Variable Reference Patterns (line-level) ───────
# Lines that READ from environment variables, not hardcoding secrets.

ENV_REFERENCE_LINE_PATTERNS = [
    re.compile(r'process\.env\.[A-Za-z_]'),       # process.env.PASSWORD
    re.compile(r"process\.env\[['\"][A-Za-z_]"),  # process.env['PASSWORD']
    re.compile(r'os\.environ\.get\('),            # os.environ.get('SECRET')
    re.compile(r"os\.environ\[['\"][A-Za-z_]"),   # os.environ['SECRET']
    re.compile(r'os\.getenv\('),                   # os.getenv('SECRET')
    re.compile(r'import\.meta\.env\.[A-Za-z_]'),  # import.meta.env.KEY
    re.compile(r'deno\.env\.get\('),              # Deno: Deno.env.get('KEY')
    re.compile(r'process\.env\.PASSWORD'),
    re.compile(r'process\.env\.SECRET'),
    re.compile(r'process\.env\.TOKEN'),
    re.compile(r'process\.env\.KEY'),
]

# ─── Line-level Exclusion Patterns ────────────────────────────
# Additional line-level checks to reduce false positives from examples,
# placeholders, comments, and documentation strings.

LINE_EXCLUSION_PATTERNS = [
    # Placeholder/example indicator lines
    re.compile(r'(?i)placeholder\s*[:=]'),        # placeholder: 'value'
    re.compile(r'(?i)\be\.g\.\b'),              # e.g. "from:example@gmail.com"
    # Example indicator in value or comment only (not in variable name or path)
    re.compile(r"""(?i)(?:#\s.*\bexample|//\s.*\bexample|['"]\s*example[s]?\s*['"])\b"""),
    re.compile(r'(?i)\bfor example\b'),           # For example, ...
    # Lines that are just comments (not code with embedded secrets)
    re.compile(r'^\s*(//|#|/\*|\*)\s'),          # Comment-only lines
    re.compile(r'^\s*\*\s'),                      # Doc comment continuation
    # Description/documentation fields in node definitions (n8n pattern)
    re.compile(r'(?i)(?:description|hint|placeholder)\s*[:=]'),
    # URL examples in documentation
    re.compile(r'(?i)https?://[a-z]+\.example\.com'),
    re.compile(r'(?i)s3://[A-Z_]+:[A-Z_]+@'),     # s3://ACCESSKEY:SECRETKEY@...
    # Gmail/search query patterns
    re.compile(r'(?i)(?:from:|to:|subject:|has:|label:|newer_than:|rfc822msgid:)'),
    # HTML content in descriptions
    re.compile(r'(?i)<(?:a |href|img |src=)'),
    # Property definitions in credential/node files (not actual assignments)
    # NOTE: Removed 'name' and 'type' from filter — they can contain real secrets
    re.compile(r"(?i)(?:displayName|placeholder|hint|description)\s*[:=]\s*['\"]"),
    # Test assertion patterns
    re.compile(r'(?i)(?:expect|assert|should)\s*\('),
    # String concatenation / template literals (variable references)
    re.compile(r'`[^`]*\$\{'),                     # Template literal with interpolation
    # Angular/React template patterns
    re.compile(r'\[\w+\]\s*='),                  # Angular property binding [prop]=value
    re.compile(r'\{\{.*\|'),                       # Angular pipe {{ value | pipe }}
    # v6.4.1: Integrity/subresource hash lines — these are content verification hashes, not secrets
    re.compile(r'(?i)integrity\s*[=:]\s*["\']sha[235]\d{2}-'),
    # v6.4.1: example.com URLs in any code (test fixture data, not real credentials)
    re.compile(r'(?i)https?://(?:[a-z0-9-]+\.)?example\.(?:com|org|net)'),
]

# ─── Test File Patterns ─────────────────────────────────────────

TEST_FILE_PATTERNS = [
    '.test.', '.spec.', '__tests__', '/test/', '/tests/',
    'test/', 'tests/', 'spec/', 'specs/',
    '/__mocks__/', '.mock.', '/mock/', '/mocks/',
    '.stories.', '.story.',
]

# ─── Credential Template Path Patterns ──────────────────────────
# n8n credential definition files that use template syntax

CREDENTIAL_PATH_PATTERNS = [
    '/credentials/',
    '/credential-definitions/',
    '/credential_templates/',
    '/benchmark/',  # Mock/fixture data for benchmarks
]

# .env variable name patterns that indicate secrets
ENV_SECRET_PATTERNS = [
    r'(?i).*(?:PASSWORD|PASSWD|PWD|SECRET|TOKEN|KEY|CREDENTIAL|AUTH|API_KEY|PRIVATE)',
    r'(?i).*(?:ACCESS_KEY|ACCESS_SECRET|CLIENT_SECRET|CONSUMER_SECRET)',
    r'(?i).*(?:DATABASE_URL|DB_HOST|MONGO_URI|REDIS_URL|AMQP_URL)',
    r'(?i).*(?:STRIPE|AWS_|GCP_|AZURE_|GITHUB_TOKEN|SLACK_TOKEN)',
    r'(?i).*(?:JWT_SECRET|SESSION_SECRET|ENCRYPTION_KEY|SIGNING_KEY)',
    r'(?i).*(?:NEXTAUTH_SECRET|AUTH0_SECRET|FIREBASE_KEY)',
]

# ─── Entropy thresholds ───────────────────────────────────────

ENTROPY_THRESHOLD = 4.5
MIN_SECRET_LENGTH = 12
MAX_SECRET_LENGTH = 256

# Entropy scan exclusions — strings matching these patterns are not secrets
ENTROPY_EXCLUSION_PATTERNS = [
    re.compile(r'^data:(?:image|application|audio|video)/'),  # Data URIs
    re.compile(r'^https?://'),                                # URLs
    re.compile(r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+'),       # Email-like
    re.compile(r'^\d+(\.\d+){1,3}$'),                       # IP-like / version
    re.compile(r'^[A-Z][a-z]+[A-Z]'),                         # PascalCase (class names)
    re.compile(r'^(?:const|let|var|import|export|from|require)'), # JS keywords
    re.compile(r'^\.{0,2}/'),                                 # Relative paths
    re.compile(r'^[a-f0-9]{7,40}$', re.IGNORECASE),           # Short git hashes
    re.compile(r'^\$\{'),                                     # Template literals ${...}
    re.compile(r'^=\{\{\$?'),                                 # n8n template ={{$... or ={{
    re.compile(r'^\{\{'),                                     # Mustache/Handlebars {{...}}
    re.compile(r'^\{%'),                                      # Django/Jinja2 {% ... %}
    re.compile(r'^<%='),                                      # ERB <%= ... %>
    re.compile(r'^[A-Za-z0-9+/]+=*$'),                        # Pure base64 (likely encoded data, not secret)
    # v6.4.1: Integrity hashes — Subresource Integrity (SRI) and lockfile integrity
    # These are SHA-256/384/512 hashes used for content verification, NOT secrets.
    # Examples: "sha512-1fygroTLlHu66zi..." in lockfiles, "sha384-oqVuAfXRKap7fdgcCY5uykM6+R9GqQ8K/uxy9rx7HNQlGYl1kPzQho1wx4JwY8wC"
    re.compile(r'^sha[235]\d{2}-', re.IGNORECASE),            # SRI hash prefix
    re.compile(r'^[a-f0-9]{64,}$', re.IGNORECASE),           # Full SHA-256/512 hex strings (not secrets)
]

def detect_secrets(
    workspace: str,
    severity: Optional[str] = None,
    config: Optional[Dict] = None,
    max_files: int = 5000
) -> Dict[str, Any]:
    """
    Detect hardcoded secrets, API keys, tokens, and passwords in source code.

    Scans source files for known secret patterns AND high-entropy strings.
    Also scans .env files and checks if they are in .gitignore.

    Args:
        workspace: Absolute path to workspace
        severity: Optional filter: "critical", "high", "medium"
        config: CodeLens config dict
        max_files: Maximum number of files to scan (default: 5000)

    Returns:
        Dict with findings, stats, risk level, env exposure, and recommendations
    """
    workspace = os.path.abspath(workspace)

    findings: List[Dict[str, Any]] = []
    env_files: List[Dict[str, Any]] = []
    env_exposed: List[str] = []
    files_scanned = 0

    # ─── Phase 1: Pattern-based scanning ──────────────────────
    skipped_oversized = 0
    skipped_regex_timeout = 0

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

            # Skip files that are too large to prevent regex catastrophic backtracking
            try:
                file_size = os.path.getsize(file_path)
                if file_size > MAX_FILE_SIZE_BYTES:
                    skipped_oversized += 1
                    continue
            except OSError:
                continue

            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except IOError:
                continue

            files_scanned += 1

            # Determine if this is a test file (for severity reduction, not skipping)
            is_test = _is_test_file(rel_path)

            # Skip documentation/example directories (contain fake credentials)
            if _is_docs_or_example_file(rel_path):
                continue

            # Skip example/sample config files (contain placeholder credentials)
            if _is_example_config_file(rel_path):
                continue

            # Skip credential template files (e.g., n8n /credentials/ with template syntax)
            if _is_credential_template_file(rel_path, content):
                continue

            # Scan for patterns with per-file timeout protection.
            # The timeout is enforced via a worker thread (cross-platform);
            # see _scan_file_with_timeout for details.
            try:
                findings.extend(_scan_file_with_timeout(content, rel_path, ext, is_test))
            except _RegexTimeout:
                skipped_regex_timeout += 1
                logger.debug(f"Skipped {rel_path}: regex matching timed out ({PER_FILE_REGEX_TIMEOUT}s)")

    # ─── Phase 2: .env file scanning ──────────────────────────
    env_files = _scan_env_files(workspace)
    for env_f in env_files:
        findings.extend(env_f.get("findings", []))

    # ─── Phase 3: .gitignore check ────────────────────────────
    env_exposed = _check_env_gitignore(workspace, env_files)

    # ─── Deduplicate findings ─────────────────────────────────
    findings = _deduplicate_findings(findings)

    # ─── Apply severity filter ────────────────────────────────
    if severity:
        findings = [f for f in findings if f.get("severity") == severity]

    # ─── Compute stats ────────────────────────────────────────
    stats = _compute_stats(findings, env_files)

    # ─── Compute risk ─────────────────────────────────────────
    risk = _compute_risk(findings, env_exposed)

    # ─── Generate recommendations ─────────────────────────────
    recommendations = _generate_recommendations(findings, env_exposed, stats)

    return {
        "status": "ok",
        "workspace": workspace,
        "severity_filter": severity,
        "stats": stats,
        "risk": risk,
        "findings": findings[:200],  # Cap to avoid explosion
        "env_exposed": env_exposed,
        "recommendations": recommendations,
        "files_scanned": files_scanned,
        "files_skipped_oversized": skipped_oversized,
        "files_skipped_regex_timeout": skipped_regex_timeout,
    }

# ─── Pattern-based Scanner ─────────────────────────────────────

def _scan_file_patterns(content: str, rel_path: str, ext: str, is_test: bool = False) -> List[Dict[str, Any]]:
    """Scan file content for known secret patterns."""
    findings = []
    lines = content.split('\n')

    for category, definition in SECRET_PATTERNS.items():
        for pattern in definition["patterns"]:
            try:
                for match in re.finditer(pattern, content):
                    line_num = content[:match.start()].count('\n') + 1

                    # Get the captured value (group 1 if exists, else full match)
                    if match.lastindex and match.lastindex >= 1:
                        raw_value = match.group(1)
                    else:
                        raw_value = match.group(0)

                    # Skip safe/false-positive values
                    # BUT: if the line contains a known secret variable name, still report it
                    # (the variable name is a strong signal this is a real secret, not a placeholder)
                    line_text = lines[line_num - 1] if line_num <= len(lines) else ""
                    _known_secret_var_on_line = _is_known_secret_variable(line_text)
                    if _is_safe_value(raw_value) and not _known_secret_var_on_line:
                        continue

                    # Get the full line for context-aware exclusion checks

                    # Skip lines containing template expressions (not hardcoded secrets)
                    if _is_template_line(line_text):
                        continue

                    # Skip lines that read from environment variables
                    if _is_env_reference_line(line_text):
                        continue

                    # Skip example/placeholder/documentation lines
                    if _is_example_or_placeholder_line(line_text):
                        continue

                    # Skip obviously fake test values in test files
                    # e.g., hashed_password="secrethashed", password="incorrect"
                    if is_test and _is_obvious_test_value(raw_value):
                        continue

                    # Skip localhost connection strings — these are development defaults, not real secrets
                    if _is_localhost_connection_string(raw_value):
                        continue

                    # Skip path values flagged as passwords (pwd="/tmp/..." means "present working directory")
                    if _is_path_value_misclassified_as_secret(line_text, raw_value, category):
                        continue

                    # Skip URL test data (example.com, localhost, test domains in test files)
                    if is_test and _is_url_test_data(raw_value, line_text):
                        continue

                    # Skip enum/constant definitions — strings like "IncorrectPassword" or
                    # "missing-password" in TypeScript/JS enums are error codes, not secrets.
                    # Pattern: EnumMember = "value-with-password-keyword" or
                    #          ErrorCode = "some-password-error"
                    if _is_enum_or_constant_definition(line_text, ext):
                        continue

                    # Mask the value for safe reporting
                    masked = _mask_value(raw_value)

                    # Determine severity (reduce for test files)
                    severity = definition["severity"]
                    if is_test:
                        severity = _reduce_severity(severity)

                    finding = {
                        "type": "pattern_match",
                        "file": rel_path,
                        "line": line_num,
                        "match": masked,
                        "value": masked,
                        "line_content": line_text.strip(),
                        "severity": severity,
                        "category": definition["category"],
                    }
                    if is_test:
                        finding["in_test_file"] = True

                    findings.append(finding)
            except re.error:
                continue

    return findings

# ─── Entropy-based Scanner ─────────────────────────────────────

def _scan_file_entropy(content: str, rel_path: str, ext: str, is_test: bool = False) -> List[Dict[str, Any]]:
    """Scan file content for high-entropy strings that look like secrets.

    Uses Shannon entropy to identify strings that are too random to be
    normal text or code, and are long enough to be a credential.
    """
    findings = []
    lines = content.split('\n')

    # Extract quoted strings from the content
    quoted_strings = re.findall(
        r'''["']([A-Za-z0-9+/=_\-\.]{12,256})["']''',
        content
    )

    # Also check assignment-style values
    assignments = re.findall(
        r'(?:=|:)\s*["\']([A-Za-z0-9+/=_\-]{12,256})["\']',
        content
    )

    all_candidates = set(quoted_strings + assignments)

    # Cap candidates per file to avoid processing thousands from minified files
    if len(all_candidates) > 200:
        # Prioritize assignment-style values (more likely to be secrets)
        priority = set(assignments)
        remaining = all_candidates - priority
        all_candidates = priority | set(list(remaining)[:200 - len(priority)])

    for candidate in all_candidates:
        if _is_safe_value(candidate):
            continue

        # Skip candidates matching entropy exclusion patterns
        if any(pat.match(candidate) for pat in ENTROPY_EXCLUSION_PATTERNS):
            continue

        # Skip template expression values
        if _is_template_value(candidate):
            continue

        # Calculate Shannon entropy
        entropy = _shannon_entropy(candidate)

        if entropy > ENTROPY_THRESHOLD:
            # Check if this value was already caught by a pattern
            masked = _mask_value(candidate)

            # Find line number
            line_num = _find_line_number(content, candidate)

            # Get the full line for context-aware exclusion checks
            line_text = lines[line_num - 1] if line_num <= len(lines) else ""

            # Skip lines containing template expressions
            if _is_template_line(line_text):
                continue

            # Skip lines that read from environment variables
            if _is_env_reference_line(line_text):
                continue

            # Skip example/placeholder/documentation lines
            if _is_example_or_placeholder_line(line_text):
                continue

            # Skip localhost connection strings — these are development defaults, not real secrets
            if _is_localhost_connection_string(candidate):
                continue

            # Determine likely category based on context
            likely_category = _infer_category_from_value(candidate)

            # Determine severity (reduce for test files)
            severity = _severity_for_category(likely_category)
            if is_test:
                severity = _reduce_severity(severity)

            # Get the full line for line_content
            line_text = lines[line_num - 1] if line_num <= len(lines) else ""

            finding = {
                "type": "entropy_match",
                "file": rel_path,
                "line": line_num,
                "match": masked,
                "value": masked,
                "line_content": line_text.strip(),
                "severity": severity,
                "category": likely_category,
                "entropy": round(entropy, 2),
            }
            if is_test:
                finding["in_test_file"] = True

            findings.append(finding)

    return findings

# ─── .env File Scanner ─────────────────────────────────────────

def _scan_env_files(workspace: str) -> List[Dict[str, Any]]:
    """Find and scan all .env files in the workspace."""
    env_files = []

    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
        if '.codelens' in root:
            dirs.clear()
            continue

        for filename in filenames:
            if not filename.startswith('.env'):
                continue

            # Skip .env.example/.env.sample/.env.template/.env.demo files —
            # these contain placeholder values for documentation, not real secrets.
            lower_name = filename.lower()
            if any(lower_name.endswith(suffix) for suffix in
                   ('.example', '.sample', '.template', '.demo', '.local.example')):
                continue

            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, workspace)

            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except IOError:
                continue

            env_findings = []
            lines = content.split('\n')

            for i, line in enumerate(lines):
                stripped = line.strip()

                # Skip comments and empty lines
                if not stripped or stripped.startswith('#'):
                    continue

                # Parse KEY=VALUE format
                m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$', stripped)
                if not m:
                    continue

                key_name = m.group(1)
                raw_value = m.group(2).strip().strip('"').strip("'")

                # Skip empty values and placeholder values
                if not raw_value or _is_safe_value(raw_value):
                    continue

                # Check if key name looks like a secret
                is_secret_key = any(
                    re.match(pat, key_name) for pat in ENV_SECRET_PATTERNS
                )

                # Check entropy of the value
                entropy = _shannon_entropy(raw_value)

                if is_secret_key or entropy > ENTROPY_THRESHOLD:
                    masked = _mask_value(raw_value)
                    category = _category_from_env_key(key_name)

                    env_findings.append({
                        "type": "env_secret",
                        "file": rel_path,
                        "line": i + 1,
                        "match": masked,
                        "value": masked,
                        "line_content": stripped,
                        "severity": _severity_for_category(category),
                        "category": category,
                        "env_key": key_name,
                        "entropy": round(entropy, 2) if entropy > ENTROPY_THRESHOLD else None,
                    })

            env_files.append({
                "path": rel_path,
                "findings": env_findings,
                "variable_count": sum(1 for l in lines if re.match(r'^[A-Za-z_]', l.strip())),
                "secret_count": len(env_findings),
            })

    return env_files

# ─── .gitignore Check ──────────────────────────────────────────

def _check_env_gitignore(workspace: str, env_files: List[Dict]) -> List[str]:
    """Check if .env files are properly excluded from git via .gitignore."""
    exposed = []

    if not env_files:
        return exposed

    # Read .gitignore
    gitignore_path = os.path.join(workspace, '.gitignore')
    gitignore_patterns = []

    if os.path.exists(gitignore_path):
        try:
            with open(gitignore_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    stripped = line.strip()
                    if stripped and not stripped.startswith('#'):
                        gitignore_patterns.append(stripped)
        except IOError:
            pass

    for env_file in env_files:
        env_path = env_file["path"]
        filename = os.path.basename(env_path)

        # Check if .env is covered by .gitignore
        is_covered = False
        for pattern in gitignore_patterns:
            if pattern in ('.env', '.env*', '*.env', 'env/', '.env.local', '.env.*'):
                is_covered = True
                break
            # Check if the pattern matches the filename
            if re.match(pattern.replace('*', '.*'), filename):
                is_covered = True
                break
            # Check if the pattern matches the full path
            if re.match(pattern.replace('*', '.*'), env_path):
                is_covered = True
                break

        if not is_covered:
            exposed.append(env_path)

    return exposed

# ─── Entropy Calculation ───────────────────────────────────────

def _shannon_entropy(data: str) -> float:
    """Calculate Shannon entropy of a string.

    Higher entropy = more random = more likely to be a secret.
    Normal text: ~3.0-3.5
    Base64-encoded secrets: ~4.5-5.5
    Hex strings: ~3.5-4.0
    Random API keys: ~4.5-6.0
    """
    if not data:
        return 0.0

    length = len(data)
    if length == 0:
        return 0.0

    # Count character frequencies
    freq: Dict[str, int] = defaultdict(int)
    for ch in data:
        freq[ch] += 1

    # Calculate entropy
    entropy = 0.0
    for count in freq.values():
        probability = count / length
        if probability > 0:
            entropy -= probability * math.log2(probability)

    return entropy

# ─── Helper Functions ──────────────────────────────────────────

def _is_localhost_connection_string(value: str) -> bool:
    """Check if a value is a localhost/loopback connection string (development default).

    Local development connection strings like mongodb://localhost:27017,
    redis://127.0.0.1:6379, amqp://localhost:5672 are NOT real secrets —
    they are safe development defaults that pose no security risk.
    """
    if not value:
        return False
    # Check for localhost, 127.0.0.1, 0.0.0.0, or ::1 in connection strings
    localhost_indicators = ['localhost', '127.0.0.1', '0.0.0.0', '::1']
    value_lower = value.lower()
    return any(ind in value_lower for ind in localhost_indicators)


def _mask_value(value: str) -> str:
    """Mask a secret value, showing only the first 4 characters.

    This prevents the engine from leaking secrets in its output.
    """
    if len(value) <= 4:
        return value[:2] + "***"
    return value[:4] + "***"

def _is_safe_value(value: str) -> bool:
    """Check if a value is a known safe / false-positive pattern."""
    if not value or len(value) < MIN_SECRET_LENGTH:
        # Allow short values for private key patterns etc.
        # But flag them for password-like checks
        if len(value) < 4:
            return True

    for pattern in SAFE_VALUE_PATTERNS:
        if re.match(pattern, value.strip()):
            return True

    return False


# Known secret variable names that indicate a real secret even if the value looks placeholder-ish
_KNOWN_SECRET_VAR_PATTERNS = [
    re.compile(r'(?i)(?:AWS_SECRET_ACCESS_KEY|AWS_ACCESS_KEY_ID)\s*=', re.IGNORECASE),
    re.compile(r'(?i)(?:JWT[_\-]?SECRET|JWT[_\-]?KEY)\s*=', re.IGNORECASE),
    re.compile(r'(?i)(?:DATABASE_URL|DB_PASSWORD|SECRET_KEY)\s*=', re.IGNORECASE),
    re.compile(r'(?i)(?:STRIPE[_\-]?API[_\-]?KEY|STRIPE[_\-]?SECRET)\s*=', re.IGNORECASE),
    re.compile(r'(?i)(?:API[_\-]?KEY|API[_\-]?SECRET|PRIVATE[_\-]?KEY)\s*=', re.IGNORECASE),
    re.compile(r'(?i)(?:ENCRYPTION[_\-]?KEY|SIGNING[_\-]?KEY)\s*=', re.IGNORECASE),
]


def _is_known_secret_variable(line: str) -> bool:
    """Check if a line contains a known secret variable name assignment.

    When a line assigns to a well-known secret variable name, the value should
    be reported even if it looks like a placeholder. The variable name is a strong
    signal that this IS a real secret configuration, not example code.
    """
    return any(pat.search(line) for pat in _KNOWN_SECRET_VAR_PATTERNS)

def _is_test_file(rel_path: str) -> bool:
    """Check if a file is in a test directory or has a test file extension.

    Test files are no longer skipped entirely — instead, findings in test
    files have their severity reduced and get an in_test_file flag.
    """
    return any(indicator in rel_path for indicator in TEST_FILE_PATTERNS)

def _is_docs_or_example_file(rel_path: str) -> bool:
    """Check if a file is in a documentation or examples directory.

    Documentation and example code often contains fake credentials
    (e.g., `password = "secret"`) that are not actual security risks.
    This includes tutorial code, security examples showing how to use
    auth features, and snippet directories.
    Note: rel_path may start without a leading slash (e.g., "docs_src/foo.py"),
    so we check both "/dir/" (middle of path) and "dir/" (start of path).
    """
    # Normalize to have leading slash for consistent matching
    normalized = '/' + rel_path if not rel_path.startswith('/') else rel_path
    docs_indicators = [
        '/docs/', '/doc/', '/documentation/',
        '/examples/', '/example/', '/demos/', '/demo/',
        '/docs_src/', '/snippets/',
        '/tutorial/', '/tutorials/', '/guides/',
        '.mdx', '.rst',
        # Security tutorial code — these contain fake keys/passwords by design
        '/security/tutorial', '/auth/tutorial',
        # Test fixture directories
        '/fixtures/', '/fixture/',
        # Changelog / release notes
        '/changelog/', '/changes/', '/news/',
        # Playwright snapshot directories (auto-generated screenshots)
        '/playwright/',
        # i18n / locale directories — contain translated UI labels, NOT real secrets
        '/locales/', '/locale/', '/i18n/', '/lang/', '/translations/',
        '/intl/', '/localization/',
        # Example/sample config directories — contain placeholder credentials
        '/config_examples/', '/config_samples/',
        '/sample_configs/', '/sample_config/',
        # Package registry mock data — contain fake tokens/keys for testing
        '/registry/', '/npm_registry/', '/mock_registry/',
        # Test server mock data
        '/mock_server/', '/mock_api/',
    ]
    # Also match paths that START with these directory names
    start_indicators = [
        'docs/', 'doc/', 'documentation/',
        'examples/', 'example/', 'demos/', 'demo/',
        'docs_src/', 'snippets/',
        'tutorial/', 'tutorials/', 'guides/',
        'fixtures/', 'fixture/',
        'changelog/', 'changes/', 'news/',
        'locales/', 'locale/', 'i18n/', 'lang/', 'translations/',
        'intl/', 'localization/',
        'config_examples/', 'config_samples/',
        'sample_configs/', 'sample_config/',
        'registry/', 'npm_registry/', 'mock_registry/',
        'mock_server/', 'mock_api/',
    ]
    return (any(indicator in normalized for indicator in docs_indicators) or
            any(rel_path.startswith(indicator) for indicator in start_indicators))

def _is_example_config_file(rel_path: str) -> bool:
    """Check if a file is an example/sample config file by filename pattern.

    Files like config.example.json, settings.sample.yaml, etc. contain
    placeholder credentials and are not security risks.
    Also skips lock files (package-lock.json, yarn.lock, pnpm-lock.yaml)
    which contain registry URLs that trigger false-positive URL-embedded-password patterns.
    """
    basename = os.path.basename(rel_path).lower()
    example_indicators = [
        '.example.', '.sample.', '.template.', '.demo.',
        '.example', '.sample',  # file ends with these
    ]
    # Lock files contain registry URLs like "resolved": "https://registry.npmjs.org/..."
    # These trigger the URL-embedded-password pattern (user:pass@host) as false positives
    lock_file_names = {
        'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml',
        'bun.lockb', 'composer.lock', 'poetry.lock', 'gemfile.lock',
    }
    if basename in lock_file_names:
        return True
    return any(indicator in basename for indicator in example_indicators)

def _find_line_number(content: str, value: str) -> int:
    """Find the line number of a value in the content."""
    idx = content.find(value)
    if idx == -1:
        return 0
    return content[:idx].count('\n') + 1

def _is_template_line(line: str) -> bool:
    """Check if a line contains template expression syntax.

    Template expressions like n8n ={{$...}}, Mustache {{...}}, Django {% ... %},
    ERB <%= ... %>, and shell/JS ${...} indicate placeholder values,
    NOT hardcoded secrets.
    """
    return any(pat.search(line) for pat in TEMPLATE_LINE_PATTERNS)

def _is_env_reference_line(line: str) -> bool:
    """Check if a line reads FROM environment variables rather than hardcoding secrets.

    Patterns like process.env.PASSWORD, os.environ.get('SECRET'), os.getenv('KEY'),
    and import.meta.env.KEY are all READING from the environment, not hardcoding.
    """
    return any(pat.search(line) for pat in ENV_REFERENCE_LINE_PATTERNS)

def _is_example_or_placeholder_line(line: str) -> bool:
    """Check if a line is an example, placeholder, or comment (not real code with secrets).

    This catches patterns like:
    - placeholder: 'value'
    - e.g. "from:example@gmail.com"
    - // comment about passwords
    - * JSDoc comment with @password
    """
    return any(pat.search(line) for pat in LINE_EXCLUSION_PATTERNS)


def _is_obvious_test_value(value: str) -> bool:
    """Check if a secret value is clearly a fake/dummy test value.

    These are commonly used in test files and are not real secrets:
    - "secrethashed", "secret", "incorrect", "password", "test"
    - Simple dictionary words or obvious test patterns
    - Short non-random strings that don't look like real secrets
    """
    if not value:
        return True
    lower = value.strip().lower().strip('"\'')
    # Obvious dummy test passwords
    dummy_passwords = {
        'secret', 'secrethashed', 'hashed', 'password', 'test', 'incorrect',
        'fake', 'dummy', 'example', 'placeholder', 'changeme', 'default',
        'none', 'null', 'undefined', 'empty', 'todo', 'fixme', 'xxx',
        'abc', 'abc123', '123', '1234', '12345', '123456', '1234567890',
        'pass', 'test123', 'testing', 'mock', 'sample', 'demo',
    }
    if lower in dummy_passwords:
        return True
    # Very short values (1-4 chars) are unlikely to be real secrets
    if len(lower) <= 4 and lower.isalpha():
        return True
    # Patterns like "test_password", "fake_key", "mock_secret"
    if any(lower.startswith(p + '_') or lower.startswith(p + '-') for p in ('test', 'fake', 'mock', 'dummy', 'sample', 'example')):
        return True
    return False

def _is_template_value(value: str) -> bool:
    """Check if a value is a template expression placeholder, not a real secret.

    This catches cases where the regex-captured value itself starts with
    template syntax, e.g., ={{$credentials.password}} or {{apiKey}}.
    """
    if not value:
        return False
    stripped = value.strip()
    # n8n template expressions
    if stripped.startswith('={{') or stripped.startswith('{{ $'):
        return True
    # Mustache/Handlebars
    if stripped.startswith('{{') and stripped.endswith('}}'):
        return True
    # Django/Jinja2
    if stripped.startswith('{%') and stripped.endswith('%}'):
        return True
    # ERB
    if stripped.startswith('<%=') and stripped.endswith('%>'):
        return True
    # Shell/JS template literals
    if stripped.startswith('${') and stripped.endswith('}'):
        return True
    return False

def _is_credential_template_file(rel_path: str, content: str) -> bool:
    """Check if a file is a credential definition template (e.g., n8n /credentials/).

    Credential template files contain placeholder syntax like ={{$credentials.password}}
    which are not actual secrets but runtime references. In n8n and similar workflow
    automation tools, /credentials/ directories contain credential TYPE definitions
    with example/template values, not real secrets.
    """
    normalized = '/' + rel_path if not rel_path.startswith('/') else rel_path

    # Check if file is in a credentials path
    in_credential_path = any(pattern in normalized for pattern in CREDENTIAL_PATH_PATTERNS)

    if in_credential_path:
        # Credential definition files are templates by nature.
        # They define credential STRUCTURE with example values, not real secrets.
        # Skip them entirely to avoid false positives from:
        #   - Example connection strings: mongodb://<USER>:<PASS>@localhost
        #   - Example private keys: -----BEGIN PRIVATE KEY-----\nXIY...
        #   - n8n template syntax: ={{$credentials.password}}
        return True

    return False

def _is_path_value_misclassified_as_secret(line_text: str, raw_value: str, category: str) -> bool:
    """Check if a value flagged as a password/secret is actually a filesystem path.

    Handles the common false positive where `pwd="/tmp/archivebox"` is flagged
    as a password — `pwd` here means "present working directory", not a password.

    Also skips values that are clearly filesystem paths when the key is `pwd`.
    """
    if category != "password":
        return False

    line_stripped = line_text.strip()

    # Check if the key is `pwd` (present working directory, not password)
    # Pattern: pwd="..." or pwd: "..." or pwd = "..."
    if re.match(r'(?i)\bpwd\b\s*(?:=|:)\s*["\']', line_stripped):
        # If the value looks like a path, it's "present working directory"
        if _looks_like_path(raw_value):
            return True

    return False


def _looks_like_path(value: str) -> bool:
    """Check if a value looks like a filesystem path rather than a secret."""
    if not value:
        return False
    # Absolute paths
    if re.match(r'^/(tmp|var|home|usr|etc|opt|srv|root|mnt|dev|proc|sys|run)/', value):
        return True
    # Relative paths
    if re.match(r'^\.\.?/', value):
        return True
    # Paths with common directory prefixes
    if re.match(r'^~/', value):
        return True
    return False


def _is_url_test_data(raw_value: str, line_text: str) -> bool:
    """Check if a value is URL parsing test data with example/test domains.

    URL test data like "http://us:pa@ex.co:42/..." contains user:pass@
    format but with example domains — these are test fixtures, not real credentials.
    """
    # Check for example/test domain patterns in URL values
    test_domain_indicators = [
        'example.com', 'example.org', 'example.net',
        'ex.co', 'test.com', 'test.org',
        'localhost', '127.0.0.1', '0.0.0.0',
        'httpbin.org', 'mocky.io', 'postman-echo.com',
    ]
    value_lower = raw_value.lower()
    line_lower = line_text.lower()
    for domain in test_domain_indicators:
        if domain in value_lower or domain in line_lower:
            return True
    return False


def _is_enum_or_constant_definition(line_text: str, ext: str) -> bool:
    """Check if a line is an enum member or constant definition that contains
    password/secret keywords in its VALUE but is not an actual secret.

    Common false positive patterns in TypeScript/JavaScript:
      IncorrectEmailPassword = "incorrect-email-password",
      IncorrectPassword = "incorrect-password",
      UserMissingPassword = "missing-password",
      PasswordResetToken = "password-reset-token",

    These are error code enum values where the string is a machine-readable
    identifier (kebab-case), not an actual hardcoded password.

    Also handles Python enum patterns:
      INCORRECT_PASSWORD = "incorrect-password"
      MISSING_TOKEN = "missing-token"
    """
    stripped = line_text.strip()

    # TypeScript/JavaScript enum pattern: Identifier = "kebab-case-value",
    # The key insight: if the value is kebab-case (contains hyphens) AND the
    # line starts with an identifier (PascalCase or ALL_CAPS) followed by =,
    # it's almost certainly an enum/constant, not a real password assignment.
    if ext in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}:
        # Match: PascalCaseOrALL_CAPS = "kebab-case-or-snake-value",
        if re.match(r'^[A-Z][A-Za-z0-9_]*\s*=\s*["\'][\w-]+["\']\s*,?\s*$', stripped):
            # If the value contains hyphens (kebab-case), it's an identifier, not a secret
            value_match = re.search(r'["\']([^"\']+)["\']', stripped)
            if value_match and '-' in value_match.group(1):
                return True
        # Match: const Identifier: Type = { ... } with enum-like content
        # This handles: const ErrorCode = { ... } patterns
        if re.match(r'^(?:export\s+)?(?:const|let|var|enum)\s+Error', stripped, re.IGNORECASE):
            return True

    # Python enum/constant pattern
    if ext == ".py":
        # ALL_CAPS = "kebab-case-value"  or  PascalCase = "kebab-value"
        if re.match(r'^[A-Z][A-Z0-9_]*\s*=\s*["\'][\w-]+["\']', stripped):
            # But NOT if the variable name contains known secret keywords
            var_name_match = re.match(r'^([A-Z][A-Z0-9_]*)\s*=', stripped)
            if var_name_match:
                var_name = var_name_match.group(1)
                _secret_keywords = {'SECRET', 'KEY', 'PASSWORD', 'TOKEN', 'CREDENTIAL',
                                    'PRIVATE', 'API_KEY', 'ACCESS_KEY'}
                if any(kw in var_name for kw in _secret_keywords):
                    return False  # This is a real secret assignment, not an enum
            value_match = re.search(r'["\']([^"\']+)["\']', stripped)
            if value_match and '-' in value_match.group(1):
                return True

    return False


def _reduce_severity(severity: str) -> str:
    """Reduce severity level for findings in test files.

    critical → medium, high → low, medium → low, low → low
    """
    reduction_map = {
        "critical": "medium",
        "high": "low",
        "medium": "low",
        "low": "low",
    }
    return reduction_map.get(severity, "low")

def _infer_category_from_value(value: str) -> str:
    """Infer the likely secret category from the value's format."""
    # JWT tokens
    if value.startswith('eyJ'):
        return "token"
    # GitHub tokens
    if value.startswith('ghp_') or value.startswith('gho_') or value.startswith('github_pat_'):
        return "api_key"
    # Stripe keys
    if value.startswith('pk_') or value.startswith('sk_'):
        return "api_key"
    # OpenAI keys
    if value.startswith('sk-'):
        return "api_key"
    # AWS keys
    if value.startswith('AKIA'):
        return "api_key"
    # Google keys
    if value.startswith('AIza'):
        return "api_key"
    # Slack tokens
    if value.startswith('xox'):
        return "api_key"
    # SendGrid keys
    if value.startswith('SG.'):
        return "api_key"
    # DigitalOcean tokens
    if value.startswith('dop_v1_'):
        return "api_key"
    # Private keys
    if 'PRIVATE KEY' in value:
        return "private_key"
    # Connection strings
    if re.match(r'^(?:mongodb|postgres|mysql|redis|amqp)://', value):
        return "connection_string"
    # Default to token for high-entropy strings
    return "token"

def _category_from_env_key(key_name: str) -> str:
    """Determine secret category from an environment variable name."""
    key_upper = key_name.upper()

    if any(kw in key_upper for kw in ('PASSWORD', 'PASSWD', 'PWD', 'DB_PASS')):
        return "password"
    if any(kw in key_upper for kw in ('DATABASE_URL', 'MONGO_URI', 'REDIS_URL', 'DB_HOST', 'AMQP')):
        return "connection_string"
    if any(kw in key_upper for kw in ('API_KEY', 'APIKEY', 'STRIPE', 'AWS_', 'GCP_', 'AZURE_')):
        return "api_key"
    if any(kw in key_upper for kw in ('TOKEN', 'JWT', 'BEARER', 'ACCESS_KEY')):
        return "token"
    if any(kw in key_upper for kw in ('CLIENT_SECRET', 'CONSUMER_SECRET', 'OAUTH')):
        return "oauth"
    if any(kw in key_upper for kw in ('SECRET_KEY', 'SECRET', 'SIGNING_KEY', 'ENCRYPTION')):
        return "secret_key"
    if any(kw in key_upper for kw in ('WEBHOOK', 'SLACK_TOKEN', 'DISCORD')):
        return "webhook"
    if any(kw in key_upper for kw in ('PRIVATE_KEY', 'PRIVATE_KEY_PEM')):
        return "private_key"

    return "token"  # Default for unknown high-entropy env vars

def _severity_for_category(category: str) -> str:
    """Return the default severity for a secret category."""
    severity_map = {
        "private_key": "critical",
        "password": "critical",
        "connection_string": "critical",
        "api_key": "high",
        "token": "high",
        "secret_key": "high",
        "oauth": "high",
        "webhook": "medium",
    }
    return severity_map.get(category, "high")

def _deduplicate_findings(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicate findings (same file, line, category)."""
    seen: Set[Tuple[str, int, str]] = set()
    unique = []

    for finding in findings:
        key = (finding.get("file", ""), finding.get("line", 0), finding.get("category", ""))
        if key not in seen:
            seen.add(key)
            unique.append(finding)

    return unique

# ─── Stats & Risk Computation ──────────────────────────────────

def _compute_stats(
    findings: List[Dict[str, Any]],
    env_files: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Compute statistics from findings."""
    by_category: Dict[str, int] = defaultdict(int)
    by_severity: Dict[str, int] = defaultdict(int)

    for f in findings:
        by_category[f.get("category", "unknown")] += 1
        by_severity[f.get("severity", "unknown")] += 1

    return {
        "total_secrets": len(findings),
        "by_category": dict(by_category),
        "by_severity": dict(by_severity),
        "env_files_checked": len(env_files),
    }

def _compute_risk(findings: List[Dict[str, Any]], env_exposed: List[str]) -> str:
    """Compute overall risk level based on findings."""
    if not findings and not env_exposed:
        return "none"

    # If .env files are not in .gitignore, that's a critical risk
    if env_exposed:
        has_critical_env = any(
            any(f.get("severity") == "critical" for f in _get_env_findings_for_path(findings, p))
            for p in env_exposed
        )
        if has_critical_env:
            return "critical"

    # Check findings by severity
    severities = {f.get("severity", "low") for f in findings}
    if "critical" in severities:
        return "critical"
    if "high" in severities:
        critical_count = sum(1 for f in findings if f.get("severity") == "critical")
        high_count = sum(1 for f in findings if f.get("severity") == "high")
        if high_count >= 3:
            return "critical"
        return "high"
    if "medium" in severities:
        return "medium"

    return "low"

def _get_env_findings_for_path(findings: List[Dict], path: str) -> List[Dict]:
    """Get findings that belong to a specific .env file path."""
    return [f for f in findings if f.get("file") == path]

# ─── Recommendations ───────────────────────────────────────────

def _generate_recommendations(
    findings: List[Dict[str, Any]],
    env_exposed: List[str],
    stats: Dict[str, Any]
) -> List[str]:
    """Generate actionable recommendations based on findings."""
    recs = []

    if not findings and not env_exposed:
        recs.append("No secrets detected in the codebase. Good practice!")
        return recs

    # Critical findings
    critical_findings = [f for f in findings if f.get("severity") == "critical"]
    if critical_findings:
        files_with_critical = set(f["file"] for f in critical_findings)
        recs.append(
            f"CRITICAL: Found {len(critical_findings)} hardcoded secret(s) with critical severity. "
            f"Rotate these credentials immediately and use environment variables or a secrets manager. "
            f"Files: {', '.join(list(files_with_critical)[:5])}"
        )

    # .env exposure
    if env_exposed:
        recs.append(
            f"EXPOSED: {len(env_exposed)} .env file(s) are not in .gitignore. "
            f"Add '.env*' to your .gitignore immediately. "
            f"Files: {', '.join(env_exposed)}"
        )

    # Private keys
    private_keys = [f for f in findings if f.get("category") == "private_key"]
    if private_keys:
        recs.append(
            f"PRIVATE KEYS: Found {len(private_keys)} hardcoded private key(s). "
            f"These should NEVER be in source code. Use a secrets manager or vault. "
            f"If already committed, rotate the keys and consider using git-filter-branch to remove history."
        )

    # Passwords
    passwords = [f for f in findings if f.get("category") == "password"]
    if passwords:
        recs.append(
            f"PASSWORDS: Found {len(passwords)} hardcoded password(s). "
            f"Use environment variables or a secrets manager instead. "
            f"Never commit passwords to version control."
        )

    # Connection strings
    conn_strings = [f for f in findings if f.get("category") == "connection_string"]
    if conn_strings:
        recs.append(
            f"CONNECTION STRINGS: Found {len(conn_strings)} hardcoded connection string(s) with credentials. "
            f"Use environment variables (e.g., DATABASE_URL) or config files outside the repo."
        )

    # API keys
    api_keys = [f for f in findings if f.get("category") == "api_key"]
    if api_keys:
        recs.append(
            f"API KEYS: Found {len(api_keys)} hardcoded API key(s). "
            f"Move them to environment variables or a .env file (and add .env to .gitignore)."
        )

    # Tokens
    tokens = [f for f in findings if f.get("category") == "token"]
    if tokens:
        recs.append(
            f"TOKENS: Found {len(tokens)} hardcoded token(s). "
            f"Use OAuth flows or environment variables for token management."
        )

    # Secret keys
    secret_keys = [f for f in findings if f.get("category") == "secret_key"]
    if secret_keys:
        recs.append(
            f"SECRET KEYS: Found {len(secret_keys)} hardcoded framework secret key(s). "
            f"These should be loaded from environment variables in production. "
            f"Generate new secrets with: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
        )

    # General advice
    if findings:
        recs.append(
            "GENERAL: Use a .env file for local development (add to .gitignore), "
            "and a secrets manager (AWS Secrets Manager, HashiCorp Vault, etc.) for production."
        )

    return recs
