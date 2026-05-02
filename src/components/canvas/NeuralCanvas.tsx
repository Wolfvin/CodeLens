'use client'

import React, { useRef, useEffect, useCallback, useState } from 'react'
import {
  forceSimulation,
  forceLink,
  forceManyBody,
  forceCenter,
  forceCollide,
} from 'd3-force'
import {
  GraphNode,
  GraphEdge,
  Cluster,
  GraphAnimation,
  NEURAL_COLORS,
  getNodeShape,
  LODLevel,
} from '@/types/neural'

// ============================================================
// Types
// ============================================================

interface NeuralCanvasProps {
  theme: 'dark' | 'light'
  nodes: GraphNode[]
  edges: GraphEdge[]
  clusters: Cluster[]
  onNodeSelect: (nodeId: string | null) => void
  selectedNodeId: string | null
  activeAnimation: GraphAnimation | null
  onCanvasReady?: () => void
}

interface SimNode extends GraphNode {
  x: number
  y: number
  vx: number
  vy: number
  fx: number | null
  fy: number | null
}

interface SimLink {
  source: SimNode | string
  target: SimNode | string
  id: string
  type: string
  weight: number
  status: string
}

interface AmbientParticle {
  x: number
  y: number
  vx: number
  vy: number
  radius: number
  opacity: number
  phase: number
  speed: number // varying speed for depth illusion
}

interface AnimationState {
  type: GraphAnimation['type']
  startTime: number
  targetIds: Set<string>
  intensity: number
}

// ============================================================
// Constants
// ============================================================

const AMBIENT_PARTICLE_COUNT = 30
const TOOLTIP_PADDING = 12
const TOOLTIP_LINE_HEIGHT = 18
const MIN_ZOOM = 0.1
const MAX_ZOOM = 3.0
const ZOOM_SENSITIVITY = 0.0004       // reduced for smoother, less jumpy zoom

// ============================================================
// Helper: get LOD level from zoom
// ============================================================

function getLODLevel(zoom: number): LODLevel {
  if (zoom < 0.3) return 'cluster'
  if (zoom < 0.7) return 'file'
  return 'symbol'
}

// ============================================================
// Helper: resolve edge source/target to string IDs
// ============================================================

function edgeSourceId(e: GraphEdge): string {
  return typeof e.source === 'string' ? e.source : e.source.id
}

function edgeTargetId(e: GraphEdge): string {
  return typeof e.target === 'string' ? e.target : e.target.id
}

// ============================================================
// Helper: create ambient particles
// ============================================================

function createAmbientParticles(width: number, height: number): AmbientParticle[] {
  const particles: AmbientParticle[] = []
  for (let i = 0; i < AMBIENT_PARTICLE_COUNT; i++) {
    // Varying speed for depth: some slow (background), some fast (foreground)
    const speed = 0.05 + Math.random() * 0.35
    particles.push({
      x: Math.random() * width,
      y: Math.random() * height,
      vx: (Math.random() - 0.5) * speed,
      vy: (Math.random() - 0.5) * speed,
      radius: Math.random() * 1.8 + 0.3,
      opacity: Math.random() * 0.25 + 0.05,
      phase: Math.random() * Math.PI * 2,
      speed,
    })
  }
  return particles
}

// ============================================================
// Helper: ensure color is in hex format for alpha concatenation
// ============================================================

function ensureHexColor(color: string): string {
  if (color.startsWith('#')) return color
  // Use canvas to resolve named colors to hex
  const ctx = document.createElement('canvas').getContext('2d')
  if (!ctx) return color
  ctx.fillStyle = color
  return ctx.fillStyle // Returns hex
}

// ============================================================
// Drawing Functions
// ============================================================

function drawBackground(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  theme: 'dark' | 'light'
) {
  // Premium gradient background with ambient glow
  if (theme === 'dark') {
    // Simple dark gradient
    const bgGrad = ctx.createLinearGradient(0, 0, width, height)
    bgGrad.addColorStop(0, '#0d0d18')
    bgGrad.addColorStop(1, '#060609')
    ctx.fillStyle = bgGrad
    ctx.fillRect(0, 0, width, height)
  } else {
    // Light mode gradient
    const bgGrad = ctx.createLinearGradient(0, 0, width, height)
    bgGrad.addColorStop(0, '#ffffff')
    bgGrad.addColorStop(1, '#f1f5f9')
    ctx.fillStyle = bgGrad
    ctx.fillRect(0, 0, width, height)
  }

  // Draw subtle dot grid (lighter than hex grid for performance)
  const gridColor = theme === 'dark' ? NEURAL_COLORS.darkGrid : NEURAL_COLORS.lightGrid
  ctx.fillStyle = gridColor
  ctx.globalAlpha = theme === 'dark' ? 0.2 : 0.15

  const gridSize = 50
  for (let x = gridSize; x < width; x += gridSize) {
    for (let y = gridSize; y < height; y += gridSize) {
      ctx.beginPath()
      ctx.arc(x, y, 0.8, 0, Math.PI * 2)
      ctx.fill()
    }
  }

  ctx.globalAlpha = 1.0
}

function drawAmbientParticles(
  ctx: CanvasRenderingContext2D,
  particles: AmbientParticle[],
  theme: 'dark' | 'light',
  time: number
) {
  // Premium particle colors with purple/blue tints
  const colors = theme === 'dark'
    ? ['160, 140, 250', '130, 180, 250', '180, 160, 230', '140, 200, 240']
    : ['120, 100, 200', '100, 140, 220', '140, 120, 180', '110, 160, 200']

  for (let i = 0; i < particles.length; i++) {
    const p = particles[i]
    const colorIdx = i % colors.length
    const flickerOpacity = p.opacity * (0.6 + 0.4 * Math.sin(time * 0.0008 + p.phase))
    
    // Core particle only (removed glow for performance)
    ctx.globalAlpha = flickerOpacity
    ctx.fillStyle = `rgba(${colors[colorIdx]}, ${flickerOpacity})`
    ctx.beginPath()
    ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2)
    ctx.fill()
    ctx.globalAlpha = 1.0
  }
}

function updateAmbientParticles(particles: AmbientParticle[], width: number, height: number) {
  for (const p of particles) {
    p.x += p.vx
    p.y += p.vy

    // Wrap around
    if (p.x < 0) p.x = width
    if (p.x > width) p.x = 0
    if (p.y < 0) p.y = height
    if (p.y > height) p.y = 0
  }
}

