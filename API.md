# Open Tree Phylesystem API Documentation

This file documents the details of the phylesystem API of
the Open Tree of Life project.
The project's [APIs Page](https://github.com/OpenTreeOfLife/opentree/wiki/Open-Tree-of-Life-APIs)
provides a summary of the other APIs and the "public" portions
of this API.

The "phylesystem API" refers to the APIs that govern the data
curated by users of Open Tree of Life.
All of the data served these APIs is all stored in git repositories
    with peyotl's TypeAwareDocStore instances that wrap the 
    git repos and provide basic CRUD functionality.
Inside the implementation, every edit operation is performed on a "work in progress"
 branch to assure that the user's edits are saved.
Each edit then triggers an attempt to update the master branch of the repo.
If the same document has not been edited on the master branch, then the
 "work in progress" branch will be merged onto the master and the edits will be
 pushed to GitHub.
If the same document has been edited, the response will indicate that a merge
 is needed; the edits will still be stored on the server of the API, but will
 not be visible on GitHub until the changes have been merged.
Note that this is quite conservative in that even compatible chnages will fail
 to merge; however, given the low levels of usage thus far, this design
 decision has not caused major problems.


### Versioning in URLs:  http://{domain}/phylesystem/`v{#}`/...
All API calls are specific to the API version, which is a part
of the URL. 
This allows for new versions of the Phylesystem API to come out
which are not backward-compatible, while allowing old clients
to continue working with older API versions.
Versions `v1`, `v2`, and `v3` have been deployed. For the
phylesystem API only backward compatible changes were involved in these
separate versions.
Thus, you will get the same behavior from the server regardless of which
of those versions you use.

