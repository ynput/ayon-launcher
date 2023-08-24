#!/usr/bin/env bash

# Colors for terminal

RST='\033[0m'             # Text Reset
BIGreen='\033[1;92m'      # Green
BIYellow='\033[1;93m'     # Yellow
BIRed='\033[1;91m'        # Red

##############################################################################
# Return absolute path
# Globals:
#   None
# Arguments:
#   Path to resolve
# Returns:
#   None
###############################################################################
realpath () {
  echo $(cd $(dirname "$1"); pwd)/$(basename "$1")
}

create_container () {
  if [ ! -f "$launcher_root/build/docker-image.id" ]; then
    echo -e "${BIRed}!!!${RST} Docker command failed, cannot find image id."
    exit 1
  fi
  local id=$(<"$launcher_root/build/docker-image.id")
  echo -e "${BIYellow}---${RST} Creating container from $id ..."
  cid="$(docker create $id bash)"
  if [ $? -ne 0 ] ; then
    echo -e "${BIRed}!!!${RST} Cannot create container."
    exit 1
  fi
}

retrieve_build_log () {
  create_container
  echo -e "${BIYellow}***${RST} Copying build log to ${BIWhite}$launcher_root/build/build.log${RST}"
  docker cp "$cid:/opt/ayon-launcher/build/build.log" "$launcher_root/build"
  docker cp "$cid:/opt/ayon-launcher/build/metadata.json" "$launcher_root/build"
  docker cp "$cid:/opt/ayon-launcher/build/installer" "$launcher_root/build"
}

launcher_root=$(realpath $(dirname $(dirname "${BASH_SOURCE[0]}")))


if [ -z $1 ]; then
    dockerfile="Dockerfile"
else
  dockerfile="Dockerfile.$1"
  if [ ! -f "$launcher_root/$dockerfile" ]; then
    echo -e "${BIRed}!!!${RST} Dockerfile for specifed platform ${BIWhite}$1${RST} doesn't exist."
    exit 1
  else
    echo -e "${BIGreen}>>>${RST} Using Dockerfile for ${BIWhite}$1${RST} ..."
  fi
fi

# Main
main () {
  launcher_root=$(realpath $(dirname $(dirname "${BASH_SOURCE[0]}")))
  pushd "$launcher_root" > /dev/null || return > /dev/null

  echo -e "${BIYellow}---${RST} Cleaning build directory ..."
  rm -rf "$launcher_root/build" && mkdir "$launcher_root/build" > /dev/null

  local version_command="import os;exec(open(os.path.join('$launcher_root', 'version.py')).read());print(__version__);"
  local launcher_version="$(python <<< ${version_command})"

  echo -e "${BIGreen}>>>${RST} Running docker build ..."
  # docker build --pull --no-cache -t pypeclub/openpype:$launcher_version .
  docker build --pull --iidfile $launcher_root/build/docker-image.id --build-arg BUILD_DATE=$(date -u +'%Y-%m-%dT%H:%M:%SZ') --build-arg VERSION=$launcher_version -t ynput/ayon_launcher:$launcher_version -f $dockerfile .
  if [ $? -ne 0 ] ; then
    echo $?
    echo -e "${BIRed}!!!${RST} Docker build failed."
    retrieve_build_log
    return 1
  fi

  echo -e "${BIGreen}>>>${RST} Copying build from container ..."
  create_container
  echo -e "${BIYellow}---${RST} Copying ..."
  docker cp "$cid:/opt/ayon-launcher/build/output" "$launcher_root/build"
  docker cp "$cid:/opt/ayon-launcher/build/build.log" "$launcher_root/build"
  if [ $? -ne 0 ] ; then
    echo -e "${BIRed}!!!${RST} Copying failed."
    return 1
  fi

  echo -e "${BIGreen}>>>${RST} Fixing user ownership ..."
  local username="$(logname)"
  chown -R $username ./build

  echo -e "${BIGreen}>>>${RST} All done, you can delete container:"
  echo -e "${BIYellow}$cid${RST}"
}

return_code=0
main || return_code=$?
exit $return_code
