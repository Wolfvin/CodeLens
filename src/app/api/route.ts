// ============================================================
// GET /api — Server health check
// ============================================================

import { NextResponse } from 'next/server'

export async function GET() {
  return NextResponse.json({
    status: 'ok',
    version: '5.7.0',
    timestamp: Date.now(),
    services: {
      api: 'running',
      python: process.env.CODELENS_PYTHON ? 'configured' : 'missing',
      script: process.env.CODELENS_SCRIPT ? 'configured' : 'missing',
    },
  })
}