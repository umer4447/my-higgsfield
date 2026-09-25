-- CreateEnum
CREATE TYPE "Mode" AS ENUM ('IMAGE', 'MOTION');

-- CreateEnum
CREATE TYPE "Engine" AS ENUM ('FLUX', 'TURBO', 'KONTEXT');

-- CreateEnum
CREATE TYPE "PresetFamily" AS ENUM ('CAMERA', 'LIGHT', 'STOCK', 'WORLD');

-- CreateEnum
CREATE TYPE "Move" AS ENUM ('PUSH', 'PULL', 'ORBIT', 'WHIP', 'CRANE', 'FLOAT', 'SHAKE', 'DOLLY');

-- CreateEnum
CREATE TYPE "JobStatus" AS ENUM ('QUEUED', 'RUNNING', 'SUCCEEDED', 'PARTIAL', 'FAILED', 'CANCELLED');

-- CreateEnum
CREATE TYPE "AssetStatus" AS ENUM ('PENDING', 'RUNNING', 'READY', 'FAILED');

-- CreateEnum
CREATE TYPE "LedgerReason" AS ENUM ('SIGNUP_GRANT', 'PLAN_GRANT', 'MONTHLY_REFRESH', 'JOB_DEBIT', 'JOB_REFUND', 'ADMIN_ADJUSTMENT');

-- CreateTable
CREATE TABLE "users" (
    "id" UUID NOT NULL,
    "isAnonymous" BOOLEAN NOT NULL DEFAULT true,
    "handle" VARCHAR(32),
    "handleLower" VARCHAR(32),
    "email" VARCHAR(320),
    "emailVerifiedAt" TIMESTAMP(3),
    "credits" INTEGER NOT NULL DEFAULT 40,
    "planId" VARCHAR(64) NOT NULL,
    "creditsResetAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "lastSeenAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "deletedAt" TIMESTAMP(3),

    CONSTRAINT "users_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "sessions" (
    "id" UUID NOT NULL,
    "userId" UUID NOT NULL,
    "tokenHash" CHAR(64) NOT NULL,
    "familyId" UUID NOT NULL,
    "userAgent" VARCHAR(400),
    "ipHash" CHAR(64),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "expiresAt" TIMESTAMP(3) NOT NULL,
    "revokedAt" TIMESTAMP(3),

    CONSTRAINT "sessions_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "plans" (
    "id" VARCHAR(64) NOT NULL,
    "name" VARCHAR(64) NOT NULL,
    "tagline" VARCHAR(200) NOT NULL,
    "priceCents" INTEGER NOT NULL,
    "monthlyCredits" INTEGER NOT NULL,
    "maxBatch" INTEGER NOT NULL DEFAULT 4,
    "maxConcurrentJobs" INTEGER NOT NULL DEFAULT 1,
    "generatePerMinute" INTEGER NOT NULL DEFAULT 6,
    "motionEnabled" BOOLEAN NOT NULL DEFAULT false,
    "perks" TEXT[],
    "featured" BOOLEAN NOT NULL DEFAULT false,
    "sortOrder" INTEGER NOT NULL DEFAULT 0,
    "active" BOOLEAN NOT NULL DEFAULT true,

    CONSTRAINT "plans_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "generation_models" (
    "id" VARCHAR(64) NOT NULL,
    "name" VARCHAR(64) NOT NULL,
    "vendor" VARCHAR(64) NOT NULL,
    "mode" "Mode" NOT NULL,
    "engine" "Engine" NOT NULL,
    "creditCost" INTEGER NOT NULL,
    "maxBatch" INTEGER NOT NULL DEFAULT 4,
    "blurb" VARCHAR(300) NOT NULL,
    "badge" VARCHAR(16),
    "sortOrder" INTEGER NOT NULL DEFAULT 0,
    "active" BOOLEAN NOT NULL DEFAULT true,

    CONSTRAINT "generation_models_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "presets" (
    "slug" VARCHAR(64) NOT NULL,
    "name" VARCHAR(64) NOT NULL,
    "family" "PresetFamily" NOT NULL,
    "mode" "Mode" NOT NULL,
    "description" VARCHAR(400) NOT NULL,
    "template" VARCHAR(2000) NOT NULL,
    "move" "Move",
    "previewPrompt" VARCHAR(400) NOT NULL,
    "previewSeed" INTEGER NOT NULL,
    "sortOrder" INTEGER NOT NULL DEFAULT 0,
    "active" BOOLEAN NOT NULL DEFAULT true,

    CONSTRAINT "presets_pkey" PRIMARY KEY ("slug")
);

