# Matched Control and console for the theft dialogue release.
# BASE_IMAGE is the currently deployed, schema-v11-compatible Control image.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
ARG SOURCE_REVISION
LABEL org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.peixian.source.commit="${SOURCE_REVISION}" \
      org.peixian.alignment="theft-dialogue-simplification" \
      org.peixian.frontend.preserved="" \
      org.peixian.control.schema.max="11" \
      org.peixian.dialogue="theft-clarification-v1"
ENV PX_BACKEND_V6=1
COPY services/peixian-control/control /app/control
COPY services/peixian-control/shared /app/shared
COPY packages/peixian-console/dist /app/static
