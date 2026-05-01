'use client'

import React, { useRef, useEffect, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, Copy, Download, ChevronDown, ChevronUp, Terminal, Trash2 } from 'lucide-react'
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

  return (
    <AnimatePresence>
      {bottomPanelOpen && (
        <motion.div
          ref={panelRef}
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: 200, opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          transition={{ duration: 0.2, ease: 'easeOut' }}
          className="border-t shrink-0 flex flex-col overflow-hidden"
          style={{
            borderColor: dark ? '#1a202c' : '#e2e8f0',
            backgroundColor: dark ? 'rgba(10,10,15,0.95)' : 'rgba(255,255,255,0.95)',
            backdropFilter: 'blur(16px)',
          }}
        >
          {/* Tab bar */}
          <div
            className="flex items-center h-8 border-b shrink-0"
            style={{ borderColor: dark ? '#2d3748' : '#e2e8f0' }}
          >
            <div className="flex-1 flex items-center overflow-x-auto min-w-0 px-1">
              {resultTabs.map(tab => (
                <button
                  key={tab.id}
                  className="flex items-center gap-1.5 px-2.5 py-1 text-[11px] rounded-md transition-colors shrink-0"
                  style={{
                    color: tab.id === activeResultTab ? (dark ? '#e2e8f0' : '#1a202c') : (dark ? '#a0aec0' : '#718096'),
                    backgroundColor: tab.id === activeResultTab ? (dark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)') : '',
                  }}
                  onClick={() => setActiveResultTab(tab.id)}
                >
                  <Terminal className="h-3 w-3" />
                  <span className="truncate max-w-[100px]">{tab.command}</span>
                  <button
                    className="h-3.5 w-3.5 flex items-center justify-center rounded hover:bg-white/10 ml-0.5"
                    onClick={e => { e.stopPropagation(); removeResultTab(tab.id) }}
                  >
                    <X className="h-2.5 w-2.5" />
                  </button>
                </button>
              ))}
            </div>

            {/* Toolbar */}
            <div className="flex items-center gap-0.5 px-1 shrink-0">
              {activeTab && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6"
                  title="Copy to clipboard"
                  onClick={() => copyToClipboard(activeTab.content)}
                >
                  <Copy className="h-3 w-3" />
                </Button>
              )}
              {resultTabs.length > 0 && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6"
                  title="Clear all results"
                  onClick={clearResultTabs}
                >
                  <Trash2 className="h-3 w-3" />
                </Button>
              )}
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6"
                title="Close panel"
                onClick={toggleBottomPanel}
              >
                <ChevronDown className="h-3 w-3" />
              </Button>
            </div>
          </div>

          {/* Content */}
          <div ref={scrollRef} className="flex-1 overflow-auto">
            {activeTab ? (
              <pre
                className="p-3 text-xs font-mono leading-relaxed whitespace-pre-wrap break-words"
                style={{ color: dark ? '#a0aec0' : '#4a5568' }}
              >
                {formatContent(activeTab.content)}
              </pre>
            ) : (
              <div className="flex items-center justify-center h-full text-xs opacity-40">
                Run a command to see results here
              </div>
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
