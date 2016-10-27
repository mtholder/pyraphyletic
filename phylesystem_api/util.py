#!/usr/bin/env python
from peyotl import get_logger
from peyotl import create_doc_store_wrapper

_LOG = get_logger(__name__)
_DOC_STORE = None


def get_phylesystem(settings):
    global _DOC_STORE
    if _DOC_STORE is not None:
        return _DOC_STORE
    repo_parent = settings['repo_parent']
    _LOG.debug('creating Doc Store Wrapper from repo_parent="{}"'.format(repo_parent))
    _DOC_STORE = create_doc_store_wrapper(repo_parent)
    _LOG.debug('repo_nexml2json = {}'.format(_DOC_STORE.phylesystem.repo_nexml2json))
    return _DOC_STORE

def fill_app_settings(settings):
    wrapper = get_phylesystem(settings)
    settings['phylesystem'] = wrapper.phylesystem


'''
import logging
import os

import anyjson
import requests
from peyotl.nexson_syntax import get_empty_nexson, BY_ID_HONEY_BADGERFISH
from peyotl.phylesystem import Phylesystem
from peyotl.phylesystem.git_actions import PhylesystemGitAction
from peyotl.utility.input_output import download as fetch
from pyramid.httpexceptions import HTTPBadRequest

_LOG = logging.getLogger(__name__)





def err_body(description):
    err = {'error': 1,
           'description': description}
    return anyjson.dumps(err)


def raise_http_error_from_msg(msg):
    raise HTTPBadRequest(body=err_body(msg))


def authenticate(**kwargs):
    """Verify that we received a valid Github authentication token

    This method takes a dict of keyword arguments and optionally
    over-rides the author_name and author_email associated with the
    given token, if they are present.

    Returns a PyGithub object, author name and author email.

    This method will return HTTP 400 if the auth token is not present
    or if it is not valid, i.e. if PyGithub throws a BadCredentialsException.

    """
    # this is the GitHub API auth-token for a logged-in curator
    auth_token = kwargs.get('auth_token', '')

    if not auth_token:
        raise HTTP(400, json.dumps({
            "error": 1,
            "description": "You must provide an auth_token to authenticate to the OpenTree API"
        }))
    gh = Github(auth_token)
    gh_user = gh.get_user()
    auth_info = {}
    try:
        auth_info['login'] = gh_user.login
    except BadCredentialsException:
        raise HTTP(400, json.dumps({
            "error": 1,
            "description": "You have provided an invalid or expired authentication token"
        }))

    auth_info['name'] = kwargs.get('author_name')
    auth_info['email'] = kwargs.get('author_email')

    # use the Github Oauth token to get a name/email if not specified
    # we don't provide these as default values above because they would
    # generate API calls regardless of author_name/author_email being specifed

    if auth_info['name'] is None:
        auth_info['name'] = gh_user.name
    if auth_info['email'] is None:
        auth_info['email'] = gh_user.email
    return auth_info


class OTISearch(object):
    def __init__(self, api_base_url):
        self.api_base_url = api_base_url

    def do_search(self, kind, key, value):
        kind_to_oti_url = {
            "tree": "singlePropertySearchForTrees/",
            "node": "singlePropertySearchForTreeNodes/",
            "study": "singlePropertySearchForStudies/"
        }

        headers = {
            'content-type': 'application/json',
            'accept': 'application/json',
        }
        search_url = self.api_base_url + kind_to_oti_url[kind]
        data = {"property": key, "value": value}

        r = requests.post(search_url, headers=headers, data=anyjson.dumps(data), allow_redirects=True)
        try:
            response = r.json()
        except:
            return anyjson.dumps({"error": 1})

        return response


def new_nexson_with_crossref_metadata(doi, ref_string, include_cc0=False):
    if doi:
        # use the supplied DOI to fetch study metadata

        # Cleanup submitted DOI to work with CrossRef API.
        #   WORKS: http://dx.doi.org/10.999...
        #   WORKS: doi:10.999...
        #   FAILS: doi: 10.999...
        #   FAILS: DOI:10.999...
        # Let's keep it simple and make it a bare DOI.
        # All DOIs use the directory indicator '10.', see
        #   http://www.doi.org/doi_handbook/2_Numbering.html#2.2.2

        # Remove all whitespace from the submitted DOI...
        publication_doi = "".join(doi.split())
        # ... then strip everything up to the first '10.'
        doi_parts = publication_doi.split('10.')
        doi_parts[0] = ''
        search_term = '10.'.join(doi_parts)

    elif ref_string:
        # use the supplied reference text to fetch study metadata
        search_term = ref_string

    # look for matching studies via CrossRef.org API
    furl = 'http://search.crossref.org/dois?{}'.format(urlencode({'q': search_term}))
    doi_lookup_response = fetch(furl)
    doi_lookup_response = unicode(doi_lookup_response, 'utf-8')  # make sure it's Unicode!
    matching_records = anyjson.loads(doi_lookup_response)

    # if we got a match, grab the first (probably only) record
    if len(matching_records) > 0:
        match = matching_records[0]

        # Convert HTML reference string to plain text
        raw_publication_reference = match.get('fullCitation', '')
        raise NotImplementError('parsing crossref should use beautiful soup!!!')  # TODO
        ref_element_tree = web2pyHTMLParser(raw_publication_reference).tree
        # root of this tree is the complete mini-DOM
        ref_root = ref_element_tree.elements()[0]
        # reduce this root to plain text (strip any tags)

        meta_publication_reference = ref_root.flatten().decode('utf-8')
        meta_publication_url = match.get('doi', u'')  # already in URL form
        meta_year = match.get('year', u'')

    else:
        # Add a bogus reference string to signal the lack of results
        if doi:
            meta_publication_reference = u'No matching publication found for this DOI!'
        else:
            meta_publication_reference = u'No matching publication found for this reference string'
        meta_publication_url = u''
        meta_year = u''

    # add any found values to a fresh NexSON template
    nexson = get_empty_nexson(BY_ID_HONEY_BADGERFISH, include_cc0=include_cc0)
    nexml_el = nexson['nexml']
    nexml_el[u'^ot:studyPublicationReference'] = meta_publication_reference
    if meta_publication_url:
        nexml_el[u'^ot:studyPublication'] = {'@href': meta_publication_url}
    if meta_year:
        nexml_el[u'^ot:studyYear'] = meta_year
    return nexson
'''
