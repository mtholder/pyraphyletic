import copy
import json
import traceback
import bleach
import markdown
from peyotl import get_logger, create_doc_store_wrapper
from pyramid.httpexceptions import (HTTPNotFound, HTTPBadRequest, HTTPForbidden)
from pyramid.response import Response
from pyramid.view import view_config
from peyotl import NexsonDocSchema, GitWorkflowError
# noinspection PyPackageRequirements
from github import Github, BadCredentialsException


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
    settings['taxon_amendments'] = wrapper.taxon_amendments
    settings['tree_collections'] = wrapper.tree_collections


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
        raise HTTPForbidden(body="You must provide an auth_token to authenticate to the OpenTree API")
    gh = Github(auth_token)
    gh_user = gh.get_user()
    auth_info = {}
    try:
        auth_info['login'] = gh_user.login
    except BadCredentialsException:
        raise HTTPForbidden(body="You have provided an invalid or expired authentication token")
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
        raise HTTPBadRequest(msg)
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
        raise HTTPNotFound(title='API version "{}" is not supported'.format(vstr))
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
        raise HTTPNotFound(body='Resource type "{}" is not supported'.format(rtstr))
    return request.registry.settings[key_name]


def doc_id_from_request(request):
    """This function is used to match requests that contain a resource_type
        in the matchdict. If that string in not in the _RESOURCE_TYPE_2_SETTINGS_UMBRELLA_KEY
        dict, then a 404 is raised. Otherwise the appropriate "umbrella" is located
        in the global settings, and the view function is called with the
        request and the umbrella object as the first 2 arguments"""
    doc_id = request.matchdict.get('doc_id')
    if doc_id is None:
        raise HTTPNotFound(body='Document ID required')
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
    raise HTTPBadRequest(body="no POSTed data", explanation='No data obtained from POST')


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
        raise HTTPBadRequest(body='"src" parameter not found in POST')

    def add_blank_target(attrs, new=False):
        attrs['target'] = '_blank'
        return attrs

    h = markdown.markdown(src)
    h = bleach.clean(h, tags=['p', 'a', 'hr', 'i', 'em', 'b', 'div', 'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4'])
    h = bleach.linkify(h, callbacks=[add_blank_target])
    return Response(h)


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
                    raise HTTPBadRequest(body=err_body(_edescrip))
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
        raise HTTPBadRequest(body='Impossible request: {}'.format(reason_or_converter))
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
        raise HTTPBadRequest(body=err_body(traceback.format_exc()))
    if transformer is None:
        result_data = document_blob
    else:
        try:
            result_data = transformer(umbrella, doc_id, document_blob, head_sha)
        except KeyError, x:
            raise HTTPNotFound(body='subresource not found: {}'.format(x))
        except ValueError, y:
            raise HTTPBadRequest(body='subresource not found: {}'.format(y.message))
        except:
            msg = "Exception in coercing to the document to the requested type. "
            _LOG.exception(msg)
            raise HTTPBadRequest(body=err_body(msg))
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


@view_config(route_name='post_study', renderer='json', request_method='POST')
def post_study_document(request):
    request.matchdict['resource_type'] = 'study'
    return post_document(request)


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


def extract_write_args(request):
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
    for key in ('starting_commit_SHA', 'commit_msg', 'merged_SHA', 'doc_id', 'resource_type'):
        val = params.get(key)
        culled_params[key] = val
    document_object = _extract_json_obj_from_http_call(request, data_kwarg_key=data_kwarg_key)
    culled_params['document'] = document_object
    _LOG.debug('culled_params = {}'.format(culled_params))
    return culled_params


def post_document(reqest):
    """Open Tree API methods relating to creating a new resource"""
    post_args = extract_write_args(request)
    if post_args.get('doc_id') is None:
        raise HTTPBadRequest(body='POST operation does not expect a URL that ends with a document ID')
    umbrella = umbrella_from_request(request)
    return finish_write_operation(umbrella, post_args)


def put_document(request):
    """Open Tree API methods relating to updating existing resources"""
    put_args = extract_write_args(request)
    if put_args.get('starting_commit_SHA') is None:
        raise HTTPBadRequest(body='PUT operation expects a "starting_commit_SHA" argument with the SHA of the parent')
    if put_args.get('doc_id') is None:
        raise HTTPBadRequest(body='PUT operation expects a URL that ends with a document ID')
    umbrella = umbrella_from_request(request)
    return finish_write_operation(umbrella, put_args)


def finish_write_operation(umbrella, put_args):
    auth_info = put_args['auth_info']
    parent_sha = put_args.get('starting_commit_SHA')
    doc_id = put_args.get('doc_id')
    resource_type = put_args['resource_type']
    commit_msg = put_args.get('commit_msg')
    merged_sha = put_args.get('merged_SHA')
    lmsg = 'PUT of {} with doc id = {} for starting_commit_SHA = {} and merged_SHA = {}'
    _LOG.debug(lmsg.format(resource_type, doc_id, parent_sha, merged_sha))
    document_object = put_args.get('document')
    bundle = umbrella.validate_doc(document_object, put_args)
    processed_doc, annotation, doc_adaptor = bundle
    try:
        annotated_commit = umbrella.annotate_and_write(document=processed_doc,
                                                       doc_id=doc_id,
                                                       auth_info=auth_info,
                                                       adaptor=doc_adaptor,
                                                       annotation=annotation,
                                                       parent_sha=parent_sha,
                                                       commit_msg=commit_msg,
                                                       merged_SHA=merged_sha)
    except GitWorkflowError, err:
        _LOG.exception('write operation failed in annotate_and_write')
        raise HTTPBadRequest(body=err.msg)
    if annotated_commit.get('error', 0) != 0:
        raise HTTPBadRequest(body=json.dumps(annotated_commit))

    mn = annotated_commit.get('merge_needed')
    if (mn is not None) and (not mn):
        trigger_push(umbrella, doc_id, 'EDIT', auth_info)
    return annotated_commit


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


