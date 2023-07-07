class BundleNotFoundError(Exception):
    """Bundle name is defined but is not available on server.

    Args:
        bundle_name (str): Name of bundle that was not found.
    """

    def __init__(self, bundle_name):
        self.bundle_name = bundle_name
        super().__init__(
            f"Bundle '{bundle_name}' is not available on server"
        )


class InstallerDistributionError(Exception):
    pass
