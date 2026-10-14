# Multi-stage Dockerfile for Next.js 15 App Router
FROM node:22-slim AS base
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1

# 1. Install dependencies
FROM base AS deps
COPY package.json ./
COPY package-lock.json ./
COPY scripts/ ./scripts/
RUN mkdir -p /app/public
RUN npm ci --legacy-peer-deps

# 2. Build the application
FROM base AS builder
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN mkdir -p /app/public
RUN npm run build

# 3. Production runner
FROM base AS runner
ENV NODE_ENV=production
ENV PORT=8080
# Local Docker default only; Cloud Run provides the deployed API URL at runtime.
ENV API_BASE=http://localhost:8080
EXPOSE 8080

# Copy necessary files from builder. Owned by the unprivileged `node` user: `next start` writes its cache under .next/.
COPY --from=builder --chown=node:node /app/package.json ./package.json
COPY --from=builder --chown=node:node /app/node_modules ./node_modules
COPY --from=builder --chown=node:node /app/.next ./.next
COPY --from=builder --chown=node:node /app/public ./public

# Do not run as root (the base image ships the `node` user, uid 1000)
USER node

CMD ["npm", "start", "--", "-p", "8080"]
