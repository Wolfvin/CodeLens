'use client'

import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Search, ArrowUp, ArrowDown, CornerDownLeft, X, Loader2, Sparkles } from 'lucide-react'
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

  // Focus input on mount
  useEffect(() => {
    const timer = setTimeout(() => inputRef.current?.focus(), 80)
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

  const borderColor = dark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'
  const mutedText = dark ? '#718096' : '#94a3b8'
  const text = dark ? '#e2e8f0' : '#1a202c'
  const bg = dark ? 'rgba(12, 12, 24, 0.97)' : 'rgba(255, 255, 255, 0.98)'

  return (
    <AnimatePresence>
      {commandPaletteOpen && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
          className="fixed inset-0 z-[60] flex items-start justify-center pt-[12vh]"
          style={{ backgroundColor: 'rgba(0, 0, 0, 0.55)', backdropFilter: 'blur(4px)' }}
          onClick={() => setCommandPaletteOpen(false)}
        >
          <motion.div
            initial={{ scale: 0.96, y: -8, opacity: 0 }}
            animate={{ scale: 1, y: 0, opacity: 1 }}
            exit={{ scale: 0.96, y: -8, opacity: 0 }}
            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
            className="w-full max-w-lg rounded-2xl overflow-hidden"
            style={{
              backgroundColor: bg,
              border: `1px solid ${borderColor}`,
              boxShadow: dark
                ? '0 24px 80px rgba(0,0,0,0.6), 0 0 0 1px rgba(139,92,246,0.05), 0 0 40px -12px rgba(139,92,246,0.15)'
                : '0 24px 80px rgba(0,0,0,0.15), 0 0 0 1px rgba(0,0,0,0.04)',
            }}
            onClick={e => e.stopPropagation()}
          >
            {/* Search Input with gradient accent */}
            <div
              className="flex items-center gap-3 px-5 py-4"
              style={{ borderBottom: `1px solid ${borderColor}` }}
            >
              <div className="relative">
                <Search className="h-4 w-4 shrink-0" style={{ color: '#b794f4' }} />
              </div>
              {activeArgs ? (
                <div className="flex-1 flex items-center gap-2">
                  <span
                    className="text-xs font-mono px-2 py-0.5 rounded-md"
                    style={{ backgroundColor: 'rgba(183,148,244,0.1)', color: '#b794f4' }}
                  >
                    {activeArgs.name}
                  </span>
                  <input
                    ref={inputRef}
                    type="text"
                    placeholder={activeArgs.args.find(a => a.name !== 'workspace')?.description ?? 'Enter value...'}
                    value={argValues[activeArgs.args.find(a => a.name !== 'workspace')?.name ?? ''] ?? ''}
                    onChange={e => {
                      const argName = activeArgs.args.find(a => a.name !== 'workspace')?.name ?? ''
                      setArgValues(prev => ({ ...prev, [argName]: e.target.value }))
                    }}
                    className="flex-1 bg-transparent text-sm outline-none placeholder:text-slate-500"
                    style={{ color: text }}
                  />
                  <button
                    className="h-6 w-6 flex items-center justify-center rounded-md transition-colors hover:bg-white/10"
                    onClick={() => { setActiveArgs(null); setArgValues({}) }}
                  >
                    <X className="h-3 w-3" style={{ color: mutedText }} />
                  </button>
                </div>
              ) : (
                <input
                  ref={inputRef}
                  type="text"
                  placeholder="Type a command..."
                  value={query}
                  onChange={e => { setQuery(e.target.value); setSelectedIndex(0) }}
                  className="flex-1 bg-transparent text-sm outline-none placeholder:text-slate-500"
                  style={{ color: text }}
                />
              )}
              <kbd
                className="text-[10px] px-2 py-0.5 rounded-md border font-mono"
                style={{
                  borderColor,
                  color: mutedText,
                  backgroundColor: dark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.03)',
                }}
              >
                ESC
              </kbd>
            </div>

            {/* Recent Commands */}
            {!query && !activeArgs && recentCommands.length > 0 && (
              <div className="px-3 py-2" style={{ borderBottom: `1px solid ${borderColor}` }}>
                <div
                  className="text-[10px] font-bold uppercase tracking-[0.1em] px-2 mb-1.5 flex items-center gap-1.5"
                  style={{ color: mutedText }}
                >
                  <Sparkles className="h-2.5 w-2.5" style={{ color: '#b794f4' }} />
                  Recent
                </div>
                {recentCommands.slice(0, 5).map(name => {
                  const cmd = CODELENS_COMMANDS.find(c => c.name === name)
                  if (!cmd) return null
                  return (
                    <button
                      key={name}
                      className="w-full flex items-center gap-2.5 px-3 py-2 text-xs rounded-lg transition-all duration-150"
                      style={{ color: text }}
                      onClick={() => handleSelect(cmd)}
                      onMouseEnter={e => {
                        (e.currentTarget as HTMLElement).style.backgroundColor = dark ? 'rgba(183,148,244,0.06)' : 'rgba(139,92,246,0.04)'
                      }}
                      onMouseLeave={e => {
                        (e.currentTarget as HTMLElement).style.backgroundColor = ''
                      }}
                    >
                      <span className="text-sm">{cmd.icon}</span>
                      <span className="font-medium">{cmd.name}</span>
                      <span className="ml-auto opacity-30 truncate text-[10px] max-w-[160px]">{cmd.description}</span>
                    </button>
                  )
                })}
              </div>
            )}

            {/* Command List */}
            {!activeArgs && (
              <div ref={listRef} className="max-h-72 overflow-y-auto panel-scroll p-1.5">
                {filtered.map((cmd, i) => (
                  <button
                    key={cmd.name}
                    data-selected={i === selectedIndex}
                    className="w-full flex items-center gap-3 px-3 py-2.5 text-xs rounded-lg transition-all duration-150"
                    style={{
                      color: text,
                      backgroundColor: i === selectedIndex ? (dark ? 'rgba(183,148,244,0.08)' : 'rgba(139,92,246,0.05)') : '',
                      boxShadow: i === selectedIndex ? '0 0 12px -6px rgba(183,148,244,0.15)' : '',
                    }}
                    onClick={() => handleSelect(cmd)}
                    onMouseEnter={() => setSelectedIndex(i)}
                  >
                    <span className="text-sm">{cmd.icon}</span>
                    <div className="flex-1 min-w-0">
                      <div className="font-medium">{cmd.name}</div>
                      <div className="opacity-40 text-[10px] truncate mt-0.5">{cmd.description}</div>
                    </div>
                    <span
                      className="text-[9px] px-2 py-0.5 rounded-md font-medium shrink-0"
                      style={{
                        backgroundColor: dark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)',
                        color: mutedText,
                      }}
                    >
                      {cmd.category}
                    </span>
                    {runningCommands.includes(cmd.name) && (
                      <Loader2 className="h-3 w-3 animate-spin shrink-0" style={{ color: '#b794f4' }} />
                    )}
                  </button>
                ))}
                {filtered.length === 0 && (
                  <div className="px-4 py-8 text-center text-xs opacity-40">
                    No commands found
                  </div>
                )}
              </div>
            )}

            {/* Footer */}
            <div
              className="flex items-center gap-4 px-5 py-2.5 text-[10px]"
              style={{
                borderTop: `1px solid ${borderColor}`,
                color: mutedText,
              }}
            >
              <span className="flex items-center gap-1">
                <ArrowUp className="h-2.5 w-2.5" />
                <ArrowDown className="h-2.5 w-2.5" />
                Navigate
              </span>
              <span className="flex items-center gap-1">
                <CornerDownLeft className="h-2.5 w-2.5" />
                Select
              </span>
              <span>ESC Close</span>
              <span className="ml-auto opacity-60">{filtered.length} commands</span>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
