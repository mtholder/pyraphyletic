"""Helper functions used by views in the phylesystem API.

Functions that are called by views.py, but which are too esoteric or ws-specific to belong in
peyotl.
"""
import copy
import json
import os
import traceback
from Queue import Queue
from threading import Lock, Thread

import requests
# noinspection PyPackageRequirements
from github import Github, BadCredentialsException
from peyotl import (create_doc_store_wrapper,
                    get_logger, GitWorkflowError,
                    NexsonDocSchema,
                    OTI,
                    SafeConfigParser, StringIO)
from pyramid.httpexceptions import (HTTPNotFound, HTTPBadRequest, HTTPForbidden,
                                    HTTPConflict, HTTPGatewayTimeout, HTTPInternalServerError)

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
                                          'taxon_amendment': 'taxon_amendments',
                                          'amendments': 'taxon_amendments',
                                          'amendment': 'taxon_amendments',
                                          'tree_collections': 'tree_collections',
                                          'tree_collection': 'tree_collections',
                                          'collections': 'tree_collections',
                                          'collection': 'tree_collections',
                                          }

_RESOURCE_TYPE_2_DATA_JSON_ARG = {'study': 'nexson',
                                  'taxon_amendments': 'json',
                                  'tree_collections': 'json'}


######################################################################################
# Working with the global resources avaialable through the request

def fill_app_settings(settings):
    """Fills a settings dict with:
    * 'phylesystem', 'taxon_amendments', 'tree_collections' ==> umbrella
    * 'doc_type_to_push_failure_list' ==> {}
    * 'push_failure_lock' ==> mutex Lock for doc_type_to_push_failure_list
    * 'job_queue' ==> a thread safe queue to hold deferred jobs

    As a side effect, launches a worker thread to deal with pushes
    """
    start_worker(1)
    wrapper = _create_doc_store_wrapper(settings)
    settings['phylesystem'] = wrapper.phylesystem
    settings['taxon_amendments'] = wrapper.taxon_amendments
    settings['tree_collections'] = wrapper.tree_collections
    # Thread-safe dict that map doc type to lists of push failure messages.
    settings['doc_type_to_push_failure_list'] = {}
    settings['push_failure_lock'] = Lock()
    settings['job_queue'] = _jobq


def _create_doc_store_wrapper(settings):
    """Uses the (configuration-dependent) settings dict to create a doc store wrapper."""
    global _DOC_STORE
    if _DOC_STORE is not None:
        return _DOC_STORE
    repo_parent = settings['repo_parent']
    _LOG.debug('creating Doc Store Wrapper from repo_parent="{}"'.format(repo_parent))
    _DOC_STORE = create_doc_store_wrapper(repo_parent)
    _LOG.debug('repo_nexml2json = {}'.format(_DOC_STORE.phylesystem.repo_nexml2json))
    return _DOC_STORE


def get_taxonomy_api_base_url(request):
    """Returns the start of the URL used to call taxonomy ws. This is configuration dependent."""
    return request.registry.settings['taxonomy_api_base_url']


# noinspection PyUnusedLocal
def get_otindex_base_url(request):  # pylint: disable=W0613
    """Returns the start of the URL used to call otindex ws. This is configuration dependent."""
    return request.registry.settings['otindex_base_url']


def get_phylesystem_doc_store(request):
    """Returns the phylesystem doc store that was created during server initialization."""
    return request.registry.settings["phylesystem"]


def get_taxon_amendments_doc_store(request):
    """Returns the taxonomic amendments doc store that was created during server initialization."""
    return request.registry.settings["taxon_amendments"]


def get_tree_collections_doc_store(request):
    """Returns the tree collections doc store that was created during server initialization."""
    return request.registry.settings["tree_collections"]


def get_resource_type_to_umbrella_name_copy():
    """As an interim measure we support some aliasing of "resource_type" strings
    to the different types of document store "umbrellas". This function
    returns a copy of the dict that performs that mapping."""
    return copy.copy(_RESOURCE_TYPE_2_SETTINGS_UMBRELLA_KEY)


