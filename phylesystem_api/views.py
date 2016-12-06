#!/usr/bin/env python

import copy
import json
import os
import traceback
import requests
from Queue import Queue
from threading import Lock, Thread
import itertools
import bleach
import markdown
from github import Github, BadCredentialsException
from peyotl import (add_cc0_waiver,
                    concatenate_collections, create_doc_store_wrapper,
                    extract_tree_nexson,
                    get_logger, GitWorkflowError,
                    import_nexson_from_crossref_metadata, import_nexson_from_treebase,
                    NexsonDocSchema,
                    OTI,
                    SafeConfigParser)
from pyramid.httpexceptions import (HTTPNotFound, HTTPBadRequest, HTTPForbidden,
                                    HTTPConflict, HTTPGatewayTimeout, HTTPInternalServerError)
from pyramid.response import Response
from pyramid.view import view_config

# LOCAL_TESTING_MODE=1 in env can used for situations in which you are offline
#   and cannot use methods associated with the GitHub webservices
_LOCAL_TESTING_MODE = os.environ.get('LOCAL_TESTING_MODE', '0') == '1'
_LOG = get_logger(__name__)
_DOC_STORE = None
_API_VERSIONS = frozenset(['v1', 'v2', 'v3'])
_RESOURCE_TYPE_2_SETTINGS_UMBRELLA_KEY = {'phylesystem': 'phylesystem',
                                          'study': 'phylesystem',
                                          'studies': 'phylesystem',
                                          'taxon_amendments': 'taxon_amendments',
                                          'amendments': 'taxon_amendments',
                                          'amendment': 'taxon_amendments',
                                          'tree_collections': 'tree_collections',
                                          'collections': 'tree_collections',
                                          'collection': 'tree_collections',
                                          }

_LOG = get_logger(__name__)


class JobQueue(Queue):
    def put(self, item, block=None, timeout=None):
        _LOG.debug("%s queued" % str(item))
        Queue.put(self, item, block=block, timeout=timeout)


_jobq = JobQueue()


def worker():
    while True:
        job = _jobq.get()
        _LOG.debug('"{}" started"'.format(job))
        try:
            job.start()
        except:
            _LOG.exception("Worker dying.")
        else:
            try:
                job.get_results()
            except:
                _LOG.error("Worker exception.  Error in job.get_results")
        _LOG.debug('"{}" completed'.format(job))
        _jobq.task_done()


_WORKER_THREADS = []


def start_worker(num_workers):
    """Spawns worker threads such that at least `num_workers` threads will be
    launched for processing jobs in the jobq.

    The only way that you can get more than `num_workers` threads is if you
    have previously called the function with a number > `num_workers`.
    (worker threads are never killed).
    """
    assert num_workers > 0, "A positive number must be passed as the number of worker threads"
    num_currently_running = len(_WORKER_THREADS)
    for i in range(num_currently_running, num_workers):
        _LOG.debug("Launching Worker thread #%d" % i)
        t = Thread(target=worker)
        _WORKER_THREADS.append(t)
        t.setDaemon(True)
        t.start()


def add_push_failure(push_failure_dict_lock, push_failure_dict, umbrella, msg):
    with push_failure_dict_lock:
        fl = push_failure_dict.setdefault(umbrella.document_type, [])
        fl.append(msg)


def clear_push_failures(push_failure_dict_lock, push_failure_dict, umbrella):
    with push_failure_dict_lock:
        fl = push_failure_dict.setdefault(umbrella.document_type, [])
        del fl[:]


def copy_of_push_failures(push_failure_dict_lock, push_failure_dict, umbrella):
    with push_failure_dict_lock:
        return copy.copy(push_failure_dict.setdefault(umbrella.document_type, []))


def find_studies_by_doi(indexer_domain, study_doi):
    oti_wrapper = OTI(domain=indexer_domain)
    return oti_wrapper.find_studies_by_doi(study_doi)


def httpexcept(except_class, message):
    return except_class(body=err_body(message))


class GitPushJob(object):
    def __init__(self, request, umbrella, doc_id, operation, auth_info=None):
        settings = request.registry.settings
        self.push_failure_dict_lock = settings['push_failure_lock']
        self.push_failure_dict = settings['doc_type_to_push_failure_list']
        self.doc_id = doc_id
        self.umbrella = umbrella
        self.status_str = None
        self.operation = operation
        self.auth_info = auth_info
        self.reindex_fn = None
        self.push_success = False

    def __str__(self):
        template = 'GitPushJob for {o} operation of "{i}" to store of "{d}" documents'
        return template.format(o=self.operation, i=self.doc_id, d=self.umbrella.document_type)

    def push_to_github(self):
        try:
            self.umbrella.push_doc_to_remote('GitHubRemote', self.doc_id)
            self.push_success = True
        except:
            m = traceback.format_exc()
            msg = "Could not push {i} ! Details: {m}".format(i=self.doc_id, m=m)
            try:
                add_push_failure(push_failure_dict_lock=self.push_failure_dict_lock,
                                 push_failure_dict=self.push_failure_dict,
                                 umbrella=self.umbrella,
                                 msg=msg)
            except:
                msg = 'Error logging push failure following {}'.format(msg)
                self.status_str = 'Push failed; logging of push failures list also failed.'
                raise httpexcept(HTTPInternalServerError, msg)
            self.status_str = 'Push failed; logging of push failures list succeeded.'
            raise httpexcept(HTTPConflict, msg)
        try:
            clear_push_failures(push_failure_dict_lock=self.push_failure_dict_lock,
                                push_failure_dict=self.push_failure_dict,
                                umbrella=self.umbrella)
        except:
            msg = 'Push succeeded; clear of push failures list failed.'
            _LOG.exception(msg)
            self.status_str = msg
            raise httpexcept(HTTPInternalServerError, msg)
        if self.reindex_fn is not None:
            self.status_str = 'Push and clearing of push_failures succeeded. Reindex failed.'
            self.reindex_fn(self.umbrella.document_type, self.doc_id, self.operation)
            self.status_str = 'Succeeded.'
        else:
            self.status_str = 'Push and clearing of push_failures succeeded; reindex not attempted'

    def start(self):
        self.push_to_github()

    def get_results(self):
        return self.status_str

    def get_response_obj(self):
        if self.status_str is None:
            self.start()
        return {"error": 0 if self.push_success else 1,
                "description": self.status_str, }


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
    """ Fills a settings dict with:
        * 'phylesystem', 'taxon_amendments', 'tree_collections' ==> umbrella
        * 'doc_type_to_push_failure_list' ==> {}
        * 'push_failure_lock' ==> mutex Lock for doc_type_to_push_failure_list
        * 'job_queue' ==> a thread safe queue to hold deferred jobs

    As a side effect, launches a
    """
    start_worker(1)
    wrapper = get_phylesystem(settings)
    settings['phylesystem'] = wrapper.phylesystem
    settings['taxon_amendments'] = wrapper.taxon_amendments
    settings['tree_collections'] = wrapper.tree_collections
    # Thread-safe dict that map doc type to lists of push failure messages.
    settings['doc_type_to_push_failure_list'] = {}
    settings['push_failure_lock'] = Lock()
    settings['job_queue'] = _jobq


