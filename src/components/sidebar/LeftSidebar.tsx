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
  { id: 'commands', icon: <Terminal className="h-4 w-4" />, label: 'Commands' },
  { id: 'workspace', icon: <Radio className="h-4 w-4" />, label: 'Workspace' },
  { id: 'security', icon: <Shield className="h-4 w-4" />, label: 'Security' },
  { id: 'quality', icon: <CheckCircle2 className="h-4 w-4" />, label: 'Quality' },
  { id: 'performance', icon: <Zap className="h-4 w-4" />, label: 'Performance' },
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
          animate={{ width: 300, opacity: 1 }}
          exit={{ width: 0, opacity: 0 }}
          transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
          className="flex shrink-0 overflow-hidden"
          style={{
            borderRight: `1px solid ${dark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.06)'}`,
            backgroundColor: dark ? 'rgba(8, 8, 16, 0.6)' : 'rgba(255, 255, 255, 0.75)',
            backdropFilter: 'blur(24px) saturate(1.3)',
            WebkitBackdropFilter: 'blur(24px) saturate(1.3)',
            boxShadow: dark
              ? 'inset -1px 0 0 rgba(255,255,255,0.03), 2px 0 16px rgba(0,0,0,0.3)'
              : 'inset -1px 0 0 rgba(0,0,0,0.04), 2px 0 12px rgba(0,0,0,0.06)',
          }}
        >
          {/* Icon rail */}
          <div
            className="w-11 flex flex-col items-center py-2.5 gap-1 shrink-0"
            style={{ borderRight: `1px solid ${dark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.04)'}` }}
          >
            {/* Collapse button */}
            <button
              className="w-8 h-8 flex items-center justify-center rounded-lg transition-all duration-200 mb-1"
              style={{ color: dark ? '#718096' : '#94a3b8' }}
              onClick={toggleSidebar}
              onMouseEnter={e => {
                const el = e.currentTarget as HTMLElement
                el.style.backgroundColor = dark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)'
                el.style.color = dark ? '#a0aec0' : '#64748b'
              }}
              onMouseLeave={e => {
                const el = e.currentTarget as HTMLElement
                el.style.backgroundColor = ''
                el.style.color = dark ? '#718096' : '#94a3b8'
              }}
              title="Collapse sidebar"
            >
              <ChevronLeft className="h-3.5 w-3.5" />
            </button>

            {/* Divider */}
            <div
              className="w-5 h-px mb-1"
              style={{ backgroundColor: dark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)' }}
            />

            {TABS.map(tab => {
              const isActive = sidebarTab === tab.id
              return (
                <button
                  key={tab.id}
                  className="w-8 h-8 flex items-center justify-center rounded-lg transition-all duration-200 relative group"
                  style={{
                    color: isActive ? '#b794f4' : dark ? '#718096' : '#94a3b8',
                    backgroundColor: isActive ? (dark ? 'rgba(183,148,244,0.08)' : 'rgba(139,92,246,0.06)') : '',
                    boxShadow: isActive ? '0 0 12px -4px rgba(183,148,244,0.2)' : '',
                  }}
                  onClick={() => setSidebarTab(tab.id)}
                  onMouseEnter={e => {
                    if (!isActive) {
                      const el = e.currentTarget as HTMLElement
                      el.style.backgroundColor = dark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)'
                      el.style.color = dark ? '#a0aec0' : '#64748b'
                    }
                  }}
                  onMouseLeave={e => {
                    if (!isActive) {
                      const el = e.currentTarget as HTMLElement
                      el.style.backgroundColor = ''
                      el.style.color = dark ? '#718096' : '#94a3b8'
                    }
                  }}
                  title={tab.label}
                >
                  {tab.icon}
                  {/* Active indicator */}
                  {isActive && (
                    <motion.div
                      layoutId="sidebar-indicator"
                      className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-4 rounded-full"
                      style={{
                        backgroundColor: '#b794f4',
                        boxShadow: '0 0 6px rgba(183,148,244,0.5)',
                      }}
                      transition={{ type: 'spring', stiffness: 300, damping: 25 }}
                    />
                  )}
                </button>
              )
            })}
          </div>

          {/* Content area */}
          <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
            {/* Header with gradient text */}
            <div
              className="px-4 py-3 flex items-center gap-2 shrink-0"
              style={{ borderBottom: `1px solid ${dark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.06)'}` }}
            >
              <span
                className="text-xs font-semibold tracking-wide uppercase"
                style={{
                  color: dark ? '#a0aec0' : '#64748b',
                  letterSpacing: '0.08em',
                }}
              >
                {TABS.find(t => t.id === sidebarTab)?.label ?? ''}
              </span>
              <div className="flex-1" />
              <div
                className="w-1.5 h-1.5 rounded-full breathe"
                style={{ backgroundColor: '#b794f4', boxShadow: '0 0 6px rgba(183,148,244,0.4)' }}
              />
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
