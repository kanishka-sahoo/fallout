# Lockfile sandbox (BUILD.md §6.3 step 2). Holds nothing but npm: the executor mounts a copy of
# the repo checkout (no .git, no tokens) and runs one time-anchored, script-free install.
FROM node:22-alpine
RUN npm config set fund false --location=global && npm config set audit false --location=global
USER node
WORKDIR /work
ENTRYPOINT ["npm", "install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund"]
