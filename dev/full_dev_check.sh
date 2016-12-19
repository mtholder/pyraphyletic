#!/bin/bash
bash dev/check_code_kwality.bash || exit 1
bash dev/all_dev_tests.sh || exit 1
