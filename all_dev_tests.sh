#!/bin/bash
cd phylesystem_api
python tests.py || exit
cd ..

cd ws-tests
./local_tests.sh || exit
cd ..

cd ws-write-tests
./local_tests.sh || exit
cd ..