def err_body(description):
    err = {'error': 1,
           'description': description}
    return json.dumps(err)


def authenticate(**kwargs):
    """Raises an HTTPForbidden error if `auth_token` is not a kwarg or its value is not a GitHub username
    returns a dict with 3 keys:
       `login` is the GitHub username
       `name` is kwargs.get('author_name', or the name associated w/ the GitHub user).
       `email` is kwargs.get('author_email', or the email address associated w/ the GitHub user).
    """
    # this is the GitHub API auth-token for a logged-in curator
    auth_token = kwargs.get('auth_token', '')
    if not auth_token:
        raise httpexcept(HTTPForbidden, "You must provide an auth_token to authenticate to the OpenTree API")
    if _LOCAL_TESTING_MODE:
        return {'login': 'fake_gh_login', 'name': 'Fake Name', 'email': 'fake@bogus.com'}
    gh = Github(auth_token)
    gh_user = gh.get_user()
    auth_info = {}
    try:
        auth_info['login'] = gh_user.login
    except BadCredentialsException:
        raise httpexcept(HTTPForbidden, "You have provided an invalid or expired authentication token")
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


def _extract_json_obj_from_http_call(request, data_kwarg_key, **kwargs):
    """Returns the JSON object from `kwargs` or the request.body"""
    try:
        # check for kwarg 'nexson', or load the full request body
        if data_kwarg_key in kwargs:
            json_blob = kwargs.get(data_kwarg_key, {})
        else:
            json_blob = request.json_body
        if not (isinstance(json_blob, dict) or isinstance(json_blob, list)):
            json_blob = json.loads(json_blob)
        if data_kwarg_key in json_blob:
            json_blob = json_blob[data_kwarg_key]
    except:
        msg = 'Could not extract JSON argument from {} or body'.format(data_kwarg_key)
        _LOG.exception(msg)
        raise httpexcept(HTTPBadRequest, msg)
    return json_blob


def get_resource_type_to_umbrella_name_copy():
    """As an interim measure we support some aliasing of "resource_type" strings
    to the different types of document store "umbrellas". This function
    returns a copy of the dict that performs that mapping."""
    return copy.copy(_RESOURCE_TYPE_2_SETTINGS_UMBRELLA_KEY)


def check_api_version(request):
    """Raises a 404 if the version string is not correct and returns the version string"""
    vstr = request.matchdict.get('api_version')
    if vstr not in _API_VERSIONS:
        raise httpexcept(HTTPNotFound, 'API version "{}" is not supported'.format(vstr))
    return vstr


def umbrella_from_request(request):
    """This function is used to match requests that contain a resource_type
        in the matchdict. If that string in not in the _RESOURCE_TYPE_2_SETTINGS_UMBRELLA_KEY
        dict, then a 404 is raised. Otherwise the appropriate "umbrella" is located
        in the global settings, and the view function is called with the
        request and the umbrella object as the first 2 arguments"""
    rtstr = request.matchdict.get('resource_type')
    key_name = _RESOURCE_TYPE_2_SETTINGS_UMBRELLA_KEY.get(rtstr)
    if key_name is None:
        raise httpexcept(HTTPNotFound, 'Resource type "{}" is not supported'.format(rtstr))
    return request.registry.settings[key_name]


def doc_id_from_request(request):
    """This function is used to match requests that contain a resource_type
        in the matchdict. If that string in not in the _RESOURCE_TYPE_2_SETTINGS_UMBRELLA_KEY
        dict, then a 404 is raised. Otherwise the appropriate "umbrella" is located
        in the global settings, and the view function is called with the
        request and the umbrella object as the first 2 arguments"""
    doc_id = request.matchdict.get('doc_id')
    if doc_id is None:
        raise httpexcept(HTTPNotFound, 'Document ID required')
    return doc_id


def umbrella_with_id_from_request(request):
    return umbrella_from_request(request), doc_id_from_request(request)


def extract_posted_data(request):
    if request.POST:
        return request.POST
    if request.params:
        return request.params
    if request.text:
        return json.loads(request.text)
    raise httpexcept(HTTPBadRequest, "no POSTed data", explanation='No data obtained from POST')


