// ============================================================
// CodeLens Neural Workspace — Normalizer
// Converts raw CodeLens CLI JSON output into normalized GraphEvents
// ============================================================

import {
  GraphNode,
  GraphEdge,
  GraphEvent,
  GraphAnimation,
  NEURAL_COLORS,
  NodeType,
  NodeStatus,
  Domain,
  EdgeType,
  EdgeStatus,
  RiskLevel,
  AnimationIntensity,
} from '@/types/neural'

class Normalizer {
  // ─── Main Entry ─────────────────────────────────────────────

  /** Convert any CLI command output to a GraphEvent */
  normalize(commandName: string, rawOutput: Record<string, any>): GraphEvent {
    const normalizer = this.getNormalizer(commandName)
    if (normalizer) {
      return normalizer.call(this, rawOutput)
    }
    // Fallback: generic event for unknown commands
    return this.makeEvent(commandName, [], [], 'pulse', [], 'low', commandName, `Unknown command: ${commandName}`)
  }

  private getNormalizer(name: string): ((output: any) => GraphEvent) | null {
    const map: Record<string, (output: any) => GraphEvent> = {
      scan: this.normalizeScan,
      query: this.normalizeQuery,
      trace: this.normalizeTrace,
      impact: this.normalizeImpact,
      symbols: this.normalizeSymbols,
      list: this.normalizeList,
      search: this.normalizeSearch,
      circular: this.normalizeCircular,
      dataflow: this.normalizeDataflow,
      smell: this.normalizeSmell,
      'side-effect': this.normalizeSideEffect,
      'refactor-safe': this.normalizeRefactorSafe,
      'dead-code': this.normalizeDeadCode,
      'stack-trace': this.normalizeStackTrace,
      'test-map': this.normalizeTestMap,
      'config-drift': this.normalizeConfigDrift,
      'type-infer': this.normalizeTypeInfer,
      ownership: this.normalizeOwnership,
      secrets: this.normalizeSecrets,
      entrypoints: this.normalizeEntrypoints,
      'api-map': this.normalizeApiMap,
      'state-map': this.normalizeStateMap,
      'env-check': this.normalizeEnvCheck,
      'debug-leak': this.normalizeDebugLeak,
      complexity: this.normalizeComplexity,
      'regex-audit': this.normalizeRegexAudit,
      a11y: this.normalizeA11y,
      'vuln-scan': this.normalizeVulnScan,
      'perf-hint': this.normalizePerfHint,
      'css-deep': this.normalizeCssDeep,
      validate: this.normalizeValidate,
      diff: this.normalizeDiff,
      dependents: this.normalizeDependents,
      context: this.normalizeContext,
      outline: this.normalizeOutline,
      'missing-refs': this.normalizeMissingRefs,
      init: this.normalizeInit,
      detect: this.normalizeDetect,
      watch: this.normalizeWatch,
      handbook: this.normalizeHandbook,
      ask: this.normalizeAsk,
    }
    return map[name] ?? null
  }

  // ─── Per-Command Normalizers ──────────────────────────────────

  /** scan: Creates ALL nodes and edges from the registry */
  private normalizeScan(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const edges: GraphEdge[] = []
    const targetIds: string[] = []

    // Frontend classes → class nodes
    const classes = output?.frontend?.classes ?? []
    for (const cls of Array.isArray(classes) ? classes : []) {
      const name: string = cls.name ?? 'unknown'
      const nodeId = this.makeNodeId('class', name)
      const status = this.statusToNodeStatus(cls.status)
      const cssRefs: any[] = cls.css ?? []
      const jsRefs: any[] = cls.js ?? []
      const primaryRef = cssRefs[0] ?? jsRefs[0] ?? {}

      nodes.push({
        id: nodeId,
        label: `.${name}`,
        type: 'class',
        domain: 'frontend',
        status,
        file: primaryRef.path,
        line: primaryRef.line,
        radius: 8 + Math.min((cls.ref_count ?? 0) * 2, 20),
        color: NEURAL_COLORS.class,
        data: { refCount: cls.ref_count ?? 0, cssCount: cssRefs.length, jsCount: jsRefs.length },
      })
      targetIds.push(nodeId)

      // Edges: JS files reference this class
      for (const jsRef of jsRefs) {
        const fileNodeId = this.makeNodeId('file', jsRef.path ?? '')
        edges.push({
          id: this.makeEdgeId(fileNodeId, nodeId, 'references'),
          source: fileNodeId,
          target: nodeId,
          type: 'references',
          weight: 1,
          status: 'active',
        })
      }
    }

    // Frontend IDs → id nodes
    const ids = output?.frontend?.ids ?? []
    for (const idEntry of Array.isArray(ids) ? ids : []) {
      const name: string = idEntry.name ?? 'unknown'
      const nodeId = this.makeNodeId('id', name)
      const status = this.statusToNodeStatus(idEntry.status)
      const htmlRefs: any[] = idEntry.defined_in_html ?? []
      const primaryRef = htmlRefs[0] ?? {}

      nodes.push({
        id: nodeId,
        label: `#${name}`,
        type: 'id',
        domain: 'frontend',
        status,
        file: primaryRef.path,
        line: primaryRef.line,
        radius: 7 + Math.min((idEntry.ref_count ?? 0) * 2, 18),
        color: NEURAL_COLORS.id,
        data: { refCount: idEntry.ref_count ?? 0 },
      })
      targetIds.push(nodeId)
    }

    // Backend nodes → function nodes
    const backendNodes = output?.backend?.nodes ?? []
    for (const bNode of Array.isArray(backendNodes) ? backendNodes : []) {
      const fn: string = bNode.fn ?? 'unknown'
      const nodeId = bNode.id ?? this.makeNodeId('function', fn, bNode.file, bNode.line)
      const status = this.statusToNodeStatus(bNode.status)

      let nodeType: NodeType = 'function'
      if (bNode.component) nodeType = 'component'
      if (bNode.impl_for) nodeType = 'function'

      nodes.push({
        id: nodeId,
        label: fn,
        type: nodeType,
        domain: 'backend',
        status,
        file: bNode.file,
        line: bNode.line,
        radius: 6 + Math.min((bNode.ref_count ?? 0) * 2, 22),
        color: nodeType === 'component' ? NEURAL_COLORS.component : NEURAL_COLORS.function,
        data: {
          async: bNode.async ?? false,
          implFor: bNode.impl_for ?? null,
          duplicateDefine: bNode.duplicate_define ?? false,
        },
      })
      targetIds.push(nodeId)
    }

    // Backend edges
    const backendEdges = output?.backend?.edges ?? []
    for (const bEdge of Array.isArray(backendEdges) ? backendEdges : []) {
      const sourceId: string = bEdge.from ?? ''
      const targetId: string = bEdge.to ?? ''
      if (!sourceId || !targetId) continue

      const edgeType: EdgeType = this.mapEdgeType(bEdge.type ?? bEdge.edge_type ?? bEdge.relation)
      edges.push({
        id: this.makeEdgeId(sourceId, targetId, edgeType),
        source: sourceId,
        target: targetId,
        type: edgeType,
        weight: 1,
        status: 'active',
      })
    }

    return this.makeEvent(
      'scan', nodes, edges, 'ripple', targetIds, 'low',
      'scan', `Scanned ${nodes.length} nodes, ${edges.length} edges`
    )
  }

  /** query: Highlights existing nodes — doesn't create new ones */
  private normalizeQuery(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const edges: GraphEdge[] = []
    const targetIds: string[] = []

    if (!output?.found) {
      return this.makeEvent('query', [], [], 'pulse', [], 'low', 'query', `Not found: ${output?.query ?? 'unknown'}`)
    }

    const domain: Domain = output.domain === 'frontend' ? 'frontend' : 'backend'
    const name: string = output.name ?? output.node?.fn ?? 'unknown'

    // Primary queried node
    if (output.type === 'class' || output.type === 'id') {
      const nodeType: NodeType = output.type === 'class' ? 'class' : 'id'
      const nodeId = this.makeNodeId(nodeType, name)
      const status = this.statusToNodeStatus(output.status)

      nodes.push({
        id: nodeId,
        label: nodeType === 'class' ? `.${name}` : `#${name}`,
        type: nodeType,
        domain: 'frontend',
        status,
        radius: 14,
        color: nodeType === 'class' ? NEURAL_COLORS.class : NEURAL_COLORS.id,
        data: { refCount: output.ref_count ?? 0 },
      })
      targetIds.push(nodeId)

      // CSS reference edges
      const cssRefs: any[] = output.css ?? []
      for (const ref of cssRefs) {
        const refNodeId = this.makeNodeId('file', ref.path ?? '')
        edges.push({
          id: this.makeEdgeId(refNodeId, nodeId, 'references'),
          source: refNodeId,
          target: nodeId,
          type: 'references',
          weight: 1,
          status: 'active',
        })
        targetIds.push(refNodeId)
      }

      // JS reference edges
      const jsRefs: any[] = output.js ?? []
      for (const ref of jsRefs) {
        const refNodeId = this.makeNodeId('file', ref.path ?? '')
        edges.push({
          id: this.makeEdgeId(refNodeId, nodeId, 'references'),
          source: refNodeId,
          target: nodeId,
          type: 'references',
          weight: 1,
          status: 'active',
        })
        targetIds.push(refNodeId)
      }
    } else if (output.type === 'function') {
      const nodeData = output.node ?? {}
      const nodeId = nodeData.id ?? this.makeNodeId('function', name, nodeData.file, nodeData.line)
      const status = this.statusToNodeStatus(nodeData.status)

      nodes.push({
        id: nodeId,
        label: name,
        type: nodeData.component ? 'component' : 'function',
        domain: 'backend',
        status,
        file: nodeData.file,
        line: nodeData.line,
        radius: 14,
        color: nodeData.component ? NEURAL_COLORS.component : NEURAL_COLORS.function,
        data: { async: nodeData.async ?? false, implFor: nodeData.impl_for ?? null },
      })
      targetIds.push(nodeId)

      // Caller edges
      const callers: any[] = output.callers ?? []
      for (const caller of callers) {
        const callerId = this.makeNodeId('function', caller.fn ?? '', caller.file, caller.line)
        edges.push({
          id: this.makeEdgeId(callerId, nodeId, 'calls'),
          source: callerId,
          target: nodeId,
          type: 'calls',
          weight: 1,
          status: 'active',
        })
        targetIds.push(callerId)
      }

      // Callee edges
      const callees: any[] = output.callees ?? []
      for (const callee of callees) {
        const calleeId = this.makeNodeId('function', callee.fn ?? '', callee.file, callee.line)
        edges.push({
          id: this.makeEdgeId(nodeId, calleeId, 'calls'),
          source: nodeId,
          target: calleeId,
          type: 'calls',
          weight: 1,
          status: 'active',
        })
        targetIds.push(calleeId)
      }
    }

    return this.makeEvent('query', nodes, edges, 'pulse', targetIds, 'low', 'query', `Queried ${name}`)
  }

