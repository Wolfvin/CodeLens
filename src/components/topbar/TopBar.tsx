'use client'

import { useState, useRef, useEffect, useMemo, useCallback } from 'react'
import {
  Moon,
  Sun,
  Search,
  Camera,
  RefreshCw,
  ChevronRight,
  Download,
  Brain,
  PanelLeft,
  Command,
  Activity,
  Sparkles,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import type { GraphNode, NodeType } from '@/types/neural'
import { NEURAL_COLORS } from '@/types/neural'
import { useAnalysisStore } from '@/lib/analysisStore'

// ─── Props ───────────────────────────────────────────────────
interface TopBarProps {
  theme: 'dark' | 'light'
  onThemeToggle: () => void
  onSearch: (query: string) => void
  searchResults: GraphNode[]
  onSearchResultSelect: (nodeId: string) => void
  onExport: (format: 'png2x' | 'png4x' | 'svg' | 'current') => void
  onRescan: () => void
  stats: { totalNodes: number; totalEdges: number }
  isScanning: boolean
  healthScore?: number
}

// ─── Helpers ─────────────────────────────────────────────────

const TYPE_ICON_MAP: Record<NodeType, string> = {
  class: '◆',
  id: '●',
  function: '⬡',
  component: '▲',
  store: '★',
  file: '■',
  package: '◎',
  route: '⬡',
  env_var: '◆',
  variable: '●',
  secret: '◆',
  vulnerability: '⬡',
  test: '●',
  import: '■',
  css_var: '◆',
  keyframe: '▲',
}

// ─── Health Score Ring ───────────────────────────────────────
function HealthRing({ score, size = 28 }: { score: number; size?: number }) {
  const radius = (size - 4) / 2
  const circumference = 2 * Math.PI * radius
  const progress = (score / 100) * circumference
  const color = score >= 80 ? '#10b981' : score >= 60 ? '#f59e0b' : score >= 40 ? '#f97316' : '#ef4444'

  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        {/* Background ring */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          className="opacity-10"
        />
        {/* Progress ring */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={2}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference - progress}
          style={{
            transition: 'stroke-dashoffset 1s cubic-bezier(0.16, 1, 0.3, 1), stroke 0.5s ease',
            filter: `drop-shadow(0 0 3px ${color}40)`,
          }}
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">
        <span
          className="text-[8px] font-bold font-mono"
          style={{ color, textShadow: `0 0 6px ${color}40` }}
        >
          {score}
        </span>
      </div>
    </div>
  )
}

// ─── Component ───────────────────────────────────────────────

export function TopBar({
  theme,
  onThemeToggle,
  onSearch,
  searchResults,
  onSearchResultSelect,
  onExport,
  onRescan,
  stats,
  isScanning,
  healthScore,
}: TopBarProps) {
  const dark = theme === 'dark'
  const [query, setQuery] = useState('')
  const [showDropdown, setShowDropdown] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const { toggleSidebar, toggleCommandPalette, sidebarOpen, bottomPanelOpen, toggleBottomPanel, qualityResults } = useAnalysisStore()

  // Close dropdown on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setShowDropdown(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const handleInputChange = useCallback(
    (value: string) => {
      setQuery(value)
      setShowDropdown(value.length > 0)
      onSearch(value)
    },
    [onSearch],
  )

  const handleSelectResult = useCallback(
    (nodeId: string) => {
      onSearchResultSelect(nodeId)
      setShowDropdown(false)
      setQuery('')
    },
    [onSearchResultSelect],
  )

  const computedHealthScore = healthScore ?? qualityResults.smells?.stats?.health_score ?? 100

  const styles = useMemo(() => ({
    bg: dark ? 'rgba(8, 8, 16, 0.75)' : 'rgba(255, 255, 255, 0.8)',
    text: dark ? '#e2e8f0' : '#1a202c',
    border: dark ? 'rgba(255, 255, 255, 0.06)' : 'rgba(0, 0, 0, 0.06)',
    mutedText: dark ? '#718096' : '#94a3b8',
    inputBg: dark ? 'rgba(255, 255, 255, 0.04)' : 'rgba(0, 0, 0, 0.03)',
    hoverBg: dark ? 'rgba(255, 255, 255, 0.04)' : 'rgba(0, 0, 0, 0.04)',
  }), [dark])

  return (
    <header
      className="fixed top-0 left-0 right-0 z-40 h-14 flex items-center gap-2 px-3"
      style={{
        backgroundColor: styles.bg,
        borderBottom: `1px solid ${styles.border}`,
        color: styles.text,
        backdropFilter: 'blur(20px) saturate(1.3)',
        WebkitBackdropFilter: 'blur(20px) saturate(1.3)',
        boxShadow: dark
          ? '0 1px 24px rgba(0, 0, 0, 0.4), 0 0 0 1px rgba(139, 92, 246, 0.03)'
          : '0 1px 16px rgba(0, 0, 0, 0.06), 0 0 0 1px rgba(0, 0, 0, 0.04)',
      }}
    >
      {/* Left: Sidebar toggle + Logo */}
      <div className="flex items-center gap-2.5 shrink-0">
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 smooth-colors hover:bg-white/5"
          onClick={toggleSidebar}
          title={sidebarOpen ? 'Close sidebar' : 'Open sidebar'}
        >
          <PanelLeft className="h-4 w-4" style={{ color: styles.mutedText }} />
        </Button>

        {/* Logo with glow */}
        <div className="flex items-center gap-2">
          <div className="relative">
            <Brain className="h-5 w-5" style={{ color: '#b794f4', filter: 'drop-shadow(0 0 6px rgba(183, 148, 244, 0.4))' }} />
          </div>
          <span
            className="font-bold text-sm tracking-tight hidden sm:inline"
            style={{
              background: dark ? 'linear-gradient(135deg, #e2e8f0, #b794f4)' : 'linear-gradient(135deg, #1a202c, #7c3aed)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
            }}
          >
            CodeLens Neural
          </span>
        </div>

        {/* Health Score Ring */}
        <div className="hidden md:flex items-center ml-1">
          <HealthRing score={computedHealthScore} />
        </div>

        <Badge
          variant="outline"
          className="text-[10px] h-5 ml-1 hidden lg:flex border-0"
          style={{
            backgroundColor: styles.inputBg,
            color: styles.mutedText,
          }}
        >
          <Sparkles className="h-2.5 w-2.5 mr-1 opacity-50" />
          {stats.totalNodes} nodes · {stats.totalEdges} edges
        </Badge>
      </div>

      {/* Center: Search */}
      <div className="flex-1 max-w-md mx-auto relative" ref={containerRef}>
        <div className="relative group">
          <Search
            className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 transition-colors duration-200"
            style={{ color: styles.mutedText }}
          />
          <Input
            ref={inputRef}
            type="text"
            placeholder="Search nodes... (⌘K for commands)"
            value={query}
            onChange={e => handleInputChange(e.target.value)}
            onFocus={() => {
              if (query.length > 0 || searchResults.length > 0) setShowDropdown(true)
            }}
            className="h-8 pl-8 pr-3 text-xs rounded-lg border-0 focus-visible:ring-1 focus-visible:ring-purple-500/40 transition-all duration-200"
            style={{
              backgroundColor: styles.inputBg,
              color: styles.text,
            }}
          />
          {/* Subtle glow on focus */}
          <div
            className="absolute inset-0 rounded-lg pointer-events-none opacity-0 group-focus-within:opacity-100 transition-opacity duration-300"
            style={{
              boxShadow: '0 0 0 1px rgba(139, 92, 246, 0.15), 0 0 12px -4px rgba(139, 92, 246, 0.2)',
            }}
          />
        </div>

        {/* Search results dropdown */}
        {showDropdown && searchResults.length > 0 && (
          <div
            className="absolute top-full mt-1.5 left-0 right-0 rounded-xl border overflow-hidden z-50 search-dropdown"
            style={{
              backgroundColor: dark ? 'rgba(15, 15, 30, 0.95)' : 'rgba(255, 255, 255, 0.97)',
              borderColor: styles.border,
              backdropFilter: 'blur(20px)',
            }}
          >
            <div className="max-h-72 overflow-y-auto panel-scroll p-1">
              {searchResults.map((node, i) => (
                <button
                  key={node.id}
                  className="w-full flex items-center gap-2.5 px-3 py-2 text-xs text-left rounded-lg transition-all duration-150"
                  style={{ color: styles.text }}
                  onMouseEnter={e => {
                    const el = e.currentTarget as HTMLElement
                    el.style.backgroundColor = dark ? 'rgba(139, 92, 246, 0.08)' : 'rgba(139, 92, 246, 0.05)'
                  }}
                  onMouseLeave={e => {
                    (e.currentTarget as HTMLElement).style.backgroundColor = ''
                  }}
                  onClick={() => handleSelectResult(node.id)}
                >
                  <span style={{ color: node.color, filter: `drop-shadow(0 0 3px ${node.color}30)` }}>{TYPE_ICON_MAP[node.type] ?? '●'}</span>
                  <span className="font-medium truncate">{node.label}</span>
                  {node.file && (
                    <span
                      className="ml-auto font-mono text-[10px] truncate max-w-[140px]"
                      style={{ color: styles.mutedText }}
                    >
                      {node.file}
                    </span>
                  )}
                  <ChevronRight className="h-3 w-3 shrink-0 opacity-20" />
                </button>
              ))}
            </div>
          </div>
        )}

        {/* No results */}
        {showDropdown && query.length > 0 && searchResults.length === 0 && (
          <div
            className="absolute top-full mt-1.5 left-0 right-0 rounded-xl border shadow-lg p-4 text-xs text-center"
            style={{
              backgroundColor: dark ? 'rgba(15, 15, 30, 0.95)' : 'rgba(255, 255, 255, 0.97)',
              borderColor: styles.border,
              color: styles.mutedText,
              backdropFilter: 'blur(20px)',
            }}
          >
            No matching nodes found
          </div>
        )}
      </div>

      {/* Right: Actions */}
      <div className="flex items-center gap-0.5 shrink-0">
        {/* Command Palette Trigger */}
        <Button
          variant="ghost"
          size="sm"
          className="h-8 gap-1.5 text-xs hidden sm:flex smooth-colors hover:bg-white/5"
          onClick={toggleCommandPalette}
          title="Command Palette (⌘K)"
          style={{ color: styles.mutedText }}
        >
          <Command className="h-3.5 w-3.5" />
          <kbd
            className="text-[9px] px-1.5 py-0.5 rounded-md border font-mono"
            style={{
              borderColor: styles.border,
              backgroundColor: styles.inputBg,
            }}
          >
            ⌘K
          </kbd>
        </Button>

        {/* Theme toggle with smooth icon swap */}
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 smooth-colors hover:bg-white/5"
          onClick={onThemeToggle}
          title={dark ? 'Switch to light mode' : 'Switch to dark mode'}
        >
          <div className="transition-transform duration-300" style={{ transform: 'rotate(0deg)' }}>
            {dark ? <Sun className="h-4 w-4" style={{ color: '#f59e0b', filter: 'drop-shadow(0 0 4px rgba(245, 158, 11, 0.4))' }} /> : <Moon className="h-4 w-4" style={{ color: styles.mutedText }} />}
          </div>
        </Button>

        {/* Export dropdown */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" className="h-8 w-8 smooth-colors hover:bg-white/5" title="Export graph">
              <Camera className="h-4 w-4" style={{ color: styles.mutedText }} />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            align="end"
            className="w-44"
            style={{
              backgroundColor: dark ? 'rgba(15, 15, 30, 0.95)' : 'rgba(255, 255, 255, 0.97)',
              borderColor: styles.border,
              backdropFilter: 'blur(20px)',
            }}
          >
            <DropdownMenuItem onClick={() => onExport('png2x')}>
              <Download className="h-3.5 w-3.5 mr-2" />
              PNG 2x
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => onExport('png4x')}>
              <Download className="h-3.5 w-3.5 mr-2" />
              PNG 4x
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => onExport('svg')}>
              <Download className="h-3.5 w-3.5 mr-2" />
              SVG
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => onExport('current')}>
              <Camera className="h-3.5 w-3.5 mr-2" />
              Current View
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        {/* Rescan with premium spinner */}
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 smooth-colors hover:bg-white/5"
          onClick={onRescan}
          disabled={isScanning}
          title="Rescan codebase"
        >
          <RefreshCw
            className={`h-4 w-4 transition-transform duration-500 ${isScanning ? 'animate-spin' : ''}`}
            style={{ color: isScanning ? '#b794f4' : styles.mutedText }}
          />
        </Button>

        {/* Bottom panel toggle */}
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 smooth-colors hover:bg-white/5"
          onClick={toggleBottomPanel}
          title={bottomPanelOpen ? 'Close results panel' : 'Open results panel'}
        >
          <Activity className="h-4 w-4" style={{ color: bottomPanelOpen ? '#b794f4' : styles.mutedText }} />
        </Button>
      </div>
    </header>
  )
}
