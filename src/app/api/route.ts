import { NextResponse } from "next/server";

export async function GET() {
  return NextResponse.json({
    name: "CodeLens API",
    version: "5.7.0",
    description: "Live Codebase Reference Intelligence — REST API",
    endpoints: {
      graph: "/api/graph?workspace=/path/to/project",
      command: "/api/command (POST)",
      health: "/api/health?workspace=/path/to/project",
    },
    docs: "https://github.com/Wolfvin/CodeLens",
  });
}
