ARG BASE_IMAGE
FROM ${BASE_IMAGE}
ARG FRONTEND_REVISION
ARG RUN_AS
USER root
RUN rm -rf /candidate/static && mkdir -p /candidate/static
COPY static/ /candidate/static/
LABEL org.peixian.frontend.revision="${FRONTEND_REVISION}"
USER ${RUN_AS}