  /** trace: Returns the call chain with flow animation */
  private normalizeTrace(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const edges: GraphEdge[] = []
    const targetIds: string[] = []
    const direction: 'up' | 'down' | 'both' = output?.direction ?? 'up'

    const upChains: any[] = output?.chains?.up ?? []
    const downChains: any[] = output?.chains?.down ?? []

    // Process up chain (callers)
    for (const entry of upChains) {
      const nodeId = entry.node_id ?? this.makeNodeId('function', entry.fn ?? '', entry.file, entry.line)
      const status = this.statusToNodeStatus(entry.status ?? 'active')

      if (!nodes.find(n => n.id === nodeId)) {
        nodes.push({
          id: nodeId,
          label: entry.fn ?? 'unknown',
          type: 'function',
          domain: 'backend',
          status,
          file: entry.file,
          line: entry.line,
          radius: entry.depth === 0 ? 14 : 8,
          color: NEURAL_COLORS.function,
          data: { depth: entry.depth ?? 0, cyclic: entry.cyclic ?? false },
        })
      }
      targetIds.push(nodeId)
    }

    // Create edges between consecutive up-chain entries
    for (let i = 1; i < upChains.length; i++) {
      const from = upChains[i].node_id ?? this.makeNodeId('function', upChains[i].fn ?? '', upChains[i].file, upChains[i].line)
      const to = upChains[i - 1].node_id ?? this.makeNodeId('function', upChains[i - 1].fn ?? '', upChains[i - 1].file, upChains[i - 1].line)
      if (from !== to) {
        edges.push({
          id: this.makeEdgeId(from, to, 'calls'),
          source: from,
          target: to,
          type: 'calls',
          weight: 1,
          status: upChains[i].cyclic ? 'warning' : 'active',
        })
      }
    }

    // Process down chain (callees)
    for (const entry of downChains) {
      const nodeId = entry.node_id ?? this.makeNodeId('function', entry.fn ?? '', entry.file, entry.line)
      const status = this.statusToNodeStatus(entry.status ?? 'active')

      if (!nodes.find(n => n.id === nodeId)) {
        nodes.push({
          id: nodeId,
          label: entry.fn ?? 'unknown',
          type: 'function',
          domain: 'backend',
          status,
          file: entry.file,
          line: entry.line,
          radius: entry.depth === 0 ? 14 : 8,
          color: NEURAL_COLORS.function,
          data: { depth: entry.depth ?? 0, cyclic: entry.cyclic ?? false, resolved: entry.resolved ?? true },
        })
      }
      targetIds.push(nodeId)
    }

    // Create edges between consecutive down-chain entries
    for (let i = 1; i < downChains.length; i++) {
      const from = downChains[i - 1].node_id ?? this.makeNodeId('function', downChains[i - 1].fn ?? '', downChains[i - 1].file, downChains[i - 1].line)
      const to = downChains[i].node_id ?? this.makeNodeId('function', downChains[i].fn ?? '', downChains[i].file, downChains[i].line)
      if (from !== to) {
        edges.push({
          id: this.makeEdgeId(from, to, 'calls'),
          source: from,
          target: to,
          type: 'calls',
          weight: 1,
          status: downChains[i].cyclic ? 'warning' : 'active',
        })
      }
    }

    const animDirection = direction === 'up' ? 'down' : direction === 'down' ? 'up' : 'both'
    const risk: RiskLevel = (upChains.some(c => c.cyclic) || downChains.some(c => c.cyclic)) ? 'high' : 'low'

    return this.makeEvent(
      'trace', nodes, edges, 'flow', targetIds, risk,
      'trace', `Traced ${output?.symbol ?? 'unknown'}: ${upChains.length} callers, ${downChains.length} callees`,
      animDirection
    )
  }

  /** impact: Returns affected nodes with alarm animation */
  private normalizeImpact(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const edges: GraphEdge[] = []
    const targetIds: string[] = []

    const risk: RiskLevel = this.mapRiskLevel(output?.risk)
    const directItems: any[] = output?.affected?.direct ?? []
    const indirectItems: any[] = output?.affected?.indirect ?? []

    // Direct dependents — high intensity
    for (const item of directItems) {
      const nodeId = this.makeNodeId(
        this.mapNodeType(item.type ?? 'function', item.domain ?? 'backend'),
        item.name ?? 'unknown',
        item.file,
        item.line,
      )
      const nodeStatus: NodeStatus = item.risk === 'critical' ? 'critical' : item.risk === 'high' ? 'warning' : 'active'

      nodes.push({
        id: nodeId,
        label: item.name ?? 'unknown',
        type: this.mapNodeType(item.type ?? 'function', item.domain ?? 'backend'),
        domain: (item.domain === 'frontend' ? 'frontend' : 'backend') as Domain,
        status: nodeStatus,
        file: item.file,
        line: item.line,
        radius: 12,
        color: nodeStatus === 'critical' ? NEURAL_COLORS.critical : nodeStatus === 'warning' ? NEURAL_COLORS.warning : NEURAL_COLORS.function,
        data: { relation: item.relation ?? '', depth: 1 },
      })
      targetIds.push(nodeId)
    }

    // Indirect dependents — medium intensity
    for (const item of indirectItems) {
      const nodeId = this.makeNodeId(
        this.mapNodeType(item.type ?? 'function', item.domain ?? 'backend'),
        item.name ?? 'unknown',
        item.file,
        item.line,
      )
      const nodeStatus: NodeStatus = item.risk === 'critical' ? 'critical' : item.risk === 'high' ? 'warning' : 'active'

      if (!nodes.find(n => n.id === nodeId)) {
        nodes.push({
          id: nodeId,
          label: item.name ?? 'unknown',
          type: this.mapNodeType(item.type ?? 'function', item.domain ?? 'backend'),
          domain: (item.domain === 'frontend' ? 'frontend' : 'backend') as Domain,
          status: nodeStatus,
          file: item.file,
          line: item.line,
          radius: 9,
          color: nodeStatus === 'critical' ? NEURAL_COLORS.critical : nodeStatus === 'warning' ? NEURAL_COLORS.warning : NEURAL_COLORS.function,
          data: { relation: item.relation ?? '', depth: item.depth ?? 2 },
        })
      }
      targetIds.push(nodeId)
    }

    // Connect direct → source, indirect → direct
    const sourceName = output?.symbol ?? 'unknown'
    const sourceId = this.makeNodeId('function', sourceName)
    for (const item of directItems) {
      const itemId = this.makeNodeId(this.mapNodeType(item.type ?? 'function', item.domain ?? 'backend'), item.name ?? 'unknown', item.file, item.line)
      edges.push({
        id: this.makeEdgeId(sourceId, itemId, 'depends_on'),
        source: sourceId,
        target: itemId,
        type: 'depends_on',
        weight: 2,
        status: 'danger',
      })
    }

    const intensity: AnimationIntensity = directItems.length > 5 || risk === 'critical' ? 'critical' : risk === 'high' ? 'high' : 'medium'

    return this.makeEvent(
      'impact', nodes, edges, 'alarm', targetIds, risk,
      'impact', `Impact on ${sourceName}: ${directItems.length} direct, ${indirectItems.length} indirect`,
      undefined, intensity
    )
  }

  /** symbols: Returns matching nodes with flash animation */
  private normalizeSymbols(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const targetIds: string[] = []
    const results: any[] = output?.results ?? []

    for (const result of results) {
      const nodeType = this.mapNodeType(result.type ?? 'function', result.domain ?? 'backend')
      const domain: Domain = result.domain === 'frontend' ? 'frontend' : 'backend'
      const nodeId = this.makeNodeId(nodeType, result.name ?? 'unknown')
      const status = this.statusToNodeStatus(result.status ?? 'active')

      nodes.push({
        id: nodeId,
        label: result.name ?? 'unknown',
        type: nodeType,
        domain,
        status,
        file: result.defined_in?.split(':')[0],
        line: result.defined_in ? parseInt(result.defined_in.split(':')[1]) : undefined,
        radius: 10,
        color: NEURAL_COLORS[nodeType as keyof typeof NEURAL_COLORS] ?? NEURAL_COLORS.function,
        data: { refCount: result.ref_count ?? 0 },
      })
      targetIds.push(nodeId)
    }

    return this.makeEvent(
      'symbols', nodes, [], 'flash', targetIds, 'low',
      'symbols', `Found ${results.length} symbol(s) matching "${output?.query ?? ''}"`
    )
  }

