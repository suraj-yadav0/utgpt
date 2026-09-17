#!/bin/bash
# Run UTGPT QML unit tests with the UT test stack:
#   qmltestrunner + QtTest (qtdeclarative5-dev-tools, qml-module-qttest)
#
# Usage:
#   ./tests/run_tests.sh            # all tests
#   ./tests/run_tests.sh -functions # list test functions
#
# On headless CI/desktop wrap with xvfb:
#   xvfb-run -a -s '-screen 0 540x960x24' ./tests/run_tests.sh

set -e
cd "$(dirname "$0")"

if ! command -v qmltestrunner >/dev/null 2>&1; then
    echo "ERROR: qmltestrunner not found."
    echo "Install UT test packages: sudo apt install qtdeclarative5-dev-tools qml-module-qttest"
    exit 1
fi

# Offscreen lets tests run without a display; xvfb-run is preferred on CI.
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"
export QT_SELECT="${QT_SELECT:-qt5}"

exec qmltestrunner -input unit "$@"
