"""
Secrets Detection Engine for CodeLens — v4
Detects hardcoded secrets, API keys, tokens, passwords, and connection strings
in source code that should never be committed.

Answers: "Are there any secrets or credentials hardcoded in the codebase?"
Answers: "Are .env files properly excluded from version control?"

Architecture:
- Pattern-based detection: regex patterns for known secret formats
- Entropy-based detection: flag high-entropy strings that look like secrets
- .env file scanner: read all .env files and report every secret variable
- .gitignore check: verify .env files are excluded from version control
- Context-aware filtering: language-specific false-positive elimination
  (Python format placeholders, SQL templates, identifier constants, type annotations)

Secret Categories (by severity):
- critical: private_key, password, connection_string
- high:     api_key, token, secret_key, oauth
- medium:   webhook

Each finding includes masked value (first 4 chars + "***") to prevent
the engine itself from becoming a secret-leaking vector.

v4 improvements:
- Python context-aware filtering: SQL templates, format placeholders, identifiers,
  type annotations, default prompt arguments
- Expanded safe value patterns for Python identifiers and framework constants
- Line-level context analysis to eliminate false positives from template code
"""

import os
import re
import math
from typing import Dict, List, Any, Optional, Set, Tuple
from collections import defaultdict
from utils import DEFAULT_IGNORE_DIRS

# ─── Configuration ─────────────────────────────────────────────

SOURCE_EXTENSIONS = {
    ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".py", ".rs", ".env", ".yaml", ".yml",
    ".json", ".toml", ".cfg", ".ini", ".conf",
}

