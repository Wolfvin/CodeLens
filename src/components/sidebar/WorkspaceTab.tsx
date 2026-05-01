'use client'

import React from 'react'
import { FolderOpen, RefreshCw, Loader2, Zap, Shield, CheckCircle2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { useAnalysisStore } from '@/lib/analysisStore'

interface WorkspaceTabProps {
  theme: 'dark' | 'light'
}

export function WorkspaceTab({ theme }: WorkspaceTabProps) {
  const {
    workspace, isScanning, lastScanTime, frameworks, registryStats,
    runCommand, setIsScanning,
  } = useAnalysisStore()

  const handleScan = async (incremental: boolean = false) => {
    setIsScanning(true)
    try {
      await runCommand('scan', incremental ? ['--incremental', workspace] : [workspace])
    } finally {
      setIsScanning(false)
    }
  }

  const stats = registryStats ?? { byType: {}, byStatus: {} }

  return (
    <ScrollArea className="h-full">
      <div className="p-3 space-y-4">
        {/* Workspace Path */}
        <div className="space-y-1.5">
          <div className="text-[10px] font-bold uppercase tracking-widest opacity-50">Workspace</div>
          <div
            className="flex items-center gap-2 px-3 py-2 rounded-md text-xs font-mono"
            style={{
              backgroundColor: theme === 'dark' ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.04)',
              color: theme === 'dark' ? '#a0aec0' : '#718096',
            }}
          >
            <FolderOpen className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">{workspace}</span>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="space-y-2">
          <div className="text-[10px] font-bold uppercase tracking-widest opacity-50">Actions</div>
          <div className="grid grid-cols-2 gap-1.5">
            <Button
              size="sm"
              variant="outline"
              className="h-8 text-xs gap-1.5"
              style={{ borderColor: theme === 'dark' ? '#2d3748' : '#e2e8f0', color: theme === 'dark' ? '#e2e8f0' : '#1a202c' }}
              onClick={() => runCommand('init', [workspace])}
            >
              <Zap className="h-3 w-3" />
              Init
            </Button>
            <Button
              size="sm"
              className="h-8 text-xs gap-1.5 bg-purple-600 hover:bg-purple-700 text-white"
              onClick={() => handleScan(false)}
              disabled={isScanning}
            >
              {isScanning ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
              Full Scan
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="h-8 text-xs gap-1.5"
              style={{ borderColor: theme === 'dark' ? '#2d3748' : '#e2e8f0', color: theme === 'dark' ? '#e2e8f0' : '#1a202c' }}
              onClick={() => handleScan(true)}
              disabled={isScanning}
            >
              <RefreshCw className="h-3 w-3" />
              Incr. Scan
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="h-8 text-xs gap-1.5"
              style={{ borderColor: theme === 'dark' ? '#2d3748' : '#e2e8f0', color: theme === 'dark' ? '#e2e8f0' : '#1a202c' }}
              onClick={() => runCommand('detect', [workspace])}
            >
              <Shield className="h-3 w-3" />
              Detect FW
            </Button>
          </div>
          <Button
            size="sm"
            variant="outline"
            className="w-full h-8 text-xs gap-1.5"
            style={{ borderColor: theme === 'dark' ? '#2d3748' : '#e2e8f0', color: theme === 'dark' ? '#e2e8f0' : '#1a202c' }}
            onClick={() => runCommand('validate', [workspace])}
          >
            <CheckCircle2 className="h-3 w-3" />
            Validate Registry
          </Button>
        </div>

        {/* Scan Progress */}
        {isScanning && (
          <div className="space-y-1.5">
            <div className="text-[10px] font-bold uppercase tracking-widest opacity-50">Scanning...</div>
            <div className="h-1.5 rounded-full overflow-hidden" style={{ backgroundColor: theme === 'dark' ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)' }}>
              <div className="h-full rounded-full bg-purple-500 animate-pulse" style={{ width: '60%' }} />
            </div>
          </div>
        )}

        {/* Last Scan */}
        {lastScanTime && (
          <div className="text-[10px] opacity-50">
            Last scan: {new Date(lastScanTime).toLocaleTimeString()}
          </div>
        )}

        <Separator style={{ backgroundColor: theme === 'dark' ? '#2d3748' : '#e2e8f0' }} />

        {/* Frameworks */}
        {frameworks.length > 0 && (
          <div className="space-y-1.5">
            <div className="text-[10px] font-bold uppercase tracking-widest opacity-50">Frameworks</div>
            <div className="flex flex-wrap gap-1">
              {frameworks.map(fw => (
                <Badge key={fw} variant="secondary" className="text-[10px] h-5">
                  {fw}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {/* Registry Stats */}
        <div className="space-y-1.5">
          <div className="text-[10px] font-bold uppercase tracking-widest opacity-50">Registry Stats</div>
          <div className="space-y-1">
            {Object.entries(stats.byType).map(([type, count]) => (
              <div key={type} className="flex items-center justify-between text-xs">
                <span style={{ color: theme === 'dark' ? '#a0aec0' : '#718096' }}>{type}</span>
                <span className="font-mono" style={{ color: theme === 'dark' ? '#e2e8f0' : '#1a202c' }}>{count as number}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </ScrollArea>
  )
}
