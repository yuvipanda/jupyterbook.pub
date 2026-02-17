FROM python:3.14-trixie

RUN apt update >/dev/null && apt install --yes nodejs npm >/dev/null

# Install a new enough version of rclone
RUN curl https://rclone.org/install.sh |  bash

# Install micromamba for use by the jupyterlite builder
RUN curl -L https://micro.mamba.pm/install.sh | bash
# Make sure we can find micromamba
ENV PATH=/root/.local/bin:${PATH}

RUN mkdir -p /opt/jupyterbook.pub
WORKDIR /opt/jupyterbook.pub

COPY . /opt/jupyterbook.pub

RUN cd js && \
    npm install && \
    npm run build
RUN python3 -m pip install /opt/jupyterbook.pub

# Overriden for dokku
CMD ["python3", "-m", "jupyterbook_pub.app"]