# Performance limits for large codebases
MAX_FILES_PER_RUN = 3000

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
            # OpenAI-style keys (sk-...)
            r'["\']?(sk-[A-Za-z0-9_\-]{20,})["\']?',
            # Stripe-style keys (pk_*, sk_*)
            r'["\']?(pk_(?:test|live)_[A-Za-z0-9]{24,})["\']?',
            r'["\']?(sk_(?:test|live)_[A-Za-z0-9]{24,})["\']?',
            # GitHub personal access tokens (ghp_*)
            r'["\']?(ghp_[A-Za-z0-9]{36,})["\']?',
            # GitHub OAuth tokens (gho_*)
            r'["\']?(gho_[A-Za-z0-9]{36,})["\']?',
            # GitHub fine-grained tokens (github_pat_*)
            r'["\']?(github_pat_[A-Za-z0-9_]{22,})["\']?',
            # Google API keys (AIza...)
            r'["\']?(AIza[A-Za-z0-9_\-]{35})["\']?',
            # AWS access key IDs (AKIA...)
            r'["\']?(AKIA[A-Z0-9]{16})["\']?',
            # AWS secret access keys (40-char base64 after known key)
            r'(?i)aws[_\-]?secret[_\-]?access[_\-]?key\s*(?:=|:)\s*["\']([A-Za-z0-9/+=]{40})["\']',
            # SendGrid API keys (SG.)
            r'["\']?(SG\.[A-Za-z0-9_\-]{22,}\.[A-Za-z0-9_\-]{43,})["\']?',
            # Twilio API keys
            r'(?i)twilio[_\-]?api[_\-]?key\s*(?:=|:)\s*["\']([A-Za-z0-9]{32,})["\']',
            # Mailgun API keys
            r'(?i)mailgun[_\-]?api[_\-]?key\s*(?:=|:)\s*["\']([A-Za-z0-9\-]{32,})["\']',
            # Slack API tokens (xoxb-*, xoxp-*)
            r'["\']?(xox[bpas]-[A-Za-z0-9\-]{10,})["\']?',
            # Heroku API keys
            r'(?i)heroku[_\-]?api[_\-]?key\s*(?:=|:)\s*["\']([A-Za-z0-9\-]{36,})["\']',
        ],
    },

    # ── Passwords ───────────────────────────────────────────────
    "password": {
        "severity": "critical",
        "category": "password",
        "patterns": [
            # Generic password assignments (MUST have quotes around value)
            r'(?i)(?:password|passwd|pwd)\s*(?:=|:)\s*["\']([^"\']{6,})["\']',
            # Environment variable style
            r'(?i)(?:DB_PASSWORD|DATABASE_PASSWORD|MYSQL_PASSWORD|POSTGRES_PASSWORD|PG_PASSWORD|MONGO_PASSWORD|REDIS_PASSWORD)\s*(?:=|:)\s*["\']?([^\s"\'`]{6,})["\']?',
            # URL-embedded passwords: user:pass@  (requires @ and domain after)
            r'(?i)[\w+\-\.]+:([^\s@"\']{4,})@[A-Za-z0-9\-\.]+\.[A-Za-z]{2,}',
            # Config-style password (JSON key-value)
            r'(?i)["\']password["\']\s*:\s*["\']([^"\']{6,})["\']',
            # Python-style (MUST have quotes around value)
            r'(?i)password\s*=\s*["\']([^"\']{6,})["\']',
            # Java properties style
            r'(?i)(?:spring\.datasource\.password|jdbc\.password)\s*=\s*([^\s]{6,})',
            # YAML-style passwords (MUST have quotes around value)
            # Note: Only matches quoted values to avoid false positives on
            # `password: someVariable` or `password: data.password`
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
            # DigitalOcean tokens
            r'["\']?(dop_v1_[A-Za-z0-9]{40,})["\']?',
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
    r'(?i)^(example|test|mock|dummy|fake|placeholder|xxx|changeme|your[_-]?key|insert[_-]?key|replace[_-]?me|todo)',
    r'(?i)^(process\.env|os\.environ|env\()',
    r'^\$\{',  # Template variable
    r'(?i)^(true|false|null|none|undefined|nil)$',
    r'^\*+$',   # All asterisks
    r'(?i)^(password|secret|token|key)$',  # Just the word itself
    # Rust / Swift / Kotlin type annotations — not actual secrets
    r'^(String|Option|Some|None|Result|Ok|Err|Vec|Box|Arc|Rc|Cell|RefCell|Cow|HashMap|HashSet|BTreeMap|BTreeSet|Duration|Instant|PathBuf|IpAddr|Ipv4Addr|Ipv6Addr|SocketAddr|Url|Uri|DateTime|OffsetDateTime|NaiveDateTime|Uuid)',
    r'^(bool|i8|i16|i32|i64|i128|isize|u8|u16|u32|u64|u128|usize|f32|f64|char|str)',
    # Rust generic type parameters (e.g., Option<String>, Result<bool, Error>)
    r'^[A-Z][A-Za-z0-9]+<[A-Za-z0-9_,\s]+>$',
    # Common function calls wrapping a type (e.g., Some("value"))
    r'^Some\(',
    # decode/encode function names (not secrets)
    r'(?i)^(decode|encode|decrypt|encrypt|hash|verify|validate|escape|unescape)$',
    # Translation/localization keys
    r'(?i)^(password_field|password_label|password_hint|password_confirm|password_reset|password_new|password_current|password_enter|password_forgot|password_change|password_required|password_strength|password_mismatch)$',
    # ── v4: Python format placeholders — never actual secrets ──
    r'^%\([a-zA-Z_]\w*\)[sdiroxXefgG]$',  # %(name)s, %(password)s, etc.
    r'^\{[a-zA-Z_]\w*\}$',                  # {name}, {password}, etc.
    r'^\{[a-zA-Z_]\w*\.[a-zA-Z_]\w*\}$',  # {obj.field}
    # ── v4: Python/framework identifier constants — not secrets ──
    r'^_[a-zA-Z]',                             # Underscore-prefixed identifiers (_password_reset_token)
    r'(?i)^[a-z_]+_[a-z_]+$',                  # snake_case identifiers (session_key, reset_token)
    # ── v4: SQL template keywords at start — not secret values ──
    r'(?i)^(ALTER|CREATE|DROP|INSERT|UPDATE|DELETE|SELECT|GRANT|REVOKE)\s',
    # ── v4: Prompt/label strings (end with colon+space or are short UI text) ──
    r'(?i)^(Enter|Type|Input|Provide|Set|Choose|Confirm)\s',  # UI prompts
    r':\s*$',                                   # Ends with colon (label)
    # ── v4: Django/framework constant patterns ──
    r'(?i)^(INTERNAL_|EXTERNAL_|DEFAULT_|AUTO_|MAX_|MIN_|OPT_|CFG_)',
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
    re.compile(r'^\$\{'),                                     # Template literals
    re.compile(r'^[A-Za-z0-9+/]+=*$'),                        # Pure base64 (likely encoded data, not secret)
]

def detect_secrets(
    workspace: str,
    severity: Optional[str] = None,
    config: Optional[Dict] = None,
    max_files: int = MAX_FILES_PER_RUN
) -> Dict[str, Any]:
    """
    Detect hardcoded secrets, API keys, tokens, and passwords in source code.

    Scans source files for known secret patterns AND high-entropy strings.
    Also scans .env files and checks if they are in .gitignore.

    Args:
        workspace: Absolute path to workspace
        severity: Optional filter: "critical", "high", "medium"
        config: CodeLens config dict

    Returns:
        Dict with findings, stats, risk level, env exposure, and recommendations
    """
    workspace = os.path.abspath(workspace)

    findings: List[Dict[str, Any]] = []
    env_files: List[Dict[str, Any]] = []
    env_exposed: List[str] = []
    files_scanned = 0
    truncated = False

    # ─── Phase 1: Pattern-based scanning ──────────────────────
    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
        if '.codelens' in root:
            dirs.clear()
            continue

        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in SOURCE_EXTENSIONS:
                continue

            # File-count limit to prevent timeout on huge repos
            if files_scanned >= max_files:
                truncated = True
                break

            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, workspace)

            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except IOError:
                continue

            files_scanned += 1

            # Skip files in test directories
            if _is_test_file(rel_path):
                continue

            # Skip documentation/example directories (contain fake credentials)
            if _is_docs_or_example_file(rel_path):
                continue

            # Scan for patterns
            file_findings = _scan_file_patterns(content, rel_path, ext)
            findings.extend(file_findings)

            # Entropy-based scanning for code files
            if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".py", ".rs"}:
                entropy_findings = _scan_file_entropy(content, rel_path, ext)
                findings.extend(entropy_findings)

        if truncated:
            break

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
        "stats": {**stats, "truncated": truncated},
        "risk": risk,
        "findings": findings[:200],  # Cap to avoid explosion
        "env_exposed": env_exposed,
        "recommendations": recommendations,
    }

