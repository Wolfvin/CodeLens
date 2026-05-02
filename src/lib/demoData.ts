// ---- Demo Analysis Data ----

export const DEMO_SECURITY = {
  secrets: {
    findings: [
      { env_key: 'AWS_SECRET_ACCESS_KEY', file: 'src/config/aws.ts', line: 5, severity: 'critical', category: 'aws_key', match: 'AKIA***' },
      { env_key: 'STRIPE_API_KEY', file: 'src/api/payment.ts', line: 3, severity: 'high', category: 'api_key', match: 'sk_live_***' },
      { env_key: 'JWT_SECRET', file: 'src/auth/jwt.ts', line: 1, severity: 'medium', category: 'secret', match: 'super***' },
    ],
    risk: 'high',
  },
  vulnerabilities: {
    vulnerabilities: [
      { package: 'express', version: '4.17.1', cve: 'CVE-2024-29041', severity: 'high', description: 'Open redirect vulnerability' },
      { package: 'lodash', version: '4.17.20', cve: 'CVE-2024-13617', severity: 'medium', description: 'Prototype pollution' },
    ],
    risk: 'medium',
  },
  dataflow: {
    flows: [
      { source: { fn: 'handleLogin', file: 'src/auth/handler.ts', line: 8, tainted: true }, sink: { fn: 'processPayment', file: 'src/api/payment.ts', line: 10, dangerous: true } },
    ],
    risk: 'critical',
  },
  envCheck: {
    missing: ['DATABASE_URL', 'REDIS_URL', 'SMTP_HOST'],
    exposed: ['.env.local'],
    risk: 'medium',
  },
  regexAudit: {
    findings: [
      { pattern: '/(a+)+$/', file: 'src/utils/validate.ts', line: 12, severity: 'critical', type: 'redos', message: 'Catastrophic backtracking in regex (ReDoS)' },
      { pattern: '/.*@.*\\..*/', file: 'src/auth/validation.ts', line: 5, severity: 'medium', type: 'inefficient', message: 'Inefficient email regex with greedy wildcards' },
      { pattern: '/^(https?:\\/\\/)?([\\w-]+\\.)+[\\w-]+/', file: 'src/utils/url.ts', line: 8, severity: 'low', type: 'overmatch', message: 'Overly permissive URL pattern' },
    ],
    risk: 'high',
  },
}

export const DEMO_QUALITY = {
  smells: {
    by_category: {
      long_function: [{ fn: 'processPayment', file: 'src/api/payment.ts', line: 10, severity: 'warning', message: 'Function is 85 lines (threshold: 50)' }],
      deep_nesting: [{ fn: 'validateInput', file: 'src/auth/validation.ts', line: 3, severity: 'warning', message: '4 levels of nesting' }],
      duplicate_code: [{ fn: 'formatCurrency', file: 'src/utils/format.ts', line: 1, severity: 'info', message: 'Similar block in cart.ts:5' }],
      magic_number: [{ fn: 'calculateTotal', file: 'src/api/cart.ts', line: 3, severity: 'info', message: 'Magic number 0.08 (tax rate)' }],
    },
    stats: { total_smells: 4, health_score: 72, by_severity: { critical: 0, warning: 2, info: 2 } },
    risk: 'medium',
  },
  complexity: {
    results: [
      { fn: 'processPayment', file: 'src/api/payment.ts', line: 10, cyclomatic: 18, cognitive: 12, level: 'untamable' },
      { fn: 'handleLogin', file: 'src/auth/handler.ts', line: 8, cyclomatic: 8, cognitive: 5, level: 'complex' },
      { fn: 'verify_token', file: 'src/auth/jwt.ts', line: 12, cyclomatic: 4, cognitive: 3, level: 'moderate' },
      { fn: 'formatCurrency', file: 'src/utils/format.ts', line: 1, cyclomatic: 2, cognitive: 1, level: 'simple' },
    ],
    stats: { simple: 12, moderate: 6, complex: 3, untamable: 1 },
  },
  debugLeaks: {
    findings: [
      { fn: 'handleLogin', file: 'src/auth/handler.ts', line: 15, type: 'console.log', message: 'Debug console.log in production code' },
      { fn: 'getData', file: 'src/api/data.ts', line: 22, type: 'console.debug', message: 'Leftover console.debug statement' },
    ],
  },
  deadCode: {
    results: {
      unused_exports: [{ fn: 'legacyHelper', file: 'src/utils/legacy.ts', line: 1 }],
      unreachable: [{ fn: 'oldHandler', file: 'src/api/old.ts', line: 5 }],
    },
    stats: { total_dead_code: 2 },
  },
  a11y: {
    issues: [
      { element: '#login-form', file: 'src/pages/Login.tsx', line: 12, category: 'missing_label', severity: 'error', message: 'Form input missing label' },
      { element: '#main-content', file: 'src/pages/Dashboard.tsx', line: 8, category: 'missing_alt', severity: 'warning', message: 'Image missing alt text' },
    ],
  },
}

