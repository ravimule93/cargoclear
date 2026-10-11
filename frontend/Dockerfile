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

# Copy necessary files from builder
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public

CMD ["npm", "start", "--", "-p", "8080"]
