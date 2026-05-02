'use client'

import React, { useEffect, useRef } from 'react'
import {
  Copy,
  Eye,
} from 'lucide-react'
import type { GraphNode, QuickAction } from '@/types/neural'

interface NodeContextMenuProps {
  x: number
  y: number
  node: GraphNode
  actions: QuickAction[]
  onAction: (action: QuickAction) => void
  onClose: () => void
  theme: 'dark' | 'light'
}

export function NodeContextMenu({
  x,
  y,
  node,
  actions,
  onAction,
  onClose,
  theme,
}: NodeContextMenuProps) {
  const ref = useRef<HTMLDivElement>(null)
  const dark = theme === 'dark'

  // Close on click outside
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose()
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [onClose])

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  // Adjust position to stay within viewport
  const menuWidth = 220
  const menuHeight = Math.min(actions.length * 36 + 80, 400)
  const adjustedX = x + menuWidth > window.innerWidth ? x - menuWidth : x
  const adjustedY = y + menuHeight > window.innerHeight ? y - menuHeight : y

  const variantStyles = {
    default: dark ? 'text-slate-300' : 'text-slate-700',
    warning: 'text-amber-400',
    danger: 'text-red-400',
  }

  return (
    <div
      ref={ref}
      className="fixed z-[100] rounded-xl border overflow-hidden py-1.5"
      style={{
        left: adjustedX,
        top: adjustedY,
        minWidth: menuWidth,
        backgroundColor: dark ? 'rgba(15, 15, 30, 0.95)' : 'rgba(255, 255, 255, 0.97)',
        borderColor: dark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)',
        backdropFilter: 'blur(20px)',
        boxShadow: dark
          ? '0 8px 32px rgba(0,0,0,0.5), 0 0 0 1px rgba(183,148,244,0.05)'
          : '0 8px 32px rgba(0,0,0,0.12), 0 0 0 1px rgba(0,0,0,0.04)',
      }}
    >
      {/* Node header */}
      <div
        className="px-3 py-2 flex items-center gap-2 border-b"
        style={{ borderColor: dark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)' }}
      >
        <div
          className="w-5 h-5 rounded-md flex items-center justify-center text-[10px]"
          style={{ backgroundColor: `${node.color}15`, color: node.color }}
        >
          {node.label.charAt(0).toUpperCase()}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-xs font-medium truncate" style={{ color: dark ? '#e2e8f0' : '#1a202c' }}>
            {node.label}
          </div>
          <div className="text-[10px]" style={{ color: dark ? '#718096' : '#94a3b8' }}>
            {node.type} · {node.status}
          </div>
        </div>
      </div>

      {/* Quick Actions */}
      <div className="py-1">
        {actions.map((action, i) => (
          <button
            key={`${action.command}-${i}`}
            className="w-full flex items-center gap-2.5 px-3 py-1.5 text-xs text-left transition-colors duration-100"
            style={{ color: dark ? '#cbd5e0' : '#4a5568' }}
            onMouseEnter={(e) => {
              const el = e.currentTarget as HTMLElement
              el.style.backgroundColor = dark ? 'rgba(183,148,244,0.08)' : 'rgba(139,92,246,0.05)'
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLElement).style.backgroundColor = ''
            }}
            onClick={() => {
              onAction(action)
              onClose()
            }}
          >
            <span className="w-4 text-center text-[11px]">{action.icon}</span>
            <span className={`flex-1 ${variantStyles[action.variant]}`}>{action.label}</span>
            <span className="text-[10px] font-mono opacity-30">{action.command}</span>
          </button>
        ))}
      </div>

      {/* Divider + utility actions */}
      {actions.length > 0 && (
        <div
          className="my-1 mx-2 h-px"
          style={{ backgroundColor: dark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)' }}
        />
      )}
      
      <button
        className="w-full flex items-center gap-2.5 px-3 py-1.5 text-xs text-left"
        style={{ color: dark ? '#718096' : '#94a3b8' }}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLElement).style.backgroundColor = dark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)'
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLElement).style.backgroundColor = ''
        }}
        onClick={() => {
          navigator.clipboard.writeText(node.id)
          onClose()
        }}
      >
        <Copy className="h-3.5 w-3.5" />
        <span>Copy Node ID</span>
      </button>

      <button
        className="w-full flex items-center gap-2.5 px-3 py-1.5 text-xs text-left"
        style={{ color: dark ? '#718096' : '#94a3b8' }}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLElement).style.backgroundColor = dark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)'
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLElement).style.backgroundColor = ''
        }}
        onClick={onClose}
      >
        <Eye className="h-3.5 w-3.5" />
        <span>Focus on Node</span>
      </button>
    </div>
  )
}