export const DEMO_PERFORMANCE = {
  perfHints: {
    hints: [
      { fn: 'getData', file: 'src/api/data.ts', line: 5, category: 'n_plus_1', severity: 'high', message: 'N+1 query pattern detected in loop' },
      { fn: 'renderDashboard', file: 'src/pages/Dashboard.tsx', line: 20, category: 'expensive_render', severity: 'medium', message: 'Expensive re-render without memoization' },
      { fn: 'calculateTotal', file: 'src/api/cart.ts', line: 3, category: 'sync_blocking', severity: 'low', message: 'Synchronous blocking call in async context' },
    ],
    stats: { by_category: { n_plus_1: 1, expensive_render: 1, sync_blocking: 1, large_bundle: 0, memory_leak: 0, render_bottleneck: 0, unnecessary_recompute: 0, unoptimized_loop: 0 } },
  },
  circular: {
    cycles: [
      { chain: ['src/api/data.ts', 'src/utils/format.ts', 'src/api/data.ts'], length: 2 },
    ],
    risk: 'high',
  },
}

export const DEMO_CSS = {
  cssDeep: {
    unused_vars: ['--color-muted', '--spacing-xl', '--font-display'],
    orphan_keyframes: ['fadeInOut', 'slideObsolete'],
    specificity_wars: { important_count: 14, files: ['src/styles/global.css', 'src/styles/buttons.css'] },
    duplicate_properties: { count: 3, examples: ['background-color in .btn-primary', 'margin in .card-shadow'] },
    z_index_abuse: { max: 99999, count: 8, above_1000: 3 },
  },
  missingRefs: {
    css_no_html: ['.deprecated-class', '.old-layout'],
    html_no_css: ['#temp-container', '.custom-override'],
  },
}

