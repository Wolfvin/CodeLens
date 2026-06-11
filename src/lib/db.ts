// ============================================================
// CodeLens — Prisma Database Client
// ============================================================
// NOTE: This client is configured but not yet used by any API route.
// To activate, create a prisma/schema.prisma and run prisma generate.
// See _archive/prisma/schema.prisma for a reference schema.
// ============================================================

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