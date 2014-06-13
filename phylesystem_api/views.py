from pyramid.httpexceptions import HTTPNotFound, HTTPBadRequest
from pyramid.view import view_config
from pyramid.url import route_url
from peyotl.nexson_syntax import get_empty_nexson, \
                                 PhyloSchema, \
                                 BY_ID_HONEY_BADGERFISH
from phylesystem_api.util import _err_body, \
                                 _raise_HTTP_from_msg, \
                                 authenticate, \
                                 new_nexson_with_crossref_metadata
import logging
import anyjson
_LOG = logging.getLogger(__name__)
try:
    from open_tree_tasks import call_http_json
    _LOG.debug('call_http_json imported')
except:
    call_http_json = None
    _LOG.debug('call_http_json was not imported from open_tree_tasks')


@view_config(route_name='home', renderer='json')
def index(request):
    return {
        "description": "The Open Tree API",
        "source_url": "https://github.com/OpenTreeOfLife/phylesystem-api/",
        "documentation_url": "https://github.com/OpenTreeOfLife/phylesystem-api/tree/master/docs"
    }

@view_config(route_name='study_list', renderer='json')
def study_list(request):
    return request.registry.settings['phylesystem'].get_study_ids()

@view_config(route_name='phylesystem_config', renderer='json')
def phylesystem_config(request):
    return request.registry.settings['phylesystem'].get_configuration_dict()

@view_config(route_name='unmerged_branches', renderer='json')
def unmerged_branches(request):
    phylesystem = request.registry.settings['phylesystem']
    bl = phylesystem.get_branch_list()
    bl.sort()
    return bl

@view_config(route_name='push_id', renderer='json')
@view_config(route_name='push', renderer='json')
def push_to_github(request):
    return 'ha'

@view_config(route_name='external_url', renderer='json')
def external_url(request):
    phylesystem = request.registry.settings['phylesystem']
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
    phylesystem = request.registry.settings['phylesystem']
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
            _edescrip = 'subtree resource requires a study_id and tree_id in the URL and a subtree_id parameter'
            raise HTTPBadRequest(body=_err_body(_edescrip))
        return_type = 'subtree'
        returning_tree = True
        content_id = (subresource_id, subtree_id)
    elif subresource in ['meta', 'otus', 'otu', 'otumap']:
        if subresource != 'meta':
            content_id = subresource_id
        return_type = subresource
    else:
        _edescrip = 'subresource requested not in list of valid resources: %s' % ' '.join(valid_subresources)
        raise HTTPBadRequest(body=_err_body(_edescrip))
    phylesystem = request.registry.settings['phylesystem']
    out_schema = _validate_output_nexml2json(phylesystem,
                                             params,
                                             return_type,
                                             content_id=content_id)
    parent_sha = params.get('starting_commit_SHA')

    _LOG.debug('parent_sha = {}'.format(parent_sha))
    # return the correct nexson of study_id, using the specified view
    try:
        r = phylesystem.return_study(study_id, commit_sha=parent_sha, return_WIP_map=True)
    except:
        _LOG.exception('GET failed')
        raise HTTPNotFound('Study #{i} GET failure'.format(i=study_id))
    try:
        study_nexson, head_sha, wip_map = r
        if returning_full_study:
            blob_sha = phylesystem.get_blob_sha_for_study_id(study_id, head_sha)
            phylesystem.add_validation_annotation(study_nexson, blob_sha)
            version_history = phylesystem.get_version_history_for_study_id(study_id)
    except:
        _LOG.exception('GET failed')
        e = sys.exc_info()[0]
        _raise_HTTP_from_msg(e)
    if out_schema.format_str == 'nexson' and out_schema.version == phylesystem.repo_nexml2json:
        result_data = study_nexson
    else:
        try:
            serialize = not out_schema.is_json()
            src_schema = PhyloSchema('nexson', version=phylesystem.repo_nexml2json)
            result_data = out_schema.convert(study_nexson,
                                             serialize=serialize,
                                             src_schema=src_schema)
        except:
            msg = "Exception in coercing to the required NexSON version for validation. "
            _LOG.exception(msg)
            raise HTTPBadRequest(body=_err_body(msg))
    if not result_data:
        msg = 'subresource "{r}/{t}" not found in study "{s}"'.format(r=subresource,
                                                                      t=subresource_id,
                                                                      s=study_id)
        raise HTTPNotFound(body=_err_body(msg))
    if returning_full_study and out_schema.is_json():
        result = {'sha': head_sha,
                 'data': result_data,
                 'branch2sha': wip_map}
        if version_history:
            result['versionHistory'] = version_history
        return result
    return result_data

