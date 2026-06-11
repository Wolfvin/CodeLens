'use client'

import React, { useState } from 'react'
import {
  FileText,
  GitCompare,
  BookOpen,
  Map,
  TrendingUp,
  Sparkles,
  User,
  DoorOpen,
  Route,
  Database,
  Loader2,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { useAnalysisStore } from '@/lib/analysisStore'

interface P2P3TabProps {
  theme: 'dark' | 'light'
}

export function P2P3Tab({ theme }: P2P3TabProps) {
  const { p2p3Results, runCommand, workspace, runningCommands } = useAnalysisStore()
  const { outline, diff, context, testMap, configDrift, typeInfer, ownership, entrypoints, apiMap, stateMap } = p2p3Results

  const isRunning = (cmd: string) => runningCommands.includes(cmd)

  const [contextSymbol, setContextSymbol] = useState('')

  const card = {
    backgroundColor: theme === 'dark' ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)',
    borderRadius: '8px',
    padding: '10px',
    transition: 'transform 0.2s ease-out, box-shadow 0.2s ease-out',
  }

  const btnOutline: React.CSSProperties = {
    borderColor: theme === 'dark' ? '#2d3748' : '#e2e8f0',
    color: theme === 'dark' ? '#e2e8f0' : '#1a202c',
  }

  const runFullAnalysis = async () => {
    await runCommand('outline', [workspace])
    await runCommand('test-map', [workspace])
    await runCommand('config-drift', [workspace])
    await runCommand('entrypoints', [workspace])
    await runCommand('api-map', [workspace])
    await runCommand('state-map', [workspace])
  }

  return (
    <ScrollArea className="h-full">
      <div className="p-3 space-y-4">
        {/* Full Analysis Button */}
        <Button
          className="w-full h-9 text-xs gap-2 bg-cyan-600 hover:bg-cyan-700 text-white audit-btn"
          onClick={runFullAnalysis}
          disabled={isRunning('outline') || isRunning('test-map')}
        >
          {isRunning('outline') || isRunning('test-map') ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <BookOpen className="h-3.5 w-3.5" />
          )}
          Full Analysis
        </Button>

        {/* P2 Section */}
        <div className="space-y-2">
          <div className="text-[10px] font-bold uppercase tracking-widest opacity-50">P2 — Outline & Diff</div>
          <div className="grid grid-cols-2 gap-1.5">
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-[10px] gap-1"
              style={btnOutline}
              onClick={() => runCommand('outline', [workspace])}
              disabled={isRunning('outline')}
            >
              <FileText className="h-3 w-3" /> Outline
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-[10px] gap-1"
              style={btnOutline}
              onClick={() => runCommand('diff', [workspace])}
              disabled={isRunning('diff')}
            >
              <GitCompare className="h-3 w-3" /> Diff
            </Button>
          </div>
        </div>

        {/* P3 Section */}
        <div className="space-y-2">
          <div className="text-[10px] font-bold uppercase tracking-widest opacity-50">P3 — Deep Analysis</div>

          {/* Context with symbol input */}
          <div className="flex gap-1.5">
            <Input
              type="text"
              placeholder="Symbol for context..."
              value={contextSymbol}
              onChange={e => setContextSymbol(e.target.value)}
              className="h-7 text-xs font-mono"
              style={{
                backgroundColor: theme === 'dark' ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.04)',
                color: theme === 'dark' ? '#e2e8f0' : '#1a202c',
                borderColor: theme === 'dark' ? '#2d3748' : '#e2e8f0',
              }}
            />
            <Button
              size="sm"
              variant="outline"
              className="h-7 px-2 text-[10px] gap-1 shrink-0"
              style={btnOutline}
              onClick={() => contextSymbol.trim() && runCommand('context', [workspace, '--name', contextSymbol])}
              disabled={isRunning('context') || !contextSymbol.trim()}
            >
              <BookOpen className="h-3 w-3" /> Context
            </Button>
          </div>

          <div className="grid grid-cols-2 gap-1.5">
            <Button size="sm" variant="outline" className="h-7 text-[10px] gap-1" style={btnOutline} onClick={() => runCommand('test-map', [workspace])} disabled={isRunning('test-map')}>
              <Map className="h-3 w-3" /> Test Map
            </Button>
            <Button size="sm" variant="outline" className="h-7 text-[10px] gap-1" style={btnOutline} onClick={() => runCommand('config-drift', [workspace])} disabled={isRunning('config-drift')}>
              <TrendingUp className="h-3 w-3" /> Drift
            </Button>
            <Button size="sm" variant="outline" className="h-7 text-[10px] gap-1" style={btnOutline} onClick={() => runCommand('type-infer', [workspace])} disabled={isRunning('type-infer')}>
              <Sparkles className="h-3 w-3" /> Types
            </Button>
            <Button size="sm" variant="outline" className="h-7 text-[10px] gap-1" style={btnOutline} onClick={() => runCommand('ownership', [workspace])} disabled={isRunning('ownership')}>
              <User className="h-3 w-3" /> Owner
            </Button>
            <Button size="sm" variant="outline" className="h-7 text-[10px] gap-1" style={btnOutline} onClick={() => runCommand('entrypoints', [workspace])} disabled={isRunning('entrypoints')}>
              <DoorOpen className="h-3 w-3" /> Entry
            </Button>
            <Button size="sm" variant="outline" className="h-7 text-[10px] gap-1" style={btnOutline} onClick={() => runCommand('api-map', [workspace])} disabled={isRunning('api-map')}>
              <Route className="h-3 w-3" /> API Map
            </Button>
          </div>
          <Button
            size="sm"
            variant="outline"
            className="w-full h-7 text-[10px] gap-1"
            style={btnOutline}
            onClick={() => runCommand('state-map', [workspace])}
            disabled={isRunning('state-map')}
          >
            <Database className="h-3 w-3" /> State Map
          </Button>
        </div>

        <Separator style={{ background: 'linear-gradient(90deg, transparent, rgba(139,92,246,0.15), transparent)', height: '1px' }} />

        {/* Outline Results */}
        {outline?.files && outline.files.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <FileText className="h-3.5 w-3.5" style={{ color: '#63b3ed' }} />
              <span className="text-xs font-semibold">File Outline</span>
              <Badge className="text-[10px] h-5 ml-auto" style={{ backgroundColor: 'rgba(99,179,237,0.15)', color: '#63b3ed' }}>
                {outline.total_symbols} symbols
              </Badge>
            </div>
            {outline.files.map((f, i) => (
              <div key={i} style={card}>
                <div className="text-xs font-medium font-mono truncate">{f.path}</div>
                <div className="flex flex-wrap gap-1 mt-1">
                  {f.symbols.map((s, j) => (
                    <Badge key={j} className="text-[9px] h-4" style={{ backgroundColor: 'rgba(183,148,244,0.15)', color: '#b794f4' }}>
                      {s}
                    </Badge>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Diff Results */}
        {diff?.changes && diff.changes.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <GitCompare className="h-3.5 w-3.5" style={{ color: '#48bb78' }} />
              <span className="text-xs font-semibold">Registry Diff</span>
            </div>
            <div className="grid grid-cols-3 gap-1.5">
              {[
                { label: 'Added', count: diff.summary.added, color: '#48bb78' },
                { label: 'Removed', count: diff.summary.removed, color: '#e53e3e' },
                { label: 'Modified', count: diff.summary.modified, color: '#ecc94b' },
              ].map(({ label, count, color }) => (
                <div key={label} style={card}>
                  <div className="text-[10px] font-bold uppercase tracking-widest opacity-50">{label}</div>
                  <div className="text-lg font-bold mt-0.5" style={{ color }}>{count}</div>
                </div>
              ))}
            </div>
            {diff.changes.map((c, i) => (
              <div key={i} className="flex items-center gap-2 text-xs">
                <Badge className="text-[9px] h-4" style={{
                  backgroundColor: c.type === 'added' ? 'rgba(72,187,120,0.2)' : c.type === 'removed' ? 'rgba(229,62,62,0.2)' : 'rgba(236,201,75,0.2)',
                  color: c.type === 'added' ? '#48bb78' : c.type === 'removed' ? '#e53e3e' : '#ecc94b',
                }}>
                  {c.type}
                </Badge>
                <span className="font-mono truncate">{c.symbol}</span>
              </div>
            ))}
          </div>
        )}

        {/* Context Results */}
        {context && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <BookOpen className="h-3.5 w-3.5" style={{ color: '#b794f4' }} />
              <span className="text-xs font-semibold">Symbol Context</span>
            </div>
            <div style={card}>
              <div className="flex items-center gap-1.5 text-xs">
                <span className="font-medium">{context.symbol}</span>
                <Badge className="text-[9px] h-4" style={{ backgroundColor: 'rgba(99,179,237,0.15)', color: '#63b3ed' }}>{context.type}</Badge>
              </div>
              <div className="text-[10px] font-mono opacity-50 mt-0.5">{context.file}:{context.line}</div>
            </div>
            {context.callers && context.callers.length > 0 && (
              <div className="space-y-1">
                <div className="text-[10px] font-bold uppercase tracking-widest opacity-40">Callers</div>
                {context.callers.map((c, i) => (
                  <div key={i} className="text-xs font-mono px-2 py-1 rounded" style={{ backgroundColor: theme === 'dark' ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)' }}>
                    {c.fn} <span className="opacity-40">at {c.file}:{c.line}</span>
                  </div>
                ))}
              </div>
            )}
            {context.callees && context.callees.length > 0 && (
              <div className="space-y-1">
                <div className="text-[10px] font-bold uppercase tracking-widest opacity-40">Callees</div>
                {context.callees.map((c, i) => (
                  <div key={i} className="text-xs font-mono px-2 py-1 rounded" style={{ backgroundColor: theme === 'dark' ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)' }}>
                    {c.fn} <span className="opacity-40">at {c.file}:{c.line}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Test Map Results */}
        {testMap?.coverage && testMap.coverage.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Map className="h-3.5 w-3.5" style={{ color: '#68d391' }} />
              <span className="text-xs font-semibold">Test Coverage</span>
              <Badge className="text-[10px] h-5 ml-auto" style={{ backgroundColor: testMap.stats.coverage_percent >= 80 ? 'rgba(72,187,120,0.15)' : 'rgba(236,201,75,0.15)', color: testMap.stats.coverage_percent >= 80 ? '#48bb78' : '#ecc94b' }}>
                {testMap.stats.coverage_percent}%
              </Badge>
            </div>
            {testMap.coverage.map((c, i) => (
              <div key={i} className="flex items-center gap-2 text-xs">
                <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: c.tested ? '#48bb78' : '#e53e3e' }} />
                <span className="truncate">{c.symbol}</span>
                <span className="ml-auto text-[10px] opacity-40 truncate">{c.file.split('/').pop()}</span>
              </div>
            ))}
          </div>
        )}

        {/* Config Drift Results */}
        {configDrift?.drifts && configDrift.drifts.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <TrendingUp className="h-3.5 w-3.5" style={{ color: '#ed8936' }} />
              <span className="text-xs font-semibold">Config Drift</span>
              <Badge className="text-[10px] h-5 ml-auto" style={{ backgroundColor: 'rgba(237,137,54,0.15)', color: '#ed8936' }}>
                {configDrift.stats.total_drift}
              </Badge>
            </div>
            {configDrift.drifts.map((d, i) => (
              <div key={i} style={card}>
                <div className="flex items-center gap-1.5 text-xs">
                  <Badge className="text-[9px] h-4" style={{
                    backgroundColor: d.severity === 'high' ? 'rgba(229,62,62,0.2)' : d.severity === 'medium' ? 'rgba(237,137,54,0.2)' : 'rgba(236,201,75,0.2)',
                    color: d.severity === 'high' ? '#e53e3e' : d.severity === 'medium' ? '#ed8936' : '#ecc94b',
                  }}>
                    {d.type.replace(/_/g, ' ')}
                  </Badge>
                  <span className="font-medium">{d.package}</span>
                </div>
                <div className="text-[10px] opacity-50 mt-0.5">{d.installed} → {d.latest}</div>
              </div>
            ))}
          </div>
        )}

        {/* Type Inference Results */}
        {typeInfer?.results && typeInfer.results.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Sparkles className="h-3.5 w-3.5" style={{ color: '#b794f4' }} />
              <span className="text-xs font-semibold">Type Inference</span>
            </div>
            {typeInfer.results.map((r, i) => (
              <div key={i} style={card}>
                <div className="flex items-center gap-1.5 text-xs">
                  <span className="font-medium">{r.symbol}</span>
                  <Badge className="text-[9px] h-4 ml-auto" style={{ backgroundColor: r.confidence >= 0.9 ? 'rgba(72,187,120,0.15)' : 'rgba(236,201,75,0.15)', color: r.confidence >= 0.9 ? '#48bb78' : '#ecc94b' }}>
                    {Math.round(r.confidence * 100)}%
                  </Badge>
                </div>
                <div className="text-[10px] font-mono opacity-60 mt-1 break-all">{r.inferred_type}</div>
                <div className="text-[10px] opacity-40 mt-0.5">{r.file}:{r.line}</div>
              </div>
            ))}
          </div>
        )}

        {/* Ownership Results */}
        {ownership?.results && ownership.results.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <User className="h-3.5 w-3.5" style={{ color: '#4fd1c5' }} />
              <span className="text-xs font-semibold">Code Ownership</span>
            </div>
            {ownership.results.map((r, i) => (
              <div key={i} className="flex items-center gap-2 text-xs">
                <div
                  className="w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-bold shrink-0"
                  style={{ backgroundColor: 'rgba(79,209,197,0.2)', color: '#4fd1c5' }}
                >
                  {r.owner[0].toUpperCase()}
                </div>
                <span className="font-medium truncate">{r.owner}</span>
                <span className="text-[10px] opacity-40 ml-auto truncate">{r.file.split('/').pop()}</span>
              </div>
            ))}
          </div>
        )}

        {/* Entrypoints Results */}
        {entrypoints?.entries && entrypoints.entries.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <DoorOpen className="h-3.5 w-3.5" style={{ color: '#f6ad55' }} />
              <span className="text-xs font-semibold">Entrypoints</span>
              <Badge className="text-[10px] h-5 ml-auto" style={{ backgroundColor: 'rgba(246,173,85,0.15)', color: '#f6ad55' }}>
                {entrypoints.total}
              </Badge>
            </div>
            {entrypoints.entries.map((e, i) => (
              <div key={i} style={card}>
                <div className="flex items-center gap-1.5 text-xs">
                  <Badge className="text-[9px] h-4" style={{ backgroundColor: e.type === 'api_route' ? 'rgba(99,179,237,0.15)' : e.type === 'page' ? 'rgba(183,148,244,0.15)' : 'rgba(236,201,75,0.15)', color: e.type === 'api_route' ? '#63b3ed' : e.type === 'page' ? '#b794f4' : '#ecc94b' }}>
                    {e.type}
                  </Badge>
                  <span className="font-mono truncate">{e.path}</span>
                </div>
                <div className="text-[10px] opacity-50 mt-0.5">{e.handler} — {e.file.split('/').pop()}</div>
              </div>
            ))}
          </div>
        )}

        {/* API Map Results */}
        {apiMap?.routes && apiMap.routes.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Route className="h-3.5 w-3.5" style={{ color: '#63b3ed' }} />
              <span className="text-xs font-semibold">API Routes</span>
              <Badge className="text-[10px] h-5 ml-auto" style={{ backgroundColor: 'rgba(99,179,237,0.15)', color: '#63b3ed' }}>
                {apiMap.total}
              </Badge>
            </div>
            {apiMap.routes.map((r, i) => (
              <div key={i} style={card}>
                <div className="flex items-center gap-1.5 text-xs">
                  <Badge className="text-[9px] h-4 font-mono" style={{
                    backgroundColor: r.method === 'GET' ? 'rgba(72,187,120,0.2)' : r.method === 'POST' ? 'rgba(99,179,237,0.2)' : 'rgba(236,201,75,0.2)',
                    color: r.method === 'GET' ? '#48bb78' : r.method === 'POST' ? '#63b3ed' : '#ecc94b',
                  }}>
                    {r.method}
                  </Badge>
                  <span className="font-mono truncate">{r.path}</span>
                </div>
                <div className="text-[10px] opacity-50 mt-0.5">{r.handler} — {r.file.split('/').pop()}</div>
                {r.middleware && r.middleware.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1">
                    {r.middleware.map((m, j) => (
                      <Badge key={j} className="text-[8px] h-3.5" style={{ backgroundColor: 'rgba(246,173,85,0.15)', color: '#f6ad55' }}>
                        {m}
                      </Badge>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {/* State Map Results */}
        {stateMap?.stores && stateMap.stores.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Database className="h-3.5 w-3.5" style={{ color: '#fbd38d' }} />
              <span className="text-xs font-semibold">State Management</span>
              <Badge className="text-[10px] h-5 ml-auto" style={{ backgroundColor: 'rgba(251,211,141,0.15)', color: '#fbd38d' }}>
                {stateMap.global_state_count} stores
              </Badge>
            </div>
            {stateMap.stores.map((s, i) => (
              <div key={i} style={card}>
                <div className="flex items-center gap-1.5 text-xs">
                  <span className="font-medium">{s.name}</span>
                  <Badge className="text-[9px] h-4" style={{ backgroundColor: 'rgba(183,148,244,0.15)', color: '#b794f4' }}>{s.type}</Badge>
                </div>
                <div className="text-[10px] font-mono opacity-50 mt-0.5">{s.file}</div>
                <div className="flex gap-3 mt-1">
                  <span className="text-[10px]"><span className="opacity-50">Reads:</span> <span className="font-mono" style={{ color: '#63b3ed' }}>{s.reads}</span></span>
                  <span className="text-[10px]"><span className="opacity-50">Writes:</span> <span className="font-mono" style={{ color: '#ed8936' }}>{s.writes}</span></span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </ScrollArea>
  )
}
