import os

from ayon_common.utils import is_staging_enabled, is_dev_mode_enabled

RESOURCES_DIR = os.path.dirname(os.path.abspath(__file__))


def get_resource_path(*args):
    path_items = list(args)
    path_items.insert(0, RESOURCES_DIR)
    return os.path.sep.join(path_items)


def get_ayon_default_icon_path():
    return get_resource_path("AYON.png")


def get_icon_path():
    if is_dev_mode_enabled():
        return get_resource_path("AYON_dev.png")
    if is_staging_enabled():
        return get_resource_path("AYON_staging.png")
    return get_ayon_default_icon_path()


def load_stylesheet():
    stylesheet_path = get_resource_path("stylesheet.css")

    with open(stylesheet_path, "r") as stream:
        content = stream.read()
    return content
