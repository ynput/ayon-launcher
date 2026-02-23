#!/usr/bin/env bash

# Build AYON using existing virtual environment.

# Colors for terminal

RST='\033[0m'             # Text Reset

# Regular Colors
Black='\033[0;30m'        # Black
Red='\033[0;31m'          # Red
Green='\033[0;32m'        # Green
Yellow='\033[0;33m'       # Yellow
Blue='\033[0;34m'         # Blue
Purple='\033[0;35m'       # Purple
Cyan='\033[0;36m'         # Cyan
White='\033[0;37m'        # White

# Bold
BBlack='\033[1;30m'       # Black
BRed='\033[1;31m'         # Red
BGreen='\033[1;32m'       # Green
BYellow='\033[1;33m'      # Yellow
BBlue='\033[1;34m'        # Blue
BPurple='\033[1;35m'      # Purple
BCyan='\033[1;36m'        # Cyan
BWhite='\033[1;37m'       # White

# Bold High Intensity
BIBlack='\033[1;90m'      # Black
BIRed='\033[1;91m'        # Red
BIGreen='\033[1;92m'      # Green
BIYellow='\033[1;93m'     # Yellow
BIBlue='\033[1;94m'       # Blue
BIPurple='\033[1;95m'     # Purple
BICyan='\033[1;96m'       # Cyan
BIWhite='\033[1;97m'      # White

args=$@
disable_submodule_update=0
while :; do
  case $1 in
    --no-submodule-update)
      disable_submodule_update=1
      ;;
    --)
      shift
      break
      ;;
    *)
      break
  esac

  shift
done

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
  echo $(cd $(dirname "$1") || return; pwd)/$(basename "$1")
}

repo_root=$(dirname $(dirname "$(realpath ${BASH_SOURCE[0]})"))