// ---- P1 Demo Data: Search & Trace ----
export const DEMO_P1 = {
  search: {
    results: [
      { file: 'src/api/payment.ts', line: 10, match: 'processPayment', context: 'export async function processPayment(req: Request)' },
      { file: 'src/api/payment.ts', line: 45, match: 'processPayment', context: 'await processPayment(req)' },
      { file: 'src/tests/payment.test.ts', line: 8, match: 'processPayment', context: 'describe("processPayment", () => {' },
    ],
    stats: { total_matches: 3, files_searched: 24 },
  },
  symbols: {
    results: [
      { name: 'processPayment', type: 'function', file: 'src/api/payment.ts', line: 10, domain: 'backend' },
      { name: 'PaymentGateway', type: 'class', file: 'src/services/payment.ts', line: 1, domain: 'backend' },
      { name: 'PaymentStatus', type: 'variable', file: 'src/types/payment.ts', line: 3, domain: 'backend' },
    ],
    stats: { total: 3 },
  },
  trace: {
    chain: [
      { fn: 'processPayment', file: 'src/api/payment.ts', line: 10, type: 'entry' },
      { fn: 'validatePayment', file: 'src/services/payment.ts', line: 5, type: 'call' },
      { fn: 'chargeCard', file: 'src/services/stripe.ts', line: 12, type: 'call' },
      { fn: 'updateOrder', file: 'src/db/orders.ts', line: 28, type: 'call' },
      { fn: 'sendReceipt', file: 'src/services/email.ts', line: 3, type: 'call' },
    ],
    depth: 4,
    risk: 'low',
  },
  impact: {
    symbol: 'processPayment',
    direct_dependents: 5,
    indirect_dependents: 12,
    affected_files: ['src/api/payment.ts', 'src/services/payment.ts', 'src/tests/payment.test.ts', 'src/pages/Checkout.tsx', 'src/hooks/usePayment.ts'],
    risk: 'high',
  },
  dependents: {
    file: 'src/services/payment.ts',
    dependents: [
      { file: 'src/api/payment.ts', imports: ['PaymentGateway', 'processPayment'] },
      { file: 'src/pages/Checkout.tsx', imports: ['PaymentGateway'] },
      { file: 'src/hooks/usePayment.ts', imports: ['processPayment'] },
    ],
    total: 3,
  },
  stackTrace: {
    symbol: 'processPayment',
    propagation: [
      { fn: 'processPayment', file: 'src/api/payment.ts', line: 10, error_type: 'PaymentError' },
      { fn: 'handleAPIError', file: 'src/middleware/error.ts', line: 5, error_type: 'APIError' },
      { fn: 'globalErrorHandler', file: 'src/app/error.tsx', line: 1, error_type: 'AppError' },
    ],
    risk: 'medium',
  },
  query: {
    symbol: 'processPayment',
    type: 'function',
    file: 'src/api/payment.ts',
    line: 10,
    complexity: 8,
    purity: 0.3,
    callers: 5,
    callees: 3,
  },
  list: {
    entries: [
      { name: 'processPayment', type: 'function', file: 'src/api/payment.ts' },
      { name: 'handleLogin', type: 'function', file: 'src/auth/handler.ts' },
      { name: 'PaymentGateway', type: 'class', file: 'src/services/payment.ts' },
      { name: 'useAuth', type: 'function', file: 'src/hooks/useAuth.ts' },
      { name: 'UserStore', type: 'store', file: 'src/stores/user.ts' },
      { name: 'LoginRoute', type: 'route', file: 'src/app/api/auth/login/route.ts' },
    ],
    total: 6,
  },
}