def get_ids_of_synth_collections():
    # URL could be configurable, but I'm not sure we've ever changed this...
    url_of_synth_config = 'https://raw.githubusercontent.com/mtholder/propinquity/master/config.opentree.synth'
    try:
        resp = requests.get(url_of_synth_config)
        conf_fo = StringIO(resp.content)
    except:
        raise httpexcept(HTTPGatewayTimeout, 'Could not fetch synthesis list from {}'.format(url_of_synth_config))
    cfg = SafeConfigParser()
    try:
        cfg.readfp(conf_fo)
    except:
        raise httpexcept(HTTPInternalServerError, 'Could not parse file from {}'.format(url_of_synth_config))
    try:
        return cfg.get('synthesis', 'collections').split()
    except:
        msg = 'Could not find a collection list in file from {}'.format(url_of_synth_config)
        raise httpexcept(HTTPInternalServerError, msg)


def create_list_of_collections(cds, coll_id_list):
    coll_list = []
    for coll_id in coll_id_list:
        try:
            coll_list.append(cds.return_doc(coll_id, return_WIP_map=False)[0])
        except:
            msg = 'GET of collection {} failed'.format(coll_id)
            _LOG.exception(msg)
            raise httpexcept(HTTPNotFound, msg)
    return coll_list


def _synth_coll_helper(request):
    """Returns tuple of four elements:
        [0] tree_collection_doc_store,
        [1] list of the synth collection IDs
        [2] a list of each of the synth collection objects in the same order as coll_id_list
        [3] a collection that is a concatenation of synth collections
    """
    coll_id_list = get_ids_of_synth_collections()
    cds = request.registry.settings['tree_collections']
    coll_list = create_list_of_collections(cds, coll_id_list)
    try:
        concat = concatenate_collections(coll_list)
    except:
        msg = 'concatenation of collections failed'
        _LOG.exception(msg)
        return HTTPInternalServerError(body=msg)
    return cds, coll_id_list, coll_list, concat


@view_config(route_name='trees_in_synth', renderer='json')
def trees_in_synth(request):
    return _synth_coll_helper(request)[3]

def _coll_args_helper(request):
    data = extract_posted_data(request)
    try:
        study_id = data['study_id'].strip()
        assert study_id
        tree_id = data['tree_id'].strip()
        assert tree_id
    except:
        raise httpexcept(HTTPBadRequest, "Expecting study_id and tree_id arguments")
    auth_info = authenticate(**data)
    return data, study_id, tree_id, auth_info

@view_config(route_name='include_tree_in_synth', renderer='json')
def include_tree_from_synth(request):
    data, study_id, tree_id, auth_info = _coll_args_helper(request)
    # examine this study and tree, to confirm it exists *and* to capture its name
    sds = request.registry.settings['phylesystem']
    try:
        found_study = sds.return_doc(study_id, commit_sha=None, return_WIP_map=False)[0]
        match_list = extract_tree_nexson(found_study, tree_id=tree_id)
        if len(match_list) != 1:
            raise KeyError('tree id not found')
        found_tree = match_list[0][1]
        found_tree_name = found_tree['@label'] or tree_id
    except:  # report a missing/misidentified tree
        msg = "Specified tree '{t}' in study '{s}' not found! Save this study and try again?"
        raise httpexcept(HTTPNotFound, msg.format(s=study_id, t=tree_id))
    cds, coll_id_list, coll_list, current_synth_coll = _synth_coll_helper(request)
    if cds.collection_includes_tree(current_synth_coll, study_id, tree_id):
        return current_synth_coll
    commit_msg = "Added via API (include_tree_in_synth)"
    comment = commit_msg + " from {p}"
    comment = comment.format(p=found_study.get('nexml', {}).get('^ot:studyPublicationReference', ''))
    decision = cds.create_tree_inclusion_decision(study_id=study_id,
                                                  tree_id=tree_id,
                                                  name=found_tree_name,
                                                  comment=comment)
    # find the default synth-input collection and parse its JSON
    default_collection_id = coll_id_list[-1]
    append_tree_to_collection_helper(request, cds, default_collection_id, decision, auth_info, commit_msg=commit_msg)
    return trees_in_synth(request)


@view_config(route_name='exclude_tree_from_synth', renderer='json')
def exclude_tree_from_synth(request):
    data, study_id, tree_id, auth_info = _coll_args_helper(request)
    cds, coll_id_list, coll_list, current_synth_coll = _synth_coll_helper(request)
    if not current_synth_coll.includes_tree(study_id, tree_id):
        return current_synth_coll
    needs_push = {}
    for coll_id, coll in itertools.izip(coll_id_list, coll_list):
        if cds.collection_includes_tree(coll, study_id, tree_id):
            try:
                r = cds.purge_tree_from_collection(coll_id,
                                                   study_id=study_id,
                                                   tree_id=tree_id,
                                                   auth_info=auth_info,
                                                   commit_msg="Updated via API (exclude_tree_from_synth)")
                commit_return = r
            except GitWorkflowError, err:
                raise httpexcept(HTTPInternalServerError, err.msg)
            except:
                raise httpexcept(HTTPBadRequest, traceback.format_exc())
            # We only need to push once per affected shard even if multiple collections in the shard change...
            mn = commit_return.get('merge_needed')
            if (mn is not None) and (not mn):
                shard = cds.get_shard(coll_id)
                needs_push[id(shard)] = coll_id
    for coll_id in needs_push.values():
        trigger_push(request, cds, coll_id, 'EDIT', auth_info=auth_info)
    return trees_in_synth(request)


def append_tree_to_collection_helper(request, cds, collection_id, include_decision, auth_info, commit_msg):
    try:
        r = cds.append_include_decision(collection_id, include_decision, auth_info=auth_info, commit_msg=commit_msg)
        commit_return = r
    except GitWorkflowError, err:
        raise httpexcept(HTTPInternalServerError, err.msg)
    except:
        raise httpexcept(HTTPBadRequest, traceback.format_exc())
    # check for 'merge needed'?
    mn = commit_return.get('merge_needed')
    if (mn is not None) and (not mn):
        trigger_push(request, cds, collection_id, 'EDIT', auth_info)