-- CreateTable
CREATE TABLE "ratios" (
    "id" VARCHAR(16) NOT NULL,
    "label" VARCHAR(16) NOT NULL,
    "width" INTEGER NOT NULL,
    "height" INTEGER NOT NULL,
    "note" VARCHAR(64) NOT NULL,
    "sortOrder" INTEGER NOT NULL DEFAULT 0,
    "active" BOOLEAN NOT NULL DEFAULT true,

    CONSTRAINT "ratios_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "jobs" (
    "id" UUID NOT NULL,
    "userId" UUID NOT NULL,
    "idempotencyKey" VARCHAR(128) NOT NULL,
    "requestHash" CHAR(64) NOT NULL,
    "status" "JobStatus" NOT NULL DEFAULT 'QUEUED',
    "mode" "Mode" NOT NULL,
    "prompt" VARCHAR(2000) NOT NULL,
    "composedPrompt" VARCHAR(6000) NOT NULL,
    "modelId" VARCHAR(64) NOT NULL,
    "presetSlug" VARCHAR(64),
    "ratioId" VARCHAR(16) NOT NULL,
    "batch" INTEGER NOT NULL,
    "seed" INTEGER,
    "move" "Move",
    "creditsDebited" INTEGER NOT NULL,
    "creditsRefunded" INTEGER NOT NULL DEFAULT 0,
    "attempts" INTEGER NOT NULL DEFAULT 0,
    "error" VARCHAR(500),
    "queuedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "startedAt" TIMESTAMP(3),
    "finishedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "jobs_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "assets" (
    "id" UUID NOT NULL,
    "userId" UUID NOT NULL,
    "jobId" UUID,
    "mode" "Mode" NOT NULL,
    "status" "AssetStatus" NOT NULL DEFAULT 'PENDING',
    "prompt" VARCHAR(2000) NOT NULL,
    "composedPrompt" VARCHAR(6000) NOT NULL,
    "modelId" VARCHAR(64) NOT NULL,
    "presetSlug" VARCHAR(64),
    "ratioId" VARCHAR(16) NOT NULL,
    "seed" INTEGER NOT NULL,
    "move" "Move",
    "width" INTEGER NOT NULL,
    "height" INTEGER NOT NULL,
    "creditCost" INTEGER NOT NULL,
    "authorHandle" VARCHAR(32) NOT NULL,
    "storageKey" VARCHAR(400),
    "contentHash" CHAR(64),
    "bytes" INTEGER,
    "published" BOOLEAN NOT NULL DEFAULT false,
    "publishedAt" TIMESTAMP(3),
    "likeCount" INTEGER NOT NULL DEFAULT 0,
    "seeded" BOOLEAN NOT NULL DEFAULT false,
    "error" VARCHAR(500),
    "version" INTEGER NOT NULL DEFAULT 1,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "deletedAt" TIMESTAMP(3),

    CONSTRAINT "assets_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "likes" (
    "userId" UUID NOT NULL,
    "assetId" UUID NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "likes_pkey" PRIMARY KEY ("userId","assetId")
);

-- CreateTable
CREATE TABLE "ledger_entries" (
    "id" BIGSERIAL NOT NULL,
    "userId" UUID NOT NULL,
    "jobId" UUID,
    "reason" "LedgerReason" NOT NULL,
    "delta" INTEGER NOT NULL,
    "balanceAfter" INTEGER NOT NULL,
    "note" VARCHAR(200),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "ledger_entries_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "audit_logs" (
    "id" BIGSERIAL NOT NULL,
    "userId" UUID,
    "action" VARCHAR(64) NOT NULL,
    "subject" VARCHAR(128),
    "metadata" JSONB,
    "ipHash" CHAR(64),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "audit_logs_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "users_handleLower_key" ON "users"("handleLower");

-- CreateIndex
CREATE UNIQUE INDEX "users_email_key" ON "users"("email");

-- CreateIndex
CREATE INDEX "users_planId_idx" ON "users"("planId");

-- CreateIndex
CREATE INDEX "users_createdAt_idx" ON "users"("createdAt" DESC);

-- CreateIndex
CREATE INDEX "users_lastSeenAt_idx" ON "users"("lastSeenAt");

-- CreateIndex
CREATE UNIQUE INDEX "sessions_tokenHash_key" ON "sessions"("tokenHash");

-- CreateIndex
CREATE INDEX "sessions_userId_idx" ON "sessions"("userId");

-- CreateIndex
CREATE INDEX "sessions_familyId_idx" ON "sessions"("familyId");

-- CreateIndex
CREATE INDEX "sessions_expiresAt_idx" ON "sessions"("expiresAt");

-- CreateIndex
CREATE INDEX "generation_models_mode_active_sortOrder_idx" ON "generation_models"("mode", "active", "sortOrder");

-- CreateIndex
CREATE INDEX "presets_family_mode_active_idx" ON "presets"("family", "mode", "active");

-- CreateIndex
CREATE INDEX "jobs_userId_createdAt_id_idx" ON "jobs"("userId", "createdAt" DESC, "id");

-- CreateIndex
CREATE INDEX "jobs_status_queuedAt_idx" ON "jobs"("status", "queuedAt");

-- CreateIndex
CREATE UNIQUE INDEX "jobs_userId_idempotencyKey_key" ON "jobs"("userId", "idempotencyKey");

-- CreateIndex
CREATE INDEX "assets_userId_createdAt_id_idx" ON "assets"("userId", "createdAt" DESC, "id");

-- CreateIndex
CREATE INDEX "assets_publishedAt_id_idx" ON "assets"("publishedAt" DESC, "id");

-- CreateIndex
CREATE INDEX "assets_jobId_idx" ON "assets"("jobId");

-- CreateIndex
CREATE INDEX "assets_contentHash_idx" ON "assets"("contentHash");

-- CreateIndex
CREATE INDEX "assets_presetSlug_publishedAt_idx" ON "assets"("presetSlug", "publishedAt" DESC);

-- CreateIndex
CREATE INDEX "likes_assetId_idx" ON "likes"("assetId");

-- CreateIndex
CREATE INDEX "ledger_entries_userId_createdAt_id_idx" ON "ledger_entries"("userId", "createdAt" DESC, "id");

-- CreateIndex
CREATE UNIQUE INDEX "ledger_entries_jobId_reason_key" ON "ledger_entries"("jobId", "reason");

-- CreateIndex
CREATE INDEX "audit_logs_userId_createdAt_idx" ON "audit_logs"("userId", "createdAt" DESC);

-- CreateIndex
CREATE INDEX "audit_logs_action_createdAt_idx" ON "audit_logs"("action", "createdAt" DESC);

-- AddForeignKey
ALTER TABLE "users" ADD CONSTRAINT "users_planId_fkey" FOREIGN KEY ("planId") REFERENCES "plans"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "sessions" ADD CONSTRAINT "sessions_userId_fkey" FOREIGN KEY ("userId") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "jobs" ADD CONSTRAINT "jobs_userId_fkey" FOREIGN KEY ("userId") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "jobs" ADD CONSTRAINT "jobs_modelId_fkey" FOREIGN KEY ("modelId") REFERENCES "generation_models"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "jobs" ADD CONSTRAINT "jobs_presetSlug_fkey" FOREIGN KEY ("presetSlug") REFERENCES "presets"("slug") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "jobs" ADD CONSTRAINT "jobs_ratioId_fkey" FOREIGN KEY ("ratioId") REFERENCES "ratios"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "assets" ADD CONSTRAINT "assets_userId_fkey" FOREIGN KEY ("userId") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "assets" ADD CONSTRAINT "assets_jobId_fkey" FOREIGN KEY ("jobId") REFERENCES "jobs"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "assets" ADD CONSTRAINT "assets_modelId_fkey" FOREIGN KEY ("modelId") REFERENCES "generation_models"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "assets" ADD CONSTRAINT "assets_presetSlug_fkey" FOREIGN KEY ("presetSlug") REFERENCES "presets"("slug") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "assets" ADD CONSTRAINT "assets_ratioId_fkey" FOREIGN KEY ("ratioId") REFERENCES "ratios"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "likes" ADD CONSTRAINT "likes_userId_fkey" FOREIGN KEY ("userId") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "likes" ADD CONSTRAINT "likes_assetId_fkey" FOREIGN KEY ("assetId") REFERENCES "assets"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ledger_entries" ADD CONSTRAINT "ledger_entries_userId_fkey" FOREIGN KEY ("userId") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ledger_entries" ADD CONSTRAINT "ledger_entries_jobId_fkey" FOREIGN KEY ("jobId") REFERENCES "jobs"("id") ON DELETE SET NULL ON UPDATE CASCADE;
