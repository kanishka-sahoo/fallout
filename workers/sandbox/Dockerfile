# Lockfile sandbox. The image contains only npm. The fix executor mounts a copy of the repo
# checkout (no .git, no tokens) and runs one install with --before=S and no install scripts.
FROM node:22-alpine
RUN npm config set fund false --location=global && npm config set audit false --location=global
USER node
WORKDIR /work
ENTRYPOINT ["npm", "install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund"]
