# Security Policy

## Supported Versions

The following versions of CodeLens are currently being supported with security updates:

| Version | Supported          |
| ------- | ------------------ |
| 5.x     | :white_check_mark: |
| 4.x     | :white_check_mark: |
| 3.x     | :x:                |
| < 3.0   | :x:                |

## Reporting a Vulnerability

We take the security of CodeLens seriously. If you have discovered a security vulnerability, we appreciate your help in disclosing it to us in a responsible manner.

### Please Do

- **Report via GitHub Security Advisories**: Use the [Security Advisories](https://github.com/Wolfvin/CodeLens/security/advisories/new) feature to report vulnerabilities privately.
- **Provide details**: Include the version, the vulnerability description, steps to reproduce, and potential impact.
- **Allow time**: Give us at least 90 days to address the issue before any public disclosure.

### Please Do Not

- **Do not** publicly disclose the vulnerability before it has been addressed.
- **Do not** exploit the vulnerability for anything other than testing.
- **Do not** access or modify other users' data without permission.

### Response Timeline

- **Acknowledgment**: We will acknowledge receipt of your report within 48 hours.
- **Assessment**: We will assess the vulnerability and determine its severity within 7 days.
- **Fix**: We aim to release a fix within 30 days for critical vulnerabilities, 90 days for low-severity issues.
- **Disclosure**: We will coordinate with you on the public disclosure timeline.

### Scope

This security policy covers:

- Vulnerabilities in the CodeLens CLI tool and its Python scripts
- Vulnerabilities in tree-sitter grammar loading
- Security issues in the registry data handling (path traversal, injection, etc.)
- Vulnerabilities that could be triggered by scanning a malicious codebase

Out of scope:

- Vulnerabilities in dependencies (tree-sitter, watchdog) — report to their respective maintainers
- Social engineering attacks
- Denial of service via extremely large workspaces
- Issues in the CodeLens web UI (separate repository)

### CodeLens Security Features

CodeLens itself includes several security-focused analysis tools:

- **`secrets`** — Detect hardcoded API keys, passwords, tokens, and connection strings
- **`dataflow`** — Trace data flow from sources to sinks for taint analysis
- **`env-check`** — Audit environment variable usage and exposure
- **`vuln-scan`** — Scan dependencies for known CVEs
- **`regex-audit`** — Detect ReDoS-vulnerable regex patterns

We recommend running these tools regularly as part of your development workflow and CI/CD pipeline.

## Security Best Practices for CodeLens Users

1. **Never commit `.codelens/` directories** — Add `.codelens/` to your `.gitignore`. The registry contains file paths and potentially sensitive project structure information.
2. **Review `secrets` findings** — Run `codelens secrets` before every commit to catch accidentally committed credentials.
3. **Use `env-check` before deployment** — Ensure no required environment variables are missing or documented.
4. **Run `vuln-scan` regularly** — Keep dependencies updated and free of known vulnerabilities.
5. **Be cautious with watch mode** — The file watcher can consume significant resources on large workspaces.
