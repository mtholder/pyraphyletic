#!/usr/bin/env python
import sys, os
from opentreetesting import test_http_json_method, config, get_response_from_http
from peyotl import convert_nexson_format

DOMAIN = config('host', 'apihost')
SUBMIT_URI = DOMAIN + '/v4/study/list'
#sys.stderr.write('Calling "{}"...\study_obj'.format(SUBMIT_URI))
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


def dict_eq(a, b):
    if a == b:
        return True
    d = True
    ka, kb = a.keys(), b.keys()
    ka.sort()
    kb.sort()
    if ka != kb:
        sa = set(ka)
        sb = set(kb)
        ao = sa - sb
        ao = list(ao)
        ao.sort()
        bo = sb - sa
        c = {u'^ot:candidateTreeForSynthesis', u'^ot:tag'}
        bextra = bo - c
        bo = list(bextra)
        bo.sort()
        if bextra or ao:
            sys.stdout.write('  keys in a only "{a}"."\n'.format(a=ao))
            sys.stdout.write('  keys in b only "{a}"."\n'.format(a=bo))
            d = False
    for k in ka:
        if k in kb:
            va = a[k]
            vb = b[k]
            if va != vb:
                if isinstance(va, dict) and isinstance(vb, dict):
                    if not dict_eq(va, vb):
                        d = False
                elif isinstance(va, list) and isinstance(vb, list):
                    for n, ela in enumerate(va):
                        elb = vb[n]
                        if not dict_eq(ela, elb):
                            d = False
                    if len(va) != len(vb):
                        d = False
                        sys.stdout.write('  lists for {} differ in length.\n'.format(k))
                else:
                    d = False
                    sys.stdout.write('  value for {k}: "{a}" != "{b}"\n'.format(k=k, a=va, b=vb))
        else:
            d = False
    return d

# loop over studies to find one with a tree so we can test the tree_get...
for study_id in r[1]:
    SUBMIT_URI = DOMAIN + '/v1/study/{}'.format(study_id)
    # a bogus value for nexml2json should give us a 400
    data = {'output_nexml2json': 'x1.2.1'}
    test_http_json_method(SUBMIT_URI, 'GET', data=data, expected_status=400)
    # now get the study in the "legacy" format
    data = {'output_nexml2json': '0.0.0'}
    pb = test_http_json_method(SUBMIT_URI, 'GET', data=data, expected_status=200, return_bool_data=True)
    if not pb[0]:
        sys.exit(1)
    # ... and in our transitional format...
    data = {'output_nexml2json': '1.0.0'}
    pl = test_http_json_method(SUBMIT_URI, 'GET', data=data, expected_status=200, return_bool_data=True)
    if not pl[0]:
        sys.exit(1)
    badger = pb[1]['data']
    legacy = pl[1]['data']
    # ...they should differ...
    assert (badger != legacy)
    # ... but convertable to the same info...
    lfromb = convert_nexson_format(badger, '1.0.0', current_format='0.0.0')
    if lfromb != legacy:
        with open('.tmp1', 'w') as fo_one:
            json.dump(legacy, fo_one, indent=0, sort_keys=True)
        with open('.tmp2', 'w') as fo_one:
            json.dump(lfromb, fo_one, indent=0, sort_keys=True)
        assert (dict_eq(lfromb, legacy))
    # ...finally we grab it in HBF...
    data = {'output_nexml2json':'1.2.1'}
    r = test_http_json_method(SUBMIT_URI, 'GET', data=data, expected_status=200, return_bool_data=True)
    if r[0]:
        # ... and do some tests of grabbing just a tree from the study...
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