@view_config(route_name='versioned_home', renderer='json')
@view_config(route_name='home', renderer='json')
def index(request):
    return {
        "description": "The Open Tree API",
        "source_url": "https://github.com/mtholder/pyraphyletic",
        "documentation_url": "https://github.com/OpenTreeOfLife/phylesystem-api/tree/master/docs"
    }


@view_config(route_name='render_markdown', request_method='POST')
def render_markdown(request):
    data = extract_posted_data(request)
    try:
        src = data['src']
    except KeyError:
        raise httpexcept(HTTPBadRequest, '"src" parameter not found in POST')

    def add_blank_target(attrs, new=False):
        attrs['target'] = '_blank'
        return attrs

    h = markdown.markdown(src)
    h = bleach.clean(h, tags=['p', 'a', 'hr', 'i', 'em', 'b', 'div', 'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4'])
    h = bleach.linkify(h, callbacks=[add_blank_target])
    return Response(h)


@view_config(route_name='generic_push_failure', renderer='json')
def push_failure(request):
    umbrella = umbrella_from_request(request)
    settings = request.registry.settings
    pfd_lock = settings['push_failure_lock']
    pfd = settings['doc_type_to_push_failure_list']
    pf = copy_of_push_failures(push_failure_dict=pfd, push_failure_dict_lock=pfd_lock, umbrella=umbrella)
    return {'doc_type': umbrella.document_type,
            'pushes_succeeding': len(pf) == 0,
            'errors': pf, }


@view_config(route_name='generic_list', renderer='json')
def generic_list(request):
    return umbrella_from_request(request).get_doc_ids()


@view_config(route_name='generic_config', renderer='json')
def generic_config(request):
    return umbrella_from_request(request).get_configuration_dict()


@view_config(route_name='unmerged_branches', renderer='json')
def unmerged_branches(request):
    """Returns the non-master branches for a resource_type.
    Default is request.matchdict['resource_type'] is 'phylesystem'.
    """
    umbrella = umbrella_from_request(request)
    bs = set(umbrella.get_branch_list())
    bl = [i for i in bs if i != 'master']
    bl.sort()
    return bl


def external_url_generic_helper(umbrella, doc_id, doc_id_key):
    try:
        u = umbrella.get_public_url(doc_id)
        return {'url': u, doc_id_key: doc_id}
    except:
        msg = 'document {} not found'.format(doc_id)
        _LOG.exception(msg)
        raise HTTPNotFound(title=msg, body=json.dumps({'error': 1, 'description': msg}))


@view_config(route_name='generic_external_url', renderer='json')
def external_url(request):
    umbrella, doc_id = umbrella_with_id_from_request(request)
    return external_url_generic_helper(umbrella, doc_id, 'doc_id')


def subresource_request(request):
    """Helper function for get_document separates params into output and input dicts

    This function composes a pair of dicts:
        the first (subresource_req_dict) is the argument to umbrella.is_plausible_transformation
        the second (culled_params) is set of input specification details.

    The goal is to adapt the peculiarities of the URL/http data into a more
    standardized set of dict.

    On output, subresource_req_dict can have:
        * output_is_json: bool default True (may be set to False in umbrella.is_plausible_transformation)
        * output_format: mapping to a dict which can contain any of the following. all absent -> no transformation
                {'schema': format name or None,
                 'type_ext': file extension or None
                 'schema_version': default '0.0.0' or the param['output_nexml2json'],
                 'tip_label': string like 'ot:ottTaxonName' for newick, NEXUS output
                 bracket_ingroup -> bool
                }
        * subresource_req_dict['subresource_type'] = string
        * subresource_id = string or (string, string) set of IDs

    culled_params holds two fields describing the core input:
        * resource_type -> ['study', 'taxon_amendments', 'tree_collections', ...]
        * doc_id -> string, ID of top-level document
    and the following option specifiers
        * version_history -> bool, True to include versionHistory in response
        * external_url -> bool, True to include external_url in response
        * starting_commit_SHA -> string or None
    """
    subresource_req_dict = {'output_is_json': True}
    culled_params = {}
    # default behaviors, here. Overloaded by request specific args below
    params = {'version_history': True}
    params.update(request.params)
    params.update(dict(request.matchdict))
    try:
        b = request.json_body
        _LOG.debug('request.json_body={}'.format(b))
        params.update(b)
    except:
        pass
    _LOG.debug('request.params={}'.format(request.params))
    _LOG.debug('request.matchdict={}'.format(request.matchdict))
    _LOG.debug('params={}'.format(params))
    doc_id = params['doc_id']
    culled_params['doc_id'] = doc_id
    culled_params['version_history'] = params['version_history']
    culled_params['external_url'] = params.get('external_url', False)
    culled_params['starting_commit_SHA'] = params.get('starting_commit_SHA')
    resource_type = params['resource_type']
    culled_params['resource_type'] = resource_type
    last_word = request.path.split('/')[-1]
    last_word_dot_split = last_word.split('.')
    last_word_was_doc_id = True
    type_ext = None
    if len(last_word_dot_split) > 1:
        type_ext = '.' + last_word_dot_split[-1]
    explicit_format = params.get('format')
    out_fmt = {'schema': explicit_format,
               'type_ext': type_ext}
    subresource_req_dict['output_format'] = out_fmt
    if resource_type == 'study':
        subresource_type = params.get('subresource_type')
        out_fmt['schema_version'] = params.get('output_nexml2json', '0.0.0')
        tree_opts = NexsonDocSchema.optional_output_detail_keys
        for trop in tree_opts:
            out_fmt[trop] = params.get(trop)
        if subresource_type is not None:
            subresource_req_dict['subresource_type'] = subresource_type
            subresource_id = params.get('subresource_id')
            if subresource_id is not None:
                last_word_was_doc_id = False
                if '.' in subresource_id:
                    subresource_id = '.'.join(subresource_id.split('.')[:-1])
                subresource_req_dict['subresource_id'] = subresource_id
            # subtrees need (tree_id, subtree_id) as their "subresource_id"
            if subresource_type == 'subtree':
                subtree_id = params.get('subtree_id')
                if (subtree_id is None) or (subresource_id is None):
                    _edescrip = 'subtree resource requires a study_id and tree_id in the URL and a subtree_id parameter'
                    raise httpexcept(HTTPBadRequest, err_body(_edescrip))
                subresource_req_dict['subresource_id'] = (subresource_id, subtree_id)
    # if we get {resource_type}/ot_1424.json we want to treat ot_1424 as the ID
    if (len(last_word_dot_split) > 1) and last_word_was_doc_id:
        if last_word == doc_id:
            culled_params['doc_id'] = '.'.join(last_word_dot_split[:-1])
    return subresource_req_dict, culled_params