  /** list: Returns listed nodes with pulse animation */
  private normalizeList(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const targetIds: string[] = []
    const results: any[] = output?.results ?? []

    for (const result of results) {
      const nodeType = this.mapNodeType(result.type ?? 'function', output?.domain ?? 'all')
      const domain: Domain = result.type === 'class' || result.type === 'id' ? 'frontend' : 'backend'
      const nodeId = this.makeNodeId(nodeType, result.name ?? 'unknown')
      const status = this.statusToNodeStatus(result.status ?? 'active')

      nodes.push({
        id: nodeId,
        label: result.type === 'class' ? `.${result.name}` : result.type === 'id' ? `#${result.name}` : result.name ?? 'unknown',
        type: nodeType,
        domain,
        status,
        file: result.defined_in?.split(':')[0],
        line: result.defined_in ? parseInt(result.defined_in.split(':')[1]) : undefined,
        radius: 8,
        color: NEURAL_COLORS[nodeType as keyof typeof NEURAL_COLORS] ?? NEURAL_COLORS.function,
        data: { refCount: result.ref_count ?? 0 },
      })
      targetIds.push(nodeId)
    }

    return this.makeEvent(
      'list', nodes, [], 'pulse', targetIds, 'low',
      'list', `Listed ${output?.count ?? results.length} items (${output?.domain ?? 'all'}, ${output?.filter ?? 'all'})`
    )
  }

  /** search: Returns matching nodes with flash animation */
  private normalizeSearch(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const targetIds: string[] = []
    const results: any[] = output?.results ?? []

    for (const result of results) {
      const nodeId = this.makeNodeId('file', result.file ?? '', undefined, result.line)
      const domain: Domain = this.inferDomain(result.file ?? '')

      nodes.push({
        id: nodeId,
        label: result.file ?? 'unknown',
        type: 'file',
        domain,
        status: 'active',
        file: result.file,
        line: result.line,
        radius: 9,
        color: NEURAL_COLORS.file,
        data: { match: result.match ?? '', lineText: result.line_text ?? '' },
      })
      targetIds.push(nodeId)
    }

    return this.makeEvent(
      'search', nodes, [], 'flash', targetIds, 'low',
      'search', `Search found ${output?.total ?? results.length} results for "${output?.pattern ?? ''}"`
    )
  }

  /** circular: Returns circular dependency chains with alarm animation */
  private normalizeCircular(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const edges: GraphEdge[] = []
    const targetIds: string[] = []
    const cycles: any[] = output?.cycles ?? []

    for (const cycle of cycles) {
      const chain: string[] = cycle.chain ?? cycle.nodes ?? []
      for (let i = 0; i < chain.length; i++) {
        const nodeId = chain[i]
        if (!nodes.find(n => n.id === nodeId)) {
          nodes.push({
            id: nodeId,
            label: nodeId.split(':').pop() ?? nodeId,
            type: 'file',
            domain: 'backend',
            status: 'warning',
            radius: 10,
            color: NEURAL_COLORS.warning,
            data: { cycleLength: chain.length },
          })
        }
        targetIds.push(nodeId)

        // Create edge to next node in cycle
        if (i < chain.length - 1) {
          edges.push({
            id: this.makeEdgeId(nodeId, chain[i + 1], 'imports'),
            source: nodeId,
            target: chain[i + 1],
            type: 'imports',
            weight: 2,
            status: 'danger',
          })
        }
      }
    }

    const risk: RiskLevel = cycles.length > 0 ? 'high' : 'low'

    return this.makeEvent(
      'circular', nodes, edges, 'alarm', targetIds, risk,
      'circular', `Found ${cycles.length} circular dependenc${cycles.length === 1 ? 'y' : 'ies'}`
    )
  }

  /** dataflow: Returns data flow source→sink with flow animation */
  private normalizeDataflow(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const edges: GraphEdge[] = []
    const targetIds: string[] = []
    const flows: any[] = output?.flows ?? []

    for (const flow of flows) {
      const sourceId = this.makeNodeId('function', flow.source?.fn ?? flow.source?.name ?? 'source', flow.source?.file, flow.source?.line)
      const sinkId = this.makeNodeId('function', flow.sink?.fn ?? flow.sink?.name ?? 'sink', flow.sink?.file, flow.sink?.line)

      if (!nodes.find(n => n.id === sourceId)) {
        nodes.push({
          id: sourceId,
          label: flow.source?.fn ?? flow.source?.name ?? 'source',
          type: 'function',
          domain: 'backend',
          status: flow.source?.tainted ? 'warning' : 'active',
          file: flow.source?.file,
          line: flow.source?.line,
          radius: 11,
          color: flow.source?.tainted ? NEURAL_COLORS.warning : NEURAL_COLORS.function,
          data: { kind: 'source', tainted: flow.source?.tainted ?? false },
        })
      }
      targetIds.push(sourceId)

      if (!nodes.find(n => n.id === sinkId)) {
        nodes.push({
          id: sinkId,
          label: flow.sink?.fn ?? flow.sink?.name ?? 'sink',
          type: 'function',
          domain: 'backend',
          status: flow.sink?.dangerous ? 'critical' : 'active',
          file: flow.sink?.file,
          line: flow.sink?.line,
          radius: 11,
          color: flow.sink?.dangerous ? NEURAL_COLORS.critical : NEURAL_COLORS.function,
          data: { kind: 'sink', dangerous: flow.sink?.dangerous ?? false },
        })
      }
      targetIds.push(sinkId)

      edges.push({
        id: this.makeEdgeId(sourceId, sinkId, 'taints'),
        source: sourceId,
        target: sinkId,
        type: 'taints',
        weight: 2,
        status: flow.sink?.dangerous ? 'danger' : 'active',
      })
    }

    const risk: RiskLevel = flows.some(f => f.sink?.dangerous) ? 'critical' : flows.length > 0 ? 'medium' : 'low'

    return this.makeEvent(
      'dataflow', nodes, edges, 'flow', targetIds, risk,
      'dataflow', `Traced ${flows.length} data flow path(s)`,
      'down'
    )
  }

  /** smell: Overlay badges — returns existing nodes with updated status */
  private normalizeSmell(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const targetIds: string[] = []
    const byCategory: Record<string, any[]> = output?.by_category ?? {}

    for (const [_category, smells] of Object.entries(byCategory)) {
      for (const smell of Array.isArray(smells) ? smells : []) {
        const name: string = smell.fn ?? smell.class ?? smell.file ?? 'unknown'
        const nodeType: NodeType = smell.class ? 'class' : 'function'
        const nodeId = this.makeNodeId(nodeType, name, smell.file, smell.line)
        const status: NodeStatus = smell.severity === 'critical' ? 'warning' : smell.severity === 'warning' ? 'warning' : 'active'

        nodes.push({
          id: nodeId,
          label: name,
          type: nodeType,
          domain: this.inferDomain(smell.file ?? ''),
          status,
          file: smell.file,
          line: smell.line,
          radius: 9,
          color: status === 'warning' ? NEURAL_COLORS.warning : (nodeType === 'class' ? NEURAL_COLORS.class : NEURAL_COLORS.function),
          data: { category: _category, severity: smell.severity, message: smell.message },
        })
        targetIds.push(nodeId)
      }
    }

    const healthScore = output?.stats?.health_score ?? 100
    const risk: RiskLevel = healthScore < 50 ? 'high' : healthScore < 75 ? 'medium' : 'low'

    return this.makeEvent(
      'smell', nodes, [], 'pulse', targetIds, risk,
      'smell', `Detected ${output?.stats?.total_smells ?? 0} smell(s), health score: ${healthScore}`
    )
  }

  /** side-effect: Returns function with side effect analysis */
  private normalizeSideEffect(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const edges: GraphEdge[] = []
    const targetIds: string[] = []
    const sideEffects: string[] = output?.side_effects ?? []
    const fn = output?.fn ?? output?.function ?? 'unknown'
    const purity: number = output?.purity ?? 1

    const nodeId = this.makeNodeId('function', fn, output?.file, output?.line)
    const status: NodeStatus = purity < 0.3 ? 'warning' : 'active'

    nodes.push({
      id: nodeId,
      label: fn,
      type: 'function',
      domain: 'backend',
      status,
      file: output?.file,
      line: output?.line,
      radius: 12,
      color: status === 'warning' ? NEURAL_COLORS.warning : NEURAL_COLORS.function,
      data: { purity, sideEffects },
    })
    targetIds.push(nodeId)

    for (const effect of sideEffects) {
      const effectId = this.makeNodeId('function', effect)
      edges.push({
        id: this.makeEdgeId(nodeId, effectId, 'writes'),
        source: nodeId,
        target: effectId,
        type: 'writes',
        weight: 1,
        status: 'warning',
      })
      targetIds.push(effectId)
    }

    const risk: RiskLevel = purity < 0.3 ? 'high' : purity < 0.7 ? 'medium' : 'low'

    return this.makeEvent(
      'side-effect', nodes, edges, 'pulse', targetIds, risk,
      'side-effect', `${fn} purity: ${purity.toFixed(2)}, ${sideEffects.length} side effect(s)`
    )
  }

  /** refactor-safe: Returns nodes that would be affected by refactoring */
  private normalizeRefactorSafe(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const edges: GraphEdge[] = []
    const targetIds: string[] = []
    const safe: boolean = output?.safe ?? true
    const risks: any[] = output?.risks ?? output?.warnings ?? []
    const name: string = output?.name ?? output?.symbol ?? 'unknown'

    const nodeId = this.makeNodeId('function', name)
    nodes.push({
      id: nodeId,
      label: name,
      type: 'function',
      domain: 'backend',
      status: safe ? 'safe' : 'warning',
      radius: 12,
      color: safe ? NEURAL_COLORS.safe : NEURAL_COLORS.warning,
      data: { safe, riskCount: risks.length },
    })
    targetIds.push(nodeId)

    for (const risk of risks) {
      const riskId = this.makeNodeId('function', risk.name ?? risk.fn ?? 'risk', risk.file, risk.line)
      nodes.push({
        id: riskId,
        label: risk.name ?? risk.fn ?? 'risk',
        type: 'function',
        domain: 'backend',
        status: 'warning',
        file: risk.file,
        line: risk.line,
        radius: 9,
        color: NEURAL_COLORS.warning,
        data: { reason: risk.reason ?? risk.message ?? '' },
      })
      targetIds.push(riskId)

      edges.push({
        id: this.makeEdgeId(nodeId, riskId, 'depends_on'),
        source: nodeId,
        target: riskId,
        type: 'depends_on',
        weight: 2,
        status: 'warning',
      })
    }

    return this.makeEvent(
      'refactor-safe', nodes, edges, 'pulse', targetIds, safe ? 'low' : 'high',
      'refactor-safe', `Refactor ${name}: ${safe ? 'SAFE' : 'UNSAFE'} (${risks.length} risk(s))`
    )
  }

