'use client'

import React from 'react'

interface CanvasSkeletonProps {
  theme: 'dark' | 'light'
}

export function CanvasSkeleton({ theme }: CanvasSkeletonProps) {
  const dark = theme === 'dark'
  
  return (
    <div
      className="absolute inset-0 flex flex-col items-center justify-center gap-4"
      style={{
        backgroundColor: dark ? '#0a0a0f' : '#f7fafc',
      }}
    >
      {/* Animated neural network skeleton */}
      <div className="relative w-64 h-48">
        {/* Simulated nodes */}
        {[
          { x: 30, y: 40, size: 18, delay: 0 },
          { x: 90, y: 20, size: 14, delay: 0.2 },
          { x: 150, y: 50, size: 22, delay: 0.4 },
          { x: 210, y: 30, size: 12, delay: 0.6 },
          { x: 50, y: 100, size: 16, delay: 0.1 },
          { x: 120, y: 90, size: 20, delay: 0.3 },
          { x: 180, y: 110, size: 14, delay: 0.5 },
          { x: 70, y: 140, size: 10, delay: 0.7 },
          { x: 140, y: 135, size: 18, delay: 0.15 },
          { x: 200, y: 130, size: 12, delay: 0.45 },
        ].map((node, i) => (
          <div
            key={i}
            className="absolute rounded-full"
            style={{
              left: node.x,
              top: node.y,
              width: node.size,
              height: node.size,
              backgroundColor: dark ? 'rgba(183, 148, 244, 0.15)' : 'rgba(139, 92, 246, 0.1)',
              animation: `skeletonPulse 2s ease-in-out ${node.delay}s infinite`,
            }}
          />
        ))}
        
        {/* Simulated edges */}
        <svg className="absolute inset-0 w-full h-full" style={{ opacity: 0.08 }}>
          <line x1="39" y1="49" x2="97" y2="27" stroke={dark ? '#b794f4' : '#7c3aed'} strokeWidth="1" />
          <line x1="97" y1="27" x2="161" y2="61" stroke={dark ? '#b794f4' : '#7c3aed'} strokeWidth="1" />
          <line x1="161" y1="61" x2="216" y2="36" stroke={dark ? '#b794f4' : '#7c3aed'} strokeWidth="1" />
          <line x1="58" y1="108" x2="130" y2="100" stroke={dark ? '#b794f4' : '#7c3aed'} strokeWidth="1" />
          <line x1="130" y1="100" x2="187" y2="117" stroke={dark ? '#b794f4' : '#7c3aed'} strokeWidth="1" />
          <line x1="39" y1="49" x2="58" y2="108" stroke={dark ? '#b794f4' : '#7c3aed'} strokeWidth="1" />
          <line x1="130" y1="100" x2="149" y2="144" stroke={dark ? '#b794f4' : '#7c3aed'} strokeWidth="1" />
        </svg>
      </div>
      
      {/* Loading text */}
      <div className="flex items-center gap-2">
        <div
          className="w-2 h-2 rounded-full animate-pulse"
          style={{ backgroundColor: '#b794f4', boxShadow: '0 0 8px rgba(183, 148, 246, 0.5)' }}
        />
        <span
          className="text-xs font-medium animate-pulse"
          style={{ color: dark ? '#718096' : '#94a3b8' }}
        >
          Initializing neural workspace...
        </span>
      </div>
      
      <style jsx>{`
        @keyframes skeletonPulse {
          0%, 100% { opacity: 0.3; transform: scale(1); }
          50% { opacity: 1; transform: scale(1.15); }
        }
      `}</style>
    </div>
  )
}
