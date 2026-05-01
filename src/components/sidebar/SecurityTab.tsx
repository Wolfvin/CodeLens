'use client'

import React from 'react'
import { Shield, AlertTriangle, Key, Bug, Globe, Droplets, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { useAnalysisStore } from '@/lib/analysisStore'

interface SecurityTabProps {
  theme: 'dark' | 'light'
}

export function SecurityTab({ theme }: SecurityTabProps) {
  const { securityResults, runCommand, workspace, runningCommands } = useAnalysisStore()
  const { secrets, vulnerabilities, dataflow, envCheck } = securityResults

  const isRunning = (cmd: string) => runningCommands.includes(cmd)

  const runFullAudit = () => {
    runChain([
      { command: 'secrets', args: [workspace] },
      { command: 'dataflow', args: [workspace] },
      { command: 'env-check', args: [workspace] },
      { command: 'vuln-scan', args: [workspace] },
    ])
  }

  const runChain = async (commands: Array<{ command: string; args: string[] }>) => {
    for (const { command, args } of commands) {
      await runCommand(command, args)
    }
  }

  const card = (bgColor: string) => ({
    backgroundColor: theme === 'dark' ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)',
    borderRadius: '8px',
    padding: '10px',
  })

  const secretCount = secrets?.findings?.length ?? 0
  const vulnCount = vulnerabilities?.vulnerabilities?.length ?? 0
  const flowCount = dataflow?.flows?.length ?? 0
  const missingEnv = envCheck?.missing?.length ?? 0

  return (
    <ScrollArea className="h-full">
      <div className="p-3 space-y-4">
        {/* Full Audit Button */}
        <Button
          className="w-full h-9 text-xs gap-2 bg-red-600 hover:bg-red-700 text-white"
          onClick={runFullAudit}
          disabled={isRunning('secrets') || isRunning('vuln-scan')}
        >
          {isRunning('secrets') || isRunning('vuln-scan') ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Shield className="h-3.5 w-3.5" />
          )}
          Full Security Audit
        </Button>

        {/* Quick Actions */}
        <div className="grid grid-cols-2 gap-1.5">
          <Button size="sm" variant="outline" className="h-7 text-[10px] gap-1" style={{ borderColor: theme === 'dark' ? '#2d3748' : '#e2e8f0', color: theme === 'dark' ? '#e2e8f0' : '#1a202c' }} onClick={() => runCommand('secrets', [workspace])} disabled={isRunning('secrets')}>
            <Key className="h-3 w-3" /> Secrets
          </Button>
          <Button size="sm" variant="outline" className="h-7 text-[10px] gap-1" style={{ borderColor: theme === 'dark' ? '#2d3748' : '#e2e8f0', color: theme === 'dark' ? '#e2e8f0' : '#1a202c' }} onClick={() => runCommand('vuln-scan', [workspace])} disabled={isRunning('vuln-scan')}>
            <Bug className="h-3 w-3" /> CVEs
          </Button>
          <Button size="sm" variant="outline" className="h-7 text-[10px] gap-1" style={{ borderColor: theme === 'dark' ? '#2d3748' : '#e2e8f0', color: theme === 'dark' ? '#e2e8f0' : '#1a202c' }} onClick={() => runCommand('dataflow', [workspace])} disabled={isRunning('dataflow')}>
            <Droplets className="h-3 w-3" /> Dataflow
          </Button>
          <Button size="sm" variant="outline" className="h-7 text-[10px] gap-1" style={{ borderColor: theme === 'dark' ? '#2d3748' : '#e2e8f0', color: theme === 'dark' ? '#e2e8f0' : '#1a202c' }} onClick={() => runCommand('env-check', [workspace])} disabled={isRunning('env-check')}>
            <Globe className="h-3 w-3" /> Env Check
          </Button>
        </div>

        <Separator style={{ backgroundColor: theme === 'dark' ? '#2d3748' : '#e2e8f0' }} />

        {/* Secrets */}
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <Key className="h-3.5 w-3.5" style={{ color: '#e53e3e' }} />
            <span className="text-xs font-semibold">Secrets Found</span>
            <Badge className="text-[10px] h-5 ml-auto" style={{ backgroundColor: secretCount > 0 ? 'rgba(229,62,62,0.15)' : 'rgba(72,187,120,0.15)', color: secretCount > 0 ? '#e53e3e' : '#48bb78' }}>
              {secretCount}
            </Badge>
          </div>
          {secrets?.findings?.map((f, i) => (
            <div key={i} style={card('')}>
              <div className="flex items-center gap-1.5 text-xs">
                <Badge className="text-[9px] h-4" style={{
                  backgroundColor: f.severity === 'critical' ? 'rgba(229,62,62,0.2)' : f.severity === 'high' ? 'rgba(237,137,54,0.2)' : 'rgba(236,201,75,0.2)',
                  color: f.severity === 'critical' ? '#e53e3e' : f.severity === 'high' ? '#ed8936' : '#ecc94b',
                }}>
                  {f.severity}
                </Badge>
                <span className="font-medium truncate">{f.env_key}</span>
              </div>
              <div className="text-[10px] opacity-50 mt-1 font-mono truncate">{f.file}:{f.line}</div>
            </div>
          ))}
        </div>

        {/* Vulnerabilities */}
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <Bug className="h-3.5 w-3.5" style={{ color: '#ed8936' }} />
            <span className="text-xs font-semibold">Vulnerabilities</span>
            <Badge className="text-[10px] h-5 ml-auto" style={{ backgroundColor: vulnCount > 0 ? 'rgba(237,137,54,0.15)' : 'rgba(72,187,120,0.15)', color: vulnCount > 0 ? '#ed8936' : '#48bb78' }}>
              {vulnCount}
            </Badge>
          </div>
          {vulnerabilities?.vulnerabilities?.map((v, i) => (
            <div key={i} style={card('')}>
              <div className="flex items-center gap-1.5 text-xs">
                <Badge className="text-[9px] h-4 font-mono" style={{
                  backgroundColor: v.severity === 'high' ? 'rgba(237,137,54,0.2)' : 'rgba(236,201,75,0.2)',
                  color: v.severity === 'high' ? '#ed8936' : '#ecc94b',
                }}>
                  {v.cve}
                </Badge>
              </div>
              <div className="text-xs font-medium mt-1">{v.package}@{v.version}</div>
              <div className="text-[10px] opacity-50">{v.description}</div>
            </div>
          ))}
        </div>

        {/* Data Flow */}
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <Droplets className="h-3.5 w-3.5" style={{ color: '#63b3ed' }} />
            <span className="text-xs font-semibold">Taint Violations</span>
            <Badge className="text-[10px] h-5 ml-auto" style={{ backgroundColor: flowCount > 0 ? 'rgba(229,62,62,0.15)' : 'rgba(72,187,120,0.15)', color: flowCount > 0 ? '#e53e3e' : '#48bb78' }}>
              {flowCount}
            </Badge>
          </div>
          {dataflow?.flows?.map((f, i) => (
            <div key={i} style={card('')}>
              <div className="text-xs">
                <span style={{ color: '#ecc94b' }}>{f.source.fn}</span>
                <span className="opacity-40 mx-1">→</span>
                <span style={{ color: '#e53e3e' }}>{f.sink.fn}</span>
              </div>
              <div className="text-[10px] opacity-50 mt-0.5">Unsafe data flow detected</div>
            </div>
          ))}
        </div>

        {/* Missing Env Vars */}
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <Globe className="h-3.5 w-3.5" style={{ color: '#ecc94b' }} />
            <span className="text-xs font-semibold">Missing Env Vars</span>
            <Badge className="text-[10px] h-5 ml-auto" style={{ backgroundColor: missingEnv > 0 ? 'rgba(236,201,75,0.15)' : 'rgba(72,187,120,0.15)', color: missingEnv > 0 ? '#ecc94b' : '#48bb78' }}>
              {missingEnv}
            </Badge>
          </div>
          {envCheck?.missing?.map((env, i) => (
            <div key={i} className="text-xs font-mono px-2 py-1 rounded" style={{ backgroundColor: theme === 'dark' ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)', color: '#ecc94b' }}>
              {env}
            </div>
          ))}
        </div>
      </div>
    </ScrollArea>
  )
}
