// ============================================================
// GET /api — CodeLens API root
// Returns server status, version, and available endpoints
// ============================================================

import { NextResponse } from 'next/server'

export async function GET() {
  return NextResponse.json({
    name: 'CodeLens',
    version: '5.7.1',
    description: 'Live Codebase Reference Intelligence',
    status: 'running',
    endpoints: {
      graph: 'GET /api/graph?workspace=/path/to/project — Full graph scan with health score',
      command: 'POST /api/command — Execute any CodeLens CLI command',
      health: 'GET /api/health?workspace=/path/to/project — Codebase health metrics',
    },
    websocket: 'socket.io on port 3030 — Real-time graph events',
    commands: 41,
  })
}