@view_config(route_name='get_study_subresource_no_id', renderer='json', request_method='GET')
@view_config(route_name='get_study_subresource_via_id', renderer='json', request_method='GET')
@view_config(route_name='get_study_via_id_and_ext', renderer='json', request_method='GET')
@view_config(route_name='get_study_via_id', renderer='json', request_method='GET')
def get_study_document(request):
    request.matchdict['resource_type'] = 'study'
    return get_document(request)


@view_config(route_name='get_taxon_amendment_via_id', renderer='json', request_method='GET')
def get_amendment_document(request):
    request.matchdict['resource_type'] = 'taxon_amendments'
    request.matchdict['external_url'] = True
    return get_document(request)


@view_config(route_name='get_tree_collection_via_id', renderer='json', request_method='GET')
def get_collection_document(request):
    request.matchdict['resource_type'] = 'tree_collections'
    request.matchdict['external_url'] = True
    u_c = [request.matchdict.get('coll_user_id', ''), request.matchdict.get('coll_id', ''), ]
    request.matchdict['doc_id'] = '/'.join(u_c)
    return get_document(request)


def get_document(request):
    """OpenTree API methods relating to reading"""
    resource_type = request.matchdict['resource_type']
    umbrella = umbrella_from_request(request)
    subresource_req_dict, params = subresource_request(request)
    doc_id = params['doc_id']
    triple = umbrella.is_plausible_transformation(subresource_req_dict)
    is_plausible, reason_or_converter, out_syntax = triple
    if not is_plausible:
        raise httpexcept(HTTPBadRequest, 'Impossible request: {}'.format(reason_or_converter))
    transformer = reason_or_converter
    parent_sha = params.get('starting_commit_SHA')
    _LOG.debug('parent_sha = {}'.format(parent_sha))
    version_history = None
    try:
        if (out_syntax == 'JSON') and params['version_history']:
            r, version_history = umbrella.return_document_and_history(doc_id,
                                                                      commit_sha=parent_sha,
                                                                      return_WIP_map=True)
        else:
            r = umbrella.return_document(doc_id, commit_sha=parent_sha, return_WIP_map=True)
    except:
        _LOG.exception('GET failed')
        raise HTTPNotFound('{r} document {i} GET failure'.format(r=resource_type, i=doc_id))
    # noinspection PyBroadException
    try:
        document_blob, head_sha, wip_map = r
    except:
        _LOG.exception('GET failed')
        raise httpexcept(HTTPBadRequest, err_body(traceback.format_exc()))
    if transformer is None:
        result_data = document_blob
    else:
        try:
            result_data = transformer(umbrella, doc_id, document_blob, head_sha)
        except KeyError, x:
            raise httpexcept(HTTPNotFound, 'subresource not found: {}'.format(x))
        except ValueError, y:
            raise httpexcept(HTTPBadRequest, 'subresource not found: {}'.format(y.message))
        except:
            msg = "Exception in coercing to the document to the requested type. "
            _LOG.exception(msg)
            raise httpexcept(HTTPBadRequest, err_body(msg))
    if subresource_req_dict['output_is_json']:
        result = {'sha': head_sha,
                  'data': result_data,
                  'branch2sha': wip_map,
                  'url': request.url,
                  }
        try:
            comment_html = render_markdown(umbrella.get_markdown_comment(result_data))
        except:
            comment_html = ''
        result['commentHTML'] = comment_html
        try:
            if version_history is not None:
                result['version_history'] = version_history
                result['versionHistory'] = result['version_history']  # TODO get rid of camelCaseVersion
        except:
            _LOG.exception('populating of version_history failed for {}'.format(doc_id))
        try:
            if params.get('external_url'):
                result['external_url'] = umbrella.get_public_url(doc_id)
        except:
            _LOG.exception('populating of external_url failed for {}'.format(doc_id))
        try:
            result['shardName'] = umbrella.get_repo_and_path_fragmen(doc_id)[0]
        except:
            _LOG.exception('populating of shardName failed for {}'.format(doc_id))
        if resource_type == 'study':
            duplicate_study_ids = []
            try:
                study_doi = document_blob['nexml']['^ot:studyPublication']['@href']
                oti_domain = request.registry.settings.get('oti_domain', 'https://api.opentreeoflife.org')
                duplicate_study_ids = find_studies_by_doi(oti_domain, study_doi)
                try:
                    duplicate_study_ids.remove(doc_id)
                except:
                    pass
            except:
                _LOG.exception('Call to find_studies_by_doi failed')
            if duplicate_study_ids:
                result['duplicateStudyIDs'] = duplicate_study_ids
        return result
    request.override_renderer = 'string'
    return Response(body=result_data, content_type='text/plain')


@view_config(route_name='put_study_via_id', renderer='json', request_method='PUT')
def put_study_document(request):
    request.matchdict['resource_type'] = 'study'
    return put_document(request)


@view_config(route_name='put_taxon_amendment_via_id', renderer='json', request_method='PUT')
def put_amendment_document(request):
    request.matchdict['resource_type'] = 'taxon_amendments'
    return put_document(request)


