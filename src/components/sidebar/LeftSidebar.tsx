'use client'

import React, { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Terminal,
  Radio,
  Shield,
  CheckCircle2,
  Zap,
  Palette,
  ChevronLeft,
  Crosshair,
  Layers,
  Hammer,
  Eye,
} from 'lucide-react'
import { CommandsTab } from './CommandsTab'
import { WorkspaceTab } from './WorkspaceTab'
import { SecurityTab } from './SecurityTab'
import { QualityTab } from './QualityTab'
import { PerformanceTab } from './PerformanceTab'
import { CssTab } from './CssTab'
import { P1Tab } from './P1Tab'
import { P2P3Tab } from './P2P3Tab'
import { RefactoringTab } from './RefactoringTab'
import { WatchTab } from './WatchTab'
import { useAnalysisStore } from '@/lib/analysisStore'
import type { SidebarTab } from '@/types/neural'

interface LeftSidebarProps {
  theme: 'dark' | 'light'
}

const TABS: Array<{ id: SidebarTab; icon: React.ReactNode; label: string }> = [
  { id: 'commands', icon: <Terminal className="h-4 w-4" />, label: 'Commands' },
  { id: 'workspace', icon: <Radio className="h-4 w-4" />, label: 'Workspace' },
  { id: 'p1', icon: <Crosshair className="h-4 w-4" />, label: 'P1: Search' },
  { id: 'p2p3', icon: <Layers className="h-4 w-4" />, label: 'P2/P3: Analysis' },
  { id: 'security', icon: <Shield className="h-4 w-4" />, label: 'Security' },
  { id: 'quality', icon: <CheckCircle2 className="h-4 w-4" />, label: 'Quality' },
  { id: 'performance', icon: <Zap className="h-4 w-4" />, label: 'Performance' },
  { id: 'css', icon: <Palette className="h-4 w-4" />, label: 'CSS' },
  { id: 'refactoring', icon: <Hammer className="h-4 w-4" />, label: 'Refactoring' },
  { id: 'watch', icon: <Eye className="h-4 w-4" />, label: 'Watch' },
]

export function LeftSidebar({ theme }: LeftSidebarProps) {
  const { sidebarOpen, sidebarTab, setSidebarTab, toggleSidebar } = useAnalysisStore()
  const dark = theme === 'dark'
  const [prevTab, setPrevTab] = useState<SidebarTab>(sidebarTab)

  // Track tab changes for animation direction
  useEffect(() => {
    setPrevTab(sidebarTab)
  }, [sidebarTab])

  const tabContent = () => {
    switch (sidebarTab) {
      case 'commands': return <CommandsTab theme={theme} />
      case 'workspace': return <WorkspaceTab theme={theme} />
      case 'p1': return <P1Tab theme={theme} />
      case 'p2p3': return <P2P3Tab theme={theme} />
      case 'security': return <SecurityTab theme={theme} />
      case 'quality': return <QualityTab theme={theme} />
      case 'performance': return <PerformanceTab theme={theme} />
      case 'css': return <CssTab theme={theme} />
      case 'refactoring': return <RefactoringTab theme={theme} />
      case 'watch': return <WatchTab theme={theme} />
      default: return null
    }
  }

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
          {/* Icon rail with gradient overlay */}
          <div
            className="w-11 flex flex-col items-center py-2.5 gap-1 shrink-0 overflow-y-auto icon-rail"
            style={{ borderRight: `1px solid ${dark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.04)'}` }}
          >
            {/* Collapse button */}
            <button
              className="w-8 h-8 flex items-center justify-center rounded-lg transition-all duration-200 mb-1 btn-bounce"
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

            {/* Divider with gradient */}
            <div
              className="w-5 h-px mb-1"
              style={{ background: `linear-gradient(90deg, transparent, ${dark ? 'rgba(183,148,244,0.2)' : 'rgba(139,92,246,0.15)'}, transparent)` }}
            />

            {TABS.map(tab => {
              const isActive = sidebarTab === tab.id
              return (
                <button
                  key={tab.id}
                  className="w-8 h-8 flex items-center justify-center rounded-lg transition-all duration-200 relative group btn-bounce"
                  style={{
                    color: isActive ? '#b794f4' : dark ? '#718096' : '#94a3b8',
                    backgroundColor: isActive ? (dark ? 'rgba(183,148,244,0.08)' : 'rgba(139,92,246,0.06)') : '',
                    boxShadow: isActive ? '0 0 12px -4px rgba(183,148,244,0.2)' : '',
                    transform: isActive ? 'scale(1.05)' : '',
                  }}
                  onClick={() => setSidebarTab(tab.id)}
                  onMouseEnter={e => {
                    if (!isActive) {
                      const el = e.currentTarget as HTMLElement
                      el.style.backgroundColor = dark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)'
                      el.style.color = dark ? '#a0aec0' : '#64748b'
                      el.style.transform = 'scale(1.05)'
                      el.style.boxShadow = '0 0 8px -4px rgba(183,148,244,0.1)'
                    }
                  }}
                  onMouseLeave={e => {
                    if (!isActive) {
                      const el = e.currentTarget as HTMLElement
                      el.style.backgroundColor = ''
                      el.style.color = dark ? '#718096' : '#94a3b8'
                      el.style.transform = ''
                      el.style.boxShadow = ''
                    }
                  }}
                  title={tab.label}
                >
                  {tab.icon}
                  {/* Active indicator with glow trail */}
                  {isActive && (
                    <motion.div
                      layoutId="sidebar-indicator"
                      className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-4 rounded-full"
                      style={{
                        backgroundColor: '#b794f4',
                        boxShadow: '0 0 6px rgba(183,148,244,0.5), 0 0 12px rgba(183,148,244,0.2)',
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

            {/* Tab content with fade+slide animation */}
            <div className="flex-1 overflow-hidden">
              <AnimatePresence mode="wait">
                <motion.div
                  key={sidebarTab}
                  initial={{ opacity: 0, x: 8 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -8 }}
                  transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
                  className="h-full"
                >
                  {tabContent()}
                </motion.div>
              </AnimatePresence>
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