  /** dead-code: Returns dead nodes with death animation */
  private normalizeDeadCode(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const targetIds: string[] = []
    const results: Record<string, any[]> = output?.results ?? {}
    const allDead: any[] = []

    for (const [_category, items] of Object.entries(results)) {
      for (const item of Array.isArray(items) ? items : []) {
        allDead.push(item)
        const name: string = item.fn ?? item.class ?? item.variable ?? item.name ?? 'unknown'
        const nodeType: NodeType = item.class ? 'class' : item.variable ? 'variable' : 'function'
        const domain: Domain = item.class || item.variable ? 'frontend' : 'backend'
        const nodeId = this.makeNodeId(nodeType, name, item.file, item.line)

        nodes.push({
          id: nodeId,
          label: name,
          type: nodeType,
          domain,
          status: 'dead',
          file: item.file,
          line: item.line,
          radius: 7,
          color: NEURAL_COLORS.dead,
          data: { category: _category, severity: item.severity ?? 'info', message: item.message ?? '' },
        })
        targetIds.push(nodeId)
      }
    }

    const totalDead = output?.stats?.total_dead_code ?? allDead.length
    const risk: RiskLevel = totalDead > 20 ? 'high' : totalDead > 5 ? 'medium' : 'low'

    return this.makeEvent(
      'dead-code', nodes, [], 'death', targetIds, risk,
      'dead-code', `Found ${totalDead} dead code item(s)`
    )
  }

  /** stack-trace: Returns error propagation chain with alarm animation */
  private normalizeStackTrace(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const edges: GraphEdge[] = []
    const targetIds: string[] = []
    const chain: any[] = output?.chain ?? output?.propagation ?? []

    for (let i = 0; i < chain.length; i++) {
      const entry = chain[i]
      const nodeId = entry.node_id ?? this.makeNodeId('function', entry.fn ?? 'unknown', entry.file, entry.line)

      nodes.push({
        id: nodeId,
        label: entry.fn ?? entry.function ?? 'unknown',
        type: 'function',
        domain: 'backend',
        status: entry.can_throw ? 'warning' : 'active',
        file: entry.file,
        line: entry.line,
        radius: i === 0 ? 14 : 9,
        color: entry.can_throw ? NEURAL_COLORS.warning : NEURAL_COLORS.function,
        data: { depth: i, errorType: entry.error_type ?? '', canThrow: entry.can_throw ?? false },
      })
      targetIds.push(nodeId)

      if (i > 0) {
        const prevId = chain[i - 1].node_id ?? this.makeNodeId('function', chain[i - 1].fn ?? 'unknown', chain[i - 1].file, chain[i - 1].line)
        edges.push({
          id: this.makeEdgeId(prevId, nodeId, 'calls'),
          source: prevId,
          target: nodeId,
          type: 'calls',
          weight: 2,
          status: 'danger',
        })
      }
    }

    return this.makeEvent(
      'stack-trace', nodes, edges, 'flow', targetIds, 'high',
      'stack-trace', `Error propagation: ${chain.length} frame(s)`,
      'up'
    )
  }

  /** test-map: Returns test coverage data with test nodes and tests edges */
  private normalizeTestMap(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const edges: GraphEdge[] = []
    const targetIds: string[] = []
    const coverage: any[] = output?.coverage ?? output?.mappings ?? []

    for (const entry of coverage) {
      const fn: string = entry.fn ?? entry.function ?? entry.symbol ?? 'unknown'
      const symbolId = this.makeNodeId('function', fn, entry.file, entry.line)
      const covered: boolean = entry.covered ?? entry.has_test ?? entry.tested ?? false

      // Create the function/symbol node
      nodes.push({
        id: symbolId,
        label: fn,
        type: 'function',
        domain: 'backend',
        status: covered ? 'safe' : 'untested',
        file: entry.file,
        line: entry.line,
        radius: 9,
        color: covered ? NEURAL_COLORS.safe : NEURAL_COLORS.untested,
        data: { covered, testFiles: entry.test_files ?? (entry.test_file ? [entry.test_file] : []) },
      })
      targetIds.push(symbolId)

      // Create test nodes and tests edges for covered symbols
      const testFiles: string[] = entry.test_files ?? (entry.test_file ? [entry.test_file] : [])
      for (const testFile of testFiles) {
        const testId = this.makeNodeId('test', testFile)
        if (!nodes.find(n => n.id === testId)) {
          nodes.push({
            id: testId,
            label: testFile.split('/').pop() ?? testFile,
            type: 'test',
            domain: 'backend',
            status: 'active',
            file: testFile,
            radius: 8,
            color: NEURAL_COLORS.test,
            data: { testedSymbol: fn },
          })
        }
        targetIds.push(testId)

        // tests edge: test node → tested symbol
        edges.push({
          id: this.makeEdgeId(testId, symbolId, 'tests'),
          source: testId,
          target: symbolId,
          type: 'tests',
          weight: 1,
          status: 'active',
        })
      }
    }

    const uncovered = coverage.filter(c => !(c.covered ?? c.has_test)).length
    const risk: RiskLevel = uncovered > 10 ? 'high' : uncovered > 3 ? 'medium' : 'low'

    return this.makeEvent(
      'test-map', nodes, edges, 'pulse', targetIds, risk,
      'test-map', `Test coverage: ${coverage.length - uncovered}/${coverage.length} functions covered`
    )
  }

  /** config-drift: Returns dependency drift data */
  private normalizeConfigDrift(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const targetIds: string[] = []
    const drift: any[] = output?.drift ?? output?.findings ?? []

    for (const entry of drift) {
      const name: string = entry.package ?? entry.name ?? 'unknown'
      const nodeId = this.makeNodeId('package', name)
      const status: NodeStatus = entry.severity === 'critical' ? 'critical' : entry.severity === 'high' ? 'warning' : 'active'

      nodes.push({
        id: nodeId,
        label: name,
        type: 'package',
        domain: 'backend',
        status,
        radius: 10,
        color: status === 'critical' ? NEURAL_COLORS.critical : status === 'warning' ? NEURAL_COLORS.warning : NEURAL_COLORS.package,
        data: {
          installed: entry.installed ?? '',
          latest: entry.latest ?? '',
          drift: entry.drift ?? entry.major_versions_behind ?? 0,
          severity: entry.severity ?? '',
        },
      })
      targetIds.push(nodeId)
    }

    const risk: RiskLevel = drift.some(d => d.severity === 'critical') ? 'critical'
      : drift.some(d => d.severity === 'high') ? 'high'
      : drift.length > 0 ? 'medium' : 'low'

    return this.makeEvent(
      'config-drift', nodes, [], 'pulse', targetIds, risk,
      'config-drift', `Dependency drift: ${drift.length} package(s) need update`
    )
  }

  /** type-infer: Returns type inference results */
  private normalizeTypeInfer(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const targetIds: string[] = []
    const inferences: any[] = output?.inferences ?? output?.results ?? []

    for (const entry of inferences) {
      const name: string = entry.name ?? entry.fn ?? 'unknown'
      const nodeId = this.makeNodeId('function', name, entry.file, entry.line)
      const status: NodeStatus = entry.conflict ? 'warning' : 'active'

      nodes.push({
        id: nodeId,
        label: name,
        type: 'function',
        domain: 'backend',
        status,
        file: entry.file,
        line: entry.line,
        radius: 9,
        color: status === 'warning' ? NEURAL_COLORS.warning : NEURAL_COLORS.function,
        data: { inferredType: entry.inferred_type ?? entry.type ?? '', confidence: entry.confidence ?? 1, conflict: entry.conflict ?? false },
      })
      targetIds.push(nodeId)
    }

    return this.makeEvent(
      'type-infer', nodes, [], 'pulse', targetIds, 'low',
      'type-infer', `Inferred types for ${inferences.length} symbol(s)`
    )
  }

  /** ownership: Returns code ownership data from git blame */
  private normalizeOwnership(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const edges: GraphEdge[] = []
    const targetIds: string[] = []
    const owners: any[] = output?.owners ?? output?.results ?? []

    for (const entry of owners) {
      const file: string = entry.file ?? entry.path ?? 'unknown'
      const nodeId = this.makeNodeId('file', file)

      nodes.push({
        id: nodeId,
        label: file.split('/').pop() ?? file,
        type: 'file',
        domain: this.inferDomain(file),
        status: 'active',
        file,
        radius: 10,
        color: NEURAL_COLORS.file,
        data: { owner: entry.owner ?? entry.author ?? '', commits: entry.commits ?? 0, lines: entry.lines ?? 0 },
      })
      targetIds.push(nodeId)
    }

    return this.makeEvent(
      'ownership', nodes, edges, 'pulse', targetIds, 'low',
      'ownership', `Code ownership: ${owners.length} file(s) analyzed`
    )
  }

