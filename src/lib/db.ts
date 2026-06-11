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

export const db =
  globalForPrisma.prisma ??
  new PrismaClient({
    log: process.env.NODE_ENV === 'development' ? ['query'] : ['error'],
  })

if (process.env.NODE_ENV !== 'production') globalForPrisma.prisma = db