# ─── Pattern-based Scanner ─────────────────────────────────────

def _scan_file_patterns(content: str, rel_path: str, ext: str) -> List[Dict[str, Any]]:
    """Scan file content for known secret patterns."""
    findings = []

    # Skip i18n/locale JSON files — they contain translated "password" etc.
    # which are not real secrets, just UI labels
    if _is_locale_file(rel_path):
        return findings

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
                    if _is_safe_value(raw_value):
                        continue

                    # Context-aware false-positive filtering for Rust files
                    # Rust type annotations like `password: String` or `password: Option<String>`
                    # are NOT secrets — they are struct field declarations
                    if ext == '.rs' and _is_rust_type_annotation(content, match.start(), raw_value):
                        continue

                    # Skip JSON/YAML/TOML values that are clearly type references
                    # e.g., "type": "password" in config schemas
                    if ext in ('.json', '.yaml', '.yml', '.toml') and _is_schema_type_ref(content, match.start(), raw_value):
                        continue

                    # Skip JS/TS property assignments where the value is a variable reference,
                    # function call, or expression — not a hardcoded string literal.
                    # e.g., `password: someVariable`, `password: func(args)`, `password: obj.prop`
                    if ext in ('.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx') and _is_js_property_assignment(content, match.start(), raw_value):
                        continue

                    # v4: Python context-aware false-positive filtering
                    # Python has many patterns that look like secrets but aren't:
                    # - SQL templates with %(password)s placeholders
                    # - Type annotations: password: str
                    # - Default prompt args: prompt="Password: "
                    # - String constants used as keys: INTERNAL_TOKEN = "_reset_token"
                    # - Format strings: "password=%(password)s"
                    if ext == '.py' and _is_python_non_secret(content, match.start(), raw_value, category):
                        continue

                    # Mask the value for safe reporting
                    masked = _mask_value(raw_value)

                    findings.append({
                        "type": "pattern_match",
                        "file": rel_path,
                        "line": line_num,
                        "match": masked,
                        "severity": definition["severity"],
                        "category": definition["category"],
                    })
            except re.error:
                continue

    return findings