@view_config(route_name='post_study_id', renderer='json', request_method='POST')
@view_config(route_name='post_study', renderer='json', request_method='POST')
def post_study(request):
    "Open Tree API methods relating to creating (and importing) resources"
    params = dict(request.params)
    params.update(dict(request.matchdict))
    auth_info = util.authenticate(**params)
    phylesystem = request.registry.settings['phylesystem']
    # Studies that were created in phylografter, can be added by
    #   POSTing the content with resource_id 
    new_study_id = params.get('study_id')
    if new_study_id is not None:
        bundle = _extract_and_validate_nexson(request,
                                              phylesystem.repo_nexml2json,
                                              params)
        new_study_nexson = bundle[0]
    else:
        # we're creating a new study (possibly with import instructions in the payload)
        import_from_location = params.get('import_from_location', '')
        treebase_id = params.get('treebase_id', '')
        nexml_fetch_url = params.get('nexml_fetch_url', '')
        nexml_pasted_string = params.get('nexml_pasted_string', '')
        publication_doi = params.get('publication_DOI', '')
        publication_ref = params.get('publication_reference', '')
        # is the submitter explicity applying the CC0 waiver to a new study
        # (i.e., this study is not currently in an online repository)?
        if import_from_location == 'IMPORT_FROM_UPLOAD':
            cc0_agreement = (params.get('chosen_license', '') == 'apply-new-CC0-waiver' and 
                             params.get('cc0_agreement', '') == 'true')
        else:
            cc0_agreement = False
        # look for the chosen import method, e.g,
        # 'import-method-PUBLICATION_DOI' or 'import-method-MANUAL_ENTRY'
        import_method = params.get('import_method', '')

        ##dryad_DOI = params.get('dryad_DOI', '')

        app_name = "api"
        # add known values for its metatags
        meta_publication_reference = None

        # Create initial study NexSON using the chosen import method.
        #
        # N.B. We're currently using a streamlined creation path with just
        # two methods (TreeBASE ID and publication DOI). But let's keep the
        # logic for others, just in case we revert based on user feedback.
        importing_from_treebase_id = (import_method == 'import-method-TREEBASE_ID' and treebase_id)
        importing_from_nexml_fetch = (import_method == 'import-method-NEXML' and nexml_fetch_url)
        importing_from_nexml_string = (import_method == 'import-method-NEXML' and nexml_pasted_string)
        importing_from_crossref_API = (import_method == 'import-method-PUBLICATION_DOI' and publication_doi) or \
                                      (import_method == 'import-method-PUBLICATION_REFERENCE' and publication_ref)

        # Are they using an existing license or waiver (CC0, CC-BY, something else?)
        using_existing_license = (params.get('chosen_license', '') == 'study-data-has-existing-license')

        # any of these methods should returna parsed NexSON dict (vs. string)
        if importing_from_treebase_id:
            # make sure the treebase ID is an integer
            treebase_id = "".join(treebase_id.split())  # remove all whitespace
            treebase_id = treebase_id.lstrip('S').lstrip('s')  # allow for possible leading 'S'?
            try:
                treebase_id = int(treebase_id)
            except ValueError, e:
                _edescrip = "TreeBASE ID should be a simple integer, not '%s'! Details:\n%s" % (treebase_id, e.message)
                raise HTTPBadRequest(body=_err_body(_edescrip))
            new_study_nexson = import_nexson_from_treebase(treebase_id,
                                                           nexson_syntax_version=BY_ID_HONEY_BADGERFISH)
        # elif importing_from_nexml_fetch:
        #     if not (nexml_fetch_url.startswith('http://') or nexml_fetch_url.startswith('https://')):
        #         raise HTTP(400, json.dumps({
        #             "error": 1,
        #             "description": 'Expecting: "nexml_fetch_url" to startwith http:// or https://',
        #         }))
        #     new_study_nexson = get_ot_study_info_from_treebase_nexml(src=nexml_fetch_url,
        #                                                     nexson_syntax_version=BY_ID_HONEY_BADGERFISH)
        # elif importing_from_nexml_string:
        #     new_study_nexson = get_ot_study_info_from_treebase_nexml(nexml_content=nexml_pasted_string,
        #                                                    nexson_syntax_version=BY_ID_HONEY_BADGERFISH)
        elif importing_from_crossref_API:
            new_study_nexson = new_nexson_with_crossref_metadata(doi=publication_doi,
                                                                 ref_string=publication_ref,
                                                                 include_cc0=cc0_agreement)
        else:   # assumes 'import-method-MANUAL_ENTRY', or insufficient args above
            new_study_nexson = get_empty_nexson(BY_ID_HONEY_BADGERFISH,
                                                include_cc0=cc0_agreement)

        nexml = new_study_nexson['nexml']

        # If submitter requested the CC0 waiver or other waiver/license, make sure it's here
        if importing_from_treebase_id or cc0_agreement:
            nexml['^xhtml:license'] = {'@href': 'http://creativecommons.org/publicdomain/zero/1.0/'}
        elif using_existing_license:
            existing_license = params.get('alternate_license', '')
            if existing_license == 'CC-0':
                nexml['^xhtml:license'] = {'@href': 'http://creativecommons.org/publicdomain/zero/1.0/'}
                pass
            elif existing_license == 'CC-BY':
                nexml['^xhtml:license'] = {'@href': 'http://creativecommons.org/licenses/by/4.0/'}
                pass
            else:  # assume it's something else
                alt_license_name = params.get('alt_license_name', '')
                alt_license_url = params.get('alt_license_URL', '')
                # OK to add a name here? mainly to capture submitter's intent
                nexml['^xhtml:license'] = {'@name': alt_license_name, '@href': alt_license_url}

        nexml['^ot:curatorName'] = auth_info.get('name', '').decode('utf-8')

    try:
        r = phylesystem.ingest_new_study(new_study_nexson,
                                         phylesystem.repo_nexml2json,
                                         auth_info,
                                         new_study_id)
        new_resource_id, commit_return = r
    except GitWorkflowError, err:
        _raise_HTTP_from_msg(err.msg)
    except:
        _raise_HTTP_from_msg(traceback.format_exc())
    if commit_return['error'] != 0:
        _LOG.debug('ingest_new_study failed with error code')
        raise HTTPBadRequest(body=json.dumps(commit_return))
    _deferred_push_to_gh_call(request, new_resource_id, **params)
    return commit_return

