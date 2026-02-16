"""Get runtime python modules from the build using this script.

Execute this script using AYON executable to get runtime python modules.
The script is using 'importlib.metadata' to get runtime
modules and their versions.

Output is stored in a JSON file that must be provided by the last argument.

How to execute:
    ayon --skip-bootstrap {path to this script} {path to output JSON}

Skip bootstrap is required to skip AYON login logic.
"""

import os
import sys
import json
if sys.version_info >= (3, 10):
    from importlib.metadata import distributions
else:
    from importlib_metadata import distributions
from pathlib import Path


def get_runtime_modules(root: Path) -> dict[str, str]:
    """Get runtime python modules from the build.

    This approach makes sure that we use right version that are really
    installed in runtime dependencies directory. Keep in mind that some
    dependencies have other modules as requirements that may not be
    listed in pyproject.toml and there might not be explicit version.
    Also using version from modules require to import them and be lucky
    that version is available and that installed module have same name
    as pip package (e.g. 'PIL' vs. 'Pillow').

    TODO:
        find a better way how to define one dependency to import
        Randomly chosen module inside runtime dependencies directory.

    Args:
        root (Path): Root to location where runtime modules are.

    Returns:
        dict[str, str]: Mapping of module name to version.

    """
    runtime_dep_root = root / "vendor" / "python"

    output = {}
    for dist in distributions():
        try:
            # Get the location of the distribution
            if dist.locate_file(''):
                dist_path = Path(dist.locate_file(''))
                if dist_path.is_relative_to(runtime_dep_root):
                    output[dist.name] = dist.version
        except (AttributeError, TypeError):
            # Handle cases where locate_file might not work
            continue

    return output


def main() -> None:
    """Get runtime modules and store them in a JSON file."""
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
