'use client'

import { useMemo } from 'react'
import { X, ChevronRight, MapPin, Tag, Shield, Code2, Zap } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import type {
  GraphNode,
  NodeDetail,
  QuickAction,
  NodeType,
  NodeStatus,
} from '@/types/neural'
import { NEURAL_COLORS, getNodeShape } from '@/types/neural'

// ─── Props ───────────────────────────────────────────────────
interface SlideInPanelProps {
  theme: 'dark' | 'light'
  node: GraphNode | null
  detail: NodeDetail | null
  quickActions: QuickAction[]
  onAction: (action: QuickAction) => void
  onClose: () => void
}

// ─── Helpers ─────────────────────────────────────────────────
const SHAPE_ICONS: Record<string, string> = {
  circle: '●',
  hexagon: '⬡',
  diamond: '◆',
  triangle: '▲',
  star: '★',
  square: '■',
  ring: '◎',
}

const TYPE_LABELS: Record<NodeType, string> = {
  class: 'CSS Class',
  id: 'HTML ID',
  function: 'Function',
  component: 'Component',
  store: 'Store',
  file: 'File',
  package: 'Package',
  route: 'Route',
  env_var: 'Env Variable',
  variable: 'Variable',
  secret: 'Secret',
  vulnerability: 'Vulnerability',
  test: 'Test',
  import: 'Import',
  css_var: 'CSS Variable',
  keyframe: 'Keyframe',
}

const STATUS_COLORS: Record<NodeStatus, string> = {
  active: NEURAL_COLORS.active,
  dead: NEURAL_COLORS.dead,
  vulnerable: NEURAL_COLORS.vulnerable,
  critical: NEURAL_COLORS.critical,
  safe: NEURAL_COLORS.safe,
  orphan: NEURAL_COLORS.orphan,
  warning: NEURAL_COLORS.warning,
  duplicate_define: NEURAL_COLORS.warning,
  collision: NEURAL_COLORS.vulnerable,
  impure: NEURAL_COLORS.warning,
  untested: NEURAL_COLORS.untested,
  unused: NEURAL_COLORS.unused,
}

function shapeIcon(type: NodeType): string {
  const shape = getNodeShape(type)
  return SHAPE_ICONS[shape] ?? '●'
}

// ─── Sub-components ──────────────────────────────────────────

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h4
      className="text-[10px] font-bold uppercase tracking-[0.1em] mb-2 flex items-center gap-1.5"
      style={{ color: 'rgba(139, 92, 246, 0.5)' }}
    >
      {children}
    </h4>
  )
}

function ProgressBar({ value, color, label }: { value: number; color: string; label: string }) {
  const pct = Math.min(100, Math.max(0, value * 100))
  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-xs">
        <span className="opacity-60">{label}</span>
        <span className="font-mono text-[10px] opacity-50">{Math.round(pct)}%</span>
      </div>
      <div className="h-1 rounded-full overflow-hidden" style={{ backgroundColor: 'rgba(139, 92, 246, 0.08)' }}>
        <div
          className="h-full rounded-full transition-all duration-700 ease-out"
          style={{
            width: `${pct}%`,
            backgroundColor: color,
            boxShadow: `0 0 8px ${color}40`,
          }}
        />
      </div>
    </div>
  )
}

function RefList({
  items,
  dark,
}: {
  items: Array<{ fn?: string; file: string; line: number; source?: string }>
  dark: boolean
}) {
  return (
    <ul className="space-y-1">
      {items.map((item, i) => (
        <li
          key={`${item.file}:${item.line}:${i}`}
          className="flex items-center gap-1.5 text-xs py-0.5 px-1.5 rounded-md transition-colors duration-150 hover:bg-white/[0.03]"
        >
          <ChevronRight className="h-3 w-3 shrink-0 opacity-30" />
          <span className="font-medium truncate">{item.fn ?? item.source ?? 'ref'}</span>
          <span
            className={`ml-auto shrink-0 font-mono text-[10px] ${dark ? 'text-slate-500' : 'text-slate-400'}`}
          >
            {item.file}:{item.line}
          </span>
        </li>
      ))}
    </ul>
  )
}

// ─── Type-specific sections ──────────────────────────────────

