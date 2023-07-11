"""Get runtime python modules from build using this script.

Execute this script using ayon executable to get runtime python modules.
The script is using 'pkg_resources' to get runtime modules and their versions.
Output is stored to a json file that must be provided by last argument.

How to execute:
    ayon --skip-bootstrap {path to this script} {path to output json}

Skip bootstrap is required to skip AYON login logic.
"""

import os
import sys
import json
import pkg_resources
from pathlib import Path


def get_runtime_modules(root):
    runtime_dep_root = root / "vendor" / "python"

    # One of the dependencies from runtime dependencies must be imported
    #   so 'pkg_resources' have them available in 'working_set'
    # This approach makes sure that we use right version that are really
    #   installed in runtime dependencies directory. Keep in mind that some
    #   dependencies have other modules as requirements that may not be
    #   listed in pyproject.toml and there might not be explicit version.
    #   Also using version from modules require to import them and be lucky
    #   that version is available and that installed module have same name
    #   as pip package (e.g. 'PIL' vs. 'Pillow').
    # TODO find a better way how to define one dependency to import
    # Randomly chosen module inside runtime dependencies

    output = {}
    for package in pkg_resources.working_set:
        package_path = Path(package.module_path)
        if package_path.is_relative_to(runtime_dep_root):
            output[package.project_name] = package.version

    return output


def main():
    output = sys.argv[-1]
    _, ext = os.path.splitext(output)
    if ext.lower() != ".json":
        raise ValueError(f"Output must be JSON file. Got {output}")
    root = Path(sys.executable).parent
    modules = get_runtime_modules(root)

    print(f"Storing output to {output}")
    with open(output, "w") as stream:
        json.dump(modules, stream, indent=4)


if __name__ == "__main__":
    main()
