Addon distribution tool
------------------------

Code in this folder is backend portion of addons and dependency packages distribution logic from AYON server.

Each AYON server can run different set of addons.

AYON launcher (running on artist machine) in the first step asks AYON server for list of enabled addons.
(It expects list of json documents matching to `addon_distribution.py:AddonInfo` object.)
Next compares presence of enabled addon version in local folder. In the case of missing version of
an addon, AYON launcher will use information in the addon to download (from http/shared local disk/git) zip file
and unzip it.

Required part of addon distribution will be sharing of dependencies (python libraries, utilities) which is not part of this folder.

Location of this folder might change in the future as it will be required for a clint to add this folder to sys.path reliably.

This code is dependent only on 'ayon_api' and 'keyring'.