function FunctionSection({ detail, dark }: { detail: NodeDetail; dark: boolean }) {
  return (
    <>
      {(detail.callers && detail.callers.length > 0) && (
        <div className="space-y-1 fade-in">
          <SectionTitle>Callers</SectionTitle>
          <RefList items={detail.callers!.map(c => ({ fn: c.fn, file: c.file, line: c.line }))} dark={dark} />
        </div>
      )}
      {(detail.callees && detail.callees.length > 0) && (
        <div className="space-y-1 fade-in">
          <SectionTitle>Callees</SectionTitle>
          <RefList items={detail.callees!.map(c => ({ fn: c.fn, file: c.file, line: c.line }))} dark={dark} />
        </div>
      )}

      <div className="divider-glow" />

      <div className="fade-in">
        <SectionTitle>Analysis</SectionTitle>
        <div className="space-y-3">
          {detail.purity !== undefined && (
            <ProgressBar
              value={detail.purity}
              color={detail.purity > 0.7 ? '#10b981' : detail.purity > 0.4 ? '#f59e0b' : '#ef4444'}
              label="Purity"
            />
          )}
          {detail.complexity !== undefined && (
            <ProgressBar
              value={1 - Math.min(detail.complexity / 20, 1)}
              color={detail.complexity > 15 ? '#ef4444' : detail.complexity > 8 ? '#f59e0b' : '#10b981'}
              label={`Complexity (${detail.complexity})`}
            />
          )}
          {detail.coverage !== undefined && (
            <div className="flex items-center gap-2 text-xs">
              <span className="opacity-60">Test coverage:</span>
              {detail.coverage ? (
                <Badge variant="outline" className="text-[10px] h-5 border-emerald-500/40 text-emerald-400 bg-emerald-500/5">
                  Covered
                </Badge>
              ) : (
                <Badge variant="outline" className="text-[10px] h-5 border-red-400/40 text-red-400 bg-red-500/5">
                  Uncovered
                </Badge>
              )}
            </div>
          )}
        </div>
      </div>
    </>
  )
}