# ─── Entropy-based Scanner ─────────────────────────────────────

def _scan_file_entropy(content: str, rel_path: str, ext: str) -> List[Dict[str, Any]]:
    """Scan file content for high-entropy strings that look like secrets.

    Uses Shannon entropy to identify strings that are too random to be
    normal text or code, and are long enough to be a credential.
    """
    findings = []

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

        # Skip candidates in test/fixture files
        if _is_test_file(rel_path):
            continue

        # Calculate Shannon entropy
        entropy = _shannon_entropy(candidate)

        if entropy > ENTROPY_THRESHOLD:
            # Check if this value was already caught by a pattern
            masked = _mask_value(candidate)

            # Find line number
            line_num = _find_line_number(content, candidate)

            # Determine likely category based on context
            likely_category = _infer_category_from_value(candidate)

            findings.append({
                "type": "entropy_match",
                "file": rel_path,
                "line": line_num,
                "match": masked,
                "severity": _severity_for_category(likely_category),
                "category": likely_category,
                "entropy": round(entropy, 2),
            })

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

def _is_test_file(rel_path: str) -> bool:
    """Check if a file is in a test directory."""
    test_indicators = [
        '.test.', '.spec.', '__tests__', 'test/', 'tests/',
        'spec/', 'specs/', 'fixtures/', '__mocks__',
        '.stories.', '.story.',
    ]
    return any(indicator in rel_path for indicator in test_indicators)

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
    ]
    # Also match paths that START with these directory names
    start_indicators = [
        'docs/', 'doc/', 'documentation/',
        'examples/', 'example/', 'demos/', 'demo/',
        'docs_src/', 'snippets/',
        'tutorial/', 'tutorials/', 'guides/',
        'fixtures/', 'fixture/',
        'changelog/', 'changes/', 'news/',
    ]
    return (any(indicator in normalized for indicator in docs_indicators) or
            any(rel_path.startswith(indicator) for indicator in start_indicators))


def _is_locale_file(rel_path: str) -> bool:
    """Check if a file is an i18n/locale translation file.

    Locale files contain translated strings like "password", "secret", etc.
    These are UI labels, not actual credentials.
    """
    locale_indicators = [
        '/locales/', '/locale/', '/i18n/', '/lang/', '/languages/',
        '/translations/', '/messages/', '/intl/',
        'locales/', 'locale/', 'i18n/', 'lang/', 'languages/',
    ]
    # Check if it's a JSON file in a locale directory
    if rel_path.endswith('.json'):
        for indicator in locale_indicators:
            if indicator in rel_path:
                return True
    return False


