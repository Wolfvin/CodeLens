'use client'

import React from 'react'

interface ErrorBoundaryProps {
  children: React.ReactNode
  fallback?: React.ReactNode
}

interface ErrorBoundaryState {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('[ErrorBoundary] Caught error:', error, errorInfo)
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback
      }
      return (
        <div className="flex items-center justify-center h-full w-full p-8" style={{ backgroundColor: '#0a0a0f' }}>
          <div className="text-center space-y-4 max-w-md">
            <div className="text-4xl">🧠</div>
            <h2 className="text-lg font-bold" style={{ color: '#e2e8f0' }}>
              Neural Workspace Error
            </h2>
            <p className="text-sm" style={{ color: '#718096' }}>
              Something went wrong rendering the workspace. This is likely a runtime error.
            </p>
            <pre
              className="text-xs text-left p-3 rounded-lg overflow-auto max-h-40"
              style={{ backgroundColor: 'rgba(255,255,255,0.03)', color: '#fc8181' }}
            >
              {this.state.error?.message ?? 'Unknown error'}
            </pre>
            <button
              className="px-4 py-2 rounded-lg text-sm font-medium transition-colors"
              style={{ backgroundColor: 'rgba(139, 92, 246, 0.15)', color: '#b794f4' }}
              onClick={() => this.setState({ hasError: false, error: null })}
            >
              Try Again
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