@view_config(route_name='put_tree_collection_via_id', renderer='json', request_method='PUT')
def put_collection_document(request):
    request.matchdict['resource_type'] = 'tree_collections'
    u_c = [request.matchdict.get('coll_user_id', ''), request.matchdict.get('coll_id', ''), ]
    request.matchdict['doc_id'] = '/'.join(u_c)
    return put_document(request)


@view_config(route_name='push_study_via_id', renderer='json', request_method='PUT')
def push_study_document(request):
    request.matchdict['resource_type'] = 'study'
    return push_document(request)


@view_config(route_name='push_taxon_amendment_via_id', renderer='json', request_method='PUT')
def push_amendment_document(request):
    request.matchdict['resource_type'] = 'taxon_amendments'
    return push_document(request)


@view_config(route_name='push_tree_collection_via_id', renderer='json', request_method='PUT')
def push_collection_document(request):
    request.matchdict['resource_type'] = 'tree_collections'
    u_c = [request.matchdict.get('coll_user_id', ''), request.matchdict.get('coll_id', ''), ]
    request.matchdict['doc_id'] = '/'.join(u_c)
    return push_document(request)


@view_config(route_name='generic_push', renderer='json')
def generic_push(request, doc_id=None):
    umbrella = umbrella_from_request(request)
    gpj = GitPushJob(request=request,
                     umbrella=umbrella,
                     doc_id=doc_id,
                     operation='USER-TRIGGERED PUSH')
    gpj.push_to_github()
    return gpj.get_response_obj()


def push_document(request):
    return generic_push(request, doc_id=request.matchdict['doc_id'])


def _make_valid_DOI(candidate):
    # Try to convert the candidate string to a proper, minimal DOI. Return the DOI,
    # or None if conversion is not possible.
    #   WORKS: http://dx.doi.org/10.999...
    #   WORKS: 10.999...
    #   FAILS: 11.999...
    #   WORKS: doi:10.999...
    #   WORKS: DOI:10.999...
    #   FAILS: http://example.com/
    #   WORKS: http://example.com/10.blah
    #   FAILS: something-else
    # Remove all whitespace from the candidate string
    candidate = ''.join(candidate.split())
    # All existing DOIs use the directory indicator '10.', see
    #   http://www.doi.org/doi_handbook/2_Numbering.html#2.2.2
    doi_prefix = '10.'
    if doi_prefix not in candidate:
        return None
    # remove anything before the first 10.
    doi_parts = candidate.split(doi_prefix)
    doi_parts[0] = ''
    return doi_prefix.join(doi_parts[:])


@view_config(route_name='post_study', renderer='json', request_method='POST')
def post_study_document(request):
    request.matchdict['resource_type'] = 'study'
    document, post_args = extract_write_args(request, study_post=True)
    if post_args.get('doc_id') is None:
        raise httpexcept(HTTPBadRequest, 'POST operation does not expect a URL that ends with a document ID')
    umbrella = umbrella_from_request(request)
    import_method = post_args['import_method']
    nsv = umbrella.document_schema.schema_version
    cc0_agreement = post_args['cc0_agreement']
    publication_doi = post_args['publication_DOI']
    if publication_doi:
        # if a URL or something other than a valid DOI was entered, don't submit it to crossref API
        publication_doi_for_crossref = _make_valid_DOI(publication_doi) or None
    publication_ref = post_args['publication_reference']
    if import_method == 'import-method-TREEBASE_ID':
        treebase_id = post_args['treebase_id']
        if not treebase_id:
            msg = "A treebase_id argument is required when import_method={}".format(import_method)
            raise httpexcept(HTTPBadRequest, msg)
        try:
            treebase_number = int(treebase_id.upper().lstrip('S'))
        except:
            msg = 'Invalid treebase_id="{}"'.format(treebase_id)
            raise httpexcept(HTTPBadRequest, msg)
        try:
            document = import_nexson_from_treebase(treebase_number, nexson_syntax_version=nsv)
        except Exception as e:
            msg = "Unexpected error parsing the file obtained from TreeBASE. " \
                  "Please report this bug to the Open Tree of Life developers."
            raise httpexcept(HTTPBadRequest, msg)
    elif import_method == 'import-method-PUBLICATION_DOI' or import_method == 'import-method-PUBLICATION_REFERENCE':
        if not (publication_ref or publication_doi_for_crossref):
            msg = 'Did not find a valid DOI in "publication_DOI" or a reference in "publication_reference" arguments.'
            raise httpexcept(HTTPBadRequest, msg)
        document = import_nexson_from_crossref_metadata(doi=publication_doi_for_crossref,
                                                        ref_string=publication_ref,
                                                        include_cc0=cc0_agreement)
    elif import_method == 'import-method-POST':
        if not document:
            msg = 'Could not read a NexSON from the body of the POST, but import_method="import-method-POST" was used.'
            raise httpexcept(HTTPBadRequest, msg)
    else:
        document = umbrella.document_schema.create_empty_doc()
        if cc0_agreement:
            add_cc0_waiver(nexson=document)
    return finish_write_operation(request, umbrella, document, post_args)


@view_config(route_name='post_taxon_amendment', renderer='json', request_method='POST')
def post_amendment_document(request):
    request.matchdict['resource_type'] = 'taxon_amendments'
    return post_document(request)


@view_config(route_name='post_tree_collection', renderer='json', request_method='POST')
def post_collection_document(request):
    request.matchdict['resource_type'] = 'tree_collections'
    return post_document(request)


_RESOURCE_TYPE_2_DATA_JSON_ARG = {'study': 'nexson',
                                  'taxon_amendments': 'json',
                                  'tree_collections': 'json'}


