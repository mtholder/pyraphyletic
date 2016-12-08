#!/usr/bin/env python
import sys, os
from opentreetesting import test_http_json_method, writable_api_host_and_oauth_or_exit
from peyotl import tree_iter_nexson_proxy
DOMAIN, auth_token = writable_api_host_and_oauth_or_exit(__file__)

def fetch_current_synth_study2tree_mapping():
    SUBMIT_URI = DOMAIN + '/v3/trees_in_synth'
    r = test_http_json_method(SUBMIT_URI,
                              'GET',
                              expected_status=200,
                              return_bool_data=True)
    if not r[0]:
        sys.stderr.write("Note that the test trees_in_synth.py will fail if your test collections repo does not have " \
                         "collections that have the same IDs as the collections currently used in synthesis.\n")
        sys.exit(1)
    decisions_list = r[1]['decisions']
    m = {}
    for d in decisions_list:
        m.setdefault(d["studyID"], []).append(d["treeID"])
    return m



def find_unincluded_tree_for_study(taboo_list, study_id):
    A_STUDY_URI = DOMAIN + '/v4/study' + '/' + study_id
    # Put of empty data should result in 400
    r = test_http_json_method(A_STUDY_URI, 'GET', expected_status=200, return_bool_data=True)
    if not r[0]:
        sys.exit(1)
    study_obj = r[1]['data']
    for tp in tree_iter_nexson_proxy(study_obj):
        if (tp.tree_id is not None) and (tp.tree_id not in taboo_list):
            return tp.tree_id
    return None

def find_unincluded_study_tree_pair(study2tree_list, study_list):
    check_later = []
    for study_id in study_list:
        if study_id in study2tree_list:
            check_later.append(study_id)
        else:
            tree_id = find_unincluded_tree_for_study([], study_id)
            if tree_id is not None:
                return study_id, tree_id
    for study_id in check_later:
        tree_id = find_unincluded_tree_for_study(study2tree_list[study_id], study_id)
        if tree_id is not None:
            return study_id, tree_id
    return None, None


# Get a mapping that reveals which trees are currently included
orig_study_to_tree_list = fetch_current_synth_study2tree_mapping()

# Find a (study_id, tree_id) pair that is not currently included
SL_URI = DOMAIN + '/v3/study_list'
r = test_http_json_method(SL_URI, 'GET',  expected_status=200, return_bool_data=True)
if not r[0]:
    sys.exit(1)
study_list = r[1]
study_id, tree_id = find_unincluded_study_tree_pair(orig_study_to_tree_list, study_list)
if study_id is None:
    sys.stderr.write('Full {} not completed because all trees are in synth collection.\n'.format(sys.argv[0]))
print(study_id, tree_id)

# See if we can add the tree
SUBMIT_URI = DOMAIN + '/v4/include_tree_in_synth'
data = {'auth_token': auth_token,
        'study_id': study_id,
        'tree_id': tree_id,
        }
r = test_http_json_method(SUBMIT_URI,
                          'POST',
                          data=data,
                          expected_status=200,
                          return_bool_data=True)
if not r[0]:
    sys.exit(1)

print(r[1])

# BELOW THIS POINT, we have to remove the tree before exiting (or at least warn if we fail to do that)

# Make sure our addition is in the current list
rc = 0
new_study_to_tree_list = fetch_current_synth_study2tree_mapping()
if study_id not in new_study_to_tree_list:
    rc = 1
elif tree_id not in new_study_to_tree_list[study_id]:
    rc = 1

# Remove our addition to return the testing corpus to its previous state.
try:
    SUBMIT_URI = DOMAIN + '/v4/exclude_tree_in_synth'
    data = {'study_id': study_id, 'tree_id': tree_id}
    r = test_http_json_method(SUBMIT_URI,
                              'POST',
                              data=data,
                              expected_status=200,
                              return_bool_data=True)
    assert r[0]
    print(r[1])
except:
    msg = "ERROR: study_id, tree_id pair ({}, {}) was added to the default synth collection, but removal failed!"
    sys.stderr.write(msg)
    sys.exit(1)
sys.exit(rc)