function drawCluster(
  ctx: CanvasRenderingContext2D,
  cluster: Cluster,
  clusterNodes: SimNode[],
  theme: 'dark' | 'light'
) {
  if (clusterNodes.length === 0) return

  // Compute bounding box of cluster nodes
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  for (const n of clusterNodes) {
    minX = Math.min(minX, n.x - n.radius)
    minY = Math.min(minY, n.y - n.radius)
    maxX = Math.max(maxX, n.x + n.radius)
    maxY = Math.max(maxY, n.y + n.radius)
  }

  const padding = 30
  const x = minX - padding
  const y = minY - padding
  const w = maxX - minX + padding * 2
  const h = maxY - minY + padding * 2
  const r = 16

  // Store computed center
  cluster.cx = (minX + maxX) / 2
  cluster.cy = (minY + maxY) / 2

  // Draw soft rounded rectangle
  const tint = cluster.tint
  const bgAlpha = theme === 'dark' ? 0.08 : 0.12
  const borderAlpha = theme === 'dark' ? 0.25 : 0.35

  ctx.save()

  // Background fill
  ctx.fillStyle = tint
  ctx.globalAlpha = bgAlpha
  ctx.beginPath()
  ctx.roundRect(x, y, w, h, r)
  ctx.fill()

  // Border
  ctx.strokeStyle = tint
  ctx.globalAlpha = borderAlpha
  ctx.lineWidth = 1.5
  ctx.setLineDash([6, 4])
  ctx.beginPath()
  ctx.roundRect(x, y, w, h, r)
  ctx.stroke()
  ctx.setLineDash([])

  // Label
  ctx.globalAlpha = theme === 'dark' ? 0.7 : 0.8
  ctx.fillStyle = tint
  ctx.font = 'bold 13px system-ui, -apple-system, sans-serif'
  ctx.textAlign = 'left'
  ctx.textBaseline = 'top'
  ctx.fillText(`${cluster.icon} ${cluster.label}`, x + 10, y + 8)

  // Cohesion badge
  ctx.font = '10px system-ui, -apple-system, sans-serif'
  ctx.globalAlpha = 0.5
  ctx.fillText(`cohesion: ${(cluster.cohesion * 100).toFixed(0)}%`, x + 10, y + 24)

  ctx.restore()
}

function drawEdge(
  ctx: CanvasRenderingContext2D,
  link: SimLink,
  theme: 'dark' | 'light',
  isActive: boolean,
  flowProgress: number,
  time: number
) {
  const source = typeof link.source === 'string' ? null : link.source
  const target = typeof link.target === 'string' ? null : link.target

  if (!source || !target) return

  const sx = source.x
  const sy = source.y
  const tx = target.x
  const ty = target.y

  // Control point for curved line (offset perpendicular to the line)
  const dx = tx - sx
  const dy = ty - sy
  const dist = Math.sqrt(dx * dx + dy * dy)
  if (dist < 1) return

  const curvature = 0.2
  const mx = (sx + tx) / 2
  const my = (sy + ty) / 2
  const nx = -dy / dist
  const ny = dx / dist
  const cx = mx + nx * dist * curvature
  const cy = my + ny * dist * curvature

  ctx.save()

  // Determine color
  let edgeColor: string
  let lineAlpha: number
  let lineWidth: number

  if (link.status === 'danger') {
    edgeColor = NEURAL_COLORS.edgeDanger
    lineAlpha = 0.9
    lineWidth = 2
  } else if (link.status === 'warning') {
    edgeColor = NEURAL_COLORS.edgeWarning
    lineAlpha = 0.7
    lineWidth = 1.5
  } else if (link.status === 'dead') {
    edgeColor = NEURAL_COLORS.edgeDead
    lineAlpha = 0.3
    lineWidth = 1
  } else {
    edgeColor = NEURAL_COLORS.edgeActive
    lineAlpha = 0.4
    lineWidth = 1
  }

  if (isActive) {
    lineAlpha = Math.min(1, lineAlpha + 0.4)
    lineWidth += 1
  }

  // Create gradient along the edge
  const gradient = ctx.createLinearGradient(sx, sy, tx, ty)
  const sourceColor = source.color || edgeColor
  const targetColor = target.color || edgeColor
  gradient.addColorStop(0, sourceColor)
  gradient.addColorStop(1, targetColor)

  ctx.globalAlpha = lineAlpha
  ctx.strokeStyle = isActive ? gradient : edgeColor
  ctx.lineWidth = lineWidth

  // Draw curved line
  ctx.beginPath()
  ctx.moveTo(sx, sy)
  ctx.quadraticCurveTo(cx, cy, tx, ty)
  ctx.stroke()

  // Flow particles along edge (simplified for performance)
  if (isActive && flowProgress >= 0) {
    const t = flowProgress
    // Single particle per edge
    const px = (1 - t) * (1 - t) * sx + 2 * (1 - t) * t * cx + t * t * tx
    const py = (1 - t) * (1 - t) * sy + 2 * (1 - t) * t * cy + t * t * ty

    ctx.globalAlpha = 0.8
    ctx.fillStyle = sourceColor
    ctx.beginPath()
    ctx.arc(px, py, 3, 0, Math.PI * 2)
    ctx.fill()
  }

  ctx.restore()
}

function drawGlow(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  radius: number,
  color: string,
  intensity: number
) {
  ctx.save()
  
  // Single efficient glow layer
  ctx.globalAlpha = intensity * 0.25
  const glow = ctx.createRadialGradient(x, y, 0, x, y, radius * 2.5)
  glow.addColorStop(0, color)
  glow.addColorStop(0.5, ensureHexColor(color) + '30')
  glow.addColorStop(1, 'transparent')
  ctx.fillStyle = glow
  ctx.beginPath()
  ctx.arc(x, y, radius * 2.5, 0, Math.PI * 2)
  ctx.fill()
  
  ctx.restore()
}

