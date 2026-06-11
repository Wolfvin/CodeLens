import { NextResponse } from 'next/server';

export async function GET() {
  return NextResponse.json({
    name: 'CodeLens API',
    version: '5.1.0',
    status: 'ok',
    endpoints: ['/api/graph', '/api/command', '/api/health']
  });
}