def extract_write_args(request, study_post=False):
    """Helper for a write-verb views. Joins params, matchdict and the JSON body
    of the request into a dict with keys:
        `auth_info`: {'login': gh-username,
                      'name': user's name or None,
                      'email': user's email from GH or None
                    }
    The following keys will hold string or None:
        'starting_commit_SHA' SHA of parent of commit
        'commit_msg' content of commit message
        'merged_SHA',
        'doc_id' ID (required for PUT, but not POST)
        'resource_type'
    if study_post is True, the following string-valued keys will also be found
        'import_method'
        'import_from_location', 'treebase_id',  'nexml_fetch_url', 'nexml_pasted_string',
        'publication_DOI', 'publication_reference',)

        cc0_agreement ==> bool (kwargs.get('chosen_license', '') == 'apply-new-CC0-waiver' and
                             kwargs.get('cc0_agreement'
    raises Forbidden if auth fails
    """
    culled_params = {}
    # default behaviors, here. Overloaded by request specific args below
    params = {}
    params.update(request.params)
    params.update(dict(request.matchdict))
    _LOG.debug('request.params={}'.format(request.params))
    _LOG.debug('request.matchdict={}'.format(request.matchdict))
    _LOG.debug('params={}'.format(params))
    resource_type = params['resource_type']
    data_kwarg_key = _RESOURCE_TYPE_2_DATA_JSON_ARG[resource_type]
    try:
        b = request.json_body
        for key, value in b.items():
            if key != data_kwarg_key:
                params[key] = value
    except:
        pass
    culled_params['auth_info'] = authenticate(**params)
    str_key_list = ('starting_commit_SHA', 'commit_msg', 'merged_SHA', 'doc_id', 'resource_type',)
    if study_post:
        additional_str_key = ('import_method', 'import_from_location', 'treebase_id', 'nexml_fetch_url',
                              'nexml_pasted_string', 'publication_DOI', 'publication_reference')
        cc0 = ((params.get('chosen_license', '') == 'apply-new-CC0-waiver')
               and (kwargs.get('cc0_agreement', '') == 'true'))
        culled_params['cc0_agreement'] = cc0
    else:
        additional_str_key = []
    for key in str_key_list:
        culled_params[key] = params.get(key)
    for key in additional_str_key:
        culled_params[key] = params.get(key)

    document_object = _extract_json_obj_from_http_call(request, data_kwarg_key=data_kwarg_key)
    _LOG.debug('culled_params = {}'.format(culled_params))
    return document_object, culled_params


def post_document(request):
    """Open Tree API methods relating to creating a new resource"""
    document, post_args = extract_write_args(request)
    if post_args.get('doc_id') is None:
        raise httpexcept(HTTPBadRequest, 'POST operation does not expect a URL that ends with a document ID')
    umbrella = umbrella_from_request(request)
    return finish_write_operation(request, umbrella, document, post_args)


def put_document(request):
    """Open Tree API methods relating to updating existing resources"""
    document, put_args = extract_write_args(request)
    if put_args.get('starting_commit_SHA') is None:
        raise httpexcept(HTTPBadRequest,
                         'PUT operation expects a "starting_commit_SHA" argument with the SHA of the parent')
    if put_args.get('doc_id') is None:
        raise httpexcept(HTTPBadRequest, 'PUT operation expects a URL that ends with a document ID')
    umbrella = umbrella_from_request(request)
    return finish_write_operation(request, umbrella, document, put_args)


def finish_write_operation(request, umbrella, document, put_args):
    auth_info = put_args['auth_info']
    parent_sha = put_args.get('starting_commit_SHA')
    doc_id = put_args.get('doc_id')
    resource_type = put_args['resource_type']
    commit_msg = put_args.get('commit_msg')
    merged_sha = put_args.get('merged_SHA')
    lmsg = '{} of {} with doc id = {} for starting_commit_SHA = {} and merged_SHA = {}'
    _LOG.debug(lmsg.format(request.method, resource_type, doc_id, parent_sha, merged_sha))
    bundle = umbrella.validate_and_convert_doc(document, put_args)
    processed_doc, errors, annotation, doc_adaptor = bundle
    if len(errors) > 0:
        msg = 'JSON {rt} payload failed validation with {nerrors} errors:\n{errors}'
        msg = msg.format(rt=resource_type, nerrors=len(errors), errors='\n  '.join(errors))
        _LOG.exception(msg)
        raise httpexcept(HTTPBadRequest, msg)
    try:
        annotated_commit = umbrella.annotate_and_write(document=processed_doc,
                                                       doc_id=doc_id,
                                                       auth_info=auth_info,
                                                       adaptor=doc_adaptor,
                                                       annotation=annotation,
                                                       parent_sha=parent_sha,
                                                       commit_msg=commit_msg,
                                                       merged_sha=merged_sha)
    except GitWorkflowError, err:
        _LOG.exception('write operation failed in annotate_and_write')
        raise httpexcept(HTTPBadRequest, err.msg)
    if annotated_commit.get('error', 0) != 0:
        raise httpexcept(HTTPBadRequest, json.dumps(annotated_commit))

    mn = annotated_commit.get('merge_needed')
    if (mn is not None) and (not mn):
        trigger_push(request, umbrella, doc_id, 'EDIT', auth_info)
    return annotated_commit


def trigger_push(request, umbrella, doc_id, operation, auth_info=None):
    settings = request.registry.settings
    joq_queue = settings['job_queue']
    gpj = GitPushJob(request=request, umbrella=umbrella, doc_id=doc_id, operation=operation, auth_info=auth_info)
    joq_queue.put(gpj)


# TODO: the following helper (and its 2 views) need to be cached, if we are going to continue to support them.
def fetch_all_docs_and_last_commit(docstore):
    doc_list = []
    for doc_id, props in docstore.iter_doc_objs():
        _LOG.debug('doc_id = {}'.format(doc_id))
        # reckon and add 'lastModified' property, based on commit history?
        latest_commit = docstore.get_version_history_for_doc_id(doc_id)[0]
        props.update({
            'id': doc_id,
            'lastModified': {
                'author_name': latest_commit.get('author_name'),
                'relative_date': latest_commit.get('relative_date'),
                'display_date': latest_commit.get('date'),
                'ISO_date': latest_commit.get('date_ISO_8601'),
                'sha': latest_commit.get('id')  # this is the commit hash
            }
        })
        doc_list.append(props)
    return doc_list


