#!/bin/bash
pylint --rcfile=$PEYOTL_ROOT/dev/pylintrc phylesystem_api -f parseable -r n || exit 1
pydocstyle phylesystem_api --ignore=D400,D401,D403,D204,D213,D205,D203,D209,D200 || exit 1
pycodestyle phylesystem_api --max-line-length=100 || exit 1

