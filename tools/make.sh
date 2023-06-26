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

poetry_verbosity=""
while :; do
  case $1 in
    --verbose)
      poetry_verbosity="-vvv"
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

             . .   ..     .    ..
        _oOOP3OPP3Op_. .
     .PPpo~·   ··   ~2p.  ··  ····  ·  ·
    ·Ppo · .pPO3Op.· · O:· · · ·
   .3Pp · oP3'· 'P33· · 4 ··   ·  ·   · ·· ·  ·  ·
  ·~OP    3PO·  .Op3    : · ··  _____  _____  _____
  ·P3O  · oP3oP3O3P' · · ·   · /    /·/    /·/    /
   O3:·   O3p~ ·       ·:· · ·/____/·/____/ /____/
   'P ·   3p3·  oP3~· ·.P:· ·  · ··  ·   · ·· ·  ·  ·
  · ':  · Po'  ·Opo'· .3O· .  o[ by Pype Club ]]]==- - - ·  ·
    · '_ ..  ·    . _OP3··  ·  ·https://openpype.io·· ·
         ~P3·OPPPO3OP~ · ··  ·
           ·  ' '· ·  ·· · · · ··  ·

EOF
  echo -e "${RST}"
}

##############################################################################
# Detect required version of python
# Globals:
#   colors
#   PYTHON
# Arguments:
#   None
# Returns:
#   None
###############################################################################
detect_python () {
  echo -e "${BIGreen}>>>${RST} Using python \c"
  command -v python >/dev/null 2>&1 || { echo -e "${BIRed}- NOT FOUND${RST} ${BIYellow}You need Python 3.9 installed to continue.${RST}"; return 1; }
  local version_command
  version_command="import sys;print('{0}.{1}'.format(sys.version_info[0], sys.version_info[1]))"
  local python_version
  python_version="$(python <<< ${version_command})"
  oIFS="$IFS"
  IFS=.
  set -- $python_version
  IFS="$oIFS"
  if [ "$1" -ge "3" ] && [ "$2" -ge "9" ] ; then
    if [ "$2" -gt "9" ] ; then
      echo -e "${BIWhite}[${RST} ${BIRed}$1.$2 ${BIWhite}]${RST} - ${BIRed}FAILED${RST} ${BIYellow}Version is new and unsupported, use${RST} ${BIPurple}3.9.x${RST}"; return 1;
    else
      echo -e "${BIWhite}[${RST} ${BIGreen}$1.$2${RST} ${BIWhite}]${RST}"
    fi
  else
    command -v python >/dev/null 2>&1 || { echo -e "${BIRed}$1.$2$ - ${BIRed}FAILED${RST} ${BIYellow}Version is old and unsupported${RST}"; return 1; }
  fi
}

install_poetry () {
  echo -e "${BIGreen}>>>${RST} Installing Poetry ..."
  export POETRY_HOME="$repo_root/.poetry"
  export POETRY_VERSION="1.3.2"
  command -v curl >/dev/null 2>&1 || { echo -e "${BIRed}!!!${RST}${BIYellow} Missing ${RST}${BIBlue}curl${BIYellow} command.${RST}"; return 1; }
  curl -sSL https://install.python-poetry.org/ | python -
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
  # Main
  detect_python || return 1

  # Directories

  if [[ -z $POETRY_HOME ]]; then
    export POETRY_HOME="$repo_root/.poetry"
  fi


  pushd "$repo_root" > /dev/null || return > /dev/null

  echo -e "${BIGreen}>>>${RST} Reading Poetry ... \c"
  if [ -f "$POETRY_HOME/bin/poetry" ]; then
    echo -e "${BIGreen}OK${RST}"
  else
    echo -e "${BIYellow}NOT FOUND${RST}"
    install_poetry || { echo -e "${BIRed}!!!${RST} Poetry installation failed"; return 1; }
  fi

  if [ -f "$repo_root/poetry.lock" ]; then
    echo -e "${BIGreen}>>>${RST} Updating dependencies ..."
  else
    echo -e "${BIGreen}>>>${RST} Installing dependencies ..."
  fi

  "$POETRY_HOME/bin/poetry" install --no-root $poetry_verbosity || { echo -e "${BIRed}!!!${RST} Poetry environment installation failed"; return 1; }
  if [ $? -ne 0 ] ; then
    echo -e "${BIRed}!!!${RST} Virtual environment creation failed."
    return 1
  fi

  echo -e "${BIGreen}>>>${RST} Cleaning cache files ..."
  clean_pyc

  # reinstall these because of bug in poetry? or cx_freeze?
  # cx_freeze will crash on missing __pychache__ on these but
  # reinstalling them solves the problem.
  echo -e "${BIGreen}>>>${RST} Post-venv creation fixes ..."
  local openpype_index=$("$POETRY_HOME/bin/poetry" run python "$repo_root/tools/parse_pyproject.py" tool.poetry.source.0.url)
  echo -e "${BIGreen}-   ${RST} Using index: ${BIWhite}$openpype_index${RST}"
  "$POETRY_HOME/bin/poetry" run python -m pip install --disable-pip-version-check --force-reinstall pip
  echo -e "${BIGreen}>>>${RST} Installing pre-commit hooks ..."
  "$POETRY_HOME/bin/poetry" run pre-commit install
}