  /** secrets: Creates secret nodes for hardcoded secrets, env_var for env vars, alarm animation */
  private normalizeSecrets(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const edges: GraphEdge[] = []
    const targetIds: string[] = []
    const findings: any[] = output?.findings ?? []

    for (const finding of findings) {
      const name: string = finding.env_key ?? finding.category ?? finding.match ?? 'secret'
      // Use 'secret' type for hardcoded secrets (not env var references)
      const isHardcodedSecret = finding.category === 'api_key' || finding.category === 'aws_key' || finding.category === 'secret' || finding.type === 'hardcoded'
      const nodeType: NodeType = isHardcodedSecret ? 'secret' : 'env_var'
      const nodeId = this.makeNodeId(nodeType, name, finding.file, finding.line)
      const status: NodeStatus = finding.severity === 'critical' ? 'critical' : 'warning'

      nodes.push({
        id: nodeId,
        label: name,
        type: nodeType,
        domain: 'backend',
        status,
        file: finding.file,
        line: finding.line,
        radius: 12,
        color: nodeType === 'secret' ? NEURAL_COLORS.secret : (status === 'critical' ? NEURAL_COLORS.critical : NEURAL_COLORS.warning),
        data: {
          category: finding.category ?? '',
          severity: finding.severity ?? 'high',
          match: finding.match ?? '',
          type: finding.type ?? '',
        },
      })
      targetIds.push(nodeId)
    }

    // Exposed .env files
    const exposed: string[] = output?.env_exposed ?? []
    for (const envPath of exposed) {
      const nodeId = this.makeNodeId('file', envPath)
      nodes.push({
        id: nodeId,
        label: envPath.split('/').pop() ?? envPath,
        type: 'file',
        domain: 'backend',
        status: 'critical',
        file: envPath,
        radius: 14,
        color: NEURAL_COLORS.critical,
        data: { exposed: true },
      })
      targetIds.push(nodeId)
    }

    const risk: RiskLevel = this.mapRiskLevel(output?.risk)

    return this.makeEvent(
      'secrets', nodes, edges, 'alarm', targetIds, risk,
      'secrets', `Found ${findings.length} secret(s), ${exposed.length} exposed .env file(s)`,
      undefined, 'critical'
    )
  }

  /** entrypoints: Maps execution entry points */
  private normalizeEntrypoints(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const edges: GraphEdge[] = []
    const targetIds: string[] = []
    const entrypoints: any[] = output?.entrypoints ?? output?.results ?? []

    for (const entry of entrypoints) {
      const name: string = entry.fn ?? entry.name ?? entry.handler ?? 'entrypoint'
      const nodeType: NodeType = entry.type === 'api_route' ? 'route' : 'function'
      const nodeId = this.makeNodeId(nodeType, name, entry.file, entry.line)

      nodes.push({
        id: nodeId,
        label: name,
        type: nodeType,
        domain: entry.type === 'api_route' ? 'backend' : this.inferDomain(entry.file ?? ''),
        status: 'active',
        file: entry.file,
        line: entry.line,
        radius: 14,
        color: nodeType === 'route' ? NEURAL_COLORS.route : NEURAL_COLORS.function,
        data: { entryType: entry.type ?? '', method: entry.method ?? '' },
      })
      targetIds.push(nodeId)
    }

    return this.makeEvent(
      'entrypoints', nodes, edges, 'pulse', targetIds, 'low',
      'entrypoints', `Found ${entrypoints.length} entry point(s)`
    )
  }

  /** api-map: Maps REST/GraphQL routes to handlers */
  private normalizeApiMap(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const edges: GraphEdge[] = []
    const targetIds: string[] = []
    const routes: any[] = output?.routes ?? output?.results ?? []

    for (const route of routes) {
      const routeId = this.makeNodeId('route', route.path ?? route.route ?? '/', route.file, route.line)
      nodes.push({
        id: routeId,
        label: `${route.method ?? 'GET'} ${route.path ?? route.route ?? '/'}`,
        type: 'route',
        domain: 'backend',
        status: 'active',
        file: route.file,
        line: route.line,
        radius: 12,
        color: NEURAL_COLORS.route,
        data: { method: route.method ?? 'GET', path: route.path ?? route.route ?? '/', middleware: route.middleware ?? [] },
      })
      targetIds.push(routeId)

      // Edge from route to handler
      if (route.handler ?? route.fn) {
        const handlerId = this.makeNodeId('function', route.handler ?? route.fn ?? 'handler', route.file, route.handler_line)
        edges.push({
          id: this.makeEdgeId(routeId, handlerId, 'routes_to'),
          source: routeId,
          target: handlerId,
          type: 'routes_to',
          weight: 2,
          status: 'active',
        })
        targetIds.push(handlerId)
      }
    }

    return this.makeEvent(
      'api-map', nodes, edges, 'pulse', targetIds, 'low',
      'api-map', `Mapped ${routes.length} API route(s)`
    )
  }

  /** state-map: Tracks global state management */
  private normalizeStateMap(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const edges: GraphEdge[] = []
    const targetIds: string[] = []
    const stores: any[] = output?.stores ?? output?.results ?? []

    for (const store of stores) {
      const name: string = store.name ?? store.store ?? 'store'
      const nodeId = this.makeNodeId('store', name, store.file, store.line)

      nodes.push({
        id: nodeId,
        label: name,
        type: 'store',
        domain: 'frontend',
        status: 'active',
        file: store.file,
        line: store.line,
        radius: 14,
        color: NEURAL_COLORS.store,
        data: { type: store.type ?? '', keys: store.keys ?? store.state_keys ?? [] },
      })
      targetIds.push(nodeId)

      // Readers
      const readers: any[] = store.readers ?? store.reads ?? []
      for (const reader of readers) {
        const readerId = this.makeNodeId('function', reader.fn ?? reader.name ?? 'reader', reader.file, reader.line)
        edges.push({
          id: this.makeEdgeId(readerId, nodeId, 'reads'),
          source: readerId,
          target: nodeId,
          type: 'reads',
          weight: 1,
          status: 'active',
        })
        targetIds.push(readerId)
      }

      // Writers
      const writers: any[] = store.writers ?? store.writes ?? []
      for (const writer of writers) {
        const writerId = this.makeNodeId('function', writer.fn ?? writer.name ?? 'writer', writer.file, writer.line)
        edges.push({
          id: this.makeEdgeId(writerId, nodeId, 'writes'),
          source: writerId,
          target: nodeId,
          type: 'writes',
          weight: 2,
          status: 'active',
        })
        targetIds.push(writerId)
      }
    }

    return this.makeEvent(
      'state-map', nodes, edges, 'pulse', targetIds, 'low',
      'state-map', `Mapped ${stores.length} state store(s)`
    )
  }

  /** env-check: Audits environment variables */
  private normalizeEnvCheck(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const targetIds: string[] = []
    const variables: any[] = output?.variables ?? output?.results ?? []

    for (const v of variables) {
      const name: string = v.name ?? v.key ?? 'ENV_VAR'
      const nodeId = this.makeNodeId('env_var', name)
      const status: NodeStatus = v.missing ? 'critical' : v.unused ? 'orphan' : v.unsafe_default ? 'warning' : 'active'

      nodes.push({
        id: nodeId,
        label: name,
        type: 'env_var',
        domain: 'backend',
        status,
        radius: 10,
        color: status === 'critical' ? NEURAL_COLORS.critical : status === 'warning' ? NEURAL_COLORS.warning : status === 'orphan' ? NEURAL_COLORS.orphan : NEURAL_COLORS.env_var,
        data: {
          missing: v.missing ?? false,
          unused: v.unused ?? false,
          unsafeDefault: v.unsafe_default ?? false,
          usedIn: v.used_in ?? [],
        },
      })
      targetIds.push(nodeId)
    }

    const missing = variables.filter(v => v.missing).length
    const risk: RiskLevel = missing > 3 ? 'critical' : missing > 0 ? 'high' : 'low'

    return this.makeEvent(
      'env-check', nodes, [], 'pulse', targetIds, risk,
      'env-check', `Env check: ${variables.length} variable(s), ${missing} missing`
    )
  }

  /** debug-leak: Detects leftover debug code */
  private normalizeDebugLeak(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const targetIds: string[] = []
    const findings: any[] = output?.findings ?? output?.results ?? []

    for (const finding of findings) {
      const name: string = finding.fn ?? finding.variable ?? finding.pattern ?? 'debug'
      const nodeId = this.makeNodeId('function', name, finding.file, finding.line)

      nodes.push({
        id: nodeId,
        label: name,
        type: 'function',
        domain: this.inferDomain(finding.file ?? ''),
        status: 'warning',
        file: finding.file,
        line: finding.line,
        radius: 9,
        color: NEURAL_COLORS.warning,
        data: { pattern: finding.pattern ?? '', severity: finding.severity ?? 'info', message: finding.message ?? '' },
      })
      targetIds.push(nodeId)
    }

    const risk: RiskLevel = findings.some(f => f.severity === 'critical') ? 'high' : findings.length > 0 ? 'medium' : 'low'

    return this.makeEvent(
      'debug-leak', nodes, [], 'pulse', targetIds, risk,
      'debug-leak', `Found ${findings.length} debug leak(s)`
    )
  }

  /** complexity: Overlay badges with complexity scores */
  private normalizeComplexity(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const targetIds: string[] = []
    const functions: any[] = output?.functions ?? output?.hotspots ?? []

    for (const fn of functions) {
      const name: string = fn.name ?? fn.fn ?? 'unknown'
      const nodeId = this.makeNodeId('function', name, fn.file, fn.line)
      const cc: number = fn.cyclomatic ?? fn.complexity ?? 1
      const status: NodeStatus = cc > 20 ? 'warning' : cc > 10 ? 'warning' : 'active'

      nodes.push({
        id: nodeId,
        label: name,
        type: 'function',
        domain: 'backend',
        status,
        file: fn.file,
        line: fn.line,
        radius: 8 + Math.min(cc, 20),
        color: cc > 20 ? NEURAL_COLORS.critical : cc > 10 ? NEURAL_COLORS.warning : NEURAL_COLORS.function,
        data: {
          cyclomatic: cc,
          cognitive: fn.cognitive ?? 0,
          loc: fn.loc ?? 0,
          complexityLevel: fn.complexity_level ?? 'simple',
        },
      })
      targetIds.push(nodeId)
    }

    const highCC = output?.stats?.high_complexity ?? 0
    const risk: RiskLevel = highCC > 5 ? 'high' : highCC > 0 ? 'medium' : 'low'

    return this.makeEvent(
      'complexity', nodes, [], 'pulse', targetIds, risk,
      'complexity', `Complexity: avg CC ${output?.stats?.avg_cyclomatic ?? 0}, ${highCC} high-complexity function(s)`
    )
  }

