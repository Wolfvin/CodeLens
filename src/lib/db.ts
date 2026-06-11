/**
 * Prisma Client — UNUSED
 *
 * TODO: This module is not imported by any API route or other module.
 * It is kept for future use when persistent storage is needed.
 * If Prisma is not needed, consider removing this file and the
 * @prisma/client dependency to reduce bundle size.
 */
import { PrismaClient } from '@prisma/client'

const globalForPrisma = globalThis as unknown as {
  prisma: PrismaClient | undefined
}

let dbInstance: PrismaClient

try {
  dbInstance =
    globalForPrisma.prisma ??
    new PrismaClient({
      log: process.env.NODE_ENV === 'development' ? ['query'] : ['error'],
    })

  if (process.env.NODE_ENV !== 'production') globalForPrisma.prisma = dbInstance

  // Handle connection errors gracefully — don't crash the app on DB failure
  dbInstance.$connect().catch((err) => {
    console.error('[CodeLens] Failed to connect to database:', err)
    console.error('[CodeLens] Database features will be unavailable. Check DATABASE_URL in .env')
  })
} catch (err) {
  console.error('[CodeLens] Failed to initialize Prisma client:', err)
  // Create a fallback instance that will fail gracefully on any query
  dbInstance = new PrismaClient({
    log: ['error'],
  })
}

export const db = dbInstance
