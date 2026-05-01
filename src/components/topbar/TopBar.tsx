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
}: TopBarProps) {
  const dark = theme === 'dark'
  const [query, setQuery] = useState('')
  const [showDropdown, setShowDropdown] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

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

  const variantStyles = useMemo(() => {
    const bg = dark ? 'rgba(13,13,20,0.9)' : 'rgba(255,255,255,0.9)'
    const text = dark ? '#e2e8f0' : '#1a202c'
    const border = dark ? '#1a202c' : '#e2e8f0'
    const mutedText = dark ? '#a0aec0' : '#718096'
    const inputBg = dark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.04)'
    return { bg, text, border, mutedText, inputBg }
  }, [dark])

  return (
    <header
      className="fixed top-0 left-0 right-0 z-40 h-14 flex items-center gap-3 px-4 border-b"
      style={{
        backgroundColor: variantStyles.bg,
        borderColor: variantStyles.border,
        color: variantStyles.text,
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
      }}
    >
      {/* Left: Logo + Stats */}
      <div className="flex items-center gap-2 shrink-0">
        <Brain className="h-5 w-5" style={{ color: '#b794f4' }} />
        <span className="font-bold text-sm tracking-tight hidden sm:inline">
          CodeLens Neural
        </span>
        <Badge
          variant="outline"
          className="text-[10px] h-5 ml-1 hidden md:flex"
          style={{
            borderColor: variantStyles.border,
            color: variantStyles.mutedText,
          }}
        >
          {stats.totalNodes} nodes · {stats.totalEdges} edges
        </Badge>
      </div>

      {/* Center: Search */}
      <div className="flex-1 max-w-md mx-auto relative" ref={containerRef}>
        <div className="relative">
          <Search
            className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5"
            style={{ color: variantStyles.mutedText }}
          />
          <Input
            ref={inputRef}
            type="text"
            placeholder="Search nodes..."
            value={query}
            onChange={e => handleInputChange(e.target.value)}
            onFocus={() => {
              if (query.length > 0 || searchResults.length > 0) setShowDropdown(true)
            }}
            className="h-8 pl-8 pr-3 text-xs rounded-md border-0 focus-visible:ring-1 focus-visible:ring-purple-400/60"
            style={{
              backgroundColor: variantStyles.inputBg,
              color: variantStyles.text,
            }}
          />
        </div>

        {/* Search results dropdown */}
        {showDropdown && searchResults.length > 0 && (
          <div
            className="absolute top-full mt-1 left-0 right-0 rounded-md border shadow-lg overflow-hidden z-50"
            style={{
              backgroundColor: dark ? '#1a1a2e' : '#ffffff',
              borderColor: variantStyles.border,
            }}
          >
            <div className="max-h-72 overflow-y-auto">
              {searchResults.map(node => (
                <button
                  key={node.id}
                  className="w-full flex items-center gap-2 px-3 py-2 text-xs text-left transition-colors hover:bg-white/5 dark:hover:bg-white/5"
                  style={{ color: variantStyles.text }}
                  onMouseEnter={e => {
                    ;(e.currentTarget as HTMLElement).style.backgroundColor = dark
                      ? 'rgba(255,255,255,0.06)'
                      : 'rgba(0,0,0,0.04)'
                  }}
                  onMouseLeave={e => {
                    ;(e.currentTarget as HTMLElement).style.backgroundColor = ''
                  }}
                  onClick={() => handleSelectResult(node.id)}
                >
                  <span style={{ color: node.color }}>{TYPE_ICON_MAP[node.type]}</span>
                  <span className="font-medium truncate">{node.label}</span>
                  {node.file && (
                    <span
                      className="ml-auto font-mono text-[10px] truncate max-w-[140px]"
                      style={{ color: variantStyles.mutedText }}
                    >
                      {node.file}
                    </span>
                  )}
                  <ChevronRight className="h-3 w-3 shrink-0 opacity-30" />
                </button>
              ))}
            </div>
          </div>
        )}

        {/* No results */}
        {showDropdown && query.length > 0 && searchResults.length === 0 && (
          <div
            className="absolute top-full mt-1 left-0 right-0 rounded-md border shadow-lg p-4 text-xs text-center"
            style={{
              backgroundColor: dark ? '#1a1a2e' : '#ffffff',
              borderColor: variantStyles.border,
              color: variantStyles.mutedText,
            }}
          >
            No matching nodes found
          </div>
        )}
      </div>

      {/* Right: Actions */}
      <div className="flex items-center gap-1 shrink-0">
        {/* Theme toggle */}
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={onThemeToggle}
          title={dark ? 'Switch to light mode' : 'Switch to dark mode'}
        >
          {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </Button>

        {/* Export dropdown */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" className="h-8 w-8" title="Export graph">
              <Camera className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-40">
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

        {/* Rescan */}
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={onRescan}
          disabled={isScanning}
          title="Rescan codebase"
        >
          <RefreshCw
            className={`h-4 w-4 ${isScanning ? 'animate-spin' : ''}`}
          />
        </Button>
      </div>
    </header>
  )
}