  /** regex-audit: Audits regex for ReDoS */
  private normalizeRegexAudit(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const targetIds: string[] = []
    const findings: any[] = output?.findings ?? output?.results ?? []

    for (const finding of findings) {
      const name: string = finding.pattern ?? finding.regex ?? 'regex'
      const nodeId = this.makeNodeId('variable', name, finding.file, finding.line)

      nodes.push({
        id: nodeId,
        label: name.length > 30 ? name.slice(0, 27) + '...' : name,
        type: 'variable',
        domain: 'backend',
        status: finding.vulnerable ? 'critical' : 'warning',
        file: finding.file,
        line: finding.line,
        radius: 10,
        color: finding.vulnerable ? NEURAL_COLORS.critical : NEURAL_COLORS.warning,
        data: { vulnerable: finding.vulnerable ?? false, severity: finding.severity ?? '', starHeight: finding.star_height ?? 0 },
      })
      targetIds.push(nodeId)
    }

    const risk: RiskLevel = findings.some(f => f.vulnerable) ? 'critical' : findings.length > 0 ? 'medium' : 'low'

    return this.makeEvent(
      'regex-audit', nodes, [], 'pulse', targetIds, risk,
      'regex-audit', `Regex audit: ${findings.length} pattern(s) checked`
    )
  }

  /** a11y: Detects accessibility issues */
  private normalizeA11y(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const targetIds: string[] = []
    const issues: any[] = output?.issues ?? output?.findings ?? []

    for (const issue of issues) {
      const name: string = issue.element ?? issue.selector ?? issue.rule ?? 'a11y'
      const nodeId = this.makeNodeId('id', name, issue.file, issue.line)

      nodes.push({
        id: nodeId,
        label: name.length > 30 ? name.slice(0, 27) + '...' : name,
        type: 'id',
        domain: 'frontend',
        status: issue.severity === 'critical' ? 'critical' : 'warning',
        file: issue.file,
        line: issue.line,
        radius: 9,
        color: issue.severity === 'critical' ? NEURAL_COLORS.critical : NEURAL_COLORS.warning,
        data: { rule: issue.rule ?? '', severity: issue.severity ?? 'warning', message: issue.message ?? '' },
      })
      targetIds.push(nodeId)
    }

    const risk: RiskLevel = issues.some(i => i.severity === 'critical') ? 'high' : issues.length > 0 ? 'medium' : 'low'

    return this.makeEvent(
      'a11y', nodes, [], 'pulse', targetIds, risk,
      'a11y', `Accessibility: ${issues.length} issue(s) found`
    )
  }

  /** vuln-scan: Creates vulnerability nodes for CVE entries with alarm animation */
  private normalizeVulnScan(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const edges: GraphEdge[] = []
    const targetIds: string[] = []
    const findings: any[] = output?.findings ?? []
    const vulnerabilities: any[] = output?.vulnerabilities ?? findings

    for (const vuln of vulnerabilities) {
      const pkgName: string = vuln.package ?? 'unknown'
      const cve: string = vuln.cve ?? ''
      const name = cve || pkgName
      const nodeId = this.makeNodeId('vulnerability', name, vuln.file, vuln.line)
      const severity: string = vuln.severity ?? 'medium'
      const status: NodeStatus = severity === 'critical' ? 'critical' : severity === 'high' ? 'vulnerable' : severity === 'medium' ? 'warning' : 'safe'

      nodes.push({
        id: nodeId,
        label: cve || pkgName,
        type: 'vulnerability',
        domain: 'backend',
        status,
        radius: 12,
        color: status === 'critical' ? NEURAL_COLORS.critical : status === 'vulnerable' ? NEURAL_COLORS.vulnerable : NEURAL_COLORS.warning,
        data: {
          package: pkgName,
          version: vuln.version ?? vuln.installed_version ?? '',
          cve,
          severity,
          description: vuln.description ?? vuln.title ?? '',
          fixVersion: vuln.fix_version ?? '',
        },
      })
      targetIds.push(nodeId)

      // Edge from vulnerable package to vulnerability
      const pkgNodeId = this.makeNodeId('package', pkgName)
      edges.push({
        id: this.makeEdgeId(pkgNodeId, nodeId, 'depends_on'),
        source: pkgNodeId,
        target: nodeId,
        type: 'depends_on',
        weight: 2,
        status: 'danger',
      })
    }

    const risk: RiskLevel = this.mapRiskLevel(output?.risk)

    return this.makeEvent(
      'vuln-scan', nodes, edges, 'alarm', targetIds, risk,
      'vuln-scan', `Vulnerability scan: ${findings.length} finding(s)`,
      undefined, 'critical'
    )
  }

  /** perf-hint: Detects performance anti-patterns */
  private normalizePerfHint(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const targetIds: string[] = []
    const hints: any[] = output?.hints ?? output?.findings ?? []

    for (const hint of hints) {
      const name: string = hint.fn ?? hint.function ?? hint.pattern ?? 'perf'
      const nodeId = this.makeNodeId('function', name, hint.file, hint.line)
      const status: NodeStatus = hint.severity === 'critical' ? 'warning' : 'active'

      nodes.push({
        id: nodeId,
        label: name,
        type: 'function',
        domain: this.inferDomain(hint.file ?? ''),
        status,
        file: hint.file,
        line: hint.line,
        radius: 9,
        color: status === 'warning' ? NEURAL_COLORS.warning : NEURAL_COLORS.function,
        data: { category: hint.category ?? hint.type ?? '', severity: hint.severity ?? 'info', message: hint.message ?? '' },
      })
      targetIds.push(nodeId)
    }

    const risk: RiskLevel = hints.some(h => h.severity === 'critical') ? 'high' : hints.length > 0 ? 'medium' : 'low'

    return this.makeEvent(
      'perf-hint', nodes, [], 'pulse', targetIds, risk,
      'perf-hint', `Performance: ${hints.length} hint(s) found`
    )
  }

  /** css-deep: Deep CSS analysis */
  private normalizeCssDeep(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const edges: GraphEdge[] = []
    const targetIds: string[] = []
    const variables: any[] = output?.variables ?? []
    const keyframes: any[] = output?.keyframes ?? []
    const conflicts: any[] = output?.specificity_conflicts ?? output?.conflicts ?? []

    // CSS variables
    for (const v of variables) {
      const nodeId = this.makeNodeId('variable', v.name ?? 'var', v.file, v.line)
      nodes.push({
        id: nodeId,
        label: v.name ?? '--var',
        type: 'variable',
        domain: 'frontend',
        status: v.unused ? 'dead' : 'active',
        file: v.file,
        line: v.line,
        radius: 8,
        color: v.unused ? NEURAL_COLORS.dead : NEURAL_COLORS.variable,
        data: { value: v.value ?? '', usageCount: v.usage_count ?? 0 },
      })
      targetIds.push(nodeId)
    }

    // Specificity conflicts
    for (const conflict of conflicts) {
      const nodeId = this.makeNodeId('class', conflict.selector ?? 'conflict', conflict.file, conflict.line)
      nodes.push({
        id: nodeId,
        label: (conflict.selector ?? 'conflict').slice(0, 30),
        type: 'class',
        domain: 'frontend',
        status: 'collision',
        file: conflict.file,
        line: conflict.line,
        radius: 10,
        color: NEURAL_COLORS.critical,
        data: { specificity: conflict.specificity ?? '', message: conflict.message ?? '' },
      })
      targetIds.push(nodeId)
    }

    const risk: RiskLevel = conflicts.length > 0 ? 'high' : 'low'

    return this.makeEvent(
      'css-deep', nodes, edges, 'pulse', targetIds, risk,
      'css-deep', `CSS analysis: ${variables.length} variable(s), ${conflicts.length} conflict(s)`
    )
  }

  /** validate: Validates registry vs file system */
  private normalizeValidate(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const targetIds: string[] = []
    const issues: any[] = output?.issues ?? output?.errors ?? []
    const valid: boolean = output?.valid ?? output?.status === 'ok'

    for (const issue of issues) {
      const name: string = issue.name ?? issue.symbol ?? 'validation'
      const nodeId = this.makeNodeId('function', name, issue.file, issue.line)
      const status: NodeStatus = issue.severity === 'error' ? 'critical' : 'warning'

      nodes.push({
        id: nodeId,
        label: name,
        type: 'function',
        domain: this.inferDomain(issue.file ?? ''),
        status,
        file: issue.file,
        line: issue.line,
        radius: 9,
        color: status === 'critical' ? NEURAL_COLORS.critical : NEURAL_COLORS.warning,
        data: { severity: issue.severity ?? 'warning', message: issue.message ?? '', type: issue.type ?? '' },
      })
      targetIds.push(nodeId)
    }

    const risk: RiskLevel = !valid ? 'high' : issues.length > 0 ? 'medium' : 'low'

    return this.makeEvent(
      'validate', nodes, [], 'pulse', targetIds, risk,
      'validate', `Validation: ${valid ? 'PASS' : 'FAIL'} — ${issues.length} issue(s)`
    )
  }

  /** diff: Compares registry snapshots */
  private normalizeDiff(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const edges: GraphEdge[] = []
    const targetIds: string[] = []
    const added: any[] = output?.added ?? []
    const removed: any[] = output?.removed ?? []
    const modified: any[] = output?.modified ?? []

    for (const item of added) {
      const name: string = item.name ?? item.fn ?? 'added'
      const nodeType: NodeType = item.type === 'class' ? 'class' : item.type === 'id' ? 'id' : 'function'
      const nodeId = this.makeNodeId(nodeType, name, item.file, item.line)

      nodes.push({
        id: nodeId,
        label: name,
        type: nodeType,
        domain: this.inferDomain(item.file ?? ''),
        status: 'safe',
        file: item.file,
        line: item.line,
        radius: 9,
        color: NEURAL_COLORS.safe,
        data: { change: 'added' },
      })
      targetIds.push(nodeId)
    }

    for (const item of removed) {
      const name: string = item.name ?? item.fn ?? 'removed'
      const nodeType: NodeType = item.type === 'class' ? 'class' : item.type === 'id' ? 'id' : 'function'
      const nodeId = this.makeNodeId(nodeType, name, item.file, item.line)

      nodes.push({
        id: nodeId,
        label: name,
        type: nodeType,
        domain: this.inferDomain(item.file ?? ''),
        status: 'dead',
        file: item.file,
        line: item.line,
        radius: 9,
        color: NEURAL_COLORS.dead,
        data: { change: 'removed' },
      })
      targetIds.push(nodeId)
    }

    for (const item of modified) {
      const name: string = item.name ?? item.fn ?? 'modified'
      const nodeType: NodeType = item.type === 'class' ? 'class' : item.type === 'id' ? 'id' : 'function'
      const nodeId = this.makeNodeId(nodeType, name, item.file, item.line)

      nodes.push({
        id: nodeId,
        label: name,
        type: nodeType,
        domain: this.inferDomain(item.file ?? ''),
        status: 'warning',
        file: item.file,
        line: item.line,
        radius: 9,
        color: NEURAL_COLORS.warning,
        data: { change: 'modified' },
      })
      targetIds.push(nodeId)
    }

    return this.makeEvent(
      'diff', nodes, edges, 'ripple', targetIds, 'low',
      'diff', `Diff: +${added.length} -${removed.length} ~${modified.length}`
    )
  }

