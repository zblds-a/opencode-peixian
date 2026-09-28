FROM peixian-agent:euler-20260928 AS bun
FROM peixian-build-python:20260928
ARG SOURCE_REVISION
LABEL org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.peixian.runtime.protocol="2" \
      org.peixian.runtime.capabilities="idle_activity_v1" \
      org.peixian.business.run.protocol="1"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=bun /usr/local/bin/bun /usr/local/bin/bun
COPY services/peixian-control/requirements.lock /app/requirements.lock
COPY deploy/peixian/offline-release/wheels-control /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r /app/requirements.lock \
    && useradd -u 10001 -m peixian \
    && rm -rf /wheels
COPY services/peixian-control/gateway /app/gateway
COPY services/peixian-control/shared /app/shared
USER 10001:10001
EXPOSE 8080
CMD ["uvicorn","gateway.app:app","--host","0.0.0.0","--port","8080","--no-access-log"]