function drawShape(
  ctx: CanvasRenderingContext2D,
  shape: 'circle' | 'hexagon' | 'diamond' | 'triangle' | 'star' | 'square' | 'ring',
  x: number,
  y: number,
  radius: number
) {
  const r = Math.max(1, radius)

  switch (shape) {
    case 'circle':
      ctx.beginPath()
      ctx.arc(x, y, r, 0, Math.PI * 2)
      ctx.fill()
      break

    case 'diamond':
      ctx.save()
      ctx.translate(x, y)
      ctx.rotate(Math.PI / 4)
      ctx.fillRect(-r * 0.75, -r * 0.75, r * 1.5, r * 1.5)
      ctx.restore()
      break

    case 'hexagon': {
      ctx.beginPath()
      for (let i = 0; i < 6; i++) {
        const angle = (Math.PI / 3) * i - Math.PI / 6
        const px = x + r * Math.cos(angle)
        const py = y + r * Math.sin(angle)
        if (i === 0) ctx.moveTo(px, py)
        else ctx.lineTo(px, py)
      }
      ctx.closePath()
      ctx.fill()
      break
    }

    case 'triangle': {
      ctx.beginPath()
      ctx.moveTo(x, y - r)
      ctx.lineTo(x - r * 0.866, y + r * 0.5)
      ctx.lineTo(x + r * 0.866, y + r * 0.5)
      ctx.closePath()
      ctx.fill()
      break
    }

    case 'star': {
      const outerR = r
      const innerR = r * 0.45
      ctx.beginPath()
      for (let i = 0; i < 10; i++) {
        const angle = (Math.PI / 5) * i - Math.PI / 2
        const rad = i % 2 === 0 ? outerR : innerR
        const px = x + rad * Math.cos(angle)
        const py = y + rad * Math.sin(angle)
        if (i === 0) ctx.moveTo(px, py)
        else ctx.lineTo(px, py)
      }
      ctx.closePath()
      ctx.fill()
      break
    }

    case 'square': {
      const half = r * 0.8
      const cornerR = half * 0.25
      ctx.beginPath()
      ctx.roundRect(x - half, y - half, half * 2, half * 2, cornerR)
      ctx.fill()
      break
    }

    case 'ring': {
      // Draw donut shape using arc fill rule instead of destination-out
      // (destination-out punches holes through ALL previously drawn content)
      const outerR = r
      const innerR = r * 0.55
      ctx.beginPath()
      ctx.arc(x, y, outerR, 0, Math.PI * 2)
      ctx.arc(x, y, innerR, 0, Math.PI * 2, true) // counter-clockwise = hole
      ctx.fill('evenodd')
      // Inner ring border
      ctx.beginPath()
      ctx.arc(x, y, innerR, 0, Math.PI * 2)
      ctx.stroke()
      break
    }
  }
}

function drawNode(
  ctx: CanvasRenderingContext2D,
  node: SimNode,
  theme: 'dark' | 'light',
  isSelected: boolean,
  isHovered: boolean,
  animState: AnimationState | null,
  time: number
) {
  const shape = getNodeShape(node.type)
  const isActive = node.status === 'active'
  const isDormant = node.status === 'dead' || node.status === 'orphan'
  const isAnimTarget = animState ? animState.targetIds.has(node.id) : false

  ctx.save()

  // Compute visual modifiers from animation
  let radiusMultiplier = 1.0
  let opacityMultiplier = 1.0
  let overrideColor: string | null = null

  if (isAnimTarget && animState) {
    const elapsed = (time - animState.startTime) / 1000
    switch (animState.type) {
      case 'pulse': {
        const wave = Math.sin(elapsed * Math.PI * 3) * 0.3
        radiusMultiplier = 1 + wave
        opacityMultiplier = 0.7 + 0.3 * Math.abs(Math.sin(elapsed * Math.PI * 3))
        break
      }
      case 'flash': {
        const flash = Math.max(0, 1 - elapsed * 2)
        opacityMultiplier = 1 + flash * 0.5
        if (flash > 0.5) overrideColor = '#ffffff'
        break
      }
      case 'death': {
        const progress = Math.min(1, elapsed * 0.7)
        radiusMultiplier = 1 - progress * 0.7
        opacityMultiplier = 1 - progress * 0.8
        break
      }
      case 'alarm': {
        const alarmPulse = Math.sin(elapsed * Math.PI * 4)
        if (alarmPulse > 0) overrideColor = '#e53e3e'
        radiusMultiplier = 1 + alarmPulse * 0.15
        break
      }
      case 'ripple': {
        const ripplePhase = elapsed * 2
        const ripple = Math.sin(ripplePhase * Math.PI * 2) * 0.2
        radiusMultiplier = 1 + ripple
        break
      }
      case 'flow': {
        const flowPulse = Math.sin(elapsed * Math.PI * 2) * 0.15
        radiusMultiplier = 1 + flowPulse
        break
      }
    }
  }

  const nodeColor = overrideColor || node.color
  const nodeRadius = node.radius * radiusMultiplier
  const nodeOpacity = opacityMultiplier * (isDormant ? 0.4 : 1.0)

  // Draw glow for active/selected nodes only (skip hover glow for performance)
  const finalRadius = nodeRadius

  if (isActive || isHovered || isSelected || (isAnimTarget && animState?.type !== 'death')) {
    const glowIntensity = isSelected ? 0.8 : isHovered ? 0.6 : 0.3
    drawGlow(ctx, node.x, node.y, finalRadius, nodeColor, glowIntensity)
  }

  // Draw node shape
  ctx.globalAlpha = nodeOpacity
  ctx.fillStyle = nodeColor
  drawShape(ctx, shape, node.x, node.y, finalRadius)

  // Draw shape outline for better visibility
  ctx.strokeStyle = nodeColor
  ctx.lineWidth = 1.5
  ctx.globalAlpha = nodeOpacity * 0.5
  drawShapeOutline(ctx, shape, node.x, node.y, finalRadius)

  // Selected ring (simplified for performance)
  if (isSelected) {
    // Main selection ring
    ctx.globalAlpha = 0.9
    ctx.strokeStyle = '#ffffff'
    ctx.lineWidth = 2.5
    ctx.beginPath()
    ctx.arc(node.x, node.y, finalRadius + 5, 0, Math.PI * 2)
    ctx.stroke()
  }

  // Label
  ctx.globalAlpha = isDormant ? 0.3 : 0.9
  ctx.fillStyle = theme === 'dark' ? '#e2e8f0' : '#2d3748'
  ctx.font = `${Math.max(9, Math.min(12, finalRadius * 0.7))}px system-ui, -apple-system, sans-serif`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'top'
  ctx.fillText(node.label, node.x, node.y + finalRadius + 4)

  // Status indicator dot
  if (node.status === 'critical' || node.status === 'vulnerable' || node.status === 'warning') {
    const statusColor =
      node.status === 'critical' ? NEURAL_COLORS.critical :
      node.status === 'vulnerable' ? NEURAL_COLORS.vulnerable :
      NEURAL_COLORS.warning

    ctx.globalAlpha = 0.9
    ctx.fillStyle = statusColor
    ctx.beginPath()
    ctx.arc(node.x + nodeRadius * 0.7, node.y - nodeRadius * 0.7, 4, 0, Math.PI * 2)
    ctx.fill()

    // Pulsing ring on critical
    if (node.status === 'critical') {
      const pulse = (Math.sin(time * 0.005) + 1) / 2
      ctx.globalAlpha = 0.3 + pulse * 0.3
      ctx.strokeStyle = statusColor
      ctx.lineWidth = 1
      ctx.beginPath()
      ctx.arc(node.x + nodeRadius * 0.7, node.y - nodeRadius * 0.7, 4 + pulse * 4, 0, Math.PI * 2)
      ctx.stroke()
    }
  }

  ctx.restore()
}