// ---- P2/P3 Demo Data: Outline & Analysis ----
export const DEMO_P2P3 = {
  outline: {
    files: [
      { path: 'src/api/payment.ts', symbols: ['processPayment', 'PaymentGateway', 'validatePayment'], type_count: { function: 2, class: 1 } },
      { path: 'src/auth/handler.ts', symbols: ['handleLogin', 'verifyToken', 'refreshSession'], type_count: { function: 3 } },
      { path: 'src/pages/Dashboard.tsx', symbols: ['Dashboard', 'useDashboardData'], type_count: { component: 1, function: 1 } },
    ],
    total_files: 3,
    total_symbols: 8,
  },
  diff: {
    changes: [
      { type: 'added', symbol: 'processRefund', file: 'src/api/payment.ts', line: 55 },
      { type: 'removed', symbol: 'legacyPayment', file: 'src/api/payment.ts', line: 0 },
      { type: 'modified', symbol: 'handleLogin', file: 'src/auth/handler.ts', line: 8 },
    ],
    summary: { added: 1, removed: 1, modified: 1, total_changes: 3 },
  },
  context: {
    symbol: 'processPayment',
    type: 'function',
    file: 'src/api/payment.ts',
    line: 10,
    callers: [
      { fn: 'CheckoutPage', file: 'src/pages/Checkout.tsx', line: 20 },
      { fn: 'usePayment', file: 'src/hooks/usePayment.ts', line: 5 },
    ],
    callees: [
      { fn: 'validatePayment', file: 'src/services/payment.ts', line: 5 },
      { fn: 'chargeCard', file: 'src/services/stripe.ts', line: 12 },
    ],
    defined_in: [{ file: 'src/api/payment.ts', line: 10 }],
    tests: [{ file: 'src/tests/payment.test.ts', line: 8 }],
  },
  testMap: {
    coverage: [
      { symbol: 'processPayment', file: 'src/api/payment.ts', tested: true, test_files: ['src/tests/payment.test.ts'] },
      { symbol: 'handleLogin', file: 'src/auth/handler.ts', tested: true, test_files: ['src/tests/auth.test.ts'] },
      { symbol: 'chargeCard', file: 'src/services/stripe.ts', tested: false, test_files: [] },
      { symbol: 'validateInput', file: 'src/auth/validation.ts', tested: false, test_files: [] },
    ],
    stats: { total: 4, tested: 2, untested: 2, coverage_percent: 50 },
  },
  configDrift: {
    drifts: [
      { package: 'express', installed: '4.17.1', latest: '4.19.2', severity: 'high', type: 'major_behind' },
      { package: 'lodash', installed: '4.17.20', latest: '4.17.21', severity: 'low', type: 'patch_behind' },
      { package: 'prisma', installed: '5.10.0', latest: '5.16.0', severity: 'medium', type: 'minor_behind' },
    ],
    stats: { total_drift: 3, high: 1, medium: 1, low: 1 },
  },
  typeInfer: {
    results: [
      { symbol: 'processPayment', inferred_type: '(req: Request) => Promise<Response>', confidence: 0.95, file: 'src/api/payment.ts', line: 10 },
      { symbol: 'userCache', inferred_type: 'Map<string, User>', confidence: 0.88, file: 'src/stores/user.ts', line: 5 },
      { symbol: 'config', inferred_type: 'Record<string, unknown>', confidence: 0.72, file: 'src/config/index.ts', line: 1 },
    ],
  },
  ownership: {
    results: [
      { file: 'src/api/payment.ts', owner: 'alice', commits: 24, last_updated: '2024-12-01' },
      { file: 'src/auth/handler.ts', owner: 'bob', commits: 18, last_updated: '2024-11-28' },
      { file: 'src/pages/Dashboard.tsx', owner: 'charlie', commits: 31, last_updated: '2024-12-05' },
    ],
  },
  entrypoints: {
    entries: [
      { type: 'api_route', path: '/api/auth/login', handler: 'handleLogin', file: 'src/app/api/auth/login/route.ts' },
      { type: 'api_route', path: '/api/payment', handler: 'processPayment', file: 'src/app/api/payment/route.ts' },
      { type: 'page', path: '/', handler: 'Home', file: 'src/app/page.tsx' },
      { type: 'page', path: '/dashboard', handler: 'Dashboard', file: 'src/app/dashboard/page.tsx' },
      { type: 'middleware', path: '__middleware', handler: 'authMiddleware', file: 'src/middleware.ts' },
    ],
    total: 5,
  },
  apiMap: {
    routes: [
      { method: 'POST', path: '/api/auth/login', handler: 'handleLogin', file: 'src/app/api/auth/login/route.ts', middleware: ['authMiddleware'] },
      { method: 'POST', path: '/api/payment', handler: 'processPayment', file: 'src/app/api/payment/route.ts', middleware: ['authMiddleware', 'rateLimit'] },
      { method: 'GET', path: '/api/user/:id', handler: 'getUser', file: 'src/app/api/user/[id]/route.ts', middleware: ['authMiddleware'] },
    ],
    total: 3,
  },
  stateMap: {
    stores: [
      { name: 'useAuthStore', file: 'src/stores/auth.ts', type: 'zustand', reads: 4, writes: 2 },
      { name: 'useCartStore', file: 'src/stores/cart.ts', type: 'zustand', reads: 6, writes: 3 },
      { name: 'useUIStore', file: 'src/stores/ui.ts', type: 'zustand', reads: 8, writes: 4 },
    ],
    global_state_count: 3,
  },
}

// ---- Refactoring Demo Data ----
export const DEMO_REFACTORING = {
  refactorSafe: {
    symbol: 'processPayment',
    safety_score: 78,
    is_safe: false,
    blockers: [
      { type: 'dynamic_import', description: 'Symbol is dynamically imported in src/plugins/loader.ts:5', severity: 'high' },
      { type: 'string_reference', description: 'Symbol name used in string literal at src/config/routes.ts:12', severity: 'medium' },
    ],
    warnings: [
      { type: 'external_consumer', description: '3 external packages depend on this symbol' },
    ],
    dependents_count: 5,
    risk: 'medium',
  },
  sideEffect: {
    symbol: 'processPayment',
    purity: 0.3,
    is_pure: false,
    side_effects: [
      { type: 'network', description: 'Makes HTTP request to Stripe API', file: 'src/services/stripe.ts', line: 12, severity: 'high' },
      { type: 'database', description: 'Writes to orders table', file: 'src/db/orders.ts', line: 28, severity: 'medium' },
      { type: 'external', description: 'Sends email receipt', file: 'src/services/email.ts', line: 3, severity: 'medium' },
    ],
    risk: 'high',
  },
}
