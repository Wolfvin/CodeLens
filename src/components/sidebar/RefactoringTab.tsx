'use client'

import React, { useState } from 'react'
import {
  Hammer,
  AlertTriangle,
  Shield,
  Loader2,
  CheckCircle2,
  XCircle,
  Zap,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { useAnalysisStore } from '@/lib/analysisStore'

interface RefactoringTabProps {
  theme: 'dark' | 'light'
}

export function RefactoringTab({ theme }: RefactoringTabProps) {
  const { refactoringResults, runCommand, workspace, runningCommands } = useAnalysisStore()
  const { refactorSafe, sideEffect } = refactoringResults

  const isRunning = (cmd: string) => runningCommands.includes(cmd)

  const [symbolInput, setSymbolInput] = useState('')

  const card = {
    backgroundColor: theme === 'dark' ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)',
    borderRadius: '8px',
    padding: '10px',
    transition: 'transform 0.2s ease-out, box-shadow 0.2s ease-out',
  }

  const inputStyle = {
    backgroundColor: theme === 'dark' ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.04)',
    color: theme === 'dark' ? '#e2e8f0' : '#1a202c',
    borderColor: theme === 'dark' ? '#2d3748' : '#e2e8f0',
  }

  const btnOutline: React.CSSProperties = {
    borderColor: theme === 'dark' ? '#2d3748' : '#e2e8f0',
    color: theme === 'dark' ? '#e2e8f0' : '#1a202c',
  }

  const runRefactorAudit = async () => {
    if (symbolInput.trim()) {
      await runCommand('refactor-safe', [workspace, '--name', symbolInput])
      await runCommand('side-effect', [workspace, '--name', symbolInput])
    }
  }

  return (
    <ScrollArea className="h-full">
      <div className="p-3 space-y-4">
        {/* Symbol Input */}
        <div className="space-y-2">
          <div className="text-[10px] font-bold uppercase tracking-widest opacity-50">Symbol Name</div>
          <Input
            type="text"
            placeholder="e.g. processPayment"
            value={symbolInput}
            onChange={e => setSymbolInput(e.target.value)}
            className="h-8 text-xs font-mono"
            style={inputStyle}
          />
        </div>

        {/* Full Refactor Audit */}
        <Button
          className="w-full h-9 text-xs gap-2 bg-orange-600 hover:bg-orange-700 text-white audit-btn"
          onClick={runRefactorAudit}
          disabled={isRunning('refactor-safe') || isRunning('side-effect') || !symbolInput.trim()}
        >
          {isRunning('refactor-safe') || isRunning('side-effect') ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Hammer className="h-3.5 w-3.5" />
          )}
          Refactor Audit
        </Button>

        {/* Quick Actions */}
        <div className="grid grid-cols-2 gap-1.5">
          <Button
            size="sm"
            variant="outline"
            className="h-7 text-[10px] gap-1"
            style={btnOutline}
            onClick={() => symbolInput.trim() && runCommand('refactor-safe', [workspace, '--name', symbolInput])}
            disabled={isRunning('refactor-safe') || !symbolInput.trim()}
          >
            <Shield className="h-3 w-3" /> Safe Check
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="h-7 text-[10px] gap-1"
            style={btnOutline}
            onClick={() => symbolInput.trim() && runCommand('side-effect', [workspace, '--name', symbolInput])}
            disabled={isRunning('side-effect') || !symbolInput.trim()}
          >
            <Zap className="h-3 w-3" /> Side FX
          </Button>
        </div>

        <Separator style={{ background: 'linear-gradient(90deg, transparent, rgba(139,92,246,0.15), transparent)', height: '1px' }} />

        {/* Refactor Safety Results */}
        {refactorSafe && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Shield className="h-3.5 w-3.5" style={{ color: refactorSafe.is_safe ? '#48bb78' : '#ed8936' }} />
              <span className="text-xs font-semibold">Safety Score</span>
              <Badge className="text-[10px] h-5 ml-auto" style={{
                backgroundColor: refactorSafe.safety_score >= 90 ? 'rgba(72,187,120,0.15)' : refactorSafe.safety_score >= 70 ? 'rgba(236,201,75,0.15)' : 'rgba(229,62,62,0.15)',
                color: refactorSafe.safety_score >= 90 ? '#48bb78' : refactorSafe.safety_score >= 70 ? '#ecc94b' : '#e53e3e',
              }}>
                {refactorSafe.safety_score}/100
              </Badge>
            </div>

            {/* Safety Score Visual */}
            <div className="flex items-center gap-3">
              <div
                className="relative w-16 h-16 flex items-center justify-center rounded-full shrink-0"
                style={{
                  border: `3px solid ${refactorSafe.safety_score >= 90 ? '#48bb78' : refactorSafe.safety_score >= 70 ? '#ecc94b' : '#e53e3e'}`,
                  backgroundColor: `${refactorSafe.safety_score >= 90 ? '#48bb78' : refactorSafe.safety_score >= 70 ? '#ecc94b' : '#e53e3e'}15`,
                }}
              >
                <span className="text-lg font-bold" style={{ color: refactorSafe.safety_score >= 90 ? '#48bb78' : refactorSafe.safety_score >= 70 ? '#ecc94b' : '#e53e3e' }}>
                  {refactorSafe.safety_score}
                </span>
              </div>
              <div className="flex-1 space-y-1">
                <div className="flex items-center gap-1.5 text-xs">
                  {refactorSafe.is_safe ? (
                    <CheckCircle2 className="h-3.5 w-3.5" style={{ color: '#48bb78' }} />
                  ) : (
                    <XCircle className="h-3.5 w-3.5" style={{ color: '#e53e3e' }} />
                  )}
                  <span className="font-medium">
                    {refactorSafe.is_safe ? 'Safe to refactor' : 'Not safe to refactor'}
                  </span>
                </div>
                <div className="text-[10px] opacity-50">
                  {refactorSafe.dependents_count} dependents
                </div>
              </div>
            </div>

            {/* Blockers */}
            {refactorSafe.blockers && refactorSafe.blockers.length > 0 && (
              <div className="space-y-1.5">
                <div className="text-[10px] font-bold uppercase tracking-widest opacity-40">Blockers</div>
                {refactorSafe.blockers.map((b, i) => (
                  <div key={i} style={card}>
                    <div className="flex items-center gap-1.5 text-xs">
                      <Badge className="text-[9px] h-4" style={{
                        backgroundColor: b.severity === 'high' ? 'rgba(229,62,62,0.2)' : 'rgba(236,201,75,0.2)',
                        color: b.severity === 'high' ? '#e53e3e' : '#ecc94b',
                      }}>
                        {b.type.replace(/_/g, ' ')}
                      </Badge>
                    </div>
                    <div className="text-[10px] opacity-60 mt-1">{b.description}</div>
                  </div>
                ))}
              </div>
            )}

            {/* Warnings */}
            {refactorSafe.warnings && refactorSafe.warnings.length > 0 && (
              <div className="space-y-1.5">
                <div className="text-[10px] font-bold uppercase tracking-widest opacity-40">Warnings</div>
                {refactorSafe.warnings.map((w, i) => (
                  <div key={i} className="flex items-start gap-1.5 text-xs">
                    <AlertTriangle className="h-3 w-3 shrink-0 mt-0.5" style={{ color: '#ecc94b' }} />
                    <span className="opacity-70">{w.description}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Side Effect Results */}
        {sideEffect && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Zap className="h-3.5 w-3.5" style={{ color: sideEffect.is_pure ? '#48bb78' : '#ed8936' }} />
              <span className="text-xs font-semibold">Side Effects</span>
              <Badge className="text-[10px] h-5 ml-auto" style={{
                backgroundColor: sideEffect.purity >= 0.8 ? 'rgba(72,187,120,0.15)' : sideEffect.purity >= 0.5 ? 'rgba(236,201,75,0.15)' : 'rgba(229,62,62,0.15)',
                color: sideEffect.purity >= 0.8 ? '#48bb78' : sideEffect.purity >= 0.5 ? '#ecc94b' : '#e53e3e',
              }}>
                purity {Math.round(sideEffect.purity * 100)}%
              </Badge>
            </div>

            {/* Purity Bar */}
            <div className="space-y-1">
              <div className="h-2 rounded-full overflow-hidden" style={{ backgroundColor: theme === 'dark' ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)' }}>
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{
                    width: `${sideEffect.purity * 100}%`,
                    backgroundColor: sideEffect.purity >= 0.8 ? '#48bb78' : sideEffect.purity >= 0.5 ? '#ecc94b' : '#e53e3e',
                  }}
                />
              </div>
              <div className="flex justify-between text-[10px] opacity-50">
                <span>Impure</span>
                <span>{sideEffect.is_pure ? 'Pure function' : 'Impure function'}</span>
                <span>Pure</span>
              </div>
            </div>

            {/* Side Effects List */}
            {sideEffect.side_effects && sideEffect.side_effects.length > 0 && (
              <div className="space-y-1.5">
                <div className="text-[10px] font-bold uppercase tracking-widest opacity-40">Detected Effects</div>
                {sideEffect.side_effects.map((fx, i) => (
                  <div key={i} style={card}>
                    <div className="flex items-center gap-1.5 text-xs">
                      <Badge className="text-[9px] h-4" style={{
                        backgroundColor: fx.severity === 'high' ? 'rgba(229,62,62,0.2)' : fx.severity === 'medium' ? 'rgba(237,137,54,0.2)' : 'rgba(236,201,75,0.2)',
                        color: fx.severity === 'high' ? '#e53e3e' : fx.severity === 'medium' ? '#ed8936' : '#ecc94b',
                      }}>
                        {fx.type}
                      </Badge>
                    </div>
                    <div className="text-xs opacity-70 mt-1">{fx.description}</div>
                    <div className="text-[10px] font-mono opacity-40 mt-0.5">{fx.file}:{fx.line}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </ScrollArea>
  )
}
