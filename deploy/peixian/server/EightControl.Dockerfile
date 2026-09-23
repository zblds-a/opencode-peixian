ARG BASE_IMAGE
FROM ${BASE_IMAGE}
ARG SOURCE_SHA
LABEL org.opencontainers.image.revision="${SOURCE_SHA}" org.peixian.eight-data-tools="3.0.0"
COPY services/peixian-control/control /candidate/control
COPY services/peixian-control/shared /candidate/shared
