# syntax=docker/dockerfile:1
FROM python:3.15-slim AS build

WORKDIR /src
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir build && python -m build --wheel

FROM python:3.15-slim

RUN useradd --no-create-home --shell /usr/sbin/nologin kcct
COPY --from=build /src/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -f /tmp/*.whl

USER kcct
WORKDIR /work
ENTRYPOINT ["kc-config-templater"]
CMD ["--help"]
