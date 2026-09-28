FROM sha256:fab95db567990491c7addadaca6ab2be13a08fa183ef911155cfb1346f57a1aa
USER root
RUN rm -rf /candidate/static && mkdir -p /candidate/static
COPY static/ /candidate/static/
LABEL org.peixian.frontend.revision="6cc9efc7ccc23e06eb3b89d3e03242f8f78588d5" \
      org.peixian.backend.base.image="sha256:fab95db567990491c7addadaca6ab2be13a08fa183ef911155cfb1346f57a1aa"
USER 10001:10001
