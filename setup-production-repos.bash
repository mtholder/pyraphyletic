#!/bin/bash
shards_dir="${1}"
git_clone_prefix="git@github.com:OpenTreeOfLife"
if test -z "${shards_dir}" ; then
    echo "Expecting a first argument to be a directory that will be the shards directory for the git repos:"
    exit 1
fi
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
for repo_name in phylesystem-1 amendments-1 collections-1 ; do
    if ! test -d ${repo_name} ; then
        if ! git clone "${git_clone_prefix}/${repo_name}" ; then
            echo "Could not clone \"${git_clone_prefix}/${repo_name}\""
            exit 3
        fi
    fi
done

echo "setting up push mirrors"
if ! python "${PEYOTL_ROOT}/dev/create_push_mirrors.py" "${PWD}" "${git_clone_prefix}" ; then
    echo 'create_push_mirrors.py failed!'
    exit 1
fi