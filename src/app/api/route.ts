// ============================================================
// GET /api
// API info endpoint — returns available endpoints and version
// ============================================================

import { NextResponse } from 'next/server'

export async function GET() {
  return NextResponse.json({
    name: 'CodeLens API',
    version: '5.7.1',
    description: 'Live Codebase Reference Intelligence — REST API',
    endpoints: [
      {
        method: 'GET',
        path: '/api/graph',
        description: 'Full workspace scan → normalized graph data (nodes, edges, clusters, health)',
        params: ['workspace (required)', 'incremental (optional)'],
      },
      {
        method: 'POST',
        path: '/api/command',
        description: 'Execute any CodeLens CLI command → normalized GraphEvent',
        body: ['command (required)', 'args (optional)', 'workspace (required)'],
      },
      {
        method: 'GET',
        path: '/api/health',
        description: 'Codebase health metrics (score, coupling, heatmap, impact radius)',
        params: ['workspace (required)', 'nodeId (optional)'],
      },
    ],
    websocket: {
      port: Number(process.env.CODELENS_WS_PORT) || 3030,
      protocol: 'socket.io',
      events: ['command', 'select_node', 'graph_init', 'graph_event', 'node_detail'],
    },
    commands: 41,
  })
}
