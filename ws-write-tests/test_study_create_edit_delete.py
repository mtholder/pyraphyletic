#!/usr/bin/env python

import datetime
import sys
from opentreetesting import test_http_json_method, writable_api_host_and_oauth_or_exit, debug

DOMAIN, auth_token = writable_api_host_and_oauth_or_exit(__file__)
BASE_STUDY_URI = DOMAIN + '/v4/study'
DATA = {'auth_token': auth_token}


def get_study_list():
    sl_uri = DOMAIN + '/v3/study/list'
    r = test_http_json_method(sl_uri,
                              'GET',
                              expected_status=200,
                              return_bool_data=True)
    assert r[0]
    return r[1]


def test_mod_of_existing(new_id):
    study_id = new_id
    a_study_url = BASE_STUDY_URI + '/' + study_id
    data = {'output_nexml2json': '1.0.0'}
    r = test_http_json_method(a_study_url, "GET", data=data, expected_status=200, return_bool_data=True)
    assert r[0]
    edit_resp = r[1]
    starting_commit_sha = edit_resp['sha']
    study_obj = edit_resp['data']
    # refresh a timestamp so that the test generates a commit
    study_obj['nexml']['^bogus_timestamp'] = datetime.datetime.utcnow().isoformat()
    data = {'nexson': study_obj,
            'auth_token': auth_token,
            'starting_commit_SHA': starting_commit_sha,
            }
    r = test_http_json_method(a_study_url,
                              'PUT',
                              data=data,
                              expected_status=200,
                              return_bool_data=True)
    assert r[0]


# Can't PUT w/o an ID
if not test_http_json_method(BASE_STUDY_URI,
                             'PUT',
                             DATA,
                             expected_status=404):
    sys.exit(1)
to_del = []
rc = 1
try:
    orig_study_list = get_study_list()
    post_resp = test_http_json_method(BASE_STUDY_URI,
                                      'POST',
                                      data=DATA,
                                      expected_status=200,
                                      return_bool_data=True)
    if not post_resp[0]:
        assert False
    create_resp = post_resp[1]
    posted_id = create_resp['resource_id']
    to_del.append(posted_id)
    debug('post created {}'.format(posted_id))

    assert posted_id not in orig_study_list
    # Put of empty data should result in 400
    resp = test_http_json_method(BASE_STUDY_URI + '/' + posted_id,
                                 'PUT',
                                 DATA,
                                 expected_status=400)
    assert resp

    # test mod
    test_mod_of_existing(posted_id)
    rc = 0
finally:
    for to_del_id in to_del:
        try:
            A_STUDY_URI = BASE_STUDY_URI + '/' + to_del_id
            del_resp = test_http_json_method(A_STUDY_URI,
                                             'DELETE',
                                             data=DATA,
                                             expected_status=200,
                                             return_bool_data=True)
            if del_resp[0]:
                sys.stderr.write('Deletion of {} succeeded: {}\n'.format(to_del_id, del_resp[1]))
            else:
                sys.stderr.write('Deletion of {} failed\n'.format(to_del_id))
                rc = 1
        except:
            sys.stderr.write("failed to delete {}\n".format(to_del_id))
            rc = 1
sys.exit(rc)
