#!/usr/bin/env bash
set -x
virtualenv travisenv || exit
source travisenv/bin/activate || exit

git clone https://github.com/mtholder/peyotl.git || exit
cd peyotl || exit
git checkout pyr-only || exit
python setup.py develop || exit
export PEYOTL_ROOT="${PWD}"
cd ..

pip install -r requirements.txt || exit
pip install -r devrequirements.txt || exit

cat development.ini.example | sed -e "s:REPO_PAR:${PWD}/travisshards:" > development.ini || exit 1
bash setup-travis-testing-repos.sh || exit 1

export LOCAL_TESTING_MODE=1
export GITHUB_OAUTH_TOKEN=bogus
python setup.py develop || exit

pserve -v development.ini &
serverpid=`echo $!`
bash full_dev_check.sh || exit
kill $serverpid
