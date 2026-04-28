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

COPY . /opt/jupyterbook.pub/

RUN cd js && \
    npm install && \
    npm run build
RUN python3 -m pip install /opt/jupyterbook.pub

# Install default book theme
RUN mkdir -p /opt/templates && \
    cd /opt/templates && \
    curl -L https://github.com/myst-templates/book-theme/archive/43b78aca9895f5a7929bf7f5591791a4bf1adcfb.zip -o theme.zip && \
    unzip theme.zip && \
    rm theme.zip && \
    mkdir -p site/myst/ && \
    mv book-theme* site/myst/book-theme && \
    cd site/myst/book-theme && \
    npm ci --ignore-scripts
ENV JUPYTERBOOK2BUILDER__templates_path=/opt/templates


# Overriden for dokku
CMD ["python3", "-m", "jupyterbook_pub.app"]