install_runtime_dependencies () {
  # Directories
  if [[ -z $POETRY_HOME ]]; then
    export POETRY_HOME="$repo_root/.poetry"
  fi

  echo -e "${BIGreen}>>>${RST} Reading Poetry ... \c"
  if [ -f "$POETRY_HOME/bin/poetry" ]; then
    echo -e "${BIGreen}OK${RST}"
  else
    echo -e "${BIYellow}NOT FOUND${RST}"
    echo -e "${BIYellow}***${RST} We need to install Poetry and virtual env ..."
    create_env
  fi

  pushd "$repo_root" > /dev/null || return > /dev/null

  echo -e "${BIGreen}>>>${RST} Installing runtime dependencies ..."
  "$POETRY_HOME/bin/poetry" run python "$repo_root/tools/runtime_dependencies.py"
}

# Main
build_ayon () {
  detect_python || return 1
  $make_installer = $1

  # Directories
  pushd "$repo_root" > /dev/null || return > /dev/null

  version_command="import os;import re;version={};exec(open(os.path.join('$repo_root', 'version.py')).read(), version);print(re.search(r'(\d+\.\d+.\d+).*', version['__version__'])[1]);"
  ayon_version="$(python <<< ${version_command})"

  if [[ -z $POETRY_HOME ]]; then
    export POETRY_HOME="$repo_root/.poetry"
  fi

  echo -e "${BIYellow}---${RST} Cleaning build directory ..."
  rm -rf "$repo_root/build" && mkdir "$repo_root/build" > /dev/null

  echo -e "${BIGreen}>>>${RST} Building AYON ${BIWhite}[${RST} ${BIGreen}$ayon_version${RST} ${BIWhite}]${RST}"
  echo -e "${BIGreen}>>>${RST} Cleaning cache files ..."
  clean_pyc

  echo -e "${BIGreen}>>>${RST} Reading Poetry ... \c"
  if [ -f "$POETRY_HOME/bin/poetry" ]; then
    echo -e "${BIGreen}OK${RST}"
  else
    echo -e "${BIYellow}NOT FOUND${RST}"
    echo -e "${BIYellow}***${RST} We need to install Poetry and virtual env ..."
    create_env
  fi

  if [ "$disable_submodule_update" == 1 ]; then
    echo -e "${BIYellow}***${RST} Not updating submodules ..."
  else
    echo -e "${BIGreen}>>>${RST} Making sure submodules are up-to-date ..."
    git submodule update --init --recursive || { echo -e "${BIRed}!!!${RST} Poetry installation failed"; return 1; }
  fi
  echo -e "${BIGreen}>>>${RST} Building ..."
  if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    "$POETRY_HOME/bin/poetry" run python "$repo_root/setup.py" build &> "$repo_root/build/build.log" || { echo -e "${BIRed}------------------------------------------${RST}"; cat "$repo_root/build/build.log"; echo -e "${BIRed}------------------------------------------${RST}"; echo -e "${BIRed}!!!${RST} Build failed, see the build log."; return 1; }
  elif [[ "$OSTYPE" == "darwin"* ]]; then
    "$POETRY_HOME/bin/poetry" run python "$repo_root/setup.py" bdist_mac &> "$repo_root/build/build.log" || { echo -e "${BIRed}------------------------------------------${RST}"; cat "$repo_root/build/build.log"; echo -e "${BIRed}------------------------------------------${RST}"; echo -e "${BIRed}!!!${RST} Build failed, see the build log."; return 1; }
  fi
  "$POETRY_HOME/bin/poetry" run python "$repo_root/tools/build_post_process.py" "build" || { echo -e "${BIRed}!!!>${RST} ${BIYellow}Failed to process dependencies${RST}"; return 1; }

  if ["$make_installer" == 1]; then
    make_installer_raw
  fi

  echo -e "${BICyan}>>>${RST} All done. You will find AYON and build log in \c"
  echo -e "${BIWhite}$repo_root/build${RST} directory."
}

make_installer_raw() {
  "$POETRY_HOME/bin/poetry" run python "$repo_root/tools/build_post_process.py" "make-installer" || { echo -e "${BIRed}!!!>${RST} ${BIYellow}Failed to create installer${RST}"; return 1; }
}

make_installer() {
  detect_python || return 1
  make_installer_raw
  echo -e "${BICyan}>>>${RST} All done. You will find AYON and build log in \c"
  echo -e "${BIWhite}$repo_root/build${RST} directory."
}

run_from_code() {
  detect_python || return 1
  pushd "$repo_root" > /dev/null || return > /dev/null
  echo -e "${BIGreen}>>>${RST} Running AYON from code ..."
  "$POETRY_HOME/bin/poetry" run python "$repo_root/start.py" "$@"
}

default_help() {
  echo ""
  echo "Ayon desktop application tool"
  echo ""
  echo "Usage: ./make.sh [target]"
  echo ""
  echo "Runtime targets:"
  echo "  create-env                    Install Poetry and update venv by lock file"
  echo "  install-runtime-dependencies  Install runtime dependencies (Qt binding)"
  echo "  install-runtime               Alias for 'install-runtime-dependencies'"
  echo "  build                         Build desktop application"
  echo "  make-installer                Make desktop application installer"
  echo "  build-make-installer          Build desktop application and make installer"
  echo "  run                           Run desktop application from code"
  echo ""
}

main() {
  # Use first argument, lower and keep only characters
  function_name="$(echo "$1" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z]*//g')"

  return_code=0
  case $function_name in
    "createenv")
      create_env || return_code=$?
      exit $return_code
      ;;
    "installruntimedependencies"|"installruntime")
      install_runtime_dependencies || return_code=$?
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
    "run")
      run_from_code "${@:2}" || return_code=$?
      exit $return_code
      ;;
  esac

  if [[-z $function_name]]; then
    echo -e "${BIRed}!!!${RST} Unknown function name: $function_name"
  fi

  default_help
  exit $return_code
}

main
