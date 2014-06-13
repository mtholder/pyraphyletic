from phylesystem_api.util import get_phylesystem
from pyramid.httpexceptions import HTTPNotFound, HTTPBadRequest
from pyramid.view import view_config
import logging
import anyjson
_LOG = logging.getLogger(__name__)

@view_config(route_name='home', renderer='json')
def index(request):
    return {
        "description": "The Open Tree API",
        "source_url": "https://github.com/OpenTreeOfLife/phylesystem-api/",
        "documentation_url": "https://github.com/OpenTreeOfLife/phylesystem-api/tree/master/docs"
    }

@view_config(route_name='study_list', renderer='json')
def study_list(request):
    phylesystem = get_phylesystem(request.registry.settings)
    return phylesystem.get_study_ids()

@view_config(route_name='phylesystem_config', renderer='json')
def phylesystem_config(request):
    phylesystem = get_phylesystem(request.registry.settings)
    return phylesystem.get_configuration_dict()

@view_config(route_name='unmerged_branches', renderer='json')
def unmerged_branches(request):
    phylesystem = get_phylesystem(request.registry.settings)
    bl = phylesystem.get_branch_list()
    bl.sort()
    return bl

@view_config(route_name='external_url', renderer='json')
def external_url(request):
    phylesystem = get_phylesystem(request.registry.settings)
    study_id = request.matchdict['study_id']
    try:
        u = phylesystem.get_public_url(study_id)
        return {'url': u, 'study_id': study_id}
    except:
        msg = 'study {} not found'.format(study_id)
        _LOG.exception(msg)
        raise HTTPNotFound(body=anyjson.dumps({'error': 1, 'description': msg}))
 
@view_config(route_name='repo_nexson_format', renderer='json')
def repo_nexson_format(request):
    phylesystem = get_phylesystem(request.registry.settings)
    return {'description': "The nexml2json property reports the version of the NexSON that is used in the document store. Using other forms of NexSON with the API is allowed, but may be slower.",
            'nexml2json': phylesystem.repo_nexml2json}

@view_config(route_name='get_sub', renderer='json', request_method='GET')
@view_config(route_name='get_sub_id', renderer='json', request_method='GET')
@view_config(route_name='get_study', renderer='json', request_method='GET')
def get_study(request):
    "OpenTree API methods relating to reading"
    valid_resources = ('study', )
    params = dict(request.params)
    params.update(dict(request.matchdict))
    study_id = request.matchdict['study_id']
    valid_subresources = ('tree', 'meta', 'otus', 'otu', 'otumap')
    returning_full_study = False
    returning_tree = False
    content_id = None
    version_history = None
    # infer file type from extension
    type_ext = None
    last_word_dot_split = request.path.split('/')[-1].split('.')
    if len(last_word_dot_split) > 1:
        type_ext = '.' + last_word_dot_split[-1]

    params['type_ext'] = type_ext
    subresource = params.get('subresource')
    subresource_id = params.get('subresource_id')
    if subresource_id and ('.' in subresource_id):
        subresource_id = subresource_id.split('.')[0] # could crop ID...
    if subresource is None:
        returning_full_study = True
        if '.' in study_id:
            study_id = study_id.split('.')[0]
        _LOG.debug('GET v1/study/{}'.format(study_id))
        return_type = 'study'
    elif subresource == 'tree':
        return_type = 'tree'
        returning_tree = True
        content_id = subresource_id
    elif subresource == 'subtree':
        subtree_id = params.get('subtree_id')
        if subtree_id is None:
            err = {"error": 1,
                   "description": 'subtree resource requires a study_id and tree_id in the URL and a subtree_id parameter'}
            raise HTTPBadRequest(body=anyjson.dumps(err))
        return_type = 'subtree'
        returning_tree = True
        content_id = (subresource_id, subtree_id)
    elif subresource in ['meta', 'otus', 'otu', 'otumap']:
        if subresource != 'meta':
            content_id = subresource_id
        return_type = subresource
    else:
        raise HTTPBadRequest(body=json.dumps({"error": 1,
                                    "description": 'subresource requested not in list of valid resources: %s' % ' '.join(valid_subresources)}))
    """out_schema = __validate_output_nexml2json(kwargs,
                                              return_type,
                                              type_ext,
                                              content_id=content_id)
    # support JSONP request from another domain
    if jsoncallback or callback:
        response.view = 'generic.jsonp'
    parent_sha = kwargs.get('starting_commit_SHA')
    _LOG.debug('parent_sha = {}'.format(parent_sha))
    # return the correct nexson of study_id, using the specified view
    phylesystem = api_utils.get_phylesystem(request)
    try:
        r = phylesystem.return_study(resource_id, commit_sha=parent_sha, return_WIP_map=True)
    except:
        _LOG.exception('GET failed')
        raise HTTP(404, json.dumps({"error": 1, "description": 'Study #%s GET failure' % resource_id}))
    try:
        study_nexson, head_sha, wip_map = r
        if returning_full_study:
            blob_sha = phylesystem.get_blob_sha_for_study_id(resource_id, head_sha)
            phylesystem.add_validation_annotation(study_nexson, blob_sha)
            version_history = phylesystem.get_version_history_for_study_id(resource_id)
    except:
        _LOG.exception('GET failed')
        e = sys.exc_info()[0]
        _raise_HTTP_from_msg(e)
    if out_schema.format_str == 'nexson' and out_schema.version == repo_nexml2json:
        result_data = study_nexson
    else:
        try:
            serialize = not out_schema.is_json()
            src_schema = PhyloSchema('nexson', version=repo_nexml2json)
            result_data = out_schema.convert(study_nexson,
                                             serialize=serialize,
                                             src_schema=src_schema)
        except:
            msg = "Exception in coercing to the required NexSON version for validation. "
            _LOG.exception(msg)
            raise HTTP(400, msg)
    if not result_data:
        raise HTTP(404, 'subresource "{r}/{t}" not found in study "{s}"'.format(r=subresource,
                                                                                t=subresource_id,
                                                                                s=resource_id))
    if returning_full_study and out_schema.is_json():
        result = {'sha': head_sha,
                 'data': result_data,
                 'branch2sha': wip_map}
        if version_history:
            result['versionHistory'] = version_history
        return result
    else:
        return result_data
"""