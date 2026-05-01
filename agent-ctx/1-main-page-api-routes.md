# Task: Create API routes and main page for CodeLens Neural Workspace

## Summary

Created three files for the CodeLens Neural Workspace:

### 1. `/src/app/api/graph/route.ts`
- GET endpoint that accepts `workspace` query parameter
- Uses `commandRunner.scan()` to run the CodeLens CLI
- Normalizes output via `normalizer.normalize('scan', rawOutput)`
- Computes clusters via `clusterEngine.computeClusters()`
- Returns `{ nodes, edges, clusters }` or `{ error }` on failure
- Returns 500 when CLI tool is unavailable (expected in demo mode)

### 2. `/src/app/api/command/route.ts`
- POST endpoint accepting `{ command, args, workspace }` in body
- Validates required fields (command, workspace)
- Executes via `commandRunner.execute(command, [...args, workspace])`
- Normalizes output and returns the GraphEvent
- Returns `{ error }` on CLI or validation errors

### 3. `/src/app/page.tsx`
- Full client-side page wrapped in ThemeProvider
- **Demo data**: 30 nodes (8 functions, 5 classes, 3 IDs, 4 components, 2 stores, 3 files, 2 packages, 2 routes, 1 env_var) and 40 edges with realistic codebase relationships
- **State management**: nodes, edges, clusters, selectedNodeId, activeAnimation, searchQuery, searchResults, isScanning, nodeDetail
- **WebSocket**: Connects to `/?XTransformPort=3030`, handles graph_init, graph_event, node_detail, command_result events
- **Search**: Uses graphStore.searchNodes() with fuzzy matching, shows dropdown results
- **Node selection**: Click canvas node → set selectedNodeId → compute NodeDetail → emit select_node via WS → show SlideInPanel
- **Quick actions**: Execute via WebSocket or simulate animation in demo mode
- **Export**: Finds canvas DOM element, supports PNG 2x/4x/current download
- **Rescan**: Fetches /api/graph, replaces demo data if real data available
- **Layout**: ThemeProvider > full viewport div > TopBar (fixed) > NeuralCanvas + SlideInPanel overlay

### Dependencies installed
- `socket.io-client@4.8.3`

### Notes
- All lint checks pass
- Page renders with 200 status
- API /graph returns 500 when CLI tool unavailable (expected, page gracefully falls back to demo data)
- The app shows a beautiful neural graph immediately on load with demo data
