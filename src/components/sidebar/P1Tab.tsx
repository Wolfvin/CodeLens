'use client'

import React, { useState } from 'react'
import {
  Search,
  Link2,
  Flame,
  Package,
  Layers,
  Crosshair,
  Loader2,
  ChevronRight,
  FileSearch,
  List,
  HelpCircle,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { useAnalysisStore } from '@/lib/analysisStore'

interface P1TabProps {
  theme: 'dark' | 'light'
}

export function P1Tab({ theme }: P1TabProps) {
  const { p1Results, runCommand, workspace, runningCommands } = useAnalysisStore()
  const { search, symbols, trace, impact, dependents, stackTrace, query, list } = p1Results

  const isRunning = (cmd: string) => runningCommands.includes(cmd)

  const [searchQuery, setSearchQuery] = useState('')
  const [symbolInput, setSymbolInput] = useState('')
  const [filePathInput, setFilePathInput] = useState('')

  const card = {
    backgroundColor: theme === 'dark' ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)',
    borderRadius: '8px',
    padding: '10px',
    transition: 'transform 0.2s ease-out, box-shadow 0.2s ease-out',
  }

  const inputStyle = {
    backgroundColor: theme === 'dark' ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.04)',
    color: theme === 'dark' ? '#e2e8f0' : '#1a202c',
    borderColor: theme === 'dark' ? '#2d3748' : '#e2e8f0',
  }

  const btnOutline: React.CSSProperties = {
    borderColor: theme === 'dark' ? '#2d3748' : '#e2e8f0',
    color: theme === 'dark' ? '#e2e8f0' : '#1a202c',
  }

  const runP1Full = async () => {
    if (searchQuery.trim()) {
      await runCommand('search', [workspace, '--pattern', searchQuery])
    }
    if (symbolInput.trim()) {
      await runCommand('trace', [workspace, '--name', symbolInput])
    }
  }

  return (
    <ScrollArea className="h-full">
      <div className="p-3 space-y-4">
        {/* Search Input */}
        <div className="space-y-2">
          <div className="text-[10px] font-bold uppercase tracking-widest opacity-50">Pattern Search</div>
          <div className="flex gap-1.5">
            <Input
              type="text"
              placeholder="Search pattern..."
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              className="h-8 text-xs"
              style={inputStyle}
              onKeyDown={e => {
                if (e.key === 'Enter' && searchQuery.trim()) {
                  runCommand('search', [workspace, '--pattern', searchQuery])
                }
              }}
            />
            <Button
              size="sm"
              className="h-8 px-3 gap-1.5 bg-violet-600 hover:bg-violet-700 text-white shrink-0"
              onClick={() => searchQuery.trim() && runCommand('search', [workspace, '--pattern', searchQuery])}
              disabled={isRunning('search') || !searchQuery.trim()}
            >
              {isRunning('search') ? <Loader2 className="h-3 w-3 animate-spin" /> : <Search className="h-3 w-3" />}
              Search
            </Button>
          </div>
        </div>

        {/* Symbol Input for Trace/Impact/StackTrace */}
        <div className="space-y-2">
          <div className="text-[10px] font-bold uppercase tracking-widest opacity-50">Symbol Name</div>
          <Input
            type="text"
            placeholder="e.g. processPayment"
            value={symbolInput}
            onChange={e => setSymbolInput(e.target.value)}
            className="h-8 text-xs font-mono"
            style={inputStyle}
          />
          <div className="grid grid-cols-2 gap-1.5">
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-[10px] gap-1"
              style={btnOutline}
              onClick={() => symbolInput.trim() && runCommand('trace', [workspace, '--name', symbolInput])}
              disabled={isRunning('trace') || !symbolInput.trim()}
            >
              <Link2 className="h-3 w-3" /> Trace
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-[10px] gap-1"
              style={btnOutline}
              onClick={() => symbolInput.trim() && runCommand('impact', [workspace, '--name', symbolInput])}
              disabled={isRunning('impact') || !symbolInput.trim()}
            >
              <Flame className="h-3 w-3" /> Impact
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-[10px] gap-1"
              style={btnOutline}
              onClick={() => symbolInput.trim() && runCommand('stack-trace', [workspace, '--name', symbolInput])}
              disabled={isRunning('stack-trace') || !symbolInput.trim()}
            >
              <Layers className="h-3 w-3" /> Stack
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-[10px] gap-1"
              style={btnOutline}
              onClick={() => symbolInput.trim() && runCommand('symbols', [workspace, '--name', symbolInput])}
              disabled={isRunning('symbols') || !symbolInput.trim()}
            >
              <Crosshair className="h-3 w-3" /> Symbols
            </Button>
          </div>
        </div>

        {/* File Path Input for Dependents */}
        <div className="space-y-2">
          <div className="text-[10px] font-bold uppercase tracking-widest opacity-50">File Path</div>
          <div className="flex gap-1.5">
            <Input
              type="text"
              placeholder="e.g. src/services/payment.ts"
              value={filePathInput}
              onChange={e => setFilePathInput(e.target.value)}
              className="h-8 text-xs font-mono"
              style={inputStyle}
            />
            <Button
              size="sm"
              variant="outline"
              className="h-8 px-3 gap-1 shrink-0"
              style={btnOutline}
              onClick={() => filePathInput.trim() && runCommand('dependents', [workspace, '--file', filePathInput])}
              disabled={isRunning('dependents') || !filePathInput.trim()}
            >
              <Package className="h-3 w-3" /> Deps
            </Button>
          </div>
        </div>

        {/* Quick Actions */}
        <div className="grid grid-cols-2 gap-1.5">
          <Button
            size="sm"
            variant="outline"
            className="h-7 text-[10px] gap-1"
            style={btnOutline}
            onClick={() => symbolInput.trim() && runCommand('query', [workspace, '--name', symbolInput])}
            disabled={isRunning('query') || !symbolInput.trim()}
          >
            <HelpCircle className="h-3 w-3" /> Query
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="h-7 text-[10px] gap-1"
            style={btnOutline}
            onClick={() => runCommand('list', [workspace])}
            disabled={isRunning('list')}
          >
            <List className="h-3 w-3" /> List All
          </Button>
        </div>

        <Separator style={{ background: 'linear-gradient(90deg, transparent, rgba(139,92,246,0.15), transparent)', height: '1px' }} />

        {/* Search Results */}
        {search?.results && search.results.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <FileSearch className="h-3.5 w-3.5" style={{ color: '#63b3ed' }} />
              <span className="text-xs font-semibold">Search Results</span>
              <Badge className="text-[10px] h-5 ml-auto" style={{ backgroundColor: 'rgba(99,179,237,0.15)', color: '#63b3ed' }}>
                {search.stats?.total_matches ?? 0}
              </Badge>
            </div>
            {search.results.map((r, i) => (
              <div key={i} style={card}>
                <div className="flex items-center gap-1.5 text-xs">
                  <span className="font-medium" style={{ color: '#b794f4' }}>{r.match}</span>
                </div>
                <div className="text-[10px] font-mono opacity-50 mt-0.5">{r.file}:{r.line}</div>
                <div className="text-[10px] opacity-40 mt-0.5 truncate font-mono">{r.context}</div>
              </div>
            ))}
          </div>
        )}

        {/* Trace Results */}
        {trace?.chain && trace.chain.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Link2 className="h-3.5 w-3.5" style={{ color: '#48bb78' }} />
              <span className="text-xs font-semibold">Call Trace</span>
              <Badge className="text-[10px] h-5 ml-auto" style={{ backgroundColor: trace.risk === 'low' ? 'rgba(72,187,120,0.15)' : 'rgba(237,137,54,0.15)', color: trace.risk === 'low' ? '#48bb78' : '#ed8936' }}>
                depth {trace.depth}
              </Badge>
            </div>
            <div className="space-y-1">
              {trace.chain.map((step, i) => (
                <div key={i} className="flex items-center gap-2 text-xs">
                  <div
                    className="w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-bold shrink-0"
                    style={{
                      backgroundColor: step.type === 'entry' ? 'rgba(183,148,244,0.2)' : 'rgba(99,179,237,0.15)',
                      color: step.type === 'entry' ? '#b794f4' : '#63b3ed',
                    }}
                  >
                    {i + 1}
                  </div>
                  <span className="font-medium truncate">{step.fn}</span>
                  {i < trace.chain.length - 1 && <ChevronRight className="h-3 w-3 opacity-30 shrink-0" />}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Impact Results */}
        {impact && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Flame className="h-3.5 w-3.5" style={{ color: '#ed8936' }} />
              <span className="text-xs font-semibold">Impact Analysis</span>
              <Badge className="text-[10px] h-5 ml-auto" style={{ backgroundColor: impact.risk === 'high' ? 'rgba(229,62,62,0.15)' : 'rgba(72,187,120,0.15)', color: impact.risk === 'high' ? '#e53e3e' : '#48bb78' }}>
                {impact.risk}
              </Badge>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div style={card}>
                <div className="text-[10px] font-bold uppercase tracking-widest opacity-50">Direct</div>
                <div className="text-xl font-bold mt-1" style={{ color: impact.direct_dependents > 5 ? '#ed8936' : '#48bb78' }}>{impact.direct_dependents}</div>
              </div>
              <div style={card}>
                <div className="text-[10px] font-bold uppercase tracking-widest opacity-50">Indirect</div>
                <div className="text-xl font-bold mt-1" style={{ color: impact.indirect_dependents > 10 ? '#e53e3e' : '#48bb78' }}>{impact.indirect_dependents}</div>
              </div>
            </div>
            {impact.affected_files && impact.affected_files.length > 0 && (
              <div className="space-y-1">
                <div className="text-[10px] font-bold uppercase tracking-widest opacity-40">Affected Files</div>
                {impact.affected_files.map((f, i) => (
                  <div key={i} className="text-xs font-mono px-2 py-1 rounded" style={{ backgroundColor: theme === 'dark' ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)' }}>
                    {f}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Dependents Results */}
        {dependents?.dependents && dependents.dependents.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Package className="h-3.5 w-3.5" style={{ color: '#4fd1c5' }} />
              <span className="text-xs font-semibold">Dependents</span>
              <Badge className="text-[10px] h-5 ml-auto" style={{ backgroundColor: 'rgba(79,209,197,0.15)', color: '#4fd1c5' }}>
                {dependents.total}
              </Badge>
            </div>
            {dependents.dependents.map((d, i) => (
              <div key={i} style={card}>
                <div className="text-xs font-medium font-mono truncate">{d.file}</div>
                <div className="flex flex-wrap gap-1 mt-1">
                  {d.imports.map((imp, j) => (
                    <Badge key={j} className="text-[9px] h-4" style={{ backgroundColor: 'rgba(99,179,237,0.15)', color: '#63b3ed' }}>
                      {imp}
                    </Badge>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Symbols Results */}
        {symbols?.results && symbols.results.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Crosshair className="h-3.5 w-3.5" style={{ color: '#b794f4' }} />
              <span className="text-xs font-semibold">Symbols</span>
              <Badge className="text-[10px] h-5 ml-auto" style={{ backgroundColor: 'rgba(183,148,244,0.15)', color: '#b794f4' }}>
                {symbols.stats?.total ?? symbols.results.length}
              </Badge>
            </div>
            {symbols.results.map((s, i) => (
              <div key={i} style={card}>
                <div className="flex items-center gap-1.5 text-xs">
                  <span className="font-medium" style={{ color: '#b794f4' }}>{s.name}</span>
                  <Badge className="text-[9px] h-4" style={{
                    backgroundColor: s.type === 'function' ? 'rgba(99,179,237,0.15)' : s.type === 'class' ? 'rgba(236,201,75,0.2)' : s.type === 'variable' ? 'rgba(72,187,120,0.15)' : s.type === 'component' ? 'rgba(246,135,179,0.15)' : 'rgba(183,148,244,0.15)',
                    color: s.type === 'function' ? '#63b3ed' : s.type === 'class' ? '#ecc94b' : s.type === 'variable' ? '#48bb78' : s.type === 'component' ? '#f687b3' : '#b794f4',
                  }}>
                    {s.type}
                  </Badge>
                  {s.domain && (
                    <Badge className="text-[9px] h-4" style={{
                      backgroundColor: s.domain === 'backend' ? 'rgba(79,209,197,0.15)' : s.domain === 'frontend' ? 'rgba(99,179,237,0.15)' : 'rgba(183,148,244,0.15)',
                      color: s.domain === 'backend' ? '#4fd1c5' : s.domain === 'frontend' ? '#63b3ed' : '#b794f4',
                    }}>
                      {s.domain}
                    </Badge>
                  )}
                </div>
                <div className="text-[10px] font-mono opacity-50 mt-0.5">{s.file}:{s.line}</div>
              </div>
            ))}
          </div>
        )}

        {/* Stack Trace Results */}
        {stackTrace?.propagation && stackTrace.propagation.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Layers className="h-3.5 w-3.5" style={{ color: '#fbd38d' }} />
              <span className="text-xs font-semibold">Stack Trace</span>
              <Badge className="text-[10px] h-5 ml-auto" style={{ backgroundColor: stackTrace.risk === 'high' ? 'rgba(229,62,62,0.15)' : stackTrace.risk === 'medium' ? 'rgba(236,201,75,0.15)' : 'rgba(72,187,120,0.15)', color: stackTrace.risk === 'high' ? '#e53e3e' : stackTrace.risk === 'medium' ? '#ecc94b' : '#48bb78' }}>
                {stackTrace.risk}
              </Badge>
            </div>
            {stackTrace.propagation.map((step, i) => (
              <div key={i} style={card}>
                <div className="flex items-center gap-1.5 text-xs">
                  <Badge className="text-[9px] h-4 font-mono" style={{ backgroundColor: i === 0 ? 'rgba(229,62,62,0.2)' : 'rgba(236,201,75,0.2)', color: i === 0 ? '#e53e3e' : '#ecc94b' }}>
                    {step.error_type}
                  </Badge>
                  <span className="font-medium">{step.fn}</span>
                </div>
                <div className="text-[10px] font-mono opacity-50 mt-0.5">{step.file}:{step.line}</div>
              </div>
            ))}
          </div>
        )}

        {/* Query Result */}
        {query && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <HelpCircle className="h-3.5 w-3.5" style={{ color: '#b794f4' }} />
              <span className="text-xs font-semibold">Query Result</span>
            </div>
            <div style={card}>
              <div className="flex items-center gap-1.5 text-xs">
                <span className="font-medium">{query.symbol}</span>
                <Badge className="text-[9px] h-4" style={{ backgroundColor: 'rgba(99,179,237,0.15)', color: '#63b3ed' }}>{query.type}</Badge>
              </div>
              <div className="text-[10px] font-mono opacity-50 mt-0.5">{query.file}:{query.line}</div>
              <div className="grid grid-cols-2 gap-2 mt-2">
                <div className="text-[10px]"><span className="opacity-50">Complexity:</span> <span className="font-mono">{query.complexity}</span></div>
                <div className="text-[10px]"><span className="opacity-50">Purity:</span> <span className="font-mono">{query.purity}</span></div>
                <div className="text-[10px]"><span className="opacity-50">Callers:</span> <span className="font-mono">{query.callers}</span></div>
                <div className="text-[10px]"><span className="opacity-50">Callees:</span> <span className="font-mono">{query.callees}</span></div>
              </div>
            </div>
          </div>
        )}

        {/* List Results */}
        {list?.entries && list.entries.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <List className="h-3.5 w-3.5" style={{ color: '#68d391' }} />
              <span className="text-xs font-semibold">Registry List</span>
              <Badge className="text-[10px] h-5 ml-auto" style={{ backgroundColor: 'rgba(104,211,145,0.15)', color: '#68d391' }}>
                {list.total}
              </Badge>
            </div>
            {list.entries.map((entry, i) => (
              <div key={i} className="flex items-center gap-2 text-xs px-2 py-1.5 rounded" style={{ backgroundColor: theme === 'dark' ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)' }}>
                <Badge className="text-[9px] h-4" style={{ backgroundColor: 'rgba(183,148,244,0.15)', color: '#b794f4' }}>{entry.type}</Badge>
                <span className="font-medium truncate">{entry.name}</span>
                <span className="ml-auto text-[10px] font-mono opacity-40 truncate">{entry.file}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </ScrollArea>
  )
}
