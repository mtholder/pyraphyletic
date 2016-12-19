#!/bin/sh
cd "$(dirname $0)"

# tests check for development.ini in parent, so they need to be run from phylesystem_api dir
cd phylesystem_api || exit
python tests.py || exit
cd -

