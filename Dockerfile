FROM python:3.14-trixie AS builder

RUN apt update >/dev/null && apt install --yes nodejs npm >/dev/null

RUN mkdir -p /opt/jupyterbook.pub
WORKDIR /opt/jupyterbook.pub

COPY . /opt/jupyterbook.pub

RUN cd js && \
    npm install && \
    npm run build
RUN python3 -m pip wheel . --wheel-dir /opt/dist/

FROM python:3.14-trixie

COPY --from=builder /opt/dist/*.whl /opt/dist/
RUN python3 -m pip install --no-cache /opt/dist/*.whl

CMD ["python3", "-m", "jupyterbook_pub.app"]
