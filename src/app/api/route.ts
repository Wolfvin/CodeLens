// ============================================================
// GET /api — System Health Check
// Returns service status, version, and configuration info
// ============================================================

import { NextResponse } from 'next/server'

export async function GET() {
  const isPythonConfigured = !!process.env.CODELENS_PYTHON
  const isScriptConfigured = !!process.env.CODELENS_SCRIPT

  const status = isPythonConfigured && isScriptConfigured ? 'ok' : 'degraded'

  return NextResponse.json({
    status,
    service: 'CodeLens Neural Workspace',
    version: '5.1.0',
    timestamp: Date.now(),
    config: {
      pythonConfigured: isPythonConfigured,
      scriptConfigured: isScriptConfigured,
    },
    message: status === 'ok'
      ? 'All systems operational'
      : 'CLI not configured — set CODELENS_PYTHON and CODELENS_SCRIPT environment variables',
  })
}