print_art() {
  echo -e "${BGreen}"
  cat <<-EOF

                    ▄██▄
         ▄███▄ ▀██▄ ▀██▀ ▄██▀ ▄██▀▀▀██▄    ▀███▄      █▄
        ▄▄ ▀██▄  ▀██▄  ▄██▀ ██▀      ▀██▄  ▄  ▀██▄    ███
       ▄██▀  ██▄   ▀ ▄▄ ▀  ██         ▄██  ███  ▀██▄  ███
      ▄██▀    ▀██▄   ██    ▀██▄      ▄██▀  ███    ▀██ ▀█▀
     ▄██▀      ▀██▄  ▀█      ▀██▄▄▄▄██▀    █▀      ▀██▄

     ·  · - =[ by YNPUT ]:[ http://ayon.ynput.io ]= - ·  ·

EOF
  echo -e "${RST}"
}

##############################################################################
# Install UV
# Arguments:
#   None
# Returns:
#   None
###############################################################################
install_uv () {
  command -v uv >/dev/null 2>&1 || {
    curl -LsSf https://astral.sh/uv/install.sh | sh
  }
}

##############################################################################
# Clean pyc files in specified directory
# Globals:
#   None
# Arguments:
#   Optional path to clean
# Returns:
#   None
###############################################################################
clean_pyc () {
  local path
  path=$repo_root
  echo -e "${BIGreen}>>>${RST} Cleaning pyc at [ ${BIWhite}$path${RST} ] ... \c"
  find "$path" -path ./build -o -regex '^.*\(__pycache__\|\.py[co]\)$' -delete

  echo -e "${BIGreen}DONE${RST}"
}

create_env () {
  # Directories
  pushd "$repo_root" > /dev/null || return > /dev/null

  uv venv --allow-existing && uv sync --all-extras || { echo -e "${BIRed}!!!${RST} Venv installation failed"; return 1; }
  if [ $? -ne 0 ] ; then
    echo -e "${BIRed}!!!${RST} Virtual environment creation failed."
    return 1
  fi

  echo -e "${BIGreen}>>>${RST} Cleaning cache files ..."
  clean_pyc

  if [ -d "$repo_root/.git" ]; then
    echo -e "${BIGreen}>>>${RST} Installing pre-commit hooks ..."
    uv run pre-commit install
  fi
}

install_runtime_dependencies () {
  pushd "$repo_root" > /dev/null || return > /dev/null

  echo -e "${BIGreen}>>>${RST} Installing runtime dependencies ..."
  uv run python "$repo_root/tools/runtime_dependencies.py" "$@"
}

fix_macos_build () {
  macoscontents="$1"
  macosdir="$macoscontents/MacOS"
  ayonexe="$macosdir/ayon"
  ayonmacosexe="$macosdir/ayon_macos"
  tmp_ayonexe="$macosdir/ayon_tmp"

  # Fix codesign bug by creating copy of executable, removing source
  #   executable and replacing by the copy
  #   - this will clear cache of codesign
  cp "$ayonexe" "$tmp_ayonexe"
  rm "$ayonexe"
  mv "$tmp_ayonexe" "$ayonexe"

  if [ -f "$ayonmacosexe" ]; then
    cp "$ayonmacosexe" "$tmp_ayonexe"
    rm "$ayonmacosexe"
    mv "$tmp_ayonexe" "$ayonmacosexe"
  fi

  # fix code signing issue
  if [ $("arch") == "arm64" ]; then
    echo -e "${BIGreen}>>>${RST} Fixing code signatures for ARM64 ..."
    codesign --remove-signature "$ayonexe" || { echo -e "${BIRed}FAILED${RST}"; return 1; }
    if [ -f "$ayonmacosexe" ]; then
      codesign --remove-signature "$ayonmacosexe" || { echo -e "${BIRed}FAILED${RST}"; return 1; }
    fi
  fi
  echo -e "${BIGreen}>>>${RST} Fixing code signatures ..."
  codesign --remove-signature "$ayonexe" || { echo -e "${BIRed}FAILED${RST}"; return 1; }
  if [ -f "$ayonmacosexe" ]; then
    codesign --remove-signature "$ayonmacosexe" || { echo -e "${BIRed}FAILED${RST}"; return 1; }
  fi
}
# Main
build_ayon () {
  should_make_installer=$1

  # Directories
  pushd "$repo_root" > /dev/null || return > /dev/null

  version_command="import os;import re;version={};exec(open(os.path.join('$repo_root', 'version.py')).read(), version);print(version['__version__']);"
  ayon_version="$(uv run python <<< ${version_command})"

  echo -e "${BIYellow}---${RST} Cleaning build directory ..."
  rm -rf "$repo_root/build" && mkdir "$repo_root/build" > /dev/null
  rm -rf "$repo_root/shim/dist" > /dev/null

  echo -e "${BIGreen}>>>${RST} Building AYON ${BIWhite}[${RST} ${BIGreen}$ayon_version${RST} ${BIWhite}]${RST}"
  echo -e "${BIGreen}>>>${RST} Cleaning cache files ..."
  clean_pyc

  if [ "$disable_submodule_update" == 1 ]; then
    echo -e "${BIYellow}***${RST} Not updating submodules ..."
  else
    echo -e "${BIGreen}>>>${RST} Making sure submodules are up-to-date ..."
    git submodule update --init --recursive || { echo -e "${BIRed}!!!${RST} Git submodule update failed"; return 1; }
  fi
  echo -e "${BIGreen}>>>${RST} Building ..."
  uv --no-color pip freeze > "$repo_root/build/requirements.txt"
  uv run python "$repo_root/tools/_venv_deps.py"

  build_command="build"
  if [[ "$OSTYPE" == "darwin"* ]]; then
    build_command="bdist_mac"
  fi

  pushd "$repo_root/shim"

  uv run python "$repo_root/shim/setup.py" $build_command &> "$repo_root/shim/build.log" || { echo -e "${BIRed}------------------------------------------${RST}"; cat "$repo_root/shim/build.log"; echo -e "${BIRed}------------------------------------------${RST}"; echo -e "${BIRed}!!!${RST} Build failed, see the build log."; return 1; }
  if [[ "$OSTYPE" == "darwin"* ]]; then
    fix_macos_build "$repo_root/shim/build/AYON.app/Contents"
  fi
  popd
  "$repo_root/.venv/bin/python" "$repo_root/setup.py" $build_command &> "$repo_root/build/build.log" || { echo -e "${BIRed}------------------------------------------${RST}"; cat "$repo_root/build/build.log"; echo -e "${BIRed}------------------------------------------${RST}"; echo -e "${BIRed}!!!${RST} Build failed, see the build log."; return 1; }
  uv run python "$repo_root/tools/build_post_process.py" "build" || { echo -e "${BIRed}!!!>${RST} ${BIYellow}Failed to process dependencies${RST}"; return 1; }
  if [[ "$OSTYPE" == "darwin"* ]]; then
    fix_macos_build "$repo_root/build/AYON $ayon_version.app/Contents"
  fi

  if [[ "$should_make_installer" == 1 ]]; then
    echo -e "${BIGreen}>>>${RST} Making installer ..."
    make_installer_raw
  fi

  echo -e "${BICyan}>>>${RST} All done. You will find AYON and build log in \c"
  echo -e "${BIWhite}$repo_root/build${RST} directory."
}

make_installer_raw() {
  uv run python "$repo_root/tools/build_post_process.py" "make-installer" || { echo -e "${BIRed}!!!>${RST} ${BIYellow}Failed to create installer${RST}"; return 1; }
}

make_installer() {
  make_installer_raw
  echo -e "${BICyan}>>>${RST} All done. You will find AYON and build log in \c"
  echo -e "${BIWhite}$repo_root/build${RST} directory."
}

installer_post_process() {
  uv run python "$repo_root/tools/installer_post_process.py" "$@"
}

run_from_code() {
  pushd "$repo_root" > /dev/null || return > /dev/null
  echo -e "${BIGreen}>>>${RST} Running AYON from code ..."
  uv run python "$repo_root/start.py" "$@"
}

create_container () {
  if [ ! -f "$repo_root/build/docker-image.id" ]; then
    echo -e "${BIRed}!!!${RST} Docker command failed, cannot find image id."
    exit 1
  fi
  local id=$(<"$repo_root/build/docker-image.id")
  echo -e "${BIYellow}---${RST} Creating container from $id ..."
  cid="$(docker create $id bash)"
  if [ $? -ne 0 ] ; then
    echo -e "${BIRed}!!!${RST} Cannot create container."
    exit 1
  fi
}

retrieve_build_log () {
  outdir=$1
  create_container
  echo -e "${BIYellow}***${RST} Copying build log to ${BIWhite}${outdir}/build.log${RST}"
  docker cp "$cid:/opt/ayon-launcher/build/build.log" $outdir
}

docker_build() {
  variant=$1
  if [ -z $variant ]; then
    variant="ubuntu"
  fi
  if [ $variant == "ubuntu" ]; then
    dockerfile="Dockerfile"
  else
    dockerfile="Dockerfile.$variant"
  fi

  if [ ! -f "$repo_root/$dockerfile" ]; then
    echo -e "${BIRed}!!!${RST} Dockerfile for specifed platform ${BIWhite}$variant${RST} doesn't exist."
    exit 1
  fi
  echo -e "${BIGreen}>>>${RST} Using Dockerfile for ${BIWhite}$variant${RST} ..."

  outdir="$repo_root/build_$variant"
  qtenv=""
  for var in "$@"
  do
    if [[ "$var" == '--use-pyside2' ]]; then
      qtenv="pyside2"
      outdir="${outdir}_pyside2"
      break
    fi
  done
  pushd "$repo_root" > /dev/null || return > /dev/null

  echo -e "${BIYellow}---${RST} Cleaning build directory ..."
  rm -rf "$outdir" && mkdir "$outdir" > /dev/null

  local version_command="import os;exec(open(os.path.join('$repo_root', 'version.py')).read());print(__version__);"
  local launcher_version="$(uv run python <<< ${version_command})"

  echo -e "${BIGreen}>>>${RST} Running docker build ..."
  docker build --pull --iidfile ${outdir}/docker-image.id --build-arg CUSTOM_QT_BINDING=$qtenv --build-arg BUILD_DATE=$(date -u +'%Y-%m-%dT%H:%M:%SZ') --build-arg VERSION=$launcher_version -t ynput/ayon-launcher-$variant:$launcher_version -f $dockerfile .
  if [ $? -ne 0 ] ; then
    echo $?
    echo -e "${BIRed}!!!${RST} Docker build failed."
    retrieve_build_log $outdir
    return 1
  fi


  echo -e "${BIGreen}>>>${RST} Copying build from container ..."
  create_container
  echo -e "${BIYellow}---${RST} Copying ..."
  docker cp "$cid:/opt/ayon-launcher/build/output" $outdir || { echo -e "${BIRed}!!!${RST} Copying build failed."; return $?; }
  docker cp "$cid:/opt/ayon-launcher/build/build.log" $outdir || { echo -e "${BIRed}!!!${RST} Copying log failed."; return $?; }
  docker cp "$cid:/opt/ayon-launcher/build/metadata.json" $outdir || { echo -e "${BIRed}!!!${RST} Copying json failed."; return $?; }
  docker cp "$cid:/opt/ayon-launcher/build/installer" $outdir || { echo -e "${BIRed}!!!${RST} Copying installer failed."; return $?; }

  echo -e "${BIGreen}>>>${RST} Fixing user ownership ..."
  local username="$(logname)"
  chown -R $username $outdir

  echo -e "${BIGreen}>>>${RST} All done, you can delete container:"
  echo -e "${BIYellow}$cid${RST}"
}

default_help() {
  print_art
  echo "AYON desktop application tool"
  echo ""
  echo "Usage: ./make.sh [target]"
  echo ""
  echo "Runtime targets:"
  echo "  create-env                    Create UV venv and update venv by lock file"
  echo "  install-runtime-dependencies  Install runtime dependencies (Qt binding)"
  echo "      --use-pyside2                 Install PySide2 instead of PySide6."
  echo "  install-runtime               Alias for 'install-runtime-dependencies'"
  echo "  build                         Build desktop application"
  echo "  make-installer                Make desktop application installer"
  echo "  build-make-installer          Build desktop application and make installer"
  echo "  upload                        Upload installer to server"
  echo "  create-server-package         Create package ready for AYON server"
  echo "  run                           Run desktop application from code"
  echo "  docker-build [variant]        Build AYON using Docker. Variant can be 'debian', 'rocky8' or 'rocky9'"
  echo "      --use-pyside2                 Use PySide2 instead of PySide6."
  echo ""
}

main() {
  install_uv
  # Use first argument, lower and keep only characters
  function_name="$(echo "$1" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z]*//g')"

  case $function_name in
    "createenv")
      create_env || return_code=$?
      exit $return_code
      ;;
    "installruntimedependencies"|"installruntime")
      install_runtime_dependencies "${@:2}" || return_code=$?
      exit $return_code
      ;;
    "build"|"buildayon")
      build_ayon 0 || return_code=$?
      exit $return_code
      ;;
    "makeinstaller")
      make_installer || return_code=$?
      exit $return_code
      ;;
    "buildmakeinstaller")
      build_ayon 1 || return_code=$?
      exit $return_code
      ;;
    "upload")
      installer_post_process upload "${@:2}" || return_code=$?
      exit $return_code
      ;;
    "run")
      run_from_code "${@:2}" || return_code=$?
      exit $return_code
      ;;
    "dockerbuild")
      docker_build "${@:2}" || return_code=$?
      exit $return_code
      ;;
  esac

  if [ "$function_name" != "" ]; then
    echo -e "${BIRed}!!!${RST} Unknown function name: $function_name"
  fi

  default_help
  exit $return_code
}

main "$@"
