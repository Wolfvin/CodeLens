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
}

function shapeIcon(type: NodeType): string {
  const shape = getNodeShape(type)
  return SHAPE_ICONS[shape] ?? '●'
}

// ─── Sub-components ──────────────────────────────────────────

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h4 className="text-[10px] font-bold uppercase tracking-widest opacity-50 mb-2">
      {children}
    </h4>
  )
}

function ProgressBar({ value, color, label }: { value: number; color: string; label: string }) {
  const pct = Math.min(100, Math.max(0, value * 100))
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="opacity-70">{label}</span>
        <span className="opacity-70">{Math.round(pct)}%</span>
      </div>
      <div className="h-1.5 rounded-full overflow-hidden bg-white/10">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, backgroundColor: color }}
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
          className="flex items-center gap-1.5 text-xs"
        >
          <ChevronRight
            className="h-3 w-3 shrink-0 opacity-40"
          />
          <span className="font-medium truncate">
            {item.fn ?? item.source ?? 'ref'}
          </span>
          <span
            className={`ml-auto shrink-0 font-mono text-[10px] ${
              dark ? 'text-slate-400' : 'text-slate-500'
            }`}
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
      {/* Topology */}
      {(detail.callers && detail.callers.length > 0) && (
        <div className="space-y-1">
          <SectionTitle>Callers</SectionTitle>
          <RefList items={detail.callers!.map(c => ({ fn: c.fn, file: c.file, line: c.line }))} dark={dark} />
        </div>
      )}
      {(detail.callees && detail.callees.length > 0) && (
        <div className="space-y-1">
          <SectionTitle>Callees</SectionTitle>
          <RefList items={detail.callees!.map(c => ({ fn: c.fn, file: c.file, line: c.line }))} dark={dark} />
        </div>
      )}

      <Separator className="opacity-20" />

      {/* Analysis */}
      <div>
        <SectionTitle>Analysis</SectionTitle>
        <div className="space-y-2">
          {detail.purity !== undefined && (
            <ProgressBar
              value={detail.purity}
              color={detail.purity > 0.7 ? '#48bb78' : detail.purity > 0.4 ? '#ecc94b' : '#e53e3e'}
              label="Purity"
            />
          )}
          {detail.complexity !== undefined && (
            <ProgressBar
              value={1 - Math.min(detail.complexity / 20, 1)} // invert: lower complexity = higher bar
              color={detail.complexity > 15 ? '#e53e3e' : detail.complexity > 8 ? '#ecc94b' : '#48bb78'}
              label={`Complexity (${detail.complexity})`}
            />
          )}
          {detail.coverage !== undefined && (
            <div className="flex items-center gap-2 text-xs">
              <span className="opacity-70">Test coverage:</span>
              {detail.coverage ? (
                <Badge variant="outline" className="text-[10px] h-5 border-green-500 text-green-500">
                  Covered
                </Badge>
              ) : (
                <Badge variant="outline" className="text-[10px] h-5 border-red-400 text-red-400">
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
        <div className="space-y-1">
          <SectionTitle>Defined In</SectionTitle>
          <RefList items={detail.definedIn!.map(d => ({ file: d.file, line: d.line, source: 'CSS' }))} dark={dark} />
        </div>
      )}

      {detail.references && detail.references.length > 0 && (
        <div className="space-y-1">
          <SectionTitle>Used By</SectionTitle>
          <RefList items={detail.references!.map(r => ({ file: r.file, line: r.line, source: r.source }))} dark={dark} />
        </div>
      )}

      {detail.issues && detail.issues.length > 0 && (
        <>
          <Separator className="opacity-20" />
          <div className="space-y-1">
            <SectionTitle>Issues</SectionTitle>
            {detail.issues!.map((issue, i) => (
              <div
                key={`issue-${i}`}
                className={`text-xs px-2 py-1.5 rounded ${
                  issue.severity === 'error'
                    ? 'bg-red-500/10 text-red-400'
                    : issue.severity === 'warning'
                      ? 'bg-amber-500/10 text-amber-400'
                      : 'bg-slate-500/10 text-slate-400'
                }`}
              >
                <span className="font-medium">{issue.category}</span>
                <span className="mx-1 opacity-50">·</span>
                <span className="opacity-80">{issue.message}</span>
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
        <div className="space-y-1">
          <SectionTitle>HTML Definition</SectionTitle>
          <RefList items={detail.definedIn!.map(d => ({ file: d.file, line: d.line, source: 'HTML' }))} dark={dark} />
        </div>
      )}

      {detail.references && detail.references.length > 0 && (
        <div className="space-y-1">
          <SectionTitle>Accessed By</SectionTitle>
          <RefList items={detail.references!.map(r => ({ file: r.file, line: r.line, source: r.source }))} dark={dark} />
        </div>
      )}

      <Separator className="opacity-20" />

      <div className="space-y-1">
        <SectionTitle>Collision</SectionTitle>
        {hasCollision ? (
          <Badge variant="outline" className="text-[10px] h-5 border-red-400 text-red-400">
            ⚠ Collision detected
          </Badge>
        ) : (
          <Badge variant="outline" className="text-[10px] h-5 border-green-500 text-green-500">
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
        <div className="space-y-1">
          <SectionTitle>Props</SectionTitle>
          <div className="flex flex-wrap gap-1">
            {props.map(p => (
              <Badge key={p} variant="secondary" className="text-[10px] h-5">
                {p}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {renderTree && renderTree.length > 0 && (
        <div className="space-y-1">
          <SectionTitle>Render Tree</SectionTitle>
          <ul className="space-y-0.5">
            {renderTree.map((child, i) => (
              <li key={`rt-${i}`} className="flex items-center gap-1.5 text-xs">
                <ChevronRight className="h-3 w-3 opacity-40" />
                <span>{child}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {connectedStores && connectedStores.length > 0 && (
        <div className="space-y-1">
          <SectionTitle>Connected Stores</SectionTitle>
          <div className="flex flex-wrap gap-1">
            {connectedStores.map(s => (
              <Badge key={s} variant="outline" className="text-[10px] h-5 border-amber-400 text-amber-400">
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
        <div className="space-y-1">
          <SectionTitle>Reads</SectionTitle>
          <div className="flex flex-wrap gap-1">
            {reads.map(r => (
              <Badge key={r} variant="secondary" className="text-[10px] h-5">
                {r}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {writes && writes.length > 0 && (
        <div className="space-y-1">
          <SectionTitle>Writes</SectionTitle>
          <div className="flex flex-wrap gap-1">
            {writes.map(w => (
              <Badge key={w} variant="outline" className="text-[10px] h-5 border-amber-400 text-amber-400">
                {w}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {flow && flow.length > 0 && (
        <>
          <Separator className="opacity-20" />
          <div className="space-y-1">
            <SectionTitle>State Change Flow</SectionTitle>
            <ul className="space-y-0.5">
              {flow.map((step, i) => (
                <li key={`flow-${i}`} className="flex items-center gap-1.5 text-xs">
                  <span className="opacity-40 text-[10px] font-mono w-4">{i + 1}.</span>
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
        <div className="space-y-1">
          <SectionTitle>Version</SectionTitle>
          <span className="text-sm font-mono">{version}</span>
        </div>
      )}

      {vulnerabilities && vulnerabilities.length > 0 && (
        <div className="space-y-1">
          <SectionTitle>Vulnerabilities</SectionTitle>
          {vulnerabilities.map((v, i) => (
            <div
              key={`vuln-${i}`}
              className={`text-xs px-2 py-1.5 rounded ${
                v.severity === 'critical'
                  ? 'bg-red-500/10 text-red-400'
                  : v.severity === 'high'
                    ? 'bg-orange-500/10 text-orange-400'
                    : 'bg-amber-500/10 text-amber-400'
              }`}
            >
              <span className="font-mono font-medium">{v.cve}</span>
              <span className="mx-1 opacity-50">·</span>
              <span className="opacity-80">{v.severity}</span>
            </div>
          ))}
        </div>
      )}

      {(!vulnerabilities || vulnerabilities.length === 0) && (
        <div className="space-y-1">
          <SectionTitle>Vulnerabilities</SectionTitle>
          <Badge variant="outline" className="text-[10px] h-5 border-green-500 text-green-500">
            ✓ No known CVEs
          </Badge>
        </div>
      )}

      {dependents && dependents.length > 0 && (
        <>
          <Separator className="opacity-20" />
          <div className="space-y-1">
            <SectionTitle>Dependents</SectionTitle>
            <div className="flex flex-wrap gap-1">
              {dependents.map(d => (
                <Badge key={d} variant="secondary" className="text-[10px] h-5">
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
      <div className="space-y-2">
        <SectionTitle>Properties</SectionTitle>
        <div className="grid grid-cols-3 gap-2 text-xs">
          <div className="space-y-0.5">
            <span className="opacity-50">Required</span>
            <div>
              {required ? (
                <Badge variant="outline" className="text-[10px] h-5 border-red-400 text-red-400">Yes</Badge>
              ) : (
                <Badge variant="outline" className="text-[10px] h-5 border-green-500 text-green-500">No</Badge>
              )}
            </div>
          </div>
          <div className="space-y-0.5">
            <span className="opacity-50">Fallback</span>
            <div>
              {hasFallback ? (
                <Badge variant="outline" className="text-[10px] h-5 border-green-500 text-green-500">Yes</Badge>
              ) : (
                <Badge variant="outline" className="text-[10px] h-5 border-amber-400 text-amber-400">None</Badge>
              )}
            </div>
          </div>
          <div className="space-y-0.5">
            <span className="opacity-50">Documented</span>
            <div>
              {documented ? (
                <Badge variant="outline" className="text-[10px] h-5 border-green-500 text-green-500">Yes</Badge>
              ) : (
                <Badge variant="outline" className="text-[10px] h-5 border-slate-400 text-slate-400">No</Badge>
              )}
            </div>
          </div>
        </div>
      </div>

      {files && files.length > 0 && (
        <>
          <Separator className="opacity-20" />
          <div className="space-y-1">
            <SectionTitle>Files</SectionTitle>
            <ul className="space-y-0.5">
              {files.map((f, i) => (
                <li key={`file-${i}`} className="flex items-center gap-1.5 text-xs font-mono">
                  <ChevronRight className="h-3 w-3 opacity-40" />
                  <span>{f}</span>
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

  const variantStyles = useMemo(() => {
    const bg = dark ? 'rgba(26,26,46,0.95)' : 'rgba(255,255,255,0.95)'
    const text = dark ? '#e2e8f0' : '#1a202c'
    const border = dark ? '#2d3748' : '#e2e8f0'
    const mutedText = dark ? '#a0aec0' : '#718096'
    return { bg, text, border, mutedText }
  }, [dark])

  return (
    <div
      className="fixed top-0 right-0 h-full z-50 flex"
      style={{
        transform: isOpen ? 'translateX(0)' : 'translateX(100%)',
        transition: 'transform 300ms ease-out',
        width: 380,
      }}
    >
      {/* Panel body */}
      <div
        className="flex flex-col h-full w-full border-l"
        style={{
          backgroundColor: variantStyles.bg,
          color: variantStyles.text,
          borderColor: variantStyles.border,
          backdropFilter: 'blur(16px)',
          WebkitBackdropFilter: 'blur(16px)',
        }}
      >
        {/* Header */}
        <div
          className="flex items-center gap-2 px-4 py-3 border-b shrink-0"
          style={{ borderColor: variantStyles.border }}
        >
          <span
            className="text-lg leading-none"
            style={{ color: node?.color ?? '#fff' }}
          >
            {node ? shapeIcon(node.type) : ''}
          </span>
          <span className="font-semibold text-sm truncate flex-1">
            {node?.label ?? ''}
          </span>
          <span
            className="text-[10px] font-medium uppercase tracking-wide px-2 py-0.5 rounded-full"
            style={{
              backgroundColor: node ? `${node.color}20` : 'transparent',
              color: node?.color ?? 'transparent',
            }}
          >
            {node ? TYPE_LABELS[node.type] : ''}
          </span>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 shrink-0"
            onClick={onClose}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>

        {/* Scrollable content */}
        {node && (
          <ScrollArea className="flex-1">
            <div className="p-4 space-y-4">
              {/* Location */}
              {node.file && (
                <div className="flex items-center gap-2 text-xs">
                  <MapPin className="h-3.5 w-3.5 shrink-0" style={{ color: variantStyles.mutedText }} />
                  <span className="font-mono truncate" style={{ color: variantStyles.mutedText }}>
                    {node.file}{node.line ? `:${node.line}` : ''}
                  </span>
                </div>
              )}

              {/* Badges */}
              <div className="flex items-center gap-2 flex-wrap">
                <Badge variant="outline" className="text-[10px] h-5 gap-1">
                  <Tag className="h-2.5 w-2.5" />
                  {node.type}
                </Badge>
                <Badge
                  variant="outline"
                  className="text-[10px] h-5"
                  style={{
                    borderColor: node.domain === 'frontend' ? '#b794f4' : '#63b3ed',
                    color: node.domain === 'frontend' ? '#b794f4' : '#63b3ed',
                  }}
                >
                  {node.domain}
                </Badge>
              </div>

              <Separator className="opacity-20" />

              {/* Status */}
              <div className="space-y-1">
                <SectionTitle>Status</SectionTitle>
                <div className="flex items-center gap-2 text-xs">
                  <span
                    className="inline-block h-2 w-2 rounded-full shrink-0"
                    style={{ backgroundColor: STATUS_COLORS[node.status] }}
                  />
                  <span className="capitalize">{node.status.replace('_', ' ')}</span>
                  {refCount > 0 && (
                    <>
                      <span className="opacity-30">·</span>
                      <span style={{ color: variantStyles.mutedText }}>
                        {refCount} ref{refCount !== 1 ? 's' : ''}
                      </span>
                    </>
                  )}
                </div>
              </div>

              <Separator className="opacity-20" />

              {/* Type-specific section */}
              {detail && (
                <TypeSpecificSection node={node} detail={detail} dark={dark} />
              )}

              {/* Code snippet */}
              {detail?.code && (
                <>
                  <Separator className="opacity-20" />
                  <div className="space-y-2">
                    <SectionTitle>Code Snippet</SectionTitle>
                    <div
                      className="rounded-md p-3 overflow-x-auto text-xs font-mono leading-relaxed"
                      style={{
                        backgroundColor: dark ? 'rgba(0,0,0,0.3)' : 'rgba(0,0,0,0.04)',
                        color: variantStyles.text,
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
                  <Separator className="opacity-20" />
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
                          className={`h-7 text-xs gap-1.5 ${
                            action.variant === 'warning'
                              ? 'border-amber-500 text-amber-500 hover:bg-amber-500/10'
                              : action.variant === 'default'
                                ? 'bg-blue-600 hover:bg-blue-700 text-white'
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
