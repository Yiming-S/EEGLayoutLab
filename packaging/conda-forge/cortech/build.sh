#!/bin/bash
set -euxo pipefail

# meson.build asks for dependency('cgal', version: '>= 6.0'). conda-forge's cgal-cpp ships a
# CMake package but no pkg-config file, and meson's CMake lookup reports Boost's version for
# CGAL, so the version check fails. A private cgal.pc, used for this build only and not
# installed, gives meson the CGAL headers with Eigen, GMP and MPFR.
cgal_version=$(sed -n 's/^#define CGAL_VERSION \([0-9.]*\).*/\1/p' "${PREFIX}/include/CGAL/version.h")
test -n "${cgal_version}"
mkdir -p "${SRC_DIR}/_pkgconfig"
cat > "${SRC_DIR}/_pkgconfig/cgal.pc" <<EOF
prefix=${PREFIX}
includedir=\${prefix}/include

Name: cgal
Description: CGAL headers from conda-forge cgal-cpp
Version: ${cgal_version}
Requires: eigen3 mpfr gmp
Cflags: -I\${includedir}
EOF
export PKG_CONFIG_PATH="${SRC_DIR}/_pkgconfig${PKG_CONFIG_PATH:+:${PKG_CONFIG_PATH}}"

# CGAL 6 requires C++17. Upstream takes cpp_std from the native file that conan writes;
# Apple clang would otherwise compile with an older default standard.
# MESON_ARGS carries the conda-forge cross file when cross-compiling; meson-python sets
# its own build type, so that argument is dropped.
MESON_ARGS_REDUCED="$(echo "${MESON_ARGS:-}" | sed 's/--buildtype release//g; s/-Dbuildtype=release//g')"
SETUP_ARGS=(-Csetup-args=-Dcpp_std=gnu++17)
for arg in ${MESON_ARGS_REDUCED}; do
  SETUP_ARGS+=("-Csetup-args=${arg}")
done

"${PYTHON}" -m pip install . -vv --no-deps --no-build-isolation "${SETUP_ARGS[@]}"