@view_config(route_name='fetch_all_amendments', renderer='json')
def fetch_all_amendments(request):
    return fetch_all_docs_and_last_commit(request.registry.settings['taxon_amendments'])


@view_config(route_name='fetch_all_collections', renderer='json')
def fetch_all_collections(request):
    return fetch_all_docs_and_last_commit(request.registry.settings['tree_collections'])


# TODO: deprecate the URLs below here
# TODO: deprecate in favor of generic_list
@view_config(route_name='phylesystem_config', renderer='json')
def phylesystem_config(request):
    return request.registry.settings['phylesystem'].get_configuration_dict()


# TODO: deprecate in favor of generic_list
@view_config(route_name='study_list', renderer='json')
def study_list(request):
    return request.registry.settings['phylesystem'].get_study_ids()


# TODO: deprecate in favor of generic_external_url
@view_config(route_name='study_external_url', renderer='json')
def study_external_url(request):
    phylesystem = request.registry.settings['phylesystem']
    study_id = request.matchdict['study_id']
    return external_url_generic_helper(phylesystem, study_id, 'study_id')


# TODO: deprecate in favor of generic_list
@view_config(route_name='amendment_list', renderer='json')
def list_all_amendments(request):
    return request.registry.settings['taxon_amendments'].get_doc_ids()


@view_config(route_name='options_study_id', renderer='json', request_method='OPTIONS')
@view_config(route_name='options_taxon_amendment_id', renderer='json', request_method='OPTIONS')
@view_config(route_name='options_tree_collection_id', renderer='json', request_method='OPTIONS')
@view_config(route_name='options_generic', renderer='json', request_method='OPTIONS')
def study_options(request):
    """A simple method for approving CORS preflight request"""
    response = Response(status_code=200)
    if request.env.http_access_control_request_method:
        response.headers['Access-Control-Allow-Methods'] = 'POST,GET,DELETE,PUT,OPTIONS'
    if request.env.http_access_control_request_headers:
        response.headers['Access-Control-Allow-Headers'] = 'Origin, Content-Type, Accept, Authorization'
    return response


def _harvest_study_ids_from_paths(path_list):
    rs = {}
    for path in path_list:
        path_parts = path.split('/')
        if path_parts[0] == "study":
            # skip any intermediate directories in docstore repo
            study_id = path_parts[ len(path_parts) - 2 ]
            rs.add(study_id)
    return rs

def get_otindex_base_url(request):
    return 'hardcoded incorrect URL'

def nudgeStudyIndexOnUpdates(request):
    """"Support method to update oti index in response to GitHub webhooks

    This examines the JSON payload of a GitHub webhook to see which studies have
    been added, modified, or removed. Then it calls oti's index service to
    (re)index the NexSON for those studies, or to delete a study's information if
    it was deleted from the docstore.

    Finally, we clear the cached study list (response to find_studies with no args).

    N.B. This depends on a GitHub webhook on the chosen docstore.
    """
    payload = request.vars
    try:
        # how we nudge the index depends on which studies are new, changed, or deleted
        added_study_ids = {}
        modified_study_ids = {}
        removed_study_ids = {}
        # TODO: Should any of these lists override another? maybe use commit timestamps
        # to "trump" based on later operations?
        for commit in payload['commits']:
            added_study_ids |= _harvest_study_ids_from_paths(commit['added'])
            modified_study_ids |= _harvest_study_ids_from_paths(commit['modified'])
            removed_study_ids |= _harvest_study_ids_from_paths(commit['removed'])
    except:
        raise httpexcept(HTTPBadRequest, "malformed GitHub payload")
    sds = request.registry.settings["study"]
    # this check will not be sufficient if we have multiple shards
    opentree_docstore_url = sds.get_remote_docstore_url
    if payload['repository']['url'] != opentree_docstore_url:
        raise httpexcept(HTTPBadRequest, "wrong repo for this API instance")
    otindex_base_url = get_otindex_base_url(request)
    msg = ""
    if add_or_update_ids:
        msg += _otindex_call(add_or_update_ids, otindex_base_url, 'add_update')
    if remove_ids:
        msg += _otindex_call(remove_ids, otindex_base_url, 'remove')
    # TODO: check returned IDs against our original list... what if something failed?

    github_webhook_url = "{}/settings/hooks".format(opentree_docstore_url)
    full_msg = """This URL should be called by a webhook set in the docstore repo:
    <br /><br /><a href="{}">{}</a><br /><pre>{}</pre>"""
    full_msg = full_msg.format(github_webhook_url, github_webhook_url, msg)
    if msg:
        raise httpexcept(HTTPInternalServerError, full_msg)
    return full_msg


def do_http_post_json(url, data=None):
    try:
        resp = requests.post(url,
                             headers={"Content-Type": "application/json"},
                             data=data,
                             allow_redirects=True)
        return resp.json()
    except Exception as e:
        raise httpexcept(HTTPInternalServerError, "Unexpected error calling {}: {}".format(url, e.message))


def _otindex_call(study_ids, otindex_base_url, oti_verb):
    nudge_url = "{o}/v3/studies/{v}".format(o=otindex_base_url, v=oti_verb)
    payload = {"studies" : study_ids}
    response = do_http_post_json(nudge_url, data=payload)
    if response['failed_studies']:
        msg = "Could not {v} following studies: {s}".format(s=", ".join(response['failed_studies']), v=oti_verb)
        _LOG.debug(msg)
        return msg
    return ''


# The portion of this file that deals with the jobq and thread-safe
# execution of delayed tasks is based on the scheduler.py file, which is part of SATe

# SATe is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

# Jiaye Yu and Mark Holder, University of Kansas
