FROM sha256:45e9edc201088fd1a28b4d5846a59a1d67c6f857525a4e9f30171503d0ee7c91
USER root
RUN rm -rf /candidate/static && mkdir -p /candidate/static
COPY static/ /candidate/static/
LABEL org.peixian.frontend.revision="ed97ccee114a36b32c32585bf5f4d0be0eeed45e" \
      org.peixian.backend.base.image="sha256:45e9edc201088fd1a28b4d5846a59a1d67c6f857525a4e9f30171503d0ee7c91"
USER 10001:10001