def umbrella_from_request(request):
    """Match requests that contain a resource_type
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
    """Match requests that contain a resource_type
    in the matchdict. If that string in not in the _RESOURCE_TYPE_2_SETTINGS_UMBRELLA_KEY
    dict, then a 404 is raised. Otherwise the appropriate "umbrella" is located
    in the global settings, and the view function is called with the
    request and the umbrella object as the first 2 arguments"""
    doc_id = request.matchdict.get('doc_id')
    if doc_id is None:
        raise httpexcept(HTTPNotFound, 'Document ID required')
    return doc_id


def umbrella_with_id_from_request(request):
    """Returns (doc_store_umbrella, doc_id) for a document based on the matchdict of the request."""
    return umbrella_from_request(request), doc_id_from_request(request)


######################################################################################
# Helpers for general request/response manipulation
def httpexcept(except_class, message):
    """Returns an instance of `except_class` with a body that hos phylesystem API's error body.

    The error body is a dict with "error" -> 1 and a "description" mapping to `message`."""
    return except_class(body=err_body(message))


def err_body(description):
    """Returns a JSON-formatted string for a dict with `error`->1 and the `description`"""
    err = {'error': 1,
           'description': description}
    return json.dumps(err)


def authenticate(**kwargs):
    """Raises an HTTPForbidden error if `auth_token` is not a kwarg or it isn't a GitHub username

    returns a dict with 3 keys:
       `login` is the GitHub username
       `name` is kwargs.get('author_name', or the name associated w/ the GitHub user).
       `email` is kwargs.get('author_email', or the email address associated w/ the GitHub user).
    """
    # this is the GitHub API auth-token for a logged-in curator
    auth_token = kwargs.get('auth_token', '')
    if not auth_token:
        msg = "You must provide an auth_token to authenticate to the OpenTree API"
        raise httpexcept(HTTPForbidden, msg)
    if _LOCAL_TESTING_MODE:
        return {'login': 'fake_gh_login', 'name': 'Fake Name', 'email': 'fake@bogus.com'}
    gh = Github(auth_token)
    gh_user = gh.get_user()
    auth_info = {}
    try:
        auth_info['login'] = gh_user.login
    except BadCredentialsException:
        msg = "You have provided an invalid or expired authentication token"
        raise httpexcept(HTTPForbidden, msg)
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


def check_api_version(request):
    """Raises a 404 if the version string is not correct and returns the version string"""
    vstr = request.matchdict.get('api_version')
    if vstr not in _API_VERSIONS:
        raise httpexcept(HTTPNotFound, 'API version "{}" is not supported'.format(vstr))
    return vstr


def extract_posted_data(request):
    """Helper - returns a dict from a POST request, by checking the cascade: POST, params, text."""
    if request.POST:
        return request.POST
    if request.params:
        return request.params
    if request.text:
        return json.loads(request.text)
    raise httpexcept(HTTPBadRequest, "no POSTed data")


def finish_write_operation(request, umbrella, document, put_args):
    """Helper for finishing an EDIT or CREATE operation for a document.

        `request` the request object is curried to a `trigger_push` call if the call succeeds.
        `umbrella` is the doc store
        `document` is the content of the document
        `put_args` is a dict (parsed from the orginal request. Curried as `optional_args` to
            `commit_existing_doc_helper`, but also uses as a source of:
            "auth_info"
            "doc_id", and
            "commit_msg"

    If `put_args["doc_id"]` is empty, this function treats the document as a new resource,
        otherwise it is considered to be an edit.
    Before the annotate_and_write is called, umbrella.validate_and_convert_doc will be called
        to validate (and possibly transform) the `document`
        Raises as HTTPBadRequest or returns an annotated commit object. If a manual merge is not
        needed a push to GitHub will be triggered.
    """
    auth_info = put_args['auth_info']
    doc_id = put_args.get('doc_id')
    commit_msg = put_args.get('commit_msg')
    bundle = umbrella.validate_and_convert_doc(document, put_args)
    processed_doc, errors, annotation, doc_adaptor = bundle
    if len(errors) > 0:
        resource_type = put_args.get('resource_type')
        msg = 'JSON {rt} payload failed validation with {nerrors} errors:\n{errors}'
        msg = msg.format(rt=resource_type, nerrors=len(errors), errors='\n  '.join(errors))
        _LOG.exception(msg)
        raise httpexcept(HTTPBadRequest, msg)
    doc_bundle = (processed_doc, annotation, doc_adaptor)
    try:
        if doc_id is None:
            anco = commit_new_doc_helper(umbrella=umbrella,
                                         doc_bundle=doc_bundle,
                                         auth_info=auth_info,
                                         commit_msg=commit_msg)
        else:
            anco = commit_existing_doc_helper(umbrella=umbrella,
                                              doc_id=doc_id,
                                              doc_bundle=doc_bundle,
                                              optional_args=put_args,
                                              auth_info=auth_info,
                                              commit_msg=commit_msg)
        annotated_commit = anco
    except GitWorkflowError, err:
        _LOG.exception('write operation failed in annotate_and_write')
        raise httpexcept(HTTPBadRequest, err.msg)
    if annotated_commit.get('error', 0) != 0:
        raise httpexcept(HTTPBadRequest, json.dumps(annotated_commit))
    mn = annotated_commit.get('merge_needed')
    if (mn is not None) and (not mn):
        trigger_push(request, umbrella, doc_id, 'EDIT', auth_info)
    return annotated_commit


def commit_new_doc_helper(umbrella, doc_bundle, auth_info, commit_msg):
    """Adaptor for a call to TypeAwareDocStore.add_new_doc that returns the annotated commit.

    `doc_bundle` is a tuple of (processed_doc, annotation, doc_adaptor) created from
        validate_and_convert_doc
    """
    processed_doc = doc_bundle[0]
    return umbrella.add_new_doc(json_repr=processed_doc,
                                auth_info=auth_info,
                                commit_msg=commit_msg)[1]


def commit_existing_doc_helper(umbrella,
                               doc_id,
                               doc_bundle,
                               optional_args,
                               auth_info,
                               commit_msg):
    """Adaptor for a call to TypeAwareDocStore.annotate_and_write that returns the annotated commit.

    `optional_args` (the write_args dict created from a request) is checked for:
       "starting_commit_SHA",
       "resource_type" (only used in error messages)
       "merged_SHA"
    `doc_bundle` is a tuple of (processed_doc, annotation, doc_adaptor) created from
        validate_and_convert_doc
    """
    processed_doc, annotation, doc_adaptor = doc_bundle
    parent_sha = optional_args.get('starting_commit_SHA')
    merged_sha = optional_args.get('merged_SHA')
    return umbrella.annotate_and_write(document=processed_doc,
                                       doc_id=doc_id,
                                       auth_info=auth_info,
                                       adaptor=doc_adaptor,
                                       annotation=annotation,
                                       parent_sha=parent_sha,
                                       commit_msg=commit_msg,
                                       merged_sha=merged_sha)


# TODO: the following helper (and its 2 views) need to be cached, if we are going to
#  continue to support them.
def fetch_all_docs_and_last_commit(docstore):
    """Returns a list of all docs in a `docstore` with extra fields.

    """
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


######################################################################################
# Code for execution in a non-blocking thread
class JobQueue(Queue):
    """Thread-safe Queue that logs the addition of a job to debug"""
    def put(self, item, block=None, timeout=None):
        """Logs `item` at the debug level then calls base-class put"""
        _LOG.debug("%s queued" % str(item))
        Queue.put(self, item, block=block, timeout=timeout)


_jobq = JobQueue()


def worker():
    """Infinite loop of getting jobs off of _jobq and performing them."""
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


######################################################################################
# bookkeeping for the in-memory info about push status
def add_push_failure(push_failure_dict_lock, push_failure_dict, umbrella, msg):
    """Adds a `msg` to the appropriate in-memory store of push failures.

    :param push_failure_dict_lock: mutex lock to acquire
    :param push_failure_dict: dict mapping doc_type -> list of failures
    :param umbrella: TypeAwareDocStore instance to use to get the doc_type from.
    :param msg: string describing failure.
    """
    with push_failure_dict_lock:
        fl = push_failure_dict.setdefault(umbrella.document_type, [])
        fl.append(msg)


def clear_push_failures(push_failure_dict_lock, push_failure_dict, umbrella):
    """Should be called when a push succeeds. Clears in-memory store of error messages.

    :param push_failure_dict_lock: mutex lock to acquire
    :param push_failure_dict: dict mapping doc_type -> list of failures
    :param umbrella: TypeAwareDocStore instance to use to get the doc_type from.
    """
    with push_failure_dict_lock:
        fl = push_failure_dict.setdefault(umbrella.document_type, [])
        del fl[:]


def copy_of_push_failures(push_failure_dict_lock, push_failure_dict, umbrella):
    """Returns a list of failures associated with pushing a particular doc_type.

    :param push_failure_dict_lock: mutex lock to acquire
    :param push_failure_dict: dict mapping doc_type -> list of failures
    :param umbrella: TypeAwareDocStore instance to use to get the doc_type from.
    :return a shallow copy of the list of push failures for a doc_type
    """
    with push_failure_dict_lock:
        return copy.copy(push_failure_dict.setdefault(umbrella.document_type, []))


def find_studies_by_doi(indexer_domain, study_doi):
    """Returns a list of studies with a DOI that match `study_doi` by calling indexer.

    `indexer_domain` is the domain argument to peyotl's OTI wrapper, this identifies the
        host that serves as the endpoint for "studies" calls.
    """
    oti_wrapper = OTI(domain=indexer_domain)
    return oti_wrapper.find_studies_by_doi(study_doi)


class GitPushJob(object):
    """Class that wraps up the info to push a shard to GitHub for use in thread-safe queues.

    Instances of this job are placed on the JobQueue, and run by the `worker` function. So
    the methods of this class need to coordinate with that function.
    """
    def __init__(self, request, umbrella, doc_id, operation, auth_info=None):
        """:param request: request object just used to get config dependent settings.
        :param umbrella: instance of a TypeAwareDocStore that holds the doc to be pushed
        :param doc_id: the ID of the document to push
        :param operation: string such as "EDIT" or "DELETE" for logging purposes
        :param auth_info: info about the user triggering the push operation.
        """
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
        """Writes the operation, doc_id and doc_store info for logging purposes"""
        template = 'GitPushJob for {o} operation of "{i}" to store of "{d}" documents'
        return template.format(o=self.operation, i=self.doc_id, d=self.umbrella.document_type)

    def push_to_github(self):
        """Attempts the push. State is stored in push_success and status_str. updates push failures.

        :raises HTTPInternalServerError or HTTPConflict on failures.
        Note that push_success only refers to the push, not any errors in recording the
            operation in the push failure state dict.
        """
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
            # TODO: this is untested
            self.status_str = 'Push and clearing of push_failures succeeded. Reindex failed.'
            # pylint: disable=E1102
            self.reindex_fn(self.umbrella.document_type, self.doc_id, self.operation)
            self.status_str = 'Succeeded.'
        else:
            self.status_str = 'Push and clearing of push_failures succeeded; reindex not attempted'

    def start(self):
        """Trigger to start push - blocking"""
        self.push_to_github()

    def get_results(self):
        """:return self.status_str"""
        return self.status_str

    def get_response_obj(self):
        """Triggers push and returns an API response dict ("error" and "description" keys)."""
        if self.status_str is None:
            self.start()
        return {"error": 0 if self.push_success else 1,
                "description": self.status_str, }


def trigger_push(request, umbrella, doc_id, operation, auth_info=None):
    """Non blocking push of `doc_id`.

    Creates an GitPushJob and puts it on the JobQueue
    See GitPushJob.__init__ for description of parameters.
    """
    settings = request.registry.settings
    joq_queue = settings['job_queue']
    gpj = GitPushJob(request=request,
                     umbrella=umbrella,
                     doc_id=doc_id,
                     operation=operation,
                     auth_info=auth_info)
    joq_queue.put(gpj)


######################################################################################
# helpers for calling other services
def do_http_post_json(url, data=None):
    """POSTs `data` to `url` using JSON content type.

    :raises HTTPInternalServerError on http failures.
    :return the object encoded by the JSON response.
    """
    try:
        resp = requests.post(url,
                             headers={"Content-Type": "application/json"},
                             data=data,
                             allow_redirects=True)
        return resp.json()
    except Exception as e:
        msg = "Unexpected error calling {}: {}".format(url, e.message)
        raise httpexcept(HTTPInternalServerError, msg)


def otindex_call(study_ids, otindex_base_url, oti_verb):
    """Helper for calling otindex for a list of IDs.

    :param study_ids: list of study IDs
    :param otindex_base_url: the domain of the OTIndex endpoint
    :param oti_verb: word after "studies/" in the URL of the OTIndex API.
    :return: empty string on success. error message on failure.
    """
    nudge_url = "{o}/v3/studies/{v}".format(o=otindex_base_url, v=oti_verb)
    payload = {"studies": study_ids}
    response = do_http_post_json(nudge_url, data=payload)
    if response['failed_studies']:
        msg = "Could not {v} following studies: {s}".format(s=", ".join(response['failed_studies']),
                                                            v=oti_verb)
        _LOG.debug(msg)
        return msg
    return ''


######################################################################################
# more complex helpers for converting http requests to dicts of options
def subresource_request_helper(request):
    """Helper function for get_document separates params into output and input dicts

    This function composes a pair of dicts:
        the first (subresource_req_dict) is the argument to umbrella.is_plausible_transformation
        the second (culled_params) is set of input specification details.

    The goal is to adapt the peculiarities of the URL/http data into a more
    standardized set of dict.

    On output, subresource_req_dict can have:
        * output_is_json: bool default True (may be set to False in
            umbrella.is_plausible_transformation)
        * output_format: mapping to a dict which can contain any of the following. all
            absent -> no transformation
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
        # noinspection PyTypeChecker
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
                    # noinspection PyUnresolvedReferences
                    subresource_id = '.'.join(subresource_id.split('.')[:-1])
                subresource_req_dict['subresource_id'] = subresource_id
            # subtrees need (tree_id, subtree_id) as their "subresource_id"
            if subresource_type == 'subtree':
                subtree_id = params.get('subtree_id')
                if (subtree_id is None) or (subresource_id is None):
                    _edescrip = 'subtree resource requires a study_id and tree_id in the URL ' \
                                'and a subtree_id parameter'
                    raise httpexcept(HTTPBadRequest, err_body(_edescrip))
                subresource_req_dict['subresource_id'] = (subresource_id, subtree_id)
    # if we get {resource_type}/ot_1424.json we want to treat ot_1424 as the ID
    if (len(last_word_dot_split) > 1) and last_word_was_doc_id:
        if last_word == doc_id:
            culled_params['doc_id'] = '.'.join(last_word_dot_split[:-1])
    return subresource_req_dict, culled_params


def extract_write_args(request, study_post=False, require_document=True):
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
        additional_str_key = ('import_method', 'import_from_location',
                              'nexml_fetch_url', 'nexml_pasted_string',
                              'publication_DOI', 'publication_reference', 'treebase_id')
        cc0 = ((params.get('chosen_license', '') == 'apply-new-CC0-waiver')
               and (params.get('cc0_agreement', '') == 'true'))
        culled_params['cc0_agreement'] = cc0
    else:
        additional_str_key = tuple()
    for key in str_key_list:
        culled_params[key] = params.get(key)
    for key in additional_str_key:
        culled_params[key] = params.get(key)

    document_object = _extract_json_obj_from_http_call(request,
                                                       data_kwarg_key=data_kwarg_key,
                                                       exception_if_absent=require_document)
    _LOG.debug('culled_params = {}'.format(culled_params))
    return document_object, culled_params


def _extract_json_obj_from_http_call(request, data_kwarg_key, exception_if_absent=True, **kwargs):
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
        if not exception_if_absent:
            return None
        msg = 'Could not extract JSON argument from {} or body'.format(data_kwarg_key)
        _LOG.exception(msg)
        raise httpexcept(HTTPBadRequest, msg)
    return json_blob


def get_ids_of_synth_collections():
    """Fairly hacky way to get the IDs of all collections queued to be used in synthesis."""
    # URL could be configurable, but I'm not sure we've ever changed this...
    surl = 'https://raw.githubusercontent.com/mtholder/propinquity/master/config.opentree.synth'
    try:
        resp = requests.get(surl)
        conf_fo = StringIO(resp.content)
    except:
        raise httpexcept(HTTPGatewayTimeout, 'Could not fetch synthesis list from {}'.format(surl))
    cfg = SafeConfigParser()
    try:
        if hasattr(cfg, "readfp"):
            # noinspection PyDeprecation
            cfg.readfp(conf_fo)
        else:
            cfg.read_file(conf_fo)
    except:
        raise httpexcept(HTTPInternalServerError, 'Could not parse file from {}'.format(surl))
    try:
        return cfg.get('synthesis', 'collections').split()
    except:
        msg = 'Could not find a collection list in file from {}'.format(surl)
        raise httpexcept(HTTPInternalServerError, msg)


def create_list_of_collections(cds, coll_id_list):
    """Returns a list of tree collection documents

    :param cds: the colletions doc store.
    :param coll_id_list: list of IDs.
    :raises HTTPNotFound: if an ID is not found in `cds`
    """
    coll_list = []
    for coll_id in coll_id_list:
        try:
            coll_list.append(cds.return_doc(coll_id, return_WIP_map=False)[0])
        except:
            msg = 'GET of collection {} failed'.format(coll_id)
            _LOG.exception(msg)
            raise httpexcept(HTTPNotFound, msg)
    return coll_list


def collection_args_helper(request):
    """helper for functions adding/removing a tree from a collection.

    Extracts and returns:
        (POSTed data, study_id, tree_id, and auth_info)
    """
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


def append_tree_to_collection_helper(request, cds, collection_id, include_decision, auth_info,
                                     commit_msg):
    """Adds an `include_decision` to collection `collection_id` in the `cds` doc store.

    returns a dict describing the commit. if "merge_needed" is in that dict and True, then
        the commit did not get merged to the master. Otherwise a push will be triggered
    :raises HTTPInternalServerError or HTTPBadRequest
    """
    try:
        r = cds.append_include_decision(collection_id,
                                        include_decision,
                                        auth_info=auth_info,
                                        commit_msg=commit_msg)
        commit_return = r
    except GitWorkflowError, err:
        raise httpexcept(HTTPInternalServerError, err.msg)
    except:
        raise httpexcept(HTTPBadRequest, traceback.format_exc())
    # check for 'merge needed'?
    mn = commit_return.get('merge_needed')
    if (mn is not None) and (not mn):
        trigger_push(request, cds, collection_id, 'EDIT', auth_info)
    return commit_return


def make_valid_doi(candidate):
    """Try to convert the candidate string to a proper, minimal DOI. Return the DOI,
    or None if conversion is not possible.

       WORKS: http://dx.doi.org/10.999...
       WORKS: 10.999...
       FAILS: 11.999...
       WORKS: doi:10.999...
       WORKS: DOI:10.999...
       FAILS: http://example.com/
       WORKS: http://example.com/10.blah
       FAILS: something-else
    """
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


def harvest_study_ids_from_paths(path_list):
    """Helper for GitHub hooks that provide the paths of modified docs.

    For the phylesystem repo, this looks at docs that look like study IDs (in study subdir and
    ending with ID+".json").
    """
    rs = set()
    for path in path_list:
        path_parts = path.split('/')
        if path_parts[0] == "study":
            # skip any intermediate directories in docstore repo
            study_id = path_parts[len(path_parts) - 2]
            rs.add(study_id)
    return rs


def harvest_ott_ids_from_paths(path_list):
    """Helper for GitHub hooks that provide the paths of modified docs.

    For the amendements repo, this looks at docs that look like amendment IDs (in amendments subdir
    and ending with ID+".json")
    """
    rs = set()
    for path in path_list:
        path_parts = path.split('/')
        # ignore changes to counter file, other directories, etc.
        if path_parts[0] == "":
            # skip intermediate directories in docstore repo
            amendment_file_name = path_parts.pop()
            ott_id = amendment_file_name[:-5]
            rs.add(ott_id)
    return rs


def github_payload_to_amr(payload, path_to_id_fn):
    """Parses the set of commits in a GitHub webhook payload into sets of IDs corresponding to:
    (added_id_set, modified_id_set, removed_id_set).

    `path_to_id_fn` should be a function that is capable of taking a list of paths and returning
        the set of IDs referred to by the element in the list.
    """
    added = set()
    modified = set()
    removed = set()
    try:
        for commit in payload['commits']:
            added |= path_to_id_fn(commit['added'])
            modified |= path_to_id_fn(commit['modified'])
            removed |= path_to_id_fn(commit['removed'])
    except:
        raise httpexcept(HTTPBadRequest, "malformed GitHub payload")
    return added, modified, removed


def format_gh_webhook_response(url, msg):
    """Helper for generating error messages from a GitHub repo at `url`."""
    full_msg = """This URL should be called by a webhook set in the docstore repo:
        <br /><br /><a href="{g}">{g}</a><br /><pre>{m}</pre>"""
    return full_msg.format(g=url, m=msg)

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