  /** dependents: Module-level import tracking */
  private normalizeDependents(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const edges: GraphEdge[] = []
    const targetIds: string[] = []
    const dependents: any[] = output?.dependents ?? []
    const dependencies: any[] = output?.dependencies ?? []
    const file: string = output?.file ?? 'unknown'

    // Source file node
    const sourceId = this.makeNodeId('file', file)
    nodes.push({
      id: sourceId,
      label: file.split('/').pop() ?? file,
      type: 'file',
      domain: this.inferDomain(file),
      status: 'active',
      file,
      radius: 14,
      color: NEURAL_COLORS.file,
      data: {},
    })
    targetIds.push(sourceId)

    // Files that depend on this file
    for (const dep of dependents) {
      const depId = this.makeNodeId('file', dep.file ?? dep.path ?? 'dependent')
      if (!nodes.find(n => n.id === depId)) {
        nodes.push({
          id: depId,
          label: (dep.file ?? dep.path ?? 'dependent').split('/').pop() ?? 'dep',
          type: 'file',
          domain: this.inferDomain(dep.file ?? dep.path ?? ''),
          status: 'active',
          file: dep.file ?? dep.path,
          radius: 9,
          color: NEURAL_COLORS.file,
          data: {},
        })
      }
      targetIds.push(depId)
      edges.push({
        id: this.makeEdgeId(depId, sourceId, 'imports_from'),
        source: depId,
        target: sourceId,
        type: 'imports_from',
        weight: 1,
        status: 'active',
      })
    }

    // Files this file depends on
    for (const dep of dependencies) {
      const depId = this.makeNodeId('file', dep.file ?? dep.path ?? 'dependency')
      if (!nodes.find(n => n.id === depId)) {
        nodes.push({
          id: depId,
          label: (dep.file ?? dep.path ?? 'dependency').split('/').pop() ?? 'dep',
          type: 'file',
          domain: this.inferDomain(dep.file ?? dep.path ?? ''),
          status: 'active',
          file: dep.file ?? dep.path,
          radius: 9,
          color: NEURAL_COLORS.file,
          data: {},
        })
      }
      targetIds.push(depId)
      edges.push({
        id: this.makeEdgeId(sourceId, depId, 'imports_from'),
        source: sourceId,
        target: depId,
        type: 'imports_from',
        weight: 1,
        status: 'active',
      })
    }

    return this.makeEvent(
      'dependents', nodes, edges, 'pulse', targetIds, 'low',
      'dependents', `${file}: ${dependents.length} dependent(s), ${dependencies.length} dependenc${dependencies.length === 1 ? 'y' : 'ies'}`
    )
  }

  /** context: Returns rich symbol context */
  private normalizeContext(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const edges: GraphEdge[] = []
    const targetIds: string[] = []
    const name: string = output?.fn ?? output?.name ?? output?.symbol ?? 'unknown'
    const nodeData = output?.node ?? output

    const nodeId = this.makeNodeId('function', name, nodeData.file, nodeData.line)
    const status = this.statusToNodeStatus(nodeData.status ?? 'active')

    nodes.push({
      id: nodeId,
      label: name,
      type: nodeData.component ? 'component' : 'function',
      domain: 'backend',
      status,
      file: nodeData.file,
      line: nodeData.line,
      radius: 14,
      color: NEURAL_COLORS.function,
      data: {
        async: nodeData.async ?? false,
        implFor: nodeData.impl_for ?? null,
        callers: output?.callers ?? [],
        callees: output?.callees ?? [],
        definedIn: output?.defined_in ?? [],
        tests: output?.tests ?? [],
      },
    })
    targetIds.push(nodeId)

    // Caller/callee edges
    const callers: any[] = output?.callers ?? []
    for (const caller of callers) {
      const callerId = this.makeNodeId('function', caller.fn ?? 'caller', caller.file, caller.line)
      edges.push({
        id: this.makeEdgeId(callerId, nodeId, 'calls'),
        source: callerId,
        target: nodeId,
        type: 'calls',
        weight: 1,
        status: 'active',
      })
      targetIds.push(callerId)
    }

    const callees: any[] = output?.callees ?? []
    for (const callee of callees) {
      const calleeId = this.makeNodeId('function', callee.fn ?? 'callee', callee.file, callee.line)
      edges.push({
        id: this.makeEdgeId(nodeId, calleeId, 'calls'),
        source: nodeId,
        target: calleeId,
        type: 'calls',
        weight: 1,
        status: 'active',
      })
      targetIds.push(calleeId)
    }

    return this.makeEvent(
      'context', nodes, edges, 'pulse', targetIds, 'low',
      'context', `Context for ${name}: ${callers.length} caller(s), ${callees.length} callee(s)`
    )
  }

  /** outline: Returns file structure outline */
  private normalizeOutline(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const edges: GraphEdge[] = []
    const targetIds: string[] = []
    const items: any[] = output?.outline ?? output?.items ?? output?.results ?? []
    const file: string = output?.file ?? 'unknown'

    // File node
    const fileId = this.makeNodeId('file', file)
    nodes.push({
      id: fileId,
      label: file.split('/').pop() ?? file,
      type: 'file',
      domain: this.inferDomain(file),
      status: 'active',
      file,
      radius: 14,
      color: NEURAL_COLORS.file,
      data: {},
    })
    targetIds.push(fileId)

    // Symbols in the file
    for (const item of items) {
      const name: string = item.name ?? item.fn ?? 'symbol'
      const nodeType: NodeType = item.kind === 'class' || item.type === 'class' ? 'component'
        : item.kind === 'method' || item.type === 'function' ? 'function'
        : item.kind === 'variable' || item.type === 'variable' ? 'variable'
        : 'function'
      const nodeId = this.makeNodeId(nodeType, name, file, item.line)

      nodes.push({
        id: nodeId,
        label: name,
        type: nodeType,
        domain: this.inferDomain(file),
        status: 'active',
        file,
        line: item.line,
        radius: 9,
        color: NEURAL_COLORS[nodeType as keyof typeof NEURAL_COLORS] ?? NEURAL_COLORS.function,
        data: { kind: item.kind ?? item.type ?? '', visibility: item.visibility ?? '' },
      })
      targetIds.push(nodeId)

      // Edge from file to symbol (defines)
      edges.push({
        id: this.makeEdgeId(fileId, nodeId, 'defines'),
        source: fileId,
        target: nodeId,
        type: 'defines',
        weight: 1,
        status: 'active',
      })
    }

    return this.makeEvent(
      'outline', nodes, edges, 'pulse', targetIds, 'low',
      'outline', `Outline of ${file}: ${items.length} symbol(s)`
    )
  }

  /** missing-refs: Detects CSS/HTML mismatches */
  private normalizeMissingRefs(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const targetIds: string[] = []
    const missing: any[] = output?.missing ?? output?.results ?? []

    for (const item of missing) {
      const name: string = item.name ?? item.ref ?? 'missing'
      const nodeType: NodeType = item.type === 'class' ? 'class' : item.type === 'id' ? 'id' : 'class'
      const nodeId = this.makeNodeId(nodeType, name, item.file, item.line)

      nodes.push({
        id: nodeId,
        label: nodeType === 'class' ? `.${name}` : `#${name}`,
        type: nodeType,
        domain: 'frontend',
        status: 'dead',
        file: item.file,
        line: item.line,
        radius: 9,
        color: NEURAL_COLORS.dead,
        data: { refType: item.type ?? '', source: item.source ?? '', message: item.message ?? '' },
      })
      targetIds.push(nodeId)
    }

    const risk: RiskLevel = missing.length > 10 ? 'high' : missing.length > 0 ? 'medium' : 'low'

    return this.makeEvent(
      'missing-refs', nodes, [], 'pulse', targetIds, risk,
      'missing-refs', `Missing refs: ${missing.length} unresolved reference(s)`
    )
  }

  /** init: Initialize .codelens config */
  private normalizeInit(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const targetIds: string[] = []
    const config = output?.config ?? {}

    // Create a single config node
    const workspace: string = output?.workspace ?? 'workspace'
    const nodeId = this.makeNodeId('file', '.codelens')

    nodes.push({
      id: nodeId,
      label: '.codelens',
      type: 'file',
      domain: 'backend',
      status: 'safe',
      file: '.codelens',
      radius: 14,
      color: NEURAL_COLORS.safe,
      data: {
        frameworks: config.frameworks ?? [],
        frontendPaths: config.frontend_paths ?? [],
        backendPaths: config.backend_paths ?? [],
        workspace,
      },
    })
    targetIds.push(nodeId)

    // Framework nodes
    const frameworks: string[] = config.frameworks ?? []
    for (const fw of frameworks) {
      const fwId = this.makeNodeId('variable', fw)
      nodes.push({
        id: fwId,
        label: fw,
        type: 'variable',
        domain: 'frontend',
        status: 'active',
        radius: 8,
        color: NEURAL_COLORS.variable,
        data: {},
      })
      targetIds.push(fwId)
    }

    return this.makeEvent(
      'init', nodes, [], 'ripple', targetIds, 'low',
      'init', `Initialized .codelens for ${workspace} (${frameworks.join(', ')})`
    )
  }

