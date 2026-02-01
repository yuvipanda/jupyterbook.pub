FROM python:3.14-trixie

RUN apt update >/dev/null && apt install --yes nodejs npm >/dev/null

RUN mkdir -p /opt/jupyterbook.pub
WORKDIR /opt/jupyterbook.pub

COPY . /opt/jupyterbook.pub

RUN cd js && \
    npm install && \
    npm run build
RUN python3 -m pip install /opt/jupyterbook.pub