FROM node:24-bookworm-slim@sha256:d6aa754f16b3197301076f047b5def2f02ea1dbbc2ca920407d46d7ec7f87b20 AS node
FROM ghcr.io/astral-sh/uv:0.10.9@sha256:10902f58a1606787602f303954cea099626a4adb02acbac4c69920fe9d278f82 AS uv
FROM python:3.11-slim-bookworm@sha256:0a310eeecf4e1f5a0743f9a6520c90c88d089c903ca5fd283f501e3a805f5f89 AS check

ENV UV_CACHE_DIR=/opt/uv-cache \
    UV_PYTHON_DOWNLOADS=never \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=uv /uv /uvx /usr/local/bin/

RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates git libstdc++6 make procps socat \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash --uid 1000 quarry \
    && chmod 700 /home/quarry

WORKDIR /workspace

COPY pyproject.toml uv.lock .python-version Makefile ./
COPY web/package.json web/package-lock.json ./web/
COPY scripts/local-checks.mjs ./scripts/

RUN make deps \
    && chown -R quarry:quarry /workspace /opt/uv-cache /opt/ms-playwright

COPY --chown=quarry:quarry src/quarry/components/builtin ./src/quarry/components/builtin
COPY --chown=quarry:quarry web ./web

USER quarry
RUN npm --prefix web run build

COPY --chown=quarry:quarry README.md AGENTS.md CLAUDE.md .verify.toml .gitignore ./
COPY --chown=quarry:quarry docs ./docs
COPY --chown=quarry:quarry scripts ./scripts
COPY --chown=quarry:quarry src ./src
COPY --chown=quarry:quarry tests ./tests

CMD ["make", "check"]
