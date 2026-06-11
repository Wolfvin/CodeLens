import { NextResponse } from 'next/server'

export async function GET() {
  return NextResponse.json({
    name: 'CodeLens API',
    version: '5.7.1',
    endpoints: {
      graph: 'GET /api/graph?workspace=<path>',
      command: 'POST /api/command',
      health: 'GET /api/health?workspace=<path>',
    },
    status: 'ok',
  })
}