This document uses `https://api.opentreeoflife.org/phylesystem/v3` as
the prefix for the examples.
**NOTE**: substituting `https://devapi` for `https://api` will let you
acess the more "bleeding edge" deployments of the code. The exact
behavior on devapi depends on what branch of code has been deployed
there (see [the germinator/deploy/README](https://github.com/OpenTreeOfLife/germinator/tree/master/deploy) 
for details on deployment).

Currently v3 is deployed, and for the phylesystem API many methods are unchanged from v1-v4.

**NOTE**: substituting `https://devapi` for `https://api` will let you acess the more "bleeding edge" 
deployments of the code.

**NOTE**: Interface details are still under development and host names and paths are subject to change.

### Resource stores in URLs:  http://{domain}/phylesystem/v{#}/`{resource}`/...
Currently API is used to manage 3 types of documents: phylogenetic studies, taxonomic amendments,
 and tree collections.
The methods described can typically be appended to the end, after
    the v#/`{resource}/` part of the URL.

For the purposes of backward compatibility, as set of aliases are now supported for the full name
of a resource


| Resource | Preferred Name | Aliases |
|----------|----------------|---------|
| phylogenetic study | `study` | `phylesystem`, `studies` |
| tree collections | `tree_collection` | `tree_collections`, `collections`, `collection` |
| taxonomic amendments | `taxon_amendment` | `taxon_amendments`, `amendments`, `amendment` |

### `auth_token` argument of write-methods
To associate edits with a user, the methods that result in changes to the corpus
    of data requires an authentication token that is supplied as the 
    value of an `auth_token` parameter.


To get a Github OAuth token, you can use ```curl```:

    curl -u USERNAME -X POST https://api.github.com/authorizations \
        --data '{"scopes":["public_repo"],"note":"description"}'

where USERNAME is your Github login/username. The above will
return JSON containing a "token" key, which is your new OAuth
token. To run the write-tests, you can then put the auth token
into an environment variable:

    export GITHUB_OAUTH_TOKEN=codecafe

In the Open Tree curation webapp, we obtain this when a user logs into the
site via Github. Github returns a persistent token that streamlines
authentication in the future. (Basically, the user shouldn't need to login
again unless they revoke access to the curation app on Github.)

Here are other tips on managing auth tokens programmatically:

http://developer.github.com/v3/oauth/#get-or-create-an-authorization-for-a-specific-app


Also note that if you run the server in an environment with
the variable `LOCAL_TESTING_MODE=1`, the auth_token will not be
validated and dummy user names will be used in commits. This is useful
for testing via TravisCI, for instance.

## Open Tree Phylesystem API Methods

## Methods

#### index: `v{#}/index`

	curl https://api.opentreeoflife.org/phylesystem/v3/index

will return a JSON object with `documentation_url`, `description`, and
`source_url` keys describing the service. Example response:

    {
    "description": "The Open Tree API",
    "documentation_url": "https://github.com/OpenTreeOfLife/phylesystem-api/tree/master/docs",
    "source_url": "https://github.com/mtholder/pyraphyletic"
    }

#### list: `v{#}/{resource}/list`

    curl https://api.opentreeoflife.org/phylesystem/v1/study/list

Returns a JSON array of all of the study IDs.  Example output:

    [
    "xy_13",
    "xy_10",
    "zz_11",
    "zz_112"
    ]

Deprecated URL: `http://{domain}/phylesystem/v1/study_list`


#### config: `v{#}/{resource}/config`

    curl https://api.opentreeoflife.org/phylesystem/v3/study/config

Returns a JSON object with information about how the phylesystem doc store is 
configured.

Also returns a list of all of the doc IDs and paths in the list of "documents"
 in each shard.
As a deprecated feature, the description of the documents, includes information 
on "keys" which lists the set of ID aliases map to the same study.
We no longer support aliases for the same study, so the list of "keys" is now
 a list of just one ID.
The returned struct is identical to what you get if you were to call
phylesystem.get_configuration_dict() on a local instance (using peyotl).

The "initialization" key that is returned by the call should be deprecated or
  only used by developers who want to mimic the server's form of initialization
  to set up a similar structure. It contains a python fragment of initializing the
  document store.

    {
    "initialization": "shard_mirror_pair_list = [['/path/mini_phyl', '/path/mirror/mini_phyl']]",
    "number_of_shards": 1,
    "shards": [{"document_schema": "NexsonDocSchema(schema_version=1.2.1)",
                "documents": [{"keys": ["xy_10"],
                               "relpath": "xy_10/xy_10/xy_10.json"
                              }, {
                               "keys": ["xy_13"],
                               "relpath": "xy_13/xy_13/xy_13.json"
                              }],
                "name": "mini_phyl",
                "number of documents": 2,
                "path": "/path/mini_phyl"
               }]
    }


Deprecated URL: `http://{domain}/phylesystem/v1/phylesystem_config`


#### external_url: `v{#}/{resource}/external_url/{doc_id}`

    curl https://api.opentreeoflife.org/v3/study/external_url/pg_09

Returns a JSON object with the canonical study ID and a url for the version of the 
study in the repo on the master branch:

    {
        "url": "https://raw.githubusercontent.com/OpenTreeOfLife/phylesystem-0/master/study/pg_09/pg_09/pg_09.json", 
        "doc_id": "pg_09"
    }


Deprecated URL: `https://api.opentreeoflife.org/phylesystem/external_url/pg_09` which
    will return a key of "study_id" rather than "doc_id".


### Fetch a resource `v{#}/{resource}/{doc_id}`

To get the entire NexSON of study `pg_09` :

    curl https://api.opentreeoflife.org/phylesystem/v2/study/pg_09
    
You can find the document ID of a study of interest by opening it in curation
 and looking at the url.

Example repsonse:

    {
    "branch2sha": {"master": "e24ff48c78bfdfa870c81e385b5dec26d4e63a31"},
    "commentHTML": "",
    "data": {"nexml": ...},
    "sha": "e24ff48c78bfdfa870c81e385b5dec26d4e63a31",
    "shardName": "mini_phyl",
    "url": "http://127.0.0.1:6543/v4/study/xy_10",
    "versionHistory": [...],
    "version_history": [{
        "author_email": "mtholder@gmail.com",
        "author_name": "Mark T. Holder",
        "date": "Thu, 11 Dec 2014 09:28:15 +0100",
        "date_ISO_8601": "2014-12-11 09:28:15 +0100",
        "id": "2d59ab892ddb3d09d4b18c91470b8c1c4cca86dc",
        "message_subject": "making the structure of this repo more like the otol phylesystem repo. forgot about the middle layer",
        "relative_date": "2 years ago"
        }, ...]
    }

The keys of the response:
  * `data` will hold the resource requested.
  * `sha` holds the SHA that identifies the version of the data that was returned. 
  It can also be used as the `starting_commit_SHA` in future GET calls to return the same data.
  * `url` the URL of the resource
  * `branch2sha` will hold a map of branch names 2 SHA mappings for all of the
    unmerged branches that relate to this resource. Typically, it will just hold
    `master` and the `sha` of the master branch, but if there are unmerged branches,
    they will be recorded here.
   * `version_history` is a list of information about commits that affected this resource.
     This information is also returned as a `versionHistory` key for backward compatibility.
     This information may be deprecated soon, or moved to "only when requested" basis.
   * `commentHTML` if the document has a `^ot:comment` markdown property, then this 
    will be translated to HTML and returned here. This field may be deprecated soon.
   * `shardName` refers to an implemenation detail (the git home of the document). 
   This field may be deprecated in v4.

#### study-specific GET details
##### Arguments of study GET
*   The `output_nexml2json` arg specifies the version of the NeXML -> NexSON 
mapping to be used. See [the NexSON wiki](https://github.com/OpenTreeOfLife/api.opentreeoflife.org/wiki/HoneyBadgerFish)
for details. Currently the only supported values are:
  *  0.0.0  badgerfish convention
  *  1.0.0  the first version of the "honey badgerfish" convention
  *  1.2.1  the "by ID" version of the "honey badgerfish" convention
The default for this parameter is 0.0.0, but this is subject to change.
Consider the call without the output_nexml2json argument to be brittle!
*   `starting_commit_SHA` This is optional 
which will return the version of the study from a specific commit sha.
If no `starting_commit_SHA` is given, GET will return study from master.

##### Output conversion of study GET
If the URL ends with a file extension, then the file type will be inferred for file conversion:
  * .nex -> NEXUS
  * .tre -> Newick
  * .nexml -> NeXML
  * .nexson, .json, or no extension -> NexSON

For NEXUS and Newick formats, by default tip labels will be those from the originally uploaded study.
Alternate labels can be accessed using `tip_label` argument. Values must be one of `ot:originallabel`, `ot:ottid`, or `ot:otttaxonname`.

e.g. 

    curl https://api.opentreeoflife.org/v2/study/pg_1144.nex/?tip_label=ot:ottid
    curl https://api.opentreeoflife.org/v2/study/pg_1144.nex/?tip_label=ot:otttaxonname



##### fine-grained access via GET
NexSON supports fine-grained access to parts of the study (such as the metadata).
NeXML can only be returned for the study. Newick and NEXUS formats can only return
the full study, trees or subtrees.

You can request just parts of the study using a syntax of alternating resource IDs and names:

  * `*/v1/study/pg_10/meta` returns a shell of information about the study but has null entries
    in place of the trees and otus. This is useful because the response is typically much
    smaller than the full study
  * `*/v1/study/pg_10/tree` returns an object with property names corresponding to the 
    IDs of the trees in the study and values being the tree objects.
  * `*/v1/study/pg_10/tree/ABC` is similar to the tree resource mentioned above, but only 
    the tree with ID of "ABC" will be included. A 404 will result if no such tree is found in the study.
    If a `bracket_info=true` argument is added to the call, then the ingroup will be the 
    newick segment between `[pre-ingroup-marker]` and `[post-ingroup-marker]` comments in the 
    newick
  * `*/v1/study/pg_10/tree/ABC?starting_commit_SHA=a2c48df995` is similar to the tree resource mentioned above, 
    except that rather than retrieving the most recent version of the tree "ABC", get the version indexed 
    by git commit SHA "a2c48df995".
  * `*/v1/study/pg_10/subtree/ABC{TREE_FORMAT}?subtree_id=XYZ` is similar to the tree resource
    mentioned above, but only a subtree of the tree with ID of "ABC" will be included. The subtree
    will be the part of the tree that is rooted at the node with ID "XYZ". A 404 will result if no such 
    subtree is found in the study. Requesting a subtree only works when the requested tree format is specified
    as newick (`.tre`) or NEXUS (`.nex`).
  * `*/v1/study/pg_10/subtree/ABC{TREE_FORMAT}?subtree_id=ingroup` ingroup is a wildcard that can be used
    to designate the ingroup node of any tree (may give a 404 for a tree, if the ingroup node
    has not been specified by a curator). Requesting a subtree only works when the requested tree format is
    specified as newick (`.tre`) or NEXUS (`.nex`).
  * `*/v1/study/pg_10/otus` the `study["nexml"]["otusById"]` object 
  * `*/v1/study/pg_10/otus/ABC` is similar to otus, but only the otus group with ID "ABC" 
    will be included.
  * `*/v1/study/pg_10/otu` returns the union of the `study["nexml"]["otusById"][*]["otuById"]` objects 
  * `*/v1/study/pg_10/otu/ABC` is similar to otu, but only the otu with ID "ABC"  will be included.
  * `*/v1/study/pg_10/otumap` will return an object that maps the original label for each OTU to 
    either an object or list of objects (if there were two tips that originally had the same label). The
    objects in the values field will have properties from the mapping: either "^ot:ottId" and/or 
    "^ot:ottTaxonName" fields, or they will be empty (if the OTU has not been mapped to OTT)
  * `*/v1/study/pg_10/file` returns a list of object describing the supplementary files associated with a study, including (in the "id" property) the fileID (see the next bullet point)
  * `*/v1/study/pg_10/file/xyz` returns the contents of the file with fileID `xyz` if that file is associated with study `pg_10`. Typically, you would call the `v1/study/STUDY_ID/file` method first, then choose the file you want and fetch it with this call.

By default all of the fine-grained access methods return NexSON 1.2.1 
Currently they do not support back translation to older versions of NexSON.
The tree related fine-grained access methods (`*/tree/*` and `*/subtree/*`) will also support NEXUS
or newick via calls like: `*/v1/study/pg_10/tree/ABC.nex`

When returning slices of data in NexSON using the fine-grained access URLs, the content returned will
simply be the requested data. The "sha", "branch2sha", and "versionHistory" properties will not be
included. Nor will the requested data be packaged in a "data" field.

#### PUT arguments

**Required arguments**

*   `auth_token` is required, and is your [GitHub authorization token](https://github.com/OpenTreeOfLife/phylesystem-api/tree/master/docs#getting-a-github-oauth-token) 
*   `starting_commit_SHA` is required, and should be the commit SHA of the parent of the edited study.

**Optional arguments**

*  `commit_msg` is optional, but it is good practice to include it
*   `merged_SHA` is optional. If the master branch's version of this study has advanced
    a PUT will not be merged to master. The curation app will need to call 
    the merge URL (see below). That controller will return a `merged_SHA` value. 
    Calling PUT with this `merged_SHA` key-value pair as an argument, is a signal 
    that the curator has examined the changes that have been made to the master branch 
    and that he/she confirms that the edits are not incompatible. The presence of the `merged_SHA`
    argument will allow the branch to merge to master despite the fact that the master has advanced
    since `starting_commit_SHA`. Note that, if the master has advanced again since the 
    client calls the merge controller, the client will need to merge


Either form of this command will create a commit with the updated JSON on a branch of the form

    USERNAME_study_ID_i
    
where USERNAME is the authenticated users Github login and ID
is the study ID number, and i is an iterator for if the user has more than one branch open for that study.
If branch can be merged to master, it will be and the branch will be deleted.

#### PUT response

On success, it will return a JSON response similar to this:

    {
        "error": 0,
        "resource_id": "pg_12",
        "branch_name": "master",
        "description": "Updated study 12",
        "sha":  "e13343535837229ced29d44bdafad2465e1d13d8",
        "merge_needed": false,
    }


*   `error` is set to 0 on success. On failure, `error` will be set to 1.
*   `description` a textual description of what occurred. This will hold the details of the error (if `error` is 1)
*   `resource id` is the id of the study that was edited
*   `branch_name` is the WIP branch that was created. This is not useful (because the `sha`
is all that really matters), and may be deprecated
*   `sha` is the handle for the commit that was created by the PUT (if `error` was 0). This must be used as `starting_commit_SHA` in the next PUT (assuming that the curator wants a linear edit history)
*   `merge_needed` descibes whether the merge controller has to be called before the commit will
be included in the master branch. If false, then the WIP will have been deleted (so that the `branch_name` returned is stale)

If the study has moved forward on the master branch since `starting_commit_SHA`, the
content of this PUT will be successfully stored on a WIP, but the merge into master
will not happen automatically.
This merge will not happen even if there is no conflict. 
The client needs to use the MERGE 
controller to merge master into that branch, then PUT that branch including the 'merged_sha'
returned by the merge. 
Even if a `merged_sha` is included in the PUT,
`merge_needed` may still be `true`.
This happens if the master has moved forward since the merge was vetted.
Then a second merge and PUT with the new `merged_sha` is required.

Any PUT request attempting to update a study with invalid JSON
will be denied and an HTTP error code 400 will be returned.

[Here](https://github.com/OpenTreeOfLife/phylesystem-1/commit/c3312d2cbb7fc608a62c0f7de177305fdd8a2d1a) is an example commit created by the OpenTree API.



### Creating a new study

To create a new study from a file in the current directory called ```study.json```:

    curl -X POST "https://api.opentreeoflife.org/phylesystem/v1/study/?auth_token=$GITHUB_OAUTH_TOKEN" --data-urlencode nexson@study.json

This will generate the output

    {
        "error": "0",
        "resource_id": "ot_12",
        "branch_name": "master",
        "description": "Updated study 12",
        "sha":  "e13343535837229ced29d44bdafad2465e1d13d8",
        "merge_needed": false
    }

See the PUT response for an explanation of the output.
For a new study merge_needed should always be `false`

POST fall into 2 general categories:
 * `import_from_location="import-method-POST"` to use the body of the POST
    to create a new study
 * `import_from_location="import-method-TREEBASE_ID"` should be used with 
    `treebase_id` argument
 * `import_from_location="import-method-PUBLICATION_DOI"` should be used with 
    `publication_DOI` argument
 * `import_from_location="import-method-PUBLICATION_REFERENCE"` should be used with
    `publication_reference` argument
 * Any other value of `import_from_location` parameter will result in an empty
    study being created If `cc0_agreement` is checked if 
        if cc0_agreement is the 'true', then CC0 deposition will be noted
        in the metadata.

## Miscellaneous methods
#### Check push failure state: `v{#}/{resource}/push_failure`

     curl https://api.opentreeoflife.org/phylesystem/v3/study/push_failure

response:

    {
        "doc_type": "study",
        "errors": [],
        "pushes_succeeding": true
    }

#### render_markdown: `v{#}/render_markdown`

     curl -H "Content-Type: application/json" -X POST https://api.opentreeoflife.org/phylesystem/render_markdown -d '{"src":"hi `there`"}

response:

    <p>hi &lt;code&gt;there&lt;/code&gt;</p>
    
#### trees_in_synth: `v{#}/trees_in_synth`
Creates a collection of all of the trees queued to be included in synthesis:

    curl https://api.opentreeoflife.org/phylesystem/v3/trees_in_synth

response:

    {
        "contributors": [{"login": "blah", "name":"Blah D. Blah"},...]
        "creator": {"login": "", "name": ""},
        "decisions": [{
            "SHA": "",
            "comments": "",
            "decision": "INCLUDED",
            "name": "Bayesian 18S Chlorophyceae (S. Watanabe, 2016)",
            "studyID": "ot_752",
            "treeID": "tree1"
            }, ...]
        "description": "",
        "name": "",
        "queries": [],
        "url": ""
    }

#### append at tree in the default synth collection: `v{#}/include_tree_in_synth`
Takes `tree_id` and `study_id` IDs.  If the tree is not included in any of the collections
that are currently used in the Open Tree of Life's synthesis procedure.
Returns the result of a `trees_in_synth`.

`auth_info` is required.

#### Remove a tree in the default synth collection: `v{#}/exclude_tree_in_synth`
Takes `tree_id` and `study_id` IDs.  Removes any occurrence of that study+tree pair
from a collection that is currently used by the Open Tree of Life's synthesis procedure.
Returns the result of a `trees_in_synth`.

`auth_info` is required.

## Authors

Jonathan "Duke" Leto wrote the previous version of this API

Jim Allman, Emily Jane McTavish, and Mark Holder wrote the current version.