function CssClassSection({ detail, dark }: { detail: NodeDetail; dark: boolean }) {
  return (
    <>
      {detail.definedIn && detail.definedIn.length > 0 && (
        <div className="space-y-1 fade-in">
          <SectionTitle>Defined In</SectionTitle>
          <RefList items={detail.definedIn!.map(d => ({ file: d.file, line: d.line, source: 'CSS' }))} dark={dark} />
        </div>
      )}
      {detail.references && detail.references.length > 0 && (
        <div className="space-y-1 fade-in">
          <SectionTitle>Used By</SectionTitle>
          <RefList items={detail.references!.map(r => ({ file: r.file, line: r.line, source: r.source }))} dark={dark} />
        </div>
      )}
      {detail.issues && detail.issues.length > 0 && (
        <>
          <div className="divider-glow" />
          <div className="space-y-1.5 fade-in">
            <SectionTitle>Issues</SectionTitle>
            {detail.issues!.map((issue, i) => (
              <div
                key={`issue-${i}`}
                className={`text-xs px-2.5 py-2 rounded-lg border transition-colors ${
                  issue.severity === 'error'
                    ? 'bg-red-500/5 border-red-500/10 text-red-400'
                    : issue.severity === 'warning'
                      ? 'bg-amber-500/5 border-amber-500/10 text-amber-400'
                      : 'bg-slate-500/5 border-slate-500/10 text-slate-400'
                }`}
              >
                <span className="font-medium">{issue.category}</span>
                <span className="mx-1 opacity-30">·</span>
                <span className="opacity-70">{issue.message}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </>
  )
}

function IdSection({ detail, node, dark }: { detail: NodeDetail; node: GraphNode; dark: boolean }) {
  const hasCollision = node.status === 'collision'
  return (
    <>
      {detail.definedIn && detail.definedIn.length > 0 && (
        <div className="space-y-1 fade-in">
          <SectionTitle>HTML Definition</SectionTitle>
          <RefList items={detail.definedIn!.map(d => ({ file: d.file, line: d.line, source: 'HTML' }))} dark={dark} />
        </div>
      )}
      {detail.references && detail.references.length > 0 && (
        <div className="space-y-1 fade-in">
          <SectionTitle>Accessed By</SectionTitle>
          <RefList items={detail.references!.map(r => ({ file: r.file, line: r.line, source: r.source }))} dark={dark} />
        </div>
      )}
      <div className="divider-glow" />
      <div className="space-y-1 fade-in">
        <SectionTitle>Collision</SectionTitle>
        {hasCollision ? (
          <Badge variant="outline" className="text-[10px] h-5 border-red-400/40 text-red-400 bg-red-500/5">
            ⚠ Collision detected
          </Badge>
        ) : (
          <Badge variant="outline" className="text-[10px] h-5 border-emerald-500/40 text-emerald-400 bg-emerald-500/5">
            ✓ No collision
          </Badge>
        )}
      </div>
    </>
  )
}

function ComponentSection({ detail, node, dark }: { detail: NodeDetail; node: GraphNode; dark: boolean }) {
  const data = node.data as Record<string, unknown>
  const props = data?.props as string[] | undefined
  const renderTree = data?.renderTree as string[] | undefined
  const connectedStores = data?.connectedStores as string[] | undefined

  return (
    <>
      {props && props.length > 0 && (
        <div className="space-y-1.5 fade-in">
          <SectionTitle>Props</SectionTitle>
          <div className="flex flex-wrap gap-1">
            {props.map(p => (
              <Badge key={p} variant="secondary" className="text-[10px] h-5 bg-purple-500/5 text-purple-300 border-purple-500/10">
                {p}
              </Badge>
            ))}
          </div>
        </div>
      )}
      {renderTree && renderTree.length > 0 && (
        <div className="space-y-1 fade-in">
          <SectionTitle>Render Tree</SectionTitle>
          <ul className="space-y-0.5">
            {renderTree.map((child, i) => (
              <li key={`rt-${i}`} className="flex items-center gap-1.5 text-xs py-0.5">
                <ChevronRight className="h-3 w-3 opacity-30" />
                <span>{child}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {connectedStores && connectedStores.length > 0 && (
        <div className="space-y-1.5 fade-in">
          <SectionTitle>Connected Stores</SectionTitle>
          <div className="flex flex-wrap gap-1">
            {connectedStores.map(s => (
              <Badge key={s} variant="outline" className="text-[10px] h-5 border-amber-400/30 text-amber-400 bg-amber-500/5">
                {s}
              </Badge>
            ))}
          </div>
        </div>
      )}
    </>
  )
}

function StoreSection({ detail, node, dark }: { detail: NodeDetail; node: GraphNode; dark: boolean }) {
  const data = node.data as Record<string, unknown>
  const reads = data?.reads as string[] | undefined
  const writes = data?.writes as string[] | undefined
  const flow = data?.flow as string[] | undefined

  return (
    <>
      {reads && reads.length > 0 && (
        <div className="space-y-1.5 fade-in">
          <SectionTitle>Reads</SectionTitle>
          <div className="flex flex-wrap gap-1">
            {reads.map(r => (
              <Badge key={r} variant="secondary" className="text-[10px] h-5 bg-blue-500/5 text-blue-300 border-blue-500/10">
                {r}
              </Badge>
            ))}
          </div>
        </div>
      )}
      {writes && writes.length > 0 && (
        <div className="space-y-1.5 fade-in">
          <SectionTitle>Writes</SectionTitle>
          <div className="flex flex-wrap gap-1">
            {writes.map(w => (
              <Badge key={w} variant="outline" className="text-[10px] h-5 border-amber-400/30 text-amber-400 bg-amber-500/5">
                {w}
              </Badge>
            ))}
          </div>
        </div>
      )}
      {flow && flow.length > 0 && (
        <>
          <div className="divider-glow" />
          <div className="space-y-1 fade-in">
            <SectionTitle>State Change Flow</SectionTitle>
            <ul className="space-y-0.5">
              {flow.map((step, i) => (
                <li key={`flow-${i}`} className="flex items-center gap-1.5 text-xs py-0.5">
                  <span className="opacity-30 text-[10px] font-mono w-4 text-right">{i + 1}.</span>
                  <span>{step}</span>
                </li>
              ))}
            </ul>
          </div>
        </>
      )}
    </>
  )
}

function PackageSection({ detail, node, dark }: { detail: NodeDetail; node: GraphNode; dark: boolean }) {
  const data = node.data as Record<string, unknown>
  const version = data?.version as string | undefined
  const vulnerabilities = data?.vulnerabilities as Array<{ cve: string; severity: string; url?: string }> | undefined
  const dependents = data?.dependents as string[] | undefined

  return (
    <>
      {version && (
        <div className="space-y-1 fade-in">
          <SectionTitle>Version</SectionTitle>
          <span className="text-sm font-mono px-2 py-0.5 rounded-md" style={{ backgroundColor: dark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)' }}>
            {version}
          </span>
        </div>
      )}
      {vulnerabilities && vulnerabilities.length > 0 && (
        <div className="space-y-1.5 fade-in">
          <SectionTitle>Vulnerabilities</SectionTitle>
          {vulnerabilities.map((v, i) => (
            <div
              key={`vuln-${i}`}
              className={`text-xs px-2.5 py-2 rounded-lg border ${
                v.severity === 'critical'
                  ? 'bg-red-500/5 border-red-500/10 text-red-400'
                  : v.severity === 'high'
                    ? 'bg-orange-500/5 border-orange-500/10 text-orange-400'
                    : 'bg-amber-500/5 border-amber-500/10 text-amber-400'
              }`}
            >
              <span className="font-mono font-medium">{v.cve}</span>
              <span className="mx-1 opacity-30">·</span>
              <span className="opacity-70">{v.severity}</span>
            </div>
          ))}
        </div>
      )}
      {(!vulnerabilities || vulnerabilities.length === 0) && (
        <div className="space-y-1 fade-in">
          <SectionTitle>Vulnerabilities</SectionTitle>
          <Badge variant="outline" className="text-[10px] h-5 border-emerald-500/40 text-emerald-400 bg-emerald-500/5">
            ✓ No known CVEs
          </Badge>
        </div>
      )}
      {dependents && dependents.length > 0 && (
        <>
          <div className="divider-glow" />
          <div className="space-y-1.5 fade-in">
            <SectionTitle>Dependents</SectionTitle>
            <div className="flex flex-wrap gap-1">
              {dependents.map(d => (
                <Badge key={d} variant="secondary" className="text-[10px] h-5 bg-slate-500/5">
                  {d}
                </Badge>
              ))}
            </div>
          </div>
        </>
      )}
    </>
  )
}

function EnvVarSection({ detail, node, dark }: { detail: NodeDetail; node: GraphNode; dark: boolean }) {
  const data = node.data as Record<string, unknown>
  const required = data?.required as boolean | undefined
  const hasFallback = data?.hasFallback as boolean | undefined
  const documented = data?.documented as boolean | undefined
  const files = data?.files as string[] | undefined

  return (
    <>
      <div className="space-y-2 fade-in">
        <SectionTitle>Properties</SectionTitle>
        <div className="grid grid-cols-3 gap-2 text-xs">
          <div className="space-y-1 text-center">
            <span className="opacity-50 text-[10px]">Required</span>
            <div>
              {required ? (
                <Badge variant="outline" className="text-[10px] h-5 border-red-400/40 text-red-400 bg-red-500/5">Yes</Badge>
              ) : (
                <Badge variant="outline" className="text-[10px] h-5 border-emerald-500/40 text-emerald-400 bg-emerald-500/5">No</Badge>
              )}
            </div>
          </div>
          <div className="space-y-1 text-center">
            <span className="opacity-50 text-[10px]">Fallback</span>
            <div>
              {hasFallback ? (
                <Badge variant="outline" className="text-[10px] h-5 border-emerald-500/40 text-emerald-400 bg-emerald-500/5">Yes</Badge>
              ) : (
                <Badge variant="outline" className="text-[10px] h-5 border-amber-400/40 text-amber-400 bg-amber-500/5">None</Badge>
              )}
            </div>
          </div>
          <div className="space-y-1 text-center">
            <span className="opacity-50 text-[10px]">Documented</span>
            <div>
              {documented ? (
                <Badge variant="outline" className="text-[10px] h-5 border-emerald-500/40 text-emerald-400 bg-emerald-500/5">Yes</Badge>
              ) : (
                <Badge variant="outline" className="text-[10px] h-5 border-slate-400/40 text-slate-400 bg-slate-500/5">No</Badge>
              )}
            </div>
          </div>
        </div>
      </div>
      {files && files.length > 0 && (
        <>
          <div className="divider-glow" />
          <div className="space-y-1 fade-in">
            <SectionTitle>Files</SectionTitle>
            <ul className="space-y-0.5">
              {files.map((f, i) => (
                <li key={`file-${i}`} className="flex items-center gap-1.5 text-xs font-mono py-0.5">
                  <ChevronRight className="h-3 w-3 opacity-30" />
                  <span className="opacity-80">{f}</span>
                </li>
              ))}
            </ul>
          </div>
        </>
      )}
    </>
  )
}

function TypeSpecificSection({ node, detail, dark }: { node: GraphNode; detail: NodeDetail; dark: boolean }) {
  switch (node.type) {
    case 'function':
      return <FunctionSection detail={detail} dark={dark} />
    case 'class':
      return <CssClassSection detail={detail} dark={dark} />
    case 'id':
      return <IdSection detail={detail} node={node} dark={dark} />
    case 'component':
      return <ComponentSection detail={detail} node={node} dark={dark} />
    case 'store':
      return <StoreSection detail={detail} node={node} dark={dark} />
    case 'package':
      return <PackageSection detail={detail} node={node} dark={dark} />
    case 'env_var':
      return <EnvVarSection detail={detail} node={node} dark={dark} />
    default:
      return null
  }
}

// ─── Main Component ──────────────────────────────────────────

export function SlideInPanel({
  theme,
  node,
  detail,
  quickActions,
  onAction,
  onClose,
}: SlideInPanelProps) {
  const dark = theme === 'dark'
  const isOpen = node !== null

  const refCount = useMemo(() => {
    if (!detail) return 0
    return (
      (detail.callers?.length ?? 0) +
      (detail.callees?.length ?? 0) +
      (detail.references?.length ?? 0) +
      (detail.definedIn?.length ?? 0) +
      (detail.tests?.length ?? 0)
    )
  }, [detail])

  const borderColor = dark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.06)'
  const bgColor = dark ? 'rgba(8, 8, 16, 0.8)' : 'rgba(255, 255, 255, 0.88)'
  const textColor = dark ? '#e2e8f0' : '#1a202c'
  const mutedText = dark ? '#718096' : '#94a3b8'

  return (
    <div
      className="fixed top-0 right-0 h-full z-50 flex slide-in-panel"
      style={{
        transform: isOpen ? 'translateX(0)' : 'translateX(100%)',
        opacity: isOpen ? 1 : 0,
        width: 400,
      }}
    >
      {/* Panel body */}
      <div
        className="flex flex-col h-full w-full overflow-hidden"
        style={{
          backgroundColor: bgColor,
          color: textColor,
          borderLeft: `1px solid ${borderColor}`,
          backdropFilter: 'blur(24px) saturate(1.3)',
          WebkitBackdropFilter: 'blur(24px) saturate(1.3)',
          boxShadow: dark
            ? '-8px 0 32px rgba(0,0,0,0.4), inset 1px 0 0 rgba(255,255,255,0.03)'
            : '-8px 0 32px rgba(0,0,0,0.08), inset 1px 0 0 rgba(0,0,0,0.03)',
        }}
      >
        {/* Header with glow accent */}
        {node && (
          <div
            className="px-5 py-4 shrink-0 relative overflow-hidden"
            style={{ borderBottom: `1px solid ${borderColor}` }}
          >
            {/* Subtle top glow */}
            <div
              className="absolute top-0 left-0 right-0 h-1 opacity-60"
              style={{
                background: `linear-gradient(90deg, transparent, ${node.color}40, transparent)`,
              }}
            />
            <div className="flex items-center gap-3 relative">
              {/* Node icon with glow */}
              <div
                className="w-8 h-8 flex items-center justify-center rounded-lg"
                style={{
                  backgroundColor: `${node.color}10`,
                  boxShadow: `0 0 12px ${node.color}15`,
                }}
              >
                <span
                  className="text-base leading-none"
                  style={{ color: node.color, filter: `drop-shadow(0 0 4px ${node.color}40)` }}
                >
                  {shapeIcon(node.type)}
                </span>
              </div>
              <div className="flex-1 min-w-0">
                <div className="font-semibold text-sm truncate">{node.label}</div>
                <div className="flex items-center gap-2 mt-0.5">
                  <span
                    className="text-[10px] font-medium uppercase tracking-wide px-2 py-0.5 rounded-full"
                    style={{
                      backgroundColor: `${node.color}10`,
                      color: node.color,
                    }}
                  >
                    {TYPE_LABELS[node.type]}
                  </span>
                  <span
                    className="inline-block h-1.5 w-1.5 rounded-full"
                    style={{ backgroundColor: STATUS_COLORS[node.status] }}
                  />
                </div>
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 shrink-0 smooth-colors hover:bg-white/5"
                onClick={onClose}
              >
                <X className="h-4 w-4" style={{ color: mutedText }} />
              </Button>
            </div>
          </div>
        )}

        {/* Scrollable content */}
        {node && (
          <ScrollArea className="flex-1 panel-scroll">
            <div className="p-5 space-y-4 stagger-children">
              {/* Location */}
              {node.file && (
                <div className="flex items-center gap-2 text-xs px-2 py-1.5 rounded-lg" style={{ backgroundColor: dark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.02)' }}>
                  <MapPin className="h-3.5 w-3.5 shrink-0" style={{ color: mutedText }} />
                  <span className="font-mono truncate opacity-60" style={{ color: mutedText }}>
                    {node.file}{node.line ? `:${node.line}` : ''}
                  </span>
                </div>
              )}

              {/* Badges */}
              <div className="flex items-center gap-2 flex-wrap">
                <Badge variant="outline" className="text-[10px] h-5 gap-1 border-0" style={{ backgroundColor: dark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.03)' }}>
                  <Tag className="h-2.5 w-2.5 opacity-50" />
                  {node.type}
                </Badge>
                <Badge
                  variant="outline"
                  className="text-[10px] h-5 border-0"
                  style={{
                    backgroundColor: node.domain === 'frontend' ? 'rgba(183,148,244,0.06)' : 'rgba(99,179,237,0.06)',
                    color: node.domain === 'frontend' ? '#b794f4' : '#63b3ed',
                  }}
                >
                  {node.domain}
                </Badge>
              </div>

              <div className="divider-glow" />

              {/* Status */}
              <div className="space-y-1.5">
                <SectionTitle>Status</SectionTitle>
                <div className="flex items-center gap-2 text-xs">
                  <span
                    className="inline-block h-2 w-2 rounded-full shrink-0"
                    style={{
                      backgroundColor: STATUS_COLORS[node.status],
                      boxShadow: `0 0 6px ${STATUS_COLORS[node.status]}40`,
                    }}
                  />
                  <span className="capitalize">{node.status.replace('_', ' ')}</span>
                  {refCount > 0 && (
                    <>
                      <span className="opacity-20">·</span>
                      <span style={{ color: mutedText }}>
                        {refCount} ref{refCount !== 1 ? 's' : ''}
                      </span>
                    </>
                  )}
                </div>
              </div>

              <div className="divider-glow" />

              {/* Type-specific section */}
              {detail && (
                <TypeSpecificSection node={node} detail={detail} dark={dark} />
              )}

              {/* Code snippet */}
              {detail?.code && (
                <>
                  <div className="divider-glow" />
                  <div className="space-y-2">
                    <SectionTitle>Code Snippet</SectionTitle>
                    <div
                      className="rounded-xl p-4 overflow-x-auto text-xs font-mono leading-relaxed border"
                      style={{
                        backgroundColor: dark ? 'rgba(0,0,0,0.25)' : 'rgba(0,0,0,0.03)',
                        borderColor: dark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.06)',
                        color: textColor,
                      }}
                    >
                      <pre className="whitespace-pre-wrap break-words">{detail.code}</pre>
                    </div>
                  </div>
                </>
              )}

              {/* Quick Actions */}
              {quickActions.length > 0 && (
                <>
                  <div className="divider-glow" />
                  <div className="space-y-2">
                    <SectionTitle>
                      <Zap className="h-3 w-3 inline mr-1" />
                      Quick Actions
                    </SectionTitle>
                    <div className="flex flex-wrap gap-2">
                      {quickActions.map(action => (
                        <Button
                          key={action.command}
                          size="sm"
                          variant={
                            action.variant === 'danger'
                              ? 'destructive'
                              : action.variant === 'warning'
                                ? 'outline'
                                : 'default'
                          }
                          className={`h-7 text-xs gap-1.5 action-glow ${
                            action.variant === 'warning'
                              ? 'border-amber-500/30 text-amber-400 hover:bg-amber-500/5 hover:border-amber-500/50'
                              : action.variant === 'default'
                                ? 'bg-purple-600 hover:bg-purple-700 text-white border-0'
                                : ''
                          }`}
                          onClick={() => onAction(action)}
                        >
                          {action.label}
                        </Button>
                      ))}
                    </div>
                  </div>
                </>
              )}
            </div>
          </ScrollArea>
        )}
      </div>
    </div>
  )
}