@view_config(route_name='put_study_id', renderer='json', request_method='PUT')
def put_study(request):
    "Open Tree API methods relating to updating existing resources"
    parent_sha = request.params.get('starting_commit_SHA')
    if parent_sha is None:
        _raise_HTTP_from_msg('Expecting a "starting_commit_SHA" argument with the SHA of the parent')
    commit_msg = request.params.get('commit_msg')
    master_file_blob_included = request.params.get('merged_SHA')
    study_id = request.matchdict['study_id']
    _LOG.debug('PUT to study {} for starting_commit_SHA = {} and merged_SHA = {}'.format(study_id,
                                                                                         parent_sha,
                                                                                         str(master_file_blob_included)))
    auth_info = authenticate(**request.params)
    phylesystem = request.registry.settings['phylesystem']
    bundle = _extract_and_validate_nexson(request,
                                          phylesystem.repo_nexml2json,
                                          request.params)
    nexson, annotation, nexson_adaptor = bundle
    gd = phylesystem.create_git_action(resource_id)
    try:
        blob = _finish_write_verb(phylesystem,
                                   gd,
                                   nexson=nexson,
                                   resource_id=study_id,
                                   auth_info=auth_info,
                                   adaptor=nexson_adaptor,
                                   annotation=annotation,
                                   parent_sha=parent_sha, 
                                   commit_msg=commit_msg,
                                   master_file_blob_included=master_file_blob_included)
    except GitWorkflowError, err:
        _LOG.exception('PUT failed in _finish_write_verb')
        _raise_HTTP_from_msg(err.msg)
    mn = blob.get('merge_needed')
    if (mn is not None) and (not mn):
        _deferred_push_to_gh_call(request, study_id, **request.params)
    return blob

