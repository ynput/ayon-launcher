# Build AYON docker image
FROM ubuntu:focal AS builder
ARG PYTHON_VERSION=3.9.13
ARG BUILD_DATE
ARG VERSION

ARG CUSTOM_QT_BINDING=""
ENV QT_BINDING=$CUSTOM_QT_BINDING

LABEL description="Docker Image to build and run AYON Launcher under Ubuntu"
LABEL org.opencontainers.image.name="ynput/ayon-launcher"
LABEL org.opencontainers.image.title="AYON Launcher Docker Image"
LABEL org.opencontainers.image.url="https://ayon.ynput.io/"
LABEL org.opencontainers.image.source="https://github.com/ynput/ayon-launcher"
LABEL org.opencontainers.image.documentation="https://ayon.ynput.io"
LABEL org.opencontainers.image.created=$BUILD_DATE
LABEL org.opencontainers.image.version=$VERSION

USER root

ARG DEBIAN_FRONTEND=noninteractive

# update base
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        bash \
        git \
        cmake \
        make \
        curl \
        wget \
        build-essential \
        checkinstall \
        libssl-dev \
        zlib1g-dev \
        libbz2-dev \
        libreadline-dev \
        libsqlite3-dev \
        llvm \
        libncursesw5-dev \
        xz-utils \
        tk-dev \
        libxml2-dev \
        libxmlsec1-dev \
        libffi-dev \
        liblzma-dev \
        patchelf

SHELL ["/bin/bash", "-c"]


RUN mkdir /opt/ayon-launcher

# download and install pyenv
RUN curl https://pyenv.run | bash \
    && echo 'export PATH="$HOME/.pyenv/bin:$PATH"'>> $HOME/init_pyenv.sh \
    && echo 'eval "$(pyenv init -)"' >> $HOME/init_pyenv.sh \
    && echo 'eval "$(pyenv virtualenv-init -)"' >> $HOME/init_pyenv.sh \
    && echo 'eval "$(pyenv init --path)"' >> $HOME/init_pyenv.sh

# install python with pyenv
RUN source $HOME/init_pyenv.sh \
    && pyenv install ${PYTHON_VERSION}

COPY . /opt/ayon-launcher/

RUN chmod +x /opt/ayon-launcher/tools/make.sh

WORKDIR /opt/ayon-launcher

# set local python version
RUN source $HOME/init_pyenv.sh \
    && pyenv local ${PYTHON_VERSION}

# build launcher and installer
RUN source $HOME/init_pyenv.sh \
    && ./tools/make.sh create-env \
    && ./tools/make.sh install-runtime \
    && ./tools/make.sh build-make-installer
