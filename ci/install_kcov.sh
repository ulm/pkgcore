#!/bin/bash
#
# Download, build, and install the latest kcov release.

set -eu

INSTALLED_KCOV_VERSION=""
KCOV_DEFAULT_VERSION="v36"
GITHUB_KCOV="https://api.github.com/repos/SimonKagstrom/kcov/releases/latest"

# Usage: download and install the latest kcov version by default.
# Fall back to $KCOV_DEFAULT_VERSION from the kcov archive if the latest is unavailable.
KCOV_VERSION=$(curl -s ${GITHUB_KCOV} | jq -Mr .tag_name || echo)
KCOV_VERSION=${KCOV_VERSION+$KCOV_DEFAULT_VERSION}

# determine installed version if it exists
if [[ -x "${HOME}"/kcov/bin/kcov ]]; then
	INSTALLED_KCOV_VERSION=v$(~/kcov/bin/kcov --version | sed 's/.* //')
fi

KCOV_TGZ="https://github.com/SimonKagstrom/kcov/archive/${KCOV_DEFAULT_VERSION}.tar.gz"

# check if a cached version exists
if [[ ${INSTALLED_KCOV_VERSION} == ${KCOV_VERSION} ]]; then
	echo kcov-${KCOV_VERSION} already installed
	exit 0
fi

rm -rf kcov-latest
mkdir kcov-latest
curl -L "${KCOV_TGZ}" | tar xzvf - -C kcov-latest --strip-components 1

cd kcov-latest
mkdir build
cd build
cmake -DCMAKE_INSTALL_PREFIX=~/kcov -DCMAKE_BUILD_TYPE=RelWithDebInfo ..
make
make install
