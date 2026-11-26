#!/bin/bash
# Build for Linux and macOS, laid out as design 0002 decides.
set -euxo pipefail

# 1. The interface, exported as static pages to webapp/dist/client (next.config.ts: output 'export'),
#    plus the bundled runtime npm package license inventory for recipe.yaml's license_file.
export npm_config_cache="${NPM_CACHE:-${SRC_DIR}/.npm-cache}"
pushd webapp
npm ci --no-audit --no-fund --prefer-offline
npm run build
node scripts/third-party-licenses.mjs --out "${SRC_DIR}/THIRD_PARTY_WEB_LICENSES.txt"
popd

# 2. The eeglayoutlab package only. compact_eeg is installed once, in the root tree below, because the workers
#    find the scientific root from their own location and identities hash the files at root-relative paths.
"${PYTHON}" - <<'EOF'
import pathlib
pyproject = pathlib.Path('pyproject.toml')
text = pyproject.read_text()
old = '[tool.setuptools.packages.find]\nwhere = ["src"]\n'
assert old in text, 'pyproject.toml layout changed'
pyproject.write_text(text.replace(old, old + 'include = ["eeglayoutlab*"]\n'))
EOF
"${PYTHON}" -m pip install . -vv --no-deps --no-build-isolation
# The recipe's entry point replaces the script that pip writes.
rm -f "${PREFIX}/bin/eeglayoutlab"
test ! -e "${SP_DIR}/compact_eeg"

# 3. The scientific root: the checkout's files at their relative paths, nothing renamed.
root="${PREFIX}/share/eeglayoutlab/root"
mkdir -p "${root}/src" "${root}/data" "${root}/webapp/dist"
cp -R src/compact_eeg "${root}/src/"
cp -R scripts configs examples "${root}/"
cp data/manifest.json data/packages.json data/SOURCES.md data/README.md "${root}/data/"
cp -R webapp/public "${root}/webapp/"
cp -R webapp/dist/client "${root}/webapp/dist/"
cp "${SRC_DIR}/THIRD_PARTY_WEB_LICENSES.txt" "${root}/webapp/dist/client/THIRD_PARTY_WEB_LICENSES.txt"
if command -v mkdocs >/dev/null 2>&1; then
  mkdocs build --strict --site-dir "${root}/site"
fi
rm -rf "${root}/examples/outputs"
find "${root}" \( -name __pycache__ -o -name '*.pyc' -o -name .DS_Store \) -prune -exec rm -rf {} +