/** Separate outline drawing to avoid double-fill on complex shapes */
function drawShapeOutline(
  ctx: CanvasRenderingContext2D,
  shape: 'circle' | 'hexagon' | 'diamond' | 'triangle' | 'star' | 'square' | 'ring',
  x: number,
  y: number,
  radius: number
) {
  const r = Math.max(1, radius)
  switch (shape) {
    case 'circle':
      ctx.beginPath()
      ctx.arc(x, y, r, 0, Math.PI * 2)
      ctx.stroke()
      break
    case 'diamond':
      ctx.save()
      ctx.translate(x, y)
      ctx.rotate(Math.PI / 4)
      ctx.strokeRect(-r * 0.75, -r * 0.75, r * 1.5, r * 1.5)
      ctx.restore()
      break
    case 'hexagon': {
      ctx.beginPath()
      for (let i = 0; i < 6; i++) {
        const angle = (Math.PI / 3) * i - Math.PI / 6
        const px = x + r * Math.cos(angle)
        const py = y + r * Math.sin(angle)
        if (i === 0) ctx.moveTo(px, py)
        else ctx.lineTo(px, py)
      }
      ctx.closePath()
      ctx.stroke()
      break
    }
    case 'triangle': {
      ctx.beginPath()
      ctx.moveTo(x, y - r)
      ctx.lineTo(x - r * 0.866, y + r * 0.5)
      ctx.lineTo(x + r * 0.866, y + r * 0.5)
      ctx.closePath()
      ctx.stroke()
      break
    }
    case 'star': {
      const outerR = r
      const innerR = r * 0.45
      ctx.beginPath()
      for (let i = 0; i < 10; i++) {
        const angle = (Math.PI / 5) * i - Math.PI / 2
        const rad = i % 2 === 0 ? outerR : innerR
        const px = x + rad * Math.cos(angle)
        const py = y + rad * Math.sin(angle)
        if (i === 0) ctx.moveTo(px, py)
        else ctx.lineTo(px, py)
      }
      ctx.closePath()
      ctx.stroke()
      break
    }
    case 'square': {
      const half = r * 0.8
      const cornerR = half * 0.25
      ctx.beginPath()
      ctx.roundRect(x - half, y - half, half * 2, half * 2, cornerR)
      ctx.stroke()
      break
    }
    case 'ring': {
      ctx.beginPath()
      ctx.arc(x, y, r, 0, Math.PI * 2)
      ctx.stroke()
      break
    }
  }
}

function drawTooltip(
  ctx: CanvasRenderingContext2D,
  node: SimNode,
  mouseX: number,
  mouseY: number,
  theme: 'dark' | 'light'
) {
  const lines: string[] = [
    node.label,
    `Type: ${node.type}`,
    `Status: ${node.status}`,
    `Domain: ${node.domain}`,
  ]
  if (node.file) lines.push(`File: ${node.file}`)
  if (node.line) lines.push(`Line: ${node.line}`)

  ctx.save()

  const fontSize = 11
  ctx.font = `${fontSize}px system-ui, -apple-system, sans-serif`

  // Measure text
  let maxWidth = 0
  for (const line of lines) {
    const m = ctx.measureText(line)
    if (m.width > maxWidth) maxWidth = m.width
  }

  const boxW = maxWidth + TOOLTIP_PADDING * 2 + 8
  const boxH = lines.length * TOOLTIP_LINE_HEIGHT + TOOLTIP_PADDING * 2

  // Position tooltip offset from cursor
  let tx = mouseX + 16
  let ty = mouseY - boxH - 8

  // Clamp to viewport
  const canvasW = ctx.canvas.width / (window.devicePixelRatio || 1)
  const canvasH = ctx.canvas.height / (window.devicePixelRatio || 1)
  if (tx + boxW > canvasW) tx = mouseX - boxW - 16
  if (ty < 0) ty = mouseY + 16

  // Premium glassmorphic tooltip
  const bgColor = theme === 'dark' ? 'rgba(10, 10, 20, 0.92)' : 'rgba(255, 255, 255, 0.95)'
  const borderColor = theme === 'dark' ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.06)'
  const textColor = theme === 'dark' ? '#c9d1d9' : '#2d3748'

  // Shadow
  ctx.globalAlpha = 1
  ctx.shadowColor = theme === 'dark' ? 'rgba(0,0,0,0.5)' : 'rgba(0,0,0,0.12)'
  ctx.shadowBlur = 20
  ctx.shadowOffsetY = 4
  ctx.fillStyle = bgColor
  ctx.beginPath()
  ctx.roundRect(tx, ty, boxW, boxH, 10)
  ctx.fill()
  ctx.shadowBlur = 0
  ctx.shadowOffsetY = 0

  // Border
  ctx.globalAlpha = 1
  ctx.strokeStyle = borderColor
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.roundRect(tx, ty, boxW, boxH, 10)
  ctx.stroke()

  // Top accent line with node color
  ctx.globalAlpha = 0.6
  ctx.fillStyle = node.color
  ctx.beginPath()
  ctx.roundRect(tx + 1, ty + 1, boxW - 2, 2, [10, 10, 0, 0])
  ctx.fill()

  // Title line with node color
  ctx.globalAlpha = 1
  ctx.fillStyle = node.color
  ctx.font = `bold ${fontSize}px system-ui, -apple-system, sans-serif`
  ctx.textAlign = 'left'
  ctx.textBaseline = 'top'
  ctx.fillText(lines[0], tx + TOOLTIP_PADDING + 4, ty + TOOLTIP_PADDING + 4)

  // Other lines
  ctx.fillStyle = textColor
  ctx.font = `${fontSize}px system-ui, -apple-system, sans-serif`
  for (let i = 1; i < lines.length; i++) {
    ctx.globalAlpha = i === 1 ? 0.8 : 0.6
    ctx.fillText(lines[i], tx + TOOLTIP_PADDING + 4, ty + TOOLTIP_PADDING + 4 + i * TOOLTIP_LINE_HEIGHT)
  }

  ctx.restore()
}

