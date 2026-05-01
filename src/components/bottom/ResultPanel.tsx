'use client'

import React, { useRef, useEffect, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, Copy, Download, ChevronDown, Terminal, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useAnalysisStore } from '@/lib/analysisStore'
import type { ResultTab } from '@/types/neural'

interface ResultPanelProps {
  theme: 'dark' | 'light'
}

export function ResultPanel({ theme }: ResultPanelProps) {
  const {
    resultTabs, activeResultTab, bottomPanelOpen,
    setActiveResultTab, removeResultTab, clearResultTabs,
    toggleBottomPanel,
  } = useAnalysisStore()

  const panelRef = useRef<HTMLDivElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const dark = theme === 'dark'

  const activeTab = resultTabs.find(t => t.id === activeResultTab)

  // Auto-scroll to bottom
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [resultTabs])

  const copyToClipboard = useCallback((content: unknown) => {
    const text = typeof content === 'string' ? content : JSON.stringify(content, null, 2)
    navigator.clipboard.writeText(text).catch(() => {})
  }, [])

  const formatContent = (content: unknown): string => {
    if (typeof content === 'string') return content
    try {
      return JSON.stringify(content, null, 2)
    } catch {
      return String(content)
    }
  }

  const borderColor = dark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.06)'
  const bgColor = dark ? 'rgba(8, 8, 16, 0.75)' : 'rgba(255, 255, 255, 0.85)'
  const textColor = dark ? '#a0aec0' : '#4a5568'
  const mutedText = dark ? '#718096' : '#94a3b8'

  return (
    <AnimatePresence>
      {bottomPanelOpen && (
        <motion.div
          ref={panelRef}
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: 220, opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
          className="shrink-0 flex flex-col overflow-hidden"
          style={{
            backgroundColor: bgColor,
            borderTop: `1px solid ${borderColor}`,
            backdropFilter: 'blur(20px) saturate(1.2)',
            WebkitBackdropFilter: 'blur(20px) saturate(1.2)',
            boxShadow: dark
              ? '0 -4px 24px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.02)'
              : '0 -4px 16px rgba(0,0,0,0.06), inset 0 1px 0 rgba(0,0,0,0.02)',
          }}
        >
          {/* Tab bar with smooth underline indicator */}
          <div
            className="flex items-center h-9 shrink-0 relative"
            style={{ borderBottom: `1px solid ${borderColor}` }}
          >
            <div className="flex-1 flex items-center overflow-x-auto min-w-0 px-1.5 panel-scroll">
              {resultTabs.map(tab => {
                const isActive = tab.id === activeResultTab
                return (
                  <button
                    key={tab.id}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] rounded-lg transition-all duration-200 shrink-0 mx-0.5 relative underline-indicator"
                    style={{
                      color: isActive ? '#b794f4' : mutedText,
                      backgroundColor: isActive ? 'rgba(183,148,244,0.08)' : '',
                      boxShadow: isActive ? '0 0 8px -4px rgba(183,148,244,0.15)' : '',
                    }}
                    onClick={() => setActiveResultTab(tab.id)}
                  >
                    <Terminal className="h-3 w-3" />
                    <span className="truncate max-w-[100px] font-medium">{tab.command}</span>
                    <button
                      className="h-4 w-4 flex items-center justify-center rounded-md transition-colors hover:bg-white/10 ml-0.5 close-btn-rotate"
                      onClick={e => { e.stopPropagation(); removeResultTab(tab.id) }}
                    >
                      <X className="h-2.5 w-2.5" />
                    </button>
                    {/* Smooth underline indicator */}
                    {isActive && (
                      <motion.div
                        layoutId="result-tab-indicator"
                        className="absolute bottom-0 left-2 right-2 h-0.5 rounded-full"
                        style={{
                          background: 'linear-gradient(90deg, transparent, #b794f4, transparent)',
                        }}
                        transition={{ type: 'spring', stiffness: 300, damping: 25 }}
                      />
                    )}
                  </button>
                )
              })}
            </div>

            {/* Toolbar */}
            <div className="flex items-center gap-0.5 px-2 shrink-0">
              {activeTab && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 smooth-colors hover:bg-white/5 btn-bounce"
                  title="Copy to clipboard"
                  onClick={() => copyToClipboard(activeTab.content)}
                >
                  <Copy className="h-3 w-3" style={{ color: mutedText }} />
                </Button>
              )}
              {resultTabs.length > 0 && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 smooth-colors hover:bg-white/5 btn-bounce"
                  title="Clear all results"
                  onClick={clearResultTabs}
                >
                  <Trash2 className="h-3 w-3" style={{ color: mutedText }} />
                </Button>
              )}
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6 smooth-colors hover:bg-white/5 close-btn-rotate"
                title="Close panel"
                onClick={toggleBottomPanel}
              >
                <ChevronDown className="h-3 w-3" style={{ color: mutedText }} />
              </Button>
            </div>
          </div>

          {/* Content with fade transition */}
          <div ref={scrollRef} className="flex-1 overflow-auto panel-scroll">
            <AnimatePresence mode="wait">
              {activeTab ? (
                <motion.div
                  key={activeTab.id}
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -4 }}
                  transition={{ duration: 0.15, ease: [0.16, 1, 0.3, 1] }}
                >
                  <pre
                    className="p-4 text-xs font-mono leading-relaxed whitespace-pre-wrap break-words"
                    style={{ color: textColor }}
                  >
                    {formatContent(activeTab.content)}
                  </pre>
                </motion.div>
              ) : (
                <div className="flex items-center justify-center h-full text-xs opacity-30">
                  Run a command to see results here
                </div>
              )}
            </AnimatePresence>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
