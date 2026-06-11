import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'CodeLens — Live Codebase Reference Intelligence',
  description: 'Scan your codebase using tree-sitter AST parsing and explore structured graph data via REST API and WebSocket.',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" className="dark">
      <body className="bg-[#0a0a0f] text-gray-100 antialiased min-h-screen">
        {children}
      </body>
    </html>
  )
}
