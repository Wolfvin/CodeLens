'use client'

import React from 'react'
import { Palette, FileQuestion, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { useAnalysisStore } from '@/lib/analysisStore'

interface CssTabProps {
  theme: 'dark' | 'light'
}

export function CssTab({ theme }: CssTabProps) {
  const { cssResults, runCommand, workspace, runningCommands } = useAnalysisStore()
  const { cssDeep, missingRefs } = cssResults

  const isRunning = (cmd: string) => runningCommands.includes(cmd)

  const runCssAudit = async () => {
    await runCommand('css-deep', [workspace])
    await runCommand('missing-refs', [workspace])
  }

  const unusedVars = cssDeep?.unused_vars?.length ?? 0
  const orphanKf = cssDeep?.orphan_keyframes?.length ?? 0
  const importantCount = cssDeep?.specificity_wars?.important_count ?? 0
  const dupProps = cssDeep?.duplicate_properties?.count ?? 0
  const zIndexAbuse = cssDeep?.z_index_abuse?.above_1000 ?? 0
  const cssNoHtml = missingRefs?.css_no_html?.length ?? 0
  const htmlNoCss = missingRefs?.html_no_css?.length ?? 0

  const card = {
    backgroundColor: theme === 'dark' ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)',
    borderRadius: '8px',
    padding: '10px',
  }

  const statCard = (label: string, count: number, warnThreshold: number = 1) => (
    <div style={card}>
      <div className="text-[10px] font-bold uppercase tracking-widest opacity-50">{label}</div>
      <div className="text-xl font-bold mt-1" style={{ color: count > warnThreshold ? '#ed8936' : '#48bb78' }}>{count}</div>
    </div>
  )

  return (
    <ScrollArea className="h-full">
      <div className="p-3 space-y-4">
        {/* CSS Deep Audit */}
        <Button
          className="w-full h-9 text-xs gap-2 bg-pink-600 hover:bg-pink-700 text-white"
          onClick={runCssAudit}
          disabled={isRunning('css-deep')}
        >
          {isRunning('css-deep') ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Palette className="h-3.5 w-3.5" />}
          CSS Deep Audit
        </Button>

        <div className="grid grid-cols-2 gap-1.5">
          <Button size="sm" variant="outline" className="h-7 text-[10px] gap-1" style={{ borderColor: theme === 'dark' ? '#2d3748' : '#e2e8f0', color: theme === 'dark' ? '#e2e8f0' : '#1a202c' }} onClick={() => runCommand('css-deep', [workspace])} disabled={isRunning('css-deep')}>
            <Palette className="h-3 w-3" /> CSS Deep
          </Button>
          <Button size="sm" variant="outline" className="h-7 text-[10px] gap-1" style={{ borderColor: theme === 'dark' ? '#2d3748' : '#e2e8f0', color: theme === 'dark' ? '#e2e8f0' : '#1a202c' }} onClick={() => runCommand('missing-refs', [workspace])} disabled={isRunning('missing-refs')}>
            <FileQuestion className="h-3 w-3" /> Refs
          </Button>
        </div>

        <Separator style={{ backgroundColor: theme === 'dark' ? '#2d3748' : '#e2e8f0' }} />

        {/* Summary Grid */}
        <div className="grid grid-cols-2 gap-2">
          {statCard('Unused CSS Vars', unusedVars)}
          {statCard('Orphan Keyframes', orphanKf)}
          {statCard('!important Overuse', importantCount, 5)}
          {statCard('Duplicate Props', dupProps)}
        </div>

        {/* Z-Index Abuse */}
        <div className="space-y-2">
          <div className="text-xs font-semibold">Z-Index Abuse</div>
          <div className="grid grid-cols-2 gap-2">
            <div style={card}>
              <div className="text-[10px] font-bold uppercase tracking-widest opacity-50">Max Z</div>
              <div className="text-xl font-bold mt-1" style={{ color: zIndexAbuse > 0 ? '#e53e3e' : '#48bb78' }}>
                {cssDeep?.z_index_abuse?.max ?? 0}
              </div>
            </div>
            <div style={card}>
              <div className="text-[10px] font-bold uppercase tracking-widest opacity-50">Above 1K</div>
              <div className="text-xl font-bold mt-1" style={{ color: zIndexAbuse > 0 ? '#ed8936' : '#48bb78' }}>{zIndexAbuse}</div>
            </div>
          </div>
        </div>

        {/* Specificity Wars Detail */}
        {cssDeep?.specificity_wars?.files && cssDeep.specificity_wars.files.length > 0 && (
          <div className="space-y-2">
            <div className="text-xs font-semibold">!important Files</div>
            {cssDeep.specificity_wars.files.map((f: string, i: number) => (
              <div key={i} className="text-xs font-mono px-2 py-1 rounded" style={{ backgroundColor: theme === 'dark' ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)' }}>
                {f}
              </div>
            ))}
          </div>
        )}

        {/* Missing Refs */}
        <div className="space-y-2">
          <div className="text-xs font-semibold">Missing References</div>

          {cssNoHtml > 0 && (
            <div className="space-y-1">
              <div className="text-[10px] font-bold uppercase tracking-widest opacity-40">CSS → No HTML</div>
              {missingRefs?.css_no_html?.map((ref: string, i: number) => (
                <div key={i} className="flex items-center gap-2 text-xs">
                  <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
                  <span className="font-mono" style={{ color: '#ed8936' }}>{ref}</span>
                </div>
              ))}
            </div>
          )}

          {htmlNoCss > 0 && (
            <div className="space-y-1">
              <div className="text-[10px] font-bold uppercase tracking-widest opacity-40">HTML → No CSS</div>
              {missingRefs?.html_no_css?.map((ref: string, i: number) => (
                <div key={i} className="flex items-center gap-2 text-xs">
                  <span className="w-1.5 h-1.5 rounded-full bg-red-500" />
                  <span className="font-mono" style={{ color: '#e53e3e' }}>{ref}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Unused Vars List */}
        {cssDeep?.unused_vars && cssDeep.unused_vars.length > 0 && (
          <div className="space-y-2">
            <div className="text-xs font-semibold">Unused CSS Variables</div>
            {cssDeep.unused_vars.map((v: string, i: number) => (
              <div key={i} className="text-xs font-mono px-2 py-1 rounded" style={{ backgroundColor: theme === 'dark' ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)', color: '#ecc94b' }}>
                {v}
              </div>
            ))}
          </div>
        )}

        {/* Orphan Keyframes */}
        {cssDeep?.orphan_keyframes && cssDeep.orphan_keyframes.length > 0 && (
          <div className="space-y-2">
            <div className="text-xs font-semibold">Orphan Keyframes</div>
            {cssDeep.orphan_keyframes.map((kf: string, i: number) => (
              <div key={i} className="text-xs font-mono px-2 py-1 rounded" style={{ backgroundColor: theme === 'dark' ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)', color: '#ed8936' }}>
                @{kf}
              </div>
            ))}
          </div>
        )}
      </div>
    </ScrollArea>
  )
}