def _validate_output_nexml2json(phylesystem, params, resource, content_id=None):
    msg = None
    if 'output_nexml2json' not in params:
        params['output_nexml2json'] = '0.0.0'
    try:
        schema = PhyloSchema(schema=params.get('format'),
                             content=resource,
                             content_id=content_id,
                             repo_nexml2json=phylesystem.repo_nexml2json,
                             **params)
        if not schema.can_convert_from(resource):
            msg = 'Cannot convert from {s} to {d}'.format(s=phylesystem.repo_nexml2json,
                                                          d=schema.description)
    except ValueError, x:
        msg = str(x)
        _LOG.exception('GET failing: {m}'.format(m=msg))
        
    if msg:
        _LOG.debug('output sniffing err msg = ' + msg)
        raise HTTPBadRequest(body=_err_body(msg))
    return schema


def _extract_and_validate_nexson(request, repo_nexml2json, kwargs):
    try:
        nexson = _extract_nexson_from_http_call(request, **kwargs)
        bundle = validate_and_convert_nexson(nexson,
                                             repo_nexml2json,
                                             allow_invalid=False)
        nexson, annotation, validation_log, nexson_adaptor = bundle
    except GitWorkflowError, err:
        _LOG = api_utils.get_logger(request, 'ot_api.default.v1')
        _LOG.exception('PUT failed in validation')
        _raise_HTTP_from_msg(err.msg)
    return nexson, annotation, nexson_adaptor

def _deferred_push_to_gh_call(request, resource_id, **kwargs):
    _LOG.debug('in _deferred_push_to_gh_call')
    if call_http_json is not None:
        url = utils.compose_push_to_github_url(request, resource_id)
        auth_token = copy.copy(kwargs.get('auth_token'))
        data = {}
        if auth_token is not None:
            data['auth_token'] = auth_token
        _LOG.debug('_deferred_push_to_gh_call({u}, {d})'.format(u=url, d=str(data)))
        call_http_json.delay(url=url, verb='PUT', data=data)

def compose_push_to_github_url(request, study_id):
    if study_id is None:
        return route_url('push', request)
    return route_url('push_id', request, study_id=study_id)


def _extract_nexson_from_http_call(request, **kwargs):
    """Returns the nexson blob from `kwargs` or the request.body"""
    try:
        # check for kwarg 'nexson', or load the full request body
        if 'nexson' in kwargs:
            nexson = kwargs.get('nexson', {})
        else:
            nexson = request.json_body

        if not isinstance(nexson, dict):
            nexson = json.loads(nexson)
        if 'nexson' in nexson:
            nexson = nexson['nexson']
    except:
        _LOG.exception('Exception getting nexson content in __extract_nexson_from_http_call')
        _raise_HTTP_from_msg('NexSON must be valid JSON')
    return nexson


def _finish_write_verb(phylesystem,
                       git_data, 
                       nexson,
                       resource_id,
                       auth_info,
                       adaptor,
                       annotation,
                       parent_sha,
                       commit_msg='',
                       master_file_blob_included=None):
    '''Called by PUT and POST handlers to avoid code repetition.'''
    # global TIMING
    #TODO, need to make this spawn a thread to do the second commit rather than block
    a = phylesystem.annotate_and_write(git_data, 
                                       nexson,
                                       resource_id,
                                       auth_info,
                                       adaptor,
                                       annotation,
                                       parent_sha,
                                       commit_msg,
                                       master_file_blob_included)
    annotated_commit = a
    # TIMING = api_utils.log_time_diff(_LOG, 'annotated commit', TIMING)
    if annotated_commit['error'] != 0:
        _LOG.debug('annotated_commit failed')
        _raise_HTTP_from_msg(json.dumps(annotated_commit))
    return annotated_commit