  /** detect: Returns detected frameworks with flash animation */
  private normalizeDetect(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const targetIds: string[] = []
    const frameworks: string[] = output?.frameworks ?? []

    for (const fw of frameworks) {
      const nodeId = this.makeNodeId('package', fw)
      nodes.push({
        id: nodeId,
        label: fw,
        type: 'package',
        domain: 'backend',
        status: 'active',
        radius: 10,
        color: NEURAL_COLORS.package,
        data: {
          hasReact: output?.has_react ?? false,
          hasVue: output?.has_vue ?? false,
          hasSvelte: output?.has_svelte ?? false,
          hasTailwind: output?.has_tailwind ?? false,
          hasNextjs: output?.has_nextjs ?? false,
          hasAngular: output?.has_angular ?? false,
        },
      })
      targetIds.push(nodeId)
    }

    return this.makeEvent(
      'detect', nodes, [], 'flash', targetIds, 'low',
      'detect', `Detected ${frameworks.length} framework(s): ${frameworks.join(', ')}`
    )
  }

  /** watch: Streaming command — returns error event for REST API */
  private normalizeWatch(output: any): GraphEvent {
    return this.makeEvent(
      'watch', [], [], 'pulse', [], 'low',
      'watch', 'Watch mode: Use the WebSocket interface for real-time updates, not the REST API.'
    )
  }

  /** handbook: Project orientation for AI agents */
  private normalizeHandbook(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const edges: GraphEdge[] = []
    const targetIds: string[] = []

    // Handbook returns structured project orientation data
    const identity = output?.identity ?? output?.project ?? {}
    const structure = output?.structure ?? {}
    const health = output?.health ?? {}
    const conventions = output?.conventions ?? {}
    const risks = output?.risks ?? []

    // Create a node for the project itself
    const projectNodeId = this.makeNodeId('file', identity.name ?? 'project')
    const projectNode: GraphNode = {
      id: projectNodeId,
      label: identity.name ?? 'project',
      type: 'file',
      domain: 'backend',
      status: 'active',
      file: identity.root ?? '',
      radius: 12,
      color: NEURAL_COLORS.file,
      data: { type: 'project', ...identity, structure, health, conventions },
    }
    nodes.push(projectNode)
    targetIds.push(projectNodeId)

    // Create risk nodes if present
    if (Array.isArray(risks)) {
      for (const risk of risks.slice(0, 10)) {
        const riskLabel = typeof risk === 'string' ? risk : risk.message ?? risk.category ?? 'risk'
        const riskNodeId = this.makeNodeId('vulnerability', riskLabel)
        const riskNode: GraphNode = {
          id: riskNodeId,
          label: riskLabel,
          type: 'vulnerability',
          domain: 'backend',
          status: 'warning',
          radius: 6,
          color: NEURAL_COLORS.vulnerability,
          data: { severity: risk.severity ?? 'medium', category: risk.category ?? '' },
        }
        nodes.push(riskNode)
        targetIds.push(riskNodeId)
        edges.push({
          id: this.makeEdgeId(projectNodeId, riskNodeId, 'contains'),
          source: projectNodeId,
          target: riskNodeId,
          type: 'contains',
          weight: 1,
          status: 'warning',
        })
      }
    }

    const riskLevel = risks.length > 3 ? 'high' : risks.length > 0 ? 'medium' : 'safe'
    return this.makeEvent(
      'handbook', nodes, edges, 'pulse', targetIds, riskLevel,
      'orientation', `Project handbook: ${identity.name ?? 'unknown'} — ${risks.length} risks identified`
    )
  }

  /** ask: Natural language query router */
  private normalizeAsk(output: any): GraphEvent {
    const nodes: GraphNode[] = []
    const targetIds: string[] = []

    // Ask returns a routed command result with the original query
    const routedCommand = output?.command ?? output?.routed_command ?? 'unknown'
    const query = output?.query ?? output?.question ?? ''
    const result = output?.result ?? output

    // If the result contains nodes/edges from the routed command, normalize them
    if (result?.frontend || result?.backend) {
      // Delegate to scan normalizer for structured results
      const scanEvent = this.normalizeScan(result)
      return {
        ...scanEvent,
        sourceCommand: 'ask',
        metadata: {
          ...scanEvent.metadata,
          category: 'ask',
          summary: `Ask "${query}" → routed to ${routedCommand}: ${scanEvent.metadata.summary ?? ''}`,
        },
      }
    }

    // Fallback: create a single info node
    const askNodeId = this.makeNodeId('function', `ask:${query.substring(0, 40)}`)
    const askNode: GraphNode = {
      id: askNodeId,
      label: `ask: ${query.substring(0, 50)}`,
      type: 'function',
      domain: 'backend',
      status: 'active',
      radius: 8,
      color: NEURAL_COLORS.function,
      data: { routedCommand, query, result },
    }
    nodes.push(askNode)
    targetIds.push(askNodeId)

    return this.makeEvent(
      'ask', nodes, [], 'pulse', targetIds, 'low',
      'ask', `Ask routed to: ${routedCommand}`
    )
  }

  // ─── Helpers ──────────────────────────────────────────────────

  /** Build a GraphEvent with sensible defaults */
  private makeEvent(
    command: string,
    nodes: GraphNode[],
    edges: GraphEdge[],
    animationType: GraphAnimation['type'],
    targetNodeIds: string[],
    riskLevel: RiskLevel,
    category: string,
    summary: string,
    direction?: 'up' | 'down' | 'both',
    intensity?: AnimationIntensity,
  ): GraphEvent {
    const animation: GraphAnimation = {
      type: animationType,
      targetNodeIds,
      ...(direction ? { direction } : {}),
      speed: 1,
      intensity: intensity ?? (riskLevel === 'critical' ? 'critical' : riskLevel === 'high' ? 'high' : riskLevel === 'medium' ? 'medium' : 'low'),
    }

    return {
      sourceCommand: command,
      timestamp: Date.now(),
      nodes,
      edges,
      animation,
      metadata: {
        riskLevel,
        category,
        summary,
      },
    }
  }

  /** Generate a stable node ID from type, name, and optional file/line */
  private makeNodeId(type: string, name: string, file?: string, line?: number): string {
    if (file && line) {
      return `${file}:${name}:${line}`
    }
    if (file) {
      return `${file}:${name}`
    }
    // Frontend nodes without file/line use type:name format
    if (type === 'class') return `class:${name}`
    if (type === 'id') return `id:${name}`
    if (type === 'package') return `pkg:${name}`
    if (type === 'env_var') return `env:${name}`
    if (type === 'secret') return `secret:${name}`
    if (type === 'vulnerability') return `vuln:${name}`
    if (type === 'test') return `test:${name}`
    if (type === 'store') return `store:${name}`
    if (type === 'route') return `route:${name}`
    return `${type}:${name}`
  }

  /** Generate a stable edge ID from source, target, and type */
  private makeEdgeId(source: string, target: string, edgeType: string): string {
    return `${source}→${target}:${edgeType}`
  }

  /** Map CLI status strings to NodeStatus */
  private statusToNodeStatus(status: string): NodeStatus {
    const map: Record<string, NodeStatus> = {
      active: 'active',
      dead: 'dead',
      duplicate_ref: 'duplicate_define',
      duplicate_define: 'duplicate_define',
      collision: 'collision',
      vulnerable: 'vulnerable',
      critical: 'critical',
      safe: 'safe',
      orphan: 'orphan',
      warning: 'warning',
    }
    return map[status] ?? 'active'
  }

  /** Map CLI type strings to NodeType based on domain */
  private mapNodeType(type: string, domain: string): NodeType {
    const typeMap: Record<string, NodeType> = {
      class: 'class',
      id: 'id',
      function: 'function',
      component: 'component',
      store: 'store',
      file: 'file',
      package: 'package',
      route: 'route',
      env_var: 'env_var',
      variable: 'variable',
      // CLI-specific type strings
      class_usage: 'class',
      id_usage: 'id',
      css_definition: 'class',
      api_key: 'secret',
      secret: 'secret',
      method: 'function',
      arrow: 'function',
      def: 'function',
      fn: 'function',
    }
    return typeMap[type] ?? 'function'
  }

  /** Infer domain from file path */
  private inferDomain(filePath: string): Domain {
    const frontendIndicators = ['src/components', 'src/app', 'src/client', 'public/', 'frontend/', '.css', '.html', '.vue', '.svelte', '.tsx']
    return frontendIndicators.some(ind => filePath.includes(ind)) ? 'frontend' : 'backend'
  }

  /** Map raw edge type string to valid EdgeType */
  private mapEdgeType(raw: string): EdgeType {
    const valid: EdgeType[] = ['references', 'calls', 'imports', 'defines', 'depends_on', 'routes_to', 'reads', 'writes', 'contains', 'extends', 'implements', 'taints', 'sanitizes', 'tests', 'imports_from']
    const lower = raw.toLowerCase().replace(/-/g, '_')
    if (valid.includes(lower as EdgeType)) return lower as EdgeType
    // Common mappings
    if (lower === 'call' || lower === 'invokes') return 'calls'
    if (lower === 'import' || lower === 'imports_from') return 'imports'
    if (lower === 'depend' || lower === 'dependency') return 'depends_on'
    if (lower === 'reference' || lower === 'ref') return 'references'
    if (lower === 'contain' || lower === 'child') return 'contains'
    if (lower === 'extend' || lower === 'inherit') return 'extends'
    if (lower === 'implement') return 'implements'
    return 'calls' // default fallback
  }

  private mapRiskLevel(risk: string | undefined): RiskLevel {
    const map: Record<string, RiskLevel> = {
      safe: 'safe',
      low: 'low',
      medium: 'medium',
      high: 'high',
      critical: 'critical',
      none: 'safe',
    }
    return map[risk ?? ''] ?? 'low'
  }
}

export const normalizer = new Normalizer()