function drawAlarmVignette(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  intensity: number,
  time: number
) {
  const pulse = (Math.sin(time * 0.005) + 1) / 2
  const alpha = intensity * (0.15 + pulse * 0.15)

  ctx.save()

  const gradient = ctx.createRadialGradient(
    width / 2, height / 2, Math.min(width, height) * 0.3,
    width / 2, height / 2, Math.max(width, height) * 0.7
  )
  gradient.addColorStop(0, 'rgba(229, 62, 62, 0)')
  gradient.addColorStop(1, `rgba(229, 62, 62, ${alpha})`)

  ctx.fillStyle = gradient
  ctx.fillRect(0, 0, width, height)
  ctx.restore()
}

function drawRippleEffect(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  elapsed: number,
  theme: 'dark' | 'light'
) {
  const maxRadius = 500
  const progress = elapsed * 0.4 // expands over ~2.5 seconds
  const radius = Math.min(maxRadius, progress * maxRadius)
  const alpha = Math.max(0, 1 - progress)

  if (alpha <= 0) return

  ctx.save()
  ctx.globalAlpha = alpha * 0.4
  ctx.strokeStyle = theme === 'dark' ? '#63b3ed' : '#3182ce'
  ctx.lineWidth = 2
  ctx.beginPath()
  ctx.arc(cx, cy, radius, 0, Math.PI * 2)
  ctx.stroke()

  // Second ring
  const radius2 = Math.max(0, radius - 40)
  if (radius2 > 0) {
    ctx.globalAlpha = alpha * 0.2
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.arc(cx, cy, radius2, 0, Math.PI * 2)
    ctx.stroke()
  }

  ctx.restore()
}

// ============================================================
// Draw cluster-only view (LOD = cluster)
// ============================================================

function drawClusterBubble(
  ctx: CanvasRenderingContext2D,
  cluster: Cluster,
  theme: 'dark' | 'light'
) {
  const cx = cluster.cx ?? 0
  const cy = cluster.cy ?? 0
  const count = cluster.nodeIds.length
  const radius = Math.max(30, 20 + Math.sqrt(count) * 15)

  ctx.save()

  // Single fill with gradient
  ctx.globalAlpha = 0.15
  const fillGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius)
  fillGrad.addColorStop(0, ensureHexColor(cluster.tint) + '40')
  fillGrad.addColorStop(1, ensureHexColor(cluster.tint) + '10')
  ctx.fillStyle = fillGrad
  ctx.beginPath()
  ctx.arc(cx, cy, radius, 0, Math.PI * 2)
  ctx.fill()

  // Border
  ctx.globalAlpha = 0.5
  ctx.strokeStyle = cluster.tint
  ctx.lineWidth = 1.5
  ctx.beginPath()
  ctx.arc(cx, cy, radius, 0, Math.PI * 2)
  ctx.stroke()

  // Icon + label
  ctx.globalAlpha = 0.9
  ctx.fillStyle = theme === 'dark' ? '#e2e8f0' : '#2d3748'
  ctx.font = 'bold 13px system-ui, -apple-system, sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(`${cluster.icon} ${cluster.label}`, cx, cy - 8)

  // Count with tinted color
  ctx.font = '10px system-ui, -apple-system, sans-serif'
  ctx.globalAlpha = 0.5
  ctx.fillStyle = cluster.tint
  ctx.fillText(`${count} nodes`, cx, cy + 10)

  ctx.restore()
}

// ============================================================
// Main Component
// ============================================================

