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

def do_tree_test_get(study_id, tree_id):
    NEXUS_SUBMIT_URI = DOMAIN + '/v1/study/{}/tree/{}.nex'.format(study_id, tree_id)
    t = get_response_from_http(NEXUS_SUBMIT_URI, 'GET')
    nexus = t.content
    if not nexus.startswith('#NEXUS'):
        sys.exit('Did not get content starting with #NEXUS')
    data = {'tip_label': 'ot:ottTaxonName'}
    NEWICK_SUBMIT_URI = DOMAIN + '/v1/study/{}/tree/{}.tre'.format(study_id, tree_id)
    r = test_http_json_method(NEWICK_SUBMIT_URI,
                              'GET',
                              data=data,
                              expected_status=200,
                              return_bool_data=True,
                              is_json=False)
    if r[0]:
        assert r[1].startswith('(')
        assert '[pre-ingroup-marker]' not in r[1]
    else:
        sys.exit(1)
    data['bracket_ingroup'] = True
    r = test_http_json_method(NEWICK_SUBMIT_URI,
                              'GET',
                              data=data,
                              expected_status=200,
                              return_bool_data=True,
                              is_json=False)
    if r[0]:
        assert r[1].startswith('(')
        assert '[pre-ingroup-marker]' in r[1]
    else:
        sys.exit(1)


# loop over studies to find one with a tree so we can test the tree_get...
for study_id in r[1]:
    SUBMIT_URI = DOMAIN + '/v1/study/{}'.format(study_id)
    data = {'output_nexml2json':'1.2.1'}
    r = test_http_json_method(SUBMIT_URI, 'GET', data=data, expected_status=200, return_bool_data=True)
    if r[0]:
        nexm_el = r[1]['data']['nexml']
        if nexm_el["@nexml2json"] != "1.2.1":
            msg = 'requested conversion to NexSON format not performed.  nexml_el["@nexml2json"] = {}\n'
            sys.exit(msg.format(nexm_el["@nexml2json"]))
        tree_group_coll_el = nexm_el.get('treesById')
        if tree_group_coll_el:
            for trees_group_id, trees_group in tree_group_coll_el.items():
                if trees_group and trees_group.get('treeById'):
                    tree_id_list = list(trees_group['treeById'].keys())
                    tree_id_list.sort() #to make the test repeatable...
                    tree_id = tree_id_list[0]
                    do_tree_test_get(study_id, tree_id)
                    sys.exit(0)
    else:
        sys.exit(1)
