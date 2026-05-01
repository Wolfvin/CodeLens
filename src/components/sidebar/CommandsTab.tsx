'use client'

import React, { useState, useMemo } from 'react'
import { Search, Loader2, ChevronRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'
import { CODELENS_COMMANDS } from '@/types/neural'
import type { CommandDef } from '@/types/neural'
import { useAnalysisStore } from '@/lib/analysisStore'

interface CommandsTabProps {
  theme: 'dark' | 'light'
}

const CATEGORIES = ['Core', 'P1', 'P2', 'P3', 'Security', 'Quality', 'Performance', 'CSS', 'Refactoring']

export function CommandsTab({ theme }: CommandsTabProps) {
  const [searchQuery, setSearchQuery] = useState('')
  const [expandedCategory, setExpandedCategory] = useState<string | null>('Core')
  const { runCommand, runningCommands, workspace } = useAnalysisStore()

  const filtered = useMemo(() => {
    if (!searchQuery.trim()) return CODELENS_COMMANDS
    const q = searchQuery.toLowerCase()
    return CODELENS_COMMANDS.filter(
      c => c.name.toLowerCase().includes(q) || c.description.toLowerCase().includes(q) || c.category.toLowerCase().includes(q)
    )
  }, [searchQuery])

  const grouped = useMemo(() => {
    const map: Record<string, CommandDef[]> = {}
    for (const cat of CATEGORIES) {
      const items = filtered.filter(c => c.category === cat)
      if (items.length > 0) map[cat] = items
    }
    return map
  }, [filtered])

  const handleRun = (cmd: CommandDef) => {
    const args = cmd.args
      .filter(a => a.name !== 'workspace')
      .map(a => a.name === 'name' || a.name === 'pattern' || a.name === 'file' ? '' : '')
      .filter(Boolean)
    runCommand(cmd.name, [workspace])
  }

  const isRunning = (name: string) => runningCommands.includes(name)

  return (
    <div className="flex flex-col h-full">
      <div className="p-3 border-b" style={{ borderColor: theme === 'dark' ? '#2d3748' : '#e2e8f0' }}>
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 opacity-50" />
          <Input
            type="text"
            placeholder="Search commands..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            className="h-8 pl-8 pr-3 text-xs"
            style={{
              backgroundColor: theme === 'dark' ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.04)',
              color: theme === 'dark' ? '#e2e8f0' : '#1a202c',
              borderColor: theme === 'dark' ? '#2d3748' : '#e2e8f0',
            }}
          />
        </div>
      </div>

      <ScrollArea className="flex-1">
        <div className="p-2">
          {Object.entries(grouped).map(([category, cmds]) => (
            <div key={category} className="mb-2">
              <button
                className="w-full flex items-center gap-1.5 px-2 py-1.5 text-[10px] font-bold uppercase tracking-widest rounded transition-colors"
                style={{ color: theme === 'dark' ? '#a0aec0' : '#718096' }}
                onClick={() => setExpandedCategory(expandedCategory === category ? null : category)}
              >
                <ChevronRight
                  className="h-3 w-3 transition-transform"
                  style={{ transform: expandedCategory === category ? 'rotate(90deg)' : 'rotate(0deg)' }}
                />
                {category}
                <Badge
                  variant="outline"
                  className="text-[9px] h-4 ml-auto px-1"
                  style={{ borderColor: theme === 'dark' ? '#2d3748' : '#e2e8f0' }}
                >
                  {cmds.length}
                </Badge>
              </button>

              {expandedCategory === category && (
                <div className="ml-1 space-y-0.5">
                  {cmds.map(cmd => (
                    <button
                      key={cmd.name}
                      className="w-full flex items-center gap-2 px-2 py-2 rounded-md text-left transition-colors group"
                      style={{ color: theme === 'dark' ? '#e2e8f0' : '#1a202c' }}
                      onClick={() => handleRun(cmd)}
                      onMouseEnter={e => {
                        (e.currentTarget as HTMLElement).style.backgroundColor = theme === 'dark'
                          ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.04)'
                      }}
                      onMouseLeave={e => {
                        (e.currentTarget as HTMLElement).style.backgroundColor = ''
                      }}
                      disabled={isRunning(cmd.name)}
                    >
                      <span className="text-sm shrink-0">{cmd.icon}</span>
                      <div className="flex-1 min-w-0">
                        <div className="text-xs font-medium truncate">{cmd.name}</div>
                        <div className="text-[10px] opacity-60 truncate">{cmd.description}</div>
                      </div>
                      {isRunning(cmd.name) ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin shrink-0 text-purple-400" />
                      ) : (
                        <ChevronRight className="h-3 w-3 opacity-0 group-hover:opacity-50 transition-opacity shrink-0" />
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </ScrollArea>
    </div>
  )
}
