'use client'

import React from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Terminal,
  Radio,
  Shield,
  CheckCircle2,
  Zap,
  Palette,
  ChevronLeft,
} from 'lucide-react'
import { CommandsTab } from './CommandsTab'
import { WorkspaceTab } from './WorkspaceTab'
import { SecurityTab } from './SecurityTab'
import { QualityTab } from './QualityTab'
import { PerformanceTab } from './PerformanceTab'
import { CssTab } from './CssTab'
import { useAnalysisStore } from '@/lib/analysisStore'
import type { SidebarTab } from '@/types/neural'

interface LeftSidebarProps {
  theme: 'dark' | 'light'
}

const TABS: Array<{ id: SidebarTab; icon: React.ReactNode; label: string }> = [
  { id: 'commands', icon: <Terminal className="h-4 w-4" />, label: 'Cmd' },
  { id: 'workspace', icon: <Radio className="h-4 w-4" />, label: 'Scan' },
  { id: 'security', icon: <Shield className="h-4 w-4" />, label: 'Sec' },
  { id: 'quality', icon: <CheckCircle2 className="h-4 w-4" />, label: 'Qual' },
  { id: 'performance', icon: <Zap className="h-4 w-4" />, label: 'Perf' },
  { id: 'css', icon: <Palette className="h-4 w-4" />, label: 'CSS' },
]

export function LeftSidebar({ theme }: LeftSidebarProps) {
  const { sidebarOpen, sidebarTab, setSidebarTab, toggleSidebar } = useAnalysisStore()
  const dark = theme === 'dark'

  return (
    <AnimatePresence>
      {sidebarOpen && (
        <motion.div
          initial={{ width: 0, opacity: 0 }}
          animate={{ width: 280, opacity: 1 }}
          exit={{ width: 0, opacity: 0 }}
          transition={{ duration: 0.2, ease: 'easeOut' }}
          className="flex shrink-0 overflow-hidden border-r"
          style={{
            borderColor: dark ? '#1a202c' : '#e2e8f0',
            backgroundColor: dark ? 'rgba(10,10,15,0.9)' : 'rgba(255,255,255,0.95)',
            backdropFilter: 'blur(16px)',
            WebkitBackdropFilter: 'blur(16px)',
          }}
        >
          {/* Icon rail */}
          <div
            className="w-10 flex flex-col items-center py-2 gap-1 border-r shrink-0"
            style={{ borderColor: dark ? '#1a202c' : '#e2e8f0' }}
          >
            {/* Collapse button */}
            <button
              className="w-7 h-7 flex items-center justify-center rounded transition-colors mb-1"
              style={{ color: dark ? '#a0aec0' : '#718096' }}
              onClick={toggleSidebar}
              onMouseEnter={e => { (e.currentTarget as HTMLElement).style.backgroundColor = dark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)' }}
              onMouseLeave={e => { (e.currentTarget as HTMLElement).style.backgroundColor = '' }}
              title="Collapse sidebar"
            >
              <ChevronLeft className="h-3.5 w-3.5" />
            </button>

            {TABS.map(tab => {
              const isActive = sidebarTab === tab.id
              return (
                <button
                  key={tab.id}
                  className="w-7 h-7 flex items-center justify-center rounded transition-colors relative"
                  style={{
                    color: isActive ? '#b794f4' : dark ? '#a0aec0' : '#718096',
                    backgroundColor: isActive ? (dark ? 'rgba(183,148,244,0.12)' : 'rgba(183,148,244,0.08)') : '',
                  }}
                  onClick={() => setSidebarTab(tab.id)}
                  onMouseEnter={e => {
                    if (!isActive) (e.currentTarget as HTMLElement).style.backgroundColor = dark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'
                  }}
                  onMouseLeave={e => {
                    if (!isActive) (e.currentTarget as HTMLElement).style.backgroundColor = ''
                  }}
                  title={tab.label}
                >
                  {tab.icon}
                  {isActive && (
                    <motion.div
                      layoutId="sidebar-indicator"
                      className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-4 rounded-full"
                      style={{ backgroundColor: '#b794f4' }}
                    />
                  )}
                </button>
              )
            })}
          </div>

          {/* Content area */}
          <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
            {/* Header */}
            <div
              className="px-3 py-2 border-b flex items-center gap-2 shrink-0"
              style={{ borderColor: dark ? '#2d3748' : '#e2e8f0' }}
            >
              <span className="text-xs font-semibold" style={{ color: dark ? '#e2e8f0' : '#1a202c' }}>
                {TABS.find(t => t.id === sidebarTab)?.label ?? ''}
              </span>
            </div>

            {/* Tab content */}
            <div className="flex-1 overflow-hidden">
              {sidebarTab === 'commands' && <CommandsTab theme={theme} />}
              {sidebarTab === 'workspace' && <WorkspaceTab theme={theme} />}
              {sidebarTab === 'security' && <SecurityTab theme={theme} />}
              {sidebarTab === 'quality' && <QualityTab theme={theme} />}
              {sidebarTab === 'performance' && <PerformanceTab theme={theme} />}
              {sidebarTab === 'css' && <CssTab theme={theme} />}
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