def _is_rust_type_annotation(content: str, match_start: int, raw_value: str) -> bool:
    """Check if a password/secret match in a Rust file is actually a type annotation
    or a non-string-literal value.

    Rust struct fields look like:
        password: String
        password: Option<String>
        secret_key: &'static str

    Rust struct initialization with variable values:
        password: verge.webdav_password.clone().unwrap_or_default()
        password: config.password.clone()

    These are NOT hardcoded secrets — they are type declarations or variable references.
    """
    # Look at the surrounding context (100 chars before the match)
    context_start = max(0, match_start - 100)
    context = content[context_start:match_start + len(raw_value) + 100]

    # Check the full line containing the match
    line_start = context.rfind('\n', 0, match_start - context_start) + 1
    line_end = context.find('\n', match_start - context_start)
    if line_end == -1:
        line_end = len(context)
    line = context[line_start:line_end].strip()

    # Rust struct field pattern: `field_name: Type`
    # Check if the line looks like a struct field declaration
    # Pattern: word colon followed by a type (not = sign)
    if re.search(r'\b\w+\s*:\s*(?:Option<)?(?:String|bool|i32|i64|u32|u64|f32|f64|Vec|Box|Arc|Rc|PathBuf|Url|Uri|Cow|HashMap|Duration|Instant|char|str|IpAddr)', line):
        return True

    # Rust struct field with reference: `password: &'static str`
    if re.search(r"\b\w+\s*:\s*(?:&'?\w*\s+)?str\b", line):
        return True

    # Check if it's a function parameter type annotation: `password: &str`
    if re.search(r'\b\w+\s*:\s*(?:&str|&mut\s+str|&String)\b', line):
        return True

    # Derive/attribute context: #[derive(...)] or struct definition nearby
    if re.search(r'#\[derive\(|\bstruct\s+\w+', line):
        return True

    # Rust struct initialization with variable/method chain:
    # `password: some_var.clone()` or `password: config.password.clone()`
    # `password: value.unwrap_or_default()` etc.
    # These are NOT hardcoded secrets
    if re.search(r'\b\w+\s*:\s*\w+', line) and not re.search(r'\b\w+\s*:\s*["\']', line):
        # If the value after colon is NOT a string literal, it's a variable reference
        return True

    return False


def _is_schema_type_ref(content: str, match_start: int, raw_value: str) -> bool:
    """Check if a password/secret match in a JSON/YAML/TOML file is a schema type reference.

    Config schemas often have entries like:
        { "type": "password" }
        { "format": "password" }

    These describe the input type, not an actual secret value.
    """
    context_start = max(0, match_start - 80)
    context = content[context_start:match_start + len(raw_value) + 30]

    # JSON schema "type": "password" or "format": "password"
    if re.search(r'["\'](?:type|format|input_type|widget)["\']\s*:\s*["\']password["\']', context):
        return True

    # YAML/TOML: type = "password" or type: password
    if re.search(r'(?:type|format|input_type)\s*[=:]\s*["\']?password["\']?', context):
        return True

    return False


