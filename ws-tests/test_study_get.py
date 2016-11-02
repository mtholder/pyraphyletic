#!/usr/bin/env python
import sys, os
from opentreetesting import test_http_json_method, config, get_response_from_http
DOMAIN = config('host', 'apihost')
SUBMIT_URI = DOMAIN + '/v4/study/list'
#sys.stderr.write('Calling "{}"...\n'.format(SUBMIT_URI))
r = test_http_json_method(SUBMIT_URI,
                          'GET',
                          expected_status=200,
                          return_bool_data=True)
if not r[0]:
    sys.exit(1)

# loop over studies to find one with a tree so we can test the tree_get...
for study_id in r[1]:
    SUBMIT_URI = DOMAIN + '/v1/study/{}'.format(study_id)
    data = {'output_nexml2json':'1.2'}
    r = test_http_json_method(SUBMIT_URI, 'GET', data=data, expected_status=200, return_bool_data=True)
    if r[0]:
        nexm_el = r[1]['data']['nexml']
        tree_group_coll_el = nexm_el.get('treesById')
        import json
        print json.dumps(nexm_el, indent=2)
        if tree_group_coll_el:
            for trees_group_id, trees_group in tree_group_coll_el.items():
                if trees_group and trees_group.get('treeById'):
                    tree_id_list = list(trees_group['treeById'].keys())
                    tree_id_list.sort() #to make the test repeatable...
                    tree_id = tree_id_list[0]
                    TREE_SUBMIT_URI = DOMAIN + '/v1/study/{}/tree/{}.nex'.format(study_id, tree_id)
                    t = get_response_from_http(TREE_SUBMIT_URI, 'GET')
                    print(t)
                    sys.exit(0)
    else:
        sys.exit(1)
