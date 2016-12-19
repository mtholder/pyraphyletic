"""Unittests that do not require the server to be running an common tests of responses.

The TestCase here just calls the functions that provide the logic to the ws views with DummyRequest
objects to mock a real request.

The functions starting with `check_...` are called with UnitTest.TestCase instance as the first
arg and the response. These functions are used within the unit tests in this file, but also
in the `ws-tests` calls that perform the tests through http.
"""
import os
import unittest

from pyramid import testing

from phylesystem_api.utility import fill_app_settings, umbrella_from_request
from phylesystem_api.views import import_nexson_from_crossref_metadata


def get_app_settings_for_testing(settings):
    """Fills the settings of a DummyRequest, with info from the development.ini

    This allows the dummy requests to mock a real request wrt configuration-dependent settings."""
    from peyotl.utility.imports import SafeConfigParser
    cfg = SafeConfigParser()
    devini_path = os.path.abspath(os.path.join('..', 'development.ini'))
    if not os.path.isfile(devini_path):
        raise RuntimeError('Expecting a INI file at "{}" to run tests'.format(devini_path))
    cfg.read(devini_path)
    settings['repo_parent'] = cfg.get('app:main', 'repo_parent')
    fill_app_settings(settings=settings)


def gen_versioned_dummy_request():
    """Adds a version number (3) to the request to mimic the matching based on URL in the real app.
    """
    req = testing.DummyRequest()
    get_app_settings_for_testing(req.registry.settings)
    req.matchdict['api_version'] = 'v3'
    return req


def check_index_response(test_case, response):
    """Verifies the existene of expected keys in the response to an index call.

    'documentation_url', 'description', and 'source_url' keys must be in the response.
    """
    for k in ['documentation_url', 'description', 'source_url']:
        test_case.assertIn(k, response)


def check_render_markdown_response(test_case, response):
    """Check of `response` to a `render_markdown` call."""
    expected = '<p>hi from <a href="http://phylo.bio.ku.edu" target="_blank">' \
               'http://phylo.bio.ku.edu</a> and  ' \
               '<a href="https://github.com/orgs/OpenTreeOfLife/dashboard" target="_blank">' \
               'https://github.com/orgs/OpenTreeOfLife/dashboard</a></p>'
    test_case.assertEquals(response.body, expected)


def check_study_list_and_config_response(test_case,
                                         sl_response,
                                         config_response,
                                         from_generic_config):
    """Checks of responses from study_list, config, and the generic config calls."""
    nsis = sum([i['number of documents'] for i in config_response['shards']])
    test_case.assertEquals(nsis, len(sl_response))
    test_case.assertEquals(from_generic_config, config_response)


def check_unmerged_response(test_case, ub):
    """Check of `ub` response from an `unmerged_branches` call"""
    test_case.assertTrue('master' not in ub)


def check_config_response(test_case, cfg):
    """Check of `cfg` response from a `config` call"""
    test_case.assertSetEqual(set(cfg.keys()), {"initialization", "shards", "number_of_shards"})


def check_external_url_response(test_case, doc_id, resp):
    """Simple check of an `external_url` `resp` response for `doc_id`.

    `doc_id` and `url` fields of the response are checked."""
    test_case.assertEquals(resp.get('doc_id'), doc_id)
    test_case.assertTrue(resp.get('url', '').endswith('{}.json'.format(doc_id)))


def check_push_failure_response(test_case, resp):
    """Check of the `resp` response of a `push_failure` method call to verify it has the right keys.
    """
    test_case.assertSetEqual(set(resp.keys()), {"doc_type", "errors", "pushes_succeeding"})
    test_case.assertTrue(resp["pushes_succeeding"])


render_test_input = 'hi from <a href="http://phylo.bio.ku.edu" target="new">' \
                    'http://phylo.bio.ku.edu</a> and  ' \
                    'https://github.com/orgs/OpenTreeOfLife/dashboard'


class ViewTests(unittest.TestCase):
    """UnitTest of the functions that underlie the ws views."""

    def setUp(self):
        """Calls pyramid testing.setUp"""
        self.config = testing.setUp()

    def tearDown(self):
        """Calls pyramid testing.tearDown"""
        testing.tearDown()

    def test_index(self):
        """Test of index view"""
        request = gen_versioned_dummy_request()
        from phylesystem_api.views import index
        check_index_response(self, index(request))

    def test_render_markdown(self):
        """Test of render_markdown view"""
        request = testing.DummyRequest(post={'src': render_test_input})
        from phylesystem_api.views import render_markdown
        check_render_markdown_response(self, render_markdown(request))

    def test_study_list_and_config(self):
        """Test of study_list and phylesystem_config views"""
        request = gen_versioned_dummy_request()
        from phylesystem_api.views import study_list
        sl = study_list(request)
        request = gen_versioned_dummy_request()
        from phylesystem_api.views import phylesystem_config
        x = phylesystem_config(request)
        request = gen_versioned_dummy_request()
        request.matchdict['resource_type'] = 'study'
        from phylesystem_api.views import generic_config
        y = generic_config(request)
        check_study_list_and_config_response(self, sl, x, y)
        if not sl:
            return
        from phylesystem_api.views import external_url
        doc_id = sl[0]
        request.matchdict['doc_id'] = doc_id
        e = external_url(request)
        check_external_url_response(self, doc_id, e)

    def test_unmerged(self):
        """Test of unmerged_branches view"""
        request = gen_versioned_dummy_request()
        request.matchdict['resource_type'] = 'study'
        from phylesystem_api.views import unmerged_branches
        check_unmerged_response(self, unmerged_branches(request))

    def test_config(self):
        """Test of generic_config view"""
        request = gen_versioned_dummy_request()
        from phylesystem_api.views import phylesystem_config, generic_config
        r2 = phylesystem_config(request)
        check_config_response(self, r2)
        request.matchdict['resource_type'] = 'study'
        r = generic_config(request)
        check_config_response(self, r)
        self.assertDictEqual(r, r2)
        request.matchdict['resource_type'] = 'amendment'
        ra = generic_config(request)
        check_config_response(self, ra)
        self.assertNotEqual(ra, r)

    def test_push_failure_state(self):
        """Test of push_failure view"""
        request = gen_versioned_dummy_request()
        request.matchdict['resource_type'] = 'collection'
        from phylesystem_api.views import push_failure
        pf = push_failure(request)
        check_push_failure_response(self, pf)

    def test_doi_import(self):
        """Make sure that fetching from DOI generates a valid study shell."""
        doi = "10.3732/ajb.0800060"
        document = import_nexson_from_crossref_metadata(doi=doi,
                                                        ref_string=None,
                                                        include_cc0=None)
        request = gen_versioned_dummy_request()
        request.matchdict['resource_type'] = 'study'
        umbrella = umbrella_from_request(request)
        errors = umbrella.validate_and_convert_doc(document, {})[1]
        self.assertEquals(len(errors), 0)


if __name__ == '__main__':
    unittest.main()