export default function NeuralCanvas({
  theme,
  nodes,
  edges,
  clusters,
  onNodeSelect,
  selectedNodeId,
  activeAnimation,
  onCanvasReady,
}: NeuralCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  // Transform state (pan + zoom) — instant zoom, no interpolation
  const transformRef = useRef({ x: 0, y: 0, zoom: 1 })

  // Interaction state
  const hoveredNodeIdRef = useRef<string | null>(null)
  const isDraggingRef = useRef(false)
  const isPanningRef = useRef(false)
  const dragNodeIdRef = useRef<string | null>(null)
  const wasDraggedRef = useRef(false)
  const mouseDownPosRef = useRef({ x: 0, y: 0 })
  const lastMouseRef = useRef({ x: 0, y: 0 })
  const mousePosRef = useRef({ x: 0, y: 0 })

  // D3 simulation
  const simulationRef = useRef<ReturnType<typeof forceSimulation<SimNode>> | null>(null)
  const simNodesRef = useRef<SimNode[]>([])
  const simLinksRef = useRef<SimLink[]>([])

  // Ambient particles
  const particlesRef = useRef<AmbientParticle[]>([])

  // Animation tracking
  const animStateRef = useRef<AnimationState | null>(null)
  const prevAnimRef = useRef<GraphAnimation | null>(null)

  // Animation frame
  const rafRef = useRef<number>(0)
  const [canvasSize, setCanvasSize] = useState({ width: 0, height: 0 })
  const canvasSizeRef = useRef({ width: 0, height: 0 })
  const clustersRef = useRef<Cluster[]>([])

  // Keep refs in sync with props/state
  useEffect(() => {
    canvasSizeRef.current = canvasSize
  }, [canvasSize])
  useEffect(() => {
    clustersRef.current = clusters
  }, [clusters])

  // ============================================================
  // Initialize simulation when nodes/edges change
  // ============================================================

  useEffect(() => {
    // Convert nodes to sim nodes, preserving existing positions from previous simulation
    const prevNodeMap = new Map<string, SimNode>()
    for (const n of simNodesRef.current) {
      prevNodeMap.set(n.id, n)
    }

    const cs = canvasSizeRef.current
    const simNodes: SimNode[] = nodes.map((n) => {
      const prev = prevNodeMap.get(n.id)
      return {
        ...n,
        x: prev?.x ?? (cs.width || 800) / 2 + (Math.random() - 0.5) * 200,
        y: prev?.y ?? (cs.height || 600) / 2 + (Math.random() - 0.5) * 200,
        vx: prev?.vx ?? 0,
        vy: prev?.vy ?? 0,
        fx: prev?.fx ?? n.fx ?? null,
        fy: prev?.fy ?? n.fy ?? null,
      }
    })

    const nodeMap = new Map<string, SimNode>()
    for (const n of simNodes) {
      nodeMap.set(n.id, n)
    }

    const simLinks: SimLink[] = []
    for (const e of edges) {
      const srcId = edgeSourceId(e)
      const tgtId = edgeTargetId(e)
      const src = nodeMap.get(srcId)
      const tgt = nodeMap.get(tgtId)
      if (src && tgt) {
        simLinks.push({
          source: src,
          target: tgt,
          id: e.id,
          type: e.type,
          weight: e.weight,
          status: e.status,
        })
      }
    }

    simNodesRef.current = simNodes
    simLinksRef.current = simLinks

    // Create or update simulation
    if (simulationRef.current) {
      simulationRef.current.stop()
    }

    const currentClusters = clustersRef.current
    const sim = forceSimulation<SimNode>(simNodes)
      .force(
        'link',
        forceLink<SimNode, SimLink>(simLinks)
          .id((d) => d.id)
          .distance(100)
      )
      .force('charge', forceManyBody().strength(-300))
      .force('center', forceCenter((cs.width || 800) / 2, (cs.height || 600) / 2))
      .force('collide', forceCollide<SimNode>().radius(30))
      .alphaDecay(0.02)
      .on('tick', () => {
        // Update cluster centers
        for (const cluster of currentClusters) {
          const cNodes = simNodes.filter((n) => cluster.nodeIds.includes(n.id))
          if (cNodes.length > 0) {
            cluster.cx = cNodes.reduce((s, n) => s + n.x, 0) / cNodes.length
            cluster.cy = cNodes.reduce((s, n) => s + n.y, 0) / cNodes.length
          }
        }
      })

    simulationRef.current = sim

    return () => {
      sim.stop()
    }
  }, [nodes, edges])

  // ============================================================
  // Update simulation center force on canvas resize (without recreating simulation)
  // ============================================================

  useEffect(() => {
    if (simulationRef.current) {
      simulationRef.current.force('center', forceCenter(
        (canvasSize.width || 800) / 2,
        (canvasSize.height || 600) / 2
      ))
      simulationRef.current.alpha(0.3).restart()
    }
  }, [canvasSize])

  // ============================================================
  // Handle animation prop changes
  // ============================================================

  useEffect(() => {
    if (activeAnimation && activeAnimation !== prevAnimRef.current) {
      animStateRef.current = {
        type: activeAnimation.type,
        startTime: performance.now(),
        targetIds: new Set(activeAnimation.targetNodeIds),
        intensity:
          activeAnimation.intensity === 'critical' ? 1.0 :
          activeAnimation.intensity === 'high' ? 0.75 :
          activeAnimation.intensity === 'medium' ? 0.5 :
          0.25,
      }
      prevAnimRef.current = activeAnimation

      // Auto-clear after duration
      const durations: Record<string, number> = {
        pulse: 2000,
        flow: 3000,
        ripple: 2500,
        flash: 1000,
        death: 2000,
        alarm: 4000,
      }
      const dur = durations[activeAnimation.type] ?? 2000
      const timer = setTimeout(() => {
        animStateRef.current = null
      }, dur)
      return () => clearTimeout(timer)
    }
  }, [activeAnimation])

  // ============================================================
  // Initialize ambient particles
  // ============================================================

  useEffect(() => {
    if (canvasSize.width > 0 && canvasSize.height > 0) {
      particlesRef.current = createAmbientParticles(canvasSize.width, canvasSize.height)
    }
  }, [canvasSize])

  // ============================================================
  // Resize observer
  // ============================================================

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    let lastW = 0, lastH = 0
    const updateSizeThrottled = () => {
      const rect = container.getBoundingClientRect()
      let w = rect.width
      let h = rect.height

      if (w === 0 || h === 0) {
        const parent = container.parentElement
        if (parent) {
          const parentRect = parent.getBoundingClientRect()
          w = parentRect.width
          h = parentRect.height
        }
      }

      if (w === 0 || h === 0) {
        w = window.innerWidth
        h = window.innerHeight - 56
      }

      const fw = Math.floor(w)
      const fh = Math.floor(h)
      // Only update if dimensions actually changed (prevents simulation recreation storm)
      if (fw > 0 && fh > 0 && (fw !== lastW || fh !== lastH)) {
        lastW = fw
        lastH = fh
        setCanvasSize({ width: fw, height: fh })
      }
    }

    const observer = new ResizeObserver(() => {
      updateSizeThrottled()
    })

    observer.observe(container)
    if (container.parentElement) {
      observer.observe(container.parentElement)
    }

    // Reduced fallback timers (removed redundant 1000ms timer)
    updateSizeThrottled()
    const t1 = setTimeout(updateSizeThrottled, 100)
    const t2 = setTimeout(updateSizeThrottled, 400)

    return () => {
      observer.disconnect()
      clearTimeout(t1)
      clearTimeout(t2)
    }
  }, [])

  // ============================================================
  // Canvas setup (DPI scaling)
  // ============================================================

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const dpr = window.devicePixelRatio || 1
    canvas.width = canvasSize.width * dpr
    canvas.height = canvasSize.height * dpr
    canvas.style.width = `${canvasSize.width}px`
    canvas.style.height = `${canvasSize.height}px`

    // NOTE: ctx.scale(dpr, dpr) removed — the render loop resets transform
    // every frame with ctx.setTransform(dpr, 0, 0, dpr, 0, 0), making
    // any initial scale redundant and causing double-scaling on first paint.
  }, [canvasSize])

  // ============================================================
  // Signal canvas ready
  // ============================================================

  useEffect(() => {
    if (onCanvasReady && canvasRef.current) onCanvasReady()
  }, [onCanvasReady])

  // ============================================================
  // Cleanup animation frame on unmount
  // ============================================================

  useEffect(() => {
    return () => {
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current)
      }
    }
  }, [])

  // ============================================================
  // Main render loop
  // ============================================================

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let running = true

    const render = (time: number) => {
      if (!running) return

      const { width, height } = canvasSize
      if (width === 0 || height === 0) {
        rafRef.current = requestAnimationFrame(render)
        return
      }

      const dpr = window.devicePixelRatio || 1
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

      const transform = transformRef.current
      const lod = getLODLevel(transform.zoom)

      // Zoom is applied instantly (no smooth interpolation to avoid lag)

      // 1. Background
      drawBackground(ctx, width, height, theme)

      // 2. Ambient particles
      updateAmbientParticles(particlesRef.current, width, height)
      drawAmbientParticles(ctx, particlesRef.current, theme, time)

      // 3. Apply camera transform
      ctx.save()
      ctx.translate(transform.x, transform.y)
      ctx.scale(transform.zoom, transform.zoom)

      const simNodes = simNodesRef.current
      const simLinks = simLinksRef.current
      const animState = animStateRef.current

      // 4. Draw clusters
      if (lod === 'cluster') {
        // Cluster-only mode: big bubbles
        for (const cluster of clusters) {
          drawClusterBubble(ctx, cluster, theme)
        }
      } else {
        // Cluster boundaries (background)
        // Build cluster node map once per frame (O(n) instead of O(n²) per cluster)
        const clusterNodeMap = new Map<string, SimNode[]>()
        for (const cluster of clusters) {
          const clusterNodes = simNodes.filter((n) => cluster.nodeIds.includes(n.id))
          clusterNodeMap.set(cluster.id, clusterNodes)
        }
        for (const cluster of clusters) {
          const cNodes = clusterNodeMap.get(cluster.id) || []
          drawCluster(ctx, cluster, cNodes, theme)
        }
      }

      // 5. Draw edges
      if (lod !== 'cluster') {
        for (const link of simLinks) {
          const srcId = typeof link.source === 'string' ? link.source : link.source.id
          const tgtId = typeof link.target === 'string' ? link.target : link.target.id

          const isActive =
            animState?.type === 'flow' &&
            (animState.targetIds.has(srcId) || animState.targetIds.has(tgtId))

          const flowProgress = isActive ? ((time - (animState?.startTime ?? 0)) % 2000) / 2000 : -1

          drawEdge(ctx, link, theme, isActive, flowProgress, time)
        }
      }

      // 6. Draw nodes based on LOD
      const hoveredId = hoveredNodeIdRef.current

      if (lod === 'cluster') {
        // No individual nodes drawn
      } else if (lod === 'file') {
        // File-level: one node per file type
        const fileNodes = simNodes.filter((n) => n.type === 'file')
        for (const node of fileNodes) {
          const isSelected = node.id === selectedNodeId
          const isHovered = node.id === hoveredId
          drawNode(ctx, node, theme, isSelected, isHovered, animState, time)
        }
      } else {
        // Symbol level: all nodes
        // Viewport culling
        const viewLeft = -transform.x / transform.zoom - 100
        const viewTop = -transform.y / transform.zoom - 100
        const viewRight = viewLeft + width / transform.zoom + 200
        const viewBottom = viewTop + height / transform.zoom + 200

        for (const node of simNodes) {
          // Skip if outside viewport
          if (
            node.x < viewLeft || node.x > viewRight ||
            node.y < viewTop || node.y > viewBottom
          ) {
            continue
          }

          const isSelected = node.id === selectedNodeId
          const isHovered = node.id === hoveredId
          drawNode(ctx, node, theme, isSelected, isHovered, animState, time)
        }
      }

      // 7. Ripple effect
      if (animState?.type === 'ripple') {
        const elapsed = (time - animState.startTime) / 1000
        // Ripple from center of target nodes
        const targetNodes = simNodes.filter((n) => animState.targetIds.has(n.id))
        if (targetNodes.length > 0) {
          const rcx = targetNodes.reduce((s, n) => s + n.x, 0) / targetNodes.length
          const rcy = targetNodes.reduce((s, n) => s + n.y, 0) / targetNodes.length
          drawRippleEffect(ctx, rcx, rcy, elapsed, theme)
        }
      }

      ctx.restore()

      // 8. Tooltip (drawn in screen space, not world space)
      if (hoveredId && lod !== 'cluster') {
        const hoveredNode = simNodes.find((n) => n.id === hoveredId)
        if (hoveredNode) {
          // Convert node position to screen coords
          const screenX = hoveredNode.x * transform.zoom + transform.x
          const screenY = hoveredNode.y * transform.zoom + transform.y
          drawTooltip(ctx, hoveredNode, mousePosRef.current.x, mousePosRef.current.y, theme)
        }
      }

      // 9. Alarm vignette (screen space)
      if (animState?.type === 'alarm') {
        drawAlarmVignette(ctx, width, height, animState.intensity, time)
      }

      // 10. Premium HUD info
      ctx.save()
      const hudY = height - 12
      const hudX = 12
      const hudText = `Zoom ${transform.zoom.toFixed(2)}x  ·  LOD ${lod}  ·  ${simNodes.length} nodes  ·  ${simLinks.length} edges`
      
      // HUD background pill
      ctx.font = '10px system-ui, -apple-system, sans-serif'
      const hudWidth = ctx.measureText(hudText).width + 16
      ctx.globalAlpha = theme === 'dark' ? 0.5 : 0.6
      ctx.fillStyle = theme === 'dark' ? 'rgba(10,10,20,0.6)' : 'rgba(255,255,255,0.7)'
      ctx.beginPath()
      ctx.roundRect(hudX, hudY - 14, hudWidth, 20, 6)
      ctx.fill()
      
      // HUD border
      ctx.strokeStyle = theme === 'dark' ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'
      ctx.lineWidth = 0.5
      ctx.globalAlpha = 0.4
      ctx.beginPath()
      ctx.roundRect(hudX, hudY - 14, hudWidth, 20, 6)
      ctx.stroke()
      
      // HUD text
      ctx.globalAlpha = theme === 'dark' ? 0.5 : 0.55
      ctx.fillStyle = theme === 'dark' ? '#a0aec0' : '#64748b'
      ctx.textAlign = 'left'
      ctx.textBaseline = 'middle'
      ctx.fillText(hudText, hudX + 8, hudY - 4)
      ctx.restore()

      rafRef.current = requestAnimationFrame(render)
    }

    rafRef.current = requestAnimationFrame(render)

    // Signal ready
    if (onCanvasReady) {
      onCanvasReady()
    }

    return () => {
      running = false
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current)
      }
    }
  }, [canvasSize, theme, selectedNodeId, clusters, onCanvasReady])

  // ============================================================
  // Mouse interaction handlers
  // ============================================================

  const screenToWorld = useCallback(
    (sx: number, sy: number) => {
      const t = transformRef.current
      return {
        x: (sx - t.x) / t.zoom,
        y: (sy - t.y) / t.zoom,
      }
    },
    []
  )

  const findNodeAtPos = useCallback(
    (worldX: number, worldY: number): SimNode | null => {
      // Search in reverse (top-drawn nodes first)
      const simNodes = simNodesRef.current
      for (let i = simNodes.length - 1; i >= 0; i--) {
        const n = simNodes[i]
        const dx = worldX - n.x
        const dy = worldY - n.y
        const hitRadius = n.radius + 5 // small tolerance
        if (dx * dx + dy * dy <= hitRadius * hitRadius) {
          return n
        }
      }
      return null
    },
    []
  )

  const handleMouseDown = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const rect = canvasRef.current?.getBoundingClientRect()
      if (!rect) return

      const sx = e.clientX - rect.left
      const sy = e.clientY - rect.top
      const world = screenToWorld(sx, sy)

      lastMouseRef.current = { x: e.clientX, y: e.clientY }
      mouseDownPosRef.current = { x: e.clientX, y: e.clientY }
      wasDraggedRef.current = false

      const hitNode = findNodeAtPos(world.x, world.y)
      if (hitNode) {
        // Start dragging node
        dragNodeIdRef.current = hitNode.id
        isDraggingRef.current = true
        // Fix node position during drag
        hitNode.fx = hitNode.x
        hitNode.fy = hitNode.y
        simulationRef.current?.alphaTarget(0.3).restart()
      } else {
        // Start panning
        isPanningRef.current = true
      }
    },
    [screenToWorld, findNodeAtPos]
  )

  const handleMouseMove = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const rect = canvasRef.current?.getBoundingClientRect()
      if (!rect) return

      const sx = e.clientX - rect.left
      const sy = e.clientY - rect.top

      mousePosRef.current = { x: sx, y: sy }

      // Check if moved enough to count as drag
      const dx = e.clientX - mouseDownPosRef.current.x
      const dy = e.clientY - mouseDownPosRef.current.y
      if (dx * dx + dy * dy > 25) {
        wasDraggedRef.current = true
      }

      if (isDraggingRef.current && dragNodeIdRef.current) {
        // Drag node
        const world = screenToWorld(sx, sy)
        const simNodes = simNodesRef.current
        const node = simNodes.find((n) => n.id === dragNodeIdRef.current)
        if (node) {
          node.fx = world.x
          node.fy = world.y
        }
      } else if (isPanningRef.current) {
        // Pan canvas
        const panDx = e.clientX - lastMouseRef.current.x
        const panDy = e.clientY - lastMouseRef.current.y
        transformRef.current.x += panDx
        transformRef.current.y += panDy
      } else {
        // Hover detection
        const world = screenToWorld(sx, sy)
        const hitNode = findNodeAtPos(world.x, world.y)
        hoveredNodeIdRef.current = hitNode ? hitNode.id : null

        // Update cursor
        if (canvasRef.current) {
          canvasRef.current.style.cursor = hitNode ? 'pointer' : 'grab'
        }
      }

      lastMouseRef.current = { x: e.clientX, y: e.clientY }
    },
    [screenToWorld, findNodeAtPos]
  )

  const handleMouseUp = useCallback(
    (_e: React.MouseEvent<HTMLCanvasElement>) => {
      if (isDraggingRef.current && dragNodeIdRef.current) {
        const simNodes = simNodesRef.current
        const node = simNodes.find((n) => n.id === dragNodeIdRef.current)
        if (node) {
          // Release fixed position
          node.fx = null
          node.fy = null
        }
        simulationRef.current?.alphaTarget(0)
      }

      isDraggingRef.current = false
      isPanningRef.current = false
      dragNodeIdRef.current = null
    },
    []
  )

  const handleWheel = useCallback(
    (e: WheelEvent) => {
      e.preventDefault()

      const rect = canvasRef.current?.getBoundingClientRect()
      if (!rect) return

      const t = transformRef.current
      const sx = e.clientX - rect.left
      const sy = e.clientY - rect.top

      // Normalize deltaY based on deltaMode for consistent zoom across devices
      let normalizedDelta = e.deltaY
      if (e.deltaMode === 1) {
        // Line mode (common on trackpads) — reduce multiplier to avoid oversensitivity
        normalizedDelta *= 20
      } else if (e.deltaMode === 2) {
        // Page mode
        normalizedDelta *= 400
      }

      // Use normalized pixel-mode sensitivity
      const delta = -normalizedDelta * ZOOM_SENSITIVITY

      // Clamp delta to prevent extreme zoom jumps (tighter clamp for smoother feel)
      const clampedDelta = Math.max(-0.15, Math.min(0.15, delta))

      // Zoom toward mouse position (instant, no interpolation, no lag)
      const newZoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, t.zoom * (1 + clampedDelta)))
      const zoomRatio = newZoom / t.zoom

      t.x = sx - (sx - t.x) * zoomRatio
      t.y = sy - (sy - t.y) * zoomRatio
      t.zoom = newZoom
    },
    []
  )

  const handleMouseLeave = useCallback(() => {
    hoveredNodeIdRef.current = null
    isPanningRef.current = false
    isDraggingRef.current = false
    dragNodeIdRef.current = null
    if (canvasRef.current) {
      canvasRef.current.style.cursor = 'grab'
    }
  }, [])

  // ============================================================
  // Handle click for node selection (separate from drag)
  // ============================================================

  const handleClick = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      // Only handle as click if we weren't dragging
      if (wasDraggedRef.current) return

      const rect = canvasRef.current?.getBoundingClientRect()
      if (!rect) return

      const sx = e.clientX - rect.left
      const sy = e.clientY - rect.top
      const world = screenToWorld(sx, sy)
      const hitNode = findNodeAtPos(world.x, world.y)
      onNodeSelect(hitNode ? hitNode.id : null)
    },
    [screenToWorld, findNodeAtPos, onNodeSelect]
  )

  // ============================================================
  // Native wheel event listener (passive: false for preventDefault)
  // React's onWheel is passive by default — preventDefault() silently fails
  // causing page to scroll while zooming. Use native addEventListener instead.
  // ============================================================

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    canvas.addEventListener('wheel', handleWheel, { passive: false })

    return () => {
      canvas.removeEventListener('wheel', handleWheel)
    }
  }, [handleWheel])

  // ============================================================
  // Render
  // ============================================================

  return (
    <div
      ref={containerRef}
      className="w-full h-full"
      style={{ background: theme === 'dark' ? NEURAL_COLORS.darkBg : NEURAL_COLORS.lightBg, position: 'relative' }}
    >
      <canvas
        ref={canvasRef}
        style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', cursor: 'grab' }}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseLeave}
        onClick={handleClick}
      />
    </div>
  )
}
