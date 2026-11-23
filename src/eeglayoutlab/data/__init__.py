"""Data packages (design 0001, decision 7): versioned, checksummed bundles of model data.

- ``manifest``: the ``eeglayoutlab-data-package/1`` format.
- ``catalog``: the author side; finds the packages of a scientific root and checks them.
- ``archive``: deterministic tar archives and their safe extraction.
- ``store``: the user side; installs, lists, verifies and removes packages in the user data directory.
- ``cli``: the ``eeglayoutlab data`` commands.

Files keep their paths relative to the scientific root (``results/v2/heads/ixi002/package.json``), because those
paths and the file bytes enter scientific identities. Nothing here changes how the service or the workers find
data; see docs/data-packages.md for the step that connects installed packages to a scientific root.
"""
