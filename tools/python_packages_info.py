# -*- coding: utf-8 -*-
"""Get version and license information on used Python packages.

This is getting over all packages installed with Poetry and printing out
their name, version and available license information from PyPi in Markdown
table format.

Usage:
    ./.poetry/bin/poetry run python ./tools/python_packages_info.py

"""

import toml
import requests


def get_packages_info():
    """Read lock file to get packages.

    Retruns:
        list[tuple[str, Union[str, None]]]: List of tuples containing package
            name and version.
    """

    with open("poetry.lock", "r") as fb:
        lock_content = toml.load(fb)

    return {
        package["name"]: package.get("version")
        for package in lock_content["package"]
    }


def print_packages(packages=None):
    if packages is None:
        packages = get_packages_info()

    url = "https://pypi.org/pypi/{}/json"
    new_packages = []
    for name, version in packages.items():
        # query pypi for license information
        response = requests.get(url.format(name))
        package_data = response.json()
        try:
            package_license = package_data["info"].get("license") or "N/A"
        except KeyError:
            package_license = "N/A"
        new_packages.append((name, version or "N/A", package_license))

    # define column headers
    package_header = "Package"
    version_header = "Version"
    license_header = "License"

    name_col_width = len(package_header)
    version_col_width = len(version_header)
    license_col_width = len(license_header)

    for package in new_packages:
        name, version, package_license = package
        if len(package_license) > 64:
            package_license = f"{package_license[:32]}..."

        # update column width based on max string length
        if len(name) > name_col_width:
            name_col_width = len(name)
        if len(version) > version_col_width:
            version_col_width = len(version)
        if len(package_license) > license_col_width:
            license_col_width = len(package_license)

    # pad columns
    name_col_width += 2
    version_col_width += 2
    license_col_width += 2

    # print table header
    print((f"|{package_header.center(name_col_width)}"
           f"|{version_header.center(version_col_width)}"
           f"|{license_header.center(license_col_width)}|"))

    print(
        "|" + ("-" * len(package_header.center(name_col_width))) +
        "|" + ("-" * len(version_header.center(version_col_width))) +
        "|" + ("-" * len(license_header.center(license_col_width))) + "|")

    # print rest of the table
    for package in packages:
        print((
            f"|{package[0].center(name_col_width)}"
            f"|{package[1].center(version_col_width)}"
            f"|{package[2].center(license_col_width)}|"
        ))


if __name__ == "__main__":
    print_packages()