def _is_js_property_assignment(content: str, match_start: int, raw_value: str) -> bool:
    """Check if a password/secret match in a JS/TS file is a property assignment
    with a non-literal value (variable reference, function call, etc.).

    Examples that are NOT secrets:
        password: someVariable
        password: func(args)
        password: obj.prop
        password: arr[index]

    Only `password: "hardcoded_string"` is an actual secret.
    """
    context_start = max(0, match_start - 60)
    context_end = min(len(content), match_start + len(raw_value) + 60)
    context = content[context_start:context_end]

    # Check the line containing the match
    line_start = context.rfind('\n', 0, match_start - context_start) + 1
    line_end = context.find('\n', match_start - context_start)
    if line_end == -1:
        line_end = len(context)
    line = context[line_start:line_end].strip()

    # If the value after the colon is NOT a string literal, it's a variable reference
    # Pattern: `password: someVar` or `password: func()` or `password: obj.prop`
    # A real secret would be: `password: "actual_secret_value"`
    # The captured group already stripped quotes, so raw_value is the content without quotes.
    # But we can check if the original match context shows it's not a string literal.
    # Look at the character right after the colon/equals and before the value
    match_in_context = match_start - context_start
    before_value = context[max(0, match_in_context - 5):match_in_context]
    after_value = context[match_in_context + len(raw_value):match_in_context + len(raw_value) + 5]

    # If the value is preceded by a quote, it's a real string literal — keep it
    # If preceded by a variable name or function call, it's not a hardcoded secret
    if re.search(r'[:=]\s*[a-zA-Z_$]', before_value.lstrip()[-2:] + raw_value[:1]):
        # Check if the value starts with a known JS/TS identifier pattern
        # (not a string literal since we already extracted the content from quotes)
        # The raw_value was extracted from quotes, so if the original line has
        # quotes around it, it's a real string.
        # If the original line has no quotes, it's a variable reference.
        if not re.search(r'[:=]\s*["\']', before_value + context[match_in_context:match_in_context + 1]):
            # No quotes around value — it's a variable reference or expression
            return True

    # Also check if the line pattern looks like a property assignment with expression
    if re.match(r'.*\b(?:password|passwd|pwd|secret|token)\s*:\s*[a-zA-Z_$]', line):
        return True

    return False


