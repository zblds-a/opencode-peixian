FROM peixian-build-python:20260928
ARG SOURCE_REVISION
LABEL org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.peixian.control.schema.min="0" \
      org.peixian.control.schema.max="11" \
      org.peixian.control.config.max="4" \
      org.peixian.runtime.protocol="2" \
      org.peixian.runtime.capabilities="idle_activity_v1" \
      org.peixian.worker.protocol="2" \
      org.peixian.worker.capabilities="runtime_pool_v1,runtime_pool_wait_v1,idle_activity_v1" \
      org.peixian.business.run.protocol="1"
ENV PX_BACKEND_V6=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY services/peixian-control/requirements.lock /app/requirements.lock
COPY deploy/peixian/offline-release/wheels-control /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r /app/requirements.lock \
    && useradd -u 10001 -m peixian \
    && rm -rf /wheels
COPY services/peixian-control/control /app/control
COPY services/peixian-control/shared /app/shared
COPY packages/peixian-console/dist /app/static
RUN mkdir /data && chown 10001:10001 /data
USER 10001:10001
EXPOSE 8080
CMD ["uvicorn","control.app:app","--host","0.0.0.0","--port","8080","--no-access-log","--timeout-graceful-shutdown","5"]
