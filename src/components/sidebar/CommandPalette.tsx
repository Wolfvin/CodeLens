'use client'

import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Search, ArrowUp, ArrowDown, CornerDownLeft, X, Loader2 } from 'lucide-react'
import { CODELENS_COMMANDS } from '@/types/neural'
import type { CommandDef } from '@/types/neural'
import { useAnalysisStore } from '@/lib/analysisStore'

interface CommandPaletteProps {
  theme: 'dark' | 'light'
}

export function CommandPalette({ theme }: CommandPaletteProps) {
  const { commandPaletteOpen, setCommandPaletteOpen, runCommand, workspace, recentCommands, runningCommands } = useAnalysisStore()
  const [query, setQuery] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [activeArgs, setActiveArgs] = useState<CommandDef | null>(null)
  const [argValues, setArgValues] = useState<Record<string, string>>({})
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const dark = theme === 'dark'

  // Filter commands
  const filtered = useMemo(() => {
    if (!query.trim()) return CODELENS_COMMANDS
    const q = query.toLowerCase()
    const terms = q.split(/\s+/).filter(Boolean)
    return CODELENS_COMMANDS.filter(cmd => {
      const text = `${cmd.name} ${cmd.description} ${cmd.category}`.toLowerCase()
      return terms.every(t => text.includes(t))
    })
  }, [query])

  // Reset on open - component remounts via AnimatePresence, so state naturally resets
  // Focus input on mount
  useEffect(() => {
    const timer = setTimeout(() => inputRef.current?.focus(), 50)
    return () => clearTimeout(timer)
  }, [])

  // Keyboard handler
  useEffect(() => {
    if (!commandPaletteOpen) return

    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        if (activeArgs) {
          setActiveArgs(null)
          setArgValues({})
        } else {
          setCommandPaletteOpen(false)
        }
      } else if (e.key === 'ArrowDown') {
        e.preventDefault()
        setSelectedIndex(i => Math.min(i + 1, filtered.length - 1))
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        setSelectedIndex(i => Math.max(i - 1, 0))
      } else if (e.key === 'Enter') {
        e.preventDefault()
        if (activeArgs) {
          // Run with args
          const nonWorkspaceArgs = activeArgs.args.filter(a => a.name !== 'workspace')
          const filledArgs = nonWorkspaceArgs.map(a => argValues[a.name] || '').filter(Boolean)
          runCommand(activeArgs.name, [...filledArgs, workspace])
          setCommandPaletteOpen(false)
        } else if (filtered[selectedIndex]) {
          const cmd = filtered[selectedIndex]
          const needsArgs = cmd.args.some(a => a.required && a.name !== 'workspace')
          if (needsArgs) {
            setActiveArgs(cmd)
            setArgValues({})
          } else {
            runCommand(cmd.name, [workspace])
            setCommandPaletteOpen(false)
          }
        }
      }
    }

    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [commandPaletteOpen, filtered, selectedIndex, activeArgs, argValues, runCommand, workspace, setCommandPaletteOpen])

  // Scroll selected into view
  useEffect(() => {
    if (listRef.current) {
      const selected = listRef.current.querySelector('[data-selected="true"]')
      selected?.scrollIntoView({ block: 'nearest' })
    }
  }, [selectedIndex])

  const handleSelect = useCallback((cmd: CommandDef) => {
    const needsArgs = cmd.args.some(a => a.required && a.name !== 'workspace')
    if (needsArgs) {
      setActiveArgs(cmd)
      setArgValues({})
    } else {
      runCommand(cmd.name, [workspace])
      setCommandPaletteOpen(false)
    }
  }, [runCommand, workspace, setCommandPaletteOpen])

  return (
    <AnimatePresence>
      {commandPaletteOpen && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
          className="fixed inset-0 z-[60] flex items-start justify-center pt-[15vh]"
          style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}
          onClick={() => setCommandPaletteOpen(false)}
        >
          <motion.div
            initial={{ scale: 0.95, y: -10 }}
            animate={{ scale: 1, y: 0 }}
            exit={{ scale: 0.95, y: -10 }}
            transition={{ duration: 0.15 }}
            className="w-full max-w-lg rounded-xl border shadow-2xl overflow-hidden"
            style={{
              backgroundColor: dark ? '#1a1a2e' : '#ffffff',
              borderColor: dark ? '#2d3748' : '#e2e8f0',
            }}
            onClick={e => e.stopPropagation()}
          >
            {/* Search Input */}
            <div
              className="flex items-center gap-2 px-4 py-3 border-b"
              style={{ borderColor: dark ? '#2d3748' : '#e2e8f0' }}
            >
              <Search className="h-4 w-4 shrink-0" style={{ color: dark ? '#a0aec0' : '#718096' }} />
              {activeArgs ? (
                <div className="flex-1 flex items-center gap-1">
                  <span className="text-xs font-mono" style={{ color: '#b794f4' }}>{activeArgs.name}</span>
                  <input
                    ref={inputRef}
                    type="text"
                    placeholder={activeArgs.args.find(a => a.name !== 'workspace')?.description ?? 'Enter value...'}
                    value={argValues[activeArgs.args.find(a => a.name !== 'workspace')?.name ?? ''] ?? ''}
                    onChange={e => {
                      const argName = activeArgs.args.find(a => a.name !== 'workspace')?.name ?? ''
                      setArgValues(prev => ({ ...prev, [argName]: e.target.value }))
                    }}
                    className="flex-1 bg-transparent text-sm outline-none"
                    style={{ color: dark ? '#e2e8f0' : '#1a202c' }}
                  />
                  <button
                    className="h-5 w-5 flex items-center justify-center rounded hover:bg-white/10"
                    onClick={() => { setActiveArgs(null); setArgValues({}) }}
                  >
                    <X className="h-3 w-3" style={{ color: dark ? '#a0aec0' : '#718096' }} />
                  </button>
                </div>
              ) : (
                <input
                  ref={inputRef}
                  type="text"
                  placeholder="Type a command..."
                  value={query}
                  onChange={e => { setQuery(e.target.value); setSelectedIndex(0) }}
                  className="flex-1 bg-transparent text-sm outline-none"
                  style={{ color: dark ? '#e2e8f0' : '#1a202c' }}
                />
              )}
              <kbd
                className="text-[10px] px-1.5 py-0.5 rounded border font-mono"
                style={{
                  borderColor: dark ? '#2d3748' : '#e2e8f0',
                  color: dark ? '#a0aec0' : '#718096',
                  backgroundColor: dark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)',
                }}
              >
                ESC
              </kbd>
            </div>

            {/* Recent Commands */}
            {!query && !activeArgs && recentCommands.length > 0 && (
              <div className="px-2 py-1.5 border-b" style={{ borderColor: dark ? '#2d3748' : '#e2e8f0' }}>
                <div className="text-[10px] font-bold uppercase tracking-widest px-2 mb-1" style={{ color: dark ? '#a0aec0' : '#718096' }}>
                  Recent
                </div>
                {recentCommands.slice(0, 5).map(name => {
                  const cmd = CODELENS_COMMANDS.find(c => c.name === name)
                  if (!cmd) return null
                  return (
                    <button
                      key={name}
                      className="w-full flex items-center gap-2 px-2 py-1.5 text-xs rounded transition-colors"
                      style={{ color: dark ? '#e2e8f0' : '#1a202c' }}
                      onClick={() => handleSelect(cmd)}
                      onMouseEnter={e => { (e.currentTarget as HTMLElement).style.backgroundColor = dark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.04)' }}
                      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.backgroundColor = '' }}
                    >
                      <span>{cmd.icon}</span>
                      <span className="font-medium">{cmd.name}</span>
                      <span className="ml-auto opacity-40 truncate text-[10px]">{cmd.description}</span>
                    </button>
                  )
                })}
              </div>
            )}

            {/* Command List */}
            {!activeArgs && (
              <div ref={listRef} className="max-h-72 overflow-y-auto p-1">
                {filtered.map((cmd, i) => (
                  <button
                    key={cmd.name}
                    data-selected={i === selectedIndex}
                    className="w-full flex items-center gap-2 px-3 py-2 text-xs rounded-md transition-colors"
                    style={{
                      color: dark ? '#e2e8f0' : '#1a202c',
                      backgroundColor: i === selectedIndex ? (dark ? 'rgba(183,148,244,0.1)' : 'rgba(183,148,244,0.08)') : '',
                    }}
                    onClick={() => handleSelect(cmd)}
                    onMouseEnter={() => setSelectedIndex(i)}
                  >
                    <span className="text-sm">{cmd.icon}</span>
                    <div className="flex-1 min-w-0">
                      <div className="font-medium">{cmd.name}</div>
                      <div className="opacity-50 text-[10px] truncate">{cmd.description}</div>
                    </div>
                    <span
                      className="text-[9px] px-1.5 py-0.5 rounded font-medium"
                      style={{
                        backgroundColor: dark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)',
                        color: dark ? '#a0aec0' : '#718096',
                      }}
                    >
                      {cmd.category}
                    </span>
                    {runningCommands.includes(cmd.name) && <Loader2 className="h-3 w-3 animate-spin text-purple-400" />}
                  </button>
                ))}
                {filtered.length === 0 && (
                  <div className="px-3 py-6 text-center text-xs opacity-50">
                    No commands found
                  </div>
                )}
              </div>
            )}

            {/* Footer */}
            <div
              className="flex items-center gap-3 px-4 py-2 border-t text-[10px]"
              style={{
                borderColor: dark ? '#2d3748' : '#e2e8f0',
                color: dark ? '#718096' : '#a0aec0',
              }}
            >
              <span className="flex items-center gap-1"><ArrowUp className="h-2.5 w-2.5" /><ArrowDown className="h-2.5 w-2.5" /> Navigate</span>
              <span className="flex items-center gap-1"><CornerDownLeft className="h-2.5 w-2.5" /> Select</span>
              <span>ESC Close</span>
              <span className="ml-auto">{filtered.length} commands</span>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