def _is_python_non_secret(content: str, match_start: int, raw_value: str, category: str) -> bool:
    """Check if a password/secret/token match in a Python file is actually a non-secret pattern.

    Python-specific false positives that this catches:
    1. SQL template strings: 'ALTER USER %(user)s IDENTIFIED BY "%(password)s"'
       → The captured value is a SQL keyword or format placeholder, not a real password
    2. Type annotations: password: str, password: Optional[str]
       → These are function parameter types, not assignments
    3. Default prompt arguments: prompt="Password: ", label="Enter password"
       → UI text, not hardcoded secrets
    4. String constants used as identifiers/keys:
       INTERNAL_RESET_SESSION_TOKEN = "_password_reset_token"
       → The value is a key name, not a real token
    5. Python format strings with secret-like keys:
       "password=%(password)s" or "user={username}"
       → Template content, not actual credentials
    6. Variable references / attribute access:
       self.password = form.cleaned_data['password']
       password = request.POST.get('password')
       → Dynamic values, not hardcoded
    7. Django/framework settings references:
       PASSWORD_HASHERS, PASSWORD_VALIDATORS, etc.
       → Configuration references, not actual passwords
    """
    # Get the line containing the match
    line_start = content.rfind('\n', 0, match_start) + 1
    line_end = content.find('\n', match_start)
    if line_end == -1:
        line_end = len(content)
    line = content[line_start:line_end].strip()

    # ── Check 1: SQL template strings ──
    # Lines containing SQL DDL/DML keywords with Python format placeholders
    sql_keywords = ['ALTER', 'CREATE', 'DROP', 'INSERT', 'UPDATE', 'DELETE',
                    'SELECT', 'GRANT', 'REVOKE', 'IDENTIFIED', 'SET PASSWORD']
    line_upper = line.upper()
    if any(kw in line_upper for kw in sql_keywords):
        # This is a SQL template, not a hardcoded secret
        return True

    # ── Check 2: Python format placeholder patterns in the value ──
    # %(name)s or {name} inside the matched string indicate template content
    if re.search(r'%\([a-zA-Z_]\w*\)[sdiroxXefgG]', raw_value):
        return True
    if re.search(r'\{[a-zA-Z_]\w*\}', raw_value):
        return True

    # ── Check 3: Type annotations in function signatures ──
    # def func(password: str) or def func(password: Optional[str])
    if re.match(r'def\s+\w+.*password\s*:\s*(?:Optional\[)?(?:str|bytes|Union)', line, re.IGNORECASE):
        return True
    # Class field type annotation: password: str = ...
    if re.match(r'(?:\s+)?password\s*:\s*(?:Optional\[)?(?:str|bytes)', line, re.IGNORECASE):
        return True

    # ── Check 4: Default prompt/label arguments ──
    # prompt="Password: ", label="Enter password", help_text="..."
    # These are UI strings, not secrets
    if category == "password":
        # Check if the variable name suggests it's a label/prompt, not a secret
        if re.match(r'.*\b(?:prompt|label|help_text|placeholder|message|title|header|text|display_name|verbose_name)\s*=\s*["\']', line, re.IGNORECASE):
            return True
        # Check if the value looks like a prompt (contains colon+space, question mark)
        if raw_value.strip().endswith(':') or raw_value.strip().endswith(': ') or '?' in raw_value:
            return True
        # Check if the value is a short UI string (< 20 chars, starts with common words)
        if len(raw_value) < 20 and re.match(r'(?i)^(Enter |Type |Input |Provide |Your |The |New |Old |Current |Repeat |Confirm )', raw_value):
            return True

    # ── Check 5: String constants used as identifiers/keys ──
    # CONSTANT_NAME = "_some_identifier" — the value is a key, not a secret
    if category in ("token", "secret_key"):
        # Check if the LHS is a module-level constant (ALL_CAPS)
        if re.match(r'^[A-Z][A-Z0-9_]+\s*=\s*["\']', line):
            # Check if the value looks like an identifier (underscore-separated, lowercase)
            if re.match(r'^_?[a-z][a-z0-9_]*$', raw_value):
                return True
        # Check if the variable name contains "INTERNAL", "KEY_NAME", "SESSION_KEY", etc.
        if re.match(r'^[A-Z_]*(?:INTERNAL|EXTERNAL|SESSION|CSRF|KEY_NAME|FIELD|PARAM|HEADER|COOKIE|ATTR)\w*\s*=\s*["\']', line):
            return True

    # ── Check 6: Variable references and attribute access ──
    # self.password = obj.password  → not a hardcoded string
    # password = form.cleaned_data['password']  → not hardcoded
    # password = request.POST.get('password')  → not hardcoded
    if category == "password":
        # If the RHS is a variable reference or method call, not a string literal
        # Match: password = something. (not password = "literal")
        rhs_match = re.match(r'(?:\w+\.)*password\s*=\s*(.+)', line, re.IGNORECASE)
        if rhs_match:
            rhs = rhs_match.group(1).strip()
            # If RHS doesn't start with a quote, it's a variable reference
            if rhs and rhs[0] not in ('"', "'"):
                return True
            # If RHS accesses an attribute or calls a method: form.data, request.GET
            if re.match(r'(?:self\.)?\w+\.\w+', rhs):
                return True
            # If RHS is a method call: getpass(), input(), etc.
            if re.match(r'\w+\(', rhs):
                return True

    # ── Check 7: Django/framework settings references ──
    # PASSWORD_HASHERS = [...], PASSWORD_VALIDATORS = [...]
    # AUTH_PASSWORD_VALIDATORS, etc.
    if category in ("password", "secret_key"):
        if re.match(r'^[A-Z_]*(?:HASHERS|VALIDATORS|BACKENDS|ENGINES|MIDDLEWARE|PROCESSORS|RENDERERS)\s*=', line):
            return True

    # ── Check 8: Function parameter default with string value ──
    # def _get_pass(self, prompt="Password: ") — this is a prompt default
    if re.match(r'def\s+\w+.*(?:password|passwd|pwd|secret|token)\s*=\s*["\']', line, re.IGNORECASE):
        # It's inside a function definition — the default is likely a UI string
        if category in ("password", "token"):
            return True

    return False


def _find_line_number(content: str, value: str) -> int:
    """Find the line number of a value in the content."""
    idx = content.find(value)
    if idx == -1:
        return 0
    return content[:idx].count('\n') + 1

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
