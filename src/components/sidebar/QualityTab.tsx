'use client'

import React from 'react'
import { CheckCircle2, AlertTriangle, Brain, Bug, Skull, Eye, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { Progress } from '@/components/ui/progress'
import { useAnalysisStore } from '@/lib/analysisStore'

interface QualityTabProps {
  theme: 'dark' | 'light'
}

export function QualityTab({ theme }: QualityTabProps) {
  const { qualityResults, runCommand, workspace, runningCommands } = useAnalysisStore()
  const { smells, complexity, debugLeaks, deadCode, a11y } = qualityResults

  const isRunning = (cmd: string) => runningCommands.includes(cmd)

  const runQualityGate = async () => {
    await runCommand('smell', [workspace])
    await runCommand('complexity', [workspace])
    await runCommand('debug-leak', [workspace])
    await runCommand('dead-code', [workspace])
    await runCommand('a11y', [workspace])
  }

  const healthScore = smells?.stats?.health_score ?? 100
  const healthColor = healthScore >= 80 ? '#48bb78' : healthScore >= 60 ? '#ecc94b' : healthScore >= 40 ? '#ed8936' : '#e53e3e'

  const totalSmells = smells?.stats?.total_smells ?? 0
  const deadCodeCount = deadCode?.stats?.total_dead_code ?? 0
  const debugLeakCount = debugLeaks?.findings?.length ?? 0
  const a11yCount = a11y?.issues?.length ?? 0

  const complexityStats = complexity?.stats ?? { simple: 0, moderate: 0, complex: 0, untamable: 0 }
  const totalComplex = complexityStats.simple + complexityStats.moderate + complexityStats.complex + complexityStats.untamable

  const card = {
    backgroundColor: theme === 'dark' ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)',
    borderRadius: '8px',
    padding: '10px',
    transition: 'transform 0.2s ease-out, box-shadow 0.2s ease-out',
  }

  return (
    <ScrollArea className="h-full">
      <div className="p-3 space-y-4">
        {/* Quality Gate */}
        <Button
          className="w-full h-9 text-xs gap-2 bg-emerald-600 hover:bg-emerald-700 text-white audit-btn"
          onClick={runQualityGate}
          disabled={isRunning('smell') || isRunning('complexity')}
        >
          {isRunning('smell') || isRunning('complexity') ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <CheckCircle2 className="h-3.5 w-3.5" />
          )}
          Quality Gate
        </Button>

        {/* Quick Actions */}
        <div className="grid grid-cols-2 gap-1.5">
          {[
            { cmd: 'smell', icon: <Brain className="h-3 w-3" />, label: 'Smells' },
            { cmd: 'complexity', icon: <AlertTriangle className="h-3 w-3" />, label: 'Complex' },
            { cmd: 'debug-leak', icon: <Bug className="h-3 w-3" />, label: 'Debug' },
            { cmd: 'dead-code', icon: <Skull className="h-3 w-3" />, label: 'Dead' },
            { cmd: 'a11y', icon: <Eye className="h-3 w-3" />, label: 'A11y' },
          ].map(({ cmd, icon, label }) => (
            <Button key={cmd} size="sm" variant="outline" className="h-7 text-[10px] gap-1" style={{ borderColor: theme === 'dark' ? '#2d3748' : '#e2e8f0', color: theme === 'dark' ? '#e2e8f0' : '#1a202c' }} onClick={() => runCommand(cmd, [workspace])} disabled={isRunning(cmd)}>
              {icon} {label}
            </Button>
          ))}
        </div>

        <Separator style={{ background: 'linear-gradient(90deg, transparent, rgba(139,92,246,0.15), transparent)', height: '1px' }} />

        {/* Health Score */}
        <div className="space-y-2">
          <div className="text-[10px] font-bold uppercase tracking-widest opacity-50">Health Score</div>
          <div className="flex items-center gap-3">
            <div
              className="relative w-16 h-16 flex items-center justify-center rounded-full"
              style={{ border: `3px solid ${healthColor}`, backgroundColor: `${healthColor}15` }}
            >
              <span className="text-lg font-bold" style={{ color: healthColor }}>{healthScore}</span>
            </div>
            <div className="flex-1 space-y-1">
              <Progress value={healthScore} className="h-2" style={{ '--tw-progress-color': healthColor } as React.CSSProperties} />
              <div className="text-[10px] opacity-50">
                {healthScore >= 80 ? 'Excellent' : healthScore >= 60 ? 'Good' : healthScore >= 40 ? 'Needs Attention' : 'Critical'}
              </div>
            </div>
          </div>
        </div>

        {/* Code Smells */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold">Code Smells</span>
            <Badge className="text-[10px] h-5" style={{ backgroundColor: totalSmells > 5 ? 'rgba(237,137,54,0.15)' : 'rgba(72,187,120,0.15)', color: totalSmells > 5 ? '#ed8936' : '#48bb78' }}>
              {totalSmells}
            </Badge>
          </div>
          {smells?.by_category && Object.entries(smells.by_category).map(([cat, items]) => (
            <div key={cat} style={card}>
              <div className="text-xs font-medium capitalize">{cat.replace(/_/g, ' ')}</div>
              <div className="text-[10px] opacity-50">{(items as unknown[]).length} finding(s)</div>
            </div>
          ))}
        </div>

        {/* Complexity Distribution */}
        <div className="space-y-2">
          <div className="text-xs font-semibold">Complexity Distribution</div>
          {totalComplex > 0 && (
            <div className="space-y-1">
              {[
                { label: 'Simple', count: complexityStats.simple, color: '#48bb78' },
                { label: 'Moderate', count: complexityStats.moderate, color: '#ecc94b' },
                { label: 'Complex', count: complexityStats.complex, color: '#ed8936' },
                { label: 'Untamable', count: complexityStats.untamable, color: '#e53e3e' },
              ].map(({ label, count, color }) => (
                <div key={label} className="flex items-center gap-2 text-xs">
                  <span className="w-16 opacity-70">{label}</span>
                  <div className="flex-1 h-2 rounded-full overflow-hidden" style={{ backgroundColor: theme === 'dark' ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)' }}>
                    <div className="h-full rounded-full" style={{ width: `${totalComplex > 0 ? (count / totalComplex) * 100 : 0}%`, backgroundColor: color }} />
                  </div>
                  <span className="font-mono w-6 text-right" style={{ color }}>{count}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Dead Code & Debug Leaks */}
        <div className="grid grid-cols-2 gap-2">
          <div style={card}>
            <div className="text-[10px] font-bold uppercase tracking-widest opacity-50">Dead Code</div>
            <div className="text-xl font-bold mt-1" style={{ color: deadCodeCount > 5 ? '#ed8936' : '#48bb78' }}>{deadCodeCount}</div>
          </div>
          <div style={card}>
            <div className="text-[10px] font-bold uppercase tracking-widest opacity-50">Debug Leaks</div>
            <div className="text-xl font-bold mt-1" style={{ color: debugLeakCount > 0 ? '#ecc94b' : '#48bb78' }}>{debugLeakCount}</div>
          </div>
        </div>

        {/* A11y */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold">A11y Issues</span>
            <Badge className="text-[10px] h-5" style={{ backgroundColor: a11yCount > 0 ? 'rgba(237,137,54,0.15)' : 'rgba(72,187,120,0.15)', color: a11yCount > 0 ? '#ed8936' : '#48bb78' }}>
              {a11yCount}
            </Badge>
          </div>
          {a11y?.issues?.map((issue, i) => (
            <div key={i} style={card}>
              <div className="flex items-center gap-1.5 text-xs">
                <Badge className="text-[9px] h-4" style={{
                  backgroundColor: issue.severity === 'error' ? 'rgba(229,62,62,0.2)' : 'rgba(236,201,75,0.2)',
                  color: issue.severity === 'error' ? '#e53e3e' : '#ecc94b',
                }}>
                  {issue.severity}
                </Badge>
                <span>{issue.category.replace(/_/g, ' ')}</span>
              </div>
              <div className="text-[10px] opacity-50 mt-0.5">{issue.message}</div>
            </div>
          ))}
        </div>
      </div>
    </ScrollArea>
  )
}
