'use client'

import React, { useState, useEffect, useCallback } from 'react'
import { Eye, EyeOff, Play, Square, Trash2, FileEdit, FilePlus, FileMinus, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { useAnalysisStore } from '@/lib/analysisStore'
import { graphStore } from '@/lib/graphStore'

interface WatchTabProps {
  theme: 'dark' | 'light'
}

interface FileChangeEvent {
  id: string
  file: string
  type: 'created' | 'modified' | 'deleted'
  timestamp: number
}

// Simulated file change events for demo purposes
const SIMULATED_EVENTS: Omit<FileChangeEvent, 'id' | 'timestamp'>[] = [
  { file: 'src/components/sidebar/WatchTab.tsx', type: 'created' },
  { file: 'src/lib/analysisStore.ts', type: 'modified' },
  { file: 'src/components/sidebar/LeftSidebar.tsx', type: 'modified' },
  { file: 'src/app/page.tsx', type: 'modified' },
  { file: 'src/types/neural.ts', type: 'modified' },
  { file: 'src/lib/graphStore.ts', type: 'modified' },
  { file: 'src/components/ui/switch.tsx', type: 'created' },
  { file: 'src/old/legacy.ts', type: 'deleted' },
  { file: 'src/api/health/route.ts', type: 'modified' },
  { file: 'src/hooks/useWatch.ts', type: 'created' },
]

export function WatchTab({ theme }: WatchTabProps) {
  const { isWatchMode, setWatchMode, workspace, runCommand } = useAnalysisStore()
  const [fileChanges, setFileChanges] = useState<FileChangeEvent[]>([])
  const [recentFiles, setRecentFiles] = useState<string[]>([])
  const [isStarting, setIsStarting] = useState(false)

  const dark = theme === 'dark'

  // Simulate file changes when watch mode is active
  useEffect(() => {
    if (!isWatchMode) return

    const interval = setInterval(() => {
      const sim = SIMULATED_EVENTS[Math.floor(Math.random() * SIMULATED_EVENTS.length)]
      const event: FileChangeEvent = {
        id: `evt-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
        file: sim.file,
        type: sim.type,
        timestamp: Date.now(),
      }
      setFileChanges(prev => [event, ...prev].slice(0, 50))
      setRecentFiles(prev => {
        const updated = [event.file, ...prev.filter(f => f !== event.file)]
        return updated.slice(0, 10)
      })
    }, 3000 + Math.random() * 4000)

    return () => clearInterval(interval)
  }, [isWatchMode])

  // Sync recent files from graph store event log
  const syncFromGraphStore = useCallback(() => {
    const events = graphStore.eventLog
    if (events.length > 0) {
      const files = new Set<string>()
      for (const evt of events) {
        for (const node of evt.nodes) {
          if (node.file) files.add(node.file)
        }
      }
      setRecentFiles(prev => {
        const merged = [...new Set([...Array.from(files), ...prev])]
        return merged.slice(0, 10)
      })
    }
  }, [])

  useEffect(() => {
    syncFromGraphStore()
  }, [syncFromGraphStore])

  const handleToggleWatch = async () => {
    setIsStarting(true)
    try {
      if (!isWatchMode) {
        await runCommand('watch', [workspace])
      } else {
        setWatchMode(false)
      }
    } finally {
      setIsStarting(false)
    }
  }

  const handleClearEvents = () => {
    setFileChanges([])
    setRecentFiles([])
  }

  const getEventTypeIcon = (type: FileChangeEvent['type']) => {
    switch (type) {
      case 'created': return <FilePlus className="h-3 w-3" style={{ color: '#48bb78' }} />
      case 'modified': return <FileEdit className="h-3 w-3" style={{ color: '#ecc94b' }} />
      case 'deleted': return <FileMinus className="h-3 w-3" style={{ color: '#fc8181' }} />
    }
  }

  const getEventTypeBadge = (type: FileChangeEvent['type']) => {
    switch (type) {
      case 'created': return { label: 'CREATED', color: '#48bb78' }
      case 'modified': return { label: 'MODIFIED', color: '#ecc94b' }
      case 'deleted': return { label: 'DELETED', color: '#fc8181' }
    }
  }

  const formatTime = (ts: number) => {
    const d = new Date(ts)
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  }

  return (
    <ScrollArea className="h-full">
      <div className="p-3 space-y-4">
        {/* Watch Mode Status */}
        <div className="space-y-2">
          <div className="text-[10px] font-bold uppercase tracking-widest opacity-50">Watch Mode</div>
          <div
            className="flex items-center justify-between px-3 py-2.5 rounded-md"
            style={{
              backgroundColor: isWatchMode
                ? (dark ? 'rgba(72, 187, 120, 0.08)' : 'rgba(72, 187, 120, 0.06)')
                : (dark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.04)'),
              border: `1px solid ${isWatchMode
                ? (dark ? 'rgba(72, 187, 120, 0.2)' : 'rgba(72, 187, 120, 0.15)')
                : (dark ? '#2d3748' : '#e2e8f0')}`,
            }}
          >
            <div className="flex items-center gap-2">
              {isWatchMode ? (
                <Eye className="h-4 w-4" style={{ color: '#48bb78' }} />
              ) : (
                <EyeOff className="h-4 w-4" style={{ color: dark ? '#718096' : '#94a3b8' }} />
              )}
              <span
                className="text-xs font-medium"
                style={{ color: isWatchMode ? '#48bb78' : (dark ? '#a0aec0' : '#718096') }}
              >
                {isWatchMode ? 'Active' : 'Inactive'}
              </span>
            </div>
            {/* Toggle switch */}
            <button
              className="relative w-9 h-5 rounded-full transition-colors duration-200"
              style={{
                backgroundColor: isWatchMode ? '#48bb78' : (dark ? '#2d3748' : '#cbd5e0'),
              }}
              onClick={handleToggleWatch}
              disabled={isStarting}
              title={isWatchMode ? 'Stop watching' : 'Start watching'}
            >
              <div
                className="absolute top-0.5 w-4 h-4 rounded-full transition-all duration-200"
                style={{
                  left: isWatchMode ? '18px' : '2px',
                  backgroundColor: '#fff',
                  boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
                }}
              />
            </button>
          </div>
        </div>

        {/* Start / Stop Button */}
        <Button
          size="sm"
          className={`w-full h-8 text-xs gap-1.5 ${
            isWatchMode
              ? 'bg-red-600 hover:bg-red-700 text-white'
              : 'bg-green-600 hover:bg-green-700 text-white'
          }`}
          onClick={handleToggleWatch}
          disabled={isStarting}
        >
          {isStarting ? (
            <RefreshCw className="h-3 w-3 animate-spin" />
          ) : isWatchMode ? (
            <Square className="h-3 w-3" />
          ) : (
            <Play className="h-3 w-3" />
          )}
          {isWatchMode ? 'Stop Watch' : 'Start Watch'}
        </Button>

        {/* Watch Info */}
        {isWatchMode && (
          <div
            className="px-3 py-2 rounded-md text-[10px] space-y-1"
            style={{
              backgroundColor: dark ? 'rgba(72, 187, 120, 0.04)' : 'rgba(72, 187, 120, 0.03)',
              border: `1px solid ${dark ? 'rgba(72, 187, 120, 0.1)' : 'rgba(72, 187, 120, 0.08)'}`,
              color: dark ? '#a0aec0' : '#718096',
            }}
          >
            <div>Watching: <span className="font-mono" style={{ color: dark ? '#e2e8f0' : '#1a202c' }}>{workspace}</span></div>
            <div className="flex items-center gap-1">
              <div className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ backgroundColor: '#48bb78' }} />
              <span>Listening for file changes...</span>
            </div>
          </div>
        )}

        <Separator style={{ background: 'linear-gradient(90deg, transparent, rgba(139,92,246,0.15), transparent)', height: '1px' }} />

        {/* Recently Changed Files */}
        {recentFiles.length > 0 && (
          <div className="space-y-1.5">
            <div className="text-[10px] font-bold uppercase tracking-widest opacity-50">Recent Files</div>
            <div className="space-y-0.5">
              {recentFiles.map(file => (
                <div
                  key={file}
                  className="flex items-center gap-1.5 px-2 py-1 rounded text-[11px] font-mono truncate"
                  style={{
                    backgroundColor: dark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.02)',
                    color: dark ? '#a0aec0' : '#718096',
                  }}
                  title={file}
                >
                  <FileEdit className="h-3 w-3 shrink-0" style={{ color: dark ? '#4fd1c5' : '#38b2ac' }} />
                  <span className="truncate">{file.replace(/^.*[\/]/, '')}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        <Separator style={{ background: 'linear-gradient(90deg, transparent, rgba(139,92,246,0.15), transparent)', height: '1px' }} />

        {/* File Change Events */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <div className="text-[10px] font-bold uppercase tracking-widest opacity-50">
              Change Events {fileChanges.length > 0 && <span style={{ color: '#b794f4' }}>({fileChanges.length})</span>}
            </div>
            {fileChanges.length > 0 && (
              <button
                className="text-[10px] flex items-center gap-1 transition-colors"
                style={{ color: dark ? '#718096' : '#94a3b8' }}
                onClick={handleClearEvents}
                onMouseEnter={e => {
                  const el = e.currentTarget as HTMLElement
                  el.style.color = '#fc8181'
                }}
                onMouseLeave={e => {
                  const el = e.currentTarget as HTMLElement
                  el.style.color = dark ? '#718096' : '#94a3b8'
                }}
                title="Clear all events"
              >
                <Trash2 className="h-3 w-3" />
                Clear
              </button>
            )}
          </div>

          {fileChanges.length === 0 ? (
            <div
              className="text-[11px] text-center py-6 rounded-md"
              style={{
                color: dark ? '#4a5568' : '#a0aec0',
                backgroundColor: dark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.02)',
              }}
            >
              {isWatchMode ? 'Waiting for file changes...' : 'Start watch mode to see events'}
            </div>
          ) : (
            <div className="max-h-96 overflow-y-auto space-y-1 pr-1" style={{ scrollbarWidth: 'thin' }}>
              {fileChanges.map(event => {
                const badge = getEventTypeBadge(event.type)
                return (
                  <div
                    key={event.id}
                    className="flex items-center gap-2 px-2 py-1.5 rounded text-[11px]"
                    style={{
                      backgroundColor: dark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.02)',
                    }}
                  >
                    {getEventTypeIcon(event.type)}
                    <span
                      className="font-mono truncate flex-1"
                      style={{ color: dark ? '#e2e8f0' : '#1a202c' }}
                      title={event.file}
                    >
                      {event.file.split('/').pop()}
                    </span>
                    <Badge
                      variant="outline"
                      className="text-[8px] h-4 px-1 shrink-0 font-bold"
                      style={{
                        borderColor: `${badge.color}40`,
                        color: badge.color,
                        backgroundColor: `${badge.color}10`,
                      }}
                    >
                      {badge.label}
                    </Badge>
                    <span
                      className="text-[9px] shrink-0 font-mono"
                      style={{ color: dark ? '#4a5568' : '#a0aec0' }}
                    >
                      {formatTime(event.timestamp)}
                    </span>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* Event Stats */}
        {fileChanges.length > 0 && (
          <div className="space-y-1.5">
            <div className="text-[10px] font-bold uppercase tracking-widest opacity-50">Stats</div>
            <div className="grid grid-cols-3 gap-1.5">
              {(['created', 'modified', 'deleted'] as const).map(type => {
                const count = fileChanges.filter(e => e.type === type).length
                const badge = getEventTypeBadge(type)
                return (
                  <div
                    key={type}
                    className="text-center px-2 py-1.5 rounded"
                    style={{
                      backgroundColor: `${badge.color}08`,
                      border: `1px solid ${badge.color}15`,
                    }}
                  >
                    <div className="text-sm font-bold font-mono" style={{ color: badge.color }}>{count}</div>
                    <div className="text-[9px] uppercase tracking-wider" style={{ color: dark ? '#718096' : '#94a3b8' }}>{type}</div>
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </div>
    </ScrollArea>
  )
}
