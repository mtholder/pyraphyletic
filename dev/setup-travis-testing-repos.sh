#!/bin/bash
shards_dir="travisshards"
git_clone_prefix="https://github.com/mtholder"
if ! test -d "${shards_dir}" ; then
    if ! mkdir -p "${shards_dir}" ; then
        echo "Could not created shards directory at \"${shards_dir}\""
        exit 1
    fi
fi
if test -z "${PEYOTL_ROOT}" ; then
    echo "Expecting PEYOTL_ROOT to be defined in your env"
    exit 4
fi
if ! test -f "${PEYOTL_ROOT}/dev/create_push_mirrors.py" ; then
    echo "Must be working on a branch of peyotl that is a descendant of the Oct 2016 reduce_dup branch"
    exit 4
fi
cd "${shards_dir}"
for repo_name in mini_phyl mini_system mini_amendments mini_collections ; do
    if ! git clone "${git_clone_prefix}/${repo_name}" ; then
        echo "Could not clone \"${git_clone_prefix}/${repo_name}\""
        exit 3
    fi
done
# Create a set of clones that we can push to
mkdir pushdestination
cd pushdestination
localpref="${PWD}"
cd ..

echo "setting up push mirrors"
if ! python "${PEYOTL_ROOT}/dev/create_push_mirrors.py" "${PWD}" "${localpref}" ; then
    echo 'create_push_mirrors.py failed!'
    exit 1
fi

cd "${localpref}"
for repo_name in mini_phyl mini_system mini_amendments mini_collections ; do
    if ! git clone ../mirror/"${repo_name}" ; then
        echo "Could not clone \../${repo_name}"
        exit 3
    fi
    cd "${repo_name}" || exit
    git config receive.denyCurrentBranch ignore || exit
    cd .. || exit
done